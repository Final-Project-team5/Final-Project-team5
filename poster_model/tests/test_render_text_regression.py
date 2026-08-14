"""render_text 회귀 하네스 — Typography v2(B) 착수 전 기준선.

## 무엇을 고정하는가

**production 소스를 스냅샷으로 복사하지 않는다.** 대신 현재 `render_text()`의
**출력**을 케이스별 digest로 고정한다. 구현이 바뀌어도 결과가 같으면 통과다.

    tests/_golden/render_text.json      케이스별 digest + 구조 지표 + 환경 지문

digest는 최종 RGB 바이트의 sha256이다. 이미지 자체는 저장하지 않는다
(270케이스 × 3072x1024를 저장할 이유가 없다).

digest만 있으면 "달라졌다"만 알 수 있으므로, **무엇이 달라졌는지** 좁힐 수
있도록 구조 지표를 함께 남긴다.

    size            출력 크기
    ink_bbox        배경과 다른 픽셀의 bbox (문구가 그려진 실제 범위)
    ink_px          그 픽셀 수
    meta            render_text(return_meta=True)의 주요 필드

## 환경 지문을 먼저 검사하는 이유

golden digest는 Pillow/RAQM/폰트 파일이 바뀌면 당연히 달라진다. 그걸 코드
회귀로 오해하지 않도록, 환경이 다르면 **회귀 실패가 아니라 "기준선 재생성
필요"로 구분해서** 보고한다.

## letter_spacing 케이스

B 이전인 지금은 `render_text`에 `letter_spacing` 인자가 없다. 하네스는
시그니처를 보고 **있을 때만** 아래를 추가로 검사한다.

    letter_spacing 미지정  → golden과 pixel diff 0
    letter_spacing = 0     → golden과 pixel diff 0

즉 이 파일은 B 전후에 **그대로** 쓰인다. B 구현 후 자동으로 검사 항목이 늘어난다.

## 사용법

    기준선 생성 (B 착수 전에 한 번)
        PYTHONPATH="$PWD" python tests/test_render_text_regression.py --update

    회귀 확인 (B 구현 중/후에 반복)
        PYTHONPATH="$PWD" python tests/test_render_text_regression.py
"""
import argparse
import hashlib
import inspect
import json
import sys
import types
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

sys.modules.setdefault("torch", types.ModuleType("torch"))
sys.modules.setdefault("diffusers", types.ModuleType("diffusers"))

import PIL                                                    # noqa: E402
from PIL import features                                      # noqa: E402

from pipeline import config                                   # noqa: E402
from pipeline.overlay import render_text                      # noqa: E402

GOLDEN = ROOT / "tests" / "_golden" / "render_text.json"

BG = (240, 236, 230)
RATIOS = {"1:1": (1024, 1024), "3:1": (3072, 1024), "3:4": (1024, 1368)}

TEXTS = {
    "short":  ("특가", "오늘까지"),
    "normal": ("여름 한정 특가", "오늘 하루만 20% 할인"),
    "long":   ("오늘 하루만 만날 수 있는 특별 할인 이벤트",
               "매장 방문 시 즉시 적용되며 일부 품목과 행사 상품은 제외됩니다"),
}

PASS = FAIL = 0
SKIP = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))
    return bool(cond)


# ------------------------------------------------------------------ 환경 지문
def _file_fp(path):
    p = Path(path) if path else None
    if not p or not p.is_file():
        return None
    b = p.read_bytes()
    return {"name": p.name, "size": len(b),
            "sha256": hashlib.sha256(b).hexdigest()[:16]}


def font_fingerprint():
    """실제로 렌더에 쓰이는 **모든** 폰트 파일을 지문에 넣는다.

    font_id뿐 아니라 역할 폰트(FONTS)도 포함한다. resolve_font_path()는 파일이
    없으면 경고만 찍고 FONT_FALLBACK_ROLE로 조용히 대체하므로, 자산 유무에 따라
    같은 요청이 다른 폰트로 그려질 수 있다. 그 차이를 코드 회귀로 오해하지
    않으려면 **해석된 경로**를 기록해야 한다.
    """
    out = {"font_ids": {}, "roles": {}}
    for fid in sorted(config.FONT_IDS):
        out["font_ids"][fid] = _file_fp(config.FONT_IDS[fid])
    for role in sorted(config.FONTS):
        try:
            out["roles"][role] = _file_fp(config.resolve_font_path(role))
        except FileNotFoundError:
            out["roles"][role] = None
    return out


def env_fingerprint():
    return {
        "pillow": PIL.__version__,
        "raqm": bool(features.check("raqm")),
        "freetype": features.version("freetype2"),
        "fonts": font_fingerprint(),
        # 렌더 결과에 직접 영향을 주는 상수만 남긴다
        "consts": {k: getattr(config, k) for k in
                   ("TEXT_MARGIN_RATIO", "LINE_GAP_RATIO", "HEADLINE_RATIO",
                    "SUB_RATIO", "STROKE_WIDTH", "BAR_ALPHA", "BAR_RADIUS")},
    }


# ------------------------------------------------------------------ 케이스
def available_font_ids():
    return [f for f in sorted(config.FONT_IDS)
            if Path(config.FONT_IDS[f]).is_file()]


def build_cases():
    """(key, kwargs) 목록. kwargs는 render_text에 그대로 넘긴다."""
    cases = []
    fonts = available_font_ids()

    # --- 그룹 A: 주 조합 (5폰트 × 3비율 × 3정렬 × 2스타일 × 3길이) ---------
    for fid in fonts:
        for rk, wh in RATIOS.items():
            for align, x in (("left", 0.08), ("center", 0.5), ("right", 0.92)):
                for style in ("plain", "bar"):
                    for lk, (head, sub) in TEXTS.items():
                        cases.append((
                            f"A|{fid}|{rk}|{align}|{style}|{lk}",
                            {"wh": wh, "headline": head, "sub": sub,
                             "x": x, "y": 0.42, "align": align, "style": style,
                             "headline_size": 0.10, "sub_size": 0.045,
                             "auto_fit": False, "font_id": fid}))

    # --- 그룹 B: 기존 동작 경로 (조합 폭발 없이 경로만 확실히) -------------
    base = {"wh": RATIOS["1:1"], "headline": "여름 한정 특가",
            "sub": "오늘 하루만 20% 할인", "font_id": fonts[0] if fonts else None}

    def add(name, **kw):
        cases.append((f"B|{name}", {**base, **kw}))

    # 프리셋 모드 (x/y 없음) — 좌표 모드와 별개 경로
    for pos in ("top", "center", "bottom"):
        add(f"preset-{pos}-plain", position=pos, style="plain", auto_fit=False)
        add(f"preset-{pos}-bar", position=pos, style="bar", auto_fit=False)
    # 프리셋 + align
    for align in ("left", "center", "right"):
        add(f"preset-align-{align}", position="top", align=align,
            style="plain", auto_fit=False)

    # auto_fit (shrink-only) — 넘치는 크기를 주어 실제로 축소되게 한다
    add("autofit-shrink", x=0.5, y=0.5, align="center", style="plain",
        headline_size=0.30, sub_size=0.12, auto_fit=True)
    add("autofit-noshrink", x=0.5, y=0.5, align="center", style="plain",
        headline_size=0.06, sub_size=0.03, auto_fit=True)
    add("autofit-maxheight", x=0.5, y=0.5, align="center", style="plain",
        headline_size=0.25, sub_size=0.10, auto_fit=True,
        max_height_ratio=0.18)
    add("autofit-minscale", x=0.5, y=0.5, align="center", style="plain",
        headline_size=0.40, sub_size=0.16, auto_fit=True, min_font_scale=0.7)

    # stroke / fill
    add("stroke-0", x=0.5, y=0.5, align="center", style="plain",
        auto_fit=False, stroke_width=0)
    add("stroke-8", x=0.5, y=0.5, align="center", style="plain",
        auto_fit=False, stroke_width=8)
    add("fill-dark", x=0.5, y=0.5, align="center", style="plain",
        auto_fit=False, fill_color=(30, 28, 26, 255))

    # headline / sub 단독
    add("headline-only", sub="", x=0.5, y=0.5, align="center", style="plain",
        auto_fit=False)
    add("sub-only", headline="", x=0.5, y=0.5, align="center", style="plain",
        auto_fit=False)
    add("headline-only-bar", sub="", x=0.5, y=0.5, align="center",
        style="bar", auto_fit=False)

    # _wrap / _split_long_word 경로
    add("wrap-longword", headline="여름한정특가이벤트지금바로확인하세요초특가",
        sub="", x=0.5, y=0.5, align="center", style="plain", auto_fit=False,
        headline_size=0.16)
    add("wrap-newline", headline="여름 한정\n특가 이벤트", sub="오늘\n까지",
        x=0.5, y=0.5, align="center", style="plain", auto_fit=False)
    add("wrap-narrow-left", x=0.88, y=0.5, align="left", style="plain",
        auto_fit=False, headline_size=0.09)
    add("wrap-narrow-right", x=0.12, y=0.5, align="right", style="plain",
        auto_fit=False, headline_size=0.09)
    add("wrap-latin", headline="SUMMER SALE 50% OFF", sub="AVATAR To WA YA",
        x=0.5, y=0.5, align="center", style="plain", auto_fit=False)

    # 역할 기반 폰트 (font_id 미지정)
    add("role-default", font_id=None, x=0.5, y=0.5, align="center",
        style="plain", auto_fit=False)
    add("role-body_medium", font_id=None, headline_font_role="body_medium",
        x=0.5, y=0.5, align="center", style="plain", auto_fit=False)

    # 비정사각에서의 프리셋/좌표
    for rk in ("3:1", "3:4"):
        add(f"{rk}-preset-top", wh=RATIOS[rk], position="top", style="bar",
            auto_fit=False)
        add(f"{rk}-coord-center", wh=RATIOS[rk], x=0.5, y=0.5, align="center",
            style="plain", auto_fit=False)
    return cases


# ------------------------------------------------------------------ 실행
def render_case(kw, extra=None):
    kw = dict(kw)
    W, H = kw.pop("wh")
    img = Image.new("RGB", (W, H), BG)
    call = dict(kw)
    if extra:
        call.update(extra)
    out, meta = render_text(img, call.pop("headline"), call.pop("sub"),
                            return_meta=True, **call)
    return out, meta


def digest_of(img):
    return hashlib.sha256(img.convert("RGB").tobytes()).hexdigest()


def ink_of(img):
    a = np.array(img.convert("RGB"), np.int16)
    d = np.abs(a - np.array(BG, np.int16)).sum(2) > 12
    ys, xs = np.where(d)
    if not len(xs):
        return None, 0
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())], int(d.sum())


META_KEYS = ("coord_mode", "y_anchor", "block_top_px", "block_height_px",
             "style", "font_id", "headline_font_role", "stroke_width",
             "max_w_px", "applied_headline_px", "applied_sub_px",
             "applied_headline_ratio", "applied_sub_ratio", "auto_fit",
             "shrunk")


def record_of(img, meta):
    box, px = ink_of(img)
    return {"sha256": digest_of(img), "size": list(img.size),
            "ink_bbox": box, "ink_px": px,
            "meta": {k: meta.get(k) for k in META_KEYS}}


def supports_letter_spacing():
    return "letter_spacing" in inspect.signature(render_text).parameters


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true",
                    help="현재 결과를 기준선으로 저장한다 (B 착수 전에 1회)")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 N개만 (디버그)")
    a = ap.parse_args()

    fonts = available_font_ids()
    print("=" * 66)
    print("render_text 회귀 하네스")
    print("=" * 66)
    print(f"  Pillow {PIL.__version__}  RAQM {features.check('raqm')}  "
          f"폰트 {len(fonts)}/{len(config.FONT_IDS)}종")
    if len(fonts) < len(config.FONT_IDS):
        missing = sorted(set(config.FONT_IDS) - set(fonts))
        print(f"  ⚠ 자산 없는 font_id: {missing} — 해당 케이스는 생성되지 않는다")

    cases = build_cases()
    if a.limit:
        cases = cases[:a.limit]
    print(f"  케이스 {len(cases)}개 "
          f"(A그룹 {sum(1 for k, _ in cases if k.startswith('A|'))} / "
          f"B그룹 {sum(1 for k, _ in cases if k.startswith('B|'))})")
    print(f"  letter_spacing 인자 존재: {supports_letter_spacing()}")

    # ---------------------------------------------------------- update
    if a.update:
        recs = {}
        for i, (key, kw) in enumerate(cases, 1):
            img, meta = render_case(kw)
            recs[key] = record_of(img, meta)
            if i % 50 == 0:
                print(f"    ... {i}/{len(cases)}")
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(
            {"env": env_fingerprint(), "cases": recs},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n기준선 저장: {GOLDEN}")
        print(f"  케이스 {len(recs)}개  파일 {GOLDEN.stat().st_size / 1024:.1f}KB")
        return 0

    # ---------------------------------------------------------- verify
    if not GOLDEN.exists():
        print(f"\n기준선이 없습니다: {GOLDEN}")
        print("  먼저 --update 로 생성하세요.")
        return 2

    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))

    print("\n[0] 환경 지문")
    cur, old = env_fingerprint(), golden["env"]
    env_same = cur == old
    if not env_same:
        print("  ⚠ 환경이 기준선과 다릅니다. **코드 회귀가 아닐 수 있습니다.**")
        for k in cur:
            if cur[k] != old.get(k):
                print(f"    {k}:")
                print(f"      기준선 {old.get(k)}")
                print(f"      현재   {cur[k]}")
        print("  → 환경 차이가 의도된 것이면 --update 로 기준선을 다시 만드세요.")
    check("환경 지문 일치", env_same)

    print("\n[1] 케이스별 결과 (letter_spacing 미지정)")
    gc = golden["cases"]
    missing = [k for k, _ in cases if k not in gc]
    extra = [k for k in gc if k not in {k for k, _ in cases}]
    check("기준선과 케이스 집합 일치", not missing and not extra,
          f"기준선에 없음 {len(missing)} / 현재에 없음 {len(extra)}")

    if a.limit:
        print("  ⚠ --limit 은 디버그용입니다. 케이스 집합 검사는 무시하세요.")

    diffs = []
    for key, kw in cases:
        if key not in gc:
            continue
        img, meta = render_case(kw)
        rec = record_of(img, meta)
        g = gc[key]
        if rec["sha256"] != g["sha256"]:
            diffs.append((key, rec, g))
    check(f"pixel digest 동일 ({len(cases) - len(diffs)}/{len(cases)})",
          not diffs, f"불일치 {len(diffs)}건")
    for key, rec, g in diffs[:10]:
        print(f"      {key}")
        for f in ("size", "ink_bbox", "ink_px"):
            if rec[f] != g[f]:
                print(f"        {f}: 기준선 {g[f]} → 현재 {rec[f]}")
        for mk in META_KEYS:
            if rec["meta"][mk] != g["meta"][mk]:
                print(f"        meta.{mk}: 기준선 {g['meta'][mk]} "
                      f"→ 현재 {rec['meta'][mk]}")

    # ---------------------------------------------------- letter_spacing
    print("\n[2] letter_spacing 계약")
    global SKIP
    if not supports_letter_spacing():
        SKIP += 2
        print("  [SKIP] render_text에 letter_spacing 인자가 아직 없다 (B 이전)")
        print("  [SKIP] B 구현 후 이 절이 자동으로 활성화된다")
    else:
        for label, val in (("None", None), ("0", 0)):
            bad = []
            for key, kw in cases:
                if key not in gc:
                    continue
                img, _m = render_case(kw, {"letter_spacing": val})
                if digest_of(img) != gc[key]["sha256"]:
                    bad.append(key)
            check(f"letter_spacing={label} → 기준선과 pixel diff 0 "
                  f"({len(cases) - len(bad)}/{len(cases)})", not bad,
                  f"불일치 {len(bad)}건 {bad[:5]}")

    print("\n" + "=" * 66)
    print(f"통과 {PASS} / 실패 {FAIL}" + (f" / 보류 {SKIP}" if SKIP else ""))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

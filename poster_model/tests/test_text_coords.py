"""문구 좌표 계약 검증 (GPU·모델 불필요).

프론트와 합의한 계약:
    x  align 기준점 (left=좌변, center=중심, right=우변)
    y  **텍스트 블록의 중심** — 이전에는 블록 상단이었다
    x/y는 둘 다 있어야 좌표 모드로 동작. 하나만 주면 position 프리셋

프리셋(position) 경로는 바뀌지 않아야 하므로, 변경 전 overlay.py와 픽셀 단위로
대조한다. 좌표 모드는 의도적으로 바뀌었으므로 새 기준으로 검증한다.

실행 (프로젝트 루트에서):
    PYTHONPATH="$PWD" python tests/test_text_coords.py
"""
import contextlib
import io as _io
import sys
import types
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

sys.modules["torch"] = types.ModuleType("torch")
sys.modules["diffusers"] = types.ModuleType("diffusers")

from pipeline.overlay import render_text                      # noqa: E402

PASS, FAIL = 0, 0


@contextlib.contextmanager
def quiet():
    """폰트 fallback 경고로 출력이 묻히지 않게 한다 (테스트 가독성 목적)."""
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        yield


def check(name, ok, detail=""):
    global PASS, FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if ok:
        PASS += 1
    else:
        FAIL += 1


def canvas(w=1024, h=1024):
    return Image.new("RGB", (w, h), (235, 232, 228))


def ink_box(img):
    """배경과 다른 픽셀의 bbox. 실제로 그려진 문구 영역."""
    a = np.array(img.convert("RGB"), np.int32)
    d = np.abs(a - np.array([235, 232, 228], np.int32)).sum(2)
    ys, xs = np.where(d > 24)
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())) if len(xs) else None


print("\n[1] 좌표 모드 — y는 블록 중심")
for h in (1024, 1368, 768):
    for yv in (0.25, 0.5, 0.75):
        with quiet():
            img, meta = render_text(canvas(1024, h), "여름 한정 특가",
                                    sub="지금 만나보세요", x=0.5, y=yv,
                                    align="center", style="plain", return_meta=True)
        want = yv * h
        got = meta["block_top_px"] + meta["block_height_px"] / 2
        check(f"H={h} y={yv}: 블록 중심 = y*H",
              abs(got - want) < 2, f"실측 {got:.0f} vs 기대 {want:.0f}")
        check(f"H={h} y={yv}: meta.y_anchor=center", meta["y_anchor"] == "center")

print("\n[2] auto_fit으로 줄어도 블록 중심이 유지되는가")
with quiet():
    img_a, meta_a = render_text(
        canvas(1024, 1024), "여름 한정 특가 대방출 지금 바로 만나보세요 놓치지 마세요",
        x=0.5, y=0.5, align="center", style="plain",
        headline_size=0.30, auto_fit=True, return_meta=True)
got = meta_a["block_top_px"] + meta_a["block_height_px"] / 2
check("auto_fit 후에도 블록 중심 = y*H", abs(got - 512) < 2, f"{got:.0f}")
check("실제로 축소가 일어남",
      meta_a["applied_headline_ratio"] < 0.30,
      f"요청 0.30 → 적용 {meta_a['applied_headline_ratio']}")

print("\n[2-1] 참고 — 블록 중심과 눈에 보이는 잉크 중심의 차이 (판정 아님)")
for lab, head, sub, hs in (("한 줄", "여름 한정 특가", "", 0.16),
                           ("한 줄 + sub", "여름 한정 특가", "지금 만나보세요", 0.16),
                           ("줄바꿈 + 축소",
                            "여름 한정 특가 대방출 지금 바로 만나보세요 놓치지 마세요",
                            "", 0.30)):
    with quiet():
        im, mt = render_text(canvas(), head, sub=sub, x=0.5, y=0.5, align="center",
                             style="plain", headline_size=hs, return_meta=True)
    bb = ink_box(im)
    bc = mt["block_top_px"] + mt["block_height_px"] / 2
    ic = (bb[1] + bb[3]) / 2
    print(f"    {lab:16s} 블록중심 {bc:.0f}  잉크중심 {ic:.0f}  차이 {ic - bc:+.0f}px")
print("    폰트 ascent/descent 때문에 잉크는 줄 상자 안에서 위쪽에 치우친다.")
print("    계약은 '텍스트 박스 중심'이므로 블록 기준이 맞지만, 프론트 CSS 박스와")
print("    줄 높이 계산이 다르면 이만큼 어긋날 수 있다.")

print("\n[3] x는 align 기준점 (기존 동작 유지)")
for align, desc in (("center", "중심"), ("left", "좌변"), ("right", "우변")):
    with quiet():
        img, _ = render_text(canvas(), "테스트 문구", x=0.5, y=0.5, align=align,
                             style="plain", return_meta=True)
    b = ink_box(img)
    if align == "center":
        ok = abs((b[0] + b[2]) / 2 - 512) < 12
        got = f"중심 {(b[0]+b[2])/2:.0f}"
    elif align == "left":
        ok = abs(b[0] - 512) < 12
        got = f"좌변 {b[0]}"
    else:
        ok = abs(b[2] - 512) < 12
        got = f"우변 {b[2]}"
    check(f"align={align}: x*W가 {desc}", ok, got)

print("\n[4] x/y 중 하나만 주면 프리셋으로 폴백")
for kw in ({"x": 0.5}, {"y": 0.5}, {}):
    with quiet():
        _, meta = render_text(canvas(), "테스트", position="top", style="plain",
                              return_meta=True, **kw)
    check(f"{kw or '좌표 없음'} → coord_mode=False", meta["coord_mode"] is False)
    check(f"{kw or '좌표 없음'} → y_anchor=position", meta["y_anchor"] == "top")

print("\n[5] 프리셋 경로 회귀 — 변경 전 코드와 픽셀 diff")
sys.path.insert(0, "/tmp/oldpkg")
try:
    from oldoverlay.overlay import render_text as old_render
except Exception as e:
    print(f"  (변경 전 사본을 찾지 못해 건너뜀: {e})")
    old_render = None

if old_render:
    cases = [
        dict(headline="여름 한정 특가", position="top", align="left", style="bar"),
        dict(headline="여름 한정 특가", position="center", align="center", style="plain"),
        dict(headline="여름 한정 특가", position="bottom", align="right", style="bar"),
        dict(headline="여름 한정 특가", sub="지금 만나보세요", position="center",
             align="center", style="plain"),
        dict(headline="아주 긴 문구를 넣어 자동 축소가 일어나게 만드는 테스트 문장입니다",
             position="bottom", align="left", style="plain", headline_size=0.28),
    ]
    for i, kw in enumerate(cases, 1):
        with quiet():
            a = old_render(canvas(), **kw)
            b = render_text(canvas(), **kw)
        diff = int(np.abs(np.array(a, np.int32) - np.array(b, np.int32)).max())
        check(f"프리셋 케이스 {i} ({kw['position']}/{kw['align']}/{kw['style']}) diff=0",
              diff == 0, f"max diff={diff}")

    print("\n[6] 좌표 모드는 의도적으로 달라졌는가")
    kw = dict(headline="여름 한정 특가", x=0.5, y=0.3, align="center", style="plain")
    with quiet():
        a = old_render(canvas(), **kw)
        b, mb = render_text(canvas(), return_meta=True, **kw)
    want = 0.3 * 1024
    # 변경 전: y*H가 블록 상단이었다 → 첫 줄 잉크가 그 부근에서 시작
    check("변경 전은 y*H 부근에서 문구가 시작", abs(ink_box(a)[1] - want) < 16,
          f"잉크 상단 {ink_box(a)[1]} vs y*H {want:.0f}")
    # 변경 후: 블록 중심이 정확히 y*H (잉크 중심은 폰트 metric 때문에 조금 위)
    got = mb["block_top_px"] + mb["block_height_px"] / 2
    check("변경 후는 블록 중심이 y*H", abs(got - want) < 2,
          f"블록 중심 {got:.0f} vs y*H {want:.0f}")
    check("두 결과가 실제로 다름",
          int(np.abs(np.array(a, np.int32) - np.array(b, np.int32)).max()) > 0)

print("\n" + "=" * 60)
print(f"통과 {PASS} / 실패 {FAIL}")
sys.exit(1 if FAIL else 0)

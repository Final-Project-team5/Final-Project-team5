"""letter_spacing 계약 검증 (GPU·rembg 불필요).

legacy 회귀(None/0 → pixel diff 0)는 test_render_text_regression.py가 golden으로
확인한다. 이 파일은 **자간이 켜졌을 때의 계약**만 본다.

    분기        None / 0 / 음수 → legacy,  양수 → per-glyph
    단위        font size 대비 비율. 반올림 없음
    폭 공유     wrap / align / bar / 렌더가 같은 _text_width를 쓴다
    커닝        문맥 advance로 쌍 커닝을 유지하고 자간만 얹는다
    외곽선      자간 경로에서도 겹침으로 짙어지지 않는다
"""
import sys
import types
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

sys.modules.setdefault("torch", types.ModuleType("torch"))
sys.modules.setdefault("diffusers", types.ModuleType("diffusers"))

from pipeline import config, overlay                          # noqa: E402
from pipeline.overlay import (_advances, _glyph_offsets, _spacing_px,
                              _text_width, _use_spacing, render_text)  # noqa: E402

PASS = FAIL = 0
BG = (240, 236, 230)


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))
    return bool(cond)


FONTS = [f for f in sorted(config.FONT_IDS)
         if Path(config.FONT_IDS[f]).is_file()]
SCRATCH = ImageDraw.Draw(Image.new("RGBA", (8, 8)))


def font_of(fid, px):
    return ImageFont.truetype(str(config.FONT_IDS[fid]), px)


def render(**kw):
    W, H = kw.pop("wh", (1024, 1024))
    img = Image.new("RGB", (W, H), BG)
    head = kw.pop("headline", "여름 한정 특가")
    sub = kw.pop("sub", "오늘 하루만 20% 할인")
    return render_text(img, head, sub, return_meta=True, **kw)


def ink(img):
    a = np.array(img.convert("RGB"), np.int16)
    d = np.abs(a - np.array(BG, np.int16)).sum(2) > 12
    ys, xs = np.where(d)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


print("=" * 62)
print("letter_spacing 계약")
print("=" * 62)
print(f"  폰트 {len(FONTS)}종: {FONTS}")

# ------------------------------------------------------------------ [1]
print("\n[1] 분기 판정 — 한 곳에서만")
for v in (None, 0, 0.0, -0.0, -0.01, -1):
    check(f"_use_spacing({v!r}) → False", _use_spacing(v) is False)
for v in (0.001, 0.02, 1.0):
    check(f"_use_spacing({v!r}) → True", _use_spacing(v) is True)

# ------------------------------------------------------------------ [2]
print("\n[2] 단위 — font size 대비 비율, 반올림 없음")
check("_spacing_px(100, 0.02) == 2.0", _spacing_px(100, 0.02) == 2.0)
check("_spacing_px(37, 0.015) 반올림 안 함",
      abs(_spacing_px(37, 0.015) - 0.555) < 1e-9, f"{_spacing_px(37, 0.015)}")
check("OFF면 0.0", _spacing_px(100, None) == 0.0 and _spacing_px(100, 0) == 0.0)
check("headline/sub가 각자 크기로 계산",
      _spacing_px(120, 0.02) != _spacing_px(50, 0.02))

# ------------------------------------------------------------------ [3]
print("\n[3] 폭 계산 — sp<=0이면 draw.textlength와 동일")
TEXTS = ["여름 한정 특가", "SUMMER SALE", "AVATAR", "To WA YA", "특가", "A"]
same = diff = 0
for fid in FONTS:
    for px in (40, 100, 220):
        f = font_of(fid, px)
        for t in TEXTS:
            base = SCRATCH.textlength(t, font=f)
            for sp in (0.0, -1.0):
                if _text_width(SCRATCH, t, f, sp) == base:
                    same += 1
                else:
                    diff += 1
            exp = base + 3.5 * (len(t) - 1)
            if abs(_text_width(SCRATCH, t, f, 3.5) - exp) < 1e-9:
                same += 1
            else:
                diff += 1
check(f"sp<=0은 textlength와 정확히 동일 / sp>0은 base + sp*(n-1) ({same}건)",
      diff == 0, f"불일치 {diff}건")
check("빈 문자열은 0.0", _text_width(SCRATCH, "", font_of(FONTS[0], 40), 5.0) == 0.0)

# ------------------------------------------------------------------ [4]
print("\n[4] 문맥 advance — 폭과 위치가 같은 값을 공유")
worst = 0.0
for fid in FONTS:
    for px in (40, 100, 220):
        f = font_of(fid, px)
        for t in TEXTS:
            r = abs(sum(_advances(SCRATCH, t, f)) - SCRATCH.textlength(t, font=f))
            worst = max(worst, r)
check("sum(문맥 advance) == whole-string 폭 (잔차 < 0.01px)", worst < 0.01,
      f"최대 잔차 {worst:.6f}px")

print("\n     커닝 유지 — 자간을 빼면 sp=0 위치와 같아야 한다")
bad = 0
for fid in FONTS:
    f = font_of(fid, 100)
    for t in ("AVATAR", "To WA YA", "SUMMER SALE"):
        base = _glyph_offsets(SCRATCH, t, f, 0.0)
        for sp in (1.0, 4.0, 12.0):
            got = _glyph_offsets(SCRATCH, t, f, sp)
            if max(abs((g - sp * i) - b) for i, (g, b) in
                   enumerate(zip(got, base))) > 1e-6:
                bad += 1
check("자간>0에서도 커닝 위치가 그대로", bad == 0, f"어긋남 {bad}건")

print("\n     naive 누적 대비 — 유지되는 커닝 양 (라틴)")
for fid in FONTS:
    f = font_of(fid, 100)
    t = "AVATAR"
    ctx = _glyph_offsets(SCRATCH, t, f, 0.0)
    naive = np.cumsum([0.0] + [SCRATCH.textlength(c, font=f) for c in t][:-1])
    print(f"      {fid:14s} naive였다면 잃었을 커닝 "
          f"{max(abs(a - b) for a, b in zip(ctx, naive)):6.2f}px")

# ------------------------------------------------------------------ [5]
print("\n[5] 렌더 — 자간이 실제로 반영되는가")
for fid in FONTS[:3]:
    prev_w = None
    for ls in (None, 0.01, 0.04):
        img, _m = render(x=0.5, y=0.5, align="center", style="plain",
                         auto_fit=False, headline_size=0.09, sub_size=0.04,
                         font_id=fid, letter_spacing=ls)
        b = ink(img)
        w = b[2] - b[0]
        if prev_w is not None:
            check(f"{fid}: ls={ls} 잉크 폭 증가", w > prev_w, f"{prev_w} → {w}")
        prev_w = w

print("\n     align 기준점 유지")
for align, x in (("left", 0.08), ("center", 0.5), ("right", 0.92)):
    boxes = []
    for ls in (None, 0.05):
        img, _m = render(x=x, y=0.5, align=align, style="plain",
                         auto_fit=False, headline_size=0.09, sub_size=0.04,
                         sub="", font_id=FONTS[0], letter_spacing=ls)
        boxes.append(ink(img))
    a, b = boxes
    if align == "left":
        ok, d = abs(a[0] - b[0]) <= 3, abs(a[0] - b[0])
    elif align == "right":
        ok, d = abs(a[2] - b[2]) <= 3, abs(a[2] - b[2])
    else:
        ok, d = abs((a[0] + a[2]) / 2 - (b[0] + b[2]) / 2) <= 3, \
            abs((a[0] + a[2]) / 2 - (b[0] + b[2]) / 2)
    check(f"align={align}: 자간을 켜도 기준점 유지 (≤3px)", ok, f"차이 {d:.1f}px")

print("\n     wrap이 자간을 반영 — _wrap 직접 검사")
long_head = "오늘 하루만 만날 수 있는 특별 할인 이벤트를 지금 바로 확인하세요"
f = font_of(FONTS[0], 72)
MAXW = 700
counts = []
for sp in (0.0, 2.0, 6.0, 14.0):
    lines = overlay._wrap(SCRATCH, long_head, f, MAXW, sp)
    counts.append(len(lines))
    # 모든 줄이 자간 포함 폭으로도 max_width 안에 있어야 한다
    over = [t for t in lines if _text_width(SCRATCH, t, f, sp) > MAXW]
    check(f"sp={sp}: 모든 줄이 max_width 이내", not over, f"초과 {len(over)}줄")
check(f"자간이 커지면 줄 수가 늘어난다 {counts}",
      counts[-1] > counts[0] and counts == sorted(counts))

# 렌더 경로에서도 줄 수가 실제로 바뀌는지 (블록 높이로 확인).
# 폭이 넉넉하면 자간을 조금 늘려도 줄 수가 그대로일 수 있다 — 그건 정상이다.
# 여기서는 재줄바꿈이 실제로 일어나는 조건(좁은 폭 + 넓은 자간 범위)에서 본다.
heights = []
for ls in (None, 0.05, 0.10, 0.20):
    _im, m = render(x=0.35, y=0.5, align="left", style="plain", auto_fit=False,
                    headline=long_head, sub="", headline_size=0.07,
                    font_id=FONTS[0], letter_spacing=ls)
    heights.append(m["block_height_px"])
check(f"렌더에서도 자간이 줄 수를 바꾼다 {heights}",
      heights[-1] > heights[0] and heights == sorted(heights))

print("\n     bar 폭이 자간을 반영")
w0 = w1 = None
for ls in (None, 0.06):
    img, _m = render(x=0.5, y=0.5, align="center", style="bar", auto_fit=False,
                     headline_size=0.09, sub_size=0.04, font_id=FONTS[0],
                     letter_spacing=ls)
    b = ink(img)
    if w0 is None:
        w0 = b[2] - b[0]
    else:
        w1 = b[2] - b[0]
check("bar 잉크 폭이 자간만큼 넓어짐", w1 > w0, f"{w0} → {w1}")

# ------------------------------------------------------------------ [6]
print("\n[6] 외곽선 — 자간 경로에서 이음매가 짙어지지 않는다")


def darkest(img):
    return int(np.array(img.convert("RGB"), np.int32).sum(2).min())


for fid in FONTS[:3]:
    off, _m = render(x=0.5, y=0.5, align="center", style="plain",
                     auto_fit=False, headline_size=0.10, sub_size=0.045,
                     font_id=fid, letter_spacing=None)
    on, _m = render(x=0.5, y=0.5, align="center", style="plain",
                    auto_fit=False, headline_size=0.10, sub_size=0.045,
                    font_id=fid, letter_spacing=0.02)
    check(f"{fid}: 가장 어두운 픽셀이 legacy와 같다",
          darkest(on) == darkest(off), f"OFF {darkest(off)} / ON {darkest(on)}")

# 두꺼운 stroke에서도 (겹침이 실제로 생기는 조건)
for st in (8, 16):
    off, _m = render(x=0.5, y=0.5, align="center", style="plain",
                     auto_fit=False, headline_size=0.10, sub_size=0.045,
                     font_id=FONTS[0], stroke_width=st, letter_spacing=None)
    on, _m = render(x=0.5, y=0.5, align="center", style="plain",
                    auto_fit=False, headline_size=0.10, sub_size=0.045,
                    font_id=FONTS[0], stroke_width=st, letter_spacing=0.01)
    check(f"stroke={st}px에서도 농도 동일",
          darkest(on) == darkest(off), f"OFF {darkest(off)} / ON {darkest(on)}")

# ------------------------------------------------------------------ [7]
print("\n[7] 기타 계약")
_img, m = render(x=0.5, y=0.5, align="center", style="plain", auto_fit=False,
                 font_id=FONTS[0], letter_spacing=0.03)
check("meta에 letter_spacing echo", m.get("letter_spacing") == 0.03)
_img, m = render(x=0.5, y=0.5, align="center", style="plain", auto_fit=False,
                 font_id=FONTS[0])
check("미지정이면 meta에 None", m.get("letter_spacing") is None)

# 프리셋 모드에서도 동작
for pos in ("top", "center", "bottom"):
    img, _m = render(position=pos, style="bar", auto_fit=False,
                     font_id=FONTS[0], letter_spacing=0.04)
    check(f"프리셋 {pos}에서도 자간 렌더 성공", ink(img) is not None)

# auto_fit과 함께
img, m = render(x=0.5, y=0.5, align="center", style="plain", auto_fit=True,
                headline_size=0.30, sub_size=0.12, font_id=FONTS[0],
                letter_spacing=0.04)
check("auto_fit + 자간에서 축소가 일어난다", m["shrunk"] is True)
check("auto_fit 결과가 캔버스 안", ink(img)[2] < 1024 and ink(img)[3] < 1024)

# 음수는 0과 같이 취급 (legacy)
a, _m = render(x=0.5, y=0.5, align="center", style="plain", auto_fit=False,
               font_id=FONTS[0], letter_spacing=None)
b, _m = render(x=0.5, y=0.5, align="center", style="plain", auto_fit=False,
               font_id=FONTS[0], letter_spacing=-0.05)
check("음수 자간은 legacy와 픽셀 동일 (아직 미지원)",
      np.array_equal(np.array(a), np.array(b)))

print("\n" + "=" * 62)
print(f"통과 {PASS} / 실패 {FAIL}")
sys.exit(1 if FAIL else 0)

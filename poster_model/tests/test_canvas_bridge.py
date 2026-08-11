"""W×H 캔버스 브리지 검증 (GPU·rembg·모델 불필요).

A1에서 도입한 두 가지를 확인한다.

    1) render_flat_background()의 축별 정규화
       이전에는 두 축을 모두 size-1로 나눠 정사각에서만 성립했다.
    2) place_product_on_canvas()의 항등 경로와 순수 변환

배치 정책(어디에 얼마나 크게)은 이 함수들의 책임이 아니므로 검증하지 않는다.
마스크는 rembg 없이 직접 만든다(제품 2덩어리 = 그림자 연결요소 2개).

실행 (프로젝트 루트에서):
    PYTHONPATH="$PWD" python tests/test_canvas_bridge.py
"""
import sys
import types
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# pipeline/__init__.py가 generate.py를 거쳐 torch를 끌어오므로 스텁으로 막는다.
sys.modules["torch"] = types.ModuleType("torch")
sys.modules["diffusers"] = types.ModuleType("diffusers")

from pipeline.masking import (MaskResult, add_ground_shadow,  # noqa: E402
                              composite_product, place_product_on_canvas,
                              render_flat_background)

PASS, FAIL = 0, 0


def check(name, ok, detail=""):
    global PASS, FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if ok:
        PASS += 1
    else:
        FAIL += 1


def synth(size=1024):
    """제품 2덩어리 합성 소스."""
    m = np.zeros((size, size), np.uint8)
    m[int(size * .29):int(size * .74), int(size * .32):int(size * .51)] = 255
    m[int(size * .47):int(size * .72), int(size * .55):int(size * .66)] = 255
    rgb = np.full((size, size, 3), 120, np.uint8)
    rgb[m > 0] = (210, 90, 70)
    return Image.fromarray(rgb), MaskResult(Image.fromarray(m),
                                            Image.fromarray(255 - m),
                                            float((m > 0).mean()))


def bbox(arr):
    ys, xs = np.where(arr > 128)
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())) if len(xs) else None


print("\n[1] render_flat_background — 축별 정규화")
for w, h in ((1024, 1024), (3072, 1024), (1024, 1368)):
    for d in ("vertical", "horizontal", "diagonal"):
        g = np.array(render_flat_background((w, h), ["#000000", "#FFFFFF"], d),
                     dtype=np.int32)[:, :, 0]
        # 그라데이션은 시작 0, 끝 255에 도달해야 한다. 축을 잘못 나누면 한쪽이
        # 1.0에 못 미치거나(정사각 외) 범위를 넘어 잘린다.
        ends_ok = g.min() == 0 and g.max() == 255
        if d == "vertical":
            mono = np.all(np.diff(g[:, 0]) >= 0) and np.all(g[0] == g[0][0])
        elif d == "horizontal":
            mono = np.all(np.diff(g[0]) >= 0) and np.all(g[:, 0] == g[0][0])
        else:
            mono = g[0, 0] == 0 and g[h - 1, w - 1] == 255
        check(f"{w}x{h} {d}", ends_ok and mono, f"min={g.min()} max={g.max()}")

check("solid는 크기만 따름",
      render_flat_background((3072, 1024), ["#F2E9DC"]).size == (3072, 1024))

print("\n[2] place_product_on_canvas — 항등 경로")
# 보장해야 하는 것은 픽셀 동일성이다. 객체까지 같으면 호출자가 in-place로
# 수정할 때 소스가 오염되므로, 오히려 별도 객체여야 한다.
base, masks = synth(1024)


def same_px(a, b):
    return np.array_equal(np.array(a), np.array(b))


for label, args in (("int 캔버스", (1024,)),
                    ("(W,H) 캔버스", ((1024, 1024),)),
                    ("scale=1.0 명시", (1024,))):
    b, m = place_product_on_canvas(base, masks, *args)
    check(f"{label}: base 픽셀 동일", same_px(b, base))
    check(f"{label}: product mask 픽셀 동일", same_px(m.product, masks.product))
    check(f"{label}: inpaint mask 픽셀 동일", same_px(m.inpaint, masks.inpaint))
    check(f"{label}: area_ratio 동일", m.area_ratio == masks.area_ratio)
    check(f"{label}: 소스와 별도 객체",
          b is not base and m.product is not masks.product
          and m.inpaint is not masks.inpaint)

# 반환값을 망가뜨려도 소스는 그대로여야 한다.
b, m = place_product_on_canvas(base, masks, 1024)
before = np.array(base).copy()
b.paste(Image.new("RGB", (200, 200), (255, 0, 0)), (0, 0))
m.product.paste(Image.new("L", (200, 200), 255), (0, 0))
check("반환값 수정이 소스 base에 영향 없음", np.array_equal(np.array(base), before))
check("반환값 수정이 소스 mask에 영향 없음",
      np.array(masks.product)[0, 0] == 0)

print("\n[3] place_product_on_canvas — 순수 변환")
for label, cwh, kw in (("3:1 위치 지정", (3072, 1024), {"x_px": 1900, "y_px": 300}),
                       ("3:1 위치 유지", (3072, 1024), {}),
                       ("3:4 확대", (1024, 1368), {"scale": 1.25, "x_px": 200, "y_px": 400})):
    b, m = place_product_on_canvas(base, masks, cwh, **kw)
    W, H = cwh
    check(f"{label}: base/mask 크기 일치",
          b.size == m.product.size == m.inpaint.size == (W, H), f"{b.size}")
    bb = bbox(np.array(m.product.convert("L")))
    check(f"{label}: 제품이 캔버스 안",
          bool(bb and bb[0] > 0 and bb[1] > 0 and bb[2] < W - 1 and bb[3] < H - 1), f"bbox={bb}")
    if "x_px" in kw:
        check(f"{label}: 지정 좌표에 배치", bb[0] == kw["x_px"] and bb[1] == kw["y_px"])
    flat = render_flat_background(cwh, ["#F2E9DC"])
    shadowed = add_ground_shadow(flat, m.product)
    out = composite_product(b, shadowed, m.product)
    check(f"{label}: 합성 결과 크기", out.size == (W, H))
    sd = np.abs(np.array(shadowed, np.int32) - np.array(flat, np.int32)).sum(2)
    sy, sx = np.where(sd > 0)
    check(f"{label}: 그림자가 캔버스 안",
          len(sx) > 0 and sx.min() > 0 and sy.min() > 0
          and sx.max() < W - 1 and sy.max() < H - 1)

print("\n[4] 배율 유지 및 이탈 방어")
b, m = place_product_on_canvas(base, masks, (1024, 1368), scale=1.25, x_px=200, y_px=400)
sb, nb = bbox(np.array(masks.product.convert("L"))), bbox(np.array(m.product.convert("L")))
sr = (sb[2] - sb[0] + 1) / (sb[3] - sb[1] + 1)
nr = (nb[2] - nb[0] + 1) / (nb[3] - nb[1] + 1)
check("종횡비 유지", abs(sr - nr) < 0.01, f"{sr:.4f} → {nr:.4f}")
check("배율 반영", abs((nb[2] - nb[0] + 1) / (sb[2] - sb[0] + 1) - 1.25) < 0.02)

for label, kw in (("과대 배율", {"scale": 3.0}), ("음수 좌표", {"x_px": -50}),
                  ("오른쪽 이탈", {"x_px": 900})):
    try:
        place_product_on_canvas(base, masks, (1024, 1024), **kw)
        check(f"{label} → ValueError", False)
    except ValueError:
        check(f"{label} → ValueError", True)

try:
    empty = MaskResult(Image.new("L", (1024, 1024), 0),
                       Image.new("L", (1024, 1024), 255), 0.0)
    place_product_on_canvas(base, empty, (3072, 1024))
    check("빈 마스크 → ValueError", False)
except ValueError:
    check("빈 마스크 → ValueError", True)

print("\n" + "=" * 60)
print(f"통과 {PASS} / 실패 {FAIL}")
sys.exit(1 if FAIL else 0)

"""비율별 기본 제품 배치 검증 (A2-2, GPU·rembg·모델 불필요).

확인 대상:
    1) 1:1은 항등 배치라 기존 결과가 픽셀 단위로 보존된다
    2) 3:1 / 3:4에서 제품과 그림자가 잘리지 않는다 (추정이 아니라 실측)
    3) blur margin 적용 여부와 무관하게 최종 제품 크기 기준이 같다
    4) 클라이언트 override가 안전 영역을 벗어나면 서버가 막는다

마스크는 rembg 없이 직접 만든다(제품 2덩어리 = 그림자 연결요소 2개).

실행 (프로젝트 루트에서):
    PYTHONPATH="$PWD" python tests/test_placement.py
"""
import sys
import types
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

sys.modules["torch"] = types.ModuleType("torch")
sys.modules["diffusers"] = types.ModuleType("diffusers")

from pipeline import config, layout                              # noqa: E402
from pipeline.masking import (MaskResult, add_ground_shadow,     # noqa: E402
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


def synth(size=1024, shrink=1.0):
    """제품 2덩어리. shrink<1은 add_blur_margin이 축소한 상태를 흉내낸다."""
    m = np.zeros((size, size), np.uint8)
    c = size / 2
    for x0, y0, x1, y1 in ((330, 300, 520, 760), (560, 480, 680, 740)):
        sx0, sx1 = int(c + (x0 - c) * shrink), int(c + (x1 - c) * shrink)
        sy0, sy1 = int(c + (y0 - c) * shrink), int(c + (y1 - c) * shrink)
        m[sy0:sy1, sx0:sx1] = 255
    rgb = np.full((size, size, 3), 120, np.uint8)
    rgb[m > 0] = (210, 90, 70)
    return Image.fromarray(rgb), MaskResult(Image.fromarray(m),
                                            Image.fromarray(255 - m),
                                            float((m > 0).mean()))


def render(base, masks, canvas, place, colors=("#F2E9DC",), direction=None):
    b, m = place_product_on_canvas(base, masks, canvas, **place.as_kwargs())
    flat = render_flat_background(canvas, list(colors), direction)
    shadowed = add_ground_shadow(flat, m.product)
    return composite_product(b, shadowed, m.product), flat, shadowed, m


def ink_box(a, b):
    """두 이미지의 차이가 있는 영역 bbox (그림자 실측용)."""
    d = np.abs(np.array(a, np.int32) - np.array(b, np.int32)).sum(2)
    ys, xs = np.where(d > 0)
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())) if len(xs) else None


print("\n[1] plan_canvas — 캔버스와 blur margin 적용 여부")
for ratio, short, want, margin in ((None, 1024, (1024, 1024), True),
                                   ("1:1", 1024, (1024, 1024), True),
                                   ("3:1", 1024, (3072, 1024), False),
                                   ("3:4", 1024, (1024, 1368), False),
                                   (None, 768, (768, 768), True),
                                   ("3:1", 768, (2304, 768), False),
                                   ("3:4", 768, (768, 1024), False)):
    canvas, use_margin = layout.plan_canvas(ratio, short)
    check(f"{ratio} @{short} → {want}, margin={margin}",
          canvas == want and use_margin is margin, f"{canvas}, margin={use_margin}")

print("\n[2] 1:1 — 항등 배치, 기존 결과 보존")
base, masks = synth(1024)
p = layout.compute_placement(masks, (1024, 1024), None)
check("1:1은 identity", p.source == "identity" and p.scale == 1.0
      and p.x_px is None and p.y_px is None and p.region is None)
for label, colors, d in (("solid", ["#F2E9DC"], None),
                         ("gradient", ["#F2E9DC", "#8C7B6B"], "vertical")):
    out, _, _, _ = render(base, masks, (1024, 1024), p, colors, d)
    # 배치를 거치지 않은 직접 렌더와 픽셀 단위로 같아야 한다.
    flat = render_flat_background((1024, 1024), colors, d)
    direct = composite_product(base, add_ground_shadow(flat, masks.product), masks.product)
    diff = int(np.abs(np.array(out, np.int32) - np.array(direct, np.int32)).max())
    check(f"1:1 {label}: 직접 렌더와 pixel diff = 0", diff == 0, f"max diff={diff}")

print("\n[3] 3:1 / 3:4 — 제품·그림자 clipping 없음 (실측)")
for ratio in ("3:1", "3:4"):
    W, H = layout.resolve_output_size(ratio, 1024)
    base, masks = synth(1024)
    p = layout.compute_placement(masks, (W, H), ratio)
    v = layout.validate_placement(masks, (W, H), p, strict=False)
    check(f"{ratio}: 배치 계산됨", p.source == "auto" and p.region is not None,
          f"scale={p.scale:.3f} x={p.x_px} y={p.y_px}")
    check(f"{ratio}: 사전 검증 통과", v["ok"] and not v["region_overflow"])

    out, flat, shadowed, m = render(base, masks, (W, H), p)
    check(f"{ratio}: 캔버스 크기", out.size == (W, H))

    pb = ink_box(np.array(m.product.convert("RGB")), np.zeros((H, W, 3), np.uint8))
    check(f"{ratio}: 제품 clipping 없음",
          pb[0] > 0 and pb[1] > 0 and pb[2] < W - 1 and pb[3] < H - 1, f"bbox={pb}")

    sb = ink_box(shadowed, flat)          # 실제 렌더된 그림자 픽셀
    check(f"{ratio}: 그림자 clipping 없음",
          sb and sb[0] > 0 and sb[1] > 0 and sb[2] < W - 1 and sb[3] < H - 1, f"bbox={sb}")

    r = p.region
    check(f"{ratio}: 그림자가 제품 영역 안",
          sb[0] >= r[0] and sb[1] >= r[1] and sb[2] <= r[2] and sb[3] <= r[3],
          f"region={r}")
    # 추정 footprint가 실측을 감싸는지 (과소평가면 clipping을 놓친다)
    fp = v["footprint"]
    check(f"{ratio}: 추정 footprint ⊇ 실측", 
          fp[0] <= sb[0] and fp[1] <= sb[1] and fp[2] >= sb[2] and fp[3] >= sb[3],
          f"est={tuple(round(x) for x in fp)} 실측={sb}")

print("\n[4] blur margin 적용 여부와 무관한 배치 기준 일관성")
# 프로덕션 경로에서는 비정사각이면 blur margin을 생략하므로 두 상태가 섞이지
# 않는다. 그 보장을 먼저 확인한다.
for ratio in ("3:1", "3:4"):
    _c, use_margin = layout.plan_canvas(ratio, 1024)
    check(f"{ratio}: 비정사각은 blur margin 생략", use_margin is False)
check("1:1은 blur margin 유지", layout.plan_canvas("1:1", 1024)[1] is True)

# 그래도 배율 계산 자체가 소스 크기에 독립인지 본다. f는 현재 bbox 대비
# 상대 배율이므로, 확대 상한에 걸리지 않는 범위에서는 최종 크기가 같아야 한다.
BIG = ((250, 120, 700, 880), (720, 560, 850, 860))


def synth_big(size=1024, shrink=1.0):
    m = np.zeros((size, size), np.uint8)
    c = size / 2
    for x0, y0, x1, y1 in BIG:
        m[int(c + (y0 - c) * shrink):int(c + (y1 - c) * shrink),
          int(c + (x0 - c) * shrink):int(c + (x1 - c) * shrink)] = 255
    rgb = np.full((size, size, 3), 120, np.uint8)
    rgb[m > 0] = (210, 90, 70)
    return Image.fromarray(rgb), MaskResult(Image.fromarray(m),
                                            Image.fromarray(255 - m),
                                            float((m > 0).mean()))


for ratio in ("3:1", "3:4"):
    W, H = layout.resolve_output_size(ratio, 1024)
    sizes, scales = [], []
    for shrink in (1.0, config.MARGIN_SCALE):
        b, mk = synth_big(1024, shrink)
        pl = layout.compute_placement(mk, (W, H), ratio)
        scales.append(pl.scale)
        _, m = place_product_on_canvas(b, mk, (W, H), **pl.as_kwargs())
        a = np.array(m.product.convert("L"))
        ys, xs = np.where(a > 128)
        sizes.append((int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)))
    (w1, h1), (w2, h2) = sizes
    capped = max(scales) >= config.CANVAS_MAX_UPSCALE * config.CANVAS_SAFETY_FACTOR - 1e-6
    check(f"{ratio}: 확대 상한에 걸리지 않음", not capped,
          f"scale {scales[0]:.3f} / {scales[1]:.3f}")
    check(f"{ratio}: 최종 제품 크기 일치 (오차 < 2%)",
          abs(w1 - w2) / w1 < 0.02 and abs(h1 - h2) / h1 < 0.02,
          f"원본 {w1}x{h1} vs 축소소스 {w2}x{h2}")

print("\n[5] 클라이언트 override 검증")
W, H = layout.resolve_output_size("3:1", 1024)
base, masks = synth(1024)
auto = layout.compute_placement(masks, (W, H), "3:1")
pub = auto.as_public((W, H))
check("자동 배치의 public 형태", pub["source"] == "auto" and pub["scale_factor"] == 1.0
      and 0 <= pub["x"] <= 1 and 0 <= pub["y"] <= 1, f"{pub}")

ok = layout.compute_placement(masks, (W, H), "3:1", {"scale_factor": 0.8})
check("영역 안 override 허용", ok.source == "override"
      and layout.validate_placement(masks, (W, H), ok, strict=False)["ok"])
check("scale_factor가 내부 배율로 변환됨",
      abs(ok.scale - auto.scale * 0.8) < 1e-6, f"{ok.scale:.4f}")
check("scale_factor만 주면 좌표 재중앙정렬",
      (ok.x_px, ok.y_px) != (auto.x_px, auto.y_px))
check("재중앙정렬 결과가 영역 안",
      layout.validate_placement(masks, (W, H), ok, strict=False)["region_overflow"] is False)

# 캔버스 안이지만 제품 영역 밖 → 통과시키되 경고로 알린다
out_region = layout.compute_placement(masks, (W, H), "3:1",
                                      {"scale_factor": 0.5, "x": 0.10, "y": 0.5})
v = layout.validate_placement(masks, (W, H), out_region, strict=False)
check("영역 밖이지만 캔버스 안 → ok + region_overflow",
      v["ok"] and v["region_overflow"] and "region_overflow" in v["reasons"])

for label, ov in (("왼쪽 이탈", {"x": 0.01}),
                  ("오른쪽 이탈", {"x": 0.99}),
                  ("아래쪽 이탈", {"y": 0.99})):
    pl = layout.compute_placement(masks, (W, H), "3:1", ov)
    try:
        layout.validate_placement(masks, (W, H), pl, strict=True)
        check(f"{label} → 거부", False)
    except layout.LayoutRejection as e:
        check(f"{label} → 거부", e.payload["error"] == "placement_unsafe")

# 그림자만 잘리는 경우
comps, (bx0, by0, bx1, by1) = layout._component_stats(masks.product)
bh = by1 - by0 + 1
edge = layout.Placement(1.0, 1800, H - bh - 2, "override", None, 1.0,
                        (bx0, by0, bx1, by1))
v = layout.validate_placement(masks, (W, H), edge, strict=False)
check("제품은 안, 그림자만 이탈 → shadow_clipped",
      not v["ok"] and "shadow_clipped" in v["reasons"]
      and "product_clipped" not in v["reasons"], f"reasons={v['reasons']}")

for bad in (0, -1):
    try:
        layout.compute_placement(masks, (W, H), "3:1", {"scale_factor": bad})
        check(f"scale_factor={bad} 거부", False)
    except layout.LayoutRejection as e:
        check(f"scale_factor={bad} 거부", e.payload["error"] == "placement_invalid")

print("\n[6] 상수가 config에 분리되어 있는지")
for name in ("CANVAS_REGIONS", "CANVAS_MARGIN_RATIO",
             "CANVAS_MAX_UPSCALE", "CANVAS_SAFETY_FACTOR"):
    check(f"config.{name} 존재", hasattr(config, name))
check("3:1 초기값 0.50 / 0.55",
      config.CANVAS_REGIONS["3:1"]["text_end"] == 0.50
      and config.CANVAS_REGIONS["3:1"]["product_start"] == 0.55)
check("3:4 제품 영역 = 하단 65%",
      abs((1 - config.CANVAS_REGIONS["3:4"]["product_start"]) - 0.65) < 1e-9)
check("max_upscale=1.6 / safety=0.97",
      config.CANVAS_MAX_UPSCALE == 1.6 and config.CANVAS_SAFETY_FACTOR == 0.97)
check("1:1은 분할 규칙 없음", "1:1" not in config.CANVAS_REGIONS)

print("\n[7] 내부값 미노출 유지")
api = (ROOT / "api.py").read_text(encoding="utf-8")
# 외부 계약에 내부 좌표계·휴리스틱·상수를 노출하지 않는다.
for token in ("x_px", "y_px", "CANVAS_MAX_UPSCALE", "CANVAS_REGIONS",
              "product_region", "footprint", "_component_stats"):
    check(f"api.py에 {token} 없음", token not in api)
check("api.py는 layout 내부 함수를 직접 호출하지 않음",
      "layout." not in api and "compute_placement" not in api)

print("\n" + "=" * 60)
print(f"통과 {PASS} / 실패 {FAIL}")
sys.exit(1 if FAIL else 0)

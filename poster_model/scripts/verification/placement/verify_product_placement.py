"""제품 배치(product_placement) 실험 검증.

실험·검증용 스크립트이며 프로덕션 파이프라인에 직접 사용되지 않음.
여기 있는 place_product()는 pipeline/masking.py에 반영되어 있지 않다.

place_product()를 여기서 먼저 구현해 실제 제품 사진으로 검증한 뒤, 결과를 보고
pipeline/masking.py로 옮긴다(그 전까지 프로덕션 코드는 손대지 않는다).

설계 결정(확정된 것):
    (a) 순서: prepare_image()(add_blur_margin 포함) -> place_product()
        scale=1.0은 "전처리 완료 후 제품 bbox" 기준 배율이다.
    (b) scale 범위: 0 < scale <= 1.5. 별도 업스케일링 없이 일반 리사이즈만.
    (c) 프레임 이탈: 자동 clamp/잘라내기 없이 명시적 오류(PlacementOutOfFrame).

구현 방식(base 전체 아핀 변환을 쓰지 않는 이유):
    base 전체를 옮기면 제품뿐 아니라 원본 배경 픽셀까지 함께 이동해, 원래 제품이
    있던 자리에 배경 잔상이 남고 테두리에 원본 배경이 딸려온다. 그래서
        base + tight mask -> 제품 RGBA 레이어 추출
        -> 레이어와 마스크에 동일한 이동/크기 변환
        -> 변환된 tight mask에서 inpaint mask를 규칙 그대로 재생성(이중 블러 방지)
    순서로 처리한다.

fringe(테두리 배경 픽셀) 대응:
    composite_product()가 마스크를 COMPOSITE_BLUR(=2)로 블러해 합성하므로, 마스크
    경계 바깥 몇 px이 base에서 읽힌다. 제품 레이어만 옮기면 그 자리는 빈 캔버스라
    합성 시 캔버스 색이 얇게 배어난다. 이를 막으려고 제품 가장자리 색을 마스크
    바깥으로 몇 px 번지게(_bleed) 채운 뒤 붙인다. 마스크 자체는 넓히지 않으므로
    halo 수정 때의 "마스크를 더 키우지 말 것" 제약과 충돌하지 않는다.

실행 (GPU 불필요, rembg 가중치는 필요):
    cd poster_model
    source .venv/bin/activate
    PYTHONPATH="$PWD" python scripts/verification/placement/verify_product_placement.py

결과:
    outputs/verification/placement/placement_cosmetic_before_after.png
    outputs/verification/placement/placement_snack_before_after.png
    outputs/verification/placement/placement_verify_log.json
"""
import json
import os
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import pipeline.config as config
import pipeline.masking as masking
import pipeline.overlay as overlay

ROOT = Path(__file__).resolve().parents[3]     # scripts/verification/placement/ -> 프로젝트 루트
OUT_DIR = ROOT / "outputs" / "verification" / "placement"
OUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = OUT_DIR / "placement_verify_log.json"
SIZE = 1024
BLEED_PX = 6          # COMPOSITE_BLUR(2)보다 넉넉히
SCALE_MAX = 1.5


class PlacementOutOfFrame(ValueError):
    """제품이 프레임을 벗어날 때. 허용 범위를 함께 담는다."""

    def __init__(self, detail: dict):
        self.detail = detail
        super().__init__(json.dumps(detail, ensure_ascii=False))


def _bbox(mask: Image.Image):
    m = np.array(mask.convert("L")) > 128
    ys, xs = np.where(m)
    if len(xs) == 0:
        raise ValueError("제품 마스크가 비어 있습니다.")
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _bleed(rgb: np.ndarray, mask: np.ndarray, px: int) -> np.ndarray:
    """마스크 바깥 px 픽셀을 제품 가장자리 색으로 채운다.

    합성 시 블러된 마스크 경계에서 빈 캔버스 색이 배어나는 것을 막는 용도.
    마스크 자체는 넓히지 않고 "색만" 번지게 한다.
    """
    kernel = np.ones((3, 3), np.uint8)
    band = cv2.dilate(mask, kernel, iterations=px)
    hole = ((band > 0) & (mask == 0)).astype(np.uint8) * 255
    if hole.max() == 0:
        return rgb
    return cv2.inpaint(rgb, hole, 3, cv2.INPAINT_TELEA)


def place_product(base: Image.Image, masks, x=None, y=None, scale=None):
    """제품을 지정 위치/크기로 옮긴다. base와 마스크에 동일 변환을 적용한다.

    x, y: 제품 bbox 중심의 목표 좌표(0~1). None이면 현재 위치 유지.
    scale: 전처리 후 bbox 기준 배율. 1.0=유지. None이면 유지.

    Returns: (새 base, 새 MaskResult, meta dict)
    """
    if x is None and y is None and (scale is None or scale == 1.0):
        return base, masks, {"applied": False}

    scale = 1.0 if scale is None else float(scale)
    if not (0 < scale <= SCALE_MAX):
        raise ValueError(f"scale은 0 초과 {SCALE_MAX} 이하여야 합니다 (요청: {scale}).")

    W, H = base.size
    x0, y0, x1, y1 = _bbox(masks.product)
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    tx = cx if x is None else x * W
    ty = cy if y is None else y * H
    nbw, nbh = bw * scale, bh * scale

    # --- (c) 프레임 이탈 검사 (자동 clamp 없음) ---
    half_w, half_h = nbw / 2, nbh / 2
    ax = (round(half_w / W, 4), round(1 - half_w / W, 4))
    ay = (round(half_h / H, 4), round(1 - half_h / H, 4))
    if not (half_w <= tx <= W - half_w and half_h <= ty <= H - half_h):
        raise PlacementOutOfFrame({
            "reason": "배치된 제품 bbox가 프레임을 벗어납니다.",
            "requested_x": None if x is None else round(x, 4),
            "requested_y": None if y is None else round(y, 4),
            "requested_scale": scale,
            "allowed_x_range": list(ax),
            "allowed_y_range": list(ay),
            "scaled_product_bbox": {"w_ratio": round(nbw / W, 4),
                                    "h_ratio": round(nbh / H, 4)},
        })

    # --- 제품 RGBA 레이어 추출 (base 전체가 아니라 제품만) ---
    base_rgb = np.array(base.convert("RGB"))
    tight = (np.array(masks.product.convert("L")) > 128).astype(np.uint8) * 255
    bled = _bleed(base_rgb, tight, BLEED_PX)

    pad = BLEED_PX + 2
    cx0, cy0 = max(x0 - pad, 0), max(y0 - pad, 0)
    cx1, cy1 = min(x1 + pad + 1, W), min(y1 + pad + 1, H)
    layer_rgb = bled[cy0:cy1, cx0:cx1]
    layer_a = tight[cy0:cy1, cx0:cx1]

    if scale != 1.0:
        nw, nh = max(int(round(layer_rgb.shape[1] * scale)), 1), \
                 max(int(round(layer_rgb.shape[0] * scale)), 1)
        layer_rgb = cv2.resize(layer_rgb, (nw, nh), interpolation=cv2.INTER_LANCZOS4)
        layer_a = cv2.resize(layer_a, (nw, nh), interpolation=cv2.INTER_LINEAR)
        layer_a = (layer_a > 128).astype(np.uint8) * 255

    # 크롭 중심과 bbox 중심의 어긋남을 보정해 붙일 좌표 계산
    off_x = (cx - cx0) * scale
    off_y = (cy - cy0) * scale
    px0 = int(round(tx - off_x))
    py0 = int(round(ty - off_y))

    new_rgb = np.zeros((H, W, 3), np.uint8)
    new_mask = np.zeros((H, W), np.uint8)

    sx0, sy0 = max(-px0, 0), max(-py0, 0)
    dx0, dy0 = max(px0, 0), max(py0, 0)
    cw = min(layer_rgb.shape[1] - sx0, W - dx0)
    ch = min(layer_rgb.shape[0] - sy0, H - dy0)
    new_rgb[dy0:dy0 + ch, dx0:dx0 + cw] = layer_rgb[sy0:sy0 + ch, sx0:sx0 + cw]
    new_mask[dy0:dy0 + ch, dx0:dx0 + cw] = layer_a[sy0:sy0 + ch, sx0:sx0 + cw]

    # --- inpaint mask는 기존 규칙 그대로 "재생성"한다 (변환된 blur mask 재블러 금지) ---
    if config.DILATE > 0:
        kernel = np.ones((config.DILATE, config.DILATE), np.uint8)
        dilated = cv2.dilate(new_mask, kernel, iterations=1)
    else:
        dilated = new_mask
    new_inpaint = Image.fromarray(255 - dilated).filter(
        ImageFilter.GaussianBlur(config.MASK_BLUR))

    new_masks = masking.MaskResult(
        Image.fromarray(new_mask), new_inpaint, float((new_mask > 0).mean()))

    meta = {
        "applied": True,
        "requested": {"x": x, "y": y, "scale": scale},
        "applied_center": {"x": round(tx / W, 4), "y": round(ty / H, 4)},
        "bbox_before": {"w_ratio": round(bw / W, 4), "h_ratio": round(bh / H, 4),
                        "center_x_ratio": round(cx / W, 4), "center_y_ratio": round(cy / H, 4)},
        "bbox_after": masking.describe_product_bbox(new_masks.product),
        "final_area_ratio": round(new_masks.area_ratio, 4),
        "bleed_px": BLEED_PX,
    }
    return Image.fromarray(new_rgb), new_masks, meta


# ---------------------------------------------------------------- 검증

def render(base, masks, category, headline, sub, text_xy):
    """배경+그림자+제품+문구까지 한 장 만든다 (solid 배경, diffusion 없음)."""
    spec = masking.resolve_background("solid", None, None, category, 1)[0]
    flat = masking.render_flat_background(SIZE, spec["colors"], spec.get("direction"))
    shadowed = masking.add_ground_shadow(flat, masks.product)
    img = masking.composite_product(base, shadowed, masks.product)
    preset = config.TONE_PRESETS["minimal_product"]
    img, _ = overlay.render_text(
        img, headline, sub, x=text_xy[0], y=text_xy[1], align="left", style="plain",
        headline_size=preset["headline_size"], sub_size=preset["sub_size"],
        headline_font_role=preset["headline_font_role"],
        stroke_width=preset["stroke_width"], fill_color=preset.get("fill_color"),
        max_height_ratio=0.45, return_meta=True)
    return img, spec


def side_by_side(before, after, label_a, label_b):
    lh, gap = 34, 12
    w, h = before.size
    canvas = Image.new("RGB", (w * 2 + gap, h + lh), "white")
    d = ImageDraw.Draw(canvas)
    d.text((8, 8), label_a, fill="black")
    d.text((w + gap + 8, 8), label_b, fill="black")
    canvas.paste(before, (0, lh))
    canvas.paste(after, (w + gap, lh))
    return canvas


CASES = [
    {"name": "cosmetic", "path": "image/cosmetic.jpg", "category": "beauty",
     "placement": {"x": 0.68, "y": 0.60, "scale": 0.85},
     "headline": "매일을 위한 클린 케어", "sub": "가볍고 편안한 데일리 루틴",
     "text_xy": (0.08, 0.18)},
    {"name": "snack", "path": "image/snack.jpg", "category": "food",
     "placement": {"x": 0.70, "y": 0.62, "scale": 0.75},
     "headline": "달콤한 멜론 한입", "sub": "바삭하게 즐기는 오늘의 간식",
     "text_xy": (0.08, 0.16)},
]


def main():
    results = []
    for case in CASES:
        print(f"\n=== {case['name']} ===")
        t0 = time.time()
        base, masks, mode = masking.prepare_image(str(ROOT / case["path"]), SIZE)
        before_layout = masking.describe_product_bbox(masks.product)
        print(f"prepare_image mode={mode}, bbox={before_layout}")

        # (1) placement 미전달 = 기존 동작 그대로여야 함
        before_img, bg_spec = render(base, masks, case["category"],
                                     case["headline"], case["sub"], case["text_xy"])

        # (2) placement 적용
        p = case["placement"]
        try:
            new_base, new_masks, pmeta = place_product(base, masks, **p)
        except PlacementOutOfFrame as e:
            print(f"  프레임 이탈로 거부됨: {json.dumps(e.detail, ensure_ascii=False)}")
            results.append({"name": case["name"], "error": e.detail})
            continue

        after_img, _ = render(new_base, new_masks, case["category"],
                              case["headline"], case["sub"], case["text_xy"])

        out = OUT_DIR / f"placement_{case['name']}_before_after.png"
        side_by_side(before_img, after_img,
                     "before (placement 없음 = 기존 동작)",
                     f"after (x={p['x']} y={p['y']} scale={p['scale']})").save(out)
        print(f"  bbox_before={pmeta['bbox_before']}")
        print(f"  bbox_after ={pmeta['bbox_after']}")
        print(f"  -> {out}")

        results.append({
            "name": case["name"], "category": case["category"], "prepare_mode": mode,
            "background_used": bg_spec, "placement_meta": pmeta,
            "elapsed": round(time.time() - t0, 2), "compare_path": str(out),
        })

    # (3) 프레임 이탈이 실제로 거부되는지
    print("\n=== 프레임 이탈 거부 확인 (x=0.95) ===")
    base, masks, _ = masking.prepare_image(str(ROOT / CASES[0]["path"]), SIZE)
    try:
        place_product(base, masks, x=0.95, y=0.6, scale=1.0)
        print("  FAIL: 거부되지 않음")
    except PlacementOutOfFrame as e:
        print(f"  PASS: {json.dumps(e.detail, ensure_ascii=False)}")
        results.append({"name": "out_of_frame_check", "error": e.detail})

    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n로그: {LOG_PATH}")


if __name__ == "__main__":
    main()

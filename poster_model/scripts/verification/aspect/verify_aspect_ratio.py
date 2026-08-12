"""용도별 이미지 비율(1:1 / 3:1 / 3:4) 지원 실험 — 프로덕션 코드 변경 없음.

실험·검증용 스크립트이며 프로덕션 파이프라인에 직접 사용되지 않는다.
pipeline/masking.py의 정사각 강제 지점 3곳을 여기서만 비정사각 버전으로 다시 만들고,
나머지(make_masks / add_ground_shadow / composite_product / render_text)는 프로덕션
함수를 그대로 호출한다. 그 함수들이 비정사각에서 실제로 잘 도는지가 곧 검증 대상이다.

두 방식을 나란히 만들어 비교한다.

    A안 crop   : ImageOps.fit(img, (W, H)) 로 원본을 목표 비율에 맞춰 잘라낸다.
                 변경이 가장 작지만, 3:1에서 세로형 제품의 위아래가 잘릴 수 있다.
    B안 canvas : 정사각으로 한 번 준비해 누끼를 딴 뒤, 제품 레이어만 목표 비율
                 캔버스에 배치한다. 잘림이 없고 제품 위치/크기를 조절할 수 있다.
                 verify_product_placement.py의 place_product()와 같은 메커니즘이다.

이번 1차 실험은 solid/gradient 배경만 사용한다(AI 배경 제외). diffusion을 호출하지
않으므로 GPU도 API 서버도 필요 없고, rembg 가중치만 있으면 된다.

A/B 공정 비교를 위해 다음을 두 방식에서 동일하게 맞춘다.
    출력 해상도 / solid 배경 색상 / 문구와 좌표 / 그림자 설정 / 제품 목표 높이
    (--canvas-scale match 기본값: canvas가 crop 결과의 제품 높이를 그대로 따라간다)
따라서 두 결과의 주요 차이는 "언제 크롭하고 언제 배치하느냐" 하나로 좁혀진다.

참고: 배경은 두 방식 모두 동일하게 교체된다. composite_product()가 마스크 영역의
픽셀만 원본에서 가져오므로, crop이라고 해서 원본 사진의 배경이 남지는 않는다.

실행:
    cd poster_model
    source .venv/bin/activate
    PYTHONPATH="$PWD" python scripts/verification/aspect/verify_aspect_ratio.py

    # 제품 하나부터 확인
    PYTHONPATH="$PWD" python scripts/verification/aspect/verify_aspect_ratio.py --images snack
    PYTHONPATH="$PWD" python scripts/verification/aspect/verify_aspect_ratio.py --limit 1
    PYTHONPATH="$PWD" python scripts/verification/aspect/verify_aspect_ratio.py \
        --images snack --ratios 3:1
    # LAYOUT 고정 배치안으로 보고 싶을 때
    PYTHONPATH="$PWD" python scripts/verification/aspect/verify_aspect_ratio.py \
        --images snack --canvas-scale fixed

제품 하나가 실패해도 나머지는 계속 진행하며, 실패 내역은 run_log.json의 errors에 남는다.

결과:
    outputs/verification/aspect/crop/{name}_{ratio}.png
    outputs/verification/aspect/canvas/{name}_{ratio}.png
    outputs/verification/aspect/comparisons/{name}_compare.png     3행(비율) x 2열(방식)
    outputs/verification/aspect/run_log.json
"""
import argparse
import json
import time
import traceback
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

import pipeline.config as config
import pipeline.masking as masking
import pipeline.overlay as overlay

ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "outputs" / "verification" / "aspect"
CROP_DIR = OUT_DIR / "crop"
CANVAS_DIR = OUT_DIR / "canvas"
CMP_DIR = OUT_DIR / "comparisons"
LOG_PATH = OUT_DIR / "run_log.json"

# 짧은 변을 1024로 고정하고 비율에 따라 긴 변을 늘린다.
BASE = 1024
RATIOS = {
    "1x1": (1, 1),     # SNS 카드뉴스
    "3x1": (3, 1),     # 배너
    "3x4": (3, 4),     # 상세페이지
}

BLEED_PX = 6           # composite_product의 COMPOSITE_BLUR(2)보다 넉넉히

CASES = [
    {"name": "snack",    "path": "image/snack.jpg",    "category": "food",
     "headline": "달콤한 멜론 한입", "sub": "바삭하게 즐기는 오늘의 간식"},
    {"name": "cosmetic", "path": "image/cosmetic.jpg", "category": "beauty",
     "headline": "매일을 위한 클린 케어", "sub": "가볍고 편안한 데일리 루틴"},
    {"name": "glass",    "path": "image/glass.jpg",    "category": "goods",
     "headline": "CLEAR MOMENT", "sub": "가볍게 채우는 깨끗한 한 잔"},
    {"name": "cake",     "path": "image/cake.jpg",     "category": "food",
     "headline": "진하고 부드러운 티라미수", "sub": "오늘 하루만 20% 할인"},
]

# 비율별 제품 배치(canvas 방식 전용)와 문구 좌표.
# 자동 계산이 아니라 실험용 고정값이다 — 어떤 배치가 적절한지 눈으로 보기 위한 출발점.
# product = (중심 x비율, 중심 y비율, 제품 높이 / 캔버스 높이)
# 하단 여백을 8% 이상 남겨 그림자가 잘리지 않게 하고, 제품을 살짝 오른쪽에 두어
# 왼쪽에 문구 공간을 확보한다(비대칭 레이아웃 방향).
LAYOUT = {
    "1x1": {"product": (0.62, 0.56, 0.68), "text": (0.06, 0.10), "align": "left"},
    "3x1": {"product": (0.76, 0.54, 0.76), "text": (0.05, 0.22), "align": "left"},
    "3x4": {"product": (0.58, 0.62, 0.60), "text": (0.07, 0.10), "align": "left"},
}


def _round8(v: float) -> int:
    """가장 가까운 8의 배수로 반올림한다(내림 아님).

    내림(v // 8 * 8)을 쓰면 3:4에서 1365.33 -> 1360이 되어 목표 비율에서 더 멀어진다.
    반올림하면 1368(= 1024/1368 = 0.7485, 3/4 = 0.75)로 훨씬 가깝다.
    """
    return max(int(round(v / 8)) * 8, 8)


def target_size(ratio_key: str) -> tuple[int, int]:
    """짧은 변을 BASE로 맞춘 (W, H). diffusion 호환을 위해 8의 배수로 반올림한다."""
    rw, rh = RATIOS[ratio_key]
    if rw >= rh:
        return _round8(BASE * rw / rh), _round8(BASE)
    return _round8(BASE), _round8(BASE * rh / rw)


# ---------------------------------------------------------------- 비정사각 대응 버전
# 프로덕션 masking.py의 정사각 강제 지점 3곳을 (W, H)로 다시 만든 것.
# pipeline/masking.py는 수정하지 않는다.

def add_blur_margin_ar(img: Image.Image, scale: float = None) -> Image.Image:
    """masking.add_blur_margin()의 비정사각 버전.

    원본은 `size = img.size[0]`으로 가로만 읽어 정사각을 가정한다.
    여기서는 W, H를 각각 축소해 캔버스 중앙에 붙인다.
    """
    scale = config.MARGIN_SCALE if scale is None else scale
    W, H = img.size
    canvas = img.filter(ImageFilter.GaussianBlur(config.BG_BLUR))
    small = img.resize((max(int(W * scale), 1), max(int(H * scale), 1)), Image.LANCZOS)
    canvas.paste(small, ((W - small.width) // 2, (H - small.height) // 2))
    return canvas


def prepare_image_ar(src, size_wh: tuple[int, int]):
    """masking.prepare_image()의 비정사각 버전 (A안 crop 경로).

    원본은 ImageOps.fit(img, (size, size))로 정사각 크롭한다.
    여기서는 목표 (W, H)로 맞춘다 — 즉 비율이 다르면 그만큼 잘려나간다.
    """
    img = Image.open(src) if isinstance(src, (str, bytes, Path)) else src
    img = ImageOps.exif_transpose(img).convert("RGB")
    img = ImageOps.fit(img, size_wh, method=Image.LANCZOS)

    masks = masking.make_masks(img)
    if masks.area_ratio <= config.AREA_THRESHOLD:
        return img, masks, "raw"

    img = add_blur_margin_ar(img)
    return img, masking.make_masks(img), "blur"


def render_flat_background_ar(size_wh: tuple[int, int], colors, direction=None):
    """masking.render_flat_background()의 비정사각 버전."""
    W, H = size_wh
    if len(colors) <= 1:
        return Image.new("RGB", (W, H), masking._hex_to_rgb(colors[0]))

    c1 = np.array(masking._hex_to_rgb(colors[0]), dtype=np.float32)
    c2 = np.array(masking._hex_to_rgb(colors[1]), dtype=np.float32)
    direction = direction or "vertical"

    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    yy /= max(H - 1, 1)
    xx /= max(W - 1, 1)
    t = yy if direction == "vertical" else xx if direction == "horizontal" else (xx + yy) / 2

    grad = c1 * (1 - t[..., None]) + c2 * t[..., None]
    return Image.fromarray(grad.astype(np.uint8), mode="RGB")


# ---------------------------------------------------------------- B안 canvas 재배치

def _bleed(rgb: np.ndarray, mask: np.ndarray, px: int) -> np.ndarray:
    """마스크 바깥 px 픽셀을 제품 가장자리 색으로 채운다(합성 경계 fringe 방지).

    verify_product_placement.py와 동일한 로직. 마스크 자체는 넓히지 않는다.
    """
    kernel = np.ones((3, 3), np.uint8)
    band = cv2.dilate(mask, kernel, iterations=px)
    hole = ((band > 0) & (mask == 0)).astype(np.uint8) * 255
    if hole.max() == 0:
        return rgb
    return cv2.inpaint(rgb, hole, 3, cv2.INPAINT_TELEA)


def place_on_canvas(base: Image.Image, masks, size_wh, cx, cy, scale,
                    fit_mode: str = "height", max_w_ratio: float = None):
    """정사각으로 준비된 제품을 목표 비율 캔버스에 옮겨 붙인다 (B안 canvas).

    base 전체가 아니라 제품 레이어만 옮기므로 원래 자리에 배경 잔상이 남지 않는다.

    fit_mode:
        "height"  — 제품 높이만 캔버스 높이의 scale 배로 맞춘다(기존 방식).
                    폭은 제품 원래 종횡비를 따라가므로 통제되지 않는다. 넓적한 제품은
                    좌우가 프레임에 닿고 그림자 타원(폭 비례)까지 잘릴 수 있다.
        "contain" — 높이와 폭 제약 중 더 빡빡한 쪽을 따른다.
                        factor = min(H*scale / bh, W*max_w_ratio / bw)
                    좁고 긴 제품은 높이가, 넓적한 제품은 폭이 배율을 결정한다.

    max_w_ratio는 후보(프리셋)마다 다르게 준다 — 문구가 위에 있는 1:1/3:4와
    왼쪽에 있는 3:1은 제품이 쓸 수 있는 가로 폭이 다르기 때문이다.

    Returns: (새 base, 새 MaskResult, meta)
    """
    W, H = size_wh
    src_rgb = np.array(base.convert("RGB"))
    tight = (np.array(masks.product.convert("L")) > 128).astype(np.uint8) * 255
    ys, xs = np.where(tight > 128)
    if len(xs) == 0:
        raise ValueError("제품 마스크가 비어 있습니다.")

    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    bw, bh = x1 - x0 + 1, y1 - y0 + 1

    # 배율 결정. height는 높이만, contain은 높이·폭 중 더 빡빡한 쪽을 따른다.
    f_h = (H * scale) / bh
    if fit_mode == "contain":
        if max_w_ratio is None:
            raise ValueError('fit_mode="contain"에는 max_w_ratio가 필요합니다.')
        f_w = (W * max_w_ratio) / bw
        factor = min(f_h, f_w)
        limited_by = "height" if f_h <= f_w else "width"
    elif fit_mode == "height":
        f_w, factor, limited_by = None, f_h, "height"
    else:
        raise ValueError(f'알 수 없는 fit_mode: {fit_mode} (height | contain)')
    bled = _bleed(src_rgb, tight, BLEED_PX)

    pad = BLEED_PX + 2
    cx0, cy0 = max(x0 - pad, 0), max(y0 - pad, 0)
    cx1, cy1 = min(x1 + pad + 1, src_rgb.shape[1]), min(y1 + pad + 1, src_rgb.shape[0])
    layer_rgb = bled[cy0:cy1, cx0:cx1]
    layer_a = tight[cy0:cy1, cx0:cx1]

    nw = max(int(round(layer_rgb.shape[1] * factor)), 1)
    nh = max(int(round(layer_rgb.shape[0] * factor)), 1)
    layer_rgb = cv2.resize(layer_rgb, (nw, nh), interpolation=cv2.INTER_LANCZOS4)
    layer_a = cv2.resize(layer_a, (nw, nh), interpolation=cv2.INTER_LINEAR)
    layer_a = (layer_a > 128).astype(np.uint8) * 255

    tx, ty = cx * W, cy * H
    off_x = ((x0 + x1) / 2 - cx0) * factor
    off_y = ((y0 + y1) / 2 - cy0) * factor
    px0, py0 = int(round(tx - off_x)), int(round(ty - off_y))

    new_rgb = np.zeros((H, W, 3), np.uint8)
    new_mask = np.zeros((H, W), np.uint8)
    sx0, sy0 = max(-px0, 0), max(-py0, 0)
    dx0, dy0 = max(px0, 0), max(py0, 0)
    cw = min(layer_rgb.shape[1] - sx0, W - dx0)
    ch = min(layer_rgb.shape[0] - sy0, H - dy0)
    clipped = (cw < layer_rgb.shape[1] - sx0) or (ch < layer_rgb.shape[0] - sy0) \
              or sx0 > 0 or sy0 > 0
    if cw > 0 and ch > 0:
        new_rgb[dy0:dy0 + ch, dx0:dx0 + cw] = layer_rgb[sy0:sy0 + ch, sx0:sx0 + cw]
        new_mask[dy0:dy0 + ch, dx0:dx0 + cw] = layer_a[sy0:sy0 + ch, sx0:sx0 + cw]

    if config.DILATE > 0:
        k = np.ones((config.DILATE, config.DILATE), np.uint8)
        dilated = cv2.dilate(new_mask, k, iterations=1)
    else:
        dilated = new_mask
    new_inpaint = Image.fromarray(255 - dilated).filter(
        ImageFilter.GaussianBlur(config.MASK_BLUR))

    new_masks = masking.MaskResult(
        Image.fromarray(new_mask), new_inpaint, float((new_mask > 0).mean()))
    return Image.fromarray(new_rgb), new_masks, {
        "fit_mode": fit_mode,
        "scale_limited_by": limited_by,
        "scale_factor": round(factor, 4),
        "factor_from_height": round(f_h, 4),
        "factor_from_width": round(f_w, 4) if f_w is not None else None,
        "max_w_ratio": max_w_ratio,
        # 정사각 준비 단계에서 잰 원본 제품 bbox (배율 계산의 입력값)
        "source_bbox_px": [bw, bh],
        "source_bbox_ratio": [round(bw / base.size[0], 4), round(bh / base.size[1], 4)],
        "layer_clipped": bool(clipped),
    }


# ---------------------------------------------------------------- 측정

def measure(img_size, masks, text_box=None, shadow_box=None,
            shadow_thresh=None) -> dict:
    """제품 bbox·면적·중심, 프레임 잘림, 그림자 범위, 문구 겹침·간격을 측정한다.

    shadow_box를 주면 실제 렌더된 그림자 픽셀 기준으로 잘림을 판정한다(권장).
    주지 않으면 add_ground_shadow의 계산식으로 추정하며, 그 경우 결과에
    estimated=True로 표시된다 — blur 꼬리까지는 반영되지 않는 근사치다.
    """
    W, H = img_size
    unit = min(W, H)
    m = np.array(masks.product.convert("L")) > 128
    ys, xs = np.where(m)
    if len(xs) == 0:
        return {"product_found": False}

    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())

    # 프레임에 닿아 있으면 잘렸을 가능성 (1px 여유)
    touch = {"left": x0 <= 1, "right": x1 >= W - 2,
             "top": y0 <= 1, "bottom": y1 >= H - 2}

    # 그림자: 현재 로직 그대로(add_ground_shadow) 계산했을 때의 위치.
    #   ey = y_max + H * SHADOW_Y_OFFSET_RATIO
    #   eh = max(제품 폭 * SHADOW_SQUASH, 6)   -> 타원 아래 끝 = ey + eh/2
    # 블러(SHADOW_BLUR)가 그 아래로 더 번지므로 실제로 보이는 하단은 조금 더 내려간다.
    shadow_cy = y1 + H * config.SHADOW_Y_OFFSET_RATIO
    gap_px = shadow_cy - y1
    ellipse_h = max((x1 - x0) * config.SHADOW_SQUASH, 6)
    shadow_bottom = shadow_cy + ellipse_h / 2 + config.SHADOW_BLUR

    out = {
        "product_found": True,
        "bbox_px": [x0, y0, x1, y1],
        "bbox_w_ratio": round((x1 - x0 + 1) / W, 4),
        "bbox_h_ratio": round((y1 - y0 + 1) / H, 4),
        "center_x_ratio": round((x0 + x1) / 2 / W, 4),
        "center_y_ratio": round((y0 + y1) / 2 / H, 4),
        "area_ratio": round(float(m.mean()), 4),
        "frame_touch": touch,
        "clipped": any(touch.values()),          # 제품 bbox 기준
        # (그림자 잘림은 아래 shadow.shadow_clipped 참고 — 제품이 안 잘려도 그림자는 잘릴 수 있음)
        "margin_ratio": {
            "left": round(x0 / W, 4), "right": round((W - 1 - x1) / W, 4),
            "top": round(y0 / H, 4), "bottom": round((H - 1 - y1) / H, 4),
        },
        "shadow": {
            "product_bottom_y": y1,
            "shadow_center_y": round(shadow_cy, 1),
            "gap_px": round(gap_px, 1),
            "gap_over_short_side": round(gap_px / unit, 5),
            "y_offset_ratio_used": config.SHADOW_Y_OFFSET_RATIO,
            "ellipse_h_px": round(ellipse_h, 1),
        },
    }

    if shadow_box is not None:
        sx0, sy0, sx1, sy1 = shadow_box
        out["shadow"].update({
            "measured": True,
            "threshold": shadow_thresh,
            "bbox_px": [sx0, sy0, sx1, sy1],
            "bottom_y": sy1,
            "bottom_margin_px": H - 1 - sy1,
            "touch": {"left": sx0 <= 1, "right": sx1 >= W - 2,
                      "top": sy0 <= 1, "bottom": sy1 >= H - 2},
            "shadow_clipped": bool(sx0 <= 1 or sy0 <= 1
                                   or sx1 >= W - 2 or sy1 >= H - 2),
        })
    else:
        # 폴백: 계산식 추정 (blur 꼬리 미반영)
        est_bottom = shadow_cy + ellipse_h / 2 + config.SHADOW_BLUR
        out["shadow"].update({
            "measured": False,
            "estimated_bottom_y": round(est_bottom, 1),
            "bottom_margin_px": round(H - est_bottom, 1),
            "shadow_clipped": bool(est_bottom > H - 1),
        })

    if text_box:
        tx0, ty0, tx1, ty1 = text_box
        inter_w = max(0, min(x1, tx1) - max(x0, tx0))
        inter_h = max(0, min(y1, ty1) - max(y0, ty0))
        inter = inter_w * inter_h
        text_area = max((tx1 - tx0) * (ty1 - ty0), 1)
        out["text"] = {
            "box_px": [tx0, ty0, tx1, ty1],
            "overlaps_product_bbox": inter > 0,
            "overlap_ratio_of_text": round(inter / text_area, 4),
        }
        # 문구와 제품 사이 간격. 3:1처럼 문구가 제품 "옆"에 있는 배치에서는
        # 세로 간격만 보면 음수가 나와 오해하기 쉬우므로 두 축을 모두 재고,
        # 실제로 둘을 갈라놓는 축(separating_axis)을 함께 표시한다.
        gap_x = (x0 - tx1) if tx1 < x0 else (tx0 - x1) if tx0 > x1 else 0
        gap_y = (y0 - ty1) if ty1 < y0 else (ty0 - y1) if ty0 > y1 else 0
        if gap_x > 0 and gap_y > 0:
            axis = "both"
        elif gap_x > 0:
            axis = "horizontal"
        elif gap_y > 0:
            axis = "vertical"
        else:
            axis = "none"      # bbox가 겹침
        out["text"].update({
            "gap_x_px": int(gap_x), "gap_y_px": int(gap_y),
            "gap_x_ratio": round(gap_x / unit, 4),
            "gap_y_ratio": round(gap_y / unit, 4),
            "separating_axis": axis,
        })
    return out


def shadow_extent(flat: Image.Image, shadowed: Image.Image, thresh: int = 3):
    """실제로 렌더된 그림자 픽셀의 bbox를 잰다 (계산식 추정이 아니라 실측).

    add_ground_shadow()는 배경을 어둡게 만드는 방식이라, 그림자 적용 전(flat)과
    후(shadowed)의 밝기 차이가 곧 그림자다. Gaussian blur의 꼬리는 점근적이라
    임계값이 필요하며, thresh(기본 3/255)보다 어두워진 픽셀까지를 "보이는 그림자"로 본다.

    Returns: (bbox 또는 None, 사용한 임계값)
    """
    a = np.array(flat.convert("L"), dtype=np.int16)
    b = np.array(shadowed.convert("L"), dtype=np.int16)
    ys, xs = np.where((a - b) > thresh)          # 어두워진 곳 = 그림자
    if len(xs) == 0:
        return None, thresh
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())], thresh


def text_ink_box(before: Image.Image, after: Image.Image):
    """문구 합성 전후 차이로 실제 글자가 차지한 영역을 구한다(안전 영역 확인용)."""
    d = np.abs(np.array(before.convert("RGB"), dtype=np.int16)
               - np.array(after.convert("RGB"), dtype=np.int16)).sum(axis=2)
    ys, xs = np.where(d > 24)
    if len(xs) == 0:
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]


# ---------------------------------------------------------------- 생성

def compose(base, masks, size_wh, category, headline, sub, text_xy, align):
    """배경 -> 그림자 -> 제품 -> 문구 순으로 합성한다 (solid 배경, diffusion 없음)."""
    spec = masking.resolve_background("solid", None, None, category, 1)[0]
    flat = render_flat_background_ar(size_wh, spec["colors"], spec.get("direction"))
    shadowed = masking.add_ground_shadow(flat, masks.product)
    no_text = masking.composite_product(base, shadowed, masks.product)
    shadow_box, shadow_thresh = shadow_extent(flat, shadowed)

    preset = config.TONE_PRESETS["minimal_product"]
    with_text, tmeta = overlay.render_text(
        no_text, headline, sub, x=text_xy[0], y=text_xy[1], align=align,
        style="plain",
        headline_size=preset["headline_size"], sub_size=preset["sub_size"],
        headline_font_role=preset["headline_font_role"],
        stroke_width=preset["stroke_width"], fill_color=preset.get("fill_color"),
        max_height_ratio=0.35, return_meta=True)
    return no_text, with_text, spec, tmeta, shadow_box, shadow_thresh


def build_crop(case, ratio_key):
    """A안: 원본을 목표 비율로 잘라낸다."""
    size_wh = target_size(ratio_key)
    lay = LAYOUT[ratio_key]
    base, masks, mode = prepare_image_ar(ROOT / case["path"], size_wh)
    no_text, img, spec, tmeta, sbox, sth = compose(
        base, masks, size_wh, case["category"], case["headline"], case["sub"],
        lay["text"], lay["align"])
    info = measure(size_wh, masks, text_ink_box(no_text, img), sbox, sth)
    info.update({"prepare_mode": mode, "background": spec, "size": list(size_wh),
                 "placement": {"scale_source": "from_source_photo"},
                 "applied_headline_ratio": tmeta["applied_headline_ratio"],
                 "text_shrunk": tmeta["shrunk"]})
    return img, info


def build_canvas(case, ratio_key, target_h_ratio=None, scale_source="layout_default"):
    """B안: 정사각으로 누끼를 딴 뒤 제품만 목표 비율 캔버스에 배치한다.

    target_h_ratio를 주면 그 값을 제품 높이(캔버스 높이 대비)로 쓴다. A/B 비교에서
    제품 크기를 통제변수로 만들기 위해 crop 결과의 제품 높이를 그대로 넘겨 쓴다.
    None이면 LAYOUT의 고정값을 쓴다.
    """
    size_wh = target_size(ratio_key)
    lay = LAYOUT[ratio_key]
    cx, cy, scale = lay["product"]
    if target_h_ratio is not None:
        scale = target_h_ratio

    # 누끼는 정사각(BASE)에서 한 번만 딴다 — 비율이 바뀌어도 마스크 품질이 동일하다.
    sq_base, sq_masks, mode = masking.prepare_image(str(ROOT / case["path"]), BASE)
    base, masks, pmeta = place_on_canvas(sq_base, sq_masks, size_wh, cx, cy, scale)

    no_text, img, spec, tmeta, sbox, sth = compose(
        base, masks, size_wh, case["category"], case["headline"], case["sub"],
        lay["text"], lay["align"])
    info = measure(size_wh, masks, text_ink_box(no_text, img), sbox, sth)
    info.update({"prepare_mode": mode, "background": spec, "size": list(size_wh),
                 "placement": {"cx": cx, "cy": cy, "target_h_ratio": round(scale, 4),
                               "scale_source": scale_source, **pmeta},
                 "applied_headline_ratio": tmeta["applied_headline_ratio"],
                 "text_shrunk": tmeta["shrunk"]})
    return img, info


def make_comparison(name, results):
    """3행(비율) x 2열(방식) 비교 이미지. 각 셀은 폭 기준으로 맞춰 축소한다."""
    cell_w, pad, label_h = 560, 10, 22
    rows = []
    for rk in results:          # 실행된 비율만 (부분 실행 지원)
        row = []
        for method in ("crop", "canvas"):
            im = results[rk][method]["image"]
            w, h = im.size
            row.append(im.resize((cell_w, max(int(h * cell_w / w), 1))))
        rows.append((rk, row))

    row_hs = [max(r[0].height, r[1].height) + label_h for _, r in rows]
    total_h = sum(row_hs) + pad * (len(rows) + 1)
    total_w = cell_w * 2 + pad * 3
    canvas = Image.new("RGB", (total_w, total_h), "white")
    d = ImageDraw.Draw(canvas)

    y = pad
    for (rk, row), rh in zip(rows, row_hs):
        for i, (method, im) in enumerate(zip(("crop", "canvas"), row)):
            x = pad + i * (cell_w + pad)
            info = results[rk][method]["info"]
            # 면적만 표시하면 3:1처럼 넓은 화면에서 세로형 제품이 실제보다 작아 보여
            # 해석이 어렵다. bbox 높이/폭 비율을 함께 보여준다.
            src = info.get("placement", {}).get("scale_source", "-")
            ov = info.get("text", {}).get("overlaps_product_bbox")
            d.text((x, y + 5),
                   f"{name} {rk} | {method} | H {info['bbox_h_ratio']:.1%}"
                   f" | W {info['bbox_w_ratio']:.1%} | area {info['area_ratio']:.1%}"
                   f" | {src} | clipped={info['clipped']}"
                   f" | shadow_cut={info['shadow']['shadow_clipped']} | text_overlap={ov}",
                   fill="black")
            canvas.paste(im, (x, y + label_h))
        y += rh + pad
    return canvas


def _normalize_ratio(key: str) -> str:
    """--ratios 1:1 처럼 콜론으로 받아도 내부 키(1x1)로 맞춘다.

    파일명에는 콜론을 쓸 수 없어(특히 Windows) 저장은 항상 1x1 형태를 쓴다.
    """
    k = key.strip().replace(":", "x").replace("/", "x")
    if k not in RATIOS:
        raise SystemExit(f"알 수 없는 비율: {key} (사용 가능: {', '.join(RATIOS)})")
    return k


def parse_args():
    ap = argparse.ArgumentParser(
        description="용도별 비율(1:1 / 3:1 / 3:4) crop vs canvas 비교 실험")
    ap.add_argument("--images", nargs="+", metavar="NAME",
                    help=f"대상 제품 이름. 기본 전체 ({', '.join(c['name'] for c in CASES)})")
    ap.add_argument("--ratios", nargs="+", metavar="RATIO",
                    help="대상 비율. 1:1 3:1 3:4 또는 1x1 3x1 3x4. 기본 전체")
    ap.add_argument("--limit", type=int, metavar="N",
                    help="앞에서 N개 제품만 실행 (--images와 함께 쓰면 그 목록에서 N개)")
    ap.add_argument("--canvas-scale", choices=["match", "fixed"], default="match",
                    help="canvas의 제품 크기. match=crop 결과에 맞춤(A/B 공정 비교, 기본), "
                         "fixed=LAYOUT 고정값(실사용 배치안 확인)")
    return ap.parse_args()


def main():
    args = parse_args()

    cases = CASES
    if args.images:
        want = set(args.images)
        cases = [c for c in CASES if c["name"] in want]
        missing = want - {c["name"] for c in cases}
        if missing:
            raise SystemExit(f"CASES에 없는 이름: {', '.join(sorted(missing))}")
    if args.limit:
        cases = cases[:args.limit]

    ratios = [_normalize_ratio(r) for r in args.ratios] if args.ratios else list(RATIOS)

    for d in (CROP_DIR, CANVAS_DIR, CMP_DIR):
        d.mkdir(parents=True, exist_ok=True)

    print(f"대상 제품: {[c['name'] for c in cases]}")
    print(f"대상 비율: {ratios}   canvas 크기 기준: {args.canvas_scale}\n")

    log, errors = [], []
    for case in cases:
        src = ROOT / case["path"]
        if not src.exists():
            msg = f"입력 이미지 없음: {src}"
            print(f"건너뜀 — {msg}")
            errors.append({"name": case["name"], "stage": "input", "error": msg})
            continue

        print(f"=== {case['name']} ===")
        results = {}
        for rk in ratios:
            results[rk] = {}

            # --- A안 crop 먼저 (canvas가 이 결과의 제품 크기를 따라갈 수 있도록)
            crop_info = None
            try:
                t0 = time.time()
                img, crop_info = build_crop(case, rk)
                path = CROP_DIR / f"{case['name']}_{rk}.png"
                img.save(path)
                crop_info.update({"name": case["name"], "ratio": rk, "method": "crop",
                                  "path": str(path.relative_to(ROOT)),
                                  "elapsed": round(time.time() - t0, 2)})
                results[rk]["crop"] = {"image": img, "info": crop_info}
                log.append(crop_info)
                print(f"  {rk:>4}   crop  size={crop_info['size']}  "
                      f"제품 {crop_info['area_ratio']:.1%} "
                      f"(높이 {crop_info['bbox_h_ratio']:.1%})  "
                      f"잘림={crop_info['clipped']}  "
                      f"그림자 {crop_info['shadow']['gap_px']}px")
            except Exception as e:      # 한 조합이 실패해도 나머지는 계속
                msg = f"{type(e).__name__}: {e}"
                print(f"  {rk:>4}   crop  실패 — {msg}")
                errors.append({"name": case["name"], "ratio": rk,
                               "method": "crop", "error": msg,
                               "traceback": traceback.format_exc()})

            # --- B안 canvas
            try:
                t0 = time.time()
                if args.canvas_scale == "match" and crop_info and not crop_info["clipped"]:
                    target_h, source = crop_info["bbox_h_ratio"], "matched_to_crop"
                elif args.canvas_scale == "match" and crop_info:
                    # crop이 잘렸다면 그 높이를 따라가도 같이 잘리므로 고정값으로 폴백
                    target_h, source = None, "layout_default(crop_clipped)"
                elif args.canvas_scale == "match":
                    target_h, source = None, "layout_default(crop_failed)"
                else:
                    target_h, source = None, "layout_default"

                img, info = build_canvas(case, rk, target_h, source)
                path = CANVAS_DIR / f"{case['name']}_{rk}.png"
                img.save(path)
                info.update({"name": case["name"], "ratio": rk, "method": "canvas",
                             "path": str(path.relative_to(ROOT)),
                             "elapsed": round(time.time() - t0, 2)})
                results[rk]["canvas"] = {"image": img, "info": info}
                log.append(info)
                print(f"  {rk:>4} canvas  size={info['size']}  "
                      f"제품 {info['area_ratio']:.1%} "
                      f"(높이 {info['bbox_h_ratio']:.1%}, {source})  "
                      f"잘림={info['clipped']}  "
                      f"그림자 {info['shadow']['gap_px']}px")
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                print(f"  {rk:>4} canvas  실패 — {msg}")
                errors.append({"name": case["name"], "ratio": rk,
                               "method": "canvas", "error": msg,
                               "traceback": traceback.format_exc()})

        try:
            usable = {rk: v for rk, v in results.items() if len(v) == 2}
            if usable:
                cmp_path = CMP_DIR / f"{case['name']}_compare.png"
                make_comparison(case["name"], usable).save(cmp_path)
                print(f"  -> {cmp_path.relative_to(ROOT)}")
            else:
                print("  비교 이미지 생략 (crop/canvas 양쪽이 성공한 비율 없음)")
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            print(f"  비교 이미지 실패 — {msg}")
            errors.append({"name": case["name"], "stage": "comparison", "error": msg,
                           "traceback": traceback.format_exc()})
        print()

    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump({"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "base_short_side": BASE,
                   "ratios": {k: list(v) for k, v in RATIOS.items()},
                   "target_sizes": {k: list(target_size(k)) for k in RATIOS},
                   "layout": LAYOUT,
                   "canvas_scale_mode": args.canvas_scale,
                   "shadow_y_offset_ratio": config.SHADOW_Y_OFFSET_RATIO,
                   "results": log, "errors": errors}, f, ensure_ascii=False, indent=2)

    print(f"완료: 성공 {len(log)}건, 실패 {len(errors)}건")
    print(f"로그: {LOG_PATH.relative_to(ROOT)}")
    if errors:
        print("실패 내역은 run_log.json의 errors 항목을 확인하세요.")


if __name__ == "__main__":
    main()

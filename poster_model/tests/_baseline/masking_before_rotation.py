"""A2 이전 add_ground_shadow의 0° 회귀 비교용 최소 baseline.

전체 masking.py 소스를 고정하지 않고, A2에서 실제로 변경된
그림자 함수의 legacy 동작만 보존한다.
"""

from __future__ import annotations

def add_ground_shadow(img: Image.Image,
                      product_mask: Image.Image,
                      opacity: int = None,
                      blur: int = None,
                      squash: float = None,
                      y_offset_ratio: float = None,
                      min_area_ratio: float = None) -> Image.Image:
    """제품 마스크 하단 기준으로 접지 그림자를 합성한다.

    배경을 교체하면 원본 그림자가 마스크 밖(배경 영역)에 있어 사라지고
    제품이 공중에 뜬 것처럼 보인다. product_mask의 하단 경계에 맞춰
    타원형 그림자를 그리고 블러 처리해 자연스러운 접지 효과를 만든다.

    한 장에 제품이 여러 개(예: 화장품 2병) 찍혀 마스크가 서로 떨어진
    덩어리로 나뉘는 경우, 전체 bbox로 그림자 하나를 그리면 제품 사이
    빈 공간까지 가로지르는 부자연스러운 그림자가 생긴다. 이를 막기 위해
    cv2.connectedComponentsWithStats로 마스크를 덩어리 단위로 분리해
    덩어리마다 개별 그림자를 그린다. min_area_ratio보다 작은 덩어리는
    rembg 노이즈로 보고 무시한다.

    composite_product보다 먼저 호출해야 한다. 그림자가 제품 마스크 영역과
    겹치는 부분은 이후 composite_product가 원본 제품으로 다시 덮으므로,
    실제로 보이는 것은 제품 바로 아래로 삐져나온 부분이다.

    Args:
        img: 그림자를 그릴 대상(주로 diffusion이 생성한 배경 이미지)
        product_mask: MaskResult.product (제품=흰색)
    """
    opacity = config.SHADOW_OPACITY if opacity is None else opacity
    blur = config.SHADOW_BLUR if blur is None else blur
    squash = config.SHADOW_SQUASH if squash is None else squash
    y_offset_ratio = (config.SHADOW_Y_OFFSET_RATIO
                      if y_offset_ratio is None else y_offset_ratio)
    min_area_ratio = (config.SHADOW_MIN_AREA_RATIO
                      if min_area_ratio is None else min_area_ratio)

    W, H = img.size
    binary = (np.array(product_mask.convert("L")) > 128).astype(np.uint8)
    if binary.sum() == 0:
        return img   # 제품 미검출 시 원본 그대로 (안전장치)

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary, connectivity=8)
    min_pixels = binary.size * min_area_ratio

    shadow = Image.new("L", (W, H), 0)
    draw = ImageDraw.Draw(shadow)
    drawn = False

    for label in range(1, num_labels):   # label 0 = 배경
        if stats[label, cv2.CC_STAT_AREA] < min_pixels:
            continue   # 작은 노이즈성 덩어리는 그림자 생략

        ys, xs = np.where(labels == label)
        x_min, x_max = int(xs.min()), int(xs.max())
        y_max = int(ys.max())
        cx = (x_min + x_max) / 2
        width = x_max - x_min

        ew = width * 0.95
        eh = max(width * squash, 6)
        ey = y_max + H * y_offset_ratio
        draw.ellipse([cx - ew / 2, ey - eh / 2, cx + ew / 2, ey + eh / 2],
                    fill=opacity)
        drawn = True

    if not drawn:
        return img

    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))

    out = img.convert("RGBA")
    dark = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    out = Image.composite(dark, out, shadow)
    return out.convert("RGB")

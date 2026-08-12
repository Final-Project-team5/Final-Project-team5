"""제품 마스킹 및 입력 이미지 전처리."""

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps
from rembg import new_session, remove

from . import config

_session = None


def get_session():
    """rembg 세션 (최초 1회만 로드)."""
    global _session
    if _session is None:
        _session = new_session(config.REMBG_MODEL)
    return _session


@dataclass
class MaskResult:
    """마스킹 결과.

    product: 제품=흰색. 원본 합성(composite)·그림자 영역 계산에 사용.
             rembg의 원본 alpha 그대로(dilate 적용 안 함) — dilate된 마스크를 쓰면
             제품 주변 원본 배경 픽셀(나무 바닥, 대리석 등)까지 같이 복원되어
             단색/그라데이션 배경에서 halo로 두드러지는 문제가 있었음(실측 확인).
    inpaint: 배경=흰색. diffusion이 다시 그릴 영역. 여기엔 계속 dilate를 적용해
             diffusion이 제품 경계에 바짝 붙지 않고 약간 여유를 두고 자연스럽게
             이어지도록 한다 (composite용 마스크와는 별개 — 이번에 분리함).
    area_ratio: 전체 대비 제품이 차지하는 비율 (product 기준, dilate 이전)
    """
    product: Image.Image
    inpaint: Image.Image
    area_ratio: float


def _as_wh(size) -> tuple[int, int]:
    """int(정사각) 또는 (W, H)를 모두 받아 (W, H)로 정규화한다.

    기존 호출부는 전부 int를 넘기므로 int 경로는 (size, size)가 되어
    동작이 완전히 동일하다. 비정사각 캔버스는 튜플로만 들어온다.
    """
    if isinstance(size, (tuple, list)):
        w, h = size
        return int(w), int(h)
    return int(size), int(size)


def make_masks(img: Image.Image,
               dilate: int = None,
               blur: int = None) -> MaskResult:
    dilate = config.DILATE if dilate is None else dilate
    blur = config.MASK_BLUR if blur is None else blur

    cut = remove(img, session=get_session())
    alpha = np.array(cut.split()[-1])
    tight = (alpha > 128).astype(np.uint8) * 255   # rembg 원본 alpha, dilate 이전

    if dilate > 0:
        kernel = np.ones((dilate, dilate), np.uint8)
        dilated = cv2.dilate(tight, kernel, iterations=1)
    else:
        dilated = tight

    product = Image.fromarray(tight)        # 합성/그림자용 — tight (halo 방지)
    inpaint = Image.fromarray(255 - dilated).filter(
        ImageFilter.GaussianBlur(blur))     # diffusion용 — dilated (경계 여유)

    return MaskResult(product, inpaint, float((tight > 0).mean()))


def describe_product_bbox(product_mask: Image.Image) -> dict:
    """제품 마스크의 bbox를 이미지 크기 대비 비율로 요약한다 (진단/로그용).

    draft(768)와 refine(1024)처럼 해상도가 다른 두 단계에서 제품의 상대 크기·
    중심 좌표가 일관되는지 비교할 때 쓴다. rembg를 해상도별로 각각 새로 돌리기
    때문에, 두 단계의 이 값이 다르면 그게 바로 크기/위치 불일치의 증거가 된다.
    """
    W, H = product_mask.size
    m = np.array(product_mask.convert("L")) > 128
    ys, xs = np.where(m)
    if len(xs) == 0:
        return {"bbox_w_ratio": None, "bbox_h_ratio": None,
                "center_x_ratio": None, "center_y_ratio": None}
    x_min, x_max, y_min, y_max = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    return {
        "bbox_w_ratio": round((x_max - x_min) / W, 4),
        "bbox_h_ratio": round((y_max - y_min) / H, 4),
        "center_x_ratio": round((x_min + x_max) / 2 / W, 4),
        "center_y_ratio": round((y_min + y_max) / 2 / H, 4),
    }


def add_blur_margin(img: Image.Image, scale: float = None) -> Image.Image:
    """제품을 축소해 중앙 배치하고, 여백은 원본을 블러한 것으로 채운다.

    흰색 캔버스를 쓰면 diffusion이 프레임/텍스트를 그려넣는 문제가 있어
    (실험에서 확인) 블러한 원본을 배경으로 사용한다.
    """
    scale = config.MARGIN_SCALE if scale is None else scale
    size = img.size[0]

    canvas = img.filter(ImageFilter.GaussianBlur(config.BG_BLUR))
    small = img.resize((int(size * scale), int(size * scale)), Image.LANCZOS)
    canvas.paste(small, ((size - small.width) // 2,
                         (size - small.height) // 2))
    return canvas


def prepare_image(src, size: int,
                  apply_blur_margin: bool = True) -> tuple[Image.Image, MaskResult, str]:
    """입력 이미지를 생성 가능한 형태로 준비한다.

    제품이 화면을 꽉 채우면 배경 재생성 영역이 부족해 배경이 바뀌지 않으므로,
    area_ratio가 임계값을 넘으면 자동으로 여백을 확보한다.

    apply_blur_margin=False는 **여백 확보(축소) 단계만** 건너뛴다. exif 보정,
    정사각 리사이즈, 마스크 생성 등 나머지 전처리는 동일하게 수행한다.
    비정사각 캔버스 경로에서 쓴다. 그 경로에서는 캔버스 배치가 제품 크기와
    여백을 단독으로 책임지므로, 여기서 0.7배로 줄이면 이중 축소가 되어
    확대 상한의 기준이 흐려지고 리샘플 손실만 커진다.
    AI 경로는 diffusion이 배경을 그릴 여백이 실제로 필요하므로 항상 True다.

    Returns:
        (준비된 이미지, 마스크, 적용 모드)
    """
    if isinstance(src, (str, bytes)):
        img = Image.open(src)
    else:
        img = src

    img = ImageOps.exif_transpose(img).convert("RGB")   # 폰카 회전 보정 필수
    img = ImageOps.fit(img, (size, size), method=Image.LANCZOS)

    masks = make_masks(img)
    if masks.area_ratio <= config.AREA_THRESHOLD or not apply_blur_margin:
        return img, masks, "raw"

    img = add_blur_margin(img)
    return img, make_masks(img), "blur"


def composite_product(original: Image.Image,
                      generated: Image.Image,
                      product_mask: Image.Image) -> Image.Image:
    """생성 결과 위에 원본 제품을 다시 덮어 픽셀 단위로 보존한다.

    inpainting만으로는 VAE 인코딩/디코딩 과정에서 로고나 텍스트가
    뭉개지므로 이 단계는 필수다.
    """
    soft = product_mask.convert("L").filter(
        ImageFilter.GaussianBlur(config.COMPOSITE_BLUR))
    return Image.composite(original, generated.convert("RGB"), soft)


def _bleed(rgb: np.ndarray, mask: np.ndarray, px: int) -> np.ndarray:
    """마스크 바깥 px를 제품 가장자리 색으로 채운다(합성 경계 fringe 방지).

    composite_product()가 COMPOSITE_BLUR로 마스크를 부드럽게 만들기 때문에
    마스크 바로 바깥 1~2px이 결과에 섞인다. 캔버스에서 그 영역이 비어 있으면
    제품 테두리가 어두워진다. 마스크 자체는 넓히지 않는다.
    """
    k = np.ones((3, 3), np.uint8)
    band = cv2.dilate(mask, k, iterations=px)
    hole = ((band > 0) & (mask == 0)).astype(np.uint8) * 255
    if hole.max() == 0:
        return rgb
    return cv2.inpaint(rgb, hole, 3, cv2.INPAINT_TELEA)


def place_product_on_canvas(base: Image.Image,
                            masks: MaskResult,
                            canvas_wh,
                            scale: float = 1.0,
                            x_px: int = None,
                            y_px: int = None,
                            bleed_px: int = 8) -> tuple[Image.Image, MaskResult]:
    """제품과 마스크를 W×H 캔버스 좌표계로 옮기는 순수 변환.

    배치 정책(어디에 얼마나 크게 둘지)은 이 함수가 정하지 않는다. 호출자가
    계산한 scale/x_px/y_px를 그대로 적용하기만 한다.

    이 함수를 따로 두는 이유는 prepare_image()가 소스 정규화(정사각)를
    담당하고, 최종 출력 크기는 그와 독립이기 때문이다. 원본을 목표 W×H로
    직접 ImageOps.fit()하면 3:1에서 제품이 잘리므로 그 방식은 쓰지 않는다.

    Args:
        canvas_wh: int 또는 (W, H). 최종 캔버스 크기.
        scale: 제품 배율. 종횡비는 항상 유지된다.
        x_px, y_px: 제품 bbox 좌상단이 놓일 캔버스 좌표.
                    None이면 소스에서의 bbox 위치를 그대로 유지한다.
        bleed_px: 마스크 바깥으로 가장자리 색을 번지게 할 픽셀 수.

    Returns:
        (캔버스 크기 base, 캔버스 크기 MaskResult).
        항등 변환일 때도 입력과 픽셀은 같지만 항상 새 객체를 돌려준다.

    Raises:
        ValueError: 제품 마스크가 비었거나, 배치 결과가 캔버스 밖으로 잘릴 때.
    """
    W, H = _as_wh(canvas_wh)
    src_w, src_h = base.size

    tight = (np.array(masks.product.convert("L")) > 128).astype(np.uint8)
    ys, xs = np.where(tight > 0)
    if len(xs) == 0:
        raise ValueError("제품 마스크가 비어 있어 캔버스 배치를 할 수 없습니다.")
    bx0, by0 = int(xs.min()), int(ys.min())
    bx1, by1 = int(xs.max()), int(ys.max())

    tx = bx0 if x_px is None else int(x_px)
    ty = by0 if y_px is None else int(y_px)

    # 항등 경로: 캔버스가 소스와 같고 배율 1.0, 이동 없음이면 crop/resize/inpaint를
    # 전혀 거치지 않는다. 기존 정사각 결과와 픽셀 단위로 동일함이 보장된다.
    #
    # 다만 원본 객체를 그대로 돌려주지는 않고 복사본을 만든다. 보장해야 하는 것은
    # 픽셀 동일성이지 객체 동일성이 아니며, 호출자가 반환값을 in-place로 수정할 때
    # (PIL의 paste/ImageDraw 등) 소스까지 바뀌는 것을 막기 위해서다.
    if (W, H) == (src_w, src_h) and float(scale) == 1.0 and (tx, ty) == (bx0, by0):
        return base.copy(), MaskResult(masks.product.copy(),
                                       masks.inpaint.copy(),
                                       masks.area_ratio)

    bw, bh = bx1 - bx0 + 1, by1 - by0 + 1
    nw = max(1, int(round(bw * scale)))
    nh = max(1, int(round(bh * scale)))
    if tx < 0 or ty < 0 or tx + nw > W or ty + nh > H:
        raise ValueError(
            f"제품이 캔버스를 벗어납니다: 배치 {nw}x{nh}@({tx},{ty}), 캔버스 {W}x{H}")

    # bleed는 잘라내기 전에 소스 전체에서 적용해야 bbox 경계에서도 색이 이어진다.
    rgb = _bleed(np.array(base.convert("RGB"), dtype=np.uint8), tight, bleed_px)

    # bbox에 bleed 여유를 두고 잘라 확대/축소한다(경계에서 fringe가 남지 않도록).
    pad = bleed_px
    cx0, cy0 = max(0, bx0 - pad), max(0, by0 - pad)
    cx1, cy1 = min(src_w, bx1 + 1 + pad), min(src_h, by1 + 1 + pad)
    cw, ch = cx1 - cx0, cy1 - cy0
    rw = max(1, int(round(cw * scale)))
    rh = max(1, int(round(ch * scale)))

    crop_rgb = Image.fromarray(rgb).crop((cx0, cy0, cx1, cy1)).resize(
        (rw, rh), Image.LANCZOS)
    crop_m = masks.product.convert("L").crop((cx0, cy0, cx1, cy1)).resize(
        (rw, rh), Image.LANCZOS)

    # bbox 좌상단이 (tx, ty)에 오도록, 패딩만큼 되돌려서 붙인다.
    px = tx - int(round((bx0 - cx0) * scale))
    py = ty - int(round((by0 - cy0) * scale))

    base_cv = Image.new("RGB", (W, H), (0, 0, 0))
    base_cv.paste(crop_rgb, (px, py))

    tight_cv = Image.new("L", (W, H), 0)
    tight_cv.paste(crop_m, (px, py))
    tight_arr = (np.array(tight_cv) > 128).astype(np.uint8) * 255
    tight_cv = Image.fromarray(tight_arr)

    # inpaint 마스크는 옮긴 결과에서 make_masks()와 같은 방식으로 다시 만든다
    # (반전 마스크를 그대로 옮기면 캔버스 여백의 값이 틀어진다).
    if config.DILATE > 0:
        kernel = np.ones((config.DILATE, config.DILATE), np.uint8)
        dilated = cv2.dilate(tight_arr, kernel, iterations=1)
    else:
        dilated = tight_arr
    inpaint_cv = Image.fromarray(255 - dilated).filter(
        ImageFilter.GaussianBlur(config.MASK_BLUR))

    return base_cv, MaskResult(tight_cv, inpaint_cv, float((tight_arr > 0).mean()))


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


# ---------------------------------------------------------------- 배경 모드 (solid/gradient)

def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb) -> str:
    r, g, b = (max(0, min(255, int(round(c)))) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _shift_lightness(hex_color: str, delta: float) -> str:
    """사용자 지정 색의 base/light/dark 변형용.

    HSL lightness를 그냥 더하면 이미 밝은 파스텔 색(L이 0.9 이상)은 +delta에서
    바로 흰색(L=1.0)으로 클리핑돼버려 구분이 안 되는 문제가 있다(실측 확인).
    대신 흰색/검은색 쪽으로 일정 비율만 섞는 방식을 써서, 원래 색이 얼마나
    밝든 어둡든 옅게라도 방향성 있는 변화가 남도록 한다.
    """
    r, g, b = _hex_to_rgb(hex_color)
    target = (255, 255, 255) if delta > 0 else (0, 0, 0)
    amount = min(abs(delta) * 2, 0.9)   # delta(±0.12 등)를 섞는 비율로 변환, 완전히 뒤덮지 않게 상한
    mixed = tuple(c * (1 - amount) + t * amount for c, t in zip((r, g, b), target))
    return _rgb_to_hex(mixed)


def render_flat_background(size,
                           colors: list[str],
                           direction: str = None) -> Image.Image:
    """단색 또는 2색 그라데이션 배경을 생성한다 (diffusion 완전 생략, PIL만 사용).

    colors가 1개면 단색, 2개 이상이면 첫 두 색으로 direction 방향
    (vertical/horizontal/diagonal) 선형 그라데이션을 만든다.

    size는 int(정사각) 또는 (W, H)를 받는다. 정규화는 반드시 축별로 한다
    (이전에는 두 축을 모두 size-1로 나눠 정사각에서만 성립했다).
    diagonal은 물리적 45도가 아니라 좌상단→우하단 corner-to-corner다.
    """
    W, H = _as_wh(size)
    if len(colors) <= 1:
        return Image.new("RGB", (W, H), _hex_to_rgb(colors[0]))

    c1 = np.array(_hex_to_rgb(colors[0]), dtype=np.float32)
    c2 = np.array(_hex_to_rgb(colors[1]), dtype=np.float32)
    direction = direction or "vertical"

    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    yy = yy / max(H - 1, 1)
    xx = xx / max(W - 1, 1)
    if direction == "vertical":
        t = yy
    elif direction == "horizontal":
        t = xx
    else:   # diagonal
        t = (xx + yy) / 2

    t = t[..., None]
    grad = c1 * (1 - t) + c2 * t
    return Image.fromarray(grad.astype(np.uint8), mode="RGB")


def resolve_background(mode: str,
                       colors: list[str] = None,
                       direction: str = None,
                       category: str = None,
                       num_images: int = 1) -> list[dict]:
    """solid/gradient 배경 설정을 draft 개수만큼 구체적인 색상 조합으로 변환한다.

    우선순위: 사용자가 colors를 지정하면 그 색 기준(단일 색이면 base/light/dark
    변형, 2색이면 그 조합의 light/dark 변형)으로 num_images장을 만든다.
    지정하지 않으면 카테고리 팔레트(config.BG_PALETTES)에서 가져온다.

    반환: [{"mode": mode, "colors": [...], "direction": ... }, ...] (길이 num_images)
    각 draft에 실제로 적용된 색을 그대로 담아 반환하므로, 사용자가 지정한 색과
    달라졌더라도(예: light/dark 변형) 응답만 보면 어떤 색이 쓰였는지 알 수 있다.
    """
    category = category or config.DEFAULT_CATEGORY
    palette = config.BG_PALETTES.get(category, config.BG_PALETTES[config.DEFAULT_CATEGORY])
    delta = config.BG_VARIANT_LIGHTNESS_DELTA

    if mode == "solid":
        if colors:
            base = colors[0]
            variants = [base, _shift_lightness(base, delta), _shift_lightness(base, -delta)]
        else:
            variants = list(palette)
        return [{"mode": "solid", "colors": [variants[i % len(variants)]], "direction": None}
                for i in range(num_images)]

    # gradient
    dir_final = direction or "vertical"
    if colors and len(colors) >= 2:
        c1, c2 = colors[0], colors[1]
        pairs = [(c1, c2),
                (_shift_lightness(c1, delta), _shift_lightness(c2, delta)),
                (_shift_lightness(c1, -delta), _shift_lightness(c2, -delta))]
    elif colors and len(colors) == 1:
        # gradient인데 색을 1개만 준 경우: 그 색 + 팔레트에서 가장 다른 색으로 짝을 만든다
        c1 = colors[0]
        c2 = palette[0] if palette[0] != c1 else palette[1]
        pairs = [(c1, c2),
                (_shift_lightness(c1, delta), _shift_lightness(c2, delta)),
                (_shift_lightness(c1, -delta), _shift_lightness(c2, -delta))]
    else:
        pairs = [(palette[i % len(palette)], palette[(i + 1) % len(palette)])
                for i in range(len(palette))]

    return [{"mode": "gradient", "colors": list(pairs[i % len(pairs)]), "direction": dir_final}
            for i in range(num_images)]

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


def prepare_image(src, size: int) -> tuple[Image.Image, MaskResult, str]:
    """입력 이미지를 생성 가능한 형태로 준비한다.

    제품이 화면을 꽉 채우면 배경 재생성 영역이 부족해 배경이 바뀌지 않으므로,
    area_ratio가 임계값을 넘으면 자동으로 여백을 확보한다.

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
    if masks.area_ratio <= config.AREA_THRESHOLD:
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


def render_flat_background(size: int,
                           colors: list[str],
                           direction: str = None) -> Image.Image:
    """단색 또는 2색 그라데이션 배경을 생성한다 (diffusion 완전 생략, PIL만 사용).

    colors가 1개면 단색, 2개 이상이면 첫 두 색으로 direction 방향
    (vertical/horizontal/diagonal) 선형 그라데이션을 만든다.
    """
    if len(colors) <= 1:
        return Image.new("RGB", (size, size), _hex_to_rgb(colors[0]))

    c1 = np.array(_hex_to_rgb(colors[0]), dtype=np.float32)
    c2 = np.array(_hex_to_rgb(colors[1]), dtype=np.float32)
    direction = direction or "vertical"

    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32) / max(size - 1, 1)
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

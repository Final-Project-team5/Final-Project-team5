"""Renderer 골격 — Step 4.

    RenderPlan + ProductRenderAsset (+ BackgroundRenderAsset)  →  pixels

**이 계층은 디자인 판단을 하지 않는다.**

```text
✗ 어떤 grid 가 더 좋은지 판단      ✗ 색을 새로 선택
✗ font weight 를 임의 변경        ✗ copy 위치 재배치
✗ product 크기 다시 판단          ✗ design_language 로 template 분기
```

Renderer 가 하는 일은 하나다 — **RenderPlan 에 확정된 geometry/style 과
명시적으로 넘겨받은 픽셀 asset 을 layer 순서대로 그린다.**

그래서 이 모듈은 `plan.design_language` 를 읽지 않는다. 애초에 RenderPlan 에
그 필드가 없다 (§6 R1). 색은 `plan.palette`, 배경은 `plan.background`,
제품 픽셀은 인자로 받은 asset 에서만 온다.

결정론
    같은 RenderPlan + 같은 asset + 같은 Pillow → 같은 픽셀.
    난수를 쓰는 곳은 그레인 하나뿐이고, seed 를 plan 에서 유도해 고정한다.
"""

from __future__ import annotations

import hashlib
import json
import random
from typing import Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw

from .assets import BackgroundRenderAsset, ProductRenderAsset
from .background import require_supported
from .errors import RenderUnsupported
from .evidence import ElementEvidence, RenderEvidence
from .policy import DEFAULT_POLICY
from .fonts import FontBook, ResolvedFont, round_half_up
from .geometry import ProductGeometry
from .palette import RGB
from .plan import RenderPlan, ResolvedCopyBlock, ResolvedMotif

RENDERER_VERSION = "0.4.0"

# 그레인 타일 크기 — 캔버스 전체에 난수를 뿌리면 느리고, 타일을 반복하면
# 결정론이 쉬워진다
GRAIN_TILE = 64


# ──────────────────────────────────────────────────────────────────────────
# 배경
# ──────────────────────────────────────────────────────────────────────────
def _lerp(a: int, b: int, num: int, den: int) -> int:
    return a + (b - a) * num // max(1, den)


def _gradient(size: Tuple[int, int], c0: RGB, c1: RGB, direction: str) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    if direction == "vertical":
        for y in range(h):
            draw.line([(0, y), (w, y)], fill=tuple(_lerp(c0[i], c1[i], y, h - 1) for i in range(3)))
    elif direction == "horizontal":
        for x in range(w):
            draw.line([(x, 0), (x, h)], fill=tuple(_lerp(c0[i], c1[i], x, w - 1) for i in range(3)))
    else:  # diagonal — 좌상 → 우하
        span = w + h - 2
        for d in range(span + 1):
            color = tuple(_lerp(c0[i], c1[i], d, span) for i in range(3))
            draw.line([(max(0, d - h + 1), min(d, h - 1)), (min(d, w - 1), max(0, d - w + 1))],
                      fill=color)
    return img


def _apply_grain(img: Image.Image, amplitude: int, seed: int) -> Image.Image:
    """결정론적 그레인. seed 를 plan 에서 유도하므로 실행마다 같다."""
    if amplitude <= 0:
        return img
    rng = random.Random(seed)
    tile = [rng.randint(-amplitude, amplitude) for _ in range(GRAIN_TILE * GRAIN_TILE)]
    w, h = img.size
    px = img.load()
    for y in range(h):
        row = (y % GRAIN_TILE) * GRAIN_TILE
        for x in range(w):
            n = tile[row + (x % GRAIN_TILE)]
            r, g, b = px[x, y][:3]
            px[x, y] = (
                min(255, max(0, r + n)),
                min(255, max(0, g + n)),
                min(255, max(0, b + n)),
            )
    return img


def render_background(
    plan: RenderPlan, asset: Optional[BackgroundRenderAsset], seed: int
) -> Image.Image:
    bg = plan.background
    size = (plan.canvas_width, plan.canvas_height)

    if bg.mode == "generated":
        if asset is None:                      # require_supported 가 먼저 걸러 준다
            raise RenderUnsupported(
                "background.generated_requires_asset", "background.mode", "asset 이 없다"
            )
        return asset.image.convert("RGB").copy()

    if bg.mode == "flat":
        img = Image.new("RGB", size, bg.base_color)
    else:
        img = _gradient(size, bg.gradient_from, bg.gradient_to, bg.gradient_direction)

    return _apply_grain(img, bg.grain_amplitude, seed)


# ──────────────────────────────────────────────────────────────────────────
# 제품
# ──────────────────────────────────────────────────────────────────────────
def render_product(
    plan: RenderPlan, asset: ProductRenderAsset, geometry: ProductGeometry
) -> Image.Image:
    """cutout → mask bbox 로 자르고 → 회전 → plan 이 정한 크기로.

    asset 을 제자리에서 고치지 않는다 — 항상 새 이미지를 만든다.
    """
    x0, y0, x1, y1 = geometry.mask_bbox
    cropped = asset.image.crop((x0, y0, x1 + 1, y1 + 1))    # 포함 → 제외 규약

    if plan.product.rotation_deg:
        cropped = cropped.rotate(
            -plan.product.rotation_deg, resample=Image.BICUBIC, expand=True
        )

    bx0, by0, bx1, by1 = plan.product.bbox_px
    return cropped.resize((max(1, bx1 - bx0), max(1, by1 - by0)), Image.LANCZOS)


# ──────────────────────────────────────────────────────────────────────────
# 타이포
# ──────────────────────────────────────────────────────────────────────────
def _draw_horizontal_line(
    draw: ImageDraw.ImageDraw,
    book: FontBook,
    font: ResolvedFont,
    text: str,
    x: int,
    y: int,
    tracking: int,
    fill: RGB,
) -> None:
    loaded = book.load(font)
    if tracking == 0:
        draw.text((x, y), text, font=loaded, fill=fill, anchor="la")
        return
    cx = x
    for ch in text:                       # 측정도 같은 방식이라 폭이 정확히 일치한다
        draw.text((cx, y), ch, font=loaded, fill=fill, anchor="la")
        cx += book.char_advance_px(font, ch) + tracking


def _draw_vertical_column(
    draw: ImageDraw.ImageDraw,
    book: FontBook,
    font: ResolvedFont,
    text: str,
    x: int,
    y: int,
    tracking: int,
    fill: RGB,
) -> None:
    loaded = book.load(font)
    cy = y
    for ch in text:
        draw.text((x, cy), ch, font=loaded, fill=fill, anchor="la")
        cy += font.size_px + tracking     # 세로는 em 사각형 진행 (fonts.py 와 동일)


def char_boxes_of(book: FontBook, font: ResolvedFont, block: ResolvedCopyBlock,
                  x0: int, x1: int, y0: int) -> Tuple[Tuple[int, int, int, int], ...]:
    """가로쓰기 블록의 **글자 단위 상자**. 핵심 글자 가림 판정에 쓴다.

    자간이 0 일 때 한 줄을 통째로 그리므로 커닝이 들어간다. 여기서는 글자별
    advance 를 누적해 근사한다 (±1px). 획 단위 가림 비율을 재는 용도라 이 정도면
    충분하고, **그림자처럼 없는 것을 만들어 내지 않는다**.
    """
    if block.orientation != "horizontal":
        return ()
    out = []
    for i, line in enumerate(block.lines):
        ly = y0 + i * block.line_height_px
        cx = _line_x(block, i, x0, x1)
        for ch in line:
            adv = book.char_advance_px(font, ch)
            if not ch.isspace():
                out.append((cx, ly, cx + adv, ly + block.line_height_px))
            cx += adv + block.tracking_px
    return tuple(out)


def _line_x(block: ResolvedCopyBlock, i: int, x0: int, x1: int) -> int:
    width = block.line_widths_px[i]
    if block.align == "right":
        return x1 - width
    if block.align == "center":
        return x0 + (x1 - x0 - width) // 2
    return x0


def _font_of(block: ResolvedCopyBlock) -> ResolvedFont:
    """RenderPlan 이 확정한 서체를 그대로 되살린다 (새로 고르지 않는다)."""
    return ResolvedFont(
        family=block.font_family,
        weight=block.font_weight,
        path=block.font_path,
        size_px=block.size_px,
        substituted=block.font_substituted,
        substitution_reason="",
    )


def draw_copy_block(
    canvas: Image.Image, book: FontBook, block: ResolvedCopyBlock, fill: RGB
) -> None:
    font = _font_of(block)
    x0, y0, x1, y1 = block.bbox_px

    if block.orientation == "horizontal":
        draw = ImageDraw.Draw(canvas)
        for i, line in enumerate(block.lines):
            _draw_horizontal_line(
                draw,
                book,
                font,
                line,
                _line_x(block, i, x0, x1),
                y0 + i * block.line_height_px,
                block.tracking_px,
                fill,
            )
        return

    if block.orientation in ("rotate_ccw", "rotate_cw"):
        # **가로로 짠 글줄을 통째로 눕힌다.** 글자를 하나씩 쌓는 세로쓰기와 다르다 —
        # 로마자 캡션("NEW ARRIVAL")을 쌓으면 글자가 낱개로 흩어져 읽히지 않는다
        text_w = max(block.line_widths_px)
        text_h = len(block.lines) * block.line_height_px
        layer = Image.new("RGBA", (max(1, text_w), max(1, text_h)), (0, 0, 0, 0))
        ldraw = ImageDraw.Draw(layer)
        for i, line in enumerate(block.lines):
            _draw_horizontal_line(
                ldraw,
                book,
                font,
                line,
                _line_x(block, i, 0, text_w),
                i * block.line_height_px,
                block.tracking_px,
                fill,
            )
        angle = 90 if block.orientation == "rotate_ccw" else -90
        rotated = layer.rotate(angle, expand=True)
        canvas.alpha_composite(rotated, (x0, y0))
        return

    # 진짜 세로쓰기 — vertical_rl 은 오른쪽 열부터
    draw = ImageDraw.Draw(canvas)
    for i, column in enumerate(block.lines):
        if block.orientation == "vertical_rl":
            cx = x1 - (i + 1) * block.line_height_px
        else:
            cx = x0 + i * block.line_height_px
        _draw_vertical_column(draw, book, font, column, cx, y0, block.tracking_px, fill)


# ──────────────────────────────────────────────────────────────────────────
# 모티프
# ──────────────────────────────────────────────────────────────────────────
def draw_motif(canvas: Image.Image, motif: ResolvedMotif, plan: RenderPlan) -> None:
    draw = ImageDraw.Draw(canvas)
    for box, role in zip(motif.boxes, motif.color_roles):
        color = plan.palette.rgb(role)
        x0, y0, x1, y1 = box
        if x1 <= x0 or y1 <= y0:
            continue
        if motif.shape in ("rule", "block"):
            draw.rectangle([x0, y0, x1 - 1, y1 - 1], fill=color)
        elif motif.shape == "circle":
            draw.ellipse([x0, y0, x1 - 1, y1 - 1], fill=color)
        elif motif.shape == "frame":
            draw.rectangle([x0, y0, x1 - 1, y1 - 1], outline=color, width=motif.weight_px)
        elif motif.shape == "diagonal":
            if motif.angle_deg < 0:
                draw.line([x0, y1 - 1, x1 - 1, y0], fill=color, width=motif.weight_px)
            else:
                draw.line([x0, y0, x1 - 1, y1 - 1], fill=color, width=motif.weight_px)


# ──────────────────────────────────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────────────────────────────────
def _seed_from(plan: RenderPlan) -> int:
    """그레인 seed 는 **배경 파라미터에서만** 유도한다.

    처음에는 plan 전체 digest 를 썼는데, 그러면 문구 한 글자만 바뀌어도 배경
    노이즈가 통째로 다시 뽑혀 "무엇이 달라졌는지" 비교가 불가능해진다.
    그레인은 배경의 성질이므로 배경 입력에만 묶는다.
    """
    payload = json.dumps(
        {
            "background": plan.background.as_dict(),
            "canvas": [plan.canvas_width, plan.canvas_height],
        },
        sort_keys=True,
    )
    return int(hashlib.sha256(payload.encode()).hexdigest()[:8], 16)


class _Compositor:
    """요소를 **한 번씩** 자기 레이어에 그려 합성하면서 근거를 모은다.

    Validator 가 나중에 다시 그리지 않도록, `alpha_composite` 에 넘긴 바로 그
    알파를 잉크 마스크로 남긴다. 합성 순서대로 진행하므로 "나중 레이어가 덮은
    부분"도 그 자리에서 깎아 낼 수 있다.
    """

    def __init__(self, canvas: Image.Image, policy) -> None:
        self.canvas = canvas
        self.policy = policy
        self.records: list = []

    def add(self, layer_img: Image.Image, *, id: str, kind: str, layer: str,
            bbox, color=None, capture_under: bool = False, **extra) -> np.ndarray:
        alpha = np.array(layer_img)[:, :, 3]
        ink = alpha >= self.policy.ink_alpha_min

        under = None
        if capture_under and ink.any():
            # **깔려 있던** 픽셀 — 이 요소를 합성하기 직전의 캔버스다.
            # 대비를 팔레트 값끼리 비교하지 않고 실제 바탕에서 재기 위한 것
            under = np.array(self.canvas)[:, :, :3][ink].astype(np.uint8)

        covered = alpha >= self.policy.cover_alpha_min
        for rec in self.records:                    # 이전 요소를 덮은 만큼 깎는다
            rec["visible"] = rec["visible"] & ~covered

        self.canvas.alpha_composite(layer_img)
        self.records.append(
            dict(id=id, kind=kind, layer=layer, bbox=tuple(bbox), ink=ink,
                 visible=ink.copy(), color=color, under=under, **extra)
        )
        return ink

    def elements(self) -> Tuple[ElementEvidence, ...]:
        return tuple(
            ElementEvidence(
                id=r["id"], kind=r["kind"], layer=r["layer"], bbox=r["bbox"],
                ink=r["ink"], visible=r["visible"], color=r.get("color"),
                under=r.get("under"), char_boxes=r.get("char_boxes", ()),
                size_px=r.get("size_px", 0), weight=r.get("weight", ""),
                intended_bbox=r.get("intended_bbox"),
            )
            for r in self.records
        )


def _blank(plan: RenderPlan) -> Image.Image:
    return Image.new("RGBA", (plan.canvas_width, plan.canvas_height), (0, 0, 0, 0))


def render_with_evidence(
    plan: RenderPlan,
    product_asset: ProductRenderAsset,
    geometry: ProductGeometry,
    background_asset: Optional[BackgroundRenderAsset] = None,
    book: Optional[FontBook] = None,
    policy=None,
) -> Tuple[Image.Image, RenderEvidence]:
    """RenderPlan 을 그대로 그리고, 합성에 쓴 근거를 함께 돌려준다."""
    require_supported(plan.background, background_asset is not None)
    geometry.validate()
    product_asset.validate(geometry)
    if background_asset is not None:
        background_asset.validate(plan.canvas_width, plan.canvas_height)

    book = book or FontBook()
    policy = policy or DEFAULT_POLICY
    canvas = render_background(plan, background_asset, _seed_from(plan)).convert("RGBA")
    comp = _Compositor(canvas, policy)

    motifs_by_layer: dict = {}
    for m in plan.motifs:
        motifs_by_layer.setdefault(m.layer, []).append(m)
    blocks_by_layer: dict = {}
    for b in plan.copy_blocks:
        blocks_by_layer.setdefault(b.layer, []).append(b)

    product_alpha = np.zeros((plan.canvas_height, plan.canvas_width), dtype=bool)

    for layer in plan.layers:                       # 스택 순서 그대로 (§3-2)
        if layer == "background":
            continue                                # 이미 깔았다

        if layer == "product":
            sprite = render_product(plan, product_asset, geometry)
            sheet = _blank(plan)
            # 마스크 없이 **RGBA 를 그대로** 옮긴다. mask 를 주면 여기서 한 번,
            # alpha_composite 에서 또 한 번 섞여 반투명 가장자리가 두 번 블렌딩된다
            sheet.paste(sprite, (plan.product.bbox_px[0], plan.product.bbox_px[1]))
            product_alpha = comp.add(
                sheet, id="__product__", kind="product", layer="product",
                bbox=plan.product.bbox_px, intended_bbox=plan.product.bbox_px,
            )
            continue

        for motif in motifs_by_layer.get(layer, []):
            sheet = _blank(plan)
            draw_motif(sheet, motif, plan)
            box = (
                min(b[0] for b in motif.boxes), min(b[1] for b in motif.boxes),
                max(b[2] for b in motif.boxes), max(b[3] for b in motif.boxes),
            ) if motif.boxes else (0, 0, 0, 0)
            comp.add(sheet, id=motif.role, kind="motif", layer=layer, bbox=box,
                     color=plan.palette.rgb(motif.color_roles[0]), intended_bbox=box)

        for block in blocks_by_layer.get(layer, []):
            fill = plan.palette.rgb(block.color_role)
            sheet = _blank(plan)
            draw_copy_block(sheet, book, block, fill)
            font = _font_of(block)
            x0, y0, x1, _ = block.bbox_px
            comp.add(
                sheet, id=block.id, kind="copy", layer=layer, bbox=block.bbox_px,
                color=fill, capture_under=True,
                char_boxes=char_boxes_of(book, font, block, x0, x1, y0),
                size_px=block.size_px, weight=block.font_weight,
                intended_bbox=block.bbox_px,
            )

    evidence = RenderEvidence(
        canvas_width=plan.canvas_width,
        canvas_height=plan.canvas_height,
        elements=comp.elements(),
        product_alpha=product_alpha,
        renderer_version=RENDERER_VERSION,
        plan_digest=plan.digest(),
    )
    return canvas.convert("RGB"), evidence


def render(
    plan: RenderPlan,
    product_asset: ProductRenderAsset,
    geometry: ProductGeometry,
    background_asset: Optional[BackgroundRenderAsset] = None,
    book: Optional[FontBook] = None,
) -> Image.Image:
    """RenderPlan 을 그대로 그린다. 새로운 판단은 하지 않는다."""
    image, _ = render_with_evidence(plan, product_asset, geometry, background_asset, book)
    return image


def render_digest(image: Image.Image) -> str:
    return hashlib.sha256(image.convert("RGB").tobytes()).hexdigest()[:16]


__all__ = [
    "RENDERER_VERSION",
    "render",
    "render_with_evidence",
    "char_boxes_of",
    "render_background",
    "render_product",
    "draw_copy_block",
    "draw_motif",
    "render_digest",
]

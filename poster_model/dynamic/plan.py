"""RenderSpec → RenderPlan — Step 3.

**그리지는 않지만 측정은 한다.**

    RenderSpec + CreativeBrief + ProductGeometry
            ↓
      1  Grid resolve          (Step 2)
      2  Zone resolve
      3  Product bbox resolve
      4  Typography style resolve
      5  Text measure / line break
      6  Copy bbox resolve
      7  Motif geometry resolve
            ↓
      RenderPlan               무엇을 · 어디에 · 어떤 크기로 가 전부 결정됨
            ↓
      Step 4 Renderer          그대로 그리기만 한다

경계 — Step 4 가 디자인 판단을 다시 하지 않게 한다. 크기·좌표·줄바꿈·서체
파일이 전부 여기서 확정된다. Renderer 에 남는 결정은 "픽셀을 어떻게 칠하는가"
뿐이다.

좌표 규약 — RenderPlan 의 모든 bbox 는 `(x0, y0, x1, y1)` 이고 **끝값은
제외**한다 (`width = x1 - x0`). 입력인 `ProductGeometry.mask_bbox` 만
production 규약을 따라 **끝값을 포함**하며, 그 변환은 이 모듈 경계에서 한 번만
일어난다. 두 규약을 섞으면 1px 씩 어긋난다.

CreativeBrief 는 **필수**다. 해석되지 않은 참조를 들고 렌더링에 들어가면
"빈 블록이 조용히 사라지는" 형태로 나타나는데, 그것도 조용한 보정이다.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .background import ResolvedBackground, resolve_background
from .brief import CreativeBrief, known_content_refs, resolve_content_ref
from .errors import AnchorUnresolvable, ContentRefUnresolved, PlanUnresolvable
from .palette import ResolvedPalette, resolve_palette
from .fonts import FontBook, ResolvedFont, round_half_up
from .geometry import ProductGeometry
from .grid import CanvasSize, ResolvedGrid, resolve_grid, round_half_up_div
from .spec import (
    ABSOLUTE_ROWS,
    LAYER_STACK,
    PALETTE_ROLE_TRANSITION,
    PRODUCT_ROW_ALIGNS,
    PRODUCT_ROW_SEQUENCE,
    ROTATED_ORIENTATIONS,
    ROW_REL_PREFIXES,
    STACKED_ORIENTATIONS,
    GridRef,
    RenderSpec,
)
from .text import break_lines
from .validate import PLANNER_CONTEXT, ValidationContext

PLAN_VERSION = "0.4"   # RenderPlan 구조 버전. schema_version 과 별개 축이다

# ── Renderer 상수 (Planner 가 정하지 않는 값) ─────────────────────────────
# 타입 스케일의 기준. design_language 로 분기하지 않는다 (§6 R1) — 언어별
# 차이는 Planner 가 size_step 으로 표현한다
TYPE_BASE_PERMILLE = 60          # short_side 의 6% 가 step 0
TYPE_RATIO_NUM, TYPE_RATIO_DEN = 5, 4   # 1.25 를 정수비로

# space_after → baseline 배수 (§ TypeRole.space_after)
SPACE_AFTER_BASELINES: Dict[str, int] = {"none": 0, "tight": 1, "normal": 2, "loose": 3}

# product.rotation 은 **의도**이고 도수는 여기 있다 (§3 product.rotation)
ROTATION_DEG: Dict[str, int] = {"none": 0, "slight_ccw": -6, "slight_cw": 6}

# motif 선 굵기 = baseline // divisor
MOTIF_WEIGHT_DIVISOR: Dict[str, int] = {"hair": 8, "thick": 2}

# 절대 row anchor 가 블록의 어느 변을 맞추는가
#   top                     상단
#   upper / center / lower  블록 **중심**을 해당 row 에 맞추고 baseline 으로 스냅
#   bottom                  하단
ANCHOR_EDGE: Dict[str, str] = {
    "top": "top",
    "upper": "middle",
    "center": "middle",
    "lower": "middle",
    "bottom": "bottom",
}


# ──────────────────────────────────────────────────────────────────────────
# 자료구조 — 전부 해석이 끝난 값만 담는다
# ──────────────────────────────────────────────────────────────────────────
Box = Tuple[int, int, int, int]


@dataclass(frozen=True)
class ResolvedZones:
    type_box: Box
    product_box: Box
    shared_box: Optional[Box]
    overlap_intent: str


@dataclass(frozen=True)
class ResolvedProduct:
    bbox_px: Box
    rotation_deg: int
    scale_milli: int
    source_bbox_px: Box            # cutout 안의 제품 범위 (끝값 제외로 변환됨)
    grounding: str
    layer: str
    bleed: Tuple[str, ...] = ()    # 선언된 이탈 허용 방향.  Step 6 이 이걸 본다

    @property
    def scale(self) -> float:
        return self.scale_milli / 1000


@dataclass(frozen=True)
class ResolvedCopyBlock:
    id: str
    role: str
    text: str                      # transform 적용 후 실제 그릴 문자열
    source_text: str               # CreativeBrief 원문
    font_path: str
    font_family: str
    font_weight: str
    font_substituted: bool
    size_px: int
    line_height_px: int
    tracking_px: int
    lines: Tuple[str, ...]
    line_widths_px: Tuple[int, ...]
    bbox_px: Box
    measure_px: int
    align: str
    orientation: str
    layer: str
    color_role: str
    priority: int
    first_row: int
    last_row: int


@dataclass(frozen=True)
class ResolvedMotif:
    role: str
    shape: str
    boxes: Tuple[Box, ...]
    color_roles: Tuple[str, ...]   # boxes 와 같은 길이 (색 전환 표기 전개)
    weight_px: int
    angle_deg: int
    orientation: str
    layer: str
    from_pattern: bool


@dataclass(frozen=True)
class RenderPlan:
    plan_version: str
    schema_version: str
    canvas_width: int
    canvas_height: int
    grid: ResolvedGrid
    zones: ResolvedZones
    product: ResolvedProduct
    palette: ResolvedPalette
    background: ResolvedBackground
    copy_blocks: Tuple[ResolvedCopyBlock, ...]
    motifs: Tuple[ResolvedMotif, ...]
    layers: Tuple[str, ...]
    critical_blocks: Tuple[str, ...]
    must_be_visible: Tuple[str, ...]
    palette_roles: Tuple[str, ...]
    font_substitutions: Tuple[str, ...]

    def draw_order(self) -> Tuple[str, ...]:
        """Renderer 가 그릴 순서 — layer 스택 그대로."""
        return self.layers

    def type_product_relation(self) -> dict:
        """문구 블록과 제품의 **실제 2D 관계**를 잰다 (§4-7).

        여기서는 **재기만 하고 판정하지 않는다** — 판정은 Step 6 Validator 몫이다.

        책임 분리를 그대로 반영한다.

            overlap_intent   겹치는가 / 겹쳐도 되는가   → 최상위 `overlap_px`
            layer            겹쳤을 때 누가 위인가      → 블록별 `above`

        한 판면 안에서 headline 은 제품 뒤, token 은 제품 앞인 mixed 구성이
        실제로 존재하므로 z-order 는 **블록 단위로만** 의미가 있다.

        Returns
            overlap_px   제품 bbox 와 겹치는 문구 bbox 면적의 합
            per_block    { id: {ratio, above, layer} }
                         above = "type"   글자가 제품 위 → 대비를 잰다
                         above = "product" 제품이 글자 위 → 가림을 잰다
            summary      "type" | "product" | "mixed" | None (겹침 없음)
                         **판정용이 아니라 요약용이다**
        """
        px0, py0, px1, py1 = self.product.bbox_px
        product_index = self.layers.index("product")

        total = 0
        per_block: dict = {}
        seen: set = set()

        for b in self.copy_blocks:
            bx0, by0, bx1, by1 = b.bbox_px
            w = max(0, min(px1, bx1) - max(px0, bx0))
            h = max(0, min(py1, by1) - max(py0, by0))
            area = w * h
            if area <= 0:
                continue
            total += area
            block_area = max(1, (bx1 - bx0) * (by1 - by0))
            above = "type" if self.layers.index(b.layer) > product_index else "product"
            seen.add(above)
            per_block[b.id] = {
                "ratio": round(area / block_area, 4),
                "above": above,
                "layer": b.layer,
            }

        summary = None
        if total:
            summary = seen.pop() if len(seen) == 1 else "mixed"
        return {
            "overlap_px": total,
            "per_block": per_block,
            "summary": summary,
            "declared": self.zones.overlap_intent,
        }

    def as_dict(self) -> dict:
        def box(b):
            return list(b) if b else None

        return {
            "plan_version": self.plan_version,
            "schema_version": self.schema_version,
            "canvas": [self.canvas_width, self.canvas_height],
            "grid": self.grid.as_dict(),
            "zones": {
                "type": box(self.zones.type_box),
                "product": box(self.zones.product_box),
                "shared": box(self.zones.shared_box),
                "overlap_intent": self.zones.overlap_intent,
            },
            "product": {
                "bbox": box(self.product.bbox_px),
                "rotation_deg": self.product.rotation_deg,
                "scale_milli": self.product.scale_milli,
                "grounding": self.product.grounding,
                "layer": self.product.layer,
            },
            "copy_blocks": [
                {
                    "id": b.id,
                    "text": b.text,
                    "font": b.font_path.split("/")[-1],
                    "size_px": b.size_px,
                    "line_height_px": b.line_height_px,
                    "tracking_px": b.tracking_px,
                    "lines": list(b.lines),
                    "line_widths_px": list(b.line_widths_px),
                    "bbox": box(b.bbox_px),
                    "rows": [b.first_row, b.last_row],
                    "align": b.align,
                    "orientation": b.orientation,
                    "layer": b.layer,
                    "color_role": b.color_role,
                }
                for b in self.copy_blocks
            ],
            "motifs": [
                {
                    "role": m.role,
                    "shape": m.shape,
                    "boxes": [list(x) for x in m.boxes],
                    "color_roles": list(m.color_roles),
                    "weight_px": m.weight_px,
                    "angle_deg": m.angle_deg,
                    "orientation": m.orientation,
                    "layer": m.layer,
                    "from_pattern": m.from_pattern,
                }
                for m in self.motifs
            ],
            "palette": self.palette.as_dict(),
            "background": self.background.as_dict(),
            "layers": list(self.layers),
        }

    def digest(self) -> str:
        payload = json.dumps(self.as_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ──────────────────────────────────────────────────────────────────────────
# 격자 좌표 헬퍼
# ──────────────────────────────────────────────────────────────────────────
def col_x0(grid: ResolvedGrid, index: int) -> int:
    return grid.content_x0 + index * (grid.col_w + grid.gutter_px)


def span_box_x(grid: ResolvedGrid, col_start: int, col_span: int) -> Tuple[int, int]:
    x0 = col_x0(grid, col_start)
    x1 = x0 + col_span * grid.col_w + (col_span - 1) * grid.gutter_px
    return x0, x1


def named_region_x(grid: ResolvedGrid, name: str) -> Tuple[int, int]:
    if name == "margin_left":
        return 0, grid.margin_x
    if name == "margin_right":
        return grid.canvas_width - grid.margin_x, grid.canvas_width
    if name == "canvas_edge_left":
        return 0, 0
    if name == "canvas_edge_right":
        return grid.canvas_width, grid.canvas_width
    raise PlanUnresolvable("grid_ref.unknown_region", "grid_ref.col_start", name)


def ref_box_x(grid: ResolvedGrid, ref: GridRef) -> Tuple[int, int]:
    if isinstance(ref.col_start, str):
        return named_region_x(grid, ref.col_start)
    return span_box_x(grid, ref.col_start, ref.col_span or 1)


def content_rows(grid: ResolvedGrid) -> Tuple[int, int]:
    """content 안에서 쓸 수 있는 첫/마지막 baseline row."""
    return grid.content_y0 // grid.baseline_px, grid.content_y1 // grid.baseline_px


def snap_row(grid: ResolvedGrid, y: int) -> int:
    return round_half_up_div(y, grid.baseline_px)


# ──────────────────────────────────────────────────────────────────────────
# 2. zones
# ──────────────────────────────────────────────────────────────────────────
def resolve_zones(spec: RenderSpec, grid: ResolvedGrid) -> ResolvedZones:
    tz = spec.zones.type
    pz = spec.zones.product
    tx0, tx1 = span_box_x(grid, tz.col_start, tz.col_span)
    px0, px1 = span_box_x(grid, pz.col_start, pz.col_span)

    sx0, sx1 = max(tx0, px0), min(tx1, px1)
    shared = (sx0, grid.content_y0, sx1, grid.content_y1) if sx0 < sx1 else None

    return ResolvedZones(
        type_box=(tx0, grid.content_y0, tx1, grid.content_y1),
        product_box=(px0, grid.content_y0, px1, grid.content_y1),
        shared_box=shared,
        overlap_intent=spec.zones.overlap_intent,
    )


# ──────────────────────────────────────────────────────────────────────────
# 3. product
# ──────────────────────────────────────────────────────────────────────────
def _rotated_extent(w: int, h: int, deg: int) -> Tuple[int, int]:
    if deg == 0:
        return w, h
    rad = math.radians(abs(deg))
    cos, sin = math.cos(rad), math.sin(rad)
    return round_half_up(w * cos + h * sin), round_half_up(w * sin + h * cos)


def resolve_product(
    spec: RenderSpec, grid: ResolvedGrid, zones: ResolvedZones, geo: ProductGeometry
) -> ResolvedProduct:
    geo.validate()
    p = spec.product
    deg = ROTATION_DEG[p.rotation]

    # 회전한 뒤의 외곽을 기준으로 맞춘다 — 회전 전 기준으로 맞추면
    # 회전이 zone 을 넘어간다
    ext_w, ext_h = _rotated_extent(geo.bbox_width, geo.bbox_height, deg)
    if ext_w <= 0 or ext_h <= 0:
        raise PlanUnresolvable("product.empty_extent", "product", f"{ext_w}×{ext_h}")

    zx0, _, zx1, _ = zones.product_box
    x_lo = 0 if "left" in p.bleed else zx0
    x_hi = grid.canvas_width if "right" in p.bleed else zx1
    y_lo = 0 if "top" in p.bleed else grid.content_y0
    y_hi = grid.canvas_height if "bottom" in p.bleed else grid.content_y1

    if p.fit == "zone_width":
        scale_milli = round_half_up_div((zx1 - zx0) * 1000, ext_w)
    elif p.fit == "zone_height":
        scale_milli = round_half_up_div((y_hi - y_lo) * 1000, ext_h)
    else:  # area_cap — 넓이 비율.  정수 sqrt 로 결정론을 지킨다
        cap_permille = round_half_up((p.area_cap or 0) * 1000)
        target = 1000 * cap_permille * grid.canvas_width * grid.canvas_height
        scale_milli = math.isqrt(target // (ext_w * ext_h))

    if scale_milli <= 0:
        raise PlanUnresolvable("product.scale_zero", "product.fit", f"{p.fit}")

    w = max(1, round_half_up_div(ext_w * scale_milli, 1000))
    h = max(1, round_half_up_div(ext_h * scale_milli, 1000))

    if p.anchor.x == "left":
        x0 = x_lo
    elif p.anchor.x == "right":
        x0 = x_hi - w
    else:
        x0 = x_lo + (x_hi - x_lo - w) // 2

    if p.anchor.y == "top":
        y0 = y_lo
    elif p.anchor.y == "bottom":
        y0 = y_hi - h
    else:
        y0 = y_lo + (y_hi - y_lo - h) // 2

    bx0, by0, bx1, by1 = geo.mask_bbox
    return ResolvedProduct(
        bbox_px=(x0, y0, x0 + w, y0 + h),
        rotation_deg=deg,
        scale_milli=scale_milli,
        source_bbox_px=(bx0, by0, bx1 + 1, by1 + 1),  # 포함 → 제외 규약 변환
        grounding=p.grounding,
        layer=p.layer,
        bleed=tuple(p.bleed),
    )


# ──────────────────────────────────────────────────────────────────────────
# 4. typography style
# ──────────────────────────────────────────────────────────────────────────
def type_size_px(short_side: int, size_step: int, scale_step: float) -> int:
    """size_step → px. 전부 정수 연산이다 (§4-1 T3 와 같은 이유).

    base = short_side × 6%,  size = base × 1.25^step × scale_step
    1.25 를 5/4 로 두면 거듭제곱도 정수비로 남는다.
    """
    scale_milli = round_half_up(scale_step * 1000)
    num = short_side * TYPE_BASE_PERMILLE * scale_milli
    den = 1000 * 1000
    if size_step >= 0:
        num *= TYPE_RATIO_NUM ** size_step
        den *= TYPE_RATIO_DEN ** size_step
    else:
        num *= TYPE_RATIO_DEN ** (-size_step)
        den *= TYPE_RATIO_NUM ** (-size_step)
    return max(1, round_half_up_div(num, den))


def line_height_px(size_px: int, line_ratio: float, baseline: int) -> int:
    """행간을 **baseline 배수로 스냅**한다.

    스냅하지 않으면 블록마다 세로 격자가 조금씩 어긋나고, 여러 블록이 같은
    정렬선을 공유한다는 전제(E11 §2 ①)가 깨진다.
    """
    raw = round_half_up(size_px * line_ratio)
    units = max(1, round_half_up_div(raw, baseline))
    return units * baseline


@dataclass(frozen=True)
class TypeStyle:
    role_id: str
    font: ResolvedFont
    size_px: int
    line_height_px: int
    tracking_px: int
    align: str
    max_lines: int
    transform: str
    color_role: str
    space_after_px: int


def resolve_type_styles(
    spec: RenderSpec, grid: ResolvedGrid, book: FontBook
) -> Dict[str, TypeStyle]:
    styles: Dict[str, TypeStyle] = {}
    for role in spec.typography.roles:
        size = type_size_px(grid.short_side, role.size_step, spec.typography.scale_step)
        styles[role.id] = TypeStyle(
            role_id=role.id,
            font=book.resolve(role.family, role.weight, size),
            size_px=size,
            line_height_px=line_height_px(size, role.line_ratio, grid.baseline_px),
            tracking_px=round_half_up(size * role.tracking_em),
            align=role.align,
            max_lines=role.max_lines,
            transform=role.transform,
            color_role=role.color_role,
            space_after_px=SPACE_AFTER_BASELINES[role.space_after] * grid.baseline_px,
        )
    return styles


# ──────────────────────────────────────────────────────────────────────────
# 5·6. copy blocks — 측정 · 줄바꿈 · 배치
# ──────────────────────────────────────────────────────────────────────────
def _resolve_row_anchor(
    *,
    anchor,
    height: int,
    grid: ResolvedGrid,
    placed: Dict[str, Tuple[int, int]],
    styles_of: Dict[str, TypeStyle],
    own_space_after: int,
    product: ResolvedProduct,
    path: str,
) -> int:
    """row_anchor → 블록 상단 y (px). 전부 baseline 배수로 떨어진다."""
    base = grid.baseline_px
    top_row, bottom_row = content_rows(grid)

    if isinstance(anchor, int):          # fixture 경로에서만 검증을 통과한다
        return anchor * base

    if anchor in ABSOLUTE_ROWS:
        if anchor == "top":
            return top_row * base
        if anchor == "bottom":
            return bottom_row * base - height
        span = bottom_row - top_row
        offset = {"upper": span // 4, "center": span // 2, "lower": 3 * span // 4}[anchor]
        centre = (top_row + offset) * base
        return snap_row(grid, centre - height // 2) * base

    if anchor in PRODUCT_ROW_ALIGNS:
        # 제품의 **변에 맞춘다** — 같은 선에 서므로 겹칠 수 있다
        _, py0, _, py1 = product.bbox_px
        if anchor == "align:product_top":
            return snap_row(grid, py0) * base
        return snap_row(grid, py1) * base - height

    if anchor in PRODUCT_ROW_SEQUENCE:
        # 제품 **다음/이전에 잇는다.** align 과 달리 겹치지 않는 쪽으로 붙인다.
        #
        # spacing 소유 — 제품은 타이포 역할이 없어 space_after 를 갖지 못한다.
        # 그래서 **제품과의 관계에서는 놓이는 블록이 자기 space_after 를 쓴다.**
        # 블록끼리의 `after:X` 는 앞선 X 가 소유하는 것과 다르다 (§4-3).
        _, py0, _, py1 = product.bbox_px
        if anchor == "after:product":
            row = -(-py1 // base)              # 제품 하단 **다음** baseline (올림)
            return row * base + own_space_after
        row = py0 // base                      # 제품 상단 **이전** baseline (내림)
        return row * base - own_space_after - height

    prefix = next((x for x in ROW_REL_PREFIXES if anchor.startswith(x)), None)
    if prefix is None:
        raise AnchorUnresolvable("anchor.unknown_form", path, repr(anchor))

    target = anchor[len(prefix):]
    if target not in placed:
        raise AnchorUnresolvable(
            "anchor.unresolved_target",
            path,
            f"{target!r} 가 아직 배치되지 않았다 (해석 순서: 카피 → 모티프)",
        )
    ty0, ty1 = placed[target]
    if prefix == "after:":
        # 앞선 블록이 자기 뒤 여백을 정한다
        gap = styles_of[target].space_after_px if target in styles_of else 0
        return ty1 + gap
    # before: — 이 블록이 자기 뒤 여백을 정한다
    return ty0 - own_space_after - height


def _apply_transform(text: str, transform: str) -> str:
    return text.upper() if transform == "uppercase" else text


def resolve_copy_blocks(
    spec: RenderSpec,
    brief: CreativeBrief,
    grid: ResolvedGrid,
    styles: Dict[str, TypeStyle],
    product: ResolvedProduct,
    book: FontBook,
    placed: Dict[str, Tuple[int, int]],
) -> Tuple[ResolvedCopyBlock, ...]:
    out: List[ResolvedCopyBlock] = []
    measure_cols = spec.typography.measure_cols

    for i, block in enumerate(spec.copy_blocks):
        path = f"copy_blocks[{i}]({block.id})"
        style = styles.get(block.type_role)
        if style is None:
            raise PlanUnresolvable("copy.type_role_unknown", path, block.type_role)

        raw_text = resolve_content_ref(brief, block.content_ref)
        if not raw_text:
            raise ContentRefUnresolved(
                "copy.content_ref_unresolved",
                f"{path}.content_ref",
                f"{block.content_ref!r} 를 해석할 수 없다 "
                f"(해석 가능: {list(known_content_refs(brief))})",
            )
        text = _apply_transform(raw_text, style.transform)

        px0, px1 = ref_box_x(grid, block.grid_ref)
        place_w = px1 - px0
        if place_w <= 0:
            raise PlanUnresolvable("copy.zero_width_placement", path, f"{px0}~{px1}")

        stacked = block.orientation in STACKED_ORIENTATIONS
        rotated = block.orientation in ROTATED_ORIENTATIONS
        vertical = stacked or rotated          # 캔버스에서 세로로 길게 놓인다

        if rotated:
            # 가로로 짠 글줄을 통째로 눕힌다 — 측정은 **가로쓰기 그대로**이고
            # 쓸 수 있는 길이가 화면의 세로 공간이다
            limit = (block.grid_ref.row_span or 0) * grid.baseline_px or (
                grid.content_y1 - grid.content_y0
            )
            measure = lambda s: book.advance_px(style.font, s, style.tracking_px)  # noqa: E731
        elif stacked:
            # 글자를 하나씩 쌓는 진짜 세로쓰기
            limit = grid.content_y1 - grid.content_y0
            measure = lambda s: book.vertical_advance_px(style.font, s, style.tracking_px)  # noqa: E731
        else:
            if isinstance(block.grid_ref.col_start, str):
                limit = place_w                      # 명명 영역은 그 폭이 곧 측정 폭
            else:
                limit = measure_cols * grid.col_w + (measure_cols - 1) * grid.gutter_px
                if limit > place_w:
                    raise PlanUnresolvable(
                        "typography.measure_exceeds_span",
                        path,
                        f"measure_cols {measure_cols} ({limit}px) 가 배치 폭 {place_w}px 보다 넓다",
                    )
            measure = lambda s: book.advance_px(style.font, s, style.tracking_px)  # noqa: E731

        lines = break_lines(text, measure, limit, style.max_lines, spec.typography.break_strategy)
        widths = tuple(measure(line) for line in lines)

        if vertical:
            # 눕힌 글줄이든 쌓은 글자든, 캔버스에서 폭은 줄/열 수 × 행간이다
            block_w = len(lines) * style.line_height_px
            # 길이 축은 글자 진행량이라 baseline 배수가 아니다.
            # 그대로 두면 이 블록만 격자에서 벗어난다 → 위로 올려 스냅한다
            raw_h = max(widths)
            block_h = -(-raw_h // grid.baseline_px) * grid.baseline_px
            if block_w > place_w:
                raise PlanUnresolvable(
                    "copy.vertical_too_wide",
                    path,
                    f"{len(lines)}줄 × {style.line_height_px}px = {block_w}px > {place_w}px",
                )
        else:
            block_w = max(widths)
            block_h = len(lines) * style.line_height_px

        align = block.grid_ref.align or style.align
        if align == "left":
            x0 = px0
        elif align == "right":
            x0 = px1 - block_w
        else:
            x0 = px0 + (place_w - block_w) // 2

        y0 = _resolve_row_anchor(
            anchor=block.grid_ref.row_anchor,
            height=block_h,
            grid=grid,
            placed=placed,
            styles_of={b.id: styles[b.type_role] for b in spec.copy_blocks if b.type_role in styles},
            own_space_after=style.space_after_px,
            product=product,
            path=f"{path}.grid_ref.row_anchor",
        )
        y1 = y0 + block_h

        if y0 < 0 or y1 > grid.canvas_height:
            raise PlanUnresolvable(
                "layout.block_out_of_canvas",
                path,
                f"y {y0}~{y1} 가 캔버스 0~{grid.canvas_height} 를 벗어난다",
            )

        placed[block.id] = (y0, y1)
        out.append(
            ResolvedCopyBlock(
                id=block.id,
                role=block.role,
                text=text,
                source_text=raw_text,
                font_path=style.font.path,
                font_family=style.font.family,
                font_weight=style.font.weight,
                font_substituted=style.font.substituted,
                size_px=style.size_px,
                line_height_px=style.line_height_px,
                tracking_px=style.tracking_px,
                lines=lines,
                line_widths_px=widths,
                bbox_px=(x0, y0, x0 + block_w, y1),
                measure_px=limit,
                align=align,
                orientation=block.orientation,
                layer=block.layer,
                color_role=block.color_role,
                priority=block.priority,
                first_row=y0 // grid.baseline_px,
                last_row=y1 // grid.baseline_px,
            )
        )
    return tuple(out)


# ──────────────────────────────────────────────────────────────────────────
# 7. motif geometry
# ──────────────────────────────────────────────────────────────────────────
def _motif_weight(grid: ResolvedGrid, weight: str) -> int:
    return max(1, grid.baseline_px // MOTIF_WEIGHT_DIVISOR[weight])


def _split_color_roles(color_role: str) -> Tuple[str, ...]:
    return tuple(p.strip() for p in color_role.split(PALETTE_ROLE_TRANSITION))


def resolve_motifs(
    spec: RenderSpec,
    grid: ResolvedGrid,
    product: ResolvedProduct,
    placed: Dict[str, Tuple[int, int]],
    styles_of: Dict[str, TypeStyle],
) -> Tuple[ResolvedMotif, ...]:
    motif = spec.motif
    if motif.shape == "none":
        return ()

    out: List[ResolvedMotif] = []

    for i, inst in enumerate(motif.instances):
        path = f"motif.instances[{i}]({inst.role})"
        weight_px = _motif_weight(grid, inst.weight)
        x0, x1 = ref_box_x(grid, inst.grid_ref)
        rows = inst.grid_ref.row_span
        vertical = inst.orientation == "vertical"

        # orientation 은 `rule` 의 방향을 바꾼다 (§8-4-2).
        # 면 도형(block/circle/frame/diagonal)은 열×행 상자라 방향이 없다
        if motif.shape == "rule":
            height = (rows * grid.baseline_px) if vertical else weight_px
            if vertical and rows is None:
                height = grid.content_y1 - grid.content_y0   # 선언이 없으면 content 전체
        else:
            height = (rows or 1) * grid.baseline_px

        y0 = _resolve_row_anchor(
            anchor=inst.grid_ref.row_anchor,
            height=height,
            grid=grid,
            placed=placed,
            styles_of=styles_of,
            own_space_after=0,
            product=product,
            path=f"{path}.grid_ref.row_anchor",
        )

        roles = _split_color_roles(inst.color_role)
        if vertical and motif.shape == "rule":
            # 세로 rule — 폭이 weight, 높이가 span 이다 (AD-C 좌측 바)
            boxes = ((x0, y0, x0 + weight_px, y0 + height),)
            colors = (roles[0],)
        elif inst.split_at is not None and isinstance(inst.grid_ref.col_start, int):
            xs = col_x0(grid, inst.split_at.col)
            xs = min(max(xs, x0), x1)
            boxes = ((x0, y0, xs, y0 + height), (xs, y0, x1, y0 + height))
            colors = (roles[0], roles[-1])
        else:
            boxes = ((x0, y0, x1, y0 + height),)
            colors = (roles[0],)

        placed[inst.role] = (y0, y0 + height)
        out.append(
            ResolvedMotif(
                role=inst.role,
                shape=motif.shape,
                boxes=boxes,
                color_roles=colors,
                weight_px=weight_px,
                angle_deg=90 if vertical else 0,
                orientation=inst.orientation,
                layer=inst.layer,
                from_pattern=False,
            )
        )

    if motif.pattern is not None:
        out.append(_resolve_pattern(spec, grid, product, placed, styles_of))

    return tuple(out)


def _resolve_pattern(spec, grid, product, placed, styles_of) -> ResolvedMotif:
    """pattern 을 실제 상자들로 전개한다 (§8-1).

    반복 축 — angle 이 `horizontal` 이면 세로로 쌓고, 그 외에는 가로로 늘어놓는다.
    줄무늬는 진행 방향과 수직으로 놓이는 것이 통상이다.
    """
    pat = spec.motif.pattern
    weight_px = _motif_weight(grid, pat.weight)
    rx0, rx1 = ref_box_x(grid, pat.region)
    rows = pat.region.row_span or 1
    region_h = rows * grid.baseline_px
    ry0 = _resolve_row_anchor(
        anchor=pat.region.row_anchor,
        height=region_h,
        grid=grid,
        placed=placed,
        styles_of=styles_of,
        own_space_after=0,
        product=product,
        path="motif.pattern.region.row_anchor",
    )

    unit = grid.col_w + grid.gutter_px if pat.spacing.unit == "col" else grid.baseline_px
    step = max(1, round_half_up(pat.spacing.value * unit))

    vertical_axis = pat.angle == "horizontal"
    run = (pat.repeat - 1) * step + weight_px
    extent = region_h if vertical_axis else (rx1 - rx0)
    start = ry0 if vertical_axis else rx0
    if pat.phase == "center":
        start += (extent - run) // 2

    boxes: List[Box] = []
    for k in range(pat.repeat):
        offset = start + k * step
        if vertical_axis:
            boxes.append((rx0, offset, rx1, offset + weight_px))
        else:
            boxes.append((offset, ry0, offset + weight_px, ry0 + region_h))

    angle_deg = {"horizontal": 0, "vertical": 90, "diagonal_up": -45, "diagonal_down": 45}[
        pat.angle
    ]
    placed[pat.role] = (ry0, ry0 + region_h)
    return ResolvedMotif(
        role=pat.role,
        shape=spec.motif.shape,
        boxes=tuple(boxes),
        color_roles=tuple([_split_color_roles(pat.color_role)[0]] * len(boxes)),
        weight_px=weight_px,
        angle_deg=angle_deg,
        orientation="vertical" if vertical_axis else "horizontal",
        layer=pat.layer,
        from_pattern=True,
    )


# ──────────────────────────────────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────────────────────────────────
def build_plan(
    spec: RenderSpec,
    brief: CreativeBrief,
    geometry: ProductGeometry,
    canvas: Optional[CanvasSize] = None,
    context: Optional[ValidationContext] = None,
    book: Optional[FontBook] = None,
) -> RenderPlan:
    """RenderSpec + CreativeBrief + ProductGeometry → RenderPlan.

    brief 와 geometry 는 **선택 인자가 아니다.** 스키마 단독 검증에서 brief 를
    생략할 수 있는 것은 그 단계에 한정된 완화이고, 실행 경로로 끌고 오지 않는다.
    """
    if not isinstance(brief, CreativeBrief):
        raise PlanUnresolvable(
            "brief.required",
            "build_plan",
            "실행 경로에서는 CreativeBrief 가 필수다 (모든 content_ref 해석 필요)",
        )
    if not isinstance(geometry, ProductGeometry):
        raise PlanUnresolvable(
            "geometry.required",
            "build_plan",
            "ProductGeometry 는 상위 단계가 계산해 명시적으로 넘긴다 — "
            "여기서 파일을 열거나 전역 상태를 보지 않는다",
        )

    ctx = context or PLANNER_CONTEXT
    book = book or FontBook()

    grid = resolve_grid(spec, canvas, ctx)                       # 1
    zones = resolve_zones(spec, grid)                            # 2
    product = resolve_product(spec, grid, zones, geometry)       # 3
    palette = resolve_palette(spec, brief)                       # 3-1  실제 색 확정
    background = resolve_background(spec, palette)               # 3-2  배경 확정
    styles = resolve_type_styles(spec, grid, book)               # 4
    placed: Dict[str, Tuple[int, int]] = {}
    blocks = resolve_copy_blocks(                                # 5·6
        spec, brief, grid, styles, product, book, placed
    )
    styles_by_name = {b.id: styles[b.type_role] for b in spec.copy_blocks if b.type_role in styles}
    motifs = resolve_motifs(spec, grid, product, placed, styles_by_name)   # 7

    subs = tuple(
        sorted(
            {
                f"{b.font_family}/{b.font_weight} → {b.font_path.split('/')[-1]}"
                for b in blocks
                if b.font_substituted
            }
        )
    )

    return RenderPlan(
        plan_version=PLAN_VERSION,
        schema_version=spec.schema_version,
        canvas_width=grid.canvas_width,
        canvas_height=grid.canvas_height,
        grid=grid,
        zones=zones,
        product=product,
        palette=palette,
        background=background,
        copy_blocks=blocks,
        motifs=motifs,
        layers=LAYER_STACK,
        critical_blocks=tuple(spec.safety.critical_blocks),
        must_be_visible=tuple(spec.safety.must_be_visible),
        palette_roles=tuple(spec.palette.roles),
        font_substitutions=subs,
    )


__all__ = [
    "PLAN_VERSION",
    "TYPE_BASE_PERMILLE",
    "SPACE_AFTER_BASELINES",
    "ROTATION_DEG",
    "MOTIF_WEIGHT_DIVISOR",
    "ANCHOR_EDGE",
    "ResolvedZones",
    "ResolvedProduct",
    "ResolvedCopyBlock",
    "ResolvedMotif",
    "RenderPlan",
    "TypeStyle",
    "type_size_px",
    "line_height_px",
    "resolve_zones",
    "resolve_product",
    "resolve_type_styles",
    "resolve_copy_blocks",
    "resolve_motifs",
    "build_plan",
]

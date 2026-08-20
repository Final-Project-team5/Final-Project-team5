"""RenderSpec 자료구조 — E12 v0.3 §3.

Planner 의 디자인 의사결정을 담는다. **픽셀 값이 없다.**
px 은 Renderer 가 RenderPlan 을 만들 때 유도한다 (Step 2/3).

이 모듈은 production `pipeline/` 과 완전히 분리된 경로다. `pipeline` 을
import 하지 않는다 — core_1x1 결과에 영향을 줄 수 있는 경로를 만들지 않는다.

설계 메모
  · `spec_source` 는 여기에 없다.  신뢰된 호출 경로(ValidationContext)가
    정한다 (§4-2 trust boundary).
  · enum / 범위 / 필수 여부는 각 필드의 `metadata` 에 선언한다.  검증기가 이
    메타데이터를 읽어 동작하므로 **제약의 단일 출처**가 된다.
  · dataclass 는 frozen 이다.  검증을 통과한 Spec 이 이후 단계에서 변형되면
    결정론 계약(§9)이 깨진다.
  · 중첩 노드에 `default=None` 이 붙은 것은 dataclass 의 필드 순서 제약을
    피하기 위한 것이고, 실제 필수 여부는 `required` 메타데이터가 정한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

from .color_roles import SUPPORTED_COLOR_ROLES

# ── schema 버전 ─────────────────────────────────────────────────────────
#
# "0.3" → "0.4".  **breaking 변경이라 올렸다.**
#
#   필수 필드 추가 (기존 Spec 이 그대로는 통과하지 못한다)
#       TypeRole.space_after · Palette.background_tone
#       MotifInstance.orientation · MotifPattern.role
#   enum 값 삭제 + 의미 변경
#       overlap_intent  shared / product_over_type / type_over_product  →  제거
#                       none | allowed | required 로 재정의 (z-order 의미 제거)
#   enum 확장 (하위 호환)
#       copy orientation 에 rotate_ccw / rotate_cw
#   허용 범위 축소
#       typography family×weight 를 번들 폰트로 표현 가능한 5조합으로 제한
#
# 버전 정책(§9)은 "의미 변경/삭제 → major" 인데, 우리는 아직 0.x 다.
# **0.x 동안은 minor 자리가 breaking 축이다** — 1.0 은 계약이 굳었을 때 쓴다.
# 그때부터 major 자리로 옮긴다.
#
# 원칙: 하나의 schema_version → 하나의 명확한 schema.
# 의미가 다른 두 스키마가 같은 번호를 쓰게 두지 않는다.
SCHEMA_VERSION = "0.5"

# ── 고정 stacking order (§3 layers).  아래 → 위 ──────────────────────────
LAYER_STACK: Tuple[str, ...] = (
    "background",
    "motif_under",
    "type_under",
    "product",
    "motif_over",
    "type_over",
)

# copy_block / motif 가 고를 수 있는 layer (background·product 는 고정 소유)
TYPE_LAYERS: Tuple[str, ...] = ("type_under", "type_over")
MOTIF_LAYERS: Tuple[str, ...] = ("motif_under", "motif_over")

# ── grid_ref 명명 영역 (§8-4) ────────────────────────────────────────────
NAMED_COL_REGIONS: Tuple[str, ...] = (
    "margin_left",
    "margin_right",
    "canvas_edge_left",
    "canvas_edge_right",
)

# ── row_anchor 문법 (§4-2) ───────────────────────────────────────────────
ABSOLUTE_ROWS: Tuple[str, ...] = ("top", "upper", "center", "lower", "bottom")

# 제품의 **변에 맞춘다** — 블록이 제품과 같은 선에 서게 된다 (겹칠 수 있다)
PRODUCT_ROW_ALIGNS: Tuple[str, ...] = ("align:product_top", "align:product_bottom")

# ★ v0.4 — 제품 **다음/이전에 잇는다.** 위 align 과 다른 관계다.
#
#   align:product_bottom   블록 하단을 제품 하단에 맞춘다  → 제품 위에 겹친다
#   after:product          제품 하단 **다음** baseline 부터  → 제품 아래로 이어진다
#
# 이게 없으면 Planner 는 "제품 위, 문구 아래" 라는 흔한 세로 구성을 좌표 없이
# 표현할 수 없다 (planner 경로에서 정수 row index 는 금지다).
PRODUCT_ROW_SEQUENCE: Tuple[str, ...] = ("after:product", "before:product")

#: anchor 대상으로 예약된 이름. copy block id / motif role 로 쓸 수 없다
RESERVED_ANCHOR_TARGETS: Tuple[str, ...] = ("product",)

ROW_REL_PREFIXES: Tuple[str, ...] = ("after:", "before:")

# ── palette ─────────────────────────────────────────────────────────────
REQUIRED_PALETTE_ROLES: Tuple[str, ...] = ("bg", "ink")
PALETTE_ROLE_TRANSITION = "→"  # "ink→spot" 형태의 색 전환 구분자

# ── 실제로 렌더할 수 있는 (family, weight) 조합 ──────────────────────────
#
# **대체를 허용하지 않는다.** Planner 가 serif/regular 를 골랐는데 결과가
# serif/bold 로 나오면 RenderSpec 을 그대로 렌더한 것이 아니다 — weight 는
# 인상을 만드는 축이라(E11 §1-4) 조용히 바꾸면 디자인이 달라진다.
#
# 그래서 번들된 폰트 파일로 **정확히 표현되는 조합만** 허용하고 나머지는
# 거부한다. 파일이 늘면 이 표에 줄이 는다.
#
#   sans    regular  Pretendard-Regular
#   sans    medium   Pretendard-Medium
#   serif   bold     NanumMyeongjoBold
#   display bold     GmarketSansTTFBold
#   display black    BlackHanSans-Regular
#
# 지금 없는 것 — sans/bold · sans/black · serif/regular · serif/medium ·
#              display/regular · display/medium
# serif/regular(얇은 명조)는 E11 §1-4 가 프리미엄 광고에 필요하다고 지목한
# 조합이라 파일 확보 시 1순위다.
SUPPORTED_TYPE_FACES: Tuple[Tuple[str, str], ...] = (
    ("sans", "regular"),
    ("sans", "medium"),
    ("serif", "bold"),
    ("display", "bold"),
    ("display", "black"),
)


# ── copy_block role ─────────────────────────────────────────────────────
COPY_ROLES: Tuple[str, ...] = (
    "eyebrow",
    "headline",
    "benefit",
    "token",
    "cta",
    "caption",
    "brand",
)

# ── 카피 블록의 쓰기 방향 ────────────────────────────────────────────────
#
# **세로쓰기와 90° 회전은 다르다.** 처음엔 vertical_* 하나로 뭉쳐 뒀는데,
# 그러면 "NEW ARRIVAL" 같은 로마자 캡션이 글자 하나씩 쌓여 나온다.
# AD-C 의 좌측 캡션은 가로로 짠 글줄을 통째로 눕힌 것이었다.
#
#   horizontal    가로쓰기
#   vertical_lr   세로쓰기.  글자를 위→아래로 쌓고 열은 좌→우
#   vertical_rl   세로쓰기.  열이 우→좌 (한글·한자 전통 조판)
#   rotate_ccw    가로 글줄을 **반시계 90°** — 아래에서 위로 읽는다 (에디토리얼 좌측 캡션)
#   rotate_cw     가로 글줄을 **시계 90°**   — 위에서 아래로 읽는다 (우측 캡션)
COPY_ORIENTATIONS: Tuple[str, ...] = (
    "horizontal",
    "vertical_lr",
    "vertical_rl",
    "rotate_ccw",
    "rotate_cw",
)
STACKED_ORIENTATIONS: Tuple[str, ...] = ("vertical_lr", "vertical_rl")
ROTATED_ORIENTATIONS: Tuple[str, ...] = ("rotate_ccw", "rotate_cw")

# ── 겹침 의도 (§4-7) ────────────────────────────────────────────────────
#
# **"겹치는가"만 담는다. "누가 위인가"는 layer 가 담는다.**
#
#   none      type / product 의 실제 2D 겹침이 없어야 한다
#   allowed   겹쳐도 되고 안 겹쳐도 된다.  개별 안전 규칙만 적용한다
#   required  의도한 겹침이 최소 하나는 있어야 한다 (선언-강제, §2-3)
#
# 예전 값 `shared` 는 사실상 allowed 와 같아서 합쳤고,
# `product_over_type` / `type_over_product` 는 z-order 를 중복 표현해서 뺐다.
OVERLAP_INTENTS: Tuple[str, ...] = ("none", "allowed", "required")


# ── 메타데이터 헬퍼 ───────────────────────────────────────────────────────
def merge(*metas) -> dict:
    out: dict = {}
    for m in metas:
        out.update(m)
    return out


def enum(*values) -> dict:
    """문자열 필드의 허용값."""
    return {"enum": tuple(values)}


def choices(*values) -> dict:
    """비문자열(정수 등) 필드의 허용값."""
    return {"choices": tuple(values)}


def rng(lo, hi=None) -> dict:
    """수치 범위 (양끝 포함). `hi=None` 이면 **상한 없음**.

    상한이 다른 필드에 달려 있는 경우가 있다 — grid_ref.col_start 의 상한은
    `grid.columns` 라서 스키마에 고정값으로 적을 수 없다. 임의의 수를 적어
    두면 columns=4 인 Spec 에서도 11 까지 합법으로 보이게 된다.
    """
    return {"range": (lo, hi)}


def item_enum(*values) -> dict:
    """tuple 필드의 각 원소 허용값."""
    return {"item_enum": tuple(values)}


def str_enum(*values) -> dict:
    """int|str 유니온 필드에서 str 쪽만 제한할 때."""
    return {"str_enum": tuple(values)}


def req(*metas) -> dict:
    """default 가 붙어 있어도 실제로는 필수인 필드."""
    return merge({"required": True}, *metas)


def min_items(n: int) -> dict:
    return {"min_items": n}


def layer_of(*allowed) -> dict:
    """layer 필드. 누락/오값 모두 LayerUnassigned 로 보고한다 (H4)."""
    return merge({"required": True, "error": "layer"}, enum(*allowed))


def describe(text: str) -> dict:
    """JSON schema 로 표현하기 어려운 문법을 **설명으로** 남긴다.
    enum 으로 못 적는 `after:<id>` 같은 형태가 프롬프트에서 사라지지 않게 한다."""
    return {"describe": text}


def color_role_field() -> dict:
    """palette.roles 를 참조하는 필드. 교차 검증에서 실제 존재를 확인한다."""
    return {"required": True, "color_role": True}


# ── 공통 구조 ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Canvas:
    ratio: str = field(metadata=enum("1:1", "3:4", "3:1"))


@dataclass(frozen=True)
class Grid:
    columns: int = field(metadata=choices(4, 6, 8, 12))
    margin_density: str = field(metadata=enum("tight", "normal", "loose"))
    gutter_scale: str = field(metadata=enum("tight", "normal", "loose"))
    baseline_scale: str = field(metadata=enum("fine", "normal", "coarse"))


@dataclass(frozen=True)
class ZoneSpan:
    col_start: int = field(metadata=rng(0, 11))
    col_span: int = field(metadata=rng(1, 12))


@dataclass(frozen=True)
class Zones:
    type: ZoneSpan
    product: ZoneSpan
    overlap_intent: str = field(metadata=enum(*OVERLAP_INTENTS))
    # shared zone 은 선언하지 않는다 — type ∩ product 로 유도된다 (§3-1)
    #
    # ★ v0.3 의미 수정 두 번 (§4-7)
    #
    #   ① zone 의 **열 교집합이 아니라** 최종 렌더 요소의 실제 2D 관계를 가리킨다.
    #      zone 은 1차원이라 열이 겹쳐도 세로로 갈라져 안 겹칠 수 있고 그 반대도
    #      성립한다.  판정은 RenderPlan 의 bbox 로 Step 6 이 한다
    #
    #   ② **z-order 의미를 뺐다.**  겹쳤을 때 누가 위인지는 각 요소의 `layer` 가
    #      이미 정확히 선언한다.  한 판면 안에서 headline 은 제품 뒤,
    #      discount_token 은 제품 앞인 mixed 구성이 실제로 존재하므로
    #      (Step 5 C fixture), 최상위 값 하나로 z-order 를 대표할 수 없다


@dataclass(frozen=True)
class GridRef:
    """관계형 위치 참조. **px 없음** (H1).

    col_start 는 열 번호(int) 또는 명명 영역(str) 중 하나다.
    명명 영역을 쓰면 col_span 을 생략한다 — 영역 자체가 범위를 정의한다 (§8-4).
    """

    # 열 번호는 **0-based** 다 — 첫 열이 0 (plan.col_x0 산술 그대로).
    # 상한은 `grid.columns` 에 달려 있어 여기 고정값으로 적지 않는다.
    # 실제 상한 검사는 `col_start + col_span <= columns` 가 담당한다
    col_start: int | str = field(
        metadata=merge(str_enum(*NAMED_COL_REGIONS), rng(0)))
    col_span: Optional[int] = field(default=None, metadata=rng(1, 12))
    row_anchor: int | str = field(default="top", metadata=describe(
        "세로 위치. planner 경로에서는 **의미적 관계만** 쓴다 — "
        "top|upper|center|lower|bottom · after:<block_id> · before:<block_id> · "
        "align:product_top · align:product_bottom · after:product · before:product. "
        "정수 row index 는 fixture 경로 전용이라 planner 가 쓰면 거부된다"))
    row_span: Optional[int] = field(default=None, metadata=rng(1, 512))
    align: Optional[str] = field(default=None, metadata=enum("left", "center", "right"))


@dataclass(frozen=True)
class SplitAt:
    col: int = field(metadata=rng(0, 12))


# ── 제품 ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Anchor:
    x: str = field(metadata=enum("left", "center", "right"))
    y: str = field(metadata=enum("top", "middle", "bottom"))


@dataclass(frozen=True)
class Product:
    fit: str = field(metadata=enum("zone_width", "zone_height", "area_cap"))
    anchor: Optional[Anchor] = field(default=None, metadata=req())
    rotation: str = field(default="none", metadata=enum("none", "slight_ccw", "slight_cw"))
    grounding: str = field(default="none", metadata=enum("none", "contact"))
    area_cap: Optional[float] = field(default=None, metadata=rng(0.01, 1.0))
    bleed: Tuple[str, ...] = field(
        default=(), metadata=item_enum("top", "bottom", "left", "right")
    )
    layer: str = field(default="product", metadata=enum("product"))


# ── 배경 ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Background:
    mode: str = field(metadata=enum("flat", "gradient", "generated"))
    material: str = field(metadata=enum("paper", "studio_sweep", "fabric", "stone", "none"))
    lighting: str = field(metadata=enum("flat", "soft_top", "soft_side", "dramatic"))
    texture: str = field(metadata=enum("none", "subtle_grain", "paper_grain"))
    whitespace_strategy: str = field(metadata=enum("generous", "balanced", "dense"))
    visual_style: Optional[str] = field(default=None, metadata=enum("realistic", "3d"))
    layer: str = field(default="background", metadata=enum("background"))
    # 프롬프트 문자열 없음 — Renderer/server 가 조합에서 파생한다 (§7-3)


# ── 타이포 ────────────────────────────────────────────────────────────────
# 블록 뒤 여백 — baseline 배수로 해석된다 (실제 px 은 Renderer 소관).
# `after:` / `before:` anchor 가 이 값을 쓴다. 숨은 Renderer 상수로 두지 않는 이유는
# **블록 간 간격도 타이포그래피 설계의 일부**이기 때문이다.
SPACE_AFTER_STEPS: Tuple[str, ...] = ("none", "tight", "normal", "loose")


@dataclass(frozen=True)
class TypeRole:
    id: str
    family: str = field(metadata=enum("sans", "serif", "display"))
    weight: str = field(metadata=enum("regular", "medium", "bold", "black"))
    size_step: int = field(metadata=rng(-8, 12))
    line_ratio: float = field(metadata=rng(0.7, 3.0))
    space_after: str = field(default="", metadata=req(enum(*SPACE_AFTER_STEPS)))
    color_role: str = field(default="", metadata=color_role_field())
    tracking_em: float = field(default=0.0, metadata=rng(-0.2, 0.5))
    transform: str = field(default="none", metadata=enum("none", "uppercase"))
    align: str = field(default="left", metadata=enum("left", "center", "right"))
    max_lines: int = field(default=3, metadata=rng(1, 12))


@dataclass(frozen=True)
class Typography:
    measure_cols: int = field(metadata=rng(1, 12))
    break_strategy: str = field(metadata=enum("semantic", "width"))
    roles: Tuple[TypeRole, ...] = field(default=(), metadata=req(min_items(1)))
    scale_step: float = field(default=1.0, metadata=rng(0.5, 2.0))


# ── 색 ────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Rhythm:
    spot_min_regions: int = field(default=1, metadata=rng(1, 12))
    spot_path: str = field(
        default="none", metadata=enum("diagonal", "vertical", "perimeter", "none")
    )


@dataclass(frozen=True)
class Palette:
    strategy: str = field(
        metadata=enum(
            "complementary",
            "analogous",
            "split_complementary",
            "monochromatic",
            "neutral_support",
            "fixed",
        )
    )
    # ★ v0.5.  `preferred` 추가 — 사용자가 고른 색을 seed 로 쓰는 branch.
    #   세 source 는 **독립 branch** 다. resolver 가 임의로 섞지 않는다.
    #     product     product_signals.palette (HEX) 를 seed 로
    #     brand       brand_palette 를 그대로
    #     preferred   brief.preferred_color 를 seed 로
    #   어느 것을 쓸지는 Planner 가 고른다 — 입력이 있다고 강제되지 않는다.
    source: str = field(metadata=enum("product", "brand", "preferred", "fixed"))
    background_tone: str = field(default="", metadata=req(enum("light", "dark")))
    # ★ v0.3.  **strategy 와 독립된 축이다** (§4-5).
    #   strategy         hue 관계 (보색·유사색·단색 …)
    #   background_tone  명도/polarity 관계 (밝은 바탕 ↔ 짙은 바탕)
    #   그래서 complementary+light · complementary+dark · monochromatic+dark …
    #   가 전부 성립한다.  bg 와 ink 의 명암이 함께 뒤집힌다
    # ★ v0.4.  **Renderer 가 색을 만들 줄 아는 이름만** 쓴다 (`color_roles.py`).
    #   전에는 자유 문자열이라 Planner 가 product_signals 의 key 를 그대로
    #   가져다 쓰는 일이 생겼다 — 스키마가 합법인 이름을 알려주지 않았으니
    #   모델 잘못이 아니다. 새 역할을 늘린 것이 아니라 이미 구현이 아는 것을
    #   적었을 뿐이다.  선언한 역할과 실제 참조의 정합은 여전히 교차 검증이 본다
    roles: Tuple[str, ...] = field(
        default=(), metadata=req(min_items(2), item_enum(*SUPPORTED_COLOR_ROLES))
    )
    rhythm: Rhythm = field(default_factory=Rhythm)
    fixed_values: Optional[dict] = None  # source=fixed 일 때만


# ── 그래픽 언어 ───────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Spacing:
    unit: str = field(metadata=enum("col", "baseline"))
    value: float = field(metadata=rng(0.01, 64.0))


@dataclass(frozen=True)
class MotifPattern:
    """반복을 **의미로** 표현한다 (§8-1).

    instances 를 14개 나열하게 만들지 않는 것이 목적이다.
    """

    repeat: int = field(metadata=rng(1, 200))
    role: str = field(default="", metadata=req())
    # ★ v0.3.  instance role 과 같은 이름 공간을 쓴다 —
    #    safety.must_be_visible 이 pattern 도 가리킬 수 있어야
    #    선언-강제 규칙(§2-3)이 pattern 까지 똑같이 적용된다
    spacing: Optional[Spacing] = field(default=None, metadata=req())
    region: Optional[GridRef] = field(default=None, metadata=req())
    angle: str = field(
        default="horizontal",
        metadata=enum("horizontal", "vertical", "diagonal_up", "diagonal_down"),
    )
    phase: str = field(default="start", metadata=enum("start", "center"))
    weight: str = field(default="hair", metadata=enum("thick", "hair"))
    color_role: str = field(default="", metadata=color_role_field())
    layer: str = field(default="", metadata=layer_of(*MOTIF_LAYERS))


@dataclass(frozen=True)
class MotifInstance:
    role: str
    grid_ref: Optional[GridRef] = field(default=None, metadata=req())
    orientation: str = field(default="", metadata=req(enum("horizontal", "vertical")))
    # ★ v0.3.  같은 motif shape 안에서 방향만 다르게 한다 (§8-4-2).
    #    AD-C 의 좌측 세로 바를 임의 shape 없이 rule 로 표현하기 위한 최소 확장
    weight: str = field(default="hair", metadata=enum("thick", "hair"))
    color_role: str = field(default="", metadata=color_role_field())
    layer: str = field(default="", metadata=layer_of(*MOTIF_LAYERS))
    split_at: Optional[SplitAt] = None


@dataclass(frozen=True)
class Motif:
    shape: str = field(metadata=enum("rule", "circle", "diagonal", "frame", "block", "none"))
    # shape enum 확장은 필요성이 확인된 것만 하나씩 (§8-5). "custom" 없음
    min_repeats: int = field(default=1, metadata=rng(1, 200))
    pattern: Optional[MotifPattern] = None
    instances: Tuple[MotifInstance, ...] = ()


# ── 카피 ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CopyBlock:
    id: str
    role: str = field(metadata=enum(*COPY_ROLES))
    content_ref: str = field(default="", metadata=req())
    type_role: str = field(default="", metadata=req())
    grid_ref: Optional[GridRef] = field(default=None, metadata=req())
    priority: int = field(default=3, metadata=rng(1, 9))
    color_role: str = field(default="", metadata=color_role_field())
    layer: str = field(default="", metadata=layer_of(*TYPE_LAYERS))
    orientation: str = field(
        default="horizontal",
        metadata=enum(*COPY_ORIENTATIONS),
    )


# ── 안전 선언 (임계값 아님 — §7-4) ────────────────────────────────────────
@dataclass(frozen=True)
class Safety:
    critical_blocks: Tuple[str, ...] = ()
    must_be_visible: Tuple[str, ...] = ()


# ── 루트 ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RenderSpec:
    schema_version: str
    canvas: Canvas
    design_language: str = field(
        metadata=enum("editorial", "premium_minimal", "promotion", "contemporary_graphic")
    )
    grid: Optional[Grid] = field(default=None, metadata=req())
    zones: Optional[Zones] = field(default=None, metadata=req())
    product: Optional[Product] = field(default=None, metadata=req())
    background: Optional[Background] = field(default=None, metadata=req())
    typography: Optional[Typography] = field(default=None, metadata=req())
    palette: Optional[Palette] = field(default=None, metadata=req())
    motif: Optional[Motif] = field(default=None, metadata=req())
    copy_blocks: Tuple[CopyBlock, ...] = field(default=(), metadata=req(min_items(1)))
    layers: Tuple[str, ...] = LAYER_STACK
    safety: Safety = field(default_factory=Safety)

    # design_language 는 **Renderer 가 읽지 않는다** (§6).
    # Planner 의 art-direction prior / 리포팅 라벨일 뿐이다.
    # 이 계약은 test D1(design_language 만 바꾸면 픽셀 동일)로 검증한다.


# 루트에서 절대 받지 않는 키 — 있으면 trust boundary 위반 (§4-2)
FORBIDDEN_ROOT_KEYS: Tuple[str, ...] = ("spec_source",)

__all__ = [
    "SCHEMA_VERSION",
    "LAYER_STACK",
    "TYPE_LAYERS",
    "MOTIF_LAYERS",
    "NAMED_COL_REGIONS",
    "ABSOLUTE_ROWS",
    "PRODUCT_ROW_ALIGNS",
    "PRODUCT_ROW_SEQUENCE",
    "RESERVED_ANCHOR_TARGETS",
    "ROW_REL_PREFIXES",
    "REQUIRED_PALETTE_ROLES",
    "PALETTE_ROLE_TRANSITION",
    "SUPPORTED_COLOR_ROLES",
    "COPY_ROLES",
    "OVERLAP_INTENTS",
    "COPY_ORIENTATIONS",
    "STACKED_ORIENTATIONS",
    "ROTATED_ORIENTATIONS",
    "SUPPORTED_TYPE_FACES",
    "SPACE_AFTER_STEPS",
    "FORBIDDEN_ROOT_KEYS",
    "Canvas",
    "Grid",
    "ZoneSpan",
    "Zones",
    "GridRef",
    "SplitAt",
    "Anchor",
    "Product",
    "Background",
    "TypeRole",
    "Typography",
    "Rhythm",
    "Palette",
    "Spacing",
    "MotifPattern",
    "MotifInstance",
    "Motif",
    "CopyBlock",
    "Safety",
    "RenderSpec",
]

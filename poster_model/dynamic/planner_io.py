"""Design Planner 입출력 계약 — 구현 전 단계.

**여기에 LLM 호출은 없다.** 계약만 닫는다. 세 개다.

    ① 서비스 입력  →  CreativeBrief          (PlannerInput)
    ② Planner 출력 =  RenderSpec 후보들        (PlannerResult)
    ③ Safety 실패  →  Planner 피드백          (SafetyFeedback)

책임 경계 — **Planner 는 prompt 문자열 생성기가 아니다.**

    CreativeBrief
        ↓  Design Planner        ← 디자인 의사결정 전체
    RenderSpec
        ├ grid / zones
        ├ product treatment      제품을 **어떻게 배치**할 것인가
        ├ typography · palette · motif · layers · overlap_intent
        └ background (**의미**)
        ↓  server prompt builder ← 문자열은 여기서 파생된다
    Visual Prompt

Visual Prompt 는 Planner 의 산출물이 아니라 **Planner 가 정한 background 의미의
후속 파생**이다. 그래서 이 모듈 어디에도 프롬프트 문자열이 없다.

이름 충돌 주의
    confirmed_product      "제품이 **무엇**인가"        → CreativeBrief.product_identity
    RenderSpec.product     "제품을 **어떻게** 놓는가"    → fit/anchor/bleed/rotation
    둘은 다른 개념이다. adapter 경계에서 이름을 갈라 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Optional, Sequence, Tuple

from .brief import BriefCopy, CreativeBrief, normalize_preferred_color
from .grid import RATIO_TERMS
from .palette import REQUIRED_PRODUCT_SIGNALS
from .color_roles import SUPPORTED_COLOR_ROLES
from .spec import (
    COPY_ORIENTATIONS,
    COPY_ROLES,
    LAYER_STACK,
    OVERLAP_INTENTS,
    REQUIRED_PALETTE_ROLES,
    SCHEMA_VERSION,
    SPACE_AFTER_STEPS,
    SUPPORTED_TYPE_FACES,
)
from .validate import (CROSS_FIELD_RULES, PLANNER_CONTEXT, ValidationContext,
                       validate)


# ──────────────────────────────────────────────────────────────────────────
# ① 서비스 입력 → CreativeBrief
# ──────────────────────────────────────────────────────────────────────────
#: `/vision/product` 가 확정한 provenance 값. **production enum 그대로 보존한다.**
#: 축약값("vision" 등)을 코드 enum 으로 만들지 않는다 — 다른 값이 되어 버린다.
CONFIRMATION_SOURCES: Tuple[str, ...] = ("vision_confirmed", "user_corrected")

#: Planner 로 가져오지 **않는** 값.
#:   `/vision/product` 의 제품 확정 **이전** flow control 이고,
#:   Planner 는 confirmed_product 가 확정된 뒤부터 시작한다.
EXCLUDED_VISION_FIELDS: Tuple[str, ...] = ("next_action", "recognition_status")


@dataclass(frozen=True)
class ProductIdentity:
    """제품이 **무엇**인가. `RenderSpec.product`(배치)와 다른 개념이다.

    `confirmation_source` 는 **provenance** 다 — 그 이름이 어디서 확정됐는지.
    디자인 의미가 아니므로 Planner 의 디자인 판단 입력으로 쓰지 않는다.
    로깅·추적·재현에는 production 값 그대로 남긴다.
    """

    confirmed_product: str
    confirmation_source: str = ""      # CONFIRMATION_SOURCES (provenance)

    #: Planner 가 디자인 판단에 써도 되는 필드
    DESIGN_FIELDS: Tuple[str, ...] = ("confirmed_product",)
    #: 추적용이라 디자인 판단에서 제외하는 필드
    PROVENANCE_FIELDS: Tuple[str, ...] = ("confirmation_source",)

    def __post_init__(self) -> None:
        src = self.confirmation_source
        if src and src not in CONFIRMATION_SOURCES:
            raise ValueError(
                f"confirmation_source 는 production enum {CONFIRMATION_SOURCES} 만 "
                f"받는다 (받음: {src!r}) — 축약값을 새로 만들지 않는다"
            )

    def for_design(self) -> dict:
        return {"confirmed_product": self.confirmed_product}

    def provenance(self) -> dict:
        return {"confirmation_source": self.confirmation_source}


#: 팀 `copy_model/background.py:BackgroundContext` 에서 **실제 코드로 확인한**
#: 필드 6개. 이 목록 밖의 key 는 스키마가 확인되지 않은 것으로 보고 신뢰하지
#: 않는다 (E21 §1-2).
#:
#:     palette      list[str]        ★ 자연어. "웜 베이지" — HEX 가 아니다
#:     lighting     Optional[str]
#:     texture      list[str]
#:     mood         Optional[str]
#:     composition  Optional[str]
#:     usable       bool = True
CONFIRMED_BACKGROUND_FIELDS: Tuple[str, ...] = (
    "palette", "lighting", "texture", "mood", "composition", "usable",
)


@dataclass(frozen=True)
class BackgroundContextInput:
    """`/vision/background` → `spec.background_context` 를 받는 자리.

    전에는 `payload` dict + `schema_confirmed` 전역 플래그였다. 실제 팀
    스키마를 코드로 확인했으므로(E21 §1-2) **확인된 6개 필드만 명시적으로
    노출한다.** 플래그 하나로 전체를 여닫지 않는다 — 그러면 "무엇이 확인됐고
    무엇이 아닌가" 가 값에 드러나지 않는다.

        palette / lighting / texture / mood / composition
                ↓  (해석은 Planner 의 일)
        RenderSpec.background
        material · lighting · texture · whitespace_strategy · visual_style

    ★ **`palette` 는 자연어다.** `product_signals.palette` (HEX) 와 같은 자리에
    넣을 수 없다. 여기 값은 Planner 가 읽는 **참고 prior** 일 뿐이고,
    `resolve_palette()` 의 입력이 아니다 (E21 §2-1).

    ★ `usable=False` 면 배경 참고로 쓸 수 없다는 뜻이다. 이때는 **프롬프트에
    아무 필드도 싣지 않는다** — 일부만 살려 쓰지 않는다 (E21 §2-2).
    """

    palette: Tuple[str, ...] = ()          # ★ 자연어 서술. HEX 아님
    lighting: Optional[str] = None
    texture: Tuple[str, ...] = ()
    mood: Optional[str] = None
    composition: Optional[str] = None
    usable: bool = True
    source: str = "vision.background"
    #: 확인된 6개 밖의 key. **보존만 한다** — 프롬프트로 나가지 않는다.
    unconfirmed: Mapping[str, Any] = field(default_factory=dict)

    def hint(self, key: str) -> Optional[Any]:
        """확인된 필드만 값을 준다. 그 밖에는 항상 None.

        `usable=False` 면 전부 None 이다 — 못 쓰는 분석에서 일부만 뽑아
        쓰지 않는다.
        """
        if key not in CONFIRMED_BACKGROUND_FIELDS:
            return None
        if not self.usable:
            return None
        value = getattr(self, key)
        if isinstance(value, tuple):
            return list(value) or None
        return value

    def design_hints(self) -> dict:
        """Planner 프롬프트에 실을 값. `usable=False` 면 빈 dict."""
        if not self.usable:
            return {}
        out = {}
        for key in CONFIRMED_BACKGROUND_FIELDS:
            if key == "usable":
                continue
            value = self.hint(key)
            if value:
                out[key] = value
        return out

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "usable": self.usable,
            "confirmed_fields": list(CONFIRMED_BACKGROUND_FIELDS),
            "present_fields": sorted(self.design_hints()),
            "unconfirmed_keys": sorted(self.unconfirmed) if self.unconfirmed else [],
        }


@dataclass(frozen=True)
class ServiceRequest:
    """팀/API 가 현재 부르는 이름 그대로 받는 **adapter 입력**.

    production API 필드명을 바꾸지 않는다. 의미 분리는 이 경계에서만 한다.
    """

    business_type: str = "product"
    category: str = ""
    confirmed_product: str = ""
    confirmation_source: str = ""
    tone: str = "minimal_product"
    keywords: Sequence[str] = ()
    request: str = ""                       # E5 의 additional_request 와 같은 자리
    output_ratio: str = "1:1"
    visual_style: Optional[str] = None
    background_context: Optional[BackgroundContextInput] = None
    product_signals: Mapping[str, Any] = field(default_factory=dict)
    copy: Optional[BriefCopy] = None
    brand_palette: Mapping[str, str] = field(default_factory=dict)
    category_label: Optional[str] = None
    business_label: Optional[str] = None
    preferred_color: Optional[str] = None   # v0.5 — #RRGGBB soft hint


#: 현재 서비스/문서 필드 → CreativeBrief 필드. 이름이 갈리는 것만 적는다.
FIELD_MAPPING: Mapping[str, str] = MappingProxyType({
    "business_type": "business_type",
    "category": "category",
    "confirmed_product": "product_identity.confirmed_product",
    "confirmation_source": "product_identity.confirmation_source  (provenance · 디자인 판단 제외)",
    "tone": "tone",
    "keywords": "keywords",
    "request": "request                      (E5 의 additional_request)",
    "output_ratio": "output_ratio",
    "visual_style": "visual_style",
    "background_context": "background_context           (확인된 6필드 · palette 는 자연어)",
    "preferred_color": "preferred_color             (#RRGGBB soft hint)",
    "product_signals": "product_signals             (palette resolver 입력)",
    "copy": "copy",
    "brand_palette": "brand_palette",
})


def to_creative_brief(req: ServiceRequest) -> CreativeBrief:
    """서비스 입력 → CreativeBrief. **디자인 결정을 하지 않는다.**

    여기서 하는 일은 이름과 의미를 가르는 것뿐이다. grid 를 고르거나 색을
    정하는 것은 Planner 의 일이고, 이 adapter 가 미리 손대면 경계가 무너진다.
    """
    identity = None
    if req.confirmed_product or req.confirmation_source:
        identity = ProductIdentity(
            confirmed_product=req.confirmed_product,
            confirmation_source=req.confirmation_source,
        )
    return CreativeBrief(
        business_type=req.business_type,
        category=req.category,
        tone=req.tone,
        output_ratio=req.output_ratio,
        visual_style=req.visual_style,
        keywords=tuple(req.keywords),
        copy=req.copy or BriefCopy(),
        product_signals=dict(req.product_signals),
        brand_palette=dict(req.brand_palette),
        category_label=req.category_label,
        business_label=req.business_label,
        product_identity=identity,
        background_context=req.background_context,
        request=req.request,
        preferred_color=normalize_preferred_color(req.preferred_color),
    )


# ──────────────────────────────────────────────────────────────────────────
# 팀 `spec` dict → ServiceRequest  (E21 §5)
# ──────────────────────────────────────────────────────────────────────────
#: 팀 `spec` 에는 있으나 Planner 로 **가져오지 않는** 키.
#:   flow control / 확정 이전 상태 / 아직 계약이 안 닫힌 것.
#: 가져오지 않는 이유를 값에 적어 둔다 — 나중에 "왜 빠졌지" 를 코드에서 찾게
#: 하지 않는다.
TEAM_SPEC_EXCLUDED: Mapping[str, str] = MappingProxyType({
    "purpose": "용도 계약 미확정 — E21 §7 열린 항목",
    "purpose_locked": "flow control",
    "purpose_invalid": "flow control",
    "product_context.product": "Vision 인식값 — confirmed_product 가 최종값이다",
    "product_context.vision_product": "인식값 원본 보존 — provenance",
    "product_context.detected_category": "E21 §7 열린 항목",
    "product_context.category_match": "flow control",
    "product_context.visible_features": "E21 §7 열린 항목",
    "product_context.visible_text": "E21 §7 열린 항목",
    "product_context.recognition_status": "제품 확정 **이전** 상태",
    "product_context.next_action": "제품 확정 **이전** flow control",
})


def background_context_from_team(payload: Optional[Mapping[str, Any]]
                                 ) -> Optional[BackgroundContextInput]:
    """팀 `spec["background_context"]` → `BackgroundContextInput`.

    확인된 6개 필드만 읽는다. 그 밖의 key 는 `unconfirmed` 에 **보존만** 하고
    프롬프트로 내보내지 않는다 — 이름이 같아 보인다고 의미가 같다고 보지
    않는다.
    """
    if not payload:
        return None

    def _seq(key: str) -> Tuple[str, ...]:
        val = payload.get(key)
        if isinstance(val, str):        # 단수로 와도 받아 준다
            return (val,) if val else ()
        if isinstance(val, (list, tuple)):
            return tuple(str(x) for x in val if x)
        return ()

    def _text(key: str) -> Optional[str]:
        val = payload.get(key)
        return str(val) if isinstance(val, str) and val else None

    usable = payload.get("usable", True)
    return BackgroundContextInput(
        palette=_seq("palette"),        # ★ 자연어. HEX 로 해석하지 않는다
        lighting=_text("lighting"),
        texture=_seq("texture"),
        mood=_text("mood"),
        composition=_text("composition"),
        usable=bool(usable) if isinstance(usable, bool) else True,
        unconfirmed={k: v for k, v in payload.items()
                     if k not in CONFIRMED_BACKGROUND_FIELDS},
    )


def service_request_from_team_spec(
    spec: Mapping[str, Any],
    *,
    tone: str = "minimal_product",
    keywords: Sequence[str] = (),
    request: str = "",
    copy: Optional[BriefCopy] = None,
    brand_palette: Optional[Mapping[str, str]] = None,
    product_signals: Optional[Mapping[str, Any]] = None,
    preferred_color: Optional[str] = None,
    visual_style: Optional[str] = None,
) -> ServiceRequest:
    """팀 `spec` dict → `ServiceRequest`. **정규화만 한다.**

    팀 spec 을 Renderer 나 Planner 에 그대로 넣지 않는다. 이 경계에서 이름을
    맞추고, 가져오지 않을 것을 떨어뜨린다 (`TEAM_SPEC_EXCLUDED`).

    키워드 인자로 받는 것들은 **팀 spec 에 아직 자리가 없는 값**이다. 추측해서
    spec 에서 뽑아내지 않는다 — 서비스가 명시적으로 넘긴다.
    """
    ctx = spec.get("product_context") or {}
    return ServiceRequest(
        business_type=spec.get("business_type") or "product",
        category=spec.get("category") or "",
        # `spec["product"]` 가 최종 확정 제품명(문자열)이다 (E21 §1-1).
        confirmed_product=str(spec.get("product") or ""),
        confirmation_source=str(ctx.get("confirmation_source") or ""),
        output_ratio=str(spec.get("aspect_ratio") or "1:1"),
        background_context=background_context_from_team(spec.get("background_context")),
        tone=tone,
        keywords=tuple(keywords),
        request=request,
        copy=copy,
        brand_palette=dict(brand_palette or {}),
        product_signals=dict(product_signals or {}),
        preferred_color=preferred_color,
        visual_style=visual_style,
    )


# ──────────────────────────────────────────────────────────────────────────
# Planner 가 만들어도 되는 값의 범위
# ──────────────────────────────────────────────────────────────────────────
def describe_capabilities(context: Optional[ValidationContext] = None) -> dict:
    """Planner 가 고를 수 있는 값들. **단일 출처는 spec 모듈이다.**

    나중에 프롬프트를 쓸 때도 이 표를 그대로 실어 보내면 되고, 스키마가
    바뀌면 여기가 따라 바뀐다 — 프롬프트에 값을 손으로 복사해 두지 않는다.
    """
    ctx = context or PLANNER_CONTEXT
    return {
        "schema_version": SCHEMA_VERSION,
        "canvas_ratios": list(ctx.supported_ratios),
        "declared_ratios": list(RATIO_TERMS),
        "grid_columns": [4, 6, 8, 12],
        "densities": ["tight", "normal", "loose"],
        "baseline_scales": ["fine", "normal", "coarse"],
        "overlap_intents": list(OVERLAP_INTENTS),
        "layers": list(LAYER_STACK),
        "copy_roles": list(COPY_ROLES),
        "copy_orientations": list(COPY_ORIENTATIONS),
        "space_after": list(SPACE_AFTER_STEPS),
        "type_faces": [f"{f}/{w}" for f, w in SUPPORTED_TYPE_FACES],
        "palette_strategies": ["complementary", "analogous", "split_complementary",
                               "monochromatic", "neutral_support", "fixed"],
        "background_tones": ["light", "dark"],
        # ★ v0.4 — 색 역할은 `color_roles.py` 가 단일 출처다. run 02 이전에는
        #   capabilities 에 이 키 자체가 없어서, 모델이 합법인 이름을 schema
        #   enum 으로만 알 수 있었다
        "color_roles": list(SUPPORTED_COLOR_ROLES),
        "required_palette_roles": list(REQUIRED_PALETTE_ROLES),
        # ★ v0.5 — 색을 **어디서 가져오는가**. 네 source 는 독립이라,
        #   고른 source 의 입력이 없으면 다른 곳으로 넘어가지 않고 거부된다
        "palette_sources": {
            "product": "product_signals.palette 의 HEX 를 seed 로 삼는다",
            "brand": "brand_palette 의 역할별 HEX 를 그대로 쓴다",
            "preferred": (
                "사용자가 고른 색(preferred_color)을 seed 로 삼는다. "
                "seed 일 뿐이라 그 색이 그대로 bg 가 되는 것은 아니다 — "
                "어느 역할에 어떤 명도로 반영할지는 네가 정한다"
            ),
        },
        "color_preference": (
            "brief.preferred_color 는 사용자의 **선호**이지 지시가 아니다. "
            "값이 있어도 palette.source 를 preferred 로 강제하지 않는다 — "
            "제품 색이나 브랜드 색이 더 맞다고 판단하면 그쪽을 골라라. "
            "반대로 preferred 를 고르면 그 값이 반드시 있어야 한다"
        ),
        # 팀 `/vision/background` 에서 **실제 코드로 확인한** 필드만 온다.
        # `palette` 는 자연어 서술이다 — HEX 가 아니고 색 계산 입력도 아니다
        "background_context_fields": list(CONFIRMED_BACKGROUND_FIELDS),
        "motif_shapes": ["rule", "circle", "diagonal", "frame", "block", "none"],
        "required_product_signals": list(REQUIRED_PRODUCT_SIGNALS),
        # ★ v0.4 — 값 **사이의 관계**. strict JSON Schema 로는 조건부 관계를
        #   표현할 수 없어서(if/then/else 미지원) 여기 싣는다. 단일 출처는
        #   규칙을 실제로 강제하는 `validate.py` 다
        "cross_field_rules": {path: why for path, why in CROSS_FIELD_RULES},
        "forbidden": [
            "픽셀 좌표 (px 는 Renderer 가 유도한다)",
            "정수 row index (planner 경로는 의미적 anchor 만)",
            "spec_source (호출 경로가 정한다)",
            "임의 shape / 임의 HEX (source=fixed 제외)",
        ],
    }


# ──────────────────────────────────────────────────────────────────────────
# ③ Safety 실패 → Planner 피드백
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SafetyFeedback:
    """`SafetyResult.for_planner()` 를 그대로 담는다.

    **처방이 없다.** 무엇이·얼마나·어떤 관계에서 실패했는지만 있고,
    색을 바꿀지 배치를 바꿀지 layer 를 바꿀지는 Planner 가 고른다.
    """

    candidate_id: str
    payload: Mapping[str, Any]

    @classmethod
    def from_result(cls, candidate_id: str, result) -> "SafetyFeedback":
        return cls(candidate_id=candidate_id, payload=result.for_planner())

    @property
    def passed(self) -> bool:
        return bool(self.payload.get("passed"))

    @property
    def violations(self) -> Tuple[Mapping[str, Any], ...]:
        return tuple(self.payload.get("violations", ()))

    def failures(self) -> Tuple[Mapping[str, Any], ...]:
        return tuple(v for v in self.violations if v.get("severity") == "fail")

    def by_element(self) -> dict:
        out: dict = {}
        for v in self.violations:
            out.setdefault(v["element_id"], []).append(v)
        return out

    @property
    def incomplete_coverage(self) -> Tuple[str, ...]:
        """`passed=True` 라도 **검사되지 않은 것**이 있으면 여기 남는다."""
        return tuple(self.payload.get("unsupported_checks", ())) + tuple(
            self.payload.get("deferred_checks", ()))


# ──────────────────────────────────────────────────────────────────────────
# ② Planner 입출력
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PlannerInput:
    """Planner 한 번 호출에 들어가는 전부."""

    brief: CreativeBrief
    capabilities: Mapping[str, Any]
    candidate_count: int = 1
    feedback: Tuple[SafetyFeedback, ...] = ()   # 재설계 요청일 때만 채워진다
    notes: str = ""

    @classmethod
    def of(cls, brief: CreativeBrief, *, candidate_count: int = 1,
           feedback: Sequence[SafetyFeedback] = (), notes: str = "",
           context: Optional[ValidationContext] = None) -> "PlannerInput":
        return cls(
            brief=brief,
            capabilities=MappingProxyType(describe_capabilities(context)),
            candidate_count=max(1, candidate_count),
            feedback=tuple(feedback),
            notes=notes,
        )

    @property
    def is_redesign(self) -> bool:
        return bool(self.feedback)

    @property
    def background_context_status(self) -> str:
        """`"present" | "empty" | "unusable" | "absent"`.

        **가드다.** 배경 Vision 정보가 실제로 프롬프트에 실렸는지를 겉으로
        드러낸다. 이게 없으면 "Planner 가 배경을 못 정한다"고 판단할 때
        정보를 안 준 것인지 모델이 못 쓴 것인지 구분할 수 없다.

            absent      background_context 자체가 없다
            unusable    usable=False — 분석 실패/부적합 (팀이 그렇게 표시했다)
            empty       usable=True 인데 실을 값이 하나도 없다
            present     Planner 가 읽을 값이 있다
        """
        ctx = getattr(self.brief, "background_context", None)
        if ctx is None:
            return "absent"
        if not getattr(ctx, "usable", False):
            return "unusable"
        return "present" if ctx.design_hints() else "empty"

    def background_ready(self) -> bool:
        """배경 결정을 **평가 대상으로 삼아도 되는가.**"""
        return self.background_context_status == "present"


@dataclass(frozen=True)
class PlannerCandidate:
    """후보 하나. **RenderSpec 원본(dict)** 을 담는다.

    Planner 가 잘못된 enum 이나 좌표를 만들어도 Step 1~6 이 그대로 방어벽이
    되도록, 여기서는 검증하지 않고 **그대로** 들고 있는다.
    """

    id: str
    render_spec: Mapping[str, Any]
    label: str = ""              # "Clean editorial" 같은 사람용 이름
    rationale: str = ""          # 왜 이렇게 설계했는지 (로깅·비교용)
    derived_from: str = ""       # 재설계면 원본 후보 id

    @property
    def design_language(self) -> str:
        return str(self.render_spec.get("design_language", ""))


@dataclass(frozen=True)
class PlannerResult:
    """한 번의 Planner 호출 결과. **처음부터 복수 후보**를 담는다.

    같은 제품에서 실제로 다른 디자인을 제안하는 것이 목표이므로
    1 request → 1 RenderSpec 에 묶지 않는다. 후보가 하나여도 목록이다.
    """

    candidates: Tuple[PlannerCandidate, ...]
    input_digest: str = ""
    notes: str = ""
    #: 실행 기록 — model · temperature · prompt_version · schema_version …
    #: **같은 brief → 같은 RenderSpec 을 보장하지 않는다.** 재현은 이 기록으로만.
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.candidates)

    def by_id(self, candidate_id: str) -> Optional[PlannerCandidate]:
        return next((c for c in self.candidates if c.id == candidate_id), None)

    def design_languages(self) -> Tuple[str, ...]:
        return tuple(c.design_language for c in self.candidates)


@dataclass(frozen=True)
class CandidateReview:
    candidate_id: str
    accepted: bool
    error_codes: Tuple[str, ...] = ()


def review_candidates(
    result: PlannerResult,
    brief: CreativeBrief,
    context: Optional[ValidationContext] = None,
) -> Tuple[CandidateReview, ...]:
    """후보들을 기존 검증기에 그대로 통과시킨다.

    **Planner 를 믿지 않는다.** 잘못된 enum·px 좌표·정수 row index 가 오면
    Step 1 검증이 거부하고, 통과한 것만 build_plan → render → safety 로 간다.
    """
    ctx = context or PLANNER_CONTEXT
    out = []
    for cand in result.candidates:
        errors = validate(dict(cand.render_spec), brief, ctx)
        out.append(CandidateReview(
            candidate_id=cand.id,
            accepted=not errors,
            error_codes=tuple(e.code for e in errors),
        ))
    return tuple(out)


__all__ = [
    "ProductIdentity",
    "BackgroundContextInput",
    "CONFIRMED_BACKGROUND_FIELDS",
    "ServiceRequest",
    "FIELD_MAPPING",
    "TEAM_SPEC_EXCLUDED",
    "to_creative_brief",
    "background_context_from_team",
    "service_request_from_team_spec",
    "describe_capabilities",
    "SafetyFeedback",
    "PlannerInput",
    "PlannerCandidate",
    "PlannerResult",
    "CandidateReview",
    "review_candidates",
]

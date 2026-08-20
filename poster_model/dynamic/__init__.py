"""동적 art direction Renderer — E12 v0.3.

**production `pipeline/` 과 분리된 경로다.** 이 패키지는 `pipeline` 을
import 하지 않으며, core_1x1 의 기존 출력에 영향을 주지 않는다.

현재 구현 범위 — Step 3 까지.

    ○ RenderSpec 자료구조            spec.py
    ○ CreativeBrief + content_ref    brief.py
    ○ schema / cross-field 검증       validate.py
    ○ Grid Resolver                  grid.py
    ○ ProductGeometry 입력 계약        geometry.py
    ○ 서체 해석 · 측정                 fonts.py
    ○ 줄바꿈                          text.py
    ○ Palette / Background resolve   palette.py · background.py
    ○ RenderSpec → RenderPlan        plan.py     ← 그리지 않고 측정만 한다
    ○ 픽셀 asset 입력 계약             assets.py
    ○ Renderer 골격                   render.py   ← 판단하지 않고 그리기만 한다
    ○ Safety Validator               policy.py · evidence.py · safety.py
    ○ Planner 입출력 계약              planner_io.py · diversity.py
    ○ AI Design Planner              planner.py · planner_prompt.py

계약 요약
    · Planner 는 디자인 의사결정만.  px 은 Renderer 가 유도한다
    · `spec_source` 는 Spec 필드가 아니다 — ValidationContext 소관
    · Renderer 는 `design_language` 를 읽지 않는다 (§6)
    · 잘못된 Spec 을 조용히 보정하지 않는다.  검증 단계에서 거부한다

Step 3 진입 조건 — 실제 실행 경로의 brief 요구 수준
    현재 `validate(raw, brief=None)` 은 CreativeBrief 없이도 통과한다.
    **스키마 단독 검증에서만** 허용되는 완화이고, content_ref 해석만 생략된다.

        RenderSpec schema 단독 validation   brief 생략 가능
        RenderPlan build / render 실행       RenderSpec + CreativeBrief **필수**
                                            모든 content_ref 해석 필수
                                            누락/실패 시 진행 금지

    Step 3 의 `build_plan()` 은 brief 를 선택 인자로 받지 않는다.
"""

from __future__ import annotations

from .brief import (
    COPY_SLOTS,
    DERIVED_REFS,
    BriefCopy,
    CopyExtra,
    CopyItem,
    CreativeBrief,
    normalize_preferred_color,
    resolve_content_ref,
)
from .errors import (
    AnchorUnresolvable,
    ContentRefUnresolved,
    PlanUnresolvable,
    ProductGeometryInvalid,
    EvidenceMismatch,
    PlannerOutputInvalid,
    RenderAssetInvalid,
    RenderUnsupported,
    CoordinateMixing,
    CriticalEmpty,
    GridUnresolvable,
    LayerUnassigned,
    RatioUnsupported,
    SchemaError,
    SpecError,
    SpecInvalid,
    SpecRejected,
    TrustBoundaryViolation,
)
from .spec import (
    LAYER_STACK,
    MOTIF_LAYERS,
    NAMED_COL_REGIONS,
    SCHEMA_VERSION,
    TYPE_LAYERS,
    Anchor,
    Background,
    Canvas,
    CopyBlock,
    Grid,
    GridRef,
    Motif,
    MotifInstance,
    MotifPattern,
    Palette,
    Product,
    RenderSpec,
    Rhythm,
    Safety,
    Spacing,
    SplitAt,
    TypeRole,
    Typography,
    ZoneSpan,
    Zones,
)
from .grid import (
    DEFAULT_SHORT_SIDE,
    TIE_BREAKS,
    CanvasSize,
    ResolvedGrid,
    check_capability,
    resolve_grid,
)
from .assets import BackgroundRenderAsset, ProductRenderAsset
from .background import ResolvedBackground, resolve_background
from .fonts import FontBook, ResolvedFont
from .geometry import ProductGeometry
from .color_roles import SUPPORTED_COLOR_ROLES
from .palette import ResolvedPalette, resolve_palette, rgb_to_hex
from .evidence import ElementEvidence, RenderEvidence
from .policy import DEFAULT_POLICY, DEFERRED_CHECKS, SystemPolicy
from .render import RENDERER_VERSION, render, render_digest, render_with_evidence
from .safety import PASSED_SCOPE, SafetyResult, Violation, check_integrity, validate_safety
from .planner import (
    DEFAULT_MODEL,
    DesignPlanner,
    FakeLLMClient,
    LLMClient,
    OpenAIClient,
    PlannerConfig,
)
from .planner_prompt import (
    CROSS_FIELD_RULES,
    PROMPT_VERSION,
    STRICT_UNSUPPORTED,
    build_system_prompt,
    build_user_prompt,
    planner_output_schema,
    planner_render_spec_schema,
    render_spec_json_schema,
    STRICT_LIMITS,
    limit_violations,
    measure_schema,
    strict_planner_output_schema,
    strict_preflight,
    strict_violations,
)
from .diversity import (
    AXIS_CATEGORIES,
    MIN_DIFFERING_AXES,
    MIN_STRUCTURAL_AXES,
    DiversityReport,
    check_diversity,
    spec_axes,
)
from .planner_io import (
    CONFIRMATION_SOURCES,
    CONFIRMED_BACKGROUND_FIELDS,
    EXCLUDED_VISION_FIELDS,
    TEAM_SPEC_EXCLUDED,
    BackgroundContextInput,
    CandidateReview,
    PlannerCandidate,
    PlannerInput,
    PlannerResult,
    ProductIdentity,
    SafetyFeedback,
    ServiceRequest,
    background_context_from_team,
    describe_capabilities,
    review_candidates,
    service_request_from_team_spec,
    to_creative_brief,
)
from .plan import (
    RenderPlan,
    ResolvedCopyBlock,
    ResolvedMotif,
    ResolvedProduct,
    ResolvedZones,
    build_plan,
)
from .text import break_lines
from .validate import (
    FIXTURE_CONTEXT,
    PLANNER_CONTEXT,
    SPEC_SOURCES,
    ValidationContext,
    load,
    validate,
)

__all__ = [
    "SCHEMA_VERSION",
    "LAYER_STACK",
    "TYPE_LAYERS",
    "MOTIF_LAYERS",
    "NAMED_COL_REGIONS",
    # spec
    "RenderSpec",
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
    # brief
    "CreativeBrief",
    "BriefCopy",
    "CopyItem",
    "CopyExtra",
    "COPY_SLOTS",
    "DERIVED_REFS",
    "resolve_content_ref",
    # validate
    "ValidationContext",
    "PLANNER_CONTEXT",
    "FIXTURE_CONTEXT",
    "SPEC_SOURCES",
    "validate",
    "load",
    # grid (Step 2)
    "CanvasSize",
    "ResolvedGrid",
    "resolve_grid",
    "check_capability",
    "DEFAULT_SHORT_SIDE",
    "TIE_BREAKS",
    # plan (Step 3)
    "ProductGeometry",
    "RenderPlan",
    "ResolvedZones",
    "ResolvedProduct",
    "ResolvedCopyBlock",
    "ResolvedMotif",
    "build_plan",
    "FontBook",
    "ResolvedFont",
    "break_lines",
    "ResolvedPalette",
    "resolve_palette",
    "SUPPORTED_COLOR_ROLES",
    "rgb_to_hex",
    "ResolvedBackground",
    "resolve_background",
    # render (Step 4)
    "ProductRenderAsset",
    "BackgroundRenderAsset",
    "render",
    "render_with_evidence",
    "render_digest",
    "RENDERER_VERSION",
    # safety (Step 6)
    "RenderEvidence",
    "ElementEvidence",
    "SystemPolicy",
    "DEFAULT_POLICY",
    "DEFERRED_CHECKS",
    "SafetyResult",
    "Violation",
    "validate_safety",
    "check_integrity",
    "PASSED_SCOPE",
    # planner 계약 (Step 7 준비)
    "ServiceRequest",
    "ProductIdentity",
    "BackgroundContextInput",
    "CONFIRMED_BACKGROUND_FIELDS",
    "TEAM_SPEC_EXCLUDED",
    "normalize_preferred_color",
    "background_context_from_team",
    "service_request_from_team_spec",
    "to_creative_brief",
    "describe_capabilities",
    "PlannerInput",
    "PlannerCandidate",
    "PlannerResult",
    "CandidateReview",
    "review_candidates",
    "SafetyFeedback",
    "CONFIRMATION_SOURCES",
    "EXCLUDED_VISION_FIELDS",
    "check_diversity",
    "DiversityReport",
    "spec_axes",
    "AXIS_CATEGORIES",
    "MIN_DIFFERING_AXES",
    "MIN_STRUCTURAL_AXES",
    # AI Design Planner (Step 9)
    "DesignPlanner",
    "PlannerConfig",
    "LLMClient",
    "OpenAIClient",
    "FakeLLMClient",
    "DEFAULT_MODEL",
    "PROMPT_VERSION",
    "CROSS_FIELD_RULES",
    "STRICT_UNSUPPORTED",
    "build_system_prompt",
    "build_user_prompt",
    "planner_output_schema",
    "planner_render_spec_schema",
    "render_spec_json_schema",
    "strict_planner_output_schema",
    "strict_violations",
    "strict_preflight",
    "measure_schema",
    "limit_violations",
    "STRICT_LIMITS",
    # errors
    "SpecError",
    "SchemaError",
    "SpecRejected",
    "RatioUnsupported",
    "GridUnresolvable",
    "AnchorUnresolvable",
    "LayerUnassigned",
    "CriticalEmpty",
    "CoordinateMixing",
    "TrustBoundaryViolation",
    "ContentRefUnresolved",
    "ProductGeometryInvalid",
    "PlanUnresolvable",
    "RenderUnsupported",
    "RenderAssetInvalid",
    "EvidenceMismatch",
    "PlannerOutputInvalid",
    "SpecInvalid",
]

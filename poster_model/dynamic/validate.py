"""RenderSpec 검증 — E12 v0.3 §9.

핵심 원칙 — **잘못된 Spec 을 Renderer 가 적당히 해석하거나 조용히 보정하지
않는다.** 검증 단계에서 거부한다.

세 단계로 나눈다.

    ① schema   타입 · enum · 범위 · 필수 · 미지의 필드
               dataclass 의 field metadata 를 읽어 동작한다 (제약의 단일 출처)
    ② build    ①을 통과했을 때만 자료구조를 만든다
    ③ cross    교차 필드 규칙.  ①이 실패하면 실행하지 않는다
               (타입이 깨진 트리 위에서 교차 검증을 하면 오탐이 난다)

에러는 **모아서** 한 번에 올린다. 한 건씩 고치게 만들지 않는다.

trust boundary (§4-2) — `spec_source` 는 RenderSpec 필드가 아니다.
신뢰된 호출자(server / test harness)가 ValidationContext 로 넘긴다.
Spec 안에 이 키가 있으면 "제약을 스스로 해제하려 했다"는 신호이므로
TrustBoundaryViolation 으로 거부한다.
"""

from __future__ import annotations

import dataclasses
import re
import types
from dataclasses import MISSING, dataclass, fields, is_dataclass
from typing import Any, Optional, Tuple, Union, get_args, get_origin, get_type_hints

from .brief import CreativeBrief, known_content_refs, resolve_content_ref
from .errors import (
    AnchorUnresolvable,
    ContentRefUnresolved,
    CoordinateMixing,
    CriticalEmpty,
    LayerUnassigned,
    RatioUnsupported,
    SchemaError,
    SpecError,
    SpecInvalid,
    SpecRejected,
    TrustBoundaryViolation,
)
from .spec import (
    ABSOLUTE_ROWS,
    FORBIDDEN_ROOT_KEYS,
    LAYER_STACK,
    PALETTE_ROLE_TRANSITION,
    PRODUCT_ROW_ALIGNS,
    PRODUCT_ROW_SEQUENCE,
    RESERVED_ANCHOR_TARGETS,
    REQUIRED_PALETTE_ROLES,
    ROW_REL_PREFIXES,
    SCHEMA_VERSION,
    SUPPORTED_TYPE_FACES,
    GridRef,
    RenderSpec,
)

SPEC_SOURCES: Tuple[str, ...] = ("planner", "fixture")
_HEX = re.compile(r"#[0-9A-Fa-f]{6}\Z")
_NONE_TYPE = type(None)


# ──────────────────────────────────────────────────────────────────────────
# ValidationContext — 신뢰 경계
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ValidationContext:
    """호출 경로가 정하는 값. **Planner 출력에서 오지 않는다.**

    spec_source
        "planner"  의미적 row_anchor 만 허용
        "fixture"  정수 row index 허용 — 기존 디자인 재기술용 검증 경로
    supported_ratios
        Renderer 의 capability.  v1 은 1:1 만 (§4-1)
    """

    spec_source: str = "planner"
    supported_ratios: Tuple[str, ...] = ("1:1",)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.spec_source not in SPEC_SOURCES:
            raise ValueError(
                f"spec_source 는 {SPEC_SOURCES} 중 하나여야 한다: {self.spec_source!r}"
            )

    @property
    def allows_row_index(self) -> bool:
        return self.spec_source == "fixture"


PLANNER_CONTEXT = ValidationContext(spec_source="planner")
FIXTURE_CONTEXT = ValidationContext(spec_source="fixture")


# ──────────────────────────────────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────────────────────────────────
def validate(
    raw: dict,
    brief: Optional[CreativeBrief] = None,
    context: Optional[ValidationContext] = None,
) -> Tuple[SpecError, ...]:
    """검증만 하고 에러 목록을 돌려준다. 빈 tuple 이면 통과."""
    ctx = context or PLANNER_CONTEXT
    errors: list[SpecError] = []

    if not isinstance(raw, dict):
        return (SchemaError("schema.type", "", "RenderSpec 은 dict 이어야 한다"),)

    # trust boundary — 다른 무엇보다 먼저 본다
    for key in FORBIDDEN_ROOT_KEYS:
        if key in raw:
            errors.append(
                TrustBoundaryViolation(
                    "trust.spec_source_in_spec",
                    key,
                    "경로는 ValidationContext 가 정한다. Spec 이 선언할 수 없다",
                )
            )
    if errors:
        return tuple(errors)

    _check_node(RenderSpec, raw, "", errors)
    if errors:
        return tuple(errors)  # 타입이 깨진 트리 위에서 교차 검증하지 않는다

    spec = _build_node(RenderSpec, raw)
    _cross(spec, brief, ctx, errors)
    return tuple(errors)


def load(
    raw: dict,
    brief: Optional[CreativeBrief] = None,
    context: Optional[ValidationContext] = None,
) -> RenderSpec:
    """검증을 통과한 RenderSpec 을 돌려준다. 실패하면 SpecInvalid."""
    errors = validate(raw, brief, context)
    if errors:
        raise SpecInvalid(errors)
    return _build_node(RenderSpec, raw)


# ──────────────────────────────────────────────────────────────────────────
# ① schema — dataclass metadata 기반 워커
# ──────────────────────────────────────────────────────────────────────────
def _is_required(f: dataclasses.Field) -> bool:
    if f.metadata.get("required"):
        return True
    return f.default is MISSING and f.default_factory is MISSING


def _join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


def _missing(f: dataclasses.Field, path: str, errors: list) -> None:
    if f.metadata.get("error") == "layer":
        errors.append(
            LayerUnassigned("layer.missing", path, "layer 는 기본값이 없다 (H4)")
        )
    else:
        errors.append(SchemaError("schema.missing_field", path))


def _check_node(cls, raw: Any, path: str, errors: list) -> None:
    if not isinstance(raw, dict):
        errors.append(
            SchemaError("schema.type", path, f"dict 이어야 한다 (받음: {_tname(raw)})")
        )
        return

    flds = {f.name: f for f in fields(cls)}
    hints = get_type_hints(cls)

    for key in raw:
        if key not in flds:
            errors.append(SchemaError("schema.unknown_field", _join(path, key)))

    for name, f in flds.items():
        p = _join(path, name)
        if name not in raw:
            if _is_required(f):
                _missing(f, p, errors)
            continue
        value = raw[name]
        if value is None:
            if _is_required(f):
                _missing(f, p, errors)
            continue
        _check_value(hints[name], value, f.metadata, p, errors)


def _check_value(tp, val: Any, meta, path: str, errors: list) -> None:
    origin = get_origin(tp)

    if origin in (Union, types.UnionType):
        args = tuple(a for a in get_args(tp) if a is not _NONE_TYPE)
        if len(args) == 1:
            _check_value(args[0], val, meta, path, errors)
            return
        _check_union(args, val, meta, path, errors)
        return

    if origin in (tuple, Tuple):
        _check_tuple(tp, val, meta, path, errors)
        return

    if is_dataclass(tp):
        _check_node(tp, val, path, errors)
        return

    _check_scalar(tp, val, meta, path, errors)


def _check_union(args, val, meta, path, errors) -> None:
    """실제로 쓰이는 유니온은 `int | str` (col_start · row_anchor) 뿐이다."""
    if isinstance(val, bool):
        errors.append(SchemaError("schema.type", path, "bool 은 허용되지 않는다"))
        return
    if isinstance(val, int):
        # 정수 가지도 범위를 본다. 전에는 int 면 무조건 통과라
        # `col_start: -1` 같은 값이 스키마 단계를 그냥 지나갔다
        bounds = meta.get("range")
        if bounds is not None:
            lo, hi = bounds
            if val < lo or (hi is not None and val > hi):
                span = f"{lo}~{hi}" if hi is not None else f"{lo} 이상"
                errors.append(
                    SchemaError("schema.range", path, f"{span} 범위여야 한다 (받음: {val!r})"))
        return
    if isinstance(val, str):
        allowed = meta.get("str_enum")
        if allowed and val not in allowed:
            errors.append(
                SchemaError(
                    "schema.enum",
                    path,
                    f"문자열 값은 {allowed} 중 하나여야 한다 (받음: {val!r})",
                )
            )
        return
    names = "|".join(getattr(a, "__name__", str(a)) for a in args)
    errors.append(SchemaError("schema.type", path, f"{names} 여야 한다 (받음: {_tname(val)})"))


def _check_tuple(tp, val, meta, path, errors) -> None:
    if isinstance(val, (str, bytes)) or not isinstance(val, (list, tuple)):
        errors.append(SchemaError("schema.type", path, f"목록이어야 한다 (받음: {_tname(val)})"))
        return

    need = meta.get("min_items")
    if need is not None and len(val) < need:
        errors.append(
            SchemaError("schema.min_items", path, f"최소 {need}개 필요 (받음: {len(val)})")
        )

    args = get_args(tp)
    item_tp = args[0] if args else Any
    allowed = meta.get("item_enum")
    for i, item in enumerate(val):
        ip = f"{path}[{i}]"
        if allowed is not None:
            if item not in allowed:
                errors.append(
                    SchemaError("schema.enum", ip, f"{allowed} 중 하나여야 한다 (받음: {item!r})")
                )
            continue
        if item_tp is Any:
            continue
        _check_value(item_tp, item, {}, ip, errors)


def _check_scalar(tp, val, meta, path, errors) -> None:
    if tp is bool:
        if not isinstance(val, bool):
            errors.append(SchemaError("schema.type", path, f"bool 이어야 한다 (받음: {_tname(val)})"))
            return
    elif tp is int:
        if isinstance(val, bool) or not isinstance(val, int):
            errors.append(SchemaError("schema.type", path, f"int 이어야 한다 (받음: {_tname(val)})"))
            return
    elif tp is float:
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            errors.append(SchemaError("schema.type", path, f"수치여야 한다 (받음: {_tname(val)})"))
            return
    elif tp is str:
        if not isinstance(val, str):
            errors.append(SchemaError("schema.type", path, f"str 이어야 한다 (받음: {_tname(val)})"))
            return
    elif tp is dict:
        if not isinstance(val, dict):
            errors.append(SchemaError("schema.type", path, f"dict 이어야 한다 (받음: {_tname(val)})"))
            return

    allowed = meta.get("enum") or meta.get("choices")
    if allowed is not None and val not in allowed:
        code = "layer.unknown" if meta.get("error") == "layer" else "schema.enum"
        err = LayerUnassigned if meta.get("error") == "layer" else SchemaError
        errors.append(err(code, path, f"{allowed} 중 하나여야 한다 (받음: {val!r})"))
        return

    bounds = meta.get("range")
    if bounds is not None and isinstance(val, (int, float)):
        lo, hi = bounds
        if val < lo or (hi is not None and val > hi):
            span = f"{lo}~{hi}" if hi is not None else f"{lo} 이상"
            errors.append(
                SchemaError("schema.range", path, f"{span} 범위여야 한다 (받음: {val!r})")
            )


def _tname(val) -> str:
    return type(val).__name__


# ──────────────────────────────────────────────────────────────────────────
# ② build — ①을 통과한 뒤에만 호출된다
# ──────────────────────────────────────────────────────────────────────────
def _build_node(cls, raw: dict):
    hints = get_type_hints(cls)
    kwargs = {}
    for f in fields(cls):
        if f.name not in raw or raw[f.name] is None:
            continue
        kwargs[f.name] = _build_value(hints[f.name], raw[f.name])
    return cls(**kwargs)


def _build_value(tp, val):
    origin = get_origin(tp)

    if origin in (Union, types.UnionType):
        args = tuple(a for a in get_args(tp) if a is not _NONE_TYPE)
        if len(args) == 1:
            return _build_value(args[0], val)
        return val  # int | str 은 그대로

    if origin in (tuple, Tuple):
        args = get_args(tp)
        item_tp = args[0] if args else Any
        if item_tp is Any or not is_dataclass(item_tp):
            return tuple(val)
        return tuple(_build_node(item_tp, item) for item in val)

    if is_dataclass(tp):
        return _build_node(tp, val)

    if tp is dict:
        # 검증을 통과한 Spec 은 이후 단계에서 변형되면 안 된다 (§9 결정론).
        # frozen dataclass 는 필드 재할당만 막으므로 dict 내부는 별도로 닫는다.
        # 원본 raw 를 그대로 감싸면 호출자가 raw 를 고쳐 Spec 을 바꿀 수 있으니
        # **복사한 뒤** 읽기 전용 뷰로 감싼다
        return types.MappingProxyType(dict(val))

    return val


# ──────────────────────────────────────────────────────────────────────────
# ③ cross — 교차 필드 규칙
# ──────────────────────────────────────────────────────────────────────────
def _cross(spec: RenderSpec, brief, ctx: ValidationContext, errors: list) -> None:
    _c_version(spec, ctx, errors)
    _c_ratio(spec, ctx, errors)
    _c_layers(spec, errors)
    _c_product(spec, errors)
    _c_background(spec, errors)
    _c_palette(spec, brief, errors)
    _c_typography(spec, errors)
    _c_zones(spec, errors)
    _c_motif(spec, errors)
    _c_copy(spec, brief, errors)
    _c_grid_refs(spec, errors)
    _c_color_roles(spec, errors)
    _c_anchors(spec, ctx, errors)
    _c_safety(spec, errors)


def _c_version(spec, ctx, errors) -> None:
    if spec.schema_version != ctx.schema_version:
        errors.append(
            SpecRejected(
                "schema.version_unsupported",
                "schema_version",
                f"{ctx.schema_version} 만 지원 (받음: {spec.schema_version!r})",
            )
        )


def _c_ratio(spec, ctx, errors) -> None:
    if spec.canvas.ratio not in ctx.supported_ratios:
        errors.append(
            RatioUnsupported(
                "canvas.ratio_unsupported",
                "canvas.ratio",
                f"현재 Renderer 는 {ctx.supported_ratios} 만 처리한다 — "
                f"근사·자동 대체를 하지 않는다 (받음: {spec.canvas.ratio!r})",
            )
        )


def _c_layers(spec, errors) -> None:
    if tuple(spec.layers) != LAYER_STACK:
        errors.append(
            SpecRejected(
                "layers.not_canonical",
                "layers",
                f"stacking order 는 canonical LAYER_STACK 으로 고정이다: {LAYER_STACK}",
            )
        )


def _c_product(spec, errors) -> None:
    p = spec.product
    if p.fit == "area_cap" and p.area_cap is None:
        errors.append(
            SpecRejected("product.area_cap_missing", "product.area_cap", "fit=area_cap 인데 값이 없다")
        )
    if p.fit != "area_cap" and p.area_cap is not None:
        errors.append(
            SpecRejected(
                "product.area_cap_unused",
                "product.area_cap",
                f"fit={p.fit} 에서는 area_cap 이 쓰이지 않는다 — 조용히 무시하지 않는다",
            )
        )
    if len(set(p.bleed)) != len(p.bleed):
        errors.append(SpecRejected("product.bleed_duplicate", "product.bleed"))


def _c_background(spec, errors) -> None:
    b = spec.background
    if b.mode == "generated" and b.visual_style is None:
        errors.append(
            SpecRejected(
                "background.visual_style_missing",
                "background.visual_style",
                "mode=generated 는 visual_style 이 필요하다",
            )
        )
    if b.mode != "generated" and b.visual_style is not None:
        errors.append(
            SpecRejected(
                "background.visual_style_unused",
                "background.visual_style",
                f"mode={b.mode} 에서는 visual_style 이 쓰이지 않는다",
            )
        )


def _c_palette(spec, brief, errors) -> None:
    pal = spec.palette
    roles = tuple(pal.roles)

    if len(set(roles)) != len(roles):
        errors.append(SpecRejected("palette.duplicate_role", "palette.roles"))

    missing = [r for r in REQUIRED_PALETTE_ROLES if r not in roles]
    if missing:
        errors.append(
            SpecRejected("palette.missing_base_roles", "palette.roles", f"필수 역할 누락: {missing}")
        )

    if pal.source == "fixed" and pal.fixed_values is None:
        errors.append(
            SpecRejected(
                "palette.fixed_values_missing",
                "palette.fixed_values",
                "source=fixed 인데 값이 없다",
            )
        )
    # v0.5 — source=preferred 는 brief 쪽 입력이 반드시 있어야 한다.
    # 없는데 통과시키면 resolver 가 product_signals 로 조용히 넘어가거나
    # 임의 기본색을 쓰게 된다. 둘 다 사용자가 고른 색이 아니다.
    if pal.source == "preferred" and not getattr(brief, "preferred_color", None):
        errors.append(
            SpecRejected(
                "palette.preferred_color_missing",
                "palette.source",
                "source=preferred 인데 brief.preferred_color 가 없다 — "
                "다른 source 로 대체하지 않는다",
            )
        )

    if pal.source != "fixed" and pal.fixed_values is not None:
        errors.append(
            SpecRejected(
                "palette.fixed_values_unused",
                "palette.fixed_values",
                f"source={pal.source} 에서 색 값은 유도된다 — 고정값을 받지 않는다",
            )
        )

    if pal.fixed_values:
        for key, val in pal.fixed_values.items():
            kp = f"palette.fixed_values.{key}"
            if key not in roles:
                errors.append(
                    SpecRejected("palette.fixed_values_unknown_role", kp, f"palette.roles 에 없다")
                )
            if not (isinstance(val, str) and _HEX.match(val)):
                errors.append(
                    SpecRejected("palette.fixed_value_format", kp, f"#RRGGBB 여야 한다 (받음: {val!r})")
                )

    rh = pal.rhythm
    if rh.spot_path == "none" and rh.spot_min_regions > 1:
        errors.append(
            SpecRejected(
                "palette.spot_rhythm_conflict",
                "palette.rhythm",
                f"spot_path=none 인데 spot_min_regions={rh.spot_min_regions} — "
                "선언한 구조는 결과에서 관측돼야 한다 (H5)",
            )
        )
    if rh.spot_min_regions > 1 and "spot" not in roles:
        errors.append(
            SpecRejected("palette.spot_role_missing", "palette.roles", "spot 순환을 선언했는데 spot 역할이 없다")
        )


def _c_typography(spec, errors) -> None:
    ids = [r.id for r in spec.typography.roles]
    if len(set(ids)) != len(ids):
        errors.append(SpecRejected("typography.duplicate_role_id", "typography.roles", f"{ids}"))

    # 번들 폰트로 정확히 표현되지 않는 조합은 **대체하지 않고 거부**한다.
    # weight 를 조용히 바꾸면 RenderSpec 을 그대로 렌더한 것이 아니다 (E11 §1-4)
    for i, role in enumerate(spec.typography.roles):
        if (role.family, role.weight) not in SUPPORTED_TYPE_FACES:
            errors.append(
                SpecRejected(
                    "typography.unsupported_face",
                    f"typography.roles[{i}]",
                    f"{role.family}/{role.weight} 는 지원하지 않는다 "
                    f"(가능: {[f'{f}/{w}' for f, w in SUPPORTED_TYPE_FACES]})",
                )
            )
    if spec.typography.measure_cols > spec.grid.columns:
        errors.append(
            SpecRejected(
                "typography.measure_cols_overflow",
                "typography.measure_cols",
                f"grid.columns={spec.grid.columns} 보다 클 수 없다",
            )
        )


def _span(zone) -> range:
    return range(zone.col_start, zone.col_start + zone.col_span)


def _c_zones(spec, errors) -> None:
    cols = spec.grid.columns
    for name in ("type", "product"):
        z = getattr(spec.zones, name)
        if z.col_start + z.col_span > cols:
            errors.append(
                SpecRejected(
                    "zones.span_overflow",
                    f"zones.{name}",
                    f"col_start {z.col_start} + col_span {z.col_span} > columns {cols}",
                )
            )

    # ★ v0.3 — overlap 과 z-order 의 **책임을 분리**했다 (§4-7).
    #
    #   overlap_intent   "겹치는가 / 겹쳐도 되는가"  → none | allowed | required
    #   layer            "겹쳤을 때 누가 위인가"      → 요소마다 이미 선언돼 있다
    #
    # ① 열 교집합으로 overlap_intent 를 검증하지 않는다.
    #    예전 규칙("zone 이 열에서 겹치면 none 불가")은 틀린 기준이었다 —
    #    zone 은 1차원이라 열이 겹쳐도 세로로 갈라져 안 겹칠 수 있고(Step 5 B),
    #    열이 안 겹쳐도 bleed·회전으로 겹칠 수 있다.
    #
    # ② 여기서 z-order 를 유추하지 않는다.
    #    한 판면 안에서 headline 은 제품 뒤, token 은 제품 앞인 mixed 구성이
    #    정상이다(Step 5 C).  최상위 값 하나로 대표할 수 없다.
    #
    # 실제 판정은 RenderPlan 의 bbox + 블록별 layer 를 보는 Step 6 이 한다.
    # 여기서는 zone 자체의 정합성(범위 초과)만 본다.


def _c_motif(spec, errors) -> None:
    m = spec.motif
    has_pattern = m.pattern is not None
    has_instances = bool(m.instances)

    if m.shape == "none":
        if has_pattern or has_instances:
            errors.append(
                SpecRejected(
                    "motif.shape_none_with_elements",
                    "motif",
                    "shape=none 인데 pattern/instances 가 있다",
                )
            )
        return

    if not has_pattern and not has_instances:
        errors.append(
            SpecRejected(
                "motif.shape_without_elements",
                "motif",
                f"shape={m.shape} 인데 그릴 것이 없다",
            )
        )

    total = (m.pattern.repeat if has_pattern else 0) + len(m.instances)
    if total < m.min_repeats:
        errors.append(
            SpecRejected(
                "motif.repeats_below_min",
                "motif.min_repeats",
                f"pattern.repeat + instances = {total} < min_repeats {m.min_repeats} — "
                "선언한 반복이 충족되지 않는다 (H5)",
            )
        )

    roles = [i.role for i in m.instances]
    if has_pattern:
        roles.append(m.pattern.role)      # pattern 도 같은 이름 공간을 쓴다
    if len(set(roles)) != len(roles):
        errors.append(SpecRejected("motif.duplicate_role", "motif", f"{roles}"))

    cols = spec.grid.columns
    for i, inst in enumerate(m.instances):
        if inst.split_at is None:
            continue
        p = f"motif.instances[{i}].split_at.col"
        if inst.orientation == "vertical":
            errors.append(
                SpecRejected(
                    "motif.split_at_on_vertical",
                    p,
                    "세로 요소에는 열 기준 분할점을 쓸 수 없다 — 조용히 무시하지 않는다",
                )
            )
            continue
        if isinstance(inst.grid_ref.col_start, str):
            errors.append(
                SpecRejected(
                    "motif.split_at_on_named_region", p, "명명 영역 위에서는 열 기준 분할점을 쓸 수 없다"
                )
            )
            continue
        lo = inst.grid_ref.col_start
        hi = lo + (inst.grid_ref.col_span or 0)
        if not (lo <= inst.split_at.col <= hi):
            errors.append(
                SpecRejected(
                    "motif.split_at_out_of_span", p, f"instance 범위 {lo}~{hi} 밖이다"
                )
            )
        if inst.split_at.col > cols:
            errors.append(SpecRejected("motif.split_at_out_of_range", p, f"columns {cols} 초과"))


def _c_copy(spec, brief, errors) -> None:
    ids = [b.id for b in spec.copy_blocks]
    if len(set(ids)) != len(ids):
        errors.append(SpecRejected("copy.duplicate_id", "copy_blocks", f"{ids}"))

    type_ids = {r.id for r in spec.typography.roles}
    for i, block in enumerate(spec.copy_blocks):
        base = f"copy_blocks[{i}]"
        if block.type_role not in type_ids:
            errors.append(
                SpecRejected(
                    "copy.type_role_unknown",
                    f"{base}.type_role",
                    f"typography.roles 에 없다: {block.type_role!r} (있는 것: {sorted(type_ids)})",
                )
            )
        if not block.content_ref.startswith("brief."):
            errors.append(
                SpecRejected(
                    "copy.content_ref_form",
                    f"{base}.content_ref",
                    f"'brief.' 로 시작하는 참조여야 한다 (받음: {block.content_ref!r})",
                )
            )
        elif brief is not None and resolve_content_ref(brief, block.content_ref) is None:
            errors.append(
                ContentRefUnresolved(
                    "copy.content_ref_unresolved",
                    f"{base}.content_ref",
                    f"{block.content_ref!r} 를 해석할 수 없다 "
                    f"(해석 가능: {list(known_content_refs(brief))})",
                )
            )


def _iter_grid_refs(spec) -> Tuple[Tuple[str, GridRef], ...]:
    out = []
    for i, block in enumerate(spec.copy_blocks):
        out.append((f"copy_blocks[{i}].grid_ref", block.grid_ref))
    for i, inst in enumerate(spec.motif.instances):
        out.append((f"motif.instances[{i}].grid_ref", inst.grid_ref))
    if spec.motif.pattern is not None:
        out.append(("motif.pattern.region", spec.motif.pattern.region))
    return tuple(out)


def _c_grid_refs(spec, errors) -> None:
    cols = spec.grid.columns
    for path, ref in _iter_grid_refs(spec):
        if isinstance(ref.col_start, str):
            if ref.col_span is not None:
                errors.append(
                    CoordinateMixing(
                        "grid_ref.span_with_named_region",
                        f"{path}.col_span",
                        f"명명 영역 {ref.col_start!r} 은 범위를 스스로 정의한다 — "
                        "열 번호 좌표계와 섞지 않는다",
                    )
                )
            continue
        if not (0 <= ref.col_start < cols):
            errors.append(
                SpecRejected(
                    "grid_ref.col_out_of_range",
                    f"{path}.col_start",
                    f"0~{cols - 1} 범위여야 한다 (받음: {ref.col_start})",
                )
            )
            continue
        if ref.col_span is None:
            errors.append(
                SpecRejected(
                    "grid_ref.span_missing", f"{path}.col_span", "열 번호를 쓰면 col_span 이 필요하다"
                )
            )
            continue
        if ref.col_start + ref.col_span > cols:
            errors.append(
                SpecRejected(
                    "grid_ref.span_overflow",
                    f"{path}.col_span",
                    f"col_start {ref.col_start} + col_span {ref.col_span} > columns {cols}",
                )
            )


#: `color_role` 을 참조하는 **모든** 자리. 규칙 설명과 실제 검사가 같은
#: 목록을 본다 — 설명에만 몇 개 적어 두면 범위가 조용히 좁아진다.
COLOR_ROLE_REF_PATHS: Tuple[str, ...] = (
    "typography.roles[].color_role",
    "copy_blocks[].color_role",
    "motif.instances[].color_role",
    "motif.pattern.color_role",
)


def color_role_references(spec) -> Tuple[Tuple[str, str], ...]:
    """`(경로, 값)` 목록. `COLOR_ROLE_REF_PATHS` 와 **같은 순서**다."""
    out: list = []
    for i, r in enumerate(spec.typography.roles):
        out.append((f"typography.roles[{i}].color_role", r.color_role))
    for i, b in enumerate(spec.copy_blocks):
        out.append((f"copy_blocks[{i}].color_role", b.color_role))
    for i, inst in enumerate(spec.motif.instances):
        out.append((f"motif.instances[{i}].color_role", inst.color_role))
    if spec.motif.pattern is not None:
        out.append(("motif.pattern.color_role", spec.motif.pattern.color_role))
    return tuple(out)


def _c_color_roles(spec, errors) -> None:
    """**참조 폐포** — 실제로 쓰는 역할은 전부 `palette.roles` 안에 있어야 한다.

    "지원되는 이름인가" 와 "선언했는가" 는 다른 조건이다. run 03 에서 모델이
    `emphasis`(합법 이름)를 선언 없이 참조했다.
    """
    roles = set(spec.palette.roles)

    for path, value in color_role_references(spec):
        for part in value.split(PALETTE_ROLE_TRANSITION):
            part = part.strip()
            if part not in roles:
                errors.append(
                    SpecRejected(
                        "palette.color_role_unknown",
                        path,
                        f"palette.roles 에 없다: {part!r} (있는 것: {sorted(roles)})",
                    )
                )


def _anchor_order(spec) -> Tuple[Tuple[str, str, Any], ...]:
    """§4-2 해석 순서 — copy_blocks 먼저, 그다음 motif."""
    out = []
    for i, b in enumerate(spec.copy_blocks):
        out.append((b.id, f"copy_blocks[{i}]", b.grid_ref.row_anchor))
    for i, inst in enumerate(spec.motif.instances):
        out.append((inst.role, f"motif.instances[{i}]", inst.grid_ref.row_anchor))
    if spec.motif.pattern is not None:
        out.append(
            (spec.motif.pattern.role, "motif.pattern", spec.motif.pattern.region.row_anchor)
        )
    return tuple(out)


def _c_anchors(spec, ctx: ValidationContext, errors) -> None:
    order = _anchor_order(spec)
    names = [n for n, _, _ in order]

    reserved = sorted(set(names) & set(RESERVED_ANCHOR_TARGETS))
    if reserved:
        errors.append(SpecRejected(
            "anchor.reserved_name",
            "copy_blocks / motif.instances",
            f"{reserved} 는 제품 관계 anchor 가 쓰는 예약어라 id/role 로 쓸 수 없다 "
            f"(after:product / before:product 와 구분되지 않는다)",
        ))

    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        errors.append(
            SpecRejected(
                "anchor.namespace_collision",
                "copy_blocks / motif.instances",
                f"copy block id 와 motif role 이 겹친다: {sorted(dupes)} — "
                "anchor 참조가 모호해진다",
            )
        )

    index = {n: i for i, n in enumerate(names)}
    edges: dict[str, str] = {}

    for pos, (name, path, anchor) in enumerate(order):
        p = f"{path}.grid_ref.row_anchor" if not path.endswith("pattern") else f"{path}.region.row_anchor"

        if isinstance(anchor, bool):
            errors.append(SchemaError("schema.type", p, "bool 은 허용되지 않는다"))
            continue

        if isinstance(anchor, int):
            if not ctx.allows_row_index:
                errors.append(
                    SpecRejected(
                        "row_anchor.index_in_planner_path",
                        p,
                        f"planner 경로에서는 정수 row index 를 만들 수 없다 (받음: {anchor}) — "
                        "의미적 관계만 허용한다 (§4-2)",
                    )
                )
            elif anchor < 0:
                errors.append(SpecRejected("row_anchor.negative_index", p, f"{anchor}"))
            continue

        if not isinstance(anchor, str):
            errors.append(SchemaError("schema.type", p, f"int|str 이어야 한다 (받음: {_tname(anchor)})"))
            continue

        if anchor in ABSOLUTE_ROWS or anchor in PRODUCT_ROW_ALIGNS:
            continue

        # 제품 관계는 블록 이름 공간을 쓰지 않는다 — 아래 target 조회 전에 건진다
        if anchor in PRODUCT_ROW_SEQUENCE:
            continue

        prefix = next((x for x in ROW_REL_PREFIXES if anchor.startswith(x)), None)
        if prefix is None:
            errors.append(
                SpecRejected(
                    "row_anchor.unknown_form",
                    p,
                    f"허용 형태: {ABSOLUTE_ROWS} · {ROW_REL_PREFIXES}<id> · "
                    f"{PRODUCT_ROW_ALIGNS} · {PRODUCT_ROW_SEQUENCE} (받음: {anchor!r})",
                )
            )
            continue

        target = anchor[len(prefix):]
        if target == name:
            errors.append(AnchorUnresolvable("anchor.self_reference", p, f"{anchor!r}"))
            continue
        if target not in index:
            errors.append(
                AnchorUnresolvable(
                    "anchor.unknown_target", p, f"{target!r} 라는 블록/모티프가 없다"
                )
            )
            continue
        edges[name] = target
        if index[target] > pos:
            errors.append(
                AnchorUnresolvable(
                    "anchor.forward_reference",
                    p,
                    f"{target!r} 는 아직 해석되지 않았다 — 선언 순서상 뒤에 있다 (§4-2)",
                )
            )

    _detect_cycle(edges, errors)


def _detect_cycle(edges: dict, errors: list) -> None:
    """전방 참조 금지가 순환을 대부분 막지만, 안전망으로 직접 검출한다."""
    seen: set[str] = set()
    for start in edges:
        if start in seen:
            continue
        path: list[str] = []
        node = start
        local: set[str] = set()
        while node in edges:
            if node in local:
                cycle = " → ".join(path[path.index(node):] + [node])
                errors.append(AnchorUnresolvable("anchor.cycle", "row_anchor", cycle))
                break
            local.add(node)
            path.append(node)
            node = edges[node]
        seen |= local


# ── cross-field 규칙의 서술 표 ─────────────────────────────────────────
#
# strict JSON Schema 로는 조건부 관계를 **표현할 수 없다** — `if/then/else`
# 도 `dependentRequired` 도 Structured Outputs 미지원이다. 그래서 여기
# 검사들을 문장으로도 적어 두고, Planner schema/capabilities 가 이 표를
# 그대로 실어 보낸다.
#
# ★ 새 규칙이 아니다. 아래는 전부 이 파일에 이미 있는 검사이고 괄호 안이
#   실제 오류 코드다. run 02 에서 후보 3개가 이 관계들을 모른 채 만들어졌다.
CROSS_FIELD_RULES: Tuple[Tuple[str, str], ...] = (
    ("background.visual_style",
     "mode=generated 일 때만 값을 넣는다. flat · gradient 면 반드시 null "
     "(background.visual_style_missing / visual_style_unused)"),
    ("palette.roles",
     "bg 와 ink 는 반드시 포함한다 (palette.missing_base_roles). "
     "rhythm.spot_path 가 none 이 아니면 spot 도 포함한다 (palette.spot_role_missing)"),
    ("*.color_role (참조 폐포)",
     "실제로 참조하는 모든 color_role 이 palette.roles 안에 선언돼 있어야 한다. "
     "지원되는 이름인 것과 선언한 것은 다른 조건이다 — emphasis 를 쓰려면 "
     "palette.roles 에 emphasis 를 넣는다. 참조 자리: "
     + " · ".join(COLOR_ROLE_REF_PATHS)
     + " (palette.color_role_unknown)"),
    # ── 참조 무결성 ────────────────────────────────────────────────────
    # `color_role → palette.roles` 폐포와 **같은 성격**이다. run 05 의
    # graphic_contrast 가 셋 다 어겼는데, 셋 다 스키마에도 프롬프트에도
    # 없었다 (B — contract gap).
    ("copy_blocks[].type_role",
     "typography.roles[].id 중 하나를 가리켜야 한다. 쓰려는 역할을 "
     "typography.roles 에 먼저 선언한다 (copy.type_role_unknown)"),
    ("copy_blocks[].id · motif role",
     "copy block id 와 motif role(instances[].role · pattern.role)은 "
     "**같은 이름 공간**을 쓴다. 이름이 겹치면 after:/before: anchor 와 "
     "safety 참조가 어느 쪽을 가리키는지 정해지지 않아 거부된다 "
     "(anchor.namespace_collision). 'product' 는 제품 관계 anchor 의 "
     "예약어라 어느 쪽에서도 쓸 수 없다 (anchor.reserved_name)"),
    ("motif.instances[].role",
     "서로 달라야 한다. pattern.role 도 같은 이름 공간이라 함께 센다 "
     "(motif.duplicate_role). copy_blocks[].id 도 서로 달라야 한다 "
     "(copy.duplicate_id)"),
    ("motif.shape",
     "none 이 아니면 pattern 또는 instances 가 실제로 있어야 한다. shape 만 "
     "선언하고 그릴 것을 두지 않으면 거부된다 (motif.shape_without_elements). "
     "반대로 none 이면 pattern·instances 가 비어 있어야 한다 "
     "(motif.shape_none_with_elements)"),
    ("palette.source",
     "preferred 를 고르면 사용자 선호색이 반드시 입력에 있어야 한다 "
     "(palette.preferred_color_missing). 세 source 는 독립이라 하나가 비었다고 "
     "다른 source 로 넘어가지 않는다 — 선호색이 없으면 product 나 brand 를 "
     "고른다"),
    ("palette.rhythm",
     "spot_path=none 이면 spot_min_regions 는 1 이다 — 순환을 선언하지 않았는데 "
     "영역 수를 요구할 수 없다 (palette.spot_rhythm_conflict)"),
    ("motif.min_repeats",
     "pattern.repeat 과 instances 개수의 합이 이 값 이상이어야 한다. "
     "선언한 반복은 결과에서 관측돼야 한다 (motif.repeats_below_min)"),
    ("*.col_start (정수)",
     "열 번호는 **0-based** 다 — 첫 열이 0, 마지막 열이 grid.columns - 1. "
     "그리고 col_start + col_span <= grid.columns 여야 한다. columns=6 이면 "
     "전체 폭은 col_start=0 · col_span=6 이다 "
     "(zones.span_overflow / grid_ref.span_overflow)"),
    ("*.grid_ref.col_span",
     "col_start 가 정수면 col_span 을 반드시 준다. 명명 영역"
     "(margin_left 등)일 때만 null 이 허용된다 (grid_ref.span_missing)"),
    ("safety.critical_blocks",
     "copy_blocks[].id 만 가리킨다. 비어 있으면 거부된다 (safety.critical_empty)"),
    ("safety.must_be_visible",
     "motif role(instances[].role · pattern.role) 또는 copy_blocks[].id 를 "
     "가리킨다. 둘의 이름이 겹치면 거부된다 (safety.must_be_visible_unknown / "
     "visible_target_ambiguous)"),
)


def _c_safety(spec, errors) -> None:
    s = spec.safety
    if not s.critical_blocks:
        errors.append(
            CriticalEmpty(
                "safety.critical_empty",
                "safety.critical_blocks",
                "무엇이 중요한지 선언하지 않으면 판정할 수 없다 (H3)",
            )
        )

    block_ids = {b.id for b in spec.copy_blocks}
    for cid in s.critical_blocks:
        if cid not in block_ids:
            errors.append(
                SpecRejected(
                    "safety.critical_unknown",
                    "safety.critical_blocks",
                    f"{cid!r} 라는 copy block 이 없다 (있는 것: {sorted(block_ids)})",
                )
            )

    motif_roles = {i.role for i in spec.motif.instances}
    if spec.motif.pattern is not None:
        motif_roles.add(spec.motif.pattern.role)   # pattern 도 가시성 선언 대상이다

    # ★ v0.4 — copy block 도 가리킬 수 있다.
    #
    # 전에는 motif role 만 허용했다. 그런데 Safety 는 이미 copy block 의 실제
    # 가시성을 잰다 (RenderEvidence 의 id 이름공간은 motif·copy·product 가
    # 공유한다). 즉 제약은 Safety 의 능력 한계가 아니라 여기 한 줄의 선택이었고,
    # `must_be_visible` 이라는 이름으로 "headline 이 보여야 한다" 를 못 쓰는
    # 상태였다. 실제 Planner 도 3/3 으로 headline 을 지정했다.
    #
    # product 는 넣지 않는다 — 제품 가시성은 별도 safety 검사가 담당한다.
    visible_targets = motif_roles | block_ids

    # 이름이 겹치면 **어느 쪽을 잰 것인지** 알 수 없다. 조용히 한쪽으로
    # 해석하지 않고 거부한다 — 측정 대상이 모호한 판정은 판정이 아니다
    for name in sorted(motif_roles & block_ids):
        errors.append(
            SpecRejected(
                "safety.visible_target_ambiguous",
                "safety.must_be_visible",
                f"{name!r} 이 motif role 이면서 copy block id 다 — "
                "어느 쪽을 재야 하는지 정해지지 않는다. 한쪽 이름을 바꾼다",
            )
        )

    for role in s.must_be_visible:
        if role not in visible_targets:
            errors.append(
                SpecRejected(
                    "safety.must_be_visible_unknown",
                    "safety.must_be_visible",
                    f"{role!r} 라는 motif role 도 copy block id 도 없다 "
                    f"(motif: {sorted(motif_roles)} · copy: {sorted(block_ids)})",
                )
            )


__all__ = [
    "CROSS_FIELD_RULES",
    "SPEC_SOURCES",
    "ValidationContext",
    "PLANNER_CONTEXT",
    "FIXTURE_CONTEXT",
    "validate",
    "load",
]

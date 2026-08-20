"""Planner 프롬프트 구성 — Step 9.

**허용값을 프롬프트에 손으로 적지 않는다.** 전부 `spec` 모듈에서 뽑는다.

    dynamic/spec.py  ──→  describe_capabilities()  ──→  system prompt
                     └──→  render_spec_json_schema()  ──→  structured output

스키마가 바뀌면 프롬프트와 JSON schema 가 **자동으로** 따라 바뀐다. 프롬프트에
enum 을 복사해 두면 스키마와 따로 놀게 되고, 그 순간 "왜 LLM 이 옛 값을 쓰지"를
디버깅하게 된다.

두 가지 유출 방지선이 여기 있다.

    ① `confirmation_source` 는 디자인 프롬프트에 넣지 않는다 (provenance)
    ② `background_ready() == False` 면 raw payload 를 **직렬화하지 않는다**
       — 넣으면 `hint()` 가 None 이어도 LLM 이 임의로 해석하게 되고,
         "확정되지 않은 스키마를 쓰지 않는다"는 계약이 그 자리에서 깨진다
"""

from __future__ import annotations

import dataclasses
import json
import types
from dataclasses import MISSING, fields, is_dataclass
from types import MappingProxyType
from typing import (Any, Mapping, Optional, Sequence, Tuple, Union,
                    get_args, get_origin, get_type_hints)

from .planner_io import PlannerInput, describe_capabilities
from .validate import CROSS_FIELD_RULES
from .spec import (LAYER_STACK, SCHEMA_VERSION, SUPPORTED_TYPE_FACES,
                   RenderSpec)

# ── 프롬프트 버전 ────────────────────────────────────────────────────────
#
# "1.3" → "1.4".  **feedback-information revision** 이다.
#
# 앞의 1.1~1.3 은 contract-aware revision 이었다 (Validator 계약을 노출).
# 1.4 는 성격이 다르다 — **재설계 요청 프롬프트에만** 영향을 준다.
#
# 디자인 지시문(prose)을 새로 튜닝한 것이 아니다. `SYSTEM_ROLE` 의 5개 규칙도
# `DIVERSITY_NOTE` 도 한 글자 그대로다. 바뀐 것은 capabilities projection 이
# 넓어져서 **실제로 렌더링된 system prompt 가 달라졌다**는 사실뿐이다.
#
#     v1.1 에서 추가된 capabilities
#       color_roles              Renderer 가 색을 만들 줄 아는 역할 이름
#       required_palette_roles   반드시 포함해야 하는 역할 (bg · ink)
#       cross_field_rules        Validator 의 값-사이-관계 계약
#
#     v1.2 에서 cross_field_rules 에 더해진 것 (run 03 이 드러낸 B 급 gap)
#       *.col_start              **0-based** — 첫 열이 0.  그리고
#                                col_start + col_span <= grid.columns
#       *.color_role             참조 폐포 — 쓰는 역할은 전부 palette.roles 에
#                                선언돼 있어야 한다 (지원 이름 ≠ 선언)
#       motif.shape              none 이 아니면 pattern/instances 가 있어야 한다
#
#     v1.3 에서 더해진 것 — **참조 무결성** (run 05 graphic_contrast 가 드러냄)
#       copy_blocks[].type_role  typography.roles[].id 를 가리켜야 한다
#       copy_blocks[].id
#         · motif role           같은 이름 공간 — 겹치면 anchor/safety 참조가 모호
#       motif.instances[].role   서로 달라야 한다 (pattern.role 포함)
#
#     셋 다 `color_role → palette.roles` 폐포와 같은 성격이고, 셋 다 Validator
#     에는 있었는데 Planner 쪽에는 노출된 적이 없었다.
#
#     v1.4 — SafetyFeedback 에 `Violation.detail` 을 추가
#       기존 관측 문구를 실어 보낼 뿐이다.  Safety rule 을 고치지 않았고
#       디자인 지시문도 그대로다.
#
#       숫자만으로는 무엇을 잰 것인지 알 수 없다 —
#         measured 182756 / threshold 0   "무엇의 교집합인가" 가 없다
#         measured 2.59 / threshold 3.0   "어떤 바탕과 어떻게 쟀는가" 가 없다
#       `detail` 은 계약상 observation-only 다 (safety.DETAIL_CONTRACT).
#
#     ★ 영향 범위 — **일반 생성 프롬프트는 v1.3 과 바이트 동일하다.**
#       `_feedback_block()` 은 `pin.feedback` 이 있을 때만 만들어지므로,
#       feedback 없는 첫 생성 요청에서는 v1.3 과 같은 문자열이 나온다.
#       redesign 요청에서만 failures[] 에 detail 이 한 줄씩 더 붙는다.
#
#     v1.5 — schema 0.5 (contract-aware revision)
#       프롬프트 문구를 다듬은 것이 아니라 **계약이 늘어난 것**을 반영한다.
#
#         palette.source     + preferred          (사용자 선호색 branch)
#         capabilities       + palette_sources · color_preference
#                            + background_context_fields
#         CROSS_FIELD_RULES  + palette.source ↔ preferred_color
#         facts              + preferred_color
#         background_hints   payload dict → 확인된 6개 필드
#         background_note    상태별로 다른 문구 (absent · unusable · empty)
#
#       ★ background 상태 이름이 바뀐다. 전에는 `confirmed / unconfirmed`
#       였는데, 그건 "우리가 팀 스키마를 아는가" 였다. 이제 스키마를
#       확인했으므로 질문이 달라진다 — "이 요청에 쓸 배경 정보가 있는가".
#       `absent / unusable / empty / present` 는 그 질문의 답이다.
#
#       `unusable` 은 팀이 `usable=false` 로 표시한 경우다. 이때 필드를
#       하나도 싣지 않는다 — 못 쓴다고 한 분석에서 일부만 골라 쓰면
#       그 판단을 우리가 뒤집는 것이 된다.
#
# 이 셋은 단순 메타데이터가 아니라 모델의 디자인 결정에 직접 들어가는 입력이다.
# 같은 prompt_version 에 다른 내용을 담지 않는다 — schema_version 에 적용한
# 원칙과 같다. `prompt_digest` 가 문자열 차이를 잡아내더라도, 실험 기록에서
# **의미가 바뀐 프롬프트는 버전도 바꾼다.**
#
# 하지 않은 것 — "copy_blocks 를 꼭 넣어라" 같은 지시문 추가. 관계 규칙은
# capabilities 로만 전달하고, 그것만으로 모델이 지키는지 먼저 본다. 부족하면
# 그때 전용 instruction 을 검토한다.
PROMPT_VERSION = "1.5"
_NONE = type(None)


# ──────────────────────────────────────────────────────────────────────────
# JSON schema — dataclass 에서 뽑는다 (단일 출처)
# ──────────────────────────────────────────────────────────────────────────
def _json_for(tp, meta: Mapping) -> dict:
    origin = get_origin(tp)

    if origin in (Union, types.UnionType):
        args = tuple(a for a in get_args(tp) if a is not _NONE)
        nullable = len(args) != len(get_args(tp))
        if len(args) == 1:
            base = _json_for(args[0], meta)
            if nullable:
                base = {"anyOf": [base, {"type": "null"}]}
            return base
        # 실제로 쓰이는 유니온은 int | str (col_start · row_anchor) 뿐이다.
        # ★ 정수 가지도 `rng` 메타데이터를 받는다 — 전에는 유니온이면 범위가
        #   통째로 사라져서 grid_ref.col_start 에 minimum 이 붙지 않았다
        int_branch: dict = {"type": "integer"}
        if meta.get("range"):
            lo, hi = meta["range"]
            if lo is not None:
                int_branch["minimum"] = lo
            if hi is not None:
                int_branch["maximum"] = hi
        opts: list = [int_branch]
        if meta.get("str_enum"):
            opts.append({"type": "string", "enum": list(meta["str_enum"])})
        else:
            opts.append({"type": "string"})
        if nullable:
            opts.append({"type": "null"})
        out = {"anyOf": opts}
        if meta.get("describe"):
            out["description"] = meta["describe"]
        return out

    if origin in (tuple, Tuple):
        args = get_args(tp)
        item = args[0] if args else Any
        if meta.get("item_enum"):
            items = {"type": "string", "enum": list(meta["item_enum"])}
        elif is_dataclass(item):
            items = _json_object(item)
        else:
            items = _json_for(item, {})
        out = {"type": "array", "items": items}
        if meta.get("min_items"):
            out["minItems"] = meta["min_items"]
        return out

    if is_dataclass(tp):
        return _json_object(tp)

    if meta.get("enum"):
        return {"type": "string", "enum": list(meta["enum"])}
    if meta.get("choices"):
        return {"type": "integer", "enum": list(meta["choices"])}

    base: dict = {"type": {str: "string", int: "integer", float: "number",
                           bool: "boolean", dict: "object"}.get(tp, "string")}
    if meta.get("range"):
        lo, hi = meta["range"]
        if lo is not None:
            base["minimum"] = lo
        if hi is not None:
            base["maximum"] = hi
    if meta.get("describe"):
        base["description"] = meta["describe"]
    return base


def _json_object(cls) -> dict:
    hints = get_type_hints(cls)
    props, required = {}, []
    for f in fields(cls):
        schema = _json_for(hints[f.name], f.metadata)
        need = f.metadata.get("required") or (
            f.default is MISSING and f.default_factory is MISSING)
        if need:
            required.append(f.name)
            # `Optional[X]` 인데 required 인 필드가 여럿 있다 (dataclass 필드
            # 순서 제약 때문에 default=None 을 붙인 것들). 필수인데 null 을
            # 허용한다고 알려 주면 모델이 null 을 낸다 → null 가지를 뺀다
            opts = schema.get("anyOf")
            if opts and {"type": "null"} in opts:
                rest = [o for o in opts if o != {"type": "null"}]
                schema = rest[0] if len(rest) == 1 else {"anyOf": rest}
        props[f.name] = schema
    return {"type": "object", "properties": props,
            "required": required, "additionalProperties": False}


def render_spec_json_schema() -> dict:
    """**generic** RenderSpec schema — 스키마가 표현할 수 있는 전부.

    fixture/debug 경로까지 포함하므로 **LLM 에 그대로 노출하지 않는다.**
    Planner 용은 `planner_render_spec_schema()` 다.
    """
    return _json_object(RenderSpec)


# ──────────────────────────────────────────────────────────────────────────
# capability projection — Planner 가 **실행 가능한 subset** 만 노출한다
# ──────────────────────────────────────────────────────────────────────────
#
#   generic RenderSpec schema
#           ↓  Planner capability filter
#   Planner output JSON schema
#
# 스키마가 Planner capability 보다 넓으면, 모델이 만들어 놓고 나중에
# `review_candidates()` 가 거부하는 일이 생긴다. validator 가 방어하는 것은
# 맞지만 **애초에 만들 수 없게** 하는 편이 낫다.
#
# 여기서 새 기능을 열지 않는다. 좁히기만 한다.
PLANNER_PROJECTIONS: Tuple[Tuple[str, str], ...] = (
    ("*.row_anchor", "정수 row index 제거 — fixture/debug 경로 전용 문법이다"),
    ("canvas.ratio", "현재 Renderer 의 supported_ratios 만 (3:4 · 3:1 은 RatioUnsupported)"),
    ("schema_version", "현재 버전으로 고정 — Planner 가 버전을 만들지 않는다"),
    ("layers", "**제거** — canonical stack 은 system invariant 다. Planner 는 "
     "각 요소의 layer 만 정한다 (build_plan 이 LAYER_STACK 을 직접 쓴다)"),
    ("palette.source/strategy", "fixed 제외 — Planner 는 색 값을 만들지 않는다"),
    ("palette.fixed_values", "null 고정 — 동적 key 라 strict 로 옮길 수 없다"),
    ("palette.roles", "Renderer 가 색을 만들 줄 아는 이름만 (color_roles.py 단일 출처)"),
    ("typography.roles[]", "family×weight 를 실제 렌더 가능한 5조합으로 묶는다"),
)

_PLANNER_ROW_ANCHOR_PATTERN = (
    r"^(top|upper|center|lower|bottom"
    r"|align:product_top|align:product_bottom"
    r"|after:product|before:product"
    r"|after:[A-Za-z0-9_]+|before:[A-Za-z0-9_]+)$"
)


def _planner_row_anchor() -> dict:
    from .spec import (ABSOLUTE_ROWS, PRODUCT_ROW_ALIGNS, PRODUCT_ROW_SEQUENCE)

    fixed = list(ABSOLUTE_ROWS) + list(PRODUCT_ROW_ALIGNS) + list(PRODUCT_ROW_SEQUENCE)
    return {
        "type": "string",           # ★ integer 가지를 없앤다
        "pattern": _PLANNER_ROW_ANCHOR_PATTERN,
        "description": (
            "세로 위치. **의미적 관계만** 쓴다. "
            f"고정값 {fixed} 또는 after:<block_id> · before:<block_id>. "
            "block_id 는 같은 Spec 의 copy_blocks[].id 이고 **선언 순서상 앞선 것**만 "
            "가리킬 수 있다. 정수 row index 는 이 경로에서 허용되지 않는다."
        ),
    }


def _project(node: Any) -> Any:
    """schema 를 훑으며 `row_anchor` 를 Planner 판으로 바꾼다."""
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict) and "row_anchor" in props:
            node = dict(node)
            node["properties"] = {**props, "row_anchor": _planner_row_anchor()}
            props = node["properties"]
        return {k: _project(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_project(v) for v in node]
    return node


def planner_render_spec_schema(allowed_ratios: Sequence[str] = ("1:1",)) -> dict:
    """Planner 가 **실제로 실행 가능한** RenderSpec 만 표현하는 schema."""
    schema = _project(render_spec_json_schema())
    props = schema["properties"]
    props["canvas"] = {**props["canvas"],
                       "properties": {**props["canvas"]["properties"],
                                      "ratio": {"type": "string",
                                                "enum": list(allowed_ratios)}}}
    # const 대신 **단일값 enum** 을 쓴다. 표현력은 같고, enum 은 지원이
    # 명확한 반면 const 는 확인되지 않았다 — 확실한 쪽으로 적는다
    props["schema_version"] = {"type": "string", "enum": [SCHEMA_VERSION],
                               "description": f"반드시 {SCHEMA_VERSION!r}"}
    # ── layers 는 Planner 출력이 아니다 ──────────────────────────────────
    #
    # canonical stacking order 는 **system invariant** 다. Planner 가 정하는
    # 것은 "각 요소를 어느 layer 에 놓을까"(copy_blocks[].layer ·
    # motif.instances[].layer) 이고, stack 자체의 순서가 아니다.
    #
    # 실제로 `build_plan()` 은 `spec.layers` 를 읽지 않는다 — `LAYER_STACK` 을
    # 직접 쓴다. 즉 Planner 가 만든 배열은 검증에 쓰인 뒤 버려졌다.
    #
    #   LLM 이 상수를 재생산 → _c_layers 가 상수와 대조 → plan 이 상수를 쓴다
    #
    # 게다가 이 필드는 dataclass default 가 있어 generic/planner schema 에서
    # required 가 아니었는데, **strict 변환("모든 property 를 required")이
    # 필수 출력으로 바꿔 놓았다.** run 04 의 layers.not_canonical 3건이 그
    # 부작용이다.
    #
    # 그래서 property 자체를 뺀다. 사후 보정이 아니다 —
    #   · 모델이 낸 값을 덮어쓰는 것이 아니라 **만들지 않게** 한다
    #   · additionalProperties:false 라 모델이 넣으면 조용히 무시되지 않고 거부된다
    #   · 누락 시 dataclass default(LAYER_STACK)로 채워진다
    #   · `_c_layers` 는 그대로 살아 있어 fixture/직접 경로는 계속 검사한다
    props.pop("layers", None)
    schema["required"] = [k for k in schema["required"] if k != "layers"]

    # ── typography face: family × weight 를 **조합으로** 묶는다 ────────────
    #
    # family enum 3개 × weight enum 4개 = 12조합이 전부 legal 이었다. 실제로
    # 렌더 가능한 것은 `SUPPORTED_TYPE_FACES` 5조합뿐이고, run 02 에서 모델이
    # 그 틈으로 sans/bold · serif/medium 을 냈다. capabilities 에 5조합을
    # 적어 뒀는데도 그랬다 — strict 를 켠 뒤로는 schema 가 더 강한 계약이라
    # 둘이 어긋나면 모델은 schema 를 따른다.
    #
    # 새 조합을 여는 게 아니라 이미 못 그리던 7조합을 닫는다.
    roles = props["typography"]["properties"]["roles"]
    item = roles["items"]
    props["typography"] = {
        **props["typography"],
        "properties": {
            **props["typography"]["properties"],
            "roles": {
                **roles,
                "items": {
                    # 5개 가지 각각이 family·weight 를 한 값으로 못 박는다.
                    # anyOf 는 strict 지원 대상이라 이 표현을 쓸 수 있다
                    "anyOf": [
                        {**item,
                         "properties": {**item["properties"],
                                        "family": {"type": "string", "enum": [fam]},
                                        "weight": {"type": "string", "enum": [wgt]}},
                         "description": f"{fam}/{wgt}"}
                        for fam, wgt in SUPPORTED_TYPE_FACES
                    ],
                    "description": "family×weight 는 실제로 렌더 가능한 조합만: "
                                   + " · ".join(f"{f}/{w}" for f, w in SUPPORTED_TYPE_FACES),
                },
            },
        },
    }

    # palette source/strategy 의 `fixed` 는 Planner 경로에서 뺀다.
    #
    #   fixed   `palette.fixed_values` 에 **Planner 가 직접 HEX 를 적는** 경로다.
    #           그런데 Planner 계약 1번이 "임의 HEX 를 쓰지 않는다" 이고,
    #           브랜드 색이 필요하면 `source="brand"` 가 brief.brand_palette 에서
    #           읽어 온다 — Planner 가 색을 만들 이유가 없다.
    #           게다가 fixed_values 는 동적 key 라 strict 로 옮길 수 없다.
    #
    # generic schema 에서는 그대로 둔다. 여기서만 좁힌다.
    pal = props["palette"]["properties"]
    props["palette"] = {
        **props["palette"],
        "properties": {
            **pal,
            "source": {"type": "string",
                       "enum": [v for v in pal["source"]["enum"] if v != "fixed"],
                       "description": "어디서 색을 가져올지 고른다. Planner 가 "
                                      "색 값 자체를 만들지는 않는다. "
                                      "brand 는 brief.brand_palette 를, "
                                      "preferred 는 brief.preferred_color 를 읽는다 — "
                                      "고른 쪽 입력이 없으면 거부된다"},
            "strategy": {"type": "string",
                         "enum": [v for v in pal["strategy"]["enum"] if v != "fixed"]},
            "fixed_values": {"type": "null",
                             "description": "Planner 경로에서는 항상 null"},
        },
    }
    _annotate_cross_field(props)
    return schema


# ── cross-field 관계 투영 ─────────────────────────────────────────────────
#
# strict JSON Schema 로는 조건부 관계를 **표현할 수 없다** — `if/then/else` 도
# `dependentRequired` 도 Structured Outputs 미지원이다. 그래서 Validator 가
# 이미 강제하는 규칙을 `description` 으로 옮겨 적는다.
#
# ★ 새 규칙을 만들지 않는다. 아래는 전부 `dynamic/validate.py` 에 이미 있는
#   검사를 문장으로 옮긴 것이고, 괄호 안이 실제 오류 코드다. run 02 에서
#   이 관계들을 모르는 채로 후보가 만들어졌다 (B 분류 10건).
# CROSS_FIELD_RULES 의 단일 출처는 `validate.py` 다 — 규칙을 강제하는
# 모듈이 소유한다. 여기서는 schema description 으로 투영만 한다.


def _append_desc(node: dict, text: str) -> None:
    old = node.get("description", "")
    node["description"] = f"{old} {text}".strip() if old else text


def _annotate_cross_field(props: dict) -> None:
    """Validator 의 cross-field 규칙을 schema description 으로 옮긴다."""
    lookup = dict(CROSS_FIELD_RULES)

    _append_desc(props["background"]["properties"]["visual_style"],
                 lookup["background.visual_style"])
    _append_desc(props["palette"]["properties"]["roles"], lookup["palette.roles"])
    _append_desc(props["palette"]["properties"]["rhythm"], lookup["palette.rhythm"])
    _append_desc(props["motif"]["properties"]["min_repeats"],
                 lookup["motif.min_repeats"])
    _append_desc(props["motif"]["properties"]["shape"], lookup["motif.shape"])
    _append_desc(props["safety"]["properties"]["critical_blocks"],
                 lookup["safety.critical_blocks"])
    _append_desc(props["safety"]["properties"]["must_be_visible"],
                 lookup["safety.must_be_visible"])

    # 참조 무결성 — 이름을 쓰는 자리마다 붙인다
    _append_desc(props["copy_blocks"]["items"]["properties"]["type_role"],
                 lookup["copy_blocks[].type_role"])
    _append_desc(props["copy_blocks"]["items"]["properties"]["id"],
                 lookup["copy_blocks[].id · motif role"])
    _mi = props["motif"]["properties"]["instances"]["items"]["properties"]
    _append_desc(_mi["role"], lookup["motif.instances[].role"])
    _append_desc(_mi["role"], lookup["copy_blocks[].id · motif role"])
    _pat = props["motif"]["properties"]["pattern"]
    for _branch in _pat.get("anyOf", [_pat]):
        _p = _branch.get("properties")
        if isinstance(_p, dict) and "role" in _p:
            _append_desc(_p["role"], lookup["motif.instances[].role"])
            _append_desc(_p["role"], lookup["copy_blocks[].id · motif role"])

    # col_start / col_span / color_role 은 여러 자리에 있다 — 한 곳만 적으면
    # 나머지는 모른 채로 남는다. zones 와 grid_ref 가 **같은 의미**를 봐야 한다
    span_rule = lookup["*.grid_ref.col_span"]
    base_rule = lookup["*.col_start (정수)"]
    closure_rule = lookup["*.color_role (참조 폐포)"]

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            p = node.get("properties")
            if isinstance(p, dict):
                if "col_start" in p:
                    _append_desc(p["col_start"], base_rule)
                    if "col_span" in p:
                        _append_desc(p["col_span"], span_rule)
                if "color_role" in p:
                    _append_desc(p["color_role"], closure_rule)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(props)


def planner_output_schema(candidate_count: int,
                          allowed_ratios: Sequence[str] = ("1:1",)) -> dict:
    """LLM 이 돌려줄 전체 구조. 후보 배열이 최상위다."""
    return {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "minItems": candidate_count,
                "maxItems": candidate_count,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "label": {"type": "string"},
                        "rationale": {"type": "string"},
                        "render_spec": planner_render_spec_schema(allowed_ratios),
                    },
                    "required": ["id", "label", "rationale", "render_spec"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["candidates"],
        "additionalProperties": False,
    }


# ──────────────────────────────────────────────────────────────────────────
# strict projection — Structured Outputs 가 실제로 강제할 수 있는 형태
# ──────────────────────────────────────────────────────────────────────────
#
#   generic RenderSpec schema
#           ↓  planner_render_spec_schema()   지금 실행 가능한 것만
#   Planner executable subset
#           ↓  to_strict()                    구조를 API 가 강제하게
#   strict API schema
#
# 첫 live run 에서 세 후보 모두 required 인 `copy_blocks` 를 빠뜨렸다.
# `strict:false` 는 스키마를 힌트로만 쓴다 — 구조 정확성을 모델의 주의력에
# 맡기지 않고 계약으로 옮긴다.
#
# strict 규칙 (공식 SDK 의 `_ensure_strict_json_schema` 와 같은 변환)
#   ① object 의 **모든** property 를 `required` 에
#   ② object 마다 `additionalProperties: false`
#   ③ "없어도 되는" 의미는 `T | null`
#
# ★ default 를 지어내지 않는다. 판단 기준은 **현재 스키마가 이미 null 을
#   허용하던 필드인가** 하나다. `_json_object()` 는 default 가 None 인
#   optional 에만 null 가지를 붙이므로, null 가지의 유무가 곧
#   "생략 = None" 인지 "생략 = 다른 default" 인지를 가른다.
#
#     null 가지 있음  → required + nullable.  생략과 같은 의미가 유지된다
#     null 가지 없음  → required + non-nullable.  모델이 값을 **명시**한다
#                       (생략 시 쓰이던 default 를 직접 적는 것뿐이라
#                        RenderSpec 의미는 그대로다 — 픽셀로 확인했다)

#: 공식 문서상 지원되지 않는 composition. 우리 스키마가 만들지 않는지 확인한다
STRICT_UNSUPPORTED: Tuple[str, ...] = (
    "allOf", "not", "dependentRequired", "dependentSchemas", "if", "then", "else",
    "oneOf", "patternProperties", "propertyNames", "unevaluatedProperties",
)


def _to_strict(node: Any) -> Any:
    if isinstance(node, list):
        return [_to_strict(v) for v in node]
    if not isinstance(node, dict):
        return node

    out = dict(node)
    props = out.get("properties")
    if isinstance(props, dict):
        out["additionalProperties"] = False
        out["required"] = list(props.keys())          # ① 전부 required
        out["properties"] = {k: _to_strict(v) for k, v in props.items()}
    if isinstance(out.get("items"), dict):
        out["items"] = _to_strict(out["items"])
    if isinstance(out.get("anyOf"), list):
        out["anyOf"] = [_to_strict(v) for v in out["anyOf"]]
    return out


def strict_violations(schema: Any, path: str = "$") -> Tuple[dict, ...]:
    """strict 로 보낼 수 없는 자리를 찾는다 — **고치지 않고 보고한다.**"""
    found: list = []
    if isinstance(schema, dict):
        for kw in STRICT_UNSUPPORTED:
            if kw in schema:
                found.append({"path": path, "keyword": kw,
                              "reason": "공식 문서상 Structured Outputs 미지원"})
        if schema.get("type") == "object" and "properties" not in schema:
            found.append({"path": path, "keyword": "additionalProperties",
                          "reason": "property 선언이 없는 object — 동적 key 구조라 "
                                    "strict 에서는 {} 밖에 담을 수 없다"})
        if schema.get("type") == "object" and schema.get("additionalProperties") is not False:
            found.append({"path": path, "keyword": "additionalProperties",
                          "reason": "false 여야 한다"})
        props = schema.get("properties")
        if isinstance(props, dict):
            missing = [k for k in props if k not in schema.get("required", [])]
            if missing:
                found.append({"path": path, "keyword": "required",
                              "reason": f"required 에 빠진 property: {missing}"})
            for k, v in props.items():
                found += list(strict_violations(v, f"{path}.{k}"))
        if isinstance(schema.get("items"), dict):
            found += list(strict_violations(schema["items"], path + "[]"))
        if isinstance(schema.get("anyOf"), list):
            for i, v in enumerate(schema["anyOf"]):
                found += list(strict_violations(v, f"{path}|{i}"))
    return tuple(found)


# ── 전역 규모 한도 ────────────────────────────────────────────────────────
#
# keyword 지원 여부와 **별개로** Structured Outputs 에는 스키마 전체 크기 한도가
# 있다. 여기 걸리면 호출 자체가 에러라 — 돈을 쓰고 나서 알게 된다. 그래서
# 호출 전에 계산한다.
#
# 값의 출처는 OpenAI 공식 Structured Outputs 문서다. 문서가 바뀌면 여기만
# 고치면 된다 — 검사 로직은 그대로다.
STRICT_LIMITS: Mapping[str, int] = MappingProxyType({
    "properties": 5000,        # object property 총 개수
    "depth": 10,               # 최대 중첩 깊이
    "string_length": 120_000,  # property 이름 · enum 값 등 문자열 총 길이
    "enum_values": 1000,       # enum 값 총 개수
})


def measure_schema(schema: Any) -> dict:
    """스키마의 전역 규모를 잰다 — API 없이.

    depth 는 **anyOf 가지도 한 단계로 세는** 보수적 기준이다. 공식 정의가
    그렇지 않다면 우리 수치가 실제보다 크게 나올 뿐이라 안전한 쪽으로 틀린다.
    """
    acc = {"properties": 0, "enum_values": 0, "string_length": 0,
           "depth": 0, "enum_nodes": 0, "objects": 0}

    def walk(n: Any, d: int) -> None:
        acc["depth"] = max(acc["depth"], d)
        if isinstance(n, dict):
            props = n.get("properties")
            if isinstance(props, dict):
                acc["objects"] += 1
                acc["properties"] += len(props)
                for k, v in props.items():
                    acc["string_length"] += len(k)
                    walk(v, d + 1)
            if isinstance(n.get("enum"), list):
                acc["enum_nodes"] += 1
                acc["enum_values"] += len(n["enum"])
                acc["string_length"] += sum(len(str(x)) for x in n["enum"])
            if isinstance(n.get("items"), dict):
                walk(n["items"], d + 1)
            if isinstance(n.get("anyOf"), list):
                for v in n["anyOf"]:
                    walk(v, d + 1)

    walk(schema, 0)
    acc["serialized_bytes"] = len(json.dumps(schema, ensure_ascii=False))
    return acc


def limit_violations(schema: Any) -> Tuple[dict, ...]:
    """전역 한도 초과를 찾는다. 통과하면 빈 튜플."""
    m = measure_schema(schema)
    out = []
    for key, cap in STRICT_LIMITS.items():
        got = m[key]
        if got > cap:
            out.append({"limit": key, "measured": got, "cap": cap,
                        "reason": "Structured Outputs 전역 한도 초과"})
    return tuple(out)


def strict_preflight(candidate_count: int,
                     allowed_ratios: Sequence[str] = ("1:1",)) -> dict:
    """두 번째 호출 직전에 도는 **전역 검사**. API 를 쓰지 않는다.

    `ok=False` 면 호출하지 않는다 — 실패를 API 에서 확인하지 않는다.
    """
    schema = strict_planner_output_schema(candidate_count, allowed_ratios)
    structural = strict_violations(schema)
    limits = limit_violations(schema)
    m = measure_schema(schema)
    checks = {
        "unsupported_keyword": not any(v.get("keyword") in STRICT_UNSUPPORTED
                                       for v in structural),
        "strict_structural": not structural,
        "property_limit": m["properties"] <= STRICT_LIMITS["properties"],
        "nesting_limit": m["depth"] <= STRICT_LIMITS["depth"],
        "string_size_limit": m["string_length"] <= STRICT_LIMITS["string_length"],
        "enum_count_limit": m["enum_values"] <= STRICT_LIMITS["enum_values"],
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "measured": m,
        "limits": dict(STRICT_LIMITS),
        "structural_violations": list(structural),
        "limit_violations": list(limits),
    }


def strict_planner_output_schema(candidate_count: int,
                                 allowed_ratios: Sequence[str] = ("1:1",)) -> dict:
    """`strict: true` 로 보낼 수 있는 Planner output schema.

    `pattern` · `minimum` / `maximum` · `minItems` / `maxItems` 는 그대로
    남긴다 — 일반 모델의 Structured Outputs 지원 대상이다. 이 제약을 버리면
    같은 규칙을 프롬프트 문장으로 다시 적어야 하고, 그건 계약이 아니다.
    """
    return _to_strict(planner_output_schema(candidate_count, allowed_ratios))


# ──────────────────────────────────────────────────────────────────────────
# 프롬프트
# ──────────────────────────────────────────────────────────────────────────
SYSTEM_ROLE = """\
너는 1:1 광고 포스터의 **아트 디렉터**다. 그림을 그리지 않고, 렌더러가 실행할
구조화된 디자인 결정(RenderSpec)을 만든다.

지켜야 할 것

1. **좌표를 만들지 않는다.** 픽셀 값, 정수 row index, 임의 HEX 를 쓰지 않는다.
   위치는 격자·영역·다른 요소와의 **관계**로만 표현한다.
   실제 px 은 Renderer 가 유도한다.

2. **`design_language` 는 템플릿 이름이 아니다.** prior 일 뿐이다.
   같은 `editorial` 안에서도 격자·제품 배치·타이포·모티프가 서로 달라야 한다.
   미리 정해진 레이아웃 몇 개 중에서 고르는 것이 아니다.

3. **후보들은 색만 달라서는 안 된다.** 아래 네 축에서 실질적으로 갈려야 한다.
   composition(격자·영역·겹침) · product treatment(크기·위치·회전·접지) ·
   hierarchy(블록 수·위계·타이포) · graphic language(모티프·배경).
   같은 레이아웃에 색이나 글자 크기만 바꾼 후보는 실패로 본다.

4. **사실을 바꾸지 않는다.** 제품명·카피 문구·사용자 요청·제품 색 신호는
   주어진 그대로 쓴다. 네가 정하는 것은 디자인 결정뿐이다.

5. 아래 capabilities 에 **없는 값을 쓰지 않는다.** 스키마 검증기가 거부하고,
   거부된 후보는 버려진다. 보정해 주지 않는다.
"""

DIVERSITY_NOTE = """\
후보 다양성은 네 자기평가가 아니라 코드가 판정한다. "서로 다양합니다"라고
써도 설계 축 차이가 부족하면 `insufficient_diversity` 다.
"""


def _brief_facts(pin: PlannerInput) -> dict:
    """LLM 에 넘길 **사실**. 디자인 결정은 하나도 들어 있지 않다."""
    b = pin.brief
    facts: dict = {
        "business_type": b.business_type,
        "category": b.category,
        "tone": b.tone,
        "keywords": list(b.keywords),
        "request": b.request,
        "output_ratio": b.output_ratio,
        "visual_style": b.visual_style,
    }

    ident = getattr(b, "product_identity", None)
    if ident is not None:
        # ★ for_design() 만 쓴다 — confirmation_source(provenance)는 넣지 않는다
        facts["product"] = ident.for_design()

    copy = b.copy
    facts["copy"] = {
        slot: getattr(copy, slot).content
        for slot in ("eyebrow", "headline", "benefit", "token", "cta")
        if getattr(copy, slot, None) and getattr(copy, slot).content
    }
    facts["copy_extra"] = {x.id: x.content for x in copy.extra if x.content}
    facts["content_refs"] = (
        [f"brief.copy.{k}" for k in facts["copy"]]
        + [f"brief.copy.extra.{k}" for k in facts["copy_extra"]]
    )
    facts["product_signals"] = dict(b.product_signals or {})

    # ★ 사용자 선호색 — **soft hint 다.** 최종 RGB 를 강제하지 않는다.
    facts["preferred_color"] = getattr(b, "preferred_color", None)

    # ★ background — 확인된 6개 필드만, 그리고 usable 일 때만 싣는다
    facts["background_context_status"] = pin.background_context_status
    if pin.background_ready():
        # `palette` 는 **자연어 서술 그대로** 간다. HEX 로 바꾸지 않는다 —
        # 이 값은 색 계산 입력이 아니라 Planner 가 읽는 참고 prior 다.
        facts["background_hints"] = b.background_context.design_hints()
    else:
        facts["background_hints"] = None
        facts["background_note"] = _BACKGROUND_NOTES[pin.background_context_status]
    return facts


#: 배경 참고 정보를 싣지 못한 이유. **상태별로 다른 말을 한다** — 뭉뚱그리면
#: 모델이 "정보가 없다" 와 "쓰면 안 된다" 를 구분하지 못한다.
_BACKGROUND_NOTES: Mapping[str, str] = MappingProxyType({
    "absent": (
        "배경 참고 이미지가 없다. tone·keywords·request·product_signals 로 "
        "background 를 설계하라. 없는 정보를 추측하지 마라."
    ),
    "unusable": (
        "배경 참고 이미지는 있으나 분석 결과를 쓸 수 없다고 표시됐다 "
        "(usable=false). 일부만 골라 쓰지 말고, 참고 없이 설계하라. "
        "어떤 이미지였을지 추측하지 마라."
    ),
    "empty": (
        "배경 분석 결과에 쓸 수 있는 값이 하나도 없다. "
        "tone·keywords·request·product_signals 로 background 를 설계하라. "
        "없는 정보를 추측하지 마라."
    ),
})


def _feedback_block(pin: PlannerInput) -> Optional[dict]:
    if not pin.feedback:
        return None
    # ★ v1.4 — `detail` 을 함께 싣는다.
    #
    # 숫자만으로는 무엇을 잰 것인지 알 수 없다. `measured=182756 / threshold=0`
    # 은 "무엇의 교집합인가" 를 말해 주지 않고, `2.59 / 3.0` 은 "어떤 바탕과의
    # 대비를 어떻게 쟀는가" 를 말해 주지 않는다.
    #
    # `Violation.detail` 은 계약상 **observation-only** 다 — 관측 사실과 측정
    # 방식만 담고 처방을 담지 않는다 (safety.DETAIL_CONTRACT). 그래서 실어도
    # "Safety 는 처방하지 않는다" 는 원칙이 깨지지 않는다.
    return {
        "note": ("이전 후보가 안전 기준에 걸렸다. 실패 사실만 주어진다 — "
                 "무엇을 어떻게 고칠지(색 역할·배치·layer·배경 톤 등)는 네가 정한다."),
        "failures": [
            {"candidate": fb.candidate_id, **{k: v[k] for k in
             ("code", "element_id", "element_kind", "severity",
              "measured", "threshold", "layer", "relation", "detail")}}
            for fb in pin.feedback for v in fb.violations
        ],
    }


#: capabilities 표에는 있지만 **프롬프트에는 싣지 않는** 진단용 필드.
#: `declared_ratios` 는 "스키마가 이름은 알지만 Renderer 가 처리하지 못하는" 값이라
#: 그대로 실으면 `이 값들만 쓴다` 라는 문장과 정면으로 충돌한다. capabilities 의
#: 단일 출처(`describe_capabilities()`)는 건드리지 않고, 프롬프트 투영에서만 뺀다.
PROMPT_EXCLUDED_CAPABILITIES: Tuple[str, ...] = ("declared_ratios",)


def build_system_prompt(pin: PlannerInput) -> str:
    caps = {k: v for k, v in (pin.capabilities or describe_capabilities()).items()
            if k not in PROMPT_EXCLUDED_CAPABILITIES}
    parts = [
        SYSTEM_ROLE,
        "\n## capabilities — 이 값들만 쓴다\n",
        json.dumps(caps, ensure_ascii=False, indent=2),
        "\n\n## 다양성\n",
        DIVERSITY_NOTE,
    ]
    return "".join(parts)


def build_user_prompt(pin: PlannerInput) -> str:
    payload: dict = {
        "candidate_count": pin.candidate_count,
        "brief": _brief_facts(pin),
    }
    fb = _feedback_block(pin)
    if fb:
        payload["safety_feedback"] = fb
    if pin.notes:
        payload["notes"] = pin.notes

    ask = (
        f"서로 구조적으로 다른 RenderSpec 후보를 **{pin.candidate_count}개** 만들어라.\n"
        "각 후보에 id · label · rationale · render_spec 을 담는다.\n"
        "rationale 은 한두 문장의 디자인 의도면 충분하다 (렌더러는 읽지 않는다).\n"
    )
    if fb:
        ask += "이전 후보의 실패 이유를 고려해 **새로** 설계하라.\n"
    return ask + "\n입력:\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def prompt_metadata(pin: PlannerInput) -> dict:
    caps = dict(pin.capabilities or {})
    return {
        "prompt_version": PROMPT_VERSION,
        "schema_version": caps.get("schema_version"),
        "candidate_count": pin.candidate_count,
        "is_redesign": pin.is_redesign,
        "background_context_status": pin.background_context_status,
    }


__all__ = [
    "PROMPT_VERSION",
    "PLANNER_PROJECTIONS",
    "CROSS_FIELD_RULES",
    "PROMPT_EXCLUDED_CAPABILITIES",
    "render_spec_json_schema",
    "planner_render_spec_schema",
    "strict_planner_output_schema",
    "strict_violations",
    "strict_preflight",
    "measure_schema",
    "limit_violations",
    "STRICT_LIMITS",
    "STRICT_UNSUPPORTED",
    "planner_output_schema",
    "build_system_prompt",
    "build_user_prompt",
    "prompt_metadata",
]

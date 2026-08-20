"""RenderSpec 검증 테스트 — E12 v0.3 Step 1.

핵심 원칙 — **잘못된 Spec 을 조용히 보정하지 않는다.** 각 테스트는
"이 Spec 은 거부되어야 한다 + 이 code 로 거부되어야 한다"를 단정한다.
에러 메시지 문구에는 의존하지 않는다.

production `pipeline/` 을 import 하지 않는다 — core_1x1 경로와 분리 확인도
이 파일의 목적 중 하나다.

실행:  python tests/test_renderspec_schema.py
"""

from __future__ import annotations

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dynamic import (  # noqa: E402
    LAYER_STACK,
    SCHEMA_VERSION,
    AnchorUnresolvable,
    BriefCopy,
    ContentRefUnresolved,
    CoordinateMixing,
    CopyExtra,
    CopyItem,
    CreativeBrief,
    CriticalEmpty,
    LayerUnassigned,
    RatioUnsupported,
    SchemaError,
    SpecInvalid,
    SpecRejected,
    TrustBoundaryViolation,
    ValidationContext,
    load,
    validate,
)

FAILS: list[str] = []
CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILS.append(label)


def section(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 62 - len(title)))


# ──────────────────────────────────────────────────────────────────────────
# 기준 Spec — 통과해야 하는 정상 Spec
# ──────────────────────────────────────────────────────────────────────────
def valid_spec() -> dict:
    """AD-C editorial 계열을 v0.3 문법으로 기술한 정상 Spec."""
    return {
        "schema_version": SCHEMA_VERSION,
        "canvas": {"ratio": "1:1"},
        "design_language": "editorial",
        "grid": {
            "columns": 6,
            "margin_density": "normal",
            "gutter_scale": "normal",
            "baseline_scale": "normal",
        },
        "zones": {
            "type": {"col_start": 0, "col_span": 4},
            "product": {"col_start": 2, "col_span": 4},
            "overlap_intent": "allowed",
        },
        "product": {
            "fit": "zone_width",
            "anchor": {"x": "right", "y": "bottom"},
            "bleed": ["bottom"],
            "rotation": "none",
            "grounding": "contact",
        },
        "background": {
            "mode": "flat",
            "material": "paper",
            "lighting": "flat",
            "texture": "paper_grain",
            "whitespace_strategy": "balanced",
        },
        "typography": {
            "measure_cols": 4,
            "break_strategy": "semantic",
            "scale_step": 1.0,
            "roles": [
                {
                    "id": "eyebrow",
                    "family": "sans",
                    "weight": "medium",
                    "size_step": -2,
                    "line_ratio": 1.4,
                    "tracking_em": 0.16,
                    "transform": "uppercase",
                    "align": "left",
                    "max_lines": 1,
                    "color_role": "spot",
                    "space_after": "tight",
                },
                {
                    "id": "headline",
                    "family": "display",
                    "weight": "bold",
                    "size_step": 3,
                    "line_ratio": 0.95,
                    "tracking_em": -0.02,
                    "align": "left",
                    "max_lines": 3,
                    "color_role": "ink",
                    "space_after": "normal",
                },
                {
                    "id": "token",
                    "family": "display",
                    "weight": "black",
                    "size_step": 5,
                    "line_ratio": 1.0,
                    "align": "right",
                    "max_lines": 1,
                    "color_role": "spot",
                    "space_after": "none",
                },
            ],
        },
        "palette": {
            "strategy": "neutral_support",
            "source": "product",
            "background_tone": "light",
            "roles": ["bg", "ink", "spot", "emphasis"],
            "rhythm": {"spot_min_regions": 3, "spot_path": "diagonal"},
        },
        "motif": {
            "shape": "rule",
            "min_repeats": 3,
            "instances": [
                {
                    "role": "eyebrow_marker",
                    "grid_ref": {
                        "col_start": 0,
                        "col_span": 1,
                        "row_anchor": "top",
                        "align": "left",
                    },
                    "orientation": "horizontal",
                    "weight": "thick",
                    "color_role": "spot",
                    "layer": "motif_under",
                },
                {
                    "role": "bottom_rule",
                    "grid_ref": {
                        "col_start": 0,
                        "col_span": 6,
                        "row_anchor": "before:discount_token",
                        "align": "left",
                    },
                    "orientation": "horizontal",
                    "weight": "hair",
                    "color_role": "ink→spot",
                    "split_at": {"col": 2},
                    "layer": "motif_over",
                },
                {
                    "role": "spine_bar",
                    "grid_ref": {"col_start": "margin_left", "row_anchor": "center",
                                 "row_span": 30},
                    "orientation": "vertical",
                    "weight": "thick",
                    "color_role": "spot",
                    "layer": "motif_under",
                },
            ],
        },
        "copy_blocks": [
            {
                "id": "eyebrow",
                "role": "eyebrow",
                "content_ref": "brief.copy.eyebrow",
                "type_role": "eyebrow",
                "grid_ref": {
                    "col_start": 0,
                    "col_span": 4,
                    "row_anchor": "top",
                    "align": "left",
                },
                "priority": 3,
                "color_role": "spot",
                "layer": "type_under",
            },
            {
                "id": "headline",
                "role": "headline",
                "content_ref": "brief.copy.headline",
                "type_role": "headline",
                "grid_ref": {
                    "col_start": 0,
                    "col_span": 4,
                    "row_anchor": "after:eyebrow",
                    "align": "left",
                },
                "priority": 1,
                "color_role": "ink",
                "layer": "type_under",
            },
            {
                "id": "side_caption",
                "role": "caption",
                "content_ref": "brief.copy.extra.side_note",
                "type_role": "eyebrow",
                "grid_ref": {"col_start": "margin_left", "row_anchor": "center"},
                "orientation": "rotate_ccw",
                "priority": 4,
                "color_role": "spot",
                "layer": "type_over",
            },
            {
                "id": "discount_token",
                "role": "token",
                "content_ref": "brief.copy.token",
                "type_role": "token",
                "grid_ref": {
                    "col_start": 0,
                    "col_span": 6,
                    "row_anchor": "bottom",
                    "align": "right",
                },
                "priority": 1,
                "color_role": "spot",
                "layer": "type_over",
            },
        ],
        "layers": list(LAYER_STACK),
        "safety": {
            "critical_blocks": ["headline", "discount_token"],
            "must_be_visible": ["bottom_rule"],
        },
    }


def valid_brief() -> CreativeBrief:
    return CreativeBrief(
        business_type="retail",
        category="cosmetics",
        tone="minimal_product",
        output_ratio="1:1",
        copy=BriefCopy(
            eyebrow=CopyItem("스킨케어", source="derived", editable=False),
            headline=CopyItem("촉촉함을 오래", source="user"),
            benefit=CopyItem("12시간 수분 지속", source="generated"),
            token=CopyItem("30%", source="user"),
            cta=CopyItem("지금 구매", source="generated"),
            extra=(CopyExtra("side_note", "NEW ARRIVAL"),),
        ),
        category_label="스킨케어",
        product_signals={
            "palette": {
                "dominant": "#D8CFC4",   # 마스크 내부 지배색 (무채에 가까움)
                "accent": "#2E6F5E",     # 가장 채도 높은 클러스터
                "neutral": "#EFEAE3",
            }
        },
    )


def mutate(fn) -> dict:
    raw = valid_spec()
    fn(raw)
    return raw


def expect_codes(raw, expected_codes, label, *, brief=None, context=None) -> None:
    """지정한 code 가 실제로 나오는지 확인한다."""
    errors = validate(raw, brief if brief is not None else valid_brief(), context)
    codes = [e.code for e in errors]
    ok = all(c in codes for c in expected_codes) and bool(errors)
    check(ok, f"{label}: 기대 {expected_codes} / 실제 {codes}")
    print(f"  {'PASS' if ok else 'FAIL'}  {label:46} → {codes}")


def expect_type(raw, err_type, label, *, brief=None, context=None) -> None:
    errors = validate(raw, brief if brief is not None else valid_brief(), context)
    ok = any(isinstance(e, err_type) for e in errors)
    check(ok, f"{label}: {err_type.__name__} 기대")
    kinds = [type(e).__name__ for e in errors]
    print(f"  {'PASS' if ok else 'FAIL'}  {label:46} → {kinds}")


# ──────────────────────────────────────────────────────────────────────────
def test_valid_spec_passes() -> None:
    section("정상 Spec 통과")

    raw = valid_spec()
    errors = validate(raw, valid_brief())
    check(not errors, f"정상 Spec 이 통과해야 한다: {[str(e) for e in errors]}")
    print(f"  {'PASS' if not errors else 'FAIL'}  planner 경로 정상 Spec → 에러 {len(errors)}건")
    for e in errors:
        print(f"        {e}")

    spec = load(raw, valid_brief())
    check(spec.grid.columns == 6, "grid.columns 파싱")
    check(spec.zones.type.col_span == 4, "zones 중첩 파싱")
    check(len(spec.copy_blocks) == 4, "copy_blocks 개수")
    check(spec.copy_blocks[2].orientation == "rotate_ccw", "orientation 파싱")
    check(spec.copy_blocks[2].grid_ref.col_start == "margin_left", "명명 영역 파싱")
    check(spec.motif.instances[1].split_at.col == 2, "split_at 파싱")
    check(spec.typography.roles[0].transform == "uppercase", "transform 파싱")
    check(spec.product.grounding == "contact", "grounding 파싱")
    check(isinstance(spec.copy_blocks, tuple), "copy_blocks 는 tuple (불변)")
    print(f"  PASS  자료구조 파싱 — columns={spec.grid.columns} "
          f"blocks={len(spec.copy_blocks)} motif={len(spec.motif.instances)}")

    # frozen 확인 — 검증 통과 후 변형되면 결정론이 깨진다
    frozen_ok = False
    try:
        spec.grid.columns = 8  # type: ignore[misc]
    except Exception:
        frozen_ok = True
    check(frozen_ok, "RenderSpec 은 frozen 이어야 한다")
    print(f"  {'PASS' if frozen_ok else 'FAIL'}  frozen — 통과한 Spec 은 변형 불가")

    test_nested_collections_immutable()

    # fixture 경로에서 정수 row index 가 허용된다
    fx = mutate(lambda r: r["copy_blocks"][3]["grid_ref"].update({"row_anchor": 54}))
    fx_errors = validate(fx, valid_brief(), ValidationContext(spec_source="fixture"))
    # bottom_rule 이 before:discount_token 을 참조하므로 여전히 유효하다
    check(not fx_errors, f"fixture 경로 정수 index 허용: {[str(e) for e in fx_errors]}")
    print(f"  {'PASS' if not fx_errors else 'FAIL'}  fixture 경로 정수 row index 허용 "
          f"→ 에러 {len(fx_errors)}건")

    # brief 없이도 스키마/교차 검증은 돌아간다 (content_ref 해석만 생략)
    no_brief = validate(valid_spec(), None)
    check(not no_brief, f"brief 없이도 통과: {[str(e) for e in no_brief]}")
    print(f"  {'PASS' if not no_brief else 'FAIL'}  brief 미지정 — content_ref 해석만 생략")


def test_nested_collections_immutable() -> None:
    """검증을 통과한 RenderSpec 은 **중첩 컨테이너까지** 변형되지 않아야 한다.

    frozen dataclass 는 필드 재할당만 막는다. 내부가 list / dict 면
    `spec.copy_blocks.append(...)` 가 통과해 버리고, 그 순간 결정론 계약(§9)의
    "동일 RenderSpec" 전제가 무너진다.
    """
    raw = valid_spec()
    raw["palette"]["strategy"] = "fixed"
    raw["palette"]["source"] = "fixed"
    raw["palette"]["fixed_values"] = {
        "bg": "#101820",
        "ink": "#F2EFE9",
        "spot": "#E8B44A",
        "emphasis": "#C0392B",
    }
    spec = load(raw, valid_brief())

    targets = [
        ("copy_blocks", lambda: spec.copy_blocks.append(None)),
        ("copy_blocks[0]=", lambda: spec.copy_blocks.__setitem__(0, None)),
        ("palette.roles", lambda: spec.palette.roles.append("neon")),
        ("product.bleed", lambda: spec.product.bleed.append("top")),
        ("motif.instances", lambda: spec.motif.instances.append(None)),
        ("layers", lambda: spec.layers.append("overlay")),
        ("safety.critical_blocks", lambda: spec.safety.critical_blocks.append("x")),
        ("palette.fixed_values", lambda: spec.palette.fixed_values.__setitem__("bg", "#000000")),
        ("fixed_values.pop", lambda: spec.palette.fixed_values.pop("bg")),
    ]
    for label, mutate_fn in targets:
        blocked = False
        try:
            mutate_fn()
        except Exception:
            blocked = True
        check(blocked, f"중첩 컨테이너 변형이 막혀야 한다: {label}")
        print(f"  {'PASS' if blocked else 'FAIL'}  중첩 불변 — {label} 변형 차단")

    # raw 를 고쳐도 이미 만들어진 Spec 이 바뀌지 않아야 한다 (복사본을 감쌌는가)
    raw["palette"]["fixed_values"]["bg"] = "#FFFFFF"
    isolated = spec.palette.fixed_values["bg"] == "#101820"
    check(isolated, "raw 변경이 Spec 에 새지 않아야 한다")
    print(f"  {'PASS' if isolated else 'FAIL'}  중첩 불변 — raw 수정이 Spec 에 전파되지 않음")


def test_trust_boundary() -> None:
    section("trust boundary — spec_source 는 Spec 이 선언할 수 없다")

    raw = mutate(lambda r: r.update({"spec_source": "fixture"}))
    expect_type(raw, TrustBoundaryViolation, "Planner 출력에 spec_source")
    expect_codes(raw, ["trust.spec_source_in_spec"], "spec_source code")

    # 우회 시도가 실제로 막히는지 — fixture 를 자칭하며 정수 index 를 넣는다
    bypass = mutate(
        lambda r: (
            r.update({"spec_source": "fixture"}),
            r["copy_blocks"][3]["grid_ref"].update({"row_anchor": 54}),
        )
    )
    errors = validate(bypass, valid_brief())
    ok = any(isinstance(e, TrustBoundaryViolation) for e in errors)
    check(ok, "fixture 자칭 우회가 막혀야 한다")
    print(f"  {'PASS' if ok else 'FAIL'}  fixture 자칭으로 정수 index 우회 시도 차단")

    # ValidationContext 는 잘못된 값을 받지 않는다
    bad_ctx = False
    try:
        ValidationContext(spec_source="whatever")
    except ValueError:
        bad_ctx = True
    check(bad_ctx, "ValidationContext 가 미지의 spec_source 를 거부")
    print(f"  {'PASS' if bad_ctx else 'FAIL'}  ValidationContext 미지의 spec_source 거부")


def test_required_cross_field_rules() -> None:
    section("사용자 지정 교차 필드 규칙 12개")

    # ① fit != area_cap 인데 area_cap 사용
    expect_codes(
        mutate(lambda r: r["product"].update({"fit": "zone_width", "area_cap": 0.42})),
        ["product.area_cap_unused"],
        "① fit≠area_cap 인데 area_cap 존재",
    )
    # ①-b 대칭 — fit=area_cap 인데 값 없음
    expect_codes(
        mutate(lambda r: r["product"].update({"fit": "area_cap"})),
        ["product.area_cap_missing"],
        "①b fit=area_cap 인데 값 없음",
    )

    # ② palette.source == fixed 인데 fixed_values 없음
    expect_codes(
        mutate(lambda r: r["palette"].update({"source": "fixed", "strategy": "fixed"})),
        ["palette.fixed_values_missing"],
        "② source=fixed 인데 fixed_values 없음",
    )

    # ③ palette.source != fixed 인데 fixed_values 존재
    expect_codes(
        mutate(lambda r: r["palette"].update({"fixed_values": {"bg": "#101820"}})),
        ["palette.fixed_values_unused"],
        "③ source≠fixed 인데 fixed_values 존재",
    )

    # ④ motif.shape == none 인데 pattern/instances 존재
    expect_codes(
        mutate(lambda r: r["motif"].update({"shape": "none"})),
        ["motif.shape_none_with_elements"],
        "④ shape=none 인데 instances 존재",
    )

    # ⑤ pattern.repeat < min_repeats
    def small_pattern(r):
        r["motif"]["instances"] = []
        r["motif"]["min_repeats"] = 5
        r["motif"]["pattern"] = {
            "role": "stripe_pattern",
            "repeat": 2,
            "spacing": {"unit": "baseline", "value": 1.5},
            "region": {"col_start": 0, "col_span": 6, "row_anchor": "top", "row_span": 6},
            "angle": "diagonal_up",
            "weight": "hair",
            "color_role": "spot",
            "layer": "motif_under",
        }
        r["safety"]["must_be_visible"] = []
        r["motif"]["instances"] = []

    expect_codes(
        mutate(small_pattern), ["motif.repeats_below_min"], "⑤ pattern.repeat < min_repeats"
    )

    # ⑥ zones.col_start + col_span > grid.columns
    expect_codes(
        mutate(lambda r: r["zones"]["product"].update({"col_start": 4, "col_span": 4})),
        ["zones.span_overflow"],
        "⑥ zone span 이 columns 초과",
    )

    # ⑦ copy_blocks[].type_role 이 존재하지 않는 typography role
    expect_codes(
        mutate(lambda r: r["copy_blocks"][1].update({"type_role": "nope"})),
        ["copy.type_role_unknown"],
        "⑦ 미지의 type_role 참조",
    )

    # ⑧ safety.critical_blocks 가 존재하지 않는 block id
    expect_codes(
        mutate(lambda r: r["safety"].update({"critical_blocks": ["ghost"]})),
        ["safety.critical_unknown"],
        "⑧ 미지의 critical block id",
    )

    # ⑨ safety.must_be_visible 가 존재하지 않는 motif role
    expect_codes(
        mutate(lambda r: r["safety"].update({"must_be_visible": ["ghost_rule"]})),
        ["safety.must_be_visible_unknown"],
        "⑨ 미지의 must_be_visible role",
    )

    # ⑩ color_role 이 palette.roles 에 없음
    expect_codes(
        mutate(lambda r: r["copy_blocks"][1].update({"color_role": "neon"})),
        ["palette.color_role_unknown"],
        "⑩ 미지의 color_role 참조",
    )
    expect_codes(
        mutate(lambda r: r["motif"]["instances"][1].update({"color_role": "ink→neon"})),
        ["palette.color_role_unknown"],
        "⑩b 색 전환 표기의 한쪽이 미지",
    )

    # ⑪ layer 가 고정 스택 밖 / 누락
    expect_type(
        mutate(lambda r: r["copy_blocks"][0].update({"layer": "type_middle"})),
        LayerUnassigned,
        "⑪ 스택 밖의 layer",
    )
    expect_codes(
        mutate(lambda r: r["copy_blocks"][0].pop("layer")),
        ["layer.missing"],
        "⑪b layer 누락 (기본값 없음)",
    )
    expect_codes(
        mutate(lambda r: r["motif"]["instances"][0].pop("layer")),
        ["layer.missing"],
        "⑪c motif instance layer 누락",
    )

    # ⑫ content_ref 가 CreativeBrief.copy 에서 해석 불가
    expect_type(
        mutate(lambda r: r["copy_blocks"][1].update({"content_ref": "brief.copy.tagline"})),
        ContentRefUnresolved,
        "⑫ 미지의 copy 슬롯 참조",
    )
    expect_type(
        mutate(lambda r: r["copy_blocks"][2].update({"content_ref": "brief.copy.extra.nope"})),
        ContentRefUnresolved,
        "⑫b 미지의 extra id 참조",
    )
    expect_codes(
        mutate(lambda r: r["copy_blocks"][1].update({"content_ref": "촉촉함을 오래"})),
        ["copy.content_ref_form"],
        "⑫c 원문을 직접 넣은 경우",
    )


def test_documented_errors() -> None:
    section("문서에 선언된 거부 에러")

    # RatioUnsupported — 지원하지 않는 비율을 조용히 해석하지 않는다
    expect_type(
        mutate(lambda r: r["canvas"].update({"ratio": "3:1"})),
        RatioUnsupported,
        "3:1 은 Renderer v1 capability 밖",
    )
    expect_codes(
        mutate(lambda r: r["canvas"].update({"ratio": "3:4"})),
        ["canvas.ratio_unsupported"],
        "3:4 도 명시적 거부",
    )
    # 확장 시나리오 — context 가 허용하면 통과해야 한다 (규칙이 하드코딩이 아님)
    future = validate(
        mutate(lambda r: r["canvas"].update({"ratio": "3:4"})),
        valid_brief(),
        ValidationContext(supported_ratios=("1:1", "3:4")),
    )
    check(not future, f"capability 확장 시 통과: {[str(e) for e in future]}")
    print(f"  {'PASS' if not future else 'FAIL'}  supported_ratios 확장 시 3:4 통과")

    # CriticalEmpty
    expect_type(
        mutate(lambda r: r["safety"].update({"critical_blocks": []})),
        CriticalEmpty,
        "critical_blocks 가 비었다 (H3)",
    )
    expect_type(mutate(lambda r: r.pop("safety")), CriticalEmpty, "safety 자체가 없다")

    # CoordinateMixing
    expect_type(
        mutate(lambda r: r["copy_blocks"][2]["grid_ref"].update({"col_span": 2})),
        CoordinateMixing,
        "명명 영역 + col_span 혼용 (§8-4)",
    )

    # planner 경로의 정수 row index
    expect_codes(
        mutate(lambda r: r["copy_blocks"][3]["grid_ref"].update({"row_anchor": 54})),
        ["row_anchor.index_in_planner_path"],
        "planner 경로 정수 row index",
    )

    # AnchorUnresolvable — 미지 / 전방 참조 / 자기 참조 / 순환
    expect_codes(
        mutate(lambda r: r["copy_blocks"][1]["grid_ref"].update({"row_anchor": "after:footer"})),
        ["anchor.unknown_target"],
        "존재하지 않는 블록 참조 (before:footer 사례)",
    )
    expect_codes(
        mutate(
            lambda r: r["copy_blocks"][0]["grid_ref"].update(
                {"row_anchor": "after:discount_token"}
            )
        ),
        ["anchor.forward_reference"],
        "선언 순서상 뒤를 참조",
    )
    expect_codes(
        mutate(lambda r: r["copy_blocks"][1]["grid_ref"].update({"row_anchor": "after:headline"})),
        ["anchor.self_reference"],
        "자기 참조",
    )

    def make_cycle(r):
        r["copy_blocks"][0]["grid_ref"]["row_anchor"] = "after:headline"
        r["copy_blocks"][1]["grid_ref"]["row_anchor"] = "after:eyebrow"

    expect_type(mutate(make_cycle), AnchorUnresolvable, "상호 참조 (순환)")

    # layers 재배열 금지
    expect_codes(
        mutate(lambda r: r.update({"layers": list(reversed(LAYER_STACK))})),
        ["layers.not_canonical"],
        "stacking order 재배열",
    )


def test_schema_level() -> None:
    section("스키마 수준 — 타입 · enum · 범위 · 누락 · 미지의 필드")

    expect_codes(
        mutate(lambda r: r["grid"].update({"columns": 5})),
        ["schema.enum"],
        "columns 는 4|6|8|12 만",
    )
    expect_codes(
        mutate(lambda r: r["grid"].update({"columns": "6"})),
        ["schema.type"],
        "columns 문자열",
    )
    expect_codes(
        mutate(lambda r: r["typography"]["roles"][0].update({"line_ratio": 9.0})),
        ["schema.range"],
        "line_ratio 범위 초과",
    )
    expect_codes(
        mutate(lambda r: r["product"].update({"rotation": "spin"})),
        ["schema.enum"],
        "미지의 rotation 값",
    )
    expect_codes(
        mutate(lambda r: r.update({"unknown_axis": "x"})),
        ["schema.unknown_field"],
        "미지의 루트 필드",
    )
    expect_codes(
        mutate(lambda r: r["product"].update({"x": 120, "y": 340})),
        ["schema.unknown_field"],
        "px 좌표를 몰래 넣는 경우 (H1)",
    )
    expect_codes(mutate(lambda r: r.pop("grid")), ["schema.missing_field"], "grid 누락")
    expect_codes(
        mutate(lambda r: r["typography"].update({"roles": []})),
        ["schema.min_items"],
        "typography.roles 가 빔",
    )
    expect_codes(
        mutate(lambda r: r.update({"copy_blocks": []})),
        ["schema.min_items"],
        "copy_blocks 가 빔",
    )
    expect_codes(
        mutate(lambda r: r["product"].update({"bleed": ["diagonal"]})),
        ["schema.enum"],
        "미지의 bleed 방향",
    )
    expect_codes(
        mutate(lambda r: r.update({"schema_version": "0.2"})),
        ["schema.version_unsupported"],
        "지원하지 않는 schema_version",
    )
    expect_codes(
        mutate(lambda r: r.update({"design_language": "brutalist"})),
        ["schema.enum"],
        "미지의 design_language",
    )
    expect_codes(
        mutate(lambda r: r["motif"].update({"shape": "custom"})),
        ["schema.enum"],
        "shape=custom 은 없다 (§8-5)",
    )
    expect_codes(
        mutate(lambda r: r["motif"].update({"shape": "starburst"})),
        ["schema.enum"],
        "shape enum 은 검증된 것만",
    )
    # 블록 간 간격은 타이포그래피 설계의 일부다 — 숨은 Renderer 기본값이 아니다
    expect_codes(
        mutate(lambda r: r["typography"]["roles"][0].pop("space_after")),
        ["schema.missing_field"],
        "space_after 누락 (기본값 없음)",
    )
    expect_codes(
        mutate(lambda r: r["typography"]["roles"][0].update({"space_after": "huge"})),
        ["schema.enum"],
        "미지의 space_after 값",
    )
    # 번들 폰트로 정확히 표현되지 않는 조합은 대체하지 않고 거부한다
    expect_codes(
        mutate(lambda r: r["typography"]["roles"][1].update({"family": "serif", "weight": "regular"})),
        ["typography.unsupported_face"],
        "serif/regular — 얇은 명조 미번들",
    )
    expect_codes(
        mutate(lambda r: r["typography"]["roles"][1].update({"family": "sans", "weight": "bold"})),
        ["typography.unsupported_face"],
        "sans/bold — Pretendard Bold 미번들",
    )


def test_additional_consistency() -> None:
    section("추가 정합성 규칙")

    # ★ v0.3 — overlap_intent 는 **열 교집합으로 검증하지 않는다** (§4-7).
    #   zone 이 열에서 겹쳐도 none 이 유효하고, 안 겹쳐도 shared 가 유효하다.
    #   실제 2D 판정은 RenderPlan 을 보는 Step 6 몫이다
    for label, mut in (
        ("열은 겹치는데 intent=none", lambda r: r["zones"].update({"overlap_intent": "none"})),
        ("열은 안 겹치는데 intent=shared",
         lambda r: r["zones"].update({"product": {"col_start": 4, "col_span": 2},
                                      "overlap_intent": "allowed"})),
    ):
        errs = validate(mutate(mut), valid_brief())
        codes = [e.code for e in errs]
        ok = not any(c.startswith("zones.overlap") for c in codes)
        check(ok, f"{label}: {codes}")
        print(f"  {'PASS' if ok else 'FAIL'}  {label:34} → 열 교집합으로 막지 않는다 {codes}")
    expect_codes(
        mutate(lambda r: r["background"].update({"mode": "generated"})),
        ["background.visual_style_missing"],
        "generated 인데 visual_style 없음",
    )
    expect_codes(
        mutate(lambda r: r["background"].update({"visual_style": "3d"})),
        ["background.visual_style_unused"],
        "flat 인데 visual_style 존재",
    )
    expect_codes(
        mutate(lambda r: r["palette"].update({"roles": ["spot", "emphasis"]})),
        ["palette.missing_base_roles"],
        "palette 필수 역할(bg/ink) 누락",
    )
    expect_codes(
        mutate(lambda r: r["palette"]["rhythm"].update({"spot_path": "none"})),
        ["palette.spot_rhythm_conflict"],
        "spot_path=none 인데 min_regions>1",
    )
    expect_codes(
        mutate(lambda r: r["typography"].update({"measure_cols": 8})),
        ["typography.measure_cols_overflow"],
        "measure_cols > columns",
    )
    expect_codes(
        mutate(lambda r: r["copy_blocks"][1].update({"id": "eyebrow"})),
        ["copy.duplicate_id"],
        "copy block id 중복",
    )
    expect_codes(
        mutate(lambda r: r["typography"]["roles"][1].update({"id": "eyebrow"})),
        ["typography.duplicate_role_id"],
        "typography role id 중복",
    )
    expect_codes(
        mutate(lambda r: r["motif"]["instances"][1].update({"role": "eyebrow_marker"})),
        ["motif.duplicate_role"],
        "motif role 중복",
    )
    expect_codes(
        mutate(lambda r: r["motif"]["instances"][0].update({"role": "headline"})),
        ["anchor.namespace_collision"],
        "copy id 와 motif role 충돌",
    )
    expect_codes(
        mutate(lambda r: r["copy_blocks"][0]["grid_ref"].update({"col_start": 7})),
        ["grid_ref.col_out_of_range"],
        "grid_ref 열 번호 범위 초과",
    )
    expect_codes(
        mutate(lambda r: r["copy_blocks"][0]["grid_ref"].update({"col_span": 8})),
        ["grid_ref.span_overflow"],
        "grid_ref span 이 columns 초과",
    )
    expect_codes(
        mutate(lambda r: r["copy_blocks"][0]["grid_ref"].pop("col_span")),
        ["grid_ref.span_missing"],
        "열 번호인데 col_span 없음",
    )
    expect_codes(
        # bottom_rule 은 col 0~6 을 덮는다.  7 은 그 밖이다
        mutate(lambda r: r["motif"]["instances"][1]["split_at"].update({"col": 7})),
        ["motif.split_at_out_of_span"],
        "split_at 이 instance 범위 밖",
    )
    def named_region_split(r):
        # 가로 rule 을 명명 영역에 올리고 열 기준 분할점을 준다 — 두 좌표계 혼용
        r["motif"]["instances"][0]["grid_ref"] = {
            "col_start": "margin_left",
            "row_anchor": "top",
        }
        r["motif"]["instances"][0]["split_at"] = {"col": 1}

    expect_codes(
        mutate(named_region_split),
        ["motif.split_at_on_named_region"],
        "명명 영역 위의 split_at",
    )
    expect_codes(
        mutate(lambda r: r["motif"]["instances"][2].update({"split_at": {"col": 1}})),
        ["motif.split_at_on_vertical"],
        "세로 요소 위의 split_at",
    )
    expect_codes(
        mutate(lambda r: r["motif"]["instances"][0].pop("orientation")),
        ["schema.missing_field"],
        "motif orientation 누락 (기본값 없음)",
    )
    expect_codes(
        mutate(lambda r: r["copy_blocks"][0]["grid_ref"].update({"row_anchor": "middle"})),
        ["row_anchor.unknown_form"],
        "미지의 row_anchor 형태",
    )
    expect_codes(
        mutate(lambda r: r["product"].update({"bleed": ["bottom", "bottom"]})),
        ["product.bleed_duplicate"],
        "bleed 중복 선언",
    )


def test_conditional_heuristics_can_be_off() -> None:
    section("Conditional heuristic 은 꺼도 실패가 아니다 (§2-2)")

    def premium_minimal(r):
        # C2 모티프 없음 · C3 spot 순환 없음 · C4 접지 없음 · C1 width 줄바꿈
        r["design_language"] = "premium_minimal"
        r["motif"] = {"shape": "none", "min_repeats": 1}
        r["palette"]["rhythm"] = {"spot_min_regions": 1, "spot_path": "none"}
        r["product"]["grounding"] = "none"
        r["typography"]["break_strategy"] = "width"
        r["safety"]["must_be_visible"] = []
        r["copy_blocks"] = [b for b in r["copy_blocks"] if b["id"] != "side_caption"]
        for b in r["copy_blocks"]:
            if b["grid_ref"].get("row_anchor") == "before:discount_token":
                b["grid_ref"]["row_anchor"] = "lower"

    raw = mutate(premium_minimal)
    errors = validate(raw, valid_brief())
    check(not errors, f"conditional 전부 off 가 통과해야 한다: {[str(e) for e in errors]}")
    print(f"  {'PASS' if not errors else 'FAIL'}  모티프·spot 순환·접지·semantic 줄바꿈 전부 off "
          f"→ 에러 {len(errors)}건")
    for e in errors:
        print(f"        {e}")

    # 반대로 켰다고 선언하면 지켜져야 한다 (declare-then-enforce, §2-3)
    expect_codes(
        mutate(lambda r: r["motif"].update({"min_repeats": 9})),
        ["motif.repeats_below_min"],
        "min_repeats 를 선언했으면 충족돼야 한다",
    )


def test_design_language_is_not_a_selector() -> None:
    section("design_language 는 preset ID 가 아니다 (§6)")

    # D1 의 검증 단계 대응 — design_language 만 바꿔도 나머지 계약은 동일하다.
    # (픽셀 동일성은 Step 4 Renderer 에서 검증한다)
    base = valid_spec()
    spec_a = load(copy.deepcopy(base), valid_brief())
    variant = copy.deepcopy(base)
    variant["design_language"] = "promotion"
    spec_b = load(variant, valid_brief())

    a = {f: getattr(spec_a, f) for f in spec_a.__dataclass_fields__ if f != "design_language"}
    b = {f: getattr(spec_b, f) for f in spec_b.__dataclass_fields__ if f != "design_language"}
    check(a == b, "design_language 외 모든 필드가 동일해야 한다")
    print(f"  {'PASS' if a == b else 'FAIL'}  design_language 만 다른 두 Spec — "
          "나머지 필드 완전 동일 (Step 4 의 D1 전제)")

    # D2 — 같은 design_language 로 서로 다른 설계가 표현 가능해야 한다
    other = copy.deepcopy(base)
    other["grid"]["columns"] = 8
    other["zones"] = {
        "type": {"col_start": 0, "col_span": 8},
        "product": {"col_start": 3, "col_span": 5},
        "overlap_intent": "required",
    }
    other["product"]["fit"] = "area_cap"
    other["product"]["area_cap"] = 0.55
    other["product"]["bleed"] = ["right"]
    other["product"]["grounding"] = "none"
    for blk in other["copy_blocks"]:
        if isinstance(blk["grid_ref"].get("col_start"), int):
            blk["grid_ref"]["col_span"] = min(8 - blk["grid_ref"]["col_start"], 8)
    for inst in other["motif"]["instances"]:
        if isinstance(inst["grid_ref"].get("col_start"), int):
            inst["grid_ref"]["col_span"] = min(8 - inst["grid_ref"]["col_start"], 8)
    other["motif"]["instances"][1]["split_at"] = {"col": 3}

    errors = validate(other, valid_brief())
    check(not errors, f"같은 editorial 의 다른 설계가 통과해야 한다: {[str(e) for e in errors]}")
    print(f"  {'PASS' if not errors else 'FAIL'}  같은 editorial · 6단→8단 · 다른 제품 배치 "
          f"→ 에러 {len(errors)}건")
    for e in errors:
        print(f"        {e}")

    check("design_language" not in _renderer_facing_fields(), "표식용 — 아래 참조")


def _renderer_facing_fields() -> tuple:
    """Step 4 에서 Renderer 가 읽어도 되는 루트 필드 목록 (§6 R1).

    design_language 가 여기 없다는 것이 계약이다. Renderer 구현 시 이 목록을
    화이트리스트로 쓰고, 목록 밖 필드 접근을 테스트로 막는다.
    """
    return (
        "schema_version",
        "canvas",
        "grid",
        "zones",
        "product",
        "background",
        "typography",
        "palette",
        "motif",
        "copy_blocks",
        "layers",
        "safety",
    )


def test_error_aggregation() -> None:
    section("에러는 모아서 한 번에 올린다")

    def many(r):
        r["grid"]["columns"] = 5
        r["product"]["rotation"] = "spin"
        r["typography"]["roles"][0]["line_ratio"] = 9.0

    errors = validate(mutate(many), valid_brief())
    ok = len(errors) >= 3
    check(ok, f"세 건 이상 한 번에 보고: {len(errors)}건")
    print(f"  {'PASS' if ok else 'FAIL'}  스키마 에러 3건 동시 보고 → {[e.code for e in errors]}")

    raised = False
    try:
        load(mutate(many), valid_brief())
    except SpecInvalid as exc:
        raised = True
        check(len(exc.errors) >= 3, "SpecInvalid 가 전체를 담는다")
        check(exc.has("schema.enum"), "SpecInvalid.has() 동작")
    check(raised, "load 는 SpecInvalid 를 올린다")
    print(f"  {'PASS' if raised else 'FAIL'}  load() 는 SpecInvalid 로 거부")

    # 스키마가 깨졌으면 교차 검증을 돌리지 않는다 (오탐 방지)
    broken = mutate(lambda r: r.update({"grid": "six columns"}))
    codes = [e.code for e in validate(broken, valid_brief())]
    only_schema = all(c.startswith("schema.") for c in codes)
    check(only_schema, f"스키마 실패 시 교차 검증 미실행: {codes}")
    print(f"  {'PASS' if only_schema else 'FAIL'}  스키마 실패 시 교차 규칙 미실행 → {codes}")


def test_isolated_from_production() -> None:
    section("production 경로와 분리")

    import importlib

    # 주의: `import dynamic.validate as m` 은 패키지가 재노출한 **함수**를 집어온다.
    # 모듈 객체가 필요하므로 sys.modules 로 받는다
    names = ("dynamic.spec", "dynamic.brief", "dynamic.validate", "dynamic.errors")
    for name in names:
        importlib.import_module(name)
        mod = sys.modules[name]
        src = open(mod.__file__, encoding="utf-8").read()
        bad = [
            line.strip()
            for line in src.splitlines()
            if line.strip().startswith(("import pipeline", "from pipeline", "import api", "from api"))
        ]
        check(not bad, f"{name} 이 production 을 import 하지 않아야 한다: {bad}")
        print(f"  {'PASS' if not bad else 'FAIL'}  {name:22} production import 없음")

    loaded = [n for n in sys.modules if n == "pipeline" or n.startswith("pipeline.")]
    check(not loaded, f"pipeline 이 로드되지 않아야 한다: {loaded}")
    print(f"  {'PASS' if not loaded else 'FAIL'}  sys.modules 에 pipeline 없음 → {loaded}")


def test_run03_contract_gaps() -> None:
    """run 03 이 드러낸 B 급 gap 을 계약으로 닫았는지 (Q1~Q4).

    셋 다 **기존 Validator 규칙의 투영**이다. 새 규칙을 만들지 않았다.
    """
    section("run 03 contract gap — Q1~Q4")

    from dynamic import strict_planner_output_schema, describe_capabilities
    from dynamic.validate import CROSS_FIELD_RULES, COLOR_ROLE_REF_PATHS, FIXTURE_CONTEXT

    rs = strict_planner_output_schema(3, ("1:1",))[
        "properties"]["candidates"]["items"]["properties"]["render_spec"]
    P = rs["properties"]
    rules = dict(CROSS_FIELD_RULES)

    # Q1 — 0-based 가 zones · grid_ref 양쪽에 같은 문장으로
    starts = []

    def walk(n):
        if isinstance(n, dict):
            p = n.get("properties")
            if isinstance(p, dict) and "col_start" in p:
                starts.append(p["col_start"])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(rs)
    ok = len(starts) >= 5 and all("0-based" in (x.get("description") or "") for x in starts)
    check(ok, f"col_start 설명 {len(starts)}자리")
    print(f"  {'PASS' if ok else 'FAIL'}  col_start {len(starts)}자리 전부 0-based 명시 "
          "— zones 와 grid_ref 가 같은 의미를 본다")
    ok = "col_start + col_span <= grid.columns" in rules["*.col_start (정수)"]
    check(ok, "span 상한 규칙")
    print(f"  {'PASS' if ok else 'FAIL'}  col_start + col_span <= grid.columns 명시")

    # Q2 — 유니온 정수 가지가 rng 를 잃지 않는다
    zone_cs = P["zones"]["properties"]["type"]["properties"]["col_start"]
    ref_cs = P["copy_blocks"]["items"]["properties"]["grid_ref"]["properties"]["col_start"]
    int_branch = [b for b in ref_cs["anyOf"] if b.get("type") == "integer"][0]
    str_branch = [b for b in ref_cs["anyOf"] if b.get("type") == "string"][0]
    ok = (zone_cs.get("minimum") == 0 and int_branch.get("minimum") == 0
          and "maximum" not in int_branch and "enum" in str_branch)
    check(ok, f"union rng: {int_branch}")
    print(f"  {'PASS' if ok else 'FAIL'}  grid_ref.col_start 정수 가지 minimum=0 유지 · "
          "maximum 은 grid.columns 에 달려 있어 고정값을 넣지 않음 · string 가지 그대로")

    # 검증기도 같이 본다 — 음수는 이제 스키마 단계에서 걸린다
    import copy as _c
    import fixtures_renderspec as FXX
    bad = _c.deepcopy(dict(FXX.FIXTURES["A"][1]()))
    bad["copy_blocks"][0]["grid_ref"]["col_start"] = -1
    codes = [e.code for e in validate(bad, FXX.brief(), FIXTURE_CONTEXT)]
    ok = "schema.range" in codes
    check(ok, f"음수 col_start: {codes}")
    print(f"  {'PASS' if ok else 'FAIL'}  col_start=-1 → {codes} "
          "(전에는 유니온이라 그냥 통과했다)")

    # Q3 — 참조 폐포. 설명의 자리 목록이 실제 검사 목록과 같다
    closure = rules["*.color_role (참조 폐포)"]
    ok = all(pth in closure for pth in COLOR_ROLE_REF_PATHS)
    check(ok, "참조 자리 목록")
    print(f"  {'PASS' if ok else 'FAIL'}  참조 폐포 설명이 실제 검사 자리 "
          f"{len(COLOR_ROLE_REF_PATHS)}곳을 그대로 나열 — 설명만 좁아지지 않는다")
    roles_nodes = []

    def walk2(n):
        if isinstance(n, dict):
            p = n.get("properties")
            if isinstance(p, dict) and "color_role" in p:
                roles_nodes.append(p["color_role"])
            for v in n.values():
                walk2(v)
        elif isinstance(n, list):
            for v in n:
                walk2(v)
    walk2(rs)
    # typography.roles 는 face 5조합이라 items 가 anyOf 5가지다 — color_role 이
    # 가지마다 한 벌씩 나온다. 자리 수가 아니라 **빠짐없이** 붙었는지를 본다
    ok = len(roles_nodes) >= len(COLOR_ROLE_REF_PATHS) and all(
        "선언" in (x.get("description") or "") for x in roles_nodes)
    check(ok, f"color_role description {len(roles_nodes)}자리")
    print(f"  {'PASS' if ok else 'FAIL'}  color_role {len(roles_nodes)}자리 전부 설명 "
          f"(참조 자리 {len(COLOR_ROLE_REF_PATHS)}종 · face anyOf 5가지로 분기) "
          "— 지원 이름인 것과 선언한 것은 다른 조건")

    # v1.3 — 참조 무결성 3규칙이 이름 쓰는 자리마다 붙었는가
    cb = P["copy_blocks"]["items"]["properties"]
    mi = P["motif"]["properties"]["instances"]["items"]["properties"]
    checks = {
        "copy_blocks[].type_role": (cb["type_role"], "typography.roles"),
        "copy_blocks[].id": (cb["id"], "같은 이름 공간"),
        "motif.instances[].role": (mi["role"], "서로 달라야"),
    }
    bad = [k for k, (node, needle) in checks.items()
           if needle not in (node.get("description") or "")]
    check(not bad, f"참조 무결성 설명 누락: {bad}")
    print(f"  {'PASS' if not bad else 'FAIL'}  참조 무결성 3규칙 투영 — "
          "type_role · id ↔ motif role 이름공간 · role 중복")

    # motif.pattern.role 도 같은 이름 공간이다 — 빠뜨리기 쉬운 자리
    pat = P["motif"]["properties"]["pattern"]
    pat_roles = [b["properties"]["role"] for b in pat.get("anyOf", [pat])
                 if isinstance(b.get("properties"), dict) and "role" in b["properties"]]
    ok = pat_roles and all("이름 공간" in (x.get("description") or "") for x in pat_roles)
    check(ok, "pattern.role 설명")
    print(f"  {'PASS' if ok else 'FAIL'}  motif.pattern.role 도 같은 설명 "
          "(instances 와 이름 공간을 공유한다)")

    # 위 3개 코드는 각각 아래에서 개별 케이스로 이미 검사한다.
    #   copy.type_role_unknown       REJECTS 표
    #   motif.duplicate_role         REJECTS 표
    #   anchor.namespace_collision   REJECTS 표
    # 전에는 실제 LLM 실행 기록(run 05) 파일을 읽어 세 위반의 동시 발생을
    # 한 번 더 확인했는데, 그 기록은 개인 실험 산출물이라 저장소에 두지
    # 않는다. 검사 자체는 위 표가 그대로 들고 있다.

    # Q4 — motif.shape 관계
    ok = P["motif"]["properties"]["shape"].get("description")
    check(bool(ok), "motif.shape description")
    print(f"  {'PASS' if ok else 'FAIL'}  motif.shape 에 pattern/instances 관계 명시")

    caps = describe_capabilities()["cross_field_rules"]
    ok = all(k in caps for k in ("*.col_start (정수)", "*.color_role (참조 폐포)",
                                 "motif.shape"))
    check(ok, "capabilities 투영")
    print(f"  {'PASS' if ok else 'FAIL'}  capabilities.cross_field_rules {len(caps)}개 "
          "— 단일 출처는 validate.py")


def main() -> int:
    print("=" * 72)
    print("RenderSpec 검증 테스트 — E12 v0.3 Step 1")
    print("=" * 72)

    test_valid_spec_passes()
    test_run03_contract_gaps()
    test_trust_boundary()
    test_required_cross_field_rules()
    test_documented_errors()
    test_schema_level()
    test_additional_consistency()
    test_conditional_heuristics_can_be_off()
    test_design_language_is_not_a_selector()
    test_error_aggregation()
    test_isolated_from_production()

    print("\n" + "=" * 72)
    if FAILS:
        print(f"실패 {len(FAILS)} / 검사 {CHECKS}")
        for f in FAILS:
            print(f"  ✗ {f}")
        return 1
    print(f"전체 통과 — 검사 {CHECKS}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

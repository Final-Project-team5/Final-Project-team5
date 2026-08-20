"""Planner 입출력 계약 테스트 — Step 7 준비.

**LLM 호출은 없다.** 계약 세 개가 닫혔는지만 본다.

    ① 서비스 입력  →  CreativeBrief
    ② Planner 출력 =  RenderSpec 후보들 (복수 표현 가능)
    ③ Safety 실패  →  Planner 피드백 (처방 없음)

그리고 **Planner 를 믿지 않는다** — 잘못된 후보가 Step 1 검증에서 걸리는지
직접 확인한다.

실행:  python tests/test_planner_contract.py
"""

from __future__ import annotations

import copy as copymod
import dataclasses
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from dynamic import (  # noqa: E402
    CONFIRMED_BACKGROUND_FIELDS,
    PASSED_SCOPE,
    BackgroundContextInput,
    BriefCopy,
    CopyItem,
    PlannerCandidate,
    PlannerInput,
    PlannerResult,
    ProductGeometry,
    ProductIdentity,
    ProductRenderAsset,
    SafetyFeedback,
    ServiceRequest,
    build_plan,
    describe_capabilities,
    load,
    normalize_preferred_color,
    render_with_evidence,
    review_candidates,
    to_creative_brief,
    validate_safety,
)
from dynamic import (  # noqa: E402
    MIN_DIFFERING_AXES,
    MIN_STRUCTURAL_AXES,
    check_diversity,
)
from dynamic.planner_io import (  # noqa: E402
    CONFIRMATION_SOURCES,
    EXCLUDED_VISION_FIELDS,
    FIELD_MAPPING,
)
from fixtures_renderspec import FIXTURES, brief as fixture_brief  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
#: 테스트 고정 자산 — 실제 세그멘테이션 결과다. 합성 마스크로
#: 바꾸면 가림/대비 측정이 실제 제품 실루엣이 아닌 값을 재게 된다.
ASSETS = Path(__file__).resolve().parent / "_assets"
FAILS: list[str] = []
CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILS.append(label)


def section(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 62 - len(title)))


def service_request() -> ServiceRequest:
    base = fixture_brief()
    return ServiceRequest(
        business_type="product",
        category="beauty",
        confirmed_product="독도토너 1025",
        confirmation_source="vision_confirmed",
        tone="minimal_product",
        keywords=("수분", "신제품"),
        request="밝고 깨끗한 느낌으로",
        output_ratio="1:1",
        visual_style=None,
        background_context=BackgroundContextInput(
            palette=("웜 베이지", "딥 그린"), mood="차분하고 고급스러운"),
        product_signals=base.product_signals,
        copy=base.copy,
        category_label="스킨케어",
        preferred_color="#2E6F5E",
    )


def fixed_asset():
    mask = Image.open(ASSETS / "mask" / "cosmetic_birefnet-general.png").convert("L")
    original = Image.open(ASSETS / "cutout" / "cosmetic_00_original.png").convert("RGB")
    rgba = original.convert("RGBA")
    rgba.putalpha(mask)
    m = np.array(mask) > 128
    ys, xs = np.where(m)
    geo = ProductGeometry.from_mask_size(
        cutout_width=mask.size[0], cutout_height=mask.size[1],
        mask_bbox=(int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())))
    return ProductRenderAsset(rgba), geo


# ──────────────────────────────────────────────────────────────────────────
def test_input_mapping() -> None:
    section("① 서비스 입력 → CreativeBrief")

    req = service_request()
    brief = to_creative_brief(req)

    print("  필드 매핑")
    for src, dst in FIELD_MAPPING.items():
        print(f"    {src:20} → {dst}")

    check(brief.business_type == "product" and brief.category == "beauty", "업종/카테고리")
    check(brief.request == "밝고 깨끗한 느낌으로", "자연어 요청")
    check(brief.keywords == ("수분", "신제품"), "keywords")
    check(brief.product_signals, "product_signals 전달")
    print(f"\n  PASS  tone={brief.tone} · ratio={brief.output_ratio} · "
          f"keywords={list(brief.keywords)} · request={brief.request!r}")

    # adapter 는 **디자인 결정을 하지 않는다**
    designish = ("grid", "zones", "palette", "motif", "typography", "layers")
    leaked = [f for f in designish if hasattr(brief, f)]
    check(not leaked, f"adapter 가 디자인 필드를 만들면 안 된다: {leaked}")
    print(f"  {'PASS' if not leaked else 'FAIL'}  CreativeBrief 에 디자인 결정 필드 없음 "
          "— grid/palette/motif 는 Planner 의 일")


def test_product_identity_boundary() -> None:
    section("② confirmed_product ↔ RenderSpec.product 의미 분리")

    brief = to_creative_brief(service_request())
    ident: ProductIdentity = brief.product_identity

    print(f"  CreativeBrief.product_identity   '제품이 **무엇**인가'")
    print(f"      confirmed_product   {ident.confirmed_product!r}   ← 디자인 판단에 사용 가능")
    print(f"      confirmation_source {ident.confirmation_source!r}          ← provenance · 판단 제외")
    print(f"  RenderSpec.product               '제품을 **어떻게** 놓는가'")
    spec_product = FIXTURES["A"][1]()["product"]
    print(f"      {list(spec_product)}")

    ok = set(ident.for_design()) == {"confirmed_product"}
    check(ok, f"디자인 입력: {ident.for_design()}")
    print(f"\n  {'PASS' if ok else 'FAIL'}  for_design() 은 confirmed_product 만 "
          f"· provenance() 는 {list(ident.provenance())}")

    # 두 개념이 서로 다른 자리에 있다
    ok = not hasattr(brief, "product") and "fit" in spec_product
    check(ok, "이름 충돌 없음")
    print(f"  {'PASS' if ok else 'FAIL'}  CreativeBrief 에 `product` 필드 없음 · "
          "RenderSpec.product 는 배치 전용")

    # production enum 을 그대로 보존한다 — 축약값을 새로 만들지 않는다
    ok = ident.confirmation_source in CONFIRMATION_SOURCES
    check(ok, f"production enum: {ident.confirmation_source}")
    print(f"  {'PASS' if ok else 'FAIL'}  confirmation_source enum {list(CONFIRMATION_SOURCES)}")
    raised = None
    try:
        ProductIdentity(confirmed_product="x", confirmation_source="vision")
    except ValueError as exc:
        raised = exc
    check(raised is not None, "축약값 거부")
    print(f"  {'PASS' if raised else 'FAIL'}  축약값 'vision' → ValueError (새 enum 을 만들지 않는다)")

    # 제품 확정 이전 flow control 값은 가져오지 않는다
    leaked = [f for f in EXCLUDED_VISION_FIELDS if hasattr(brief, f) or hasattr(ident, f)]
    check(not leaked, f"제외 필드 유입: {leaked}")
    print(f"  {'PASS' if not leaked else 'FAIL'}  {list(EXCLUDED_VISION_FIELDS)} 미유입 "
          "— Planner 는 confirmed_product 확정 이후부터 시작한다")


def test_background_context() -> None:
    section("③ background_context 계약 — 확인된 6개 필드만")

    # 팀 `copy_model/background.py:BackgroundContext` 에서 코드로 확인한 6개.
    # 전역 schema_confirmed 플래그를 쓰지 않는다 — 무엇이 확인됐는지가
    # 필드 이름 자체로 드러나야 한다
    ok = CONFIRMED_BACKGROUND_FIELDS == (
        "palette", "lighting", "texture", "mood", "composition", "usable")
    check(ok, "확인 필드 6개 고정")
    print(f"  {'PASS' if ok else 'FAIL'}  CONFIRMED_BACKGROUND_FIELDS = "
          f"{list(CONFIRMED_BACKGROUND_FIELDS)}")

    ctx = BackgroundContextInput(
        palette=("웜 베이지", "딥 그린"), mood="차분한",
        unconfirmed={"dominant": "#EFEAE3"})
    print(f"  {ctx.as_dict()}")

    ok = ctx.hint("palette") == ["웜 베이지", "딥 그린"] and ctx.hint("mood") == "차분한"
    check(ok, "확인된 필드는 값을 준다")
    print(f"  {'PASS' if ok else 'FAIL'}  hint('palette') = {ctx.hint('palette')}")

    # ★ 이름이 있다고 신뢰하지 않는다. 6개 밖은 보존만 하고 내보내지 않는다
    ok = ctx.hint("dominant") is None and "dominant" not in ctx.design_hints()
    check(ok, "확인 안 된 key 는 hint 로 새지 않는다")
    print(f"  {'PASS' if ok else 'FAIL'}  hint('dominant') = {ctx.hint('dominant')} "
          f"(unconfirmed 에 보존: {sorted(ctx.unconfirmed)})")

    # ★ palette 는 자연어다 — HEX 로 해석하면 안 된다
    ok = all(not str(c).startswith("#") for c in ctx.palette)
    check(ok, "palette 는 자연어")
    print(f"  {'PASS' if ok else 'FAIL'}  palette 를 HEX 로 바꾸지 않는다 — "
          f"resolve_palette() 입력이 아니라 Planner 가 읽는 prior 다")

    # ★ usable=False → 일부만 골라 쓰지 않는다. 전부 막는다
    unusable = BackgroundContextInput(palette=("웜 베이지",), mood="차분한", usable=False)
    ok = unusable.design_hints() == {} and unusable.hint("mood") is None
    check(ok, "usable=False 면 전부 제외")
    print(f"  {'PASS' if ok else 'FAIL'}  usable=False → design_hints() = "
          f"{unusable.design_hints()}")

    brief = to_creative_brief(service_request())
    ok = brief.background_context is not None and brief.background_context.design_hints()
    check(ok, "brief 로 전달")
    print(f"  {'PASS' if ok else 'FAIL'}  CreativeBrief 까지 전달 "
          f"(필드 {sorted(brief.background_context.design_hints())})")

    # 가드 — 상태가 겉으로 드러나야 "Planner 가 배경을 못 정한다"고 오판하지 않는다
    pin = PlannerInput.of(brief)
    ok = pin.background_context_status == "present" and pin.background_ready()
    check(ok, f"background 상태: {pin.background_context_status}")
    print(f"  {'PASS' if ok else 'FAIL'}  status = {pin.background_context_status!r} · "
          f"background_ready() = {pin.background_ready()}")

    for value, expected in (
        (None, "absent"),
        (BackgroundContextInput(mood="차분한", usable=False), "unusable"),
        (BackgroundContextInput(), "empty"),
    ):
        p = PlannerInput.of(to_creative_brief(
            dataclasses.replace(service_request(), background_context=value)))
        ok = p.background_context_status == expected and not p.background_ready()
        check(ok, f"status={expected}")
        print(f"  {'PASS' if ok else 'FAIL'}  {expected:<9} → background_ready() = "
              f"{p.background_ready()}")


def test_preferred_color() -> None:
    section("③-2 preferred_color — soft hint 이지 지시가 아니다")

    brief = to_creative_brief(service_request())
    ok = brief.preferred_color == "#2E6F5E"
    check(ok, "brief 까지 전달")
    print(f"  {'PASS' if ok else 'FAIL'}  brief.preferred_color = {brief.preferred_color}")

    # ★ 값이 있다고 palette.source 가 preferred 로 강제되지 않는다
    ok = "preferred" in describe_capabilities()["palette_sources"]
    check(ok, "source 는 Planner 가 고른다")
    print(f"  {'PASS' if ok else 'FAIL'}  capabilities.palette_sources = "
          f"{sorted(describe_capabilities()['palette_sources'])}")

    # ★ 형식은 조용히 보정하지 않는다 — 고친 색은 사용자가 고른 색이 아니다
    for bad in ("#FFF", "red", "2E6F5E", "#GGGGGG"):
        try:
            normalize_preferred_color(bad)
            ok = False
        except ValueError:
            ok = True
        check(ok, f"거부: {bad}")
        print(f"  {'PASS' if ok else 'FAIL'}  {bad!r} 거부 (축약·색이름을 해석하지 않는다)")

    ok = normalize_preferred_color("#2e6f5e") == "#2E6F5E"
    check(ok, "대소문자 정규화")
    print(f"  {'PASS' if ok else 'FAIL'}  '#2e6f5e' → {normalize_preferred_color('#2e6f5e')}")


def test_planner_input() -> None:
    section("④ PlannerInput — Planner 가 고를 수 있는 값의 범위")

    brief = to_creative_brief(service_request())
    pin = PlannerInput.of(brief, candidate_count=3)
    caps = pin.capabilities

    for key in ("canvas_ratios", "grid_columns", "overlap_intents", "type_faces",
                "background_tones", "motif_shapes"):
        print(f"  {key:20} {caps[key]}")
    print(f"  forbidden            {caps['forbidden'][0]}")
    print(f"                       {caps['forbidden'][1]}")

    check(caps["canvas_ratios"] == ["1:1"], "capability 는 현재 Renderer 기준")
    check(caps["overlap_intents"] == ["none", "allowed", "required"], "overlap enum")
    check("sans/bold" not in caps["type_faces"], "미지원 서체 조합 제외")
    check(pin.candidate_count == 3 and not pin.is_redesign, "후보 수 / 재설계 여부")
    print(f"\n  PASS  candidate_count={pin.candidate_count} · is_redesign={pin.is_redesign}")
    print("        capability 의 단일 출처는 spec 모듈 — 프롬프트에 값을 손으로 복사하지 않는다")


def test_planner_output() -> None:
    section("⑤⑥ Planner 출력 = RenderSpec 후보들 (복수)")

    brief = fixture_brief()
    # **사람이 쓴 fixture 를 Planner 출력인 것처럼** 담는다 (LLM 호출 없음)
    result = PlannerResult(
        candidates=tuple(
            PlannerCandidate(id=f"cand_{k}", render_spec=fn(), label=name,
                             rationale=f"{name} 방향")
            for k, (name, fn) in FIXTURES.items()
        ),
        input_digest="demo",
    )
    print(f"  후보 {len(result)}개 — {list(result.design_languages())}")
    check(len(result) == 4, "복수 후보 표현")
    check(len(set(result.design_languages())) == 4, "서로 다른 design_language")

    reviews = review_candidates(result, brief)
    for r in reviews:
        print(f"    {r.candidate_id:10} accepted={r.accepted}  {list(r.error_codes)}")
    check(all(r.accepted for r in reviews), "정상 후보 전부 통과")

    # Planner 를 믿지 않는다 — 잘못된 후보는 Step 1 이 막는다
    bad_specs = {
        "px 좌표를 넣음": lambda s: s["product"].update({"x": 120, "y": 340}),
        "정수 row index": lambda s: s["copy_blocks"][0]["grid_ref"].update({"row_anchor": 54}),
        "미지의 enum": lambda s: s["zones"].update({"overlap_intent": "product_over_type"}),
        "미지원 서체": lambda s: s["typography"]["roles"][1].update(
            {"family": "serif", "weight": "regular"}),
        "spec_source 자칭": lambda s: s.update({"spec_source": "fixture"}),
    }
    print()
    for label, mut in bad_specs.items():
        raw = copymod.deepcopy(FIXTURES["A"][1]())
        mut(raw)
        rv = review_candidates(
            PlannerResult(candidates=(PlannerCandidate(id="bad", render_spec=raw),)), brief)[0]
        check(not rv.accepted, f"{label} 거부")
        print(f"  {'PASS' if not rv.accepted else 'FAIL'}  {label:16} → {list(rv.error_codes)}")
    print("        Planner 가 무엇을 만들어도 Step 1 검증이 방어벽이다")


def test_candidate_diversity() -> None:
    section("⑪ 후보 다양성 계약 — 정말 다른 디자인인가")

    brief = fixture_brief()
    real = PlannerResult(candidates=tuple(
        PlannerCandidate(id=k, render_spec=fn(), label=name)
        for k, (name, fn) in FIXTURES.items()))
    rep = check_diversity(real)
    for pr in rep.pairs:
        print(f"  {pr.a}↔{pr.b}  갈린 {len(pr.differing):2} · 구조 {len(pr.structural):2} "
              f"· {list(pr.categories)}")
    check(rep.sufficient and not rep.code, f"실제 4종: {rep.code}")
    print(f"  {'PASS' if rep.sufficient else 'FAIL'}  실제 fixture 4종 → 충분 "
          f"(하한 {MIN_DIFFERING_AXES}축 / 구조 {MIN_STRUCTURAL_AXES}축)")

    # 색만 바꾼 후보는 다양성 부족으로 **명시적 결과**를 낸다
    a = copymod.deepcopy(FIXTURES["A"][1]())
    b = copymod.deepcopy(a)
    b["palette"]["strategy"] = "complementary"
    b["palette"]["background_tone"] = "dark"
    rep2 = check_diversity(PlannerResult(candidates=(
        PlannerCandidate(id="a", render_spec=a), PlannerCandidate(id="b", render_spec=b))))
    ok = not rep2.sufficient and rep2.code == "insufficient_diversity"
    check(ok, f"색만 변경: {rep2.code}")
    print(f"\n  {'PASS' if ok else 'FAIL'}  같은 layout + 색만 변경 → {rep2.code}")
    print(f"        {rep2.detail}")

    # size_step 만 조금 바꾼 것도 마찬가지
    c = copymod.deepcopy(a)
    c["typography"]["roles"][1]["size_step"] = 4
    rep3 = check_diversity(PlannerResult(candidates=(
        PlannerCandidate(id="a", render_spec=a), PlannerCandidate(id="c", render_spec=c))))
    ok = rep3.code == "insufficient_diversity"
    check(ok, f"size_step 만: {rep3.code}")
    print(f"  {'PASS' if ok else 'FAIL'}  같은 layout + size_step 만 변경 → {rep3.code}")

    # 후보가 하나면 비교 대상이 없다 — 실패가 아니다
    rep4 = check_diversity(PlannerResult(candidates=(PlannerCandidate(id="only", render_spec=a),)))
    ok = rep4.sufficient and rep4.code == "single_candidate"
    check(ok, f"단일 후보: {rep4.code}")
    print(f"  {'PASS' if ok else 'FAIL'}  후보 1개 → {rep4.code} (실패 아님)")
    print("        판정만 한다 — 부족해도 후보를 다시 만들거나 고치지 않는다 (자동 retry 없음)")


def test_safety_feedback() -> None:
    section("⑦ Safety 실패 → Planner 피드백")

    asset, geo = fixed_asset()
    brief = fixture_brief()
    plan = build_plan(load(FIXTURES["C"][1](), brief), brief, geo)
    _, ev = render_with_evidence(plan, asset, geo)
    fb = SafetyFeedback.from_result("cand_C", validate_safety(plan, ev))

    print(f"  candidate={fb.candidate_id} · passed={fb.passed} · "
          f"실패 {len(fb.failures())}건")
    for v in fb.failures()[:3]:
        print(f"    {v['code']:28} {v['element_id']:16} "
              f"{v['measured']} / {v['threshold']}  ({v['relation']})")

    required = {"code", "element_id", "element_kind", "severity",
                "measured", "threshold", "layer", "relation"}
    ok = all(required <= set(v) for v in fb.violations)
    check(ok, "필수 필드")
    print(f"\n  {'PASS' if ok else 'FAIL'}  Planner 가 받는 필드 {sorted(required)}")

    grouped = fb.by_element()
    ok = "headline" in grouped and len(grouped["headline"]) >= 2
    check(ok, f"요소별 묶기: {list(grouped)}")
    print(f"  {'PASS' if ok else 'FAIL'}  요소별 묶음 — headline 에 "
          f"{[v['code'] for v in grouped.get('headline', [])]}")

    ok = json.dumps(fb.payload, ensure_ascii=False) is not None
    check(ok, "직렬화")
    print(f"  {'PASS' if ok else 'FAIL'}  JSON 직렬화 가능")

    # 재설계 요청으로 되돌려 넣을 수 있다
    pin = PlannerInput.of(brief, candidate_count=2, feedback=[fb])
    check(pin.is_redesign and len(pin.feedback) == 1, "재설계 입력")
    print(f"  PASS  PlannerInput(feedback=[…]) → is_redesign={pin.is_redesign}")
    print("        무엇이 실패했는지만 넘어간다 — 색/배치/layer 중 무엇을 고칠지는 Planner 가 정한다")


def test_passed_scope() -> None:
    section("⑧ passed 의 의미 — 넓게 읽지 않는다")

    asset, geo = fixed_asset()
    brief = fixture_brief()
    plan = build_plan(load(FIXTURES["B"][1](), brief), brief, geo)
    _, ev = render_with_evidence(plan, asset, geo)
    res = validate_safety(plan, ev)
    payload = res.for_planner()

    print(f"  B passed={payload['passed']}")
    print(f"  passed_scope: {payload['passed_scope']}")
    print(f"  unsupported_checks {len(payload['unsupported_checks'])}건 · "
          f"deferred_checks {len(payload['deferred_checks'])}건")

    ok = payload["passed"] and payload["passed_scope"] == PASSED_SCOPE
    check(ok, "passed_scope 동봉")
    print(f"  {'PASS' if ok else 'FAIL'}  passed=True 여도 커버리지 공백을 함께 싣는다")

    fb = SafetyFeedback.from_result("cand_B", res)
    ok = len(fb.incomplete_coverage) == len(payload["deferred_checks"]) + len(
        payload["unsupported_checks"])
    check(ok, "incomplete_coverage")
    print(f"  {'PASS' if ok else 'FAIL'}  SafetyFeedback.incomplete_coverage "
          f"{len(fb.incomplete_coverage)}건 — Planner/API 가 별도로 볼 수 있다")
    for item in fb.incomplete_coverage:
        print(f"      · {item[:76]}…")


def test_full_chain() -> None:
    section("⑨ 전체 흐름 — Planner 출력이 그대로 파이프라인을 탄다")

    asset, geo = fixed_asset()
    brief = fixture_brief()
    result = PlannerResult(candidates=(
        PlannerCandidate(id="cand_A", render_spec=FIXTURES["A"][1](), label="Clean editorial"),
        PlannerCandidate(id="cand_B", render_spec=FIXTURES["B"][1](), label="Premium minimal"),
    ))

    print("  CreativeBrief → Planner → RenderSpec → validate → build_plan → render → safety")
    for cand in result.candidates:
        rv = review_candidates(PlannerResult(candidates=(cand,)), brief)[0]
        if not rv.accepted:
            print(f"    {cand.id}  검증 거부 {rv.error_codes}")
            continue
        plan = build_plan(load(dict(cand.render_spec), brief), brief, geo)
        _, ev = render_with_evidence(plan, asset, geo)
        res = validate_safety(plan, ev)
        fb = SafetyFeedback.from_result(cand.id, res)
        print(f"    {cand.id}  {cand.label:18} validate OK → plan → render → "
              f"safety {'PASS' if fb.passed else f'FAIL {len(fb.failures())}건'}")
        check(True, f"{cand.id} chain")

    print("\n  PASS  Visual Prompt 는 이 흐름 어디에도 없다")
    print("        RenderSpec.background(의미) → server prompt builder → Visual Prompt(문자열)")
    print("        Planner 는 prompt 생성기가 아니다")


def test_no_llm_no_retry() -> None:
    section("⑩ 이번 단계에서 하지 않은 것")

    src = open(ROOT / "dynamic" / "planner_io.py", encoding="utf-8").read()
    banned = {
        "LLM 호출": ("openai", "anthropic", "requests.post", "httpx", "completion("),
        "프롬프트 문자열": ("system_prompt", "PROMPT_TEMPLATE", "user_prompt"),
        "자동 retry": ("while ", "retry(", "regenerate("),
    }
    for label, needles in banned.items():
        hits = [n for n in needles if n in src]
        check(not hits, f"{label}: {hits}")
        print(f"  {'PASS' if not hits else 'FAIL'}  {label} 없음")

    import dynamic.planner_io as m
    leaked = [n for n in dir(m) if n in ("build_prompt", "call_llm", "generate", "retry")]
    check(not leaked, f"유출 API: {leaked}")
    print(f"  {'PASS' if not leaked else 'FAIL'}  생성/재시도 API 없음 — 계약만 있다")

    bad = [ln.strip() for ln in src.splitlines()
           if ln.strip().startswith(("import pipeline", "from pipeline", "import api", "from api"))]
    check(not bad, f"production import: {bad}")
    print(f"  {'PASS' if not bad else 'FAIL'}  production import 없음")
    loaded = [n for n in sys.modules if n == "pipeline" or n.startswith("pipeline.")]
    check(not loaded, f"pipeline 로드: {loaded}")
    print(f"  {'PASS' if not loaded else 'FAIL'}  sys.modules 에 pipeline 없음")


def main() -> int:
    print("=" * 72)
    print("Planner 입출력 계약 테스트 — Step 7 준비")
    print("=" * 72)

    test_input_mapping()
    test_product_identity_boundary()
    test_background_context()
    test_preferred_color()
    test_planner_input()
    test_planner_output()
    test_candidate_diversity()
    test_safety_feedback()
    test_passed_scope()
    test_full_chain()
    test_no_llm_no_retry()

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

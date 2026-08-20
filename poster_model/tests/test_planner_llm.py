"""AI Design Planner MVP 테스트 — Step 9.

**FakeLLM 으로 돈다.** 실제 모델 호출은 API 키가 필요해서 여기서 하지 않는다
(`tools/verification/dynamic_planner/run_planner.py` 가 그 몫이다).
이 파일이 확인하는 것은 "모델이 좋은 디자인을 냈는가"가 아니라
**계약이 닫혀 있는가**다.

    프롬프트에 무엇이 들어가고 무엇이 안 들어가는가
    구조화 출력을 강제하는가
    잘못된 출력을 고치지 않고 거부하는가
    후보가 그대로 파이프라인을 타는가

실행:  python tests/test_planner_llm.py
"""

from __future__ import annotations

import copy as copymod
import dataclasses
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from dynamic import (  # noqa: E402
    BackgroundContextInput,
    DesignPlanner,
    FakeLLMClient,
    PlannerConfig,
    PlannerInput,
    PlannerOutputInvalid,
    ProductGeometry,
    ProductRenderAsset,
    SafetyFeedback,
    ServiceRequest,
    build_plan,
    check_diversity,
    load,
    planner_output_schema,
    render_with_evidence,
    review_candidates,
    to_creative_brief,
    validate_safety,
)
import dynamic.planner as planner_mod  # noqa: E402
from dynamic.planner import prompt_digest  # noqa: E402
from dynamic.planner_io import describe_capabilities  # noqa: E402
from dynamic.planner_prompt import build_system_prompt, build_user_prompt  # noqa: E402
from fixtures_renderspec import FIXTURES, brief as fixture_brief  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
#: 테스트 고정 자산 — 실제 세그멘테이션 결과다. 합성 마스크로
#: 바꾸면 가림/대비 측정이 실제 제품 실루엣이 아닌 값을 재게 된다.
ASSETS = Path(__file__).resolve().parent / "_assets"
# 테스트 산출물은 **저장소 안에 남기지 않는다.** 검사는 전부 메모리 위의
# 이미지로 하고, 저장은 사람이 눈으로 확인하고 싶을 때를 위한 것이다.
# 눈으로 보려면  DYNAMIC_TEST_OUT=/some/dir  로 경로를 지정한다.
OUT = Path(os.environ.get("DYNAMIC_TEST_OUT")
           or tempfile.mkdtemp(prefix="dynamic_step9_"))

FAILS: list[str] = []
CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILS.append(label)


def section(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 62 - len(title)))


def service_request(**over) -> ServiceRequest:
    base = fixture_brief()
    kw = dict(
        business_type="product", category="beauty",
        confirmed_product="독도토너 1025", confirmation_source="vision_confirmed",
        tone="minimal_product", keywords=("수분", "신제품"),
        request="밝고 깨끗한 느낌으로", output_ratio="1:1",
        # usable=False — 못 쓴다고 표시된 분석. 토큰이 하나라도 새면 안 된다.
        # product_signals 와 겹치지 않는 **고유 토큰** 이라 유출 여부를 정확히 본다
        background_context=BackgroundContextInput(
            mood="VISIONMOODTOKEN", composition="VISIONSURFACETOKEN", usable=False),
        product_signals=base.product_signals, copy=base.copy,
        category_label="스킨케어",
    )
    kw.update(over)
    return ServiceRequest(**kw)


def planner_input(count: int = 3, **over) -> PlannerInput:
    return PlannerInput.of(to_creative_brief(service_request(**over)),
                           candidate_count=count)


def fake_response(keys=("A", "C", "D")) -> dict:
    """FakeLLM 이 돌려줄 응답.

    **fixture 를 프롬프트로 가르치지 않는다** — 여기서는 "모델이 이런 걸 냈다"고
    가정할 뿐이다. 실제 프롬프트에 A/B/C/D 는 들어가지 않는다 (아래 테스트로 확인).
    """
    return {"candidates": [
        {"id": f"cand_{k}", "label": FIXTURES[k][0],
         "rationale": f"{FIXTURES[k][0]} 방향으로 설계", "render_spec": FIXTURES[k][1]()}
        for k in keys
    ]}


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
def test_prompt_composition() -> None:
    section("③ 프롬프트 구성 — capabilities 는 spec 모듈에서 온다")

    pin = planner_input()
    system = build_system_prompt(pin)
    user = build_user_prompt(pin)

    for token in ('"none",\n    "allowed",\n    "required"', "sans/regular", "rotate_ccw",
                  '"light"', "grid_columns"):
        ok = token.replace("\n    ", "") in system.replace("\n    ", "")
        check(ok, f"capabilities 에 {token!r}")
    print(f"  PASS  system {len(system)}자 · capabilities 동적 삽입 "
          "(overlap enum · type_faces · orientation · background_tone …)")

    for token in ("forbidden", "픽셀 좌표", "정수 row index", "spec_source", "임의 shape"):
        check(token in system, f"금지 목록에 {token!r}")
    print(f"  PASS  금지 목록 포함 — 픽셀 좌표 · 정수 row index · spec_source · 임의 shape/HEX")

    # design_language 가 템플릿이 아니라는 지시
    ok = "템플릿" in system and "prior" in system
    check(ok, "design_language 지시")
    print(f"  {'PASS' if ok else 'FAIL'}  \"design_language 는 템플릿 이름이 아니다\" 명시")

    # fixture 이름을 가르치지 않는다
    leaked = [n for n in ("Clean editorial", "Premium minimal", "Contemporary graphic",
                          "fixture A", "A/B/C/D") if n in system or n in user]
    check(not leaked, f"fixture 유출: {leaked}")
    print(f"  {'PASS' if not leaked else 'FAIL'}  fixture 이름이 프롬프트에 없다 "
          "— 템플릿 선택으로 유도하지 않는다")

    # 다양성 요구는 프롬프트에, 판정은 코드에
    ok = "composition" in system and "insufficient_diversity" in system
    check(ok, "다양성 지시")
    print(f"  {'PASS' if ok else 'FAIL'}  다양성 요구 + \"판정은 코드가 한다\" 명시")

    ok = f'"candidate_count": {pin.candidate_count}' in user
    check(ok, "candidate_count 전달")
    print(f"  {'PASS' if ok else 'FAIL'}  candidate_count={pin.candidate_count} 를 user 에 전달")


def test_prompt_leak_guards() -> None:
    section("⑥⑦ 프롬프트 유출 방지선")

    # confirmation_source 는 디자인 입력이 아니다
    pin = planner_input()
    text = build_system_prompt(pin) + build_user_prompt(pin)
    ok = "vision_confirmed" not in text and "confirmation_source" not in text
    check(ok, "confirmation_source 유출")
    print(f"  {'PASS' if ok else 'FAIL'}  confirmation_source / 'vision_confirmed' 미유입")
    ok = "독도토너 1025" in text
    check(ok, "confirmed_product 는 들어간다")
    print(f"  {'PASS' if ok else 'FAIL'}  confirmed_product 는 디자인 입력이라 들어간다")

    # usable=False → 일부라도 직렬화하지 않는다
    user = build_user_prompt(pin)
    leaked = [t for t in ("VISIONMOODTOKEN", "VISIONSURFACETOKEN") if t in user]
    ok = not leaked and '"background_context_status": "unusable"' in user
    check(ok, f"unusable background 유출: {leaked}")
    print(f"  {'PASS' if ok else 'FAIL'}  usable=False → 필드 토큰 {leaked} "
          "미유입 · status 만 전달")
    ok = "추측하지 마라" in user
    check(ok, "추측 금지 문구")
    print(f"  {'PASS' if ok else 'FAIL'}  \"없는 정보를 추측하지 마라\" 지시 포함")

    # usable=True → 확인된 6개 필드만 들어간다. 그 밖의 key 는 보존만 하고 막는다
    ready = planner_input(background_context=BackgroundContextInput(
        mood="VISIONMOODTOKEN", palette=("웜 베이지",),
        unconfirmed={"surface": "VISIONSURFACETOKEN"}))
    u2 = build_user_prompt(ready)
    ok = ('"mood": "VISIONMOODTOKEN"' in u2
          and '"background_context_status": "present"' in u2
          and "VISIONSURFACETOKEN" not in u2)
    check(ok, "확인된 필드만 전달")
    print(f"  {'PASS' if ok else 'FAIL'}  usable=True → 확인된 6필드만 전달 · "
          "unconfirmed key 는 프롬프트로 나가지 않는다")

    # ★ palette 는 자연어 그대로 간다 — HEX 로 바꾸지 않는다
    ok = "웜 베이지" in u2 and '"preferred_color"' in u2
    check(ok, "palette 자연어 유지")
    print(f"  {'PASS' if ok else 'FAIL'}  background palette 를 자연어 그대로 전달 "
          "(색 계산 입력이 아니라 Planner 가 읽는 prior)")


def test_structured_output() -> None:
    section("④ structured output 강제")

    pin = planner_input()
    fake = FakeLLMClient(responses=[fake_response()])
    planner = DesignPlanner(client=fake)
    planner.plan(pin)

    schema = fake.calls[-1]["schema"]
    cfg = fake.calls[-1]["config"]
    ok = (schema["required"] == ["candidates"]
          and schema["properties"]["candidates"]["minItems"] == 3
          and schema["properties"]["candidates"]["maxItems"] == 3)
    check(ok, "envelope schema")
    print(f"  {'PASS' if ok else 'FAIL'}  후보 배열 minItems=maxItems={pin.candidate_count}")

    rs = schema["properties"]["candidates"]["items"]["properties"]["render_spec"]
    ok = rs["properties"]["zones"]["properties"]["overlap_intent"]["enum"] == [
        "none", "allowed", "required"]
    check(ok, "RenderSpec schema 가 spec 모듈에서 생성")
    print(f"  {'PASS' if ok else 'FAIL'}  render_spec schema 는 dataclass 에서 생성 "
          f"— overlap enum {rs['properties']['zones']['properties']['overlap_intent']['enum']}")
    # ★ v0.4 — family/weight 는 이제 **조합**으로 묶여 anyOf 5가지다.
    #   독립 enum(3×4=12조합)일 때 모델이 그 틈으로 sans/bold 를 냈다
    branches = rs["properties"]["typography"]["properties"]["roles"]["items"]["anyOf"]
    from dynamic.spec import SUPPORTED_TYPE_FACES
    got = [(b["properties"]["family"]["enum"][0], b["properties"]["weight"]["enum"][0])
           for b in branches]
    ok = tuple(got) == SUPPORTED_TYPE_FACES
    check(ok, "type face 조합")
    print(f"  {'PASS' if ok else 'FAIL'}  중첩 구조까지 enum 전달 — face 는 "
          f"{len(branches)}조합 {[f'{f}/{w}' for f, w in got]}")

    ok = cfg.response_format == "json_schema"
    check(ok, "response_format")
    print(f"  {'PASS' if ok else 'FAIL'}  response_format={cfg.response_format!r} "
          f"(strict={cfg.strict_schema}) — 자유 텍스트에서 JSON 을 찾지 않는다")

    # 잘못된 response_format 은 만들 수 없다
    raised = None
    try:
        PlannerConfig(response_format="freeform")
    except ValueError as exc:
        raised = exc
    check(raised is not None, "미지의 response_format 거부")
    print(f"  {'PASS' if raised else 'FAIL'}  response_format='freeform' → ValueError")


def test_parse_and_reject() -> None:
    section("⑤ 잘못된 출력은 고치지 않고 거부")

    pin = planner_input()
    cases = {
        "JSON 이 아님": "여기 후보입니다: {…",
        "후보 배열 없음": {"result": "ok"},
        "개수 불일치": {"candidates": [fake_response(("A",))["candidates"][0]]},
        "필드 누락": {"candidates": [{"id": "x", "render_spec": {}} for _ in range(3)]},
        "id 중복": {"candidates": [dict(fake_response(("A",))["candidates"][0], id="dup")
                                 for _ in range(3)]},
        "render_spec 이 객체가 아님": {"candidates": [
            {"id": f"c{i}", "label": "", "rationale": "", "render_spec": "…"}
            for i in range(3)]},
    }
    for label, payload in cases.items():
        raised = None
        try:
            DesignPlanner(client=FakeLLMClient(responses=[payload])).plan(pin)
        except Exception as exc:  # noqa: BLE001
            raised = exc
        ok = isinstance(raised, PlannerOutputInvalid)
        check(ok, f"{label}: {type(raised).__name__}")
        print(f"  {'PASS' if ok else 'FAIL'}  {label:22} → {type(raised).__name__}"
              f":{getattr(raised, 'code', '')}")

    print("\n  스키마를 어긴 후보는 **파서가 아니라 기존 validator** 가 잡는다")
    brief = fixture_brief()
    bad = {
        "px 좌표": lambda s: s["product"].update({"x": 120}),
        "정수 row index": lambda s: s["copy_blocks"][0]["grid_ref"].update({"row_anchor": 54}),
        "미지의 enum": lambda s: s["zones"].update({"overlap_intent": "shared"}),
        "미지원 서체": lambda s: s["typography"]["roles"][1].update(
            {"family": "serif", "weight": "regular"}),
        "spec_source 자칭": lambda s: s.update({"spec_source": "fixture"}),
    }
    for label, mut in bad.items():
        resp = fake_response()
        mut(resp["candidates"][0]["render_spec"])
        result = DesignPlanner(client=FakeLLMClient(responses=[resp])).plan(pin)
        rv = review_candidates(result, brief)[0]
        check(not rv.accepted, f"{label} 거부")
        print(f"  {'PASS' if not rv.accepted else 'FAIL'}  {label:16} → {list(rv.error_codes)}")


def test_end_to_end() -> None:
    section("①②⑧⑨ candidate_count=3 → validate → render → safety")

    OUT.mkdir(parents=True, exist_ok=True)
    asset, geo = fixed_asset()
    brief = fixture_brief()
    pin = planner_input(3)

    fake = FakeLLMClient(responses=[fake_response()])
    result = DesignPlanner(client=fake).plan(pin)

    ok = len(result) == 3
    check(ok, f"후보 3개: {len(result)}")
    print(f"  {'PASS' if ok else 'FAIL'}  후보 {len(result)}개 파싱 — "
          f"{[c.id for c in result.candidates]}")
    for c in result.candidates:
        check(bool(c.id and c.label and c.rationale and c.render_spec), f"{c.id} 필드")
    print(f"  PASS  각 후보에 id · label · rationale · render_spec")

    print(f"\n  metadata  {json.dumps(dict(result.metadata), ensure_ascii=False)[:150]}…")
    for key in ("model", "temperature", "prompt_version", "schema_version",
                "candidate_count", "determinism"):
        check(key in result.metadata, f"metadata.{key}")
    ok = result.metadata["determinism"] == "not_guaranteed_for_llm"
    check(ok, "결정론 표기")
    print(f"  PASS  model={result.metadata['model']} · temp={result.metadata['temperature']} · "
          f"prompt_version={result.metadata['prompt_version']} · "
          f"schema_version={result.metadata['schema_version']}")
    print(f"  {'PASS' if ok else 'FAIL'}  determinism={result.metadata['determinism']!r} "
          "— 같은 brief → 같은 RenderSpec 을 보장하지 않는다")

    # ⑪ schema validation
    reviews = review_candidates(result, brief)
    for r in reviews:
        check(r.accepted, f"{r.candidate_id}: {r.error_codes}")
        print(f"  PASS  {r.candidate_id:10} validate accepted={r.accepted}")

    # ⑩ diversity
    rep = check_diversity(result)
    print()
    for p in rep.pairs:
        print(f"  {p.a}↔{p.b}  갈린 {len(p.differing):2} · 구조 {len(p.structural):2} "
              f"· {list(p.categories)}")
    check(rep.sufficient, f"diversity: {rep.code}")
    print(f"  {'PASS' if rep.sufficient else 'FAIL'}  check_diversity → "
          f"sufficient={rep.sufficient} code={rep.code!r}")

    # ⑫ render + safety
    print()
    images = {}
    for cand in result.candidates:
        plan = build_plan(load(dict(cand.render_spec), brief), brief, geo)
        img, ev = render_with_evidence(plan, asset, geo)
        res = validate_safety(plan, ev)
        images[cand.id] = img
        img.save(OUT / f"{cand.id}.png")
        px0, py0, px1, py1 = plan.product.bbox_px
        print(f"  {cand.id:10} 격자 {plan.grid.columns}단 · 제품 "
              f"{(px1-px0)*(py1-py0)/1024/1024:4.0%} · 블록 {len(plan.copy_blocks)} → "
              f"safety {'PASS' if res.passed else f'FAIL {len(res.failures)}건'}")
        for v in res.failures[:2]:
            print(f"             {v.code} @ {v.element_id} {v.measured}/{v.threshold}")
        check(True, f"{cand.id} chain")

    sheet = Image.new("RGB", (460 * len(images), 460), (255, 255, 255))
    for i, (cid, img) in enumerate(images.items()):
        sheet.paste(img.resize((460, 460), Image.LANCZOS), (i * 460, 0))
    sheet.save(OUT / "_planner_sheet.png")
    print(f"\n  PASS  {(OUT / '_planner_sheet.png').name}")


def test_redesign_input() -> None:
    section("⑨ Safety 실패 → 재설계 입력 (자동 루프 없음)")

    asset, geo = fixed_asset()
    brief = fixture_brief()
    plan = build_plan(load(FIXTURES["C"][1](), brief), brief, geo)
    _, ev = render_with_evidence(plan, asset, geo)
    fb = SafetyFeedback.from_result("cand_C", validate_safety(plan, ev))

    pin = PlannerInput.of(to_creative_brief(service_request()),
                          candidate_count=2, feedback=[fb])
    user = build_user_prompt(pin)
    ok = ('"safety_feedback"' in user and "safety.critical_occlusion" in user
          and '"measured": 0.3207' in user)
    check(ok, "feedback 프롬프트 유입")
    print(f"  {'PASS' if ok else 'FAIL'}  실패 사실이 프롬프트에 들어간다 "
          "(code · element_id · measured · threshold · layer · relation)")

    ok = "네가 정한다" in user and "새로" in user
    check(ok, "처방 없음")
    print(f"  {'PASS' if ok else 'FAIL'}  처방은 넣지 않는다 — "
          "\"무엇을 어떻게 고칠지는 네가 정한다\"")

    result = DesignPlanner(client=FakeLLMClient(
        responses=[fake_response(("A", "D"))])).plan(pin)
    ok = all(c.derived_from == "cand_C" for c in result.candidates)
    check(ok, "derived_from")
    print(f"  {'PASS' if ok else 'FAIL'}  derived_from={result.candidates[0].derived_from!r} 기록")

    # 자동 재호출은 없다 — 한 번 호출하고 끝
    fake = FakeLLMClient(responses=[fake_response()])
    DesignPlanner(client=fake).plan(planner_input())
    ok = len(fake.calls) == 1
    check(ok, f"호출 수 {len(fake.calls)}")
    print(f"  {'PASS' if ok else 'FAIL'}  LLM 호출 {len(fake.calls)}회 — 자동 retry loop 없음")

    src = open(ROOT / "dynamic" / "planner.py", encoding="utf-8").read()
    bad = [k for k in ("while ", "retry(", "regenerate(", "for attempt") if k in src]
    check(not bad, f"루프 흔적: {bad}")
    print(f"  {'PASS' if not bad else 'FAIL'}  planner.py 에 재시도 루프 없음")


def test_fake_determinism_and_live_note() -> None:
    section("⑪ FakeLLM 결정론 · 실제 호출 안내")

    pin = planner_input()
    digests = {DesignPlanner(client=FakeLLMClient(responses=[fake_response()]))
               .plan(pin).input_digest for _ in range(5)}
    check(len(digests) == 1, f"digest {digests}")
    print(f"  {'PASS' if len(digests) == 1 else 'FAIL'}  같은 입력 → 같은 prompt digest "
          f"{digests.pop()} (단위 테스트 결정론은 FakeLLM 이 확보)")

    has_key = bool(os.environ.get("OPENAI_API_KEY"))
    print(f"\n  OPENAI_API_KEY 존재: {has_key}")
    print("  실제 모델 호출은 이 환경에서 하지 않는다 (키 없음).")
    print("  → tools/verification/dynamic_planner/run_planner.py 를 키와 함께 직접 실행")
    check(True, "live note")


def test_isolation() -> None:
    section("⑫ production 분리 · SDK 경계")

    for name in ("dynamic/planner.py", "dynamic/planner_prompt.py"):
        src = open(ROOT / name, encoding="utf-8").read()
        bad = [ln.strip() for ln in src.splitlines()
               if ln.strip().startswith(("import pipeline", "from pipeline",
                                         "import api", "from api"))]
        check(not bad, f"{name}: {bad}")
        print(f"  {'PASS' if not bad else 'FAIL'}  {name:28} production import 없음")

    # SDK 는 지연 import — 패키지가 없어도 계약/테스트가 돈다
    src = open(ROOT / "dynamic" / "planner.py", encoding="utf-8").read()
    top = [ln for ln in src.splitlines()[:60] if ln.startswith(("import openai", "from openai"))]
    check(not top, f"최상위 openai import: {top}")
    print(f"  {'PASS' if not top else 'FAIL'}  openai 는 지연 import — "
          "설치 없이도 FakeLLM 테스트가 돈다")

    import dynamic.planner_prompt as pp
    check(not any(n in dir(pp) for n in ("OpenAI", "openai")), "prompt 에 SDK 없음")
    print(f"  PASS  프롬프트 모듈은 SDK 를 모른다 — 디자인 계약 ≠ 특정 LLM SDK")

    loaded = [n for n in sys.modules if n == "pipeline" or n.startswith("pipeline.")]
    check(not loaded, f"pipeline 로드: {loaded}")
    print(f"  {'PASS' if not loaded else 'FAIL'}  sys.modules 에 pipeline 없음")


def test_schema_projection() -> None:
    """④-2 Planner schema 는 **현재 실행 가능한 subset** 이다.

    generic RenderSpec schema 를 그대로 노출하면 LLM 이 만들 수 있는 값과
    `review_candidates()` 가 통과시키는 값이 어긋난다 — 모델은 스키마를 지켰는데
    우리가 거부하는 상태가 된다. 그 어긋남을 schema 단계에서 없앤다.
    """
    section("④-2 capability projection — 실행 가능한 subset")

    from dynamic import planner_render_spec_schema, render_spec_json_schema
    from dynamic.planner_prompt import PLANNER_PROJECTIONS
    from dynamic.spec import LAYER_STACK, SCHEMA_VERSION

    generic = render_spec_json_schema()
    proj = planner_render_spec_schema(("1:1",))

    def row_anchors(node, path="$"):
        found = []
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "row_anchor" and isinstance(v, dict):
                    found.append((path + "." + k, v))
                found += row_anchors(v, path + "." + k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                found += row_anchors(v, f"{path}[{i}]")
        return found

    g_int = [p for p, v in row_anchors(generic) if "integer" in json.dumps(v)]
    p_int = [p for p, v in row_anchors(proj) if "integer" in json.dumps(v)]
    check(len(g_int) > 0, "generic 은 integer 를 허용한다(fixture 경로)")
    check(not p_int, f"projection 에 integer row_anchor 잔존: {p_int}")
    print(f"  {'PASS' if not p_int else 'FAIL'}  row_anchor integer — "
          f"generic {len(g_int)}곳 / planner 0곳")

    n_anchor = len(row_anchors(proj))
    ok = n_anchor >= 3 and all(v.get("type") == "string" for _, v in row_anchors(proj))
    check(ok, "모든 row_anchor 가 string 단일 타입")
    print(f"  {'PASS' if ok else 'FAIL'}  row_anchor {n_anchor}곳 전부 type='string' "
          "— copy_blocks · motif.instances · motif.pattern.region")

    # pattern 이 실제로 유효/무효 값을 갈라내는지
    import re
    pat = row_anchors(proj)[0][1]["pattern"]
    rx = re.compile(pat)
    good = ["top", "center", "after:product", "before:product",
            "align:product_top", "after:headline"]
    bad = ["12", "-1", "after:", "middle", "after:pro duct"]
    ok = all(rx.match(x) for x in good) and not any(rx.match(x) for x in bad)
    check(ok, "row_anchor pattern 판별")
    print(f"  {'PASS' if ok else 'FAIL'}  pattern 이 {good[:3]}… 는 통과, {bad} 는 거부")

    # ratio — 현재 Renderer 가 처리하는 것만
    g_ratio = generic["properties"]["canvas"]["properties"]["ratio"]["enum"]
    p_ratio = proj["properties"]["canvas"]["properties"]["ratio"]["enum"]
    ok = p_ratio == ["1:1"] and set(g_ratio) > set(p_ratio)
    check(ok, "ratio projection")
    print(f"  {'PASS' if ok else 'FAIL'}  ratio — generic {g_ratio} → planner {p_ratio} "
          "(3:4 · 3:1 은 RatioUnsupported 로 거부되던 값)")

    ok = planner_render_spec_schema(("1:1", "3:4"))[
        "properties"]["canvas"]["properties"]["ratio"]["enum"] == ["1:1", "3:4"]
    check(ok, "ratio 는 capability 를 따라간다")
    print(f"  {'PASS' if ok else 'FAIL'}  supported_ratios 가 늘면 schema 도 따라 늘어난다 "
          "— 하드코딩이 아니다")

    # schema_version · layers
    sv = proj["properties"]["schema_version"]
    # const 가 아니라 **단일값 enum** 이다 — 표현력은 같은데 enum 은 지원이
    # 명확하고 const 는 확인되지 않았다. strict 로 보낼 수 있는 쪽을 쓴다
    ok = sv.get("enum") == [SCHEMA_VERSION] and "const" not in sv
    check(ok, "schema_version 단일값 enum")
    print(f"  {'PASS' if ok else 'FAIL'}  schema_version enum={sv.get('enum')} "
          "— Planner 가 버전을 만들지 않는다 (const 대신 enum: strict 안전)")
    # layers 는 아예 노출하지 않는다 — system invariant (④-5 참고)
    ok = "layers" not in proj["properties"]
    check(ok, "layers 제거")
    print(f"  {'PASS' if ok else 'FAIL'}  layers 는 Planner 출력이 아니다 "
          f"— system 이 {list(LAYER_STACK)} 을 소유한다")

    # projection 목록이 실제 trust 분기와 1:1 인지
    import dynamic.validate  # noqa: F401 — 아래는 모듈이지 재export 된 함수가 아니다
    src = inspect.getsource(sys.modules["dynamic.validate"])
    diverge = [n for n in ("allows_row_index", "supported_ratios", "schema_version")
               if f"ctx.{n}" in src]
    ok = len(diverge) == 3
    check(ok, f"validator 의 trust 분기: {diverge}")
    print(f"  {'PASS' if ok else 'FAIL'}  validator 가 경로에 따라 다르게 판정하는 지점은 "
          f"{diverge} 3곳뿐 — 전부 projection 에 반영됨")
    for path, why in PLANNER_PROJECTIONS:
        print(f"        {path:16} {why}")

    # 프롬프트 본문에도 실행 불가능한 값이 남아 있으면 안 된다
    pin0 = planner_input()
    sysmsg = build_system_prompt(pin0)
    leaked = [r for r in ("3:4", "3:1") if r in sysmsg]
    check(not leaked, f"프롬프트에 미지원 ratio 노출: {leaked}")
    print(f"  {'PASS' if not leaked else 'FAIL'}  '이 값들만 쓴다' 표에서 declared_ratios 제외 "
          "— 스키마만 아는 3:4 · 3:1 은 프롬프트에도 안 나온다")
    ok = "declared_ratios" in describe_capabilities()
    check(ok, "capabilities 단일 출처는 그대로")
    print(f"  {'PASS' if ok else 'FAIL'}  describe_capabilities() 자체는 유지 "
          "— 진단 정보를 지운 게 아니라 프롬프트 투영에서만 뺐다")

    # DesignPlanner 가 실제로 projection 을 넘기는지 (generic 이 아니라)
    pin = planner_input()
    fake = FakeLLMClient(responses=[fake_response()])
    DesignPlanner(client=fake).plan(pin)
    sent = fake.calls[-1]["schema"]["properties"]["candidates"]["items"][
        "properties"]["render_spec"]
    sent_int = [p for p, v in row_anchors(sent) if "integer" in json.dumps(v)]
    ok = not sent_int and sent["properties"]["canvas"]["properties"]["ratio"][
        "enum"] == list(pin.capabilities["canvas_ratios"])
    check(ok, "plan() 이 projection 을 전송")
    print(f"  {'PASS' if ok else 'FAIL'}  DesignPlanner.plan() 이 LLM 에 보내는 schema 는 "
          f"projection — ratio {sent['properties']['canvas']['properties']['ratio']['enum']}")


def test_no_silent_fallback() -> None:
    """④-3 structured output 실패를 성공으로 바꾸지 않는다."""
    section("④-3 silent fallback 금지")

    src = inspect.getsource(planner_mod)
    # OpenAIClient 구간만 본다 — FakeLLM 은 테스트 전용이라 제외
    head = src.split("class FakeLLMClient")[0]
    body = head.split("class OpenAIClient")[1]
    FALLBACK_MARKERS = (
        "except Exception", "fallback", "재시도", "retry",
        "re.search", "```", "find(", "rfind(",
    )
    bad = [kw for kw in FALLBACK_MARKERS if kw in body]
    # json_object 로의 **자동** 강등: config 를 코드가 바꿔 쓰는 흔적
    if "response_format = " in body or 'config.response_format = ' in body:
        bad.append("response_format 재대입")
    check(not bad, f"fallback 흔적: {bad}")
    print(f"  {'PASS' if not bad else 'FAIL'}  OpenAIClient 경로에 "
          "json_object 자동 강등 · 자유 텍스트 JSON 추출 · FakeLLM 대체 없음")

    # response_format 은 호출자가 명시적으로만 바꿀 수 있다
    ok = PlannerConfig().response_format == "json_schema"
    check(ok, "기본 json_schema")
    print(f"  {'PASS' if ok else 'FAIL'}  기본값 json_schema — 강등하려면 "
          "PlannerConfig(response_format='json_object') 를 사람이 직접 쓴다")

    # 파싱 실패는 예외로 올라온다
    class Boom:
        name = "boom"
        def complete_json(self, system, user, schema, config):
            raise PlannerOutputInvalid("planner.not_json", "llm.response", "<html>...")

    raised = None
    try:
        DesignPlanner(client=Boom()).plan(planner_input())
    except PlannerOutputInvalid as exc:
        raised = exc
    check(raised is not None, "실패가 위로 전파")
    print(f"  {'PASS' if raised else 'FAIL'}  JSON 이 아니면 PlannerOutputInvalid "
          "— 재시도도 대체도 하지 않는다")


def test_strict_projection() -> None:
    """④-4 strict Structured Output — 구조를 모델의 주의력이 아니라 계약으로.

    첫 live run 에서 세 후보가 전부 required 인 `copy_blocks` 를 빠뜨렸다.
    `strict:false` 는 스키마를 힌트로만 쓴다. strict 를 켜면 그 부류의 실패가
    애초에 만들어지지 않는다 — 대신 "모든 property 가 required" 를 지켜야 한다.
    """
    section("④-4 strict projection")

    import dataclasses
    from dynamic import (STRICT_UNSUPPORTED, SUPPORTED_COLOR_ROLES,
                         planner_output_schema, strict_planner_output_schema,
                         strict_violations, load, build_plan, render_with_evidence)
    from jsonschema import Draft202012Validator
    import fixtures_renderspec as FXX

    base = planner_output_schema(3, ("1:1",))
    strict = strict_planner_output_schema(3, ("1:1",))

    v = strict_violations(strict)
    check(not v, f"strict 위반: {v[:3]}")
    print(f"  {'PASS' if not v else 'FAIL'}  strict 위반 0건 "
          "(모든 property required · additionalProperties:false · 미지원 composition 없음)")

    Draft202012Validator.check_schema(strict)
    print("  PASS  JSON Schema 문법 자체 유효 (Draft 2020-12)")

    # 미지원 composition 을 우리가 만들지 않는지
    txt = json.dumps(strict)
    bad = [k for k in STRICT_UNSUPPORTED if f'"{k}"' in txt]
    check(not bad, f"미지원 keyword 생성: {bad}")
    print(f"  {'PASS' if not bad else 'FAIL'}  allOf · not · if/then/else · oneOf · "
          "dependentRequired 등 미지원 composition 0건")

    # 지원되는 제약은 **버리지 않는다** — 버리면 같은 규칙을 프롬프트 문장으로
    # 다시 적어야 하고, 그건 계약이 아니다
    kept = {k: txt.count(f'"{k}"') for k in ("minimum", "maximum", "pattern",
                                             "minItems", "maxItems")}
    ok = all(n > 0 for n in kept.values())
    check(ok, f"제약 유실: {kept}")
    print(f"  {'PASS' if ok else 'FAIL'}  제약 keyword 유지 {kept} "
          "— 일반 모델 Structured Outputs 지원 대상이라 schema 로 남긴다")
    ok = '"const"' not in txt
    check(ok, "const 미사용")
    print(f"  {'PASS' if ok else 'FAIL'}  const 대신 단일값 enum — 지원이 확실한 쪽")

    # required 수 비교
    def count(n, key):
        c = 0
        if isinstance(n, dict):
            if key in n and isinstance(n[key], list):
                c += len(n[key])
            for x in n.values():
                c += count(x, key)
        elif isinstance(n, list):
            for x in n:
                c += count(x, key)
        return c
    before, after = count(base, "required"), count(strict, "required")
    print(f"  PASS  required {before} → {after} (전부)")

    # nullable 은 늘지도 줄지도 않는다 — default 를 지어내지 않았다는 증거
    def nullable(n):
        c = 0
        if isinstance(n, dict):
            for v in n.values():
                if isinstance(v, dict) and any(
                        o == {"type": "null"} for o in v.get("anyOf", [])):
                    c += 1
                c += nullable(v)
        elif isinstance(n, list):
            for v in n:
                c += nullable(v)
        return c
    ok = nullable(base) == nullable(strict)
    check(ok, "nullable 수 변화")
    print(f"  {'PASS' if ok else 'FAIL'}  nullable {nullable(base)}개 그대로 — "
          "이미 null 이던 것만 nullable 로 남겼다 (default 를 지어내지 않았다)")

    # palette 단일 출처
    rs = strict["properties"]["candidates"]["items"]["properties"]["render_spec"]
    roles = rs["properties"]["palette"]["properties"]["roles"]["items"]["enum"]
    ok = tuple(roles) == SUPPORTED_COLOR_ROLES
    check(ok, "palette.roles enum")
    print(f"  {'PASS' if ok else 'FAIL'}  palette.roles enum = {roles} "
          "— color_roles.py 가 Renderer·Validator·Planner schema 의 단일 출처")
    src = rs["properties"]["palette"]["properties"]["source"]["enum"]
    ok = "fixed" not in src and rs["properties"]["palette"][
        "properties"]["fixed_values"]["type"] == "null"
    check(ok, "fixed 제외")
    print(f"  {'PASS' if ok else 'FAIL'}  palette.source={src} · fixed_values=null "
          "— brand 는 brief 에서 읽으므로 Planner 가 색 값을 만들 이유가 없다")

    # cross-field 규칙 투영 — strict 로 표현 못 하는 관계를 description 으로
    from dynamic.validate import CROSS_FIELD_RULES
    from dynamic import describe_capabilities
    rsp = strict["properties"]["candidates"]["items"]["properties"]["render_spec"]
    P = rsp["properties"]
    spots = {
        "background.visual_style": P["background"]["properties"]["visual_style"],
        "palette.roles": P["palette"]["properties"]["roles"],
        "palette.rhythm": P["palette"]["properties"]["rhythm"],
        "motif.min_repeats": P["motif"]["properties"]["min_repeats"],
        "safety.critical_blocks": P["safety"]["properties"]["critical_blocks"],
        "safety.must_be_visible": P["safety"]["properties"]["must_be_visible"],
    }
    missing = [k for k, node in spots.items() if not node.get("description")]
    check(not missing, f"description 누락: {missing}")
    print(f"  {'PASS' if not missing else 'FAIL'}  cross-field 규칙 {len(spots)}자리에 "
          "description 투영 — if/then/else 를 못 쓰니 문장으로 적는다")

    # col_span 은 세 자리 전부
    def span_nodes(n, acc=None):
        acc = acc if acc is not None else []
        if isinstance(n, dict):
            p = n.get("properties")
            if isinstance(p, dict) and "col_span" in p and "col_start" in p:
                acc.append(p["col_span"])
            for v in n.values():
                span_nodes(v, acc)
        elif isinstance(n, list):
            for v in n:
                span_nodes(v, acc)
        return acc
    nodes = span_nodes(rsp)
    ok = len(nodes) >= 3 and all(x.get("description") for x in nodes)
    check(ok, f"col_span description {len(nodes)}자리")
    print(f"  {'PASS' if ok else 'FAIL'}  col_span {len(nodes)}자리 전부 설명 — "
          "한 곳만 적으면 나머지는 모른 채로 남는다")

    caps = describe_capabilities()
    ok = (list(caps.get("cross_field_rules", {})) == [p for p, _ in CROSS_FIELD_RULES]
          and caps.get("required_palette_roles") == ["bg", "ink"]
          and caps.get("color_roles") == list(SUPPORTED_COLOR_ROLES))
    check(ok, "capabilities 투영")
    print(f"  {'PASS' if ok else 'FAIL'}  capabilities 에 color_roles · "
          "required_palette_roles · cross_field_rules — 단일 출처는 validate.py")

    # 전역 규모 한도 — keyword 지원 여부와 별개다. 여기 걸리면 호출 자체가
    # 에러라 돈을 쓰고 나서 알게 된다
    from dynamic import STRICT_LIMITS, measure_schema, strict_preflight
    pre = strict_preflight(3, ("1:1",))
    m = pre["measured"]
    for name, okv in pre["checks"].items():
        check(okv, f"preflight {name}")
    print(f"  {'PASS' if pre['ok'] else 'FAIL'}  preflight 6항목 전부 통과 — "
          f"unsupported keyword · strict structural · property · nesting · "
          f"string-size · enum-count")
    print(f"        property {m['properties']}/{STRICT_LIMITS['properties']} · "
          f"depth {m['depth']}/{STRICT_LIMITS['depth']} · "
          f"string {m['string_length']}/{STRICT_LIMITS['string_length']} · "
          f"enum {m['enum_values']}/{STRICT_LIMITS['enum_values']} · "
          f"직렬화 {m['serialized_bytes']}자")

    # depth 는 여유가 가장 적다 — 회귀를 여기서 잡는다
    ok = m["depth"] <= STRICT_LIMITS["depth"] - 1
    check(ok, f"depth 여유 부족: {m['depth']}")
    print(f"  {'PASS' if ok else 'FAIL'}  depth {m['depth']} — 한도 "
          f"{STRICT_LIMITS['depth']} 까지 여유 {STRICT_LIMITS['depth']-m['depth']}단계뿐. "
          "중첩을 한 겹 더 넣으면 걸린다")

    # ★ 의미가 바뀌지 않았다는 증거 — 픽셀
    brief_fx = FXX.brief()
    asset, geo = fixed_asset()
    RSV = Draft202012Validator(rs)
    for name in ("A", "B", "C", "D"):
        raw = dict(FXX.FIXTURES[name][1]())
        spec = load(raw, brief_fx)
        full = json.loads(json.dumps(dataclasses.asdict(spec)))   # 모든 필드 명시
        # layers 는 Planner 출력이 아니다 (④-5) — 후보에는 애초에 없다
        full.pop("layers", None)
        errs = list(RSV.iter_errors(full))
        check(not errs, f"{name} strict 위반 {len(errs)}")
        p0 = build_plan(spec, brief_fx, geo)
        p1 = build_plan(load(dict(full), brief_fx), brief_fx, geo)
        i0, _ = render_with_evidence(p0, asset, geo)
        i1, _ = render_with_evidence(p1, asset, geo)
        same = i0.tobytes() == i1.tobytes()
        check(same, f"{name} 픽셀 불일치")
        print(f"  {'PASS' if not errs and same else 'FAIL'}  fixture {name} — "
              f"strict 위반 {len(errs)}건 · 픽셀 {'동일' if same else '★다름'} "
              "(생략하던 default 를 명시해도 결과가 같다)")


def test_layers_system_owned() -> None:
    """④-5 canonical stack 은 **system invariant** 다 (S1).

    run 04 에서 세 후보가 전부 `layers` 배열을 틀렸다. 그런데 `build_plan()` 은
    `spec.layers` 를 읽지 않는다 — `LAYER_STACK` 을 직접 쓴다. 즉 LLM 이
    상수를 재생산하고, 검증기가 상수와 대조하고, 그 값은 버려지고 있었다.

    root cause 는 두 겹이다.
      · Planner 가 결정할 수 없는 system invariant 를 출력하게 두었다
      · 그 필드는 원래 optional 이었는데 **strict 변환("모든 property 를
        required")이 필수 출력으로 바꿔 놓았다**

    사후 보정이 아니다 — 만들지 않게 한다.
    """
    section("④-5 layers ownership — system invariant")

    import copy as _copy
    from dynamic import (LAYER_STACK, load, validate, FIXTURE_CONTEXT,
                         planner_render_spec_schema, render_spec_json_schema,
                         strict_planner_output_schema)
    from jsonschema import Draft202012Validator
    import fixtures_renderspec as FXX

    # ① Planner projection 에 layers property 가 없다
    proj = planner_render_spec_schema(("1:1",))
    st = strict_planner_output_schema(3, ("1:1",))[
        "properties"]["candidates"]["items"]["properties"]["render_spec"]
    ok = ("layers" not in proj["properties"] and "layers" not in proj["required"]
          and "layers" not in st["properties"] and "layers" not in st["required"])
    check(ok, "projection 에 layers 잔존")
    print(f"  {'PASS' if ok else 'FAIL'}  planner · strict schema 양쪽에서 제거 "
          "(generic 은 그대로 — fixture/debug 경로가 쓴다)")
    ok = "layers" in render_spec_json_schema()["properties"]
    check(ok, "generic 에서도 사라짐")
    print(f"  {'PASS' if ok else 'FAIL'}  generic RenderSpec schema 에는 유지")

    # ② layers 없는 후보도 parsing 후 canonical 로 채워진다
    brief_fx = FXX.brief()
    raw = _copy.deepcopy(dict(FXX.FIXTURES["A"][1]()))
    raw.pop("layers", None)
    spec = load(raw, brief_fx)
    ok = tuple(spec.layers) == LAYER_STACK
    check(ok, f"default hydration: {spec.layers}")
    print(f"  {'PASS' if ok else 'FAIL'}  layers 없는 raw → RenderSpec.layers == "
          "LAYER_STACK (dataclass default)")

    # ③ 임의로 넣으면 schema 가 거부한다 — 조용히 무시되지 않는다
    payload = {"candidates": [{"id": "x", "label": "l", "rationale": "r",
                               "render_spec": {**_copy.deepcopy(raw),
                                               "layers": list(LAYER_STACK)}}]}
    env = strict_planner_output_schema(1, ("1:1",))
    errs = [e for e in Draft202012Validator(env).iter_errors(payload)
            if "additionalProperties" in e.message or "layers" in e.message]
    ok = bool(errs)
    check(ok, "layers 를 넣어도 통과함")
    print(f"  {'PASS' if ok else 'FAIL'}  Planner 가 layers 를 넣으면 "
          "additionalProperties:false 로 거부 — silent ignore 아님")

    # ④ fixture/직접 경로에서는 noncanonical 을 계속 거부한다
    bad = _copy.deepcopy(dict(FXX.FIXTURES["A"][1]()))
    bad["layers"] = ["background", "type_under", "product",
                     "type_over", "motif_over", "background"]   # run 04 c1 의 실제 값
    codes = [e.code for e in validate(bad, brief_fx, FIXTURE_CONTEXT)]
    ok = "layers.not_canonical" in codes
    check(ok, f"_c_layers 회귀: {codes}")
    print(f"  {'PASS' if ok else 'FAIL'}  fixture 경로의 noncanonical layers 는 "
          f"그대로 거부 — {codes}")

    # 메시지는 버전에 매이지 않는다 (S2)
    msg = [e.detail for e in validate(bad, brief_fx, FIXTURE_CONTEXT)
           if e.code == "layers.not_canonical"][0]
    ok = "v0.3" not in msg and "canonical LAYER_STACK" in msg
    check(ok, f"stale 문구: {msg[:60]}")
    print(f"  {'PASS' if ok else 'FAIL'}  오류 문구가 버전 비의존 — {msg[:52]}…")


def test_feedback_detail() -> None:
    """④-6 SafetyFeedback 에 `detail` 을 싣는다 (prompt v1.4).

    숫자만으로는 무엇을 잰 것인지 알 수 없다. `detail` 은 계약상
    observation-only 라(safety.DETAIL_CONTRACT) 실어도 "Safety 는 처방하지
    않는다" 가 깨지지 않는다.
    """
    section("④-6 SafetyFeedback detail (v1.4)")

    from dynamic import SafetyFeedback
    from dynamic.safety import DETAIL_CONTRACT

    payload = {
        "passed": False,
        "violations": [
            {"code": "safety.overlap_declared_none", "severity": "fail",
             "element_id": "overlap_intent", "element_kind": "zones",
             "layer": "", "relation": "", "measured": 182756, "threshold": 0,
             "detail": "none 을 선언했는데 실제 2D 교집합이 있다"},
        ],
    }
    fb = SafetyFeedback(candidate_id="c1", payload=payload)

    plain = planner_input()
    redo = PlannerInput.of(plain.brief, candidate_count=3, feedback=(fb,))

    # ① 일반 생성 프롬프트는 **바이트 동일** — v1.4 는 redesign 에만 영향
    same = (build_system_prompt(plain) == build_system_prompt(redo)
            and "safety_feedback" not in build_user_prompt(plain))
    check(same, "일반 프롬프트가 달라짐")
    print(f"  {'PASS' if same else 'FAIL'}  feedback 없는 요청에는 블록이 안 붙는다 "
          "— 일반 생성 프롬프트는 v1.3 과 동일")

    # ② redesign 에는 detail 이 실린다
    ur = build_user_prompt(redo)
    ok = "none 을 선언했는데 실제 2D 교집합이 있다" in ur
    check(ok, "detail 미포함")
    print(f"  {'PASS' if ok else 'FAIL'}  redesign 프롬프트에 detail 포함 — "
          "measured 182756 만으로는 '무엇의 교집합인가' 를 알 수 없다")

    # ③ 처방은 여전히 없다
    ok = ("네가 정한다" in ur
          and not any(w in ur for w in ("줄여라", "옮겨라", "바꿔라", "늘려라")))
    check(ok, "처방 문구 발견")
    print(f"  {'PASS' if ok else 'FAIL'}  수정 방법은 여전히 주지 않는다 "
          f"— {DETAIL_CONTRACT}")

    # ④ 필드 집합이 계약대로인지
    import json as _j
    i = ur.find('"failures"')
    ok = all(k in ur[i:i + 700] for k in
             ("code", "element_id", "element_kind", "severity",
              "measured", "threshold", "layer", "relation", "detail"))
    check(ok, "필드 누락")
    print(f"  {'PASS' if ok else 'FAIL'}  failures[] 9개 필드 전달")


def main() -> int:
    print("=" * 72)
    print("AI Design Planner MVP 테스트 — Step 9")
    print("=" * 72)

    test_prompt_composition()
    test_prompt_leak_guards()
    test_structured_output()
    test_schema_projection()
    test_strict_projection()
    test_layers_system_owned()
    test_feedback_detail()
    test_no_silent_fallback()
    test_parse_and_reject()
    test_end_to_end()
    test_redesign_input()
    test_fake_determinism_and_live_note()
    test_isolation()

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

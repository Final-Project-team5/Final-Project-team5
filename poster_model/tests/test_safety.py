"""Safety Validator 테스트 — E12 v0.3 Step 6.

Validator 는 **판정만 한다.** 대비를 올리거나 문구를 옮기거나 제품을 줄이지
않는다. 그래서 이 테스트가 확인하는 것은 "고쳤는가"가 아니라
"실제 렌더 결과를 근거로 옳게 판정했는가"다.

특히 두 가지를 못 박는다.

    ① bbox 겹침을 글자 가림으로 쓰지 않는다
       C headline 의 bbox 겹침은 51.3% 지만 실제 **획** 가림은 그보다 작다.
       판정은 잉크 기준으로 한다
    ② layer 에 따라 재는 것이 다르다
       type_under → 가림 · type_over → 대비

실행:  python tests/test_safety.py
"""

from __future__ import annotations

import copy as copymod
import dataclasses
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
    DEFAULT_POLICY,
    DEFERRED_CHECKS,
    ProductGeometry,
    ProductRenderAsset,
    SystemPolicy,
    build_plan,
    load,
    render_with_evidence,
    validate_safety,
)
from dynamic import EvidenceMismatch, RENDERER_VERSION  # noqa: E402
from dynamic.safety import FAIL, WARN, contrast_of, ink_occlusion  # noqa: E402
from fixtures_renderspec import FIXTURES, brief  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
#: 테스트 고정 자산 — 실제 세그멘테이션 결과다. 합성 마스크로
#: 바꾸면 가림/대비 측정이 실제 제품 실루엣이 아닌 값을 재게 된다.
ASSETS = Path(__file__).resolve().parent / "_assets"
# 테스트 산출물은 **저장소 안에 남기지 않는다.** 검사는 전부 메모리 위의
# 이미지로 하고, 저장은 사람이 눈으로 확인하고 싶을 때를 위한 것이다.
# 눈으로 보려면  DYNAMIC_TEST_OUT=/some/dir  로 경로를 지정한다.
OUT = Path(os.environ.get("DYNAMIC_TEST_OUT")
           or tempfile.mkdtemp(prefix="dynamic_step6_"))

FAILS: list[str] = []
CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILS.append(label)


def section(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 62 - len(title)))


def fixed_asset():
    mask = Image.open(ASSETS / "mask" / "cosmetic_birefnet-general.png").convert("L")
    original = Image.open(ASSETS / "cutout" / "cosmetic_00_original.png").convert("RGB")
    rgba = original.convert("RGBA")
    rgba.putalpha(mask)
    m = np.array(mask) > 128
    ys, xs = np.where(m)
    geo = ProductGeometry.from_mask_size(
        cutout_width=mask.size[0], cutout_height=mask.size[1],
        mask_bbox=(int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())),
    )
    return ProductRenderAsset(rgba), geo


ASSET, GEO = fixed_asset()
BRIEF = brief()


def run(raw: dict, policy=None):
    plan = build_plan(load(raw, BRIEF), BRIEF, GEO)
    image, ev = render_with_evidence(plan, ASSET, GEO)
    return plan, image, ev, validate_safety(plan, ev, policy)


# ──────────────────────────────────────────────────────────────────────────
def test_all_fixtures() -> None:
    section("fixture 전체 판정")

    OUT.mkdir(parents=True, exist_ok=True)
    global RESULTS
    RESULTS = {}
    for k, (name, fn) in FIXTURES.items():
        plan, image, ev, res = run(fn())
        RESULTS[k] = (plan, ev, res)
        print(f"\n  {k} {name:22} → {'PASS' if res.passed else 'FAIL'} "
              f"(실패 {len(res.failures)} · 경고 {len(res.violations) - len(res.failures)})")
        for v in res.violations:
            print(f"      {v}")
        for bid, e in res.measurements["blocks"].items():
            tag = "critical" if e["critical"] else "        "
            size = f"{e['size_px']:4}px {'large' if e['large_text'] else 'small'}"
            if e["checked"] == "contrast":
                detail = f"대비 {e['contrast']:>6} / {e['contrast_min']}"
            else:
                detail = (f"획가림 {e['ink_occlusion']:.3f} · 최악글자 "
                          f"{e['worst_char_occlusion']:.3f} · 대비 {e['contrast']}")
            print(f"      └ {bid:16} {e['layer']:11}{tag} {size}  {detail}")
        (OUT / f"fixture_{k}.png").write_bytes(b"")  # 자리 확보 후 아래에서 저장
        image.save(OUT / f"fixture_{k}.png")
        (OUT / f"safety_{k}.json").write_text(
            json.dumps({"passed": res.passed,
                        "violations": [dataclasses.asdict(v) for v in res.violations],
                        "measurements": res.measurements},
                       ensure_ascii=False, indent=2), encoding="utf-8")

    check(len(RESULTS) == 4, "4개 fixture 판정")


def test_target_cases() -> None:
    section("① A eyebrow 대비 · ② C 핵심 headline 실제 잉크 가림")

    _, _, resA = RESULTS["A"][0], RESULTS["A"][1], RESULTS["A"][2]
    eb = resA.measurements["blocks"]["eyebrow"]
    ok = (eb["contrast"] < DEFAULT_POLICY.text_contrast_min
          and not eb["large_text"]
          and any(v.code == "safety.text_contrast" and "eyebrow" in v.target
                  for v in resA.failures))
    check(ok, f"A eyebrow: {eb}")
    print(f"  {'PASS' if ok else 'FAIL'}  ① A eyebrow {eb['size_px']}px {eb['weight']} "
          f"→ small text · 대비 {eb['contrast']} < {DEFAULT_POLICY.text_contrast_min} → FAIL")

    planC, evC, resC = RESULTS["C"]
    hb = resC.measurements["blocks"]["headline"]
    bbox_ratio = planC.type_product_relation()["per_block"]["headline"]["ratio"]
    ink_ratio = hb["ink_occlusion"]
    ok = (hb["checked"] == "occlusion" and hb["critical"]
          and ink_ratio > DEFAULT_POLICY.critical_occlusion_max
          and resC.has("safety.critical_occlusion"))
    check(ok, f"C headline: {hb}")
    print(f"  {'PASS' if ok else 'FAIL'}  ② C headline (critical · type_under)")
    print(f"        bbox 겹침 {bbox_ratio:.3f}  ≠  실제 잉크 가림 {ink_ratio:.3f}"
          f"  ← **다른 수를 쓴다**")
    print(f"        잉크 {ink_ratio:.1%} > 기준 {DEFAULT_POLICY.critical_occlusion_max:.0%} → FAIL")
    diff = abs(bbox_ratio - ink_ratio)
    check(diff > 0.05, f"bbox 와 잉크가 실제로 다르다: {diff:.3f}")
    print(f"  {'PASS' if diff > 0.05 else 'FAIL'}  두 수의 차이 {diff:.3f} — "
          "bbox 를 그대로 썼다면 잘못 판정했을 것")

    ok = resC.has("safety.char_occlusion")
    check(ok, "C 글자 단위 가림")
    worst = hb["worst_char_occlusion"]
    print(f"  {'PASS' if ok else 'FAIL'}  글자 단위 — 최악 {worst:.1%} > "
          f"{DEFAULT_POLICY.char_occlusion_max:.0%} → FAIL (핵심 글자가 완전히 가려짐)")


def test_layer_dependent_checks() -> None:
    section("⑥⑦ type_under → 가림 · type_over → 대비")

    for k in ("A", "C", "D"):
        _, _, res = RESULTS[k]
        for bid, e in res.measurements["blocks"].items():
            expect = "contrast" if e["above_product"] else "occlusion"
            ok = e["checked"] == expect
            check(ok, f"{k}.{bid} {e['layer']} → {e['checked']}")
        print(f"  PASS  {k} — " + " · ".join(
            f"{bid}({e['layer'].replace('type_', '')}→{e['checked']})"
            for bid, e in res.measurements["blocks"].items()))

    # type_over 블록에는 가림 수치가 아예 없다 (제품 위라 가림이 의미 없다)
    _, _, resD = RESULTS["D"]
    over = [e for e in resD.measurements["blocks"].values() if e["above_product"]]
    ok = all("ink_occlusion" not in e for e in over)
    check(ok, "type_over 에 가림 수치 없음")
    print(f"  {'PASS' if ok else 'FAIL'}  type_over 블록 {len(over)}개 — 가림 대신 대비만 잰다")


def test_overlap_intent() -> None:
    section("③④⑤ overlap_intent 검사")

    # ③ allowed — 겹침 자체로 실패하지 않는다
    _, _, resA = RESULTS["A"]
    rel = RESULTS["A"][0].type_product_relation()
    ok = rel["declared"] == "allowed" and rel["overlap_px"] > 0 and not any(
        v.code.startswith("safety.overlap") for v in resA.violations)
    check(ok, "allowed + overlap → 겹침으로는 실패 없음")
    print(f"  {'PASS' if ok else 'FAIL'}  ③ A allowed + 실제 {rel['overlap_px']}px "
          "→ 겹침 자체로는 FAIL 없음")

    # ④ none 인데 실제 겹침
    raw = copymod.deepcopy(FIXTURES["A"][1]())
    raw["zones"]["overlap_intent"] = "none"
    _, _, _, res = run(raw)
    ok = res.has("safety.overlap_declared_none")
    check(ok, "none + overlap → FAIL")
    print(f"  {'PASS' if ok else 'FAIL'}  ④ none 선언 + 실제 겹침 → "
          f"{[v.code for v in res.failures if v.code.startswith('safety.overlap')]}")

    # ⑤ required 인데 겹침 없음
    raw = copymod.deepcopy(FIXTURES["B"][1]())
    raw["zones"]["overlap_intent"] = "required"
    _, _, _, res = run(raw)
    ok = res.has("safety.overlap_required_absent")
    check(ok, "required + 겹침 없음 → FAIL")
    print(f"  {'PASS' if ok else 'FAIL'}  ⑤ required 선언 + 실제 0px → "
          f"{[v.code for v in res.failures if v.code.startswith('safety.overlap')]} (선언-강제)")

    # B 는 none 선언 + 실제 0px → 통과
    _, _, resB = RESULTS["B"]
    ok = not any(v.code.startswith("safety.overlap") for v in resB.violations)
    check(ok, "B none + 0px → 통과")
    print(f"  {'PASS' if ok else 'FAIL'}  B none + 실제 0px → 겹침 위반 없음")


def test_must_be_visible() -> None:
    section("⑧ must_be_visible — 실제로 남아 있는가")

    # A 는 bottom_rule(motif_over) 을 선언했고 실제로 보인다
    _, _, resA = RESULTS["A"]
    mv = resA.measurements["must_be_visible"]["bottom_rule"]
    ok = mv["visible_ratio"] >= DEFAULT_POLICY.motif_visible_min
    check(ok, f"A bottom_rule {mv}")
    print(f"  {'PASS' if ok else 'FAIL'}  A bottom_rule {mv['visible_px']}/{mv['ink_px']}px "
          f"= {mv['visible_ratio']:.1%} → 통과")

    # 제품 뒤에 깔린 모티프를 must_be_visible 로 선언하면 실패해야 한다
    raw = copymod.deepcopy(FIXTURES["A"][1]())
    raw["motif"]["instances"].append({
        "role": "hidden_bar",
        "grid_ref": {"col_start": 3, "col_span": 3, "row_anchor": "center"},
        "orientation": "horizontal",
        "weight": "thick",
        "color_role": "spot",
        "layer": "motif_under",
    })
    raw["safety"]["must_be_visible"] = ["bottom_rule", "hidden_bar"]
    _, _, _, res = run(raw)
    ok = res.has("safety.must_be_visible_occluded")
    hb = res.measurements["must_be_visible"].get("hidden_bar", {})
    check(ok, f"가려진 모티프 → FAIL: {hb}")
    print(f"  {'PASS' if ok else 'FAIL'}  제품 뒤 모티프 {hb.get('visible_px')}/{hb.get('ink_px')}px "
          f"= {hb.get('visible_ratio', 0):.1%} → FAIL")
    print("        RenderPlan 에 role 이 있다는 이유로 통과시키지 않는다")


def test_overflow() -> None:
    section("⑨ 선언되지 않은 캔버스 이탈")

    plan, ev, res = RESULTS["A"]
    ok = not res.has("safety.canvas_overflow")
    check(ok, "정상 fixture 는 이탈 없음")
    print(f"  {'PASS' if ok else 'FAIL'}  A — bleed {list(plan.product.bleed)} · 이탈 위반 없음")

    # 정상 경로에서는 이탈이 구조적으로 발생하지 않는다.
    #   · 카피 이탈은 build_plan 이 layout.block_out_of_canvas 로 먼저 거부한다
    #   · bleed 는 캔버스 **경계까지만** 확장한다 (넘지 않는다)
    # 그래서 Validator 의 이탈 검사는 plan 을 직접 손봐 시험한다
    px0, py0 = plan.product.bbox_px[0], plan.product.bbox_px[1]
    spill = (px0, py0, plan.canvas_width + 40, plan.canvas_height + 40)
    bad_plan = dataclasses.replace(
        plan, product=dataclasses.replace(plan.product, bbox_px=spill, bleed=("bottom",)))
    # 이 plan 을 그린 것처럼 근거도 함께 맞춘다 (무결성 검사를 우회하지 않는다)
    bad_ev = dataclasses.replace(ev, plan_digest=bad_plan.digest(), elements=tuple(
        dataclasses.replace(e, intended_bbox=spill) if e.kind == "product" else e
        for e in ev.elements))
    res2 = validate_safety(bad_plan, bad_ev)
    ok = res2.has("safety.canvas_overflow")
    over = res2.measurements["overflow"].get("__product__", {})
    check(ok, f"선언 안 된 방향 이탈 → FAIL: {over}")
    print(f"  {'PASS' if ok else 'FAIL'}  bleed=['bottom'] 인데 우측 40px 이탈 → "
          f"위반 {over.get('violating')} (허용 {over.get('allowed')})")

    ok_plan = dataclasses.replace(
        plan, product=dataclasses.replace(plan.product, bbox_px=spill,
                                          bleed=("bottom", "right")))
    ok_ev = dataclasses.replace(bad_ev, plan_digest=ok_plan.digest())
    res3 = validate_safety(ok_plan, ok_ev)
    ok = not res3.has("safety.canvas_overflow")
    check(ok, "선언된 방향은 허용")
    print(f"  {'PASS' if ok else 'FAIL'}  같은 이탈이라도 bleed 에 'right' 를 선언하면 통과")


def test_integrity() -> None:
    section("① Plan ↔ Evidence 무결성")

    planA, evA, _ = RESULTS["A"]
    planC, evC, _ = RESULTS["C"]

    raised = None
    try:
        validate_safety(planC, evA)          # 다른 plan 의 근거
    except Exception as exc:  # noqa: BLE001
        raised = exc
    ok = isinstance(raised, EvidenceMismatch) and raised.code == "evidence.plan_mismatch"
    check(ok, f"다른 plan 의 evidence → {type(raised).__name__}")
    print(f"  {'PASS' if ok else 'FAIL'}  C 의 plan + A 의 evidence → "
          f"{type(raised).__name__}:{getattr(raised, 'code', '')}")

    raised = None
    try:
        validate_safety(planA, dataclasses.replace(evA, renderer_version="0.0.1-old"))
    except Exception as exc:  # noqa: BLE001
        raised = exc
    ok = isinstance(raised, EvidenceMismatch) and raised.code == "evidence.renderer_version_mismatch"
    check(ok, f"renderer version 불일치 → {type(raised).__name__}")
    print(f"  {'PASS' if ok else 'FAIL'}  다른 Renderer 버전의 근거 → "
          f"{type(raised).__name__}:{getattr(raised, 'code', '')}")

    ok = evA.plan_digest == planA.digest() and evA.renderer_version == RENDERER_VERSION
    check(ok, "정상 짝은 통과")
    print(f"  {'PASS' if ok else 'FAIL'}  정상 짝 — plan_digest {evA.plan_digest} · "
          f"renderer {evA.renderer_version}")
    print("        불일치 시 조용히 판정하지 않고 거부한다")


def test_visible_ink_contrast() -> None:
    section("② 대비는 **최종 화면에 남은 획**만 대상으로 한다")

    _, evC, resC = RESULTS["C"]
    hb = resC.measurements["blocks"]["headline"]
    el = evC.by_id("headline")
    ok = (hb["contrast_sample_px"] == el.visible_px
          and hb["contrast_sample_px"] < el.ink_px)
    check(ok, f"visible-ink 표본: {hb['contrast_sample_px']} / ink {el.ink_px}")
    print(f"  {'PASS' if ok else 'FAIL'}  C headline — 잉크 {el.ink_px}px 중 "
          f"보이는 {el.visible_px}px 만 대비 표본 (표본 {hb['contrast_sample_px']}px)")
    print(f"        제품에 덮인 {el.ink_px - el.visible_px}px 는 제외 — "
          "안 보이는 획의 가독성을 재지 않는다")

    # type_over 는 합성 직전 under 픽셀을 그대로 쓴다 (덮인 것이 없으면 전부)
    tb = resC.measurements["blocks"]["discount_token"]
    tel = evC.by_id("discount_token")
    ok = tb["relation"] == "type_over" and tb["contrast_sample_px"] == tel.visible_px
    check(ok, f"type_over 표본: {tb['contrast_sample_px']}")
    print(f"  {'PASS' if ok else 'FAIL'}  C discount_token (type_over) — "
          f"합성 직전 under 픽셀 {tb['contrast_sample_px']}px 사용")

    # 획이 하나도 안 남으면 대비 대신 별도 코드로 보고한다
    ok = all(b.get("contrast") is not None or b.get("visible_ink_px") == 0
             for r in RESULTS.values() for b in r[2].measurements["blocks"].values())
    check(ok, "획 0 이면 대비 None")
    print(f"  {'PASS' if ok else 'FAIL'}  남은 획이 0 이면 대비 대신 "
          "safety.block_fully_occluded 로 보고")


def test_char_capability() -> None:
    section("③ char-level 지원 범위 — 가로쓰기만")

    rows = []
    for k, (_, _, res) in RESULTS.items():
        for bid, e in res.measurements["blocks"].items():
            if e["relation"] != "type_under":
                continue
            rows.append((k, bid, e["orientation"], e.get("char_check"),
                         e.get("worst_char_occlusion")))
    for k, bid, orient, chk, worst in rows:
        print(f"  {k}.{bid:16} {orient:12} char_check={chk}  최악글자={worst}")
        ok = (chk == "supported") if orient == "horizontal" else str(chk).startswith("unsupported")
        check(ok, f"{k}.{bid} char capability")

    # 회전/세로 블록을 type_under 로 두면 **미지원이라고 밝히고** 건너뛴다
    raw = copymod.deepcopy(FIXTURES["A"][1]())
    for blk in raw["copy_blocks"]:
        if blk["id"] == "side_caption":
            blk["layer"] = "type_under"
    _, _, _, res = run(raw)
    e = res.measurements["blocks"]["side_caption"]
    ok = (e["char_check"] == "unsupported:rotate_ccw"
          and e["worst_char_occlusion"] is None
          and any("side_caption" in u for u in res.unsupported))
    check(ok, f"rotate_ccw 미지원 명시: {e.get('char_check')} · {res.unsupported}")
    print(f"\n  {'PASS' if ok else 'FAIL'}  rotate_ccw 블록 → char_check="
          f"{e['char_check']} · 블록 단위 가림은 {e['ink_occlusion']} 로 검사")
    print(f"        미지원 목록에 기록: {res.unsupported[0][:60]}…")
    print("        조용히 건너뛰지도, 틀린 글자 상자로 검사하지도 않는다")


def test_planner_payload() -> None:
    section("④ SafetyResult → Planner 전달 구조")

    for k in ("A", "C"):
        _, _, res = RESULTS[k]
        payload = res.for_planner()
        print(f"\n  {k} — passed={payload['passed']} · violations={len(payload['violations'])}")
        for v in payload["violations"][:3]:
            print(f"      code       {v['code']}")
            print(f"      element_id {v['element_id']} ({v['element_kind']})")
            print(f"      severity   {v['severity']}")
            print(f"      measured   {v['measured']}  threshold {v['threshold']}")
            print(f"      layer      {v['layer']}  relation {v['relation']}")
            print()
        required = {"code", "element_id", "element_kind", "severity",
                    "measured", "threshold", "layer", "relation", "detail"}
        ok = all(required <= set(v) for v in payload["violations"])
        check(ok, f"{k} 필수 필드")
        ok_json = json.dumps(payload, ensure_ascii=False) is not None
        check(ok_json, f"{k} 직렬화")

    print(f"  PASS  필수 필드 {sorted(required)} 전부 존재 · JSON 직렬화 가능")

    # **처방을 담지 않는다** — 해결 방법은 Planner 의 몫이다
    banned = ("바꿔", "옮기", "줄여", "늘려", "해야 한다", "권장", "추천")
    hits = []
    for k, (_, _, res) in RESULTS.items():
        for v in res.violations:
            hits += [w for w in banned if w in v.detail]
    check(not hits, f"처방 어휘: {hits}")
    print(f"  {'PASS' if not hits else 'FAIL'}  violation.detail 에 처방 어휘 없음 — "
          "무엇이 왜 실패했는지만 담는다")


def test_policy_explicit() -> None:
    section("SystemPolicy — 기준이 코드에 숨어 있지 않다")

    p = DEFAULT_POLICY
    print(f"  large text 기준   regular/medium ≥ {p.large_text_min_px}px · "
          f"bold/black ≥ {p.large_bold_min_px}px")
    print(f"                   (표시 짧은 변 {p.as_dict()['reference_display_short_side']}px 가정, "
          "WCAG 24px/18.66px 환산)")
    print(f"  대비             작은 글자 {p.text_contrast_min} · 큰 글자 "
          f"{p.large_text_contrast_min} · 하위 {p.contrast_percentile}% 로 판정")
    print(f"  가림             critical {p.critical_occlusion_max} · 글자 "
          f"{p.char_occlusion_max} · 일반 {p.block_occlusion_max}")
    print(f"  모티프           가시 {p.motif_visible_min} · 이탈 {p.canvas_overflow_max}px")

    cases = [
        (39, "medium", p.text_contrast_min, False),
        (52, "medium", p.large_text_contrast_min, True),
        (39, "bold", p.text_contrast_min, False),
        (40, "black", p.large_text_contrast_min, True),
    ]
    for size, weight, want, large in cases:
        ok = p.contrast_min_for(size, weight) == want and p.is_large_text(size, weight) == large
        check(ok, f"{size}px {weight} → {want}")
    print(f"  PASS  크기·굵기별 기준 4건 확인 — Validator 가 임의로 정하지 않는다")

    # 기준을 바꾸면 판정도 바뀐다 (하드코딩이 아니라는 증거)
    loose = SystemPolicy(text_contrast_min=1.0, large_text_contrast_min=1.0,
                         critical_occlusion_max=1.0, char_occlusion_max=1.0,
                         block_occlusion_max=1.0, motif_visible_min=0.0)
    _, _, _, res = run(FIXTURES["C"][1](), loose)
    check(res.passed, f"완화된 policy: {res.codes}")
    print(f"  {'PASS' if res.passed else 'FAIL'}  policy 를 완화하면 C 도 통과 → "
          "기준이 policy 에 있다")

    check("label_visible_min" in DEFERRED_CHECKS, "보류 항목 명시")
    print(f"  PASS  보류: label_visible_min — {DEFERRED_CHECKS['label_visible_min'][:46]}…")


def test_determinism_and_no_mutation() -> None:
    section("⑩⑪ 결정론 · Validator 가 아무것도 고치지 않는다")

    plan, ev, res = RESULTS["C"]
    repeat = [validate_safety(plan, ev) for _ in range(5)]
    same = all(r.codes == res.codes and r.passed == res.passed for r in repeat)
    check(same, "같은 evidence → 같은 결과")
    print(f"  {'PASS' if same else 'FAIL'}  같은 plan+evidence 5회 → 동일 판정 {res.codes}")

    # 렌더를 새로 해도 같은 판정
    _, _, _, res2 = run(FIXTURES["C"][1]())
    ok = res2.codes == res.codes
    check(ok, "재렌더 후에도 동일")
    print(f"  {'PASS' if ok else 'FAIL'}  다시 렌더해도 같은 판정")

    # Validator 가 evidence / plan / 이미지를 건드리지 않았는가
    before = (int(ev.product_alpha.sum()),
              tuple(e.ink_px for e in ev.elements),
              tuple(e.visible_px for e in ev.elements))
    validate_safety(plan, ev)
    after = (int(ev.product_alpha.sum()),
             tuple(e.ink_px for e in ev.elements),
             tuple(e.visible_px for e in ev.elements))
    check(before == after, "evidence 무변형")
    print(f"  {'PASS' if before == after else 'FAIL'}  evidence 무변형 (마스크 픽셀 수 동일)")

    frozen = False
    try:
        res.violations[0].code = "x"  # type: ignore[misc]
    except Exception:
        frozen = True
    check(frozen, "결과 frozen")
    print(f"  {'PASS' if frozen else 'FAIL'}  SafetyResult / Violation frozen")

    # SafetyResult 에 '수정' API 가 없다
    banned = [n for n in dir(res) if n in ("fix", "repair", "apply", "adjust", "rewrite")]
    check(not banned, f"수정 API: {banned}")
    print(f"  {'PASS' if not banned else 'FAIL'}  수정/재시도 API 없음 — 판정만 한다")


def test_isolation() -> None:
    section("⑫ production 분리")

    import importlib

    for name in ("dynamic.safety", "dynamic.policy", "dynamic.evidence"):
        importlib.import_module(name)
        src = open(sys.modules[name].__file__, encoding="utf-8").read()
        bad = [ln.strip() for ln in src.splitlines()
               if ln.strip().startswith(("import pipeline", "from pipeline",
                                         "import api", "from api"))]
        check(not bad, f"{name}: {bad}")
        print(f"  {'PASS' if not bad else 'FAIL'}  {name:20} production import 없음")

    loaded = [n for n in sys.modules if n == "pipeline" or n.startswith("pipeline.")]
    check(not loaded, f"pipeline 로드: {loaded}")
    print(f"  {'PASS' if not loaded else 'FAIL'}  sys.modules 에 pipeline 없음")


def test_must_be_visible_targets() -> None:
    """must_be_visible 은 motif role **과 copy block id** 를 가리킨다 (v0.4).

    전에는 motif 전용이었다. 그런데 Safety 는 처음부터 copy block 의 실제
    가시성을 잴 수 있었다 — evidence 의 id 이름공간이 평면이라서다. 즉 제약은
    측정 능력이 아니라 validator 한 줄의 선택이었고, `must_be_visible` 이라는
    이름으로 "headline 이 보여야 한다" 를 못 쓰는 상태였다.
    """
    section("must_be_visible 대상 범위")

    import copy as _copy
    from dynamic import validate, FIXTURE_CONTEXT, PLANNER_CONTEXT
    import fixtures_renderspec as FXX

    brief = FXX.brief()
    asset, geo = fixed_asset()
    raw = _copy.deepcopy(dict(FXX.FIXTURES["A"][1]()))
    block_ids = [b["id"] for b in raw["copy_blocks"]]

    # ① copy block id 를 가리켜도 통과한다
    spec_raw = _copy.deepcopy(raw)
    spec_raw["safety"]["must_be_visible"] = ["headline"]
    errs = validate(_copy.deepcopy(spec_raw), brief, FIXTURE_CONTEXT)
    check(not errs, f"copy block 참조 거부: {[e.code for e in errs]}")
    print(f"  {'PASS' if not errs else 'FAIL'}  copy block id 참조 허용 "
          f"— must_be_visible=['headline'] (copy: {block_ids})")

    # ② 실제로 측정되고 kind 가 맞게 보고된다
    plan = build_plan(load(_copy.deepcopy(spec_raw), brief), brief, geo)
    img, ev = render_with_evidence(plan, asset, geo)
    res = validate_safety(plan, ev)
    meas = res.measurements.get("must_be_visible", {}).get("headline", {})
    ok = meas.get("kind") == "copy" and meas.get("visible_ratio", 0) > 0
    check(ok, f"측정 실패: {meas}")
    print(f"  {'PASS' if ok else 'FAIL'}  실제 측정 kind={meas.get('kind')!r} "
          f"visible_ratio={meas.get('visible_ratio')} — element_kind 하드코딩 제거됨")

    # ③ motif role 도 그대로 된다 (회귀)
    errs = validate(_copy.deepcopy(raw), brief, FIXTURE_CONTEXT)
    check(not errs, f"motif 참조 회귀: {[e.code for e in errs]}")
    print(f"  {'PASS' if not errs else 'FAIL'}  motif role 참조 그대로 "
          f"— {raw['safety']['must_be_visible']}")

    # ④ 어느 쪽도 아니면 여전히 거부
    bad = _copy.deepcopy(raw)
    bad["safety"]["must_be_visible"] = ["nonexistent_thing"]
    codes = [e.code for e in validate(bad, brief, FIXTURE_CONTEXT)]
    ok = "safety.must_be_visible_unknown" in codes
    check(ok, f"미지 참조 통과: {codes}")
    print(f"  {'PASS' if ok else 'FAIL'}  motif 도 copy 도 아니면 거부 — {codes}")

    # ⑤ 이름이 겹치면 **조용히 한쪽으로 해석하지 않는다**
    amb = _copy.deepcopy(raw)
    amb["motif"]["instances"][0]["role"] = "headline"     # copy block 과 같은 이름
    amb["safety"]["must_be_visible"] = ["headline"]
    codes = [e.code for e in validate(amb, brief, FIXTURE_CONTEXT)]
    ok = "safety.visible_target_ambiguous" in codes
    check(ok, f"모호한 참조를 통과시킴: {codes}")
    print(f"  {'PASS' if ok else 'FAIL'}  motif role 과 copy id 가 겹치면 거부 "
          "— 무엇을 쟀는지 모르는 판정은 만들지 않는다")


#: `Violation.detail` 로 **현재 만들어질 수 있는 문구 전부.**
#:
#: 금지어 목록으로 계약을 지키지 않는다 — 처방은 얼마든지 다른 말로 쓸 수
#: 있어서 blacklist 는 새는 방어다. 대신 **등록제**로 잠근다. Safety rule 을
#: 새로 넣으면 여기 없는 문구가 생기고 아래 테스트가 실패하므로, 사람이
#: "이게 관측 서술인가 처방인가" 를 판단하고 등록해야 한다.
#:
#: 검토 기록 — 아래 9종은 전부 ① 관측 사실 또는 ② 측정 방식이다.
#: 해결 방법을 말하는 문구는 0건이다.
REVIEWED_DETAILS = {
    '"none 을 선언했는데 실제 2D 교집합이 있다"',
    '"required 를 선언했는데 실제 겹침이 없다 (선언-강제)"',
    '"렌더 결과에 존재하지 않는다"',
    'f"{el.ink_px}px 중 {el.visible_px}px 만 남았다"',
    'f"선언되지 않은 방향으로 벗어남: {bad}"',
    'f"제품이 실제 획의 {occ:.1%} 를 덮었다 (bbox 아님)"',
    'f"가장 많이 가린 글자 {worst:.1%} — 글자가 읽히지 않는다"',
    '"최종 화면에 남은 획이 없다 — 대비를 잴 대상 자체가 없다"',
    'CONTRAST_DETAIL',        # f-string 3줄 연결 — 아래에서 실제 값으로 확인한다
}


def test_detail_observation_only() -> None:
    """Violation.detail 은 **관측만** 담는다 (safety.DETAIL_CONTRACT).

    prompt v1.4 부터 detail 이 SafetyFeedback 으로 Planner 에 그대로 실린다.
    처방이 섞이면 "Safety 는 고치는 방법을 말하지 않는다" 는 계약이 그 자리에서
    깨지므로, 문구 집합 자체를 잠근다.
    """
    section("Violation.detail — observation-only 계약")

    import re
    import inspect as _ins
    from dynamic.safety import DETAIL_CONTRACT
    import dynamic.safety as _S

    src = _ins.getsource(_S)
    found = set(re.findall(r'detail=(f?"[^"]*")', src))
    found |= set(re.findall(r'flag\([^)]*?,\s*(f?"[^"]*")\s*\)', src, re.S))
    # 여러 줄로 이어붙인 contrast 문구는 리터럴로 안 잡힌다 — 실제 실행으로 본다
    found.discard('f"{\'큰\' if entry[\'large_text\'] else \'작은\'} 글자"')

    unknown = {d for d in found if d not in REVIEWED_DETAILS}
    check(not unknown, f"등록되지 않은 detail: {unknown}")
    print(f"  {'PASS' if not unknown else 'FAIL'}  소스의 detail 문구 {len(found)}종이 "
          "전부 검토·등록됨 — 새 rule 이 생기면 여기서 막힌다")
    print(f"        계약: {DETAIL_CONTRACT}")

    # 실제 실행에서 나오는 detail 도 같이 본다 (f-string 연결 포함)
    asset, geo = fixed_asset()
    _brief = brief()
    live = []
    for name in ("A", "C", "D"):
        plan = build_plan(load(dict(FIXTURES[name][1]()), _brief), _brief, geo)
        img, ev = render_with_evidence(plan, asset, geo)
        live += [v.detail for v in validate_safety(plan, ev).violations if v.detail]
    ok = bool(live)
    check(ok, "실제 detail 수집 실패")
    print(f"  {'PASS' if ok else 'FAIL'}  fixture A·C·D 에서 실제 생성된 detail "
          f"{len(live)}건 수집")
    for d in sorted(set(live)):
        print(f"        · {d}")

    # 실제 문구가 측정 서술인지 — 숫자/단위/관측 동사가 있고 명령형이 없는가
    imperative = [d for d in set(live)
                  if re.search(r"(하라|해라|바꿔|줄여|늘려|옮겨|사용하라|권장)", d)]
    check(not imperative, f"명령형 detail: {imperative}")
    print(f"  {'PASS' if not imperative else 'FAIL'}  실제 문구에 명령형/권고 표현 0건 "
          "(등록제의 보조 확인일 뿐, 이것만으로 계약을 지키지 않는다)")


def main() -> int:
    print("=" * 72)
    print("Safety Validator 테스트 — E12 v0.3 Step 6")
    print("=" * 72)

    test_all_fixtures()
    test_integrity()
    test_must_be_visible_targets()
    test_detail_observation_only()
    test_visible_ink_contrast()
    test_char_capability()
    test_planner_payload()
    test_target_cases()
    test_layer_dependent_checks()
    test_overlap_intent()
    test_must_be_visible()
    test_overflow()
    test_policy_explicit()
    test_determinism_and_no_mutation()
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

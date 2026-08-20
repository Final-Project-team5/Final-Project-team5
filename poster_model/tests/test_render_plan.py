"""RenderSpec → RenderPlan 테스트 — E12 v0.3 Step 3.

Step 3 은 **그리지 않지만 측정은 한다.** 그래서 확인할 것은
"좌표가 맞는가"가 아니라 "측정 결과가 배치에 실제로 반영되는가"다.

    after:eyebrow      eyebrow 의 **실측 높이** + space_after 만큼 내려가는가
    before:<block>     대상 위치에서 역산되는가
    align:product_*    ProductGeometry 기반 bbox 와 baseline 이 맞는가
    여러 줄 headline    줄 수가 바뀌면 다음 블록도 따라 움직이는가
    문구 길이 변화       줄바꿈 · bbox · 후속 블록이 함께 달라지는가

실행:  python tests/test_render_plan.py
"""

from __future__ import annotations

import copy
import dataclasses
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dynamic import (  # noqa: E402
    AnchorUnresolvable,
    BriefCopy,
    ContentRefUnresolved,
    CopyExtra,
    CopyItem,
    CreativeBrief,
    FontBook,
    PlanUnresolvable,
    ProductGeometry,
    ProductGeometryInvalid,
    build_plan,
    load,
    validate,
)
from dynamic.plan import (  # noqa: E402
    SPACE_AFTER_BASELINES,
    line_height_px,
    type_size_px,
)
from test_renderspec_schema import valid_brief, valid_spec  # noqa: E402

FAILS: list[str] = []
CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILS.append(label)


def section(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 62 - len(title)))


def geometry(bw: int = 681, bh: int = 861) -> ProductGeometry:
    return ProductGeometry.from_mask_size(
        cutout_width=1024,
        cutout_height=1024,
        mask_bbox=(180, 120, 180 + bw - 1, 120 + bh - 1),
    )


def brief_with(**copy_kwargs) -> CreativeBrief:
    base = valid_brief()
    fields = {
        "eyebrow": base.copy.eyebrow,
        "headline": base.copy.headline,
        "benefit": base.copy.benefit,
        "token": base.copy.token,
        "cta": base.copy.cta,
        "extra": base.copy.extra,
    }
    for key, value in copy_kwargs.items():
        fields[key] = CopyItem(value) if isinstance(value, str) else value
    return dataclasses.replace(base, copy=BriefCopy(**fields))


def plan_from(mutator=None, brief=None, geo=None):
    raw = valid_spec()
    if mutator:
        mutator(raw)
    spec = load(raw, brief or valid_brief())
    return build_plan(spec, brief or valid_brief(), geo or geometry())


def block(plan, block_id):
    for b in plan.copy_blocks:
        if b.id == block_id:
            return b
    raise KeyError(block_id)


def motif(plan, role):
    for m in plan.motifs:
        if m.role == role:
            return m
    raise KeyError(role)


# ──────────────────────────────────────────────────────────────────────────
def test_baseline_plan() -> None:
    section("기준 plan")

    plan = plan_from()
    print(f"  격자   baseline {plan.grid.baseline_px} · margin {plan.grid.margin_x} · "
          f"gutter {plan.grid.gutter_px} · col_w {plan.grid.col_w}")
    for b in plan.copy_blocks:
        print(f"  {b.id:15} {b.size_px:4}px  lh {b.line_height_px:3}  "
              f"rows {b.first_row:2}~{b.last_row:2}  bbox {b.bbox_px}  {list(b.lines)}")
    print(f"  product  bbox {plan.product.bbox_px}  scale {plan.product.scale:.3f}  "
          f"rot {plan.product.rotation_deg}°")
    for m in plan.motifs:
        print(f"  motif {m.role:15} {list(m.boxes)}  {list(m.color_roles)}")

    # 모든 세로 좌표가 baseline 격자 위에 있어야 한다
    off = [
        (b.id, b.bbox_px)
        for b in plan.copy_blocks
        if b.bbox_px[1] % plan.grid.baseline_px or b.bbox_px[3] % plan.grid.baseline_px
    ]
    check(not off, f"블록 세로 좌표가 baseline 배수여야 한다: {off}")
    print(f"  {'PASS' if not off else 'FAIL'}  모든 블록이 baseline {plan.grid.baseline_px} 격자 위")

    # 행간도 baseline 배수 — 그래야 여러 블록이 같은 정렬선을 공유한다
    bad = [b.id for b in plan.copy_blocks if b.line_height_px % plan.grid.baseline_px]
    check(not bad, f"행간이 baseline 배수여야 한다: {bad}")
    print(f"  {'PASS' if not bad else 'FAIL'}  행간이 baseline 배수")

    frozen = False
    try:
        plan.copy_blocks[0].size_px = 10  # type: ignore[misc]
    except Exception:
        frozen = True
    check(frozen, "RenderPlan frozen")
    print(f"  {'PASS' if frozen else 'FAIL'}  RenderPlan frozen")

    # 대체는 이제 아예 일어나지 않는다 — 표현할 수 없는 조합은 검증에서 거부된다.
    # 필드는 남겨 둔다. 나중에 표에 대체가 생기면 그때 여기서 드러난다
    check(plan.font_substitutions == (), f"대체 서체 없음: {plan.font_substitutions}")
    check(
        all(not b.font_substituted for b in plan.copy_blocks),
        "어떤 블록도 대체 서체를 쓰지 않는다",
    )
    print(f"  PASS  서체 대체 0건 — Planner 가 고른 family/weight 가 그대로 렌더된다")
    for b in plan.copy_blocks:
        print(f"        {b.id:15} {b.font_family}/{b.font_weight} → "
              f"{b.font_path.split('/')[-1]}")


def test_after_anchor() -> None:
    section("① after:<block> — 실측 높이 + space_after")

    plan = plan_from()
    eyebrow, headline = block(plan, "eyebrow"), block(plan, "headline")
    gap = SPACE_AFTER_BASELINES["tight"] * plan.grid.baseline_px  # eyebrow.space_after

    want = eyebrow.bbox_px[3] + gap
    ok = headline.bbox_px[1] == want
    check(ok, f"after: 기대 {want} / 실제 {headline.bbox_px[1]}")
    print(f"  {'PASS' if ok else 'FAIL'}  eyebrow 하단 {eyebrow.bbox_px[3]} + space_after {gap} "
          f"= headline 상단 {headline.bbox_px[1]}")

    # space_after 를 바꾸면 실제로 간격이 바뀐다 — 숨은 상수가 아니다
    loose = plan_from(lambda r: r["typography"]["roles"][0].update({"space_after": "loose"}))
    lg = SPACE_AFTER_BASELINES["loose"] * plan.grid.baseline_px
    moved = block(loose, "headline").bbox_px[1] - headline.bbox_px[1]
    ok = moved == lg - gap
    check(ok, f"space_after 변경 반영: {moved} (기대 {lg - gap})")
    print(f"  {'PASS' if ok else 'FAIL'}  space_after tight→loose 하니 headline 이 "
          f"{moved}px 내려감 (기대 {lg - gap})")

    # eyebrow 문구가 길어져 줄이 늘면 headline 도 따라 내려간다
    long_eyebrow = plan_from(
        lambda r: r["typography"]["roles"][0].update({"max_lines": 3}),
        brief=brief_with(eyebrow="스킨케어 데일리 라인 신제품 출시"),
    )
    e2, h2 = block(long_eyebrow, "eyebrow"), block(long_eyebrow, "headline")
    ok = len(e2.lines) > len(eyebrow.lines) and h2.bbox_px[1] > headline.bbox_px[1]
    check(ok, "eyebrow 줄 수 증가가 headline 위치에 반영")
    print(f"  {'PASS' if ok else 'FAIL'}  eyebrow {len(eyebrow.lines)}줄→{len(e2.lines)}줄 하니 "
          f"headline 상단 {headline.bbox_px[1]}→{h2.bbox_px[1]}")


def test_before_anchor() -> None:
    section("② before:<block> — 대상 위치에서 역산")

    plan = plan_from()
    token = block(plan, "discount_token")
    rule = motif(plan, "bottom_rule")
    top = min(b[1] for b in rule.boxes)
    bottom = max(b[3] for b in rule.boxes)

    ok = bottom == token.bbox_px[1]
    check(ok, f"before: rule 하단 {bottom} == token 상단 {token.bbox_px[1]}")
    print(f"  {'PASS' if ok else 'FAIL'}  bottom_rule 하단 {bottom} = "
          f"discount_token 상단 {token.bbox_px[1]} (space_after none)")
    check(bottom - top == rule.weight_px, "rule 두께")
    print(f"  PASS  rule 두께 {rule.weight_px}px (hair = baseline // 8)")

    # 대상이 움직이면 before: 도 따라 움직인다
    moved = plan_from(lambda r: r["copy_blocks"][3]["grid_ref"].update({"row_anchor": "lower"}))
    t2 = block(moved, "discount_token")
    r2 = motif(moved, "bottom_rule")
    ok = max(b[3] for b in r2.boxes) == t2.bbox_px[1] and t2.bbox_px[1] != token.bbox_px[1]
    check(ok, "대상 이동이 before: 에 반영")
    print(f"  {'PASS' if ok else 'FAIL'}  token 을 bottom→lower 로 옮기니 "
          f"rule 도 {bottom}→{max(b[3] for b in r2.boxes)}")


def test_product_align() -> None:
    section("③ align:product_top / product_bottom")

    for anchor, side in (("align:product_top", "top"), ("align:product_bottom", "bottom")):
        plan = plan_from(
            lambda r, a=anchor: r["copy_blocks"][3]["grid_ref"].update({"row_anchor": a})
        )
        tok = block(plan, "discount_token")
        px0, py0, px1, py1 = plan.product.bbox_px
        base = plan.grid.baseline_px
        if side == "top":
            want = ((py0 + base // 2) // base) * base
            got = tok.bbox_px[1]
        else:
            want = ((py1 + base // 2) // base) * base
            got = tok.bbox_px[3]
        ok = got == want and abs(got - (py0 if side == "top" else py1)) <= base // 2
        check(ok, f"{anchor}: 기대 {want} / 실제 {got}")
        print(f"  {'PASS' if ok else 'FAIL'}  {anchor:22} 제품 {side} {py0 if side == 'top' else py1} "
              f"→ 가장 가까운 baseline row {got}")

    # geometry 가 바뀌면 제품 bbox 도 바뀌고 anchor 도 따라간다
    a = plan_from(lambda r: r["copy_blocks"][3]["grid_ref"].update({"row_anchor": "align:product_top"}))
    b = plan_from(
        lambda r: r["copy_blocks"][3]["grid_ref"].update({"row_anchor": "align:product_top"}),
        geo=geometry(bw=681, bh=500),
    )
    ok = a.product.bbox_px != b.product.bbox_px and block(a, "discount_token").bbox_px[1] != block(
        b, "discount_token"
    ).bbox_px[1]
    check(ok, "geometry 변화가 anchor 에 전달")
    print(f"  {'PASS' if ok else 'FAIL'}  제품 비율 변경 → bbox {a.product.bbox_px} → "
          f"{b.product.bbox_px}, anchor 도 이동")


def test_product_sequence_anchor() -> None:
    section("after:product / before:product — 제품 다음/이전에 잇는다")

    from dynamic.spec import PRODUCT_ROW_SEQUENCE

    def seq_spec(row_anchor, **product_over):
        raw = valid_spec()
        raw["product"].update(product_over)
        anchor = row_anchor
        # headline 을 제품 관계로 옮기고 뒤따르는 블록은 headline 에 잇는다
        raw["copy_blocks"][1]["grid_ref"]["row_anchor"] = anchor
        raw["copy_blocks"][0]["grid_ref"]["row_anchor"] = "top"
        raw["motif"]["instances"][1]["grid_ref"]["row_anchor"] = "bottom"
        return raw

    # ① after:product — 블록 상단이 제품 하단 **다음** baseline 부터
    plan = build_plan(load(seq_spec("after:product",
                                    fit="area_cap", area_cap=0.14, bleed=[],
                                    anchor={"x": "center", "y": "top"}), valid_brief()),
                      valid_brief(), geometry())
    h = block(plan, "headline")
    px0, py0, px1, py1 = plan.product.bbox_px
    base = plan.grid.baseline_px
    gap = SPACE_AFTER_BASELINES["normal"] * base          # headline 자신의 space_after
    want = -(-py1 // base) * base + gap
    ok = h.bbox_px[1] == want and h.bbox_px[1] >= py1
    check(ok, f"after:product 기대 {want} / 실제 {h.bbox_px[1]}")
    print(f"  {'PASS' if ok else 'FAIL'}  제품 하단 {py1} → 다음 baseline "
          f"{-(-py1 // base) * base} + space_after {gap} = headline 상단 {h.bbox_px[1]}")
    print(f"        제품 아래에 있는가 {h.bbox_px[1] >= py1} · baseline 정합 "
          f"{h.bbox_px[1] % base == 0}")

    # align:product_bottom 과 **다른 결과**여야 한다 (같으면 계약이 무의미하다)
    aligned = build_plan(load(seq_spec("align:product_bottom",
                                       fit="area_cap", area_cap=0.14, bleed=[],
                                       anchor={"x": "center", "y": "top"}), valid_brief()),
                         valid_brief(), geometry())
    ha = block(aligned, "headline")
    ok = ha.bbox_px[1] != h.bbox_px[1] and ha.bbox_px[3] <= py1 + base
    check(ok, f"align 과 after 가 달라야 한다: {ha.bbox_px} vs {h.bbox_px}")
    print(f"  {'PASS' if ok else 'FAIL'}  align:product_bottom 은 {ha.bbox_px[1]}"
          f"(제품에 겹침) · after:product 는 {h.bbox_px[1]}(제품 아래)")

    # ② before:product — 블록 하단이 제품 상단 **이전** baseline 까지
    plan2 = build_plan(load(seq_spec("before:product",
                                     fit="area_cap", area_cap=0.14, bleed=[],
                                     anchor={"x": "center", "y": "bottom"}), valid_brief()),
                       valid_brief(), geometry())
    h2 = block(plan2, "headline")
    _, py0b, _, _ = plan2.product.bbox_px
    want2 = py0b // base * base - gap
    ok = h2.bbox_px[3] == want2 and h2.bbox_px[3] <= py0b
    check(ok, f"before:product 기대 {want2} / 실제 {h2.bbox_px[3]}")
    print(f"  {'PASS' if ok else 'FAIL'}  제품 상단 {py0b} → 이전 baseline "
          f"{py0b // base * base} − space_after {gap} = headline 하단 {h2.bbox_px[3]}")

    # ③ 회전·bleed 가 있어도 **resolved bbox 기준**으로 결정론적이다
    rot = seq_spec("after:product", fit="area_cap", area_cap=0.10,
                   anchor={"x": "right", "y": "top"}, rotation="slight_cw",
                   bleed=["right"])
    p3 = build_plan(load(rot, valid_brief()), valid_brief(), geometry())
    h3 = block(p3, "headline")
    _, _, _, py1c = p3.product.bbox_px
    same = all(
        block(build_plan(load(copy.deepcopy(rot), valid_brief()), valid_brief(),
                         geometry()), "headline").bbox_px == h3.bbox_px
        for _ in range(5))
    ok = same and h3.bbox_px[1] >= py1c and p3.product.rotation_deg != 0
    check(ok, f"회전 제품에서 결정론: {h3.bbox_px}")
    print(f"  {'PASS' if ok else 'FAIL'}  회전 {p3.product.rotation_deg}° + bleed['right'] "
          f"→ 제품 하단 {py1c} 아래 {h3.bbox_px[1]} · 5회 동일")

    # ④ 캔버스를 벗어나면 거부한다 (조용히 밀어 넣지 않는다)
    raised = None
    try:
        build_plan(load(seq_spec("after:product", fit="zone_width",
                                 anchor={"x": "right", "y": "bottom"},
                                 bleed=["bottom"]), valid_brief()),
                   valid_brief(), geometry())
    except Exception as exc:  # noqa: BLE001
        raised = exc
    ok = isinstance(raised, PlanUnresolvable) and raised.code == "layout.block_out_of_canvas"
    check(ok, f"캔버스 이탈 거부: {type(raised).__name__}")
    print(f"  {'PASS' if ok else 'FAIL'}  제품이 하단까지 차면 after:product 는 "
          f"{type(raised).__name__}:{getattr(raised, 'code', '')}")

    # ⑤ planner 경로의 정수 row 금지는 그대로
    raw = seq_spec("after:product", fit="area_cap", area_cap=0.14, bleed=[],
                   anchor={"x": "center", "y": "top"})
    raw["copy_blocks"][1]["grid_ref"]["row_anchor"] = 40
    codes = [e.code for e in validate(raw, valid_brief())]
    ok = "row_anchor.index_in_planner_path" in codes
    check(ok, f"정수 row 금지: {codes}")
    print(f"  {'PASS' if ok else 'FAIL'}  정수 row index 는 여전히 거부 → {codes}")

    # ⑥ "product" 는 예약어 — block id / motif role 로 쓸 수 없다
    raw = valid_spec()
    raw["copy_blocks"][0]["id"] = "product"
    raw["safety"]["critical_blocks"] = ["headline", "discount_token"]
    codes = [e.code for e in validate(raw, valid_brief())]
    ok = "anchor.reserved_name" in codes
    check(ok, f"예약어: {codes}")
    print(f"  {'PASS' if ok else 'FAIL'}  block id 'product' → {codes}")
    print(f"        허용 값: {list(PRODUCT_ROW_SEQUENCE)}")


def test_multiline_and_copy_length() -> None:
    section("④⑥ 여러 줄 headline · 문구 길이 변화")

    short = plan_from(brief=brief_with(headline="촉촉함"))
    long = plan_from(
        lambda r: r["typography"]["roles"][1].update({"max_lines": 4}),
        brief=brief_with(headline="촉촉함을 오래 지켜 주는 토너"),
    )

    hs, hl = block(short, "headline"), block(long, "headline")
    print(f"  짧은 문구  {len(hs.lines)}줄 {list(hs.lines)}  bbox {hs.bbox_px}")
    print(f"  긴  문구  {len(hl.lines)}줄 {list(hl.lines)}  bbox {hl.bbox_px}")

    ok = len(hl.lines) > len(hs.lines)
    check(ok, "긴 문구가 더 많은 줄")
    print(f"  {'PASS' if ok else 'FAIL'}  줄 수 {len(hs.lines)} → {len(hl.lines)}")

    ok = hl.bbox_px[3] - hl.bbox_px[1] > hs.bbox_px[3] - hs.bbox_px[1]
    check(ok, "블록 높이 증가")
    print(f"  {'PASS' if ok else 'FAIL'}  블록 높이 {hs.bbox_px[3] - hs.bbox_px[1]} → "
          f"{hl.bbox_px[3] - hl.bbox_px[1]}")

    ok = all(w <= hl.measure_px for w in hl.line_widths_px)
    check(ok, f"모든 줄이 측정 폭 이내: {hl.line_widths_px} / {hl.measure_px}")
    print(f"  {'PASS' if ok else 'FAIL'}  줄 폭 {list(hl.line_widths_px)} ≤ 측정 폭 {hl.measure_px} "
          "(줄 수만 세지 않고 폭도 본다)")

    # 의미 단위 줄바꿈 — 어절이 쪼개지지 않는다
    joined = " ".join(hl.lines)
    ok = joined == hl.text
    check(ok, f"어절 보존: {joined!r}")
    print(f"  {'PASS' if ok else 'FAIL'}  어절 보존 — 줄을 이으면 원문과 같다")

    # 고아 줄 회피 — 마지막 줄에 한 어절만 남기지 않는다 (가능하면)
    orphan = len(hl.lines) >= 2 and len(hl.lines[-1].split()) >= 2
    print(f"  {'PASS' if orphan else 'INFO'}  마지막 줄 어절 수 {len(hl.lines[-1].split())} "
          "(고아 줄 벌점)")


def test_determinism() -> None:
    section("⑤ 결정론")

    args = (valid_spec(), valid_brief(), geometry())
    spec = load(copy.deepcopy(args[0]), args[1])
    first = build_plan(spec, args[1], args[2]).digest()
    same = all(build_plan(spec, args[1], args[2]).digest() == first for _ in range(20))
    check(same, "같은 입력 20회 → 같은 digest")
    print(f"  {'PASS' if same else 'FAIL'}  같은 Spec+Brief+Geometry 20회 → digest {first}")

    # 새 FontBook 으로도 같은 결과 (캐시가 결과를 바꾸지 않는다)
    fresh = build_plan(spec, args[1], args[2], book=FontBook()).digest()
    check(fresh == first, "새 FontBook 에서도 동일")
    print(f"  {'PASS' if fresh == first else 'FAIL'}  새 FontBook 인스턴스 → {fresh}")

    # 입력이 달라지면 digest 도 달라진다
    other = build_plan(spec, brief_with(headline="촉촉함"), geometry()).digest()
    check(other != first, "copy 가 다르면 digest 도 다르다")
    print(f"  {'PASS' if other != first else 'FAIL'}  copy 변경 → {other}")

    geo_other = build_plan(spec, args[1], geometry(bh=500)).digest()
    check(geo_other != first, "geometry 가 다르면 digest 도 다르다")
    print(f"  {'PASS' if geo_other != first else 'FAIL'}  geometry 변경 → {geo_other}")

    # design_language 만 바꾸면 plan 이 동일해야 한다 (§6 R1)
    raw = valid_spec()
    raw["design_language"] = "promotion"
    other_lang = build_plan(load(raw, args[1]), args[1], args[2]).digest()
    check(other_lang == first, f"design_language 만 바꾸면 동일: {other_lang}")
    print(f"  {'PASS' if other_lang == first else 'FAIL'}  design_language editorial→promotion "
          f"→ digest {other_lang} (동일해야 한다)")


def test_failures() -> None:
    section("⑦⑧⑨ 실패 케이스")

    # ⑦ 해석되지 않는 content_ref
    empty = dataclasses.replace(valid_brief(), copy=BriefCopy(headline=CopyItem("")))
    raised = None
    try:
        build_plan(load(valid_spec(), valid_brief()), empty, geometry())
    except Exception as exc:  # noqa: BLE001
        raised = exc
    ok = isinstance(raised, ContentRefUnresolved)
    check(ok, f"빈 content → ContentRefUnresolved (실제 {type(raised).__name__})")
    print(f"  {'PASS' if ok else 'FAIL'}  빈 문자열 copy → {type(raised).__name__}"
          f":{getattr(raised, 'code', '')} (조용히 지우지 않는다)")

    # ⑧ 미해결 / 순환 anchor — Validator 를 우회해 plan builder 의 방어선을 본다
    spec = load(valid_spec(), valid_brief())
    broken_ref = dataclasses.replace(spec.copy_blocks[1].grid_ref, row_anchor="after:ghost")
    broken = dataclasses.replace(
        spec,
        copy_blocks=(
            spec.copy_blocks[0],
            dataclasses.replace(spec.copy_blocks[1], grid_ref=broken_ref),
        )
        + spec.copy_blocks[2:],
    )
    raised = None
    try:
        build_plan(broken, valid_brief(), geometry())
    except Exception as exc:  # noqa: BLE001
        raised = exc
    ok = isinstance(raised, AnchorUnresolvable)
    check(ok, f"미해결 anchor (실제 {type(raised).__name__})")
    print(f"  {'PASS' if ok else 'FAIL'}  after:ghost → {type(raised).__name__}"
          f":{getattr(raised, 'code', '')}")

    fwd_ref = dataclasses.replace(
        spec.copy_blocks[0].grid_ref, row_anchor="after:discount_token"
    )
    fwd = dataclasses.replace(
        spec,
        copy_blocks=(dataclasses.replace(spec.copy_blocks[0], grid_ref=fwd_ref),)
        + spec.copy_blocks[1:],
    )
    raised = None
    try:
        build_plan(fwd, valid_brief(), geometry())
    except Exception as exc:  # noqa: BLE001
        raised = exc
    ok = isinstance(raised, AnchorUnresolvable)
    check(ok, "전방 참조")
    print(f"  {'PASS' if ok else 'FAIL'}  전방 참조 → {type(raised).__name__}"
          f":{getattr(raised, 'code', '')}")

    # ⑨ ProductGeometry 누락 / 모순
    raised = None
    try:
        build_plan(spec, valid_brief(), None)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001
        raised = exc
    ok = isinstance(raised, PlanUnresolvable) and raised.code == "geometry.required"
    check(ok, "geometry 누락")
    print(f"  {'PASS' if ok else 'FAIL'}  geometry=None → {type(raised).__name__}"
          f":{getattr(raised, 'code', '')}")

    raised = None
    try:
        build_plan(spec, None, geometry())  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001
        raised = exc
    ok = isinstance(raised, PlanUnresolvable) and raised.code == "brief.required"
    check(ok, "brief 누락")
    print(f"  {'PASS' if ok else 'FAIL'}  brief=None → {type(raised).__name__}"
          f":{getattr(raised, 'code', '')} (실행 경로에서는 필수)")

    for label, kwargs in (
        ("빈 마스크", dict(cutout_width=1024, cutout_height=1024, mask_bbox=(50, 50, 40, 40))),
        ("cutout 밖", dict(cutout_width=100, cutout_height=100, mask_bbox=(0, 0, 200, 200))),
        ("음수 크기", dict(cutout_width=0, cutout_height=100, mask_bbox=(0, 0, 10, 10))),
    ):
        raised = None
        try:
            ProductGeometry.from_mask_size(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raised = exc
        ok = isinstance(raised, ProductGeometryInvalid)
        check(ok, f"geometry 모순 — {label}")
        print(f"  {'PASS' if ok else 'FAIL'}  {label:10} → {type(raised).__name__}"
              f":{getattr(raised, 'code', '')}")

    # 크기를 몰래 줄여 맞추지 않는다
    raised = None
    try:
        plan_from(
            lambda r: r["typography"]["roles"][1].update({"size_step": 9, "max_lines": 1}),
            brief=brief_with(headline="하루 종일 촉촉함을 오래 지켜 주는 데일리 토너"),
        )
    except Exception as exc:  # noqa: BLE001
        raised = exc
    ok = isinstance(raised, PlanUnresolvable)
    check(ok, "들어가지 않는 문구는 실패")
    print(f"  {'PASS' if ok else 'FAIL'}  거대한 문구 + max_lines 1 → {type(raised).__name__}"
          f":{getattr(raised, 'code', '')} (크기를 줄여 맞추지 않는다)")


def test_type_scale() -> None:
    section("타이포 스케일 — 정수 연산")

    sizes = [type_size_px(1024, s, 1.0) for s in range(-3, 7)]
    check(all(a < b for a, b in zip(sizes, sizes[1:])), f"단조 증가: {sizes}")
    print(f"  PASS  size_step −3~+6 → {sizes}")

    # 같은 인자는 항상 같은 값 (float 경계에 의존하지 않는다)
    stable = all(type_size_px(1024, 3, 1.0) == sizes[6] for _ in range(100))
    check(stable, "size 계산 안정")
    print(f"  {'PASS' if stable else 'FAIL'}  100회 반복 동일")

    lh = line_height_px(120, 0.95, 16)
    check(lh % 16 == 0, f"행간 baseline 스냅: {lh}")
    print(f"  PASS  line_height(120, 0.95, baseline 16) = {lh} (baseline 배수로 스냅)")

    scaled = type_size_px(1024, 3, 1.25)
    check(scaled > sizes[6], "scale_step 반영")
    print(f"  PASS  scale_step 1.0 → {sizes[6]} / 1.25 → {scaled}")


def test_isolation() -> None:
    section("⑩ production 분리 · 범위")

    import importlib

    for name in ("dynamic.plan", "dynamic.geometry", "dynamic.fonts", "dynamic.text"):
        importlib.import_module(name)
        mod = sys.modules[name]
        src = open(mod.__file__, encoding="utf-8").read()
        bad = [
            line.strip()
            for line in src.splitlines()
            if line.strip().startswith(("import pipeline", "from pipeline", "import api", "from api"))
        ]
        check(not bad, f"{name} production import: {bad}")
        print(f"  {'PASS' if not bad else 'FAIL'}  {name:20} production import 없음")

    loaded = [n for n in sys.modules if n == "pipeline" or n.startswith("pipeline.")]
    check(not loaded, f"pipeline 로드: {loaded}")
    print(f"  {'PASS' if not loaded else 'FAIL'}  sys.modules 에 pipeline 없음")

    # Step 4 기능이 섞여 들어오지 않았는지 — 그리기 API 가 없어야 한다
    import dynamic.plan as p

    leaked = [n for n in dir(p) if n in ("draw", "render", "composite", "to_image", "save")]
    check(not leaked, f"그리기 API 유입: {leaked}")
    print(f"  {'PASS' if not leaked else 'FAIL'}  그리기/합성 API 없음 (Step 4 범위)")

    src = open(p.__file__, encoding="utf-8").read()
    draws = [k for k in ("ImageDraw", "Image.new", ".paste(", ".alpha_composite") if k in src]
    check(not draws, f"픽셀 생성 흔적: {draws}")
    print(f"  {'PASS' if not draws else 'FAIL'}  픽셀을 만들지 않는다 (측정만)")


def main() -> int:
    print("=" * 72)
    print("RenderPlan 테스트 — E12 v0.3 Step 3")
    print("=" * 72)

    test_baseline_plan()
    test_after_anchor()
    test_before_anchor()
    test_product_align()
    test_product_sequence_anchor()
    test_multiline_and_copy_length()
    test_determinism()
    test_failures()
    test_type_scale()
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

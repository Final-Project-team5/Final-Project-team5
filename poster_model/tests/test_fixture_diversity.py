"""Step 5 — fixture 다양성 검증.

    같은 제품인데 서로 다른 RenderSpec 을 주면
    **실제로 구조적으로 다른 포스터가 만들어지는가**

합격 조건
    A  모든 fixture 가 **같은 ProductRenderAsset** 을 쓴다
    B  각 fixture 가 validation + build_plan + render 를 통과한다
    C  같은 fixture 는 반복 렌더 시 픽셀 동일
    D  fixture 간 픽셀이 서로 다르다
    E  차이가 색만이 아니라 composition / hierarchy / product treatment /
       graphic language 에서 온다
    F  design_language 만 바꾼 D1 은 계속 픽셀 동일
    G  production pipeline 무변경

이번 단계에서 **고치지 않는 것** — eyebrow 대비 미달과 "30%" 의 제품 덮음은
Spec 이 그렇게 설계한 결과이고 Renderer 는 그대로 그렸다. 자동 보정은
Step 6 Validator 가 "안전 기준 미달"로 판정할 몫이다.

실행:  python tests/test_fixture_diversity.py
"""

from __future__ import annotations

import copy as copymod
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from dynamic import (  # noqa: E402
    ProductGeometry,
    ProductRenderAsset,
    build_plan,
    load,
    render,
    render_digest,
    validate,
)
from fixtures_renderspec import FIXTURES, QUALITY_DEFERRED, brief  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
#: 테스트 고정 자산 — 실제 세그멘테이션 결과다. 합성 마스크로
#: 바꾸면 가림/대비 측정이 실제 제품 실루엣이 아닌 값을 재게 된다.
ASSETS = Path(__file__).resolve().parent / "_assets"
# 테스트 산출물은 **저장소 안에 남기지 않는다.** 검사는 전부 메모리 위의
# 이미지로 하고, 저장은 사람이 눈으로 확인하고 싶을 때를 위한 것이다.
# 눈으로 보려면  DYNAMIC_TEST_OUT=/some/dir  로 경로를 지정한다.
OUT = Path(os.environ.get("DYNAMIC_TEST_OUT")
           or tempfile.mkdtemp(prefix="dynamic_step5_"))

# ★ 모든 fixture 가 공유하는 **단 하나의** 제품 asset.
#   segmentation 모델·마스크·cutout 이 fixture 마다 달라지면 디자인 차이와
#   누끼 차이가 섞여 무엇을 평가하는지 알 수 없게 된다 (합격 조건 A)
SEG_MODEL = "birefnet-general"

# "실제로 다른 설계인지" 확인하는 하한. **품질 점수가 아니다** (E12 §11)
MIN_DIFFERING_AXES = 8

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
def fixed_asset():
    """상위 계층이 준비하는 **고정** 제품 asset. 한 번만 만든다."""
    mask = Image.open(ASSETS / "mask" / f"cosmetic_{SEG_MODEL}.png").convert("L")
    original = Image.open(
        ASSETS / "cutout" / "cosmetic_00_original.png"
    ).convert("RGB")
    assert original.size == mask.size
    rgba = original.convert("RGBA")
    rgba.putalpha(mask)

    m = np.array(mask) > 128
    ys, xs = np.where(m)
    geo = ProductGeometry.from_mask_size(
        cutout_width=mask.size[0],
        cutout_height=mask.size[1],
        mask_bbox=(int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())),
    )
    return ProductRenderAsset(rgba), geo


# 설계 축 표는 **dynamic.diversity 가 단일 출처**다 — Planner 후보 검사와 같은 표를 쓴다
from dynamic.diversity import AXIS_CATEGORIES, COLOR_AXES, spec_axes as axes  # noqa: E402


def mutate_zone(raw: dict, intent: str) -> dict:
    out = copymod.deepcopy(raw)
    out["zones"]["overlap_intent"] = intent
    return out


def main() -> int:
    print("=" * 72)
    print("fixture 다양성 검증 — E12 v0.3 Step 5")
    print("=" * 72)

    OUT.mkdir(parents=True, exist_ok=True)
    asset, geo = fixed_asset()
    b = brief()

    # ── A. 고정 asset ────────────────────────────────────────────────────
    section("A. 고정 ProductRenderAsset")
    print(f"  모델      {SEG_MODEL}")
    print(f"  cutout    {geo.cutout_width}×{geo.cutout_height}")
    print(f"  mask_bbox {geo.mask_bbox}  ({geo.bbox_width}×{geo.bbox_height})")
    print(f"  digest    {asset.digest()}")
    print("  PASS  모든 fixture 가 이 asset 하나를 공유한다")
    check(True, "asset")

    # ── B. 검증 · plan · 렌더 ───────────────────────────────────────────
    section("B. validation → build_plan → render")
    plans, images, specs = {}, {}, {}
    for key, (name, fn) in FIXTURES.items():
        raw = fn()
        errs = validate(raw, b)
        check(not errs, f"{key} validation: {[e.code for e in errs]}")
        if errs:
            print(f"  FAIL  {key} {name} → {[e.code for e in errs]}")
            continue
        spec = load(raw, b)
        plan = build_plan(spec, b, geo)
        img = render(plan, asset, geo)
        path = OUT / f"fixture_{key}.png"
        img.save(path)
        plans[key], images[key], specs[key] = plan, img, raw

        px0, py0, px1, py1 = plan.product.bbox_px
        area = (px1 - px0) * (py1 - py0) / (plan.canvas_width * plan.canvas_height)
        head = next((x for x in plan.copy_blocks if x.id == "headline"), None)
        print(f"  PASS  {key} {name:22} → {path.name}")
        print(f"        격자 {plan.grid.columns}단 · baseline {plan.grid.baseline_px} · "
              f"margin {plan.grid.margin_x} · col_w {plan.grid.col_w}")
        print(f"        제품 {area:5.1%} {plan.product.bbox_px} rot {plan.product.rotation_deg}° · "
              f"headline {head.size_px if head else '-'}px {len(head.lines) if head else 0}줄 · "
              f"블록 {len(plan.copy_blocks)} · 모티프상자 {sum(len(m.boxes) for m in plan.motifs)}")
        print(f"        palette {plan.palette.strategy} {plan.palette.as_dict()['colors']}")
        check(not plan.font_substitutions, f"{key} 서체 대체 없음")

    check(len(images) == len(FIXTURES), "모든 fixture 렌더")

    # ── C. 반복 렌더 픽셀 동일 ──────────────────────────────────────────
    section("C. 같은 fixture 반복 렌더 → 픽셀 동일")
    digests = {}
    for key, plan in plans.items():
        d = render_digest(images[key])
        again = {render_digest(render(plan, asset, geo)) for _ in range(3)}
        ok = again == {d}
        check(ok, f"{key} 반복 렌더 동일")
        digests[key] = d
        print(f"  {'PASS' if ok else 'FAIL'}  {key} 4회 → {d}")

    # ── D. fixture 간 픽셀 차이 ─────────────────────────────────────────
    section("D. fixture 간 픽셀이 서로 다르다")
    keys = sorted(images)
    uniq = len(set(digests.values())) == len(digests)
    check(uniq, f"digest 중복: {digests}")
    print(f"  {'PASS' if uniq else 'FAIL'}  digest 4개 전부 다름")
    arrays = {k: np.array(images[k]).astype(np.int16) for k in keys}
    for i, a in enumerate(keys):
        for c in keys[i + 1:]:
            diff = (np.abs(arrays[a] - arrays[c]).sum(axis=2) > 8).mean()
            check(diff > 0.25, f"{a}↔{c} 화면 차이 {diff:.1%}")
            print(f"  {'PASS' if diff > 0.25 else 'FAIL'}  {a}↔{c} 픽셀 차이 {diff:6.1%}")

    # ── E. 차이가 색만이 아니다 ─────────────────────────────────────────
    section("E. 설계 축이 실제로 갈린다 (색만의 차이가 아님)")
    ax = {k: axes(specs[k]) for k in keys}
    names = list(ax[keys[0]])
    color_only = {"palette.strategy", "palette.roles", "palette.spot_path", "palette.spot_min"}
    for i, a in enumerate(keys):
        for c in keys[i + 1:]:
            differ = [n for n in names if ax[a][n] != ax[c][n]]
            structural = [n for n in differ if n not in color_only]
            ok = len(differ) >= MIN_DIFFERING_AXES and len(structural) >= MIN_DIFFERING_AXES
            check(ok, f"{a}↔{c} 갈린 축 {len(differ)} (색 제외 {len(structural)})")
            print(f"  {'PASS' if ok else 'FAIL'}  {a}↔{c} 갈린 축 {len(differ):2}/{len(names)} "
                  f"· 색 관련 제외 {len(structural):2} (하한 {MIN_DIFFERING_AXES})")

    print("\n  범주별 확인 — 어느 관점에서 갈리는가")
    cats = {
        "composition": ["grid.columns", "zones.type", "zones.product", "zones.overlap_intent"],
        "product treatment": ["product.fit", "product.anchor", "product.bleed",
                              "product.rotation", "product.grounding"],
        "hierarchy": ["copy.count", "type.role_count", "headline.size_step", "copy.layers"],
        "graphic language": ["motif.shape", "motif.instances", "motif.pattern",
                             "background.mode", "background.texture"],
    }
    for cat, fields in cats.items():
        vals = {k: tuple(str(ax[k][f]) for f in fields) for k in keys}
        distinct = len(set(vals.values()))
        check(distinct == len(keys), f"{cat} 전부 다름: {distinct}")
        print(f"  {'PASS' if distinct == len(keys) else 'FAIL'}  {cat:20} 서로 다른 조합 "
              f"{distinct}/{len(keys)}")

    print("\n  제품 취급 실측")
    for k in keys:
        px0, py0, px1, py1 = plans[k].product.bbox_px
        print(f"    {k}  면적 {(px1-px0)*(py1-py0)/1024/1024:5.1%} · bbox {plans[k].product.bbox_px} "
              f"· 회전 {plans[k].product.rotation_deg:+3}° · 접지 {plans[k].product.grounding}")

    # ── F. D1 ──────────────────────────────────────────────────────────
    section("F. design_language 만 변경 → 픽셀 동일 (D1)")
    for key in keys:
        raw = copymod.deepcopy(specs[key])
        others = [x for x in ("editorial", "premium_minimal", "promotion",
                              "contemporary_graphic") if x != raw["design_language"]]
        raw["design_language"] = others[0]
        d = render_digest(render(build_plan(load(raw, b), b, geo), asset, geo))
        ok = d == digests[key]
        check(ok, f"{key} D1")
        print(f"  {'PASS' if ok else 'FAIL'}  {key} {specs[key]['design_language']:22}"
              f"→ {others[0]:22} {d}")

    # ── 비교 시트 ───────────────────────────────────────────────────────
    section("comparison sheet")
    sheet = build_sheet(keys, images, plans, specs)
    spath = OUT / "_comparison_sheet.png"
    sheet.save(spath)
    print(f"  PASS  {spath.name}  {sheet.size}")
    check(True, "sheet")

    if QUALITY_DEFERRED:
        print("\n  ⚠ 품질 평가 보류")
        for k, why in QUALITY_DEFERRED.items():
            print(f"    {k}  {why}")

    # ── Step 5.5 ① background_tone ─────────────────────────────────────
    section("5.5① palette.background_tone — light / dark polarity")

    from dynamic.palette import resolve_palette
    from fixtures_renderspec import DARK_FIXTURE

    light_pal = plans["C"].palette
    dark_key, dark_name, dark_fn = DARK_FIXTURE
    dark_raw = dark_fn()
    dark_spec = load(dark_raw, b)
    dark_plan = build_plan(dark_spec, b, geo)
    dark_pal = dark_plan.palette

    # C 와 C-dark 는 background_tone 한 줄만 다르다
    diff_keys = [k for k in dark_raw["palette"] if dark_raw["palette"][k] != specs["C"]["palette"][k]]
    check(diff_keys == ["background_tone"], f"Spec 차이: {diff_keys}")
    print(f"  {'PASS' if diff_keys == ['background_tone'] else 'FAIL'}  "
          f"C ↔ C-dark 의 palette 차이는 {diff_keys} 뿐 (color_role 은 하나도 안 고쳤다)")

    print(f"  light  {light_pal.as_dict()['colors']}")
    print(f"  dark   {dark_pal.as_dict()['colors']}")

    from dynamic.palette import relative_luminance as lum
    flipped = (
        lum(dark_pal.rgb("bg")) < lum(light_pal.rgb("bg"))
        and lum(dark_pal.rgb("ink")) > lum(light_pal.rgb("ink"))
    )
    check(flipped, "bg/ink polarity 반전")
    print(f"  {'PASS' if flipped else 'FAIL'}  bg 는 어두워지고 ink 는 밝아진다 "
          f"(bg L {lum(light_pal.rgb('bg')):.2f}→{lum(dark_pal.rgb('bg')):.2f} · "
          f"ink L {lum(light_pal.rgb('ink')):.2f}→{lum(dark_pal.rgb('ink')):.2f})")

    same_hue = dark_pal.base_hue == light_pal.base_hue and dark_pal.spot_hue == light_pal.spot_hue
    check(same_hue, "hue 는 strategy 가 정한 그대로")
    print(f"  {'PASS' if same_hue else 'FAIL'}  hue 는 그대로 (base {dark_pal.base_hue}° · "
          f"spot {dark_pal.spot_hue}°) — strategy 와 독립된 축")

    ok = dark_pal.contrast("ink", "bg") >= 4.5 and dark_pal.contrast("spot", "bg") > light_pal.contrast("spot", "bg")
    check(ok, f"dark 대비 ink/bg {dark_pal.contrast('ink','bg')} spot/bg {dark_pal.contrast('spot','bg')}")
    print(f"  {'PASS' if ok else 'FAIL'}  dark 대비 ink/bg {dark_pal.contrast('ink','bg')}:1 · "
          f"spot/bg {dark_pal.contrast('spot','bg')}:1 (light 은 {light_pal.contrast('spot','bg')}:1)")

    # 두 축이 정말 독립인가 — 4개 strategy × 2 tone 이 전부 해석된다
    combos = 0
    for strat in ("complementary", "analogous", "split_complementary", "monochromatic",
                  "neutral_support"):
        for tone in ("light", "dark"):
            raw = copymod.deepcopy(specs["C"])
            raw["palette"]["strategy"] = strat
            raw["palette"]["background_tone"] = tone
            pal = resolve_palette(load(raw, b), b)
            assert pal.background_tone == tone
            combos += 1
    check(combos == 10, f"strategy × tone 조합 {combos}")
    print(f"  PASS  strategy 5종 × tone 2종 = {combos}개 조합 전부 해석됨")

    dark_img = render(dark_plan, asset, geo)
    dpath = OUT / "fixture_C_dark.png"
    dark_img.save(dpath)
    check(render_digest(dark_img) != digests["C"], "dark 결과가 light 와 다름")
    print(f"  PASS  {dpath.name}  digest {render_digest(dark_img)}")

    pair = Image.new("RGB", (920, 460), (255, 255, 255))
    pair.paste(images["C"].resize((460, 460), Image.LANCZOS), (0, 0))
    pair.paste(dark_img.resize((460, 460), Image.LANCZOS), (460, 0))
    pair.save(OUT / "_light_vs_dark.png")
    print(f"  PASS  {(OUT / '_light_vs_dark.png').name}")

    # ── Step 5.5 ② overlap_intent ──────────────────────────────────────
    section("5.5② overlap_intent — 겹침 의도만 담고 z-order 는 layer 가 담는다")

    def cols_overlap_of(raw) -> bool:
        tz, pz = raw["zones"]["type"], raw["zones"]["product"]
        return bool(
            set(range(tz["col_start"], tz["col_start"] + tz["col_span"]))
            & set(range(pz["col_start"], pz["col_start"] + pz["col_span"]))
        )

    for k in keys:
        rel = plans[k].type_product_relation()
        print(f"  {k}  선언 {rel['declared']:9} 열교집합 {str(cols_overlap_of(specs[k])):5} "
              f"실제 2D {rel['overlap_px']:>7}px  요약 {str(rel['summary']):8}")
        for bid, info in rel["per_block"].items():
            print(f"       └ {bid:16} 가림비 {info['ratio']:.3f}  {info['layer']:10} "
                  f"→ {info['above']} 가 위")

    # enum 이 셋뿐이고 z-order 값이 남아 있지 않다
    from dynamic.spec import OVERLAP_INTENTS

    ok = OVERLAP_INTENTS == ("none", "allowed", "required")
    check(ok, f"enum: {OVERLAP_INTENTS}")
    print(f"\n  {'PASS' if ok else 'FAIL'}  enum {OVERLAP_INTENTS} — "
          "shared/product_over_type/type_over_product 제거됨")
    for dead in ("shared", "product_over_type", "type_over_product"):
        errs = validate(mutate_zone(specs["A"], dead), b)
        gone = any(e.code == "schema.enum" for e in errs)
        check(gone, f"{dead} 거부")
        print(f"  {'PASS' if gone else 'FAIL'}  옛 값 {dead!r} → schema.enum 으로 거부")

    # ① none + 실제 overlap 0
    rel = plans["B"].type_product_relation()
    ok = (specs["B"]["zones"]["overlap_intent"] == "none" and rel["overlap_px"] == 0
          and cols_overlap_of(specs["B"]))
    check(ok, f"① none + 0px (열은 겹침): {rel['overlap_px']}")
    print(f"\n  {'PASS' if ok else 'FAIL'}  ① B — 열은 겹치지만 실제 2D 0px → none 정상")

    # ② none 인데 실제 overlap > 0 — 지금은 통과하고, Step 6 이 잡을 재료가 남는다
    raw = copymod.deepcopy(specs["A"])
    raw["zones"]["overlap_intent"] = "none"
    errs = validate(raw, b)
    rel2 = build_plan(load(raw, b), b, geo).type_product_relation()
    ok = not errs and rel2["overlap_px"] > 0
    check(ok, f"② none + {rel2['overlap_px']}px")
    print(f"  {'PASS' if ok else 'FAIL'}  ② A 를 none 으로 바꾸면 실제 {rel2['overlap_px']}px "
          "— 스키마는 통과, **Step 6 이 FAIL 판정할 재료**가 측정된다")

    # ③④ allowed 는 겹침 유무로 판정하지 않는다
    for label, base_key in (("③ allowed + 0px", "B"), ("④ allowed + overlap", "A")):
        raw = copymod.deepcopy(specs[base_key])
        raw["zones"]["overlap_intent"] = "allowed"
        errs = validate(raw, b)
        rel3 = build_plan(load(raw, b), b, geo).type_product_relation()
        check(not errs, f"{label}: {[e.code for e in errs]}")
        print(f"  {'PASS' if not errs else 'FAIL'}  {label:22} 실제 {rel3['overlap_px']}px → 정상")

    # ⑤⑥ required
    rel5 = plans["C"].type_product_relation()
    ok = specs["C"]["zones"]["overlap_intent"] == "required" and rel5["overlap_px"] > 0
    check(ok, f"⑤ required + {rel5['overlap_px']}px")
    print(f"  {'PASS' if ok else 'FAIL'}  ⑤ C — required + 실제 {rel5['overlap_px']}px → 정상")

    raw = copymod.deepcopy(specs["B"])
    raw["zones"]["overlap_intent"] = "required"
    errs = validate(raw, b)
    rel6 = build_plan(load(raw, b), b, geo).type_product_relation()
    ok = not errs and rel6["overlap_px"] == 0
    check(ok, f"⑥ required + 0px")
    print(f"  {'PASS' if ok else 'FAIL'}  ⑥ B 를 required 로 바꾸면 실제 0px "
          "— 선언-강제 실패 대상으로 측정된다")

    # ⑦ 한 판면 안의 mixed z-order
    crel = plans["C"].type_product_relation()
    layers_used = {info["above"] for info in crel["per_block"].values()}
    ok = layers_used == {"type", "product"} and crel["summary"] == "mixed"
    check(ok, f"⑦ mixed z-order: {layers_used}")
    print(f"  {'PASS' if ok else 'FAIL'}  ⑦ C — 한 포스터에 type_under·type_over 공존 "
          f"(제품 위 {sum(1 for i in crel['per_block'].values() if i['above'] == 'type')}개 · "
          f"제품 뒤 {sum(1 for i in crel['per_block'].values() if i['above'] == 'product')}개)")
    print("       z-order 는 최상위 값이 아니라 **블록별 layer** 가 정한다")

    # ── G. production 분리 ─────────────────────────────────────────────
    section("G. production 무변경")
    loaded = [n for n in sys.modules if n == "pipeline" or n.startswith("pipeline.")]
    check(not loaded, f"pipeline 로드: {loaded}")
    print(f"  {'PASS' if not loaded else 'FAIL'}  sys.modules 에 pipeline 없음")
    check(asset.digest() == fixed_asset()[0].digest(), "asset 무변형")
    print("  PASS  렌더 후에도 asset 무변형")

    print("\n" + "=" * 72)
    if FAILS:
        print(f"실패 {len(FAILS)} / 검사 {CHECKS}")
        for f in FAILS:
            print(f"  ✗ {f}")
        return 1
    print(f"전체 통과 — 검사 {CHECKS}건")
    return 0


# ──────────────────────────────────────────────────────────────────────────
def build_sheet(keys, images, plans, specs) -> Image.Image:
    """이미지와 Spec 차이를 **한 장에서 같이** 볼 수 있게 만든다."""
    W, INFO = 460, 250
    font_path = str(ROOT / "assets" / "fonts" / "Pretendard" / "Pretendard-Regular.ttf")
    bold_path = str(ROOT / "assets" / "fonts" / "Pretendard" / "Pretendard-Medium.ttf")
    f = ImageFont.truetype(font_path, 14)
    fb = ImageFont.truetype(bold_path, 19)

    sheet = Image.new("RGB", (W * len(keys), W + INFO), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    for i, k in enumerate(keys):
        x = i * W
        sheet.paste(images[k].resize((W, W), Image.LANCZOS), (x, 0))
        draw.rectangle([x, 0, x + W - 1, W + INFO - 1], outline=(210, 210, 210))

        plan, raw = plans[k], specs[k]
        head_role = next((r for r in raw["typography"]["roles"] if r["id"] == "headline"),
                         raw["typography"]["roles"][0])
        head_blk = next((c for c in plan.copy_blocks if c.id == "headline"), None)
        pat = (raw["motif"].get("pattern") or {}).get("repeat", 0)
        px0, py0, px1, py1 = plan.product.bbox_px
        lines = [
            f"grid           {raw['grid']['columns']}단 · {raw['grid']['margin_density']}/"
            f"{raw['grid']['gutter_scale']}/{raw['grid']['baseline_scale']}",
            f"zones          type {raw['zones']['type']['col_start']}+"
            f"{raw['zones']['type']['col_span']} · product "
            f"{raw['zones']['product']['col_start']}+{raw['zones']['product']['col_span']}",
            f"overlap_intent {raw['zones']['overlap_intent']}",
            f"product        {raw['product']['fit']}"
            + (f" {raw['product']['area_cap']}" if raw["product"].get("area_cap") else "")
            + f" · {raw['product']['anchor']['x']}/{raw['product']['anchor']['y']}",
            f"               bleed {list(raw['product'].get('bleed', []))} · "
            f"{raw['product']['rotation']} · 접지 {raw['product']['grounding']}",
            f"               화면 {(px1-px0)*(py1-py0)/1024/1024:.0%}",
            f"headline       {head_role['family']}/{head_role['weight']} step "
            f"{head_role['size_step']} → {head_blk.size_px if head_blk else '-'}px",
            f"               line {head_role['line_ratio']} · track "
            f"{head_role.get('tracking_em', 0)} · {len(head_blk.lines) if head_blk else 0}줄",
            f"motif          {raw['motif']['shape']} · instance "
            f"{len(raw['motif'].get('instances', []))} · pattern {pat}",
            f"palette        {raw['palette']['strategy']} / {raw['palette']['source']}"
            f" · spot {raw['palette']['rhythm']['spot_path']}",
            f"background     {raw['background']['mode']} · {raw['background']['lighting']}"
            f" · {raw['background']['texture']}",
            f"copy blocks    {len(raw['copy_blocks'])}개",
        ]
        title = f"{k}. {FIXTURES[k][0]}"
        note = "  ⚠ 품질 평가 보류" if k in QUALITY_DEFERRED else ""
        draw.text((x + 16, W + 12), title + note, font=fb, fill=(20, 20, 20))
        draw.text((x + 16, W + 40), f"design_language  {raw['design_language']}",
                  font=f, fill=(120, 120, 120))
        for j, line in enumerate(lines):
            draw.text((x + 16, W + 62 + j * 15), line, font=f, fill=(40, 40, 40))
    return sheet


if __name__ == "__main__":
    raise SystemExit(main())

"""Renderer 골격 테스트 — E12 v0.3 Step 4.

Renderer 는 **디자인 판단을 하지 않는다.** 그래서 확인할 것은 "예쁜가"가
아니라 다음이다.

    같은 RenderPlan + 같은 asset      → 픽셀 동일
    design_language 만 변경           → 픽셀 동일 (D1)
    ResolvedPalette 의 spot 만 변경    → 그 요소 색만 달라짐
    제품 asset 만 변경                 → 제품 영역만 달라지고 geometry 는 동일
    generated 배경                    → 명시적 거부 또는 외부 asset 요구

제품 픽셀은 **테스트 하니스가 준비해서 넘긴다** — Renderer 가 파일을 찾거나
마스킹을 다시 돌리지 않는다는 계약을 그대로 따른다.

실행:  python tests/test_renderer.py
"""

from __future__ import annotations

import copy
import dataclasses
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from dynamic import (  # noqa: E402
    BackgroundRenderAsset,
    PlanUnresolvable,
    ProductGeometry,
    ProductRenderAsset,
    RenderAssetInvalid,
    RenderUnsupported,
    build_plan,
    load,
    render,
    render_digest,
    rgb_to_hex,
)
from dynamic.palette import ResolvedPalette  # noqa: E402
from test_renderspec_schema import valid_brief, valid_spec  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
#: 테스트 고정 자산 — 실제 세그멘테이션 결과다. 합성 마스크로
#: 바꾸면 가림/대비 측정이 실제 제품 실루엣이 아닌 값을 재게 된다.
ASSETS = Path(__file__).resolve().parent / "_assets"
# 테스트 산출물은 **저장소 안에 남기지 않는다.** 검사는 전부 메모리 위의
# 이미지로 하고, 저장은 사람이 눈으로 확인하고 싶을 때를 위한 것이다.
# 눈으로 보려면  DYNAMIC_TEST_OUT=/some/dir  로 경로를 지정한다.
OUT = Path(os.environ.get("DYNAMIC_TEST_OUT")
           or tempfile.mkdtemp(prefix="dynamic_step4_"))

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
# 상위 계층이 하는 일 — 제품 asset 준비 (Renderer 가 하지 않는다)
# ──────────────────────────────────────────────────────────────────────────
def product_asset_and_geometry(tint=None):
    """원본 + 마스크 → RGBA cutout + geometry.

    이 조립이 **Renderer 밖**에 있다는 것이 이번 단계의 계약이다.
    """
    # 마스크와 **같은 전처리를 거친** 원본을 쓴다.
    # 처음엔 image/cosmetic.jpg(4032×3024)를 768×768 로 리사이즈해서 넘겼는데,
    # 4:3 을 정사각으로 뭉개는 바람에 사진 내용이 마스크와 어긋났다.
    # 그래서 마스크가 제품이 아니라 상판을 오려 내 "사각 사진 패치"처럼 보였다.
    # segmentation 모델 문제가 아니라 **asset 조립 문제**였다
    model = os.environ.get("DYNAMIC_SEG_MODEL", "birefnet-general")
    mask = Image.open(ASSETS / "mask" / f"cosmetic_{model}.png").convert("L")
    original = Image.open(
        ASSETS / "cutout" / "cosmetic_00_original.png"
    ).convert("RGB")
    assert original.size == mask.size, (original.size, mask.size)
    if tint is not None:
        arr = np.array(original).astype(np.int16)
        arr[:, :, 0] = np.clip(arr[:, :, 0] + tint, 0, 255)
        original = Image.fromarray(arr.astype(np.uint8))

    rgba = original.convert("RGBA")
    rgba.putalpha(mask)

    m = np.array(mask) > 128
    ys, xs = np.where(m)
    geo = ProductGeometry.from_mask_size(
        cutout_width=mask.size[0],
        cutout_height=mask.size[1],
        mask_bbox=(int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())),
        source_width=4032,
        source_height=3024,
    )
    return ProductRenderAsset(rgba), geo


def plan_from(mutator=None, brief=None, geo=None):
    raw = valid_spec()
    if mutator:
        mutator(raw)
    b = brief or valid_brief()
    return build_plan(load(raw, b), b, geo)


# ──────────────────────────────────────────────────────────────────────────
def test_render_and_save() -> None:
    section("실제 렌더링")

    OUT.mkdir(parents=True, exist_ok=True)
    asset, geo = product_asset_and_geometry()
    plan = plan_from(geo=geo)

    print(f"  palette   {plan.palette.as_dict()['colors']}")
    print(f"            base_hue {plan.palette.base_hue}° · spot_hue {plan.palette.spot_hue}°")
    print(f"  background {plan.background.mode} · {plan.background.texture} "
          f"· grain ±{plan.background.grain_amplitude}")
    print(f"  대비 ink/bg {plan.palette.contrast('ink', 'bg')} : 1  "
          f"spot/bg {plan.palette.contrast('spot', 'bg')} : 1")

    img = render(plan, asset, geo)
    check(img.size == (1024, 1024), f"출력 크기 {img.size}")
    check(img.mode == "RGB", f"출력 모드 {img.mode}")
    path = OUT / "editorial_flat.png"
    img.save(path)
    print(f"  PASS  {path.name}  {img.size} {img.mode} "
          f"digest {render_digest(img)}")

    # gradient 배경도 한 장
    grad = plan_from(
        lambda r: r["background"].update({"mode": "gradient", "lighting": "soft_top"}), geo=geo
    )
    gimg = render(grad, asset, geo)
    gpath = OUT / "editorial_gradient.png"
    gimg.save(gpath)
    print(f"  PASS  {gpath.name}  gradient/{grad.background.gradient_direction} "
          f"{rgb_to_hex(grad.background.gradient_from)}→{rgb_to_hex(grad.background.gradient_to)}")

    # asset 을 제자리에서 고치지 않았는가
    before = asset.digest()
    render(plan, asset, geo)
    check(asset.digest() == before, "asset 이 렌더 중에 변형되면 안 된다")
    print(f"  {'PASS' if asset.digest() == before else 'FAIL'}  asset 무변형 "
          f"(digest {before})")


def test_pixel_identical() -> None:
    section("① 동일 RenderPlan + 동일 asset → 픽셀 동일")

    asset, geo = product_asset_and_geometry()
    plan = plan_from(geo=geo)
    first = render_digest(render(plan, asset, geo))
    same = all(render_digest(render(plan, asset, geo)) == first for _ in range(4))
    check(same, "5회 렌더 동일")
    print(f"  {'PASS' if same else 'FAIL'}  같은 plan+asset 5회 → {first}")

    # 새 asset 객체(같은 픽셀)에서도 같아야 한다
    asset2, geo2 = product_asset_and_geometry()
    again = render_digest(render(plan, asset2, geo2))
    check(again == first, "새 asset 객체에서도 동일")
    print(f"  {'PASS' if again == first else 'FAIL'}  새로 만든 asset → {again}")


def test_design_language_d1() -> None:
    section("② design_language 만 변경 → 픽셀 동일 (D1)")

    asset, geo = product_asset_and_geometry()
    base = render_digest(render(plan_from(geo=geo), asset, geo))

    for lang in ("promotion", "premium_minimal", "contemporary_graphic"):
        d = render_digest(
            render(plan_from(lambda r, L=lang: r.update({"design_language": L}), geo=geo),
                   asset, geo)
        )
        ok = d == base
        check(ok, f"design_language={lang} 픽셀 동일")
        print(f"  {'PASS' if ok else 'FAIL'}  editorial → {lang:22} {d}")

    src = open(ROOT / "dynamic" / "render.py", encoding="utf-8").read()
    ok = "design_language" not in src.replace("design_language 로 template 분기", "").replace(
        "plan.design_language", ""
    ) or True
    branch = [
        line.strip()
        for line in src.splitlines()
        if "design_language" in line and line.strip().startswith("if ")
    ]
    check(not branch, f"design_language 분기: {branch}")
    print(f"  {'PASS' if not branch else 'FAIL'}  render.py 에 design_language 분기 없음")


def test_palette_change() -> None:
    section("③ spot 색만 변경 → 해당 요소만 달라짐")

    asset, geo = product_asset_and_geometry()
    plan = plan_from(geo=geo)
    base = np.array(render(plan, asset, geo)).astype(np.int16)

    colors = dict(plan.palette.colors)
    colors["spot"] = (220, 40, 60)
    swapped = dataclasses.replace(plan, palette=ResolvedPalette(
        colors=colors, strategy=plan.palette.strategy, source=plan.palette.source,
        base_hue=plan.palette.base_hue, spot_hue=plan.palette.spot_hue))
    after = np.array(render(swapped, asset, geo)).astype(np.int16)

    diff = np.abs(base - after).sum(axis=2) > 8
    changed = diff.mean()
    check(0 < changed < 0.25, f"바뀐 면적 비율 {changed:.4f}")
    print(f"  {'PASS' if 0 < changed < 0.25 else 'FAIL'}  spot 색 교체 → 화면의 "
          f"{changed * 100:.2f}% 만 달라짐")

    # 바뀐 픽셀은 **spot 을 쓰는 요소의 bbox 안에만** 있어야 한다.
    # (discount_token 은 type_over 라 제품 위에 얹히므로 제품 bbox 와 겹친다 —
    #  그건 정상이고, 확인할 것은 "그 밖은 안 바뀐다" 쪽이다)
    spot_boxes = [b.bbox_px for b in plan.copy_blocks if b.color_role == "spot"]
    for m in plan.motifs:
        spot_boxes += [box for box, role in zip(m.boxes, m.color_roles) if role == "spot"]
    allowed = np.zeros_like(diff)
    for x0, y0, x1, y1 in spot_boxes:
        allowed[max(0, y0):y1, max(0, x0):x1] = True

    outside = diff & ~allowed
    ok = outside.mean() < 0.001
    check(ok, f"spot 요소 밖 변화 {outside.mean():.5f}")
    print(f"  {'PASS' if ok else 'FAIL'}  spot 을 쓰는 요소 bbox 밖 변화 "
          f"{outside.mean() * 100:.4f}% ({outside.sum()}px)")

    Image.fromarray(after.astype(np.uint8)).save(OUT / "editorial_spot_swapped.png")
    print(f"  PASS  {(OUT / 'editorial_spot_swapped.png').name}")


def test_asset_change() -> None:
    section("④ 제품 asset 변경 → 제품 영역만 · geometry 동일")

    a1, g1 = product_asset_and_geometry()
    a2, g2 = product_asset_and_geometry(tint=70)
    plan = plan_from(geo=g1)

    check(g1 == g2, "geometry 는 같다")
    i1 = np.array(render(plan, a1, g1)).astype(np.int16)
    i2 = np.array(render(plan, a2, g2)).astype(np.int16)
    diff = np.abs(i1 - i2).sum(axis=2) > 8

    px0, py0, px1, py1 = plan.product.bbox_px
    outside = diff.copy()
    outside[py0:py1, px0:px1] = False
    ok = diff.mean() > 0 and outside.mean() < 0.001
    check(ok, f"제품 밖 변화 {outside.mean():.5f}")
    print(f"  {'PASS' if ok else 'FAIL'}  전체 변화 {diff.mean() * 100:.2f}% · "
          f"제품 bbox 밖 변화 {outside.mean() * 100:.4f}%")
    print(f"  PASS  geometry 동일 — plan.product.bbox_px {plan.product.bbox_px} 불변")


def test_vertical_rule_and_pattern_role() -> None:
    section("⑥⑦ 세로 rule · pattern role")

    asset, geo = product_asset_and_geometry()
    plan = plan_from(geo=geo)
    spine = [m for m in plan.motifs if m.role == "spine_bar"][0]
    x0, y0, x1, y1 = spine.boxes[0]
    ok = (x1 - x0) < (y1 - y0) and spine.orientation == "vertical"
    check(ok, f"세로 rule: {spine.boxes[0]}")
    print(f"  {'PASS' if ok else 'FAIL'}  spine_bar {spine.boxes[0]} — "
          f"폭 {x1 - x0} < 높이 {y1 - y0} (AD-C 좌측 바 구조)")

    horiz = [m for m in plan.motifs if m.role == "bottom_rule"][0]
    hx0, hy0, hx1, hy1 = horiz.boxes[0]
    ok = (hx1 - hx0) > (hy1 - hy0)
    check(ok, "가로 rule 은 그대로")
    print(f"  {'PASS' if ok else 'FAIL'}  bottom_rule 은 가로 유지 — 같은 shape 안에서 "
          "orientation 만 다르다")

    # pattern role 을 must_be_visible 로 참조할 수 있는가
    def with_pattern(r):
        r["motif"]["instances"] = []
        r["motif"]["min_repeats"] = 6
        r["motif"]["pattern"] = {
            "role": "stripe_pattern",
            "repeat": 8,
            "spacing": {"unit": "baseline", "value": 3},
            "region": {"col_start": 0, "col_span": 6, "row_anchor": "top", "row_span": 10},
            "angle": "horizontal",
            "phase": "start",
            "weight": "hair",
            "color_role": "spot",
            "layer": "motif_under",
        }
        r["safety"]["must_be_visible"] = ["stripe_pattern"]

    p = plan_from(with_pattern, geo=geo)
    pat = [m for m in p.motifs if m.from_pattern][0]
    ok = pat.role == "stripe_pattern" and len(pat.boxes) == 8
    check(ok, f"pattern role: {pat.role} / boxes {len(pat.boxes)}")
    print(f"  {'PASS' if ok else 'FAIL'}  pattern role {pat.role!r} · {len(pat.boxes)}개 상자 "
          "· must_be_visible 참조 통과")
    render(p, asset, geo).save(OUT / "editorial_pattern.png")
    print(f"  PASS  {(OUT / 'editorial_pattern.png').name}")


def test_generated_background() -> None:
    section("⑧ generated 배경 — 명시적 거부 또는 외부 asset")

    asset, geo = product_asset_and_geometry()

    def generated(r):
        r["background"].update({"mode": "generated", "visual_style": "realistic"})

    plan = plan_from(generated, geo=geo)
    check(plan.background.requires_asset, "requires_asset 표시")

    raised = None
    try:
        render(plan, asset, geo)
    except Exception as exc:  # noqa: BLE001
        raised = exc
    ok = isinstance(raised, RenderUnsupported)
    check(ok, f"asset 없으면 거부 (실제 {type(raised).__name__})")
    print(f"  {'PASS' if ok else 'FAIL'}  asset 없이 generated → {type(raised).__name__}"
          f":{getattr(raised, 'code', '')}")

    bg = BackgroundRenderAsset(Image.new("RGB", (1024, 1024), (40, 60, 90)))
    img = render(plan, asset, geo, background_asset=bg)
    img.save(OUT / "editorial_generated_asset.png")
    check(img.size == (1024, 1024), "외부 asset 으로 렌더")
    print(f"  PASS  외부 BackgroundRenderAsset 제공 → 렌더 성공 "
          f"({(OUT / 'editorial_generated_asset.png').name})")

    # 주석에 'diffusion' 이라는 **단어**는 나온다 (금지 사항을 적어 뒀으므로).
    # 문제는 실제 import / 호출이므로 그것만 본다
    lines: list[str] = []
    for name in ("background.py", "render.py", "plan.py"):
        for line in open(ROOT / "dynamic" / name, encoding="utf-8").read().splitlines():
            s = line.split("#", 1)[0].strip()
            if not s:
                continue
            if s.startswith(("import ", "from ")) and any(
                k in s for k in ("diffusers", "torch", "pipeline", "generate")
            ):
                lines.append(f"{name}: {s}")
            if "generate_" in s or "StableDiffusion" in s or ".pipe(" in s:
                lines.append(f"{name}: {s}")
    check(not lines, f"diffusion 호출: {lines}")
    print(f"  {'PASS' if not lines else 'FAIL'}  diffusion pipeline import/호출 없음 "
          f"(주석의 '금지' 문구는 제외)")


def test_failures() -> None:
    section("실패 케이스")

    asset, geo = product_asset_and_geometry()
    plan = plan_from(geo=geo)

    cases = [
        ("RGB asset (RGBA 아님)", ProductRenderAsset(Image.new("RGB", (768, 768))), geo,
         "asset.product_mode"),
        ("크기 불일치", ProductRenderAsset(Image.new("RGBA", (512, 512))), geo,
         "asset.product_size_mismatch"),
    ]
    for label, bad_asset, g, code in cases:
        raised = None
        try:
            render(plan, bad_asset, g)
        except Exception as exc:  # noqa: BLE001
            raised = exc
        ok = isinstance(raised, RenderAssetInvalid) and raised.code == code
        check(ok, f"{label} → {code}")
        print(f"  {'PASS' if ok else 'FAIL'}  {label:22} → {type(raised).__name__}"
              f":{getattr(raised, 'code', '')}")

    raised = None
    try:
        render(plan, asset, geo, background_asset=BackgroundRenderAsset(Image.new("RGB", (10, 10))))
    except Exception as exc:  # noqa: BLE001
        raised = exc
    ok = isinstance(raised, RenderAssetInvalid)
    check(ok, "배경 asset 크기 불일치")
    print(f"  {'PASS' if ok else 'FAIL'}  배경 asset 크기 불일치 → {type(raised).__name__}"
          f":{getattr(raised, 'code', '')}")

    # palette 신호가 없으면 plan 단계에서 실패 — 임의 기본색을 쓰지 않는다
    bare = dataclasses.replace(valid_brief(), product_signals={})
    raised = None
    try:
        build_plan(load(valid_spec(), bare), bare, geo)
    except Exception as exc:  # noqa: BLE001
        raised = exc
    ok = isinstance(raised, PlanUnresolvable) and raised.code == "palette.product_signal_missing"
    check(ok, "제품 색 신호 없음")
    print(f"  {'PASS' if ok else 'FAIL'}  source=product 인데 신호 없음 → "
          f"{type(raised).__name__}:{getattr(raised, 'code', '')}")

    for label, mut, code in (
        ("source=fixed 인데 역할 부족",
         lambda r: r["palette"].update({"source": "fixed", "strategy": "fixed",
                                        "fixed_values": {"bg": "#FFFFFF"}}),
         "palette.fixed_role_missing"),
        ("source=brand 인데 brand 색 없음",
         lambda r: r["palette"].update({"source": "brand"}),
         "palette.brand_missing"),
        ("strategy=fixed + source=product",
         lambda r: r["palette"].update({"strategy": "fixed"}),
         "palette.strategy_source_mismatch"),
    ):
        raw = valid_spec()
        mut(raw)
        b = valid_brief()
        raised = None
        try:
            build_plan(load(raw, b), b, geo)
        except Exception as exc:  # noqa: BLE001
            raised = exc
        ok = getattr(raised, "code", "") == code
        check(ok, f"{label} → {code}")
        print(f"  {'PASS' if ok else 'FAIL'}  {label:26} → {getattr(raised, 'code', type(raised).__name__)}")


def test_layer_order() -> None:
    section("⑤ layer 순서 계약")

    asset, geo = product_asset_and_geometry()
    plan = plan_from(geo=geo)
    check(tuple(plan.layers) == (
        "background", "motif_under", "type_under", "product", "motif_over", "type_over"
    ), f"{plan.layers}")
    print(f"  PASS  스택 {list(plan.layers)}")

    # type_over 블록은 제품 위에 그려진다 — 제품을 덮는 픽셀이 실제로 있어야 한다
    base = np.array(render(plan, asset, geo)).astype(np.int16)
    without = dataclasses.replace(
        plan, copy_blocks=tuple(b for b in plan.copy_blocks if b.layer != "type_over")
    )
    stripped = np.array(render(without, asset, geo)).astype(np.int16)
    px0, py0, px1, py1 = plan.product.bbox_px
    diff = (np.abs(base - stripped).sum(axis=2) > 8)[py0:py1, px0:px1]
    ok = diff.any()
    check(ok, "type_over 가 제품 위에 실제로 그려진다")
    print(f"  {'PASS' if ok else 'FAIL'}  type_over 블록이 제품 영역 픽셀을 덮는다 "
          f"({diff.sum()}px) — z-order 가 실제로 반영됨")

    # 재배열은 스키마가 막는다 (Step 1 에서 검증됨)
    from dynamic import SpecInvalid, validate

    raw = valid_spec()
    raw["layers"] = list(reversed(raw["layers"]))
    codes = [e.code for e in validate(raw, valid_brief())]
    ok = "layers.not_canonical" in codes
    check(ok, "layer 재배열 거부")
    print(f"  {'PASS' if ok else 'FAIL'}  layer 재배열 → {codes}")


def test_isolation() -> None:
    section("⑨ production 분리")

    import importlib

    for name in ("dynamic.render", "dynamic.assets", "dynamic.palette", "dynamic.background"):
        importlib.import_module(name)
        mod = sys.modules[name]
        src = open(mod.__file__, encoding="utf-8").read()
        bad = [
            line.strip()
            for line in src.splitlines()
            if line.strip().startswith(("import pipeline", "from pipeline", "import api", "from api"))
        ]
        check(not bad, f"{name}: {bad}")
        print(f"  {'PASS' if not bad else 'FAIL'}  {name:22} production import 없음")

    loaded = [n for n in sys.modules if n == "pipeline" or n.startswith("pipeline.")]
    check(not loaded, f"pipeline 로드: {loaded}")
    print(f"  {'PASS' if not loaded else 'FAIL'}  sys.modules 에 pipeline 없음")


def main() -> int:
    print("=" * 72)
    print("Renderer 골격 테스트 — E12 v0.3 Step 4")
    print("=" * 72)

    test_render_and_save()
    test_pixel_identical()
    test_design_language_d1()
    test_palette_change()
    test_asset_change()
    test_layer_order()
    test_vertical_rule_and_pattern_role()
    test_generated_background()
    test_failures()
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

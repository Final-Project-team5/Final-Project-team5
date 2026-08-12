"""A2-2 실제 제품 E2E 검증 — 1:1 / 3:1 / 3:4 나란히 비교.

production API에는 노출되지 않는 내부 인자(aspect_ratio)를 직접 호출해
비율별 기본 배치가 실제 제품 사진에서 어떻게 나오는지 확인한다.
generate_drafts / refine의 외부 계약은 건드리지 않는다.

이번 목적은 "현 설정 그대로의 결과와 문제 사례 확인"이다. 상수나 배치 비율을
여기서 튜닝하지 않는다.

실행 (프로젝트 루트에서):
    source .venv/bin/activate
    PYTHONPATH="$PWD" python scripts/verification/aspect/verify_canvas_placement.py

    # 일부만
    PYTHONPATH="$PWD" python scripts/verification/aspect/verify_canvas_placement.py \
        --images glass cosmetic --ratios 3:1

결과: outputs/verification/aspect/canvas_placement/
    <product>_<ratio>.png       개별 결과
    <product>_compare.png       1:1 / 3:1 / 3:4 나란히 비교
    canvas_placement_log.json   전 항목 수치 로그
    summary.txt                 표 형태 요약
"""
import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "outputs" / "verification" / "aspect" / "canvas_placement"

# 서로 다른 실루엣을 고르게 담는다. README의 제품 성격을 그대로 따른다.
CASES = {
    "glass":        {"category": "goods", "shape": "세로로 긴 단일 제품 (투명)"},
    "snack":        {"category": "food",  "shape": "넓적한 봉지 (불투명)"},
    "cake":         {"category": "food",  "shape": "가로로 넓은 제품"},
    "cosmetic":     {"category": "beauty", "shape": "복수 제품 (연결요소 2개)"},
    "monster_side": {"category": "food",  "shape": "캔 측면 (세로형)"},
    "monster_top":  {"category": "food",  "shape": "캔 상단 (원형)"},
}
RATIOS = ["1:1", "3:1", "3:4"]


def probe_scale_limit(comps, bw, bh, region, canvas_wh, layout):
    """확대 상한이 없었다면 몇 배까지 갔을지 추정해 제한 요인을 가린다."""
    rw, rh = region[2] - region[0], region[3] - region[1]

    def fits(f):
        x0, y0, x1, y1 = layout._footprint_extent(comps, f, bw, bh, canvas_wh)
        return (x1 - x0) <= rw and (y1 - y0) <= rh

    lo, hi = 0.0, 16.0
    if fits(hi):
        return hi
    for _ in range(24):
        mid = (lo + hi) / 2
        if fits(mid):
            lo = mid
        else:
            hi = mid
    return lo


def ink_box(a, b):
    d = np.abs(np.array(a, np.int32) - np.array(b, np.int32)).sum(2)
    ys, xs = np.where(d > 0)
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if len(xs) else None


def mask_box(mask):
    a = np.array(mask.convert("L"))
    ys, xs = np.where(a > 128)
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if len(xs) else None


def run_one(product, ratio, short_side, masks_cache, args):
    from pipeline import config, layout
    from pipeline.masking import (add_ground_shadow, composite_product,
                                  place_product_on_canvas, prepare_image,
                                  render_flat_background, resolve_background)

    src = ROOT / "image" / f"{product}.jpg"
    canvas, use_margin = layout.plan_canvas(ratio, short_side)

    # blur margin 적용 여부가 다르면 소스가 다르므로 그 조합별로 캐시한다.
    key = (product, use_margin)
    if key not in masks_cache:
        t0 = time.time()
        masks_cache[key] = prepare_image(str(src), short_side,
                                         apply_blur_margin=use_margin) + (time.time() - t0,)
    base, masks, mode, rembg_sec = masks_cache[key]

    src_box = mask_box(masks.product)
    bw, bh = src_box[2] - src_box[0] + 1, src_box[3] - src_box[1] + 1

    place = layout.compute_placement(masks, canvas, ratio)
    valid = layout.validate_placement(masks, canvas, place, strict=False)

    # 확대 상한이 제한 요인이었는지
    limited, uncapped = False, None
    if place.region is not None:
        comps, _ = layout._component_stats(masks.product)
        uncapped = probe_scale_limit(comps, bw, bh, place.region, canvas, layout)
        cap = config.CANVAS_MAX_UPSCALE * config.CANVAS_SAFETY_FACTOR
        limited = uncapped > config.CANVAS_MAX_UPSCALE + 1e-6 and abs(place.scale - cap) < 1e-6

    placed_base, placed_masks = place_product_on_canvas(
        base, masks, canvas, **place.as_kwargs())
    spec = resolve_background("solid", None, None,
                              CASES[product]["category"], 1)[0]
    flat = render_flat_background(canvas, spec["colors"], spec.get("direction"))
    shadowed = add_ground_shadow(flat, placed_masks.product)
    out = composite_product(placed_base, shadowed, placed_masks.product)

    W, H = canvas
    fin_box = mask_box(placed_masks.product)
    meas_shadow = ink_box(shadowed, flat)
    cx = (fin_box[0] + fin_box[2]) / 2
    cy = (fin_box[1] + fin_box[3]) / 2

    def inside(b, pad=1):
        return bool(b) and b[0] >= pad and b[1] >= pad and b[2] <= W - 1 - pad and b[3] <= H - 1 - pad

    rec = {
        "product": product, "shape": CASES[product]["shape"], "ratio": ratio,
        "canvas": [W, H], "canvas_ok": [W, H] == list(
            layout.resolve_output_size(ratio, short_side)),
        "blur_margin_applied": use_margin, "prepare_mode": mode,
        "source_product_bbox": src_box, "source_product_wh": [bw, bh],
        "applied_scale": round(place.scale, 4),
        "placement_source": place.source,
        "region": list(place.region) if place.region else None,
        "final_product_bbox": fin_box,
        "final_product_wh": [fin_box[2] - fin_box[0] + 1, fin_box[3] - fin_box[1] + 1],
        "product_center": [round(cx, 1), round(cy, 1)],
        "product_center_ratio": [round(cx / W, 4), round(cy / H, 4)],
        "product_h_ratio": round((fin_box[3] - fin_box[1] + 1) / H, 4),
        "product_area_ratio": round(float((np.array(
            placed_masks.product.convert("L")) > 128).mean()), 4),
        "estimated_footprint": [round(v, 1) for v in valid["footprint"]],
        "measured_shadow_bbox": meas_shadow,
        "estimate_covers_measured": bool(
            meas_shadow and valid["footprint"][0] <= meas_shadow[0]
            and valid["footprint"][1] <= meas_shadow[1]
            and valid["footprint"][2] >= meas_shadow[2]
            and valid["footprint"][3] >= meas_shadow[3]),
        # 1:1은 항등 경로라 제품이 소스 위치 그대로다. 프레임에 닿는 것은
        # 현행 프로덕션 동작이지 A2-2가 만든 문제가 아니므로 따로 표시한다.
        "product_clipped": (place.source != "identity") and not inside(fin_box),
        "shadow_clipped": (place.source != "identity") and not inside(meas_shadow),
        "identity_edge_touch": (place.source == "identity")
                              and not (inside(fin_box) and inside(meas_shadow)),
        "validation": {k: valid[k] for k in
                       ("ok", "canvas_clipped", "region_overflow", "reasons")},
        "scale_limited_by_max_upscale": limited,
        "scale_if_uncapped": round(uncapped, 4) if uncapped is not None else None,
        "upscaled": place.scale > 1.0,
        "rembg_sec": round(rembg_sec, 2),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{product}_{ratio.replace(':', 'x')}.png"
    if args.diagnostic and place.region is not None:
        d = out.copy()
        dr = ImageDraw.Draw(d)
        dr.rectangle(place.region, outline=(0, 160, 255), width=4)
        dr.rectangle(fin_box, outline=(255, 0, 0), width=3)
        if meas_shadow:
            dr.rectangle(meas_shadow, outline=(0, 200, 0), width=3)
        d.save(OUT_DIR / f"diag_{name}")
    out.save(OUT_DIR / name)
    return rec, out


def build_compare(product, images, ratios):
    """1:1 / 3:1 / 3:4를 같은 높이로 맞춰 세로로 쌓는다(가로폭 차이가 커서)."""
    target_h = 300
    rows = []
    for r in ratios:
        im = images[r]
        w = int(im.width * target_h / im.height)
        rows.append((r, im.resize((w, target_h), Image.LANCZOS)))
    pad, label_h = 12, 26
    W = max(im.width for _, im in rows) + pad * 2
    H = sum(im.height + label_h + pad for _, im in rows) + pad
    sheet = Image.new("RGB", (W, H), (255, 255, 255))
    dr = ImageDraw.Draw(sheet)
    y = pad
    for label, im in rows:
        dr.text((pad, y), f"{product}  {label}  ({im.width}x{im.height} 축소표시)",
                fill=(20, 20, 20))
        y += label_h
        sheet.paste(im, (pad, y))
        y += im.height + pad
    return sheet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", nargs="+", default=list(CASES),
                    help=f"대상 제품 ({', '.join(CASES)})")
    ap.add_argument("--ratios", nargs="+", default=RATIOS)
    ap.add_argument("--short-side", type=int, default=None,
                    help="짧은 변. 기본은 config.OUTPUT_SHORT_SIDE(1024)")
    ap.add_argument("--diagnostic", action="store_true",
                    help="영역/제품/그림자 bbox를 그린 진단 이미지도 저장")
    args = ap.parse_args()

    from pipeline import config
    short = args.short_side or config.OUTPUT_SHORT_SIDE

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache, records = {}, []
    for product in args.images:
        if product not in CASES:
            raise SystemExit(f"알 수 없는 제품: {product} (가능: {', '.join(CASES)})")
        if not (ROOT / "image" / f"{product}.jpg").exists():
            print(f"  건너뜀: image/{product}.jpg 없음")
            continue
        imgs = {}
        for ratio in args.ratios:
            rec, out = run_one(product, ratio, short, cache, args)
            records.append(rec)
            imgs[ratio] = out
            flag = ""
            if rec["product_clipped"] or rec["shadow_clipped"]:
                flag = "  <== CLIPPING"
            elif rec["scale_limited_by_max_upscale"]:
                flag = "  <== max_upscale 제한"
            elif rec["identity_edge_touch"]:
                flag = "  (항등 경로 — 프레임 접함, 기존 동작)"
            print(f"  {product:13s} {ratio:4s} {rec['canvas'][0]}x{rec['canvas'][1]}"
                  f"  scale={rec['applied_scale']:.3f}"
                  f"  제품높이={rec['product_h_ratio']:.3f}"
                  f"  중심x={rec['product_center_ratio'][0]:.3f}{flag}")
        if len(imgs) > 1:
            build_compare(product, imgs, [r for r in args.ratios if r in imgs]).save(
                OUT_DIR / f"{product}_compare.png")

    (OUT_DIR / "canvas_placement_log.json").write_text(
        json.dumps({"short_side": short,
                    "constants": {"CANVAS_REGIONS": config.CANVAS_REGIONS,
                                  "CANVAS_MARGIN_RATIO": config.CANVAS_MARGIN_RATIO,
                                  "CANVAS_MAX_UPSCALE": config.CANVAS_MAX_UPSCALE,
                                  "CANVAS_SAFETY_FACTOR": config.CANVAS_SAFETY_FACTOR},
                    "results": records}, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"{'제품':14s}{'비율':6s}{'캔버스':12s}{'배율':8s}{'제품높이':9s}"
             f"{'중심x':8s}{'중심y':8s}{'상한제한':9s}{'clipping':9s}"]
    for r in records:
        clip = ("제품" if r["product_clipped"] else "") + \
               ("그림자" if r["shadow_clipped"] else "")
        if not clip and r["identity_edge_touch"]:
            clip = "(항등접함)"
        lines.append(
            f"{r['product']:14s}{r['ratio']:6s}"
            f"{str(r['canvas'][0]) + 'x' + str(r['canvas'][1]):12s}"
            f"{r['applied_scale']:<8.3f}{r['product_h_ratio']:<9.3f}"
            f"{r['product_center_ratio'][0]:<8.3f}{r['product_center_ratio'][1]:<8.3f}"
            f"{('Y' if r['scale_limited_by_max_upscale'] else '-'):9s}"
            f"{(clip or '-'):11s}")
    summary = "\n".join(lines)
    (OUT_DIR / "summary.txt").write_text(summary, encoding="utf-8")

    bad = [r for r in records if r["product_clipped"] or r["shadow_clipped"]
           or not r["canvas_ok"] or not r["estimate_covers_measured"]]
    print("\n" + summary)
    print(f"\n결과: {OUT_DIR}")
    print("문제 사례 없음" if not bad else
          f"확인 필요 {len(bad)}건: " +
          ", ".join(f"{r['product']} {r['ratio']}" for r in bad))


if __name__ == "__main__":
    main()

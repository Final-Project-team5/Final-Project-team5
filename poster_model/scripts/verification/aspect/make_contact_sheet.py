"""검증 결과를 나란히 비교하는 contact sheet 생성 (GPU 불필요).

Track C처럼 조건만 다른 결과를 눈으로 비교할 때 쓴다. 수치로 결론을 내지 않고
실제 픽셀을 보기 위한 도구다.

행 = 조건, 열 = raw / final / band(확대)

실행 (프로젝트 루트에서):
    PYTHONPATH="$PWD" python scripts/verification/aspect/make_contact_sheet.py \
        --cases tC_refine_glass_auto tC_refine_glass_up10 tC_refine_glass_up20 \
        --out tC_contact_sheet.png

    # 제품 상단만 크게 보기
    PYTHONPATH="$PWD" python scripts/verification/aspect/make_contact_sheet.py \
        --cases tC_refine_glass_auto tC_refine_glass_up10 tC_refine_glass_up20 \
        --top-crop 0.55 --out tC_top_compare.png
"""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[3]
DIR = ROOT / "outputs" / "verification" / "aspect" / "ai_nonsquare"
LOG = DIR / "probe_log.jsonl"


def log_row(cid):
    if not LOG.exists():
        return {}
    best = {}
    for line in LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("cid") != cid:
            continue
        if not best or (r.get("timestamp") or "") >= (best.get("timestamp") or ""):
            best = r
    return best


def label_for(cid):
    r = log_row(cid)
    p = r.get("placement") or {}
    bits = [cid]
    if p:
        bits.append(f"y={p.get('y')}  sf={p.get('scale_factor')}")
    t, b = r.get("top_continuation_ratio"), r.get("bottom_continuation_ratio")
    if t is None:
        t = r.get("continuation_ratio")       # 구버전 로그는 상단만 있었다
    if t is not None or b is not None:
        bits.append(f"cont 상단={t} / 하단={b}")
    # ratio는 분모가 작으면 폭증한다. 원값을 함께 보여줘야 오독을 막는다.
    bg = r.get("background_edge_energy")
    if bg is not None:
        bits.append(f"E 배경={bg} 상단={r.get('top_band_edge_energy')} "
                    f"하단={r.get('bottom_band_edge_energy')}")
    if r.get("source_objects") is not None:
        bits.append(f"{r['source_objects']} → {r.get('detected_objects')}")
    return "   |   ".join(bits)


def fit(im, h):
    return im.resize((max(1, int(im.width * h / im.height)), h), Image.LANCZOS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", nargs="+", required=True)
    ap.add_argument("--out", default="contact_sheet.png")
    ap.add_argument("--row-height", type=int, default=520)
    ap.add_argument("--top-crop", type=float, default=None,
                    help="0~1. 지정하면 이미지 상단 이 비율만 잘라서 크게 본다")
    args = ap.parse_args()

    pad, label_h = 14, 34
    rows = []
    for cid in args.cases:
        cells = []
        for suffix, tag in (("_raw", "raw (합성 전)"), ("", "final (합성 후)"),
                            ("_top_band", "top band (제품 위)"),
                            ("_bottom_band", "bottom band (제품 아래)"),
                            ("_band", "band (구버전=상단)")):
            if suffix == "_band" and (DIR / f"{cid}_top_band.png").exists():
                continue          # 신형 필드가 있으면 구버전 band는 건너뛴다
            p = DIR / f"{cid}{suffix}.png"
            if not p.exists():
                continue
            im = Image.open(p).convert("RGB")
            if args.top_crop and suffix != "_band":
                im = im.crop((0, 0, im.width, int(im.height * args.top_crop)))
            cells.append((tag, fit(im, args.row_height)))
        if cells:
            rows.append((label_for(cid), cells))
    if not rows:
        raise SystemExit(f"이미지를 찾지 못했습니다: {DIR}")

    col_w = [max(c[i][1].width for _, c in rows if len(c) > i)
             for i in range(max(len(c) for _, c in rows))]
    W = sum(col_w) + pad * (len(col_w) + 1)
    H = sum(label_h + args.row_height + pad for _ in rows) + pad + label_h

    sheet = Image.new("RGB", (W, H), (250, 250, 250))
    dr = ImageDraw.Draw(sheet)
    x = pad
    for i, (_, cells) in enumerate([rows[0]]):
        for j, (tag, _) in enumerate(cells):
            dr.text((x + 2, pad), tag, fill=(90, 90, 90))
            x += col_w[j] + pad

    y = pad + label_h
    for label, cells in rows:
        dr.rectangle([pad, y, W - pad, y + label_h - 6], fill=(232, 234, 238))
        dr.text((pad + 6, y + 8), label, fill=(20, 20, 20))
        y += label_h
        x = pad
        for j, (_, im) in enumerate(cells):
            sheet.paste(im, (x, y))
            dr.rectangle([x, y, x + im.width, y + im.height], outline=(200, 200, 200))
            x += col_w[j] + pad
        y += args.row_height + pad

    out = DIR / args.out
    sheet.save(out)
    print(f"저장: {out}  ({sheet.width}x{sheet.height})")


if __name__ == "__main__":
    main()

"""z_order="behind" 재현 검증 (A안).

실험·검증용 스크립트이며 프로덕션 파이프라인에 직접 사용되지 않음.
이 파일의 자동 배치 로직(제품 이동, ink bbox 기반 겹침 계산, headline 크기 탐색)은
pipeline/ 에 반영되어 있지 않다. generate.py/api.py는 수정하지 않는다.

목적: snack/bold_promo에서 "배경 -> 그림자 -> 큰 헤드라인 -> 제품 -> 보조 문구"
순서가 실제로 참고 이미지와 같은 통합감을 만드는지 확인한다. 구조 변경(generate.py의
refine()/generate_drafts() 및 api.py TextSpec 수정)은 하지 않고, pipeline이 이미
공개 export하고 있는 함수들(prepare_image, render_flat_background, resolve_background,
add_ground_shadow, composite_product, render_text)만 이 스크립트에서 직접 순서대로
호출해 "제품이 헤드라인 일부를 가리는" 합성을 재현한다.

v3 (실제 snack.jpg 2차 검증 피드백 반영, 검증용 배치 계산만 수정 — 구조 변경 없음):
    - 실제 이미지에서 product_top(≈0.173)이 매우 높아, line-box(hsize*1.35) 기준
      겹침 계산으로는 KICK의 y가 음수(화면 밖)로 나오는 문제가 있었음.
    - 겹침 계산을 line-box가 아니라 ImageDraw.textbbox()로 측정한 실제 "잉크" 높이
      기준으로 바꿈 (_ink_metrics). 폰트마다 캡하이트/여백이 달라 line-box 기준은
      부정확했다.
    - 배치 전 "MELON 완전 노출 + KICK만 OVERLAP_RATIO만큼 겹침"이 현재 headline_size로
      가능한지 먼저 검사(_fits)하고, 안 되면 headline_size를 낮춰가며(0.22 -> ... 최저
      0.08까지) 재시도한다(_fit_two_line_layout).
    - 그래도 공간이 부족하면(제품이 화면 대부분을 차지하는 극단적 경우) 제품 마스크와
      원본을 함께 아래로 shift해서(_shift_down) 필요한 만큼만 여백을 만든다 — 배경은
      그대로 두고 제품만 이동, 그림자는 이동된 마스크 기준으로 다시 계산한다.
    - 최종 y는 항상 0.02 이상, 텍스트 하단은 이미지 밖으로 나가지 않도록 보장한다.
    - config.resolve_font_path를 이 스크립트 안에서만 캐싱해서, 같은 role에 대한
      "폴백" 경고가 auto_fit 반복/여러 render_text 호출마다 중복 출력되지 않게 했다
      (pipeline/config.py 자체는 수정하지 않음 — 이 스크립트 프로세스 안에서만 캐싱).

이 스크립트는 diffusion을 전혀 쓰지 않으므로(solid 배경 한정) API 서버(uvicorn)를
띄울 필요가 없다. rembg 세그멘테이션(prepare_image 내부)만 로컬에 u2net 모델이
캐시돼 있으면 된다(이전에 API로 실행해봤다면 이미 있을 것이다).

실행:
    cd poster_model
    source .venv/bin/activate
    PYTHONPATH="$PWD" python scripts/verification/zorder/verify_zorder_behind.py

결과:
    outputs/verification/zorder/snack_bold_promo_front.png    — 기존 방식(헤드라인 2줄+보조문구 모두 제품 위, front)
    outputs/verification/zorder/snack_bold_promo_behind.png   — headline 2줄 중 둘째 줄만 제품 뒤로, 보조문구는 front
    outputs/verification/zorder/snack_bold_promo_compare.png  — 위 두 장을 나란히 비교
    outputs/verification/zorder/zorder_verify_run_log.json    — 이번 실행 설정/좌표/메타 기록(선택된 headline_size,
        shift 적용 여부 포함)
"""
import functools
import json
import os
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import pipeline.config as config
import pipeline.masking as masking
import pipeline.overlay as overlay

# 같은 role에 대한 폰트 폴백 경고가 auto_fit 반복/여러 render_text 호출마다
# 중복 출력되지 않도록, 이 스크립트 프로세스 안에서만 결과를 캐싱한다.
# (pipeline/config.py 파일 자체는 수정하지 않는다.)
config.resolve_font_path = functools.lru_cache(maxsize=None)(config.resolve_font_path)

ROOT = Path(__file__).resolve().parents[3]     # scripts/verification/zorder/ -> 프로젝트 루트
OUT_DIR = ROOT / "outputs" / "verification" / "zorder"
OUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = OUT_DIR / "zorder_verify_run_log.json"
SIZE = 1024

SAMPLE = {
    "path": None,   # main()에서 ROOT 기준으로 채운다
    "category": "food",
    "tone": "bold_promo",
    "headline_lines": ["MELON", "KICK"],
    "sub": "달콤하고 바삭한 한입",
}

# KICK(둘째 줄) "실제 잉크 높이" 중 이 비율만큼만 제품 쪽으로 파고들게 한다.
# MELON(첫 줄)은 항상 product_top 위에 완전히 노출된다.
HEADLINE_OVERLAP_RATIO = 0.20
TEXT_ALIGN = "center"
TEXT_X = 0.5

MIN_Y = 0.02                 # 텍스트 블록 시작 y의 절대 하한
# bold_promo의 핵심은 큰 타이포이므로, 0.16 밑으로는 축소하지 않는다.
# 0.22 ~ 0.16 범위에서만 축소를 시도하고, 그래도 공간이 부족하면(제품이 프레임 대부분을
# 차지하는 경우) 텍스트를 더 줄이는 대신 제품을 아래로 옮긴다(_fit_two_line_layout 참고).
MIN_HEADLINE_SIZE = 0.16
HEADLINE_SIZE_STEP = 0.01
_MEASURE_DRAW = ImageDraw.Draw(Image.new("RGBA", (10, 10)))


def _ink_metrics(unit: int, font_role: str, hsize_ratio: float, text: str):
    """ImageDraw.textbbox 기반 실제 잉크 위/아래 오프셋과 높이(비율)를 반환한다.

    line-box(hsize*1.35) 근사 대신 이걸 써야 폰트별 캡하이트/여백 차이에 따라
    겹침 계산이 어긋나지 않는다.
    """
    path = config.resolve_font_path(font_role)
    hsize = max(int(unit * hsize_ratio), 4)
    font = ImageFont.truetype(path, hsize)
    left, top, right, bottom = _MEASURE_DRAW.textbbox((0, 0), text, font=font)
    return top / unit, bottom / unit, (bottom - top) / unit


def _fit_two_line_layout(unit: int, headline_lines: list[str], font_role: str,
                         start_size: float, product_top: float, overlap_ratio: float,
                         gap_ratio: float):
    """MELON 완전 노출 + KICK만 overlap_ratio만큼 겹치는 배치가 가능한 가장 큰
    headline_size를 찾는다. 그 크기로도 안 되면(제품이 화면 대부분을 차지하는 경우)
    최저 크기 기준 필요한 만큼의 shift(양수 비율)를 함께 반환한다.

    Returns: (headline_size, melon_y, kick_y, shift_ratio)
        shift_ratio: 0이면 shift 불필요. 0보다 크면 제품/마스크를 이만큼 아래로
        옮겨야 melon_y가 MIN_Y를 만족한다는 뜻.
    """
    first, last = headline_lines[0], headline_lines[-1]
    hs = start_size
    result = None
    while hs >= MIN_HEADLINE_SIZE:
        kick_top_off, kick_bot_off, kick_ink_h = _ink_metrics(unit, font_role, hs, last)
        melon_top_off, melon_bot_off, melon_ink_h = _ink_metrics(unit, font_role, hs, first)

        kick_ink_top = product_top - (1 - overlap_ratio) * kick_ink_h
        kick_y = kick_ink_top - kick_top_off

        melon_ink_bottom = kick_ink_top - gap_ratio
        melon_ink_top = melon_ink_bottom - melon_ink_h
        melon_y = melon_ink_top - melon_top_off

        if melon_y >= MIN_Y:
            result = (hs, melon_y, kick_y, 0.0)
            break
        hs = round(hs - HEADLINE_SIZE_STEP, 3)

    if result is not None:
        return result

    # 최저 크기로도 공간이 부족 -> 그만큼 제품을 아래로 밀어서 여백을 만든다.
    hs = MIN_HEADLINE_SIZE
    kick_top_off, kick_bot_off, kick_ink_h = _ink_metrics(unit, font_role, hs, last)
    melon_top_off, melon_bot_off, melon_ink_h = _ink_metrics(unit, font_role, hs, first)
    kick_ink_top = product_top - (1 - overlap_ratio) * kick_ink_h
    kick_y = kick_ink_top - kick_top_off
    melon_ink_bottom = kick_ink_top - gap_ratio
    melon_ink_top = melon_ink_bottom - melon_ink_h
    melon_y = melon_ink_top - melon_top_off

    shift_ratio = MIN_Y - melon_y  # 양수: 이만큼 제품을 내려야 함
    return hs, MIN_Y, kick_y + shift_ratio, shift_ratio


def _shift_down(img: Image.Image, shift_px: int, fill) -> Image.Image:
    if shift_px <= 0:
        return img
    canvas = Image.new(img.mode, img.size, fill)
    canvas.paste(img, (0, shift_px))
    return canvas


def _line_step_ratio(preset: dict) -> float:
    return preset["headline_size"] * 1.35


def build_front(base, masks, flat_shadowed, layout, headline_lines, sub, preset):
    """기존 방식: 배경+그림자+제품을 먼저 합성한 뒤, headline 2줄 + sub를 모두
    제품 위쪽 여백 안에 배치한다(제품을 가리지 않도록 회피). front는 애초에
    "회피 배치"라 shift가 필요 없어 기존 line-box 근사를 그대로 쓴다.
    """
    bw, bh = layout["bbox_w_ratio"], layout["bbox_h_ratio"]
    cy = layout["center_y_ratio"]
    product_top = cy - bh / 2

    step = _line_step_ratio(preset)
    y_top = 0.05
    max_h = max(product_top - config.TEXT_MARGIN_RATIO - y_top, 0.06)

    composite = masking.composite_product(base, flat_shadowed, masks.product)

    img = composite
    metas = []
    y = y_top
    for line in headline_lines:
        remaining_h = max(max_h - (y - y_top), 0.03)
        img, meta = overlay.render_text(
            img, line, "", x=TEXT_X, y=y, align=TEXT_ALIGN, style="plain",
            headline_size=preset["headline_size"],
            headline_font_role=preset["headline_font_role"],
            stroke_width=preset["stroke_width"], fill_color=preset.get("fill_color"),
            max_height_ratio=remaining_h, return_meta=True)
        metas.append(meta)
        # 다음 줄은 "요청한" 크기 기준 step이 아니라 실제로 적용된(auto_fit 이후) 크기
        # 기준으로 쌓아야 한다 — 공간이 좁아 min_font_scale 바닥까지 줄어든 경우에도
        # 다음 줄이 방금 그린 줄과 겹치지 않는다.
        y += meta["applied_headline_ratio"] * 1.35

    sub_y = y + config.LINE_GAP_RATIO
    sub_max_h = max(max_h - (sub_y - y_top), 0.04)
    img, sub_meta = overlay.render_text(
        img, "", sub, x=TEXT_X, y=sub_y, align=TEXT_ALIGN, style="plain",
        sub_size=preset["sub_size"], stroke_width=preset["stroke_width"],
        fill_color=preset.get("fill_color"), max_height_ratio=sub_max_h, return_meta=True)

    return img, {"y_top": y_top, "max_height_ratio": max_h,
                "headline_metas": metas, "sub_meta": sub_meta}


def build_behind(base, masks, flat, layout, headline_lines, sub, preset, unit):
    """behind: MELON은 제품 위에 완전히 노출, KICK만 실제 잉크 높이 기준으로
    OVERLAP_RATIO만큼만 제품과 겹치게 배치한다. 공간이 부족하면 headline_size를
    줄이고, 그래도 부족하면 제품(마스크+원본)을 아래로 shift한 뒤 그 위치 기준으로
    그림자를 다시 계산한다. 마지막으로 보조문구는 제품 합성 후 front로 그린다.
    """
    bw, bh = layout["bbox_w_ratio"], layout["bbox_h_ratio"]
    cy = layout["center_y_ratio"]
    product_top = cy - bh / 2
    product_bottom = cy + bh / 2

    hs, melon_y, kick_y, shift_ratio = _fit_two_line_layout(
        unit, headline_lines, preset["headline_font_role"], preset["headline_size"],
        product_top, HEADLINE_OVERLAP_RATIO, config.LINE_GAP_RATIO)

    shift_px = int(round(shift_ratio * unit))
    if shift_px > 0:
        # 배경은 그대로 두고 제품(마스크+원본)만 아래로 옮긴 뒤, 그 위치 기준으로
        # 그림자를 다시 계산한다(그림자가 옮기기 전 위치에 남으면 어긋나 보인다).
        product_mask = _shift_down(masks.product, shift_px, 0)
        base_shifted = _shift_down(base, shift_px, (0, 0, 0))
        shadowed = masking.add_ground_shadow(flat, product_mask)
        product_top += shift_ratio
        product_bottom += shift_ratio
    else:
        product_mask = masks.product
        base_shifted = base
        shadowed = masking.add_ground_shadow(flat, masks.product)

    img = shadowed
    metas = []
    for line, y in zip(headline_lines, (melon_y, kick_y)):
        img, meta = overlay.render_text(
            img, line, "", x=TEXT_X, y=y, align=TEXT_ALIGN, style="plain",
            headline_size=hs,
            headline_font_role=preset["headline_font_role"],
            stroke_width=preset["stroke_width"], fill_color=preset.get("fill_color"),
            max_height_ratio=0.95, return_meta=True)
        metas.append(meta)

    with_product = masking.composite_product(base_shifted, img, product_mask)

    sub_y = min(product_bottom + config.TEXT_MARGIN_RATIO, 0.92)
    sub_max_h = max(1 - sub_y - 0.03, 0.05)
    final, sub_meta = overlay.render_text(
        with_product, "", sub, x=TEXT_X, y=sub_y, align=TEXT_ALIGN, style="plain",
        sub_size=preset["sub_size"],
        stroke_width=preset["stroke_width"], fill_color=preset.get("fill_color"),
        max_height_ratio=sub_max_h, return_meta=True)

    return final, {"headline_size_used": hs, "melon_y": melon_y, "kick_y": kick_y,
                   "shift_ratio": round(shift_ratio, 4), "shift_px": shift_px,
                   "sub_y": sub_y, "headline_metas": metas, "sub_meta": sub_meta}


def make_compare(front: Image.Image, behind: Image.Image) -> Image.Image:
    label_h = 36
    gap = 12
    w, h = front.size
    canvas = Image.new("RGB", (w * 2 + gap, h + label_h), "white")
    d = ImageDraw.Draw(canvas)
    d.text((8, 6), "front (2줄 headline+sub 모두 제품 위, 회피 배치)", fill="black")
    d.text((w + gap + 8, 6), "behind (KICK만 제품에 살짝 걸침, sub는 front)", fill="black")
    canvas.paste(front, (0, label_h))
    canvas.paste(behind, (w + gap, label_h))
    return canvas


def main():
    spec = SAMPLE
    preset = config.TONE_PRESETS[spec["tone"]]

    t0 = time.time()
    src = spec["path"] or (ROOT / "image" / "snack.jpg")
    base, masks, mode = masking.prepare_image(str(src), SIZE)
    layout = masking.describe_product_bbox(masks.product)
    unit = SIZE  # prepare_image가 정사각형(size x size)으로 맞추므로 unit == SIZE

    bg_specs = masking.resolve_background("solid", None, None, spec["category"], 1)
    bg_spec = bg_specs[0]
    flat = masking.render_flat_background(SIZE, bg_spec["colors"], bg_spec.get("direction"))
    shadowed_for_front = masking.add_ground_shadow(flat, masks.product)

    front_img, front_info = build_front(base, masks, shadowed_for_front, layout,
                                        spec["headline_lines"], spec["sub"], preset)
    behind_img, behind_info = build_behind(base, masks, flat, layout,
                                           spec["headline_lines"], spec["sub"], preset, unit)

    front_path = OUT_DIR / "snack_bold_promo_front.png"
    behind_path = OUT_DIR / "snack_bold_promo_behind.png"
    compare_path = OUT_DIR / "snack_bold_promo_compare.png"

    front_img.save(front_path)
    behind_img.save(behind_path)
    make_compare(front_img, behind_img).save(compare_path)

    elapsed = round(time.time() - t0, 2)
    print(f"mode={mode} layout={layout}")
    print(f"front: {front_info}")
    print(f"behind: {behind_info}")
    print(f"완료 ({elapsed}s): {front_path}, {behind_path}, {compare_path}")

    entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "name": "snack", "tone": spec["tone"], "category": spec["category"],
        "prepare_mode": mode, "layout": layout,
        "background_mode": "solid", "background_used": bg_spec,
        "headline_lines": spec["headline_lines"],
        "headline_overlap_ratio": HEADLINE_OVERLAP_RATIO,
        "text_align": TEXT_ALIGN,
        "front": front_info, "behind": behind_info,
        "elapsed": elapsed,
        "front_path": str(front_path), "behind_path": str(behind_path),
        "compare_path": str(compare_path),
    }
    history = []
    if os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH, "r", encoding="utf-8") as f:
                history = json.load(f)
                if not isinstance(history, list):
                    history = [history]
        except (json.JSONDecodeError, OSError):
            history = []
    history.append(entry)
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f"로그 누적: {LOG_PATH}")


if __name__ == "__main__":
    main()

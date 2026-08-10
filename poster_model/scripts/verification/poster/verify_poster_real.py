"""실제 제품 이미지 기반 poster 검증 v2 — 톤별 프리셋 + 제품 bbox 회피 배치.

v1(최초) 결과에서 발견된 문제 반영:
    1. auto_fit이 x 좌표/align 기준 실제 가로 여백을 반영하지 못해 headline 오른쪽이
       잘리던 버그 -> overlay.render_text의 max_w 계산 자체를 수정 (pipeline 코드 수정, 완료)
    2. headline이 제품(펌프/라벨)을 무작위로 가리던 문제 -> 여기서는 "제품 상단 여백"을
       max_height_ratio로 명시적으로 제한해, 요청 크기가 얼마든 그 영역 밖(=제품 위)으로는
       절대 넘어가지 않게 한다(넘치면 auto_fit이 축소, 그래도 안 되면 min_font_scale까지만).
    3. minimal_product에 headline_size=0.18은 과함 -> config.TONE_PRESETS로 톤별 기본값 분리
       (minimal_product ~0.11, bold_promo ~0.22). 이 스크립트는 SAMPLES에 값을 하드코딩하지
       않고 TONE_PRESETS를 그대로 참조한다.
    4. Gmarket Sans 부재로 Black Han Sans 폴백 + 굵은 stroke가 이벤트 전단처럼 보이던 문제
       -> minimal_product는 headline_font_role="body_medium"(Pretendard Medium) + 얇은 stroke.
    5. sub가 제품 중앙을 가로지르던 문제 -> headline/sub를 하나의 블록으로 묶어 "제품 상단
       여백" 영역 전체에 대해 auto_fit을 적용하므로, sub도 항상 그 영역 안(=제품 위)에만 온다.

z_order="behind"는 이번에도 구현하지 않는다. 제품 bbox는 API에 정식 필드로 노출하지 않고,
이 스크립트가 draft 응답의 meta.layout을 읽어 클라이언트 측에서만 좌표/영역을 계산한다
(오버레이 개선안(headline_font_role/stroke_width/max_height_ratio)을 API 스키마 변경 없이
검증하기 위해, 텍스트 합성은 /generate/refine이 아니라 이 스크립트에서 pipeline.render_text를
직접 호출한다 — refine 요청은 text=None으로 보내 배경/그림자/제품 합성까지만 받는다).

사전 조건: 다른 터미널에서 API 서버가 떠 있어야 한다.
    uvicorn api:app --host 0.0.0.0 --port 8000

실행 (한 번에 한 샘플만):
    cd poster_model
    source .venv/bin/activate
    PYTHONPATH="$PWD" python scripts/verification/poster/verify_poster_real.py cosmetic
    PYTHONPATH="$PWD" python scripts/verification/poster/verify_poster_real.py snack
    PYTHONPATH="$PWD" python scripts/verification/poster/verify_poster_real.py glass

결과:
    outputs/verification/poster/{name}_plain_autofit_draft768.png
    outputs/verification/poster/{name}_plain_autofit_refine1024.png   (텍스트 포함 최종본)
    outputs/verification/poster/poster_verify_run_log.json  (누적 기록)
"""
import base64
import io
import json
import os
import sys
import time
from pathlib import Path

import requests
from PIL import Image

import pipeline
import pipeline.config as config

URL = "http://localhost:8000"
ROOT = Path(__file__).resolve().parents[3]     # scripts/verification/poster/ -> 프로젝트 루트
OUT_DIR = ROOT / "outputs" / "verification" / "poster"
OUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = OUT_DIR / "poster_verify_run_log.json"

BACKGROUND_MODE = "solid"   # 그림자 파라미터가 solid 기준으로 동결됐으므로 고정

SAMPLES = {
    "cosmetic": {
        "path": "image/cosmetic.jpg",
        "category": "beauty",
        "tone": "minimal_product",
        "headline": "매일을 위한 클린 케어",
        "sub": "가볍고 편안한 데일리 루틴",
    },
    "snack": {
        "path": "image/snack.jpg",
        "category": "food",
        "tone": "bold_promo",
        "headline": "MELON KICK",
        "sub": "달콤하고 바삭한 한입",
    },
    "glass": {
        "path": "image/glass.jpg",
        "category": "goods",
        # 정면형 단일 제품 포스터 — 배너형 굵은 프로모션이 아니라 절제된 톤에 가까워
        # minimal_product 프리셋을 사용한다. bold_promo가 맞다고 판단되면 tone만 바꾸면 된다.
        "tone": "minimal_product",
        "headline": "CLEAR MOMENT",
        "sub": "가볍게 채우는 깨끗한 한 잔",
    },
}

TOP_MARGIN_RATIO = 0.05     # headline 블록의 시작 y (이미지 최상단 여백)
# 제품 상단과 headline/sub 블록 사이 최소 간격. config.TEXT_MARGIN_RATIO(기존 여백 기준)와
# 동일하게 맞춰, 문구가 제품 bbox 바로 위까지 붙어 보이지 않도록 충분한 여백을 둔다.
PRODUCT_GAP_RATIO = config.TEXT_MARGIN_RATIO
MIN_REGION_RATIO = 0.06     # 위 간격을 다 빼도 남겨줄 최소 영역(너무 좁아지는 것 방지)


def compute_text_region(layout: dict) -> dict:
    """draft meta.layout(제품 bbox 비율)을 읽어 "제품 상단 여백" 영역을 계산한다.

    headline+sub 블록을 이 영역(y=TOP_MARGIN_RATIO ~ 제품 상단 - gap) 안에만 배치되도록
    x/y/align/max_height_ratio를 만든다. auto_fit이 이 영역을 기준으로 축소 여부를
    판단하므로, headline_size가 얼마나 크게 요청되든 제품을 가리는 일은 없다.
    """
    bw, bh = layout["bbox_w_ratio"], layout["bbox_h_ratio"]
    cx, cy = layout["center_x_ratio"], layout["center_y_ratio"]
    product_left = cx - bw / 2
    product_top = cy - bh / 2

    x = max(0.06, min(product_left, 0.5))
    y = TOP_MARGIN_RATIO
    max_height_ratio = max(product_top - PRODUCT_GAP_RATIO - y, MIN_REGION_RATIO)
    return {"x": round(x, 3), "y": round(y, 3), "align": "left",
           "max_height_ratio": round(max_height_ratio, 3)}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in SAMPLES:
        print(f"사용법: python {sys.argv[0]} [{'|'.join(SAMPLES)}]  (한 번에 하나만)")
        sys.exit(1)

    name = sys.argv[1]
    spec = SAMPLES[name]
    preset = config.TONE_PRESETS[spec["tone"]]

    print(requests.get(f"{URL}/health").json())

    with open(ROOT / spec["path"], "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    t0 = time.time()
    draft_req = {
        "mode": "inpaint", "image": img_b64, "category": spec["category"],
        "num_images": 1, "background_mode": BACKGROUND_MODE,
    }
    drafts = requests.post(f"{URL}/generate/drafts", json=draft_req).json()
    if "drafts" not in drafts:
        print(f"{name} draft 실패: {drafts}")
        sys.exit(1)

    d = drafts["drafts"][0]
    draft_path = OUT_DIR / f"{name}_plain_autofit_draft768.png"
    Image.open(io.BytesIO(base64.b64decode(d["image"]))).save(draft_path)
    layout = drafts["meta"]["layout"]
    print(f"{name} draft meta: {drafts['meta']}")

    region = compute_text_region(layout)

    # 텍스트 없이 배경/그림자/제품 합성까지만 받는다 (text=None).
    refine_req = {
        "draft_image": d["image"],
        "original_image": img_b64,
        "category": spec["category"],
        "ai_notice": False,
    }
    if d.get("background"):
        refine_req["background"] = d["background"]

    refine = requests.post(f"{URL}/generate/refine", json=refine_req).json()
    if "image" not in refine:
        print(f"{name} refine 실패: {refine}")
        sys.exit(1)

    base_img = Image.open(io.BytesIO(base64.b64decode(refine["image"])))

    # 텍스트는 여기서 직접 pipeline.render_text로 합성한다 (API 스키마 변경 없이
    # headline_font_role/stroke_width/max_height_ratio 같은 확장 인자를 쓰기 위함).
    final_img, text_meta = pipeline.render_text(
        base_img, spec["headline"], spec["sub"],
        x=region["x"], y=region["y"], align=region["align"],
        style="plain",
        headline_size=preset["headline_size"],
        sub_size=preset["sub_size"],
        headline_font_role=preset["headline_font_role"],
        stroke_width=preset["stroke_width"],
        fill_color=preset.get("fill_color"),
        max_height_ratio=region["max_height_ratio"],
        return_meta=True,
    )

    refine_path = OUT_DIR / f"{name}_plain_autofit_refine1024.png"
    final_img.save(refine_path)
    elapsed_total = round(time.time() - t0, 1)
    print(f"{name} text_meta: {text_meta}  (elapsed total {elapsed_total}s)")

    entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "name": name,
        "tone": spec["tone"],
        "category": spec["category"],
        "tone_preset": preset,
        "font_role_headline_resolved": config.resolve_font_path(preset["headline_font_role"]),
        "font_role_body_resolved": config.resolve_font_path("body"),
        "text_region": region,
        "style": "plain",
        "background_mode": BACKGROUND_MODE,
        "background_used": d.get("background"),
        "draft_layout": layout,
        "draft_meta": drafts["meta"],
        "refine_meta": refine["meta"],
        "text_meta": text_meta,   # 실제 적용된 폰트 크기, auto_fit 축소 여부 등
        "elapsed_total": elapsed_total,
        "draft_path": str(draft_path),
        "refine_path": str(refine_path),
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

    try:
        requests.post(f"{URL}/admin/gc", timeout=10)
    except requests.exceptions.RequestException:
        pass

    print(f"완료: {draft_path}, {refine_path}")
    print(f"로그 누적: {LOG_PATH}")


if __name__ == "__main__":
    main()

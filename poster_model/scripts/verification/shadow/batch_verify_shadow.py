"""그림자 + background_mode 효과 확인 (API 서버 필요, GPU 필요).

사전 조건: 다른 터미널에서 API 서버가 떠 있어야 한다.
    uvicorn api:app --host 0.0.0.0 --port 8000

실행:
    cd poster_model
    source .venv/bin/activate
    PYTHONPATH="$PWD" python scripts/verification/shadow/batch_verify_shadow.py

결과: outputs/verification/shadow/shadow_verify_out/ 아래에 이미지별로
    {name}_draft768.png   — 1단계 결과
    {name}_refine1024.png — 2단계 결과
    run_log.json          — 이번 실행에 쓰인 설정값 + 결과 메타 (전/후 비교용, 누적 기록)

v5: 실행 코드를 main()으로 옮기고 __main__ 가드를 적용했다 (import만으로 서버에
    요청이 나가던 부작용 제거).

v4: background_mode(solid/gradient/ai) 검증 반영
    - BACKGROUND_MODE로 테스트할 모드 선택 (기본 "ai" — 기존 동작 그대로 검증)
    - solid/gradient일 땐 draft 응답의 background를 그대로 refine 요청에 담아
      되돌려 보낸다(서버 무상태 원칙 그대로 재현) — 프론트가 할 일과 동일한 흐름
    - run_log.json에 background_mode, 실제 bg_colors, gradient_direction,
      refine_strength, shadow_prompt_suffix, 처리 해상도, diffusion 호출 여부를 기록
    - NAMES 기본값 유지 (cosmetic: 플랫레이·다중 연결요소 / glass: 정면형·단일 제품)
"""
import base64
import glob
import io
import json
import os
import time

import requests
from PIL import Image

import pipeline.config as config   # 이번 실행에 실제로 쓰인 설정값을 로그에 남기기 위해 import

from pathlib import Path

URL = "http://localhost:8000"
ROOT = Path(__file__).resolve().parents[3]   # scripts/verification/shadow/ -> 프로젝트 루트
OUT_DIR = ROOT / "outputs" / "verification" / "shadow" / "shadow_verify_out"
PAUSE_SEC = 3

# 검증할 이미지 이름(확장자 제외). None이면 image/*.jpg 전체.
NAMES = ["cosmetic"]

# "ai"(기본, 기존 동작 검증) | "solid" | "gradient"
BACKGROUND_MODE = "solid"
BG_COLORS = None
GRADIENT_DIRECTION = None

OUT_DIR.mkdir(parents=True, exist_ok=True)

CATEGORY_GUESS = {
    "cake": "food", "snack": "food",
    "cosmetic": "beauty",
    "glass": "goods", "monster_side": "goods", "monster_top": "goods",
}

def main():
    print(requests.get(f"{URL}/health").json())

    all_paths = sorted(glob.glob(str(ROOT / "image" / "*.jpg")))
    paths = all_paths if NAMES is None else [
        p for p in all_paths if os.path.splitext(os.path.basename(p))[0] in NAMES]

    print(f"이번 실행 대상: {[os.path.basename(p) for p in paths]} "
         f"(background_mode={BACKGROUND_MODE})")

    run_log = {
        "settings": {
            "background_mode": BACKGROUND_MODE,
            "bg_colors_requested": BG_COLORS,
            "gradient_direction_requested": GRADIENT_DIRECTION,
            "REFINE_STRENGTH": config.REFINE_STRENGTH,
            "SHADOW_PROMPT_SUFFIX": config.SHADOW_PROMPT_SUFFIX,
            "ISOLATION_PROMPT_SUFFIX": config.ISOLATION_PROMPT_SUFFIX,
            "SHADOW_OPACITY": config.SHADOW_OPACITY,
            "SHADOW_BLUR": config.SHADOW_BLUR,
            "SHADOW_SQUASH": config.SHADOW_SQUASH,
            "NEGATIVE_PROMPT": config.NEGATIVE_PROMPT,
        },
        "results": [],
    }

    for path in paths:
        name = os.path.splitext(os.path.basename(path))[0]
        category = CATEGORY_GUESS.get(name, "goods")

        with open(path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

        t0 = time.time()
        draft_req = {
            "mode": "inpaint", "image": img_b64, "category": category, "num_images": 1,
            "background_mode": BACKGROUND_MODE,
        }
        if BG_COLORS:
            draft_req["bg_colors"] = BG_COLORS
        if GRADIENT_DIRECTION:
            draft_req["gradient_direction"] = GRADIENT_DIRECTION

        drafts = requests.post(f"{URL}/generate/drafts", json=draft_req).json()
        if "drafts" not in drafts:
            print(f"{name} draft 실패: {drafts}")
            continue
        d = drafts["drafts"][0]
        draft_path = OUT_DIR / f"{name}_{BACKGROUND_MODE}_draft768.png"
        Image.open(io.BytesIO(base64.b64decode(d["image"]))).save(draft_path)
        print(f"{name} ({category}) draft: {drafts['meta']}  background={d.get('background')}")

        refine_req = {
            "draft_image": d["image"],
            "original_image": img_b64,
            "category": category,
            "ai_notice": False,
        }
        # 서버 무상태 원칙: draft 응답의 background를 그대로 refine 요청에 되돌려 보낸다
        # (ai 모드면 d["background"]가 None이라 아예 안 보냄 = 기존 동작과 동일)
        if d.get("background"):
            refine_req["background"] = d["background"]

        refine = requests.post(f"{URL}/generate/refine", json=refine_req).json()
        if "image" not in refine:
            print(f"{name} refine 실패: {refine}")
            continue
        refine_path = OUT_DIR / f"{name}_{BACKGROUND_MODE}_refine1024.png"
        Image.open(io.BytesIO(base64.b64decode(refine["image"]))).save(refine_path)
        elapsed_total = round(time.time() - t0, 1)
        print(f"{name} refine: {refine['meta']}  (elapsed total {elapsed_total}s)")

        run_log["results"].append({
            "name": name, "category": category,
            "draft_path": str(draft_path), "refine_path": str(refine_path),
            "draft_background": d.get("background"),
            "refine_background_used": refine_req.get("background"),
            "draft_meta": drafts["meta"], "refine_meta": refine["meta"],
            "elapsed_total": elapsed_total,
        })

        try:
            requests.post(f"{URL}/admin/gc", timeout=10)
        except requests.exceptions.RequestException:
            pass
        time.sleep(PAUSE_SEC)

    log_path = OUT_DIR / "run_log.json"
    history = []
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                history = json.load(f)
                if not isinstance(history, list):
                    history = [history]
        except (json.JSONDecodeError, OSError):
            history = []
    run_log["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
    history.append(run_log)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    print(f"완료: {OUT_DIR}/ 확인하세요. 설정값/결과 로그는 {log_path}에 누적됩니다.")


if __name__ == "__main__":
    main()

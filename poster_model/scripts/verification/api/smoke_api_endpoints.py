"""API 기본 흐름 스모크 테스트 (draft -> refine, 좌표 모드 + position 폴백).

자동으로 PASS/FAIL을 판정하지 않는다. 요청이 200으로 돌아오는지와 생성된
이미지를 눈으로 확인하는 용도다(그래서 tests/가 아니라 scripts/verification/에 있다).

사전 조건: 다른 터미널에서 API 서버가 떠 있어야 한다 (GPU 필요).
    uvicorn api:app --host 0.0.0.0 --port 8000

실행:
    cd poster_model
    source .venv/bin/activate
    PYTHONPATH="$PWD" python scripts/verification/api/smoke_api_endpoints.py

결과:
    outputs/verification/api/api_d1.png, api_d2.png, api_d3.png   시안 3장
    outputs/verification/api/api_final.png                        좌표 모드 최종본
    outputs/verification/api/api_final_fallback.png               position 폴백 최종본
"""
import base64
import io
from pathlib import Path

import requests
from PIL import Image

# scripts/verification/api/ -> 프로젝트 루트
ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "image" / "cake.jpg"
OUT_DIR = ROOT / "outputs" / "verification" / "api"
URL = "http://localhost:8000"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not SRC.exists():
        raise SystemExit(f"{SRC} 가 없습니다. image/README.md의 필요 파일 목록을 확인하세요.")

    with open(SRC, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    print(requests.get(f"{URL}/health").json())

    r = requests.post(f"{URL}/generate/drafts", json={
        "mode": "inpaint", "image": img_b64, "category": "food", "num_images": 3
    }).json()
    print("drafts:", r["meta"])

    for d in r["drafts"]:
        Image.open(io.BytesIO(base64.b64decode(d["image"]))).save(
            OUT_DIR / f"api_{d['id']}.png")

    # 첫 번째 시안으로 refine — 좌표 방식 (x, y 비율 + 폰트 크기 비율)
    r2 = requests.post(f"{URL}/generate/refine", json={
        "draft_image": r["drafts"][0]["image"],
        "original_image": img_b64,
        "category": "food",
        "text": {"headline": "진하고 부드러운 티라미수",
                 "sub": "오늘 하루만 20% 할인",
                 "x": 0.08, "y": 0.12,
                 "headline_size": 0.07, "sub_size": 0.043,
                 "align": "left", "style": "bar"}
    }).json()
    print("refine (좌표 모드):", r2["meta"])
    Image.open(io.BytesIO(base64.b64decode(r2["image"]))).save(OUT_DIR / "api_final.png")

    # 하위 호환 확인 — x, y 없이 position만 전달해도 기존처럼 동작해야 함
    r3 = requests.post(f"{URL}/generate/refine", json={
        "draft_image": r["drafts"][0]["image"],
        "original_image": img_b64,
        "category": "food",
        "text": {"headline": "진하고 부드러운 티라미수",
                 "sub": "오늘 하루만 20% 할인",
                 "position": "top", "align": "left", "style": "bar"}
    }).json()
    print("refine (position 폴백):", r3["meta"])
    Image.open(io.BytesIO(base64.b64decode(r3["image"]))).save(
        OUT_DIR / "api_final_fallback.png")
    print(f"완료: {OUT_DIR}/ 확인하세요.")


if __name__ == "__main__":
    main()

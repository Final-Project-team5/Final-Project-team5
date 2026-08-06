"""z_order 실제 API 스모크 테스트 (PR 전 최종 확인).

GPU + 실행 중인 API 서버가 필요하다:
    uvicorn api:app --host 0.0.0.0 --port 8000

실행:
    cd poster_model
    source .venv/bin/activate
    PYTHONPATH="$PWD" python scripts/verification/api/smoke_zorder_api.py

두 가지를 순서대로 확인한다.
    [A] behind/front — 이번에 추가한 기능. headline은 제품 뒤, sub는 제품 앞.
    [B] front/front  — z_order 필드를 아예 보내지 않는 기존 요청 형식(회귀 확인).

결과:
    outputs/verification/api/snack_bold_promo_api_behind.png
    outputs/verification/api/snack_bold_promo_api_behind_response.json
    outputs/verification/api/snack_frontfront_regression.png
"""
import base64
import io
import json
import sys
from pathlib import Path

import requests
from PIL import Image

URL = "http://localhost:8000"
ROOT = Path(__file__).resolve().parents[3]     # scripts/verification/api/ -> 프로젝트 루트
OUT_DIR = ROOT / "outputs" / "verification" / "api"
OUT_DIR.mkdir(parents=True, exist_ok=True)
SRC = ROOT / "image" / "snack.jpg"

# 자동 배치 기능은 쓰지 않는다. 좌표/크기는 여기서 명시적으로 지정한다.
HEADLINE = "MELON\nKICK"
SUB = "달콤함이 톡! 새로운 에너지"

# --- 좌표/크기 산출 근거 (1차 스모크 테스트에서 KICK이 완전히 가려진 문제 대응) ---
# 실제 snack.jpg 레이아웃: center_y_ratio=0.5034, bbox_h_ratio=0.6611
#   -> product_top = 0.5034 - 0.6611/2 = 0.1728
#   -> 텍스트가 쓸 수 있는 세로 공간 = 0.1728 - 0.02(최소 상단 여백) = 0.1528
#
# 멀티라인 headline은 y가 "블록 전체의 시작점"이라 MELON과 KICK의 위치를 따로 잡을 수 없다.
# KICK 위치는 y + (headline_size * 1.35)로 자동 결정되므로, headline_size가 커질수록
# KICK이 product_top보다 훨씬 아래로 밀려 제품에 완전히 가려진다.
# 위 공간(0.1528)에 대해 y=0.02로 고정하고 크기별 KICK 노출률을 실측한 결과:
#
#     headline_size   MELON 하단   KICK 노출률
#         0.16          0.1489        0%    <- 1차 테스트 값 (완전히 가려짐)
#         0.12          0.1167        0%
#         0.10          0.1011       21%
#         0.09          0.0932       42%
#         0.08          0.0835       72%    <- 선택 (MELON 완전 노출 + KICK 인식 가능)
#         0.07          0.0766      100%    (거의 안 가려져 오클루전 효과 없음)
#
# 즉 "MELON 완전 노출 + KICK 부분 가림"을 만족하는 크기는 0.08뿐인데, 이는 bold_promo가
# 의도한 큰 타이포(0.16~0.28)의 절반이다. 두 조건을 동시에 만족하려면 줄별로 y를 따로
# 지정할 수 있어야 하고, 그건 현재 최소 구현 범위 밖이다(문서의 "알려진 제한" 참고).
# 이 스모크 테스트는 z_order 배선이 실제로 동작하는지 눈으로 확인하는 것이 목적이므로,
# 타이포 크기보다 "가림 정도를 확인 가능한" 0.08을 쓴다.
HEADLINE_SIZE = 0.08
SUB_SIZE = 0.05
HEADLINE_XY = (0.5, 0.02)
SUB_XY = (0.5, 0.88)

fails = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   {detail}" if not cond else ""))
    if not cond:
        fails.append(name)


def main():
    print(requests.get(f"{URL}/health").json())

    with open(SRC, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    # ---- draft (solid 배경: diffusion 생략, 그림자 파라미터가 solid 기준으로 동결돼 있음)
    drafts = requests.post(f"{URL}/generate/drafts", json={
        "mode": "inpaint", "image": img_b64, "category": "food",
        "num_images": 1, "background_mode": "solid",
    }).json()
    if "drafts" not in drafts:
        print(f"draft 실패: {drafts}")
        sys.exit(1)
    d = drafts["drafts"][0]
    print(f"draft meta: {drafts['meta']}")

    # ---- [A] behind/front
    print("\n[A] headline_z_order=behind / sub_z_order=front")
    req_a = {
        "draft_image": d["image"],
        "original_image": img_b64,
        "category": "food",
        "ai_notice": True,
        "text": {
            "headline": HEADLINE, "sub": SUB,
            "x": HEADLINE_XY[0], "y": HEADLINE_XY[1],
            "sub_x": SUB_XY[0], "sub_y": SUB_XY[1],
            "align": "center", "style": "plain",
            "headline_size": HEADLINE_SIZE, "sub_size": SUB_SIZE,
            "headline_z_order": "behind", "sub_z_order": "front",
        },
    }
    if d.get("background"):
        req_a["background"] = d["background"]

    resp = requests.post(f"{URL}/generate/refine", json=req_a)
    check("1. 요청이 오류 없이 완료", resp.status_code == 200, f"{resp.status_code} {resp.text[:300]}")
    if resp.status_code != 200:
        sys.exit(1)

    body = resp.json()
    meta = body["meta"]
    out_path = OUT_DIR / "snack_bold_promo_api_behind.png"
    Image.open(io.BytesIO(base64.b64decode(body["image"]))).save(out_path)

    check("5. meta.text 기존 구조(단일 dict) 유지",
          isinstance(meta.get("text"), dict) and "applied_headline_px" in meta["text"],
          str(meta.get("text"))[:200])
    layers = meta.get("text_layers", {})
    check("6a. text_layers.headline.z_order == behind",
          layers.get("headline", {}).get("z_order") == "behind", str(layers))
    check("6b. text_layers.sub.z_order == front",
          layers.get("sub", {}).get("z_order") == "front", str(layers))
    check("6c. headline 좌표 기록", layers.get("headline", {}).get("y") == HEADLINE_XY[1], str(layers))
    check("6d. sub 좌표 기록", layers.get("sub", {}).get("y") == SUB_XY[1], str(layers))
    check("6e. 적용 크기 기록",
          layers.get("headline", {}).get("applied_size") is not None
          and layers.get("sub", {}).get("applied_size") is not None, str(layers))

    with open(OUT_DIR / "snack_bold_promo_api_behind_response.json", "w", encoding="utf-8") as f:
        json.dump({"request_text": req_a["text"], "meta": meta,
                   "image_path": str(out_path)}, f, ensure_ascii=False, indent=2)

    print(f"  -> {out_path} 저장")
    print("  * 2/3/4/7번(제품 뒤 렌더링, sub 앞 렌더링, AI 표시 1회, verify_zorder_behind 유사성)은")
    print("    저장된 이미지를 눈으로 확인해주세요.")

    # ---- [B] front/front 회귀 (z_order 필드 자체를 보내지 않음)
    print("\n[B] 회귀: z_order 필드 미전송 (기존 요청 형식 그대로)")
    req_b = {
        "draft_image": d["image"],
        "original_image": img_b64,
        "category": "food",
        "ai_notice": True,
        "text": {
            "headline": "MELON KICK", "sub": SUB,
            "x": 0.5, "y": 0.05, "align": "center", "style": "bar",
            "headline_size": 0.16, "sub_size": SUB_SIZE,
        },
    }
    if d.get("background"):
        req_b["background"] = d["background"]

    resp_b = requests.post(f"{URL}/generate/refine", json=req_b)
    check("기존 형식 요청 200", resp_b.status_code == 200, f"{resp_b.status_code} {resp_b.text[:300]}")
    if resp_b.status_code == 200:
        body_b = resp_b.json()
        reg_path = OUT_DIR / "snack_frontfront_regression.png"
        Image.open(io.BytesIO(base64.b64decode(body_b["image"]))).save(reg_path)
        lb = body_b["meta"].get("text_layers", {})
        check("기본값이 front/front",
              lb.get("headline", {}).get("z_order") == "front"
              and lb.get("sub", {}).get("z_order") == "front", str(lb))
        check("meta.text 구조 동일",
              isinstance(body_b["meta"].get("text"), dict), str(body_b["meta"].get("text"))[:150])
        print(f"  -> {reg_path} 저장")

    print("\n" + "=" * 50)
    if fails:
        print(f"실패 {len(fails)}건: {fails}")
        sys.exit(1)
    print("SMOKE_TEST_PASSED (이미지 육안 확인 항목은 별도)")


if __name__ == "__main__":
    main()

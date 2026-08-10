"""규제 규칙 A/B 실험.

가설: LLM은 매력적인 카피를 만들도록 학습돼 있어, 규제 지침 없이 생성하면
      규제 위반 표현이 더 많이 나온다. (특히 푸드·뷰티)

실험: 같은 제품 세트에 대해
  A) 규제 지침을 뺀 프롬프트로 생성 (baseline)
  B) 규제 지침을 넣은 프롬프트로 생성 (우리 방식)
  → 두 그룹의 위반율(block 포함 비율)을 룰 검사로 측정해 비교

측정은 룰 기반이라 비용 0. 생성만 API 비용이 든다.

사용:
    # 실제 생성 (API 키 필요)
    OPENAI_API_KEY=sk-... python -m eval.run_regulation_ab --n 10

    # 파이프라인 검증 (mock — 규칙 유무 차이는 안 나지만 흐름 확인용)
    COPY_MOCK=1 python -m eval.run_regulation_ab --n 3

주의: mock 모드는 고정 샘플이라 A/B 차이가 나오지 않는다.
      실제 위반율 비교는 반드시 API 키로 실행할 것.
"""
import argparse
import json

from copy_model import config, prompts
from copy_model.generator import _client, _chat_json
from eval.metrics import evaluate_batch

# 실험용 제품 세트 (규제 위반이 유도되기 쉬운 업종·품목 중심)
TEST_PRODUCTS = [
    ("food", "홍삼 진액", ["건강", "매일"]),
    ("food", "다이어트 도시락", ["체중관리", "저칼로리"]),
    ("food", "유산균 요거트", ["장", "매일아침"]),
    ("food", "수제 흑마늘", ["면역", "정성"]),
    ("beauty", "주름 개선 크림", ["안티에이징", "탄력"]),
    ("beauty", "여드름 진정 세럼", ["트러블", "진정"]),
    ("beauty", "미백 앰플", ["브라이트닝", "톤업"]),
    ("beauty", "수분 크림", ["보습", "데일리"]),
    ("goods", "친환경 에코백", ["재활용", "일상"]),
    ("goods", "핸드메이드 캔들", ["감성", "선물"]),
]


def _generate(client, category, product, keywords, num, include_regulation):
    """한 제품에 대해 시안 생성. 반환: [{"headline","sub"}, ...]"""
    system = prompts.build_system_prompt(
        category, "warm", num, config.HEADLINE_MAX, config.SUB_MAX,
        include_regulation=include_regulation)
    user = prompts.build_user_prompt(product, keywords, None, num)
    data = _chat_json(client, system, user)
    return [
        {"headline": str(c.get("headline", "")).strip(),
         "sub": str(c.get("sub", "")).strip()}
        for c in data.get("candidates", [])[:num]
    ]


def run(n_products: int, num_candidates: int) -> dict:
    if config.MOCK_MODE:
        # mock: 고정 샘플이라 규칙 유무 차이가 없음. 파이프라인 흐름만 검증.
        from copy_model.generator import _MOCK_SAMPLES
        products = TEST_PRODUCTS[:n_products]
        sets_a, sets_b = [], []
        for cat, _, _ in products:
            samp = [{"headline": h, "sub": s}
                    for h, s in _MOCK_SAMPLES[cat][:num_candidates]]
            sets_a.append((samp, cat))
            sets_b.append((samp, cat))
        note = "MOCK 모드 — A/B 동일 샘플. 실제 비교는 API 키 필요."
    else:
        client = _client()
        products = TEST_PRODUCTS[:n_products]
        sets_a, sets_b = [], []
        for cat, prod, kw in products:
            sets_a.append(
                (_generate(client, cat, prod, kw, num_candidates, False), cat))
            sets_b.append(
                (_generate(client, cat, prod, kw, num_candidates, True), cat))
        note = "실측 결과"

    res_a = evaluate_batch(sets_a)
    res_b = evaluate_batch(sets_b)
    return {
        "note": note,
        "n_products": len(products),
        "num_candidates": num_candidates,
        "group_A_no_regulation": res_a.summary(),
        "group_B_with_regulation": res_b.summary(),
        "improvement": {
            "violation_rate_drop": round(
                res_a.violation_rate - res_b.violation_rate, 3),
            "safe_rate_gain": round(
                res_b.safe_rate - res_a.safe_rate, 3),
        },
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=len(TEST_PRODUCTS),
                   help="실험할 제품 수 (최대 10)")
    p.add_argument("--candidates", type=int, default=3, help="제품당 시안 수")
    args = p.parse_args()

    result = run(min(args.n, len(TEST_PRODUCTS)), args.candidates)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    a = result["group_A_no_regulation"]
    b = result["group_B_with_regulation"]
    print("\n" + "=" * 50)
    print(f"{result['note']}")
    print(f"규칙 없음(A) 위반율: {a['violation_rate']:.1%}  안전율: {a['safe_rate']:.1%}")
    print(f"규칙 있음(B) 위반율: {b['violation_rate']:.1%}  안전율: {b['safe_rate']:.1%}")
    print(f"→ 위반율 {result['improvement']['violation_rate_drop']:+.1%} "
          f"(규칙 적용 시 감소량)")
    print("=" * 50)


if __name__ == "__main__":
    main()

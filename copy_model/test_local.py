"""로컬 CLI 테스트 스크립트 (서버 없이 생성 로직만 확인).

사용 예:
    # mock 모드 (API 키 불필요, 비용 0)
    COPY_MOCK=1 python test_local.py --category food --product "딸기 생크림 케이크"

    # 실제 API 호출
    OPENAI_API_KEY=sk-... python test_local.py --category beauty \
        --product "수분 크림" --tone luxury --keywords 저자극 데일리
"""
import argparse

from copy_model.schemas import CopyRequest
from copy_model.generator import generate_copy


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--category", choices=["food", "beauty", "goods"], required=True)
    p.add_argument("--product", required=True)
    p.add_argument("--tone", choices=["warm", "energetic", "luxury", "simple"],
                   default="warm")
    p.add_argument("--keywords", nargs="*", default=None)
    p.add_argument("--request", default=None)
    p.add_argument("--num", type=int, default=3)
    args = p.parse_args()

    req = CopyRequest(
        category=args.category, product=args.product, tone=args.tone,
        keywords=args.keywords, request=args.request, num_candidates=args.num,
    )
    res = generate_copy(req)

    print(f"\n모델: {res.meta.model} | 소요: {res.meta.elapsed}s"
          f"{' | ⚠ MOCK 모드' if res.meta.mock else ''}\n")
    for c in res.candidates:
        flag = " ⚠ 제한초과" if c.over_limit else ""
        print(f"[{c.id}] {c.headline}  ({c.headline_chars}자){flag}")
        print(f"     {c.sub}  ({c.sub_chars}자)\n")


if __name__ == "__main__":
    main()

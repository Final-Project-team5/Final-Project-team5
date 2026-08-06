"""시안 다양성 측정.

문제: 시안 3개를 한 번에 생성하면 서로 비슷하게 나오는 경우가 있음.
("오늘 갓 구운 빵 / 매일 아침 구운 빵 / 신선하게 구운 빵")
시안을 3개 주는 이유가 선택지 제공인데, 비슷하면 의미가 없음.

측정 방식: 문자 bigram 자카드 유사도 (비용 0, 키 불필요)
- 한국어는 조사·어미 변화가 많아 어절 단위 비교만으로는 "구운 빵"과 "구운빵"을
  다른 것으로 판정함. 문자 bigram이 이런 표기 차이에 강함.
- 광고 문구는 짧아서(20~30자) 문자 단위 비교로도 충분히 판별 가능.

한계: 표면적 유사도라 "저렴한"과 "가성비 좋은"처럼 표현은 다르지만 의미가
같은 경우는 잡지 못함. 의미 기반 판정이 필요하면 임베딩으로 확장 가능
(config.DIVERSITY_USE_EMBEDDING) — 다만 API 키와 추가 비용이 필요.
"""
import re
from itertools import combinations

_NON_WORD = re.compile(r"[^\w가-힣]+")


def _normalize(text: str) -> str:
    """공백·문장부호를 제거해 표기 차이의 영향을 줄인다."""
    return _NON_WORD.sub("", text)


def _bigrams(text: str) -> set[str]:
    t = _normalize(text)
    if len(t) < 2:
        return {t} if t else set()
    return {t[i:i + 2] for i in range(len(t) - 1)}


def similarity(a: str, b: str) -> float:
    """문자 bigram 자카드 유사도. 0.0(완전히 다름) ~ 1.0(동일)."""
    sa, sb = _bigrams(a), _bigrams(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def pair_similarity(c1: dict, c2: dict) -> float:
    """시안 두 개의 유사도. headline과 sub를 합쳐 비교한다."""
    t1 = f"{c1.get('headline', '')} {c1.get('sub', '')}"
    t2 = f"{c2.get('headline', '')} {c2.get('sub', '')}"
    return similarity(t1, t2)


def find_duplicates(candidates: list[dict], threshold: float) -> list[int]:
    """임계값을 넘는 쌍에서 뒤쪽 시안의 인덱스를 반환.

    앞 시안을 남기고 뒤 시안을 교체 대상으로 삼는다.
    (LLM이 보통 앞쪽을 더 공들여 생성하는 경향을 가정)
    """
    dup = set()
    for i, j in combinations(range(len(candidates)), 2):
        if j in dup:
            continue
        if pair_similarity(candidates[i], candidates[j]) >= threshold:
            dup.add(j)
    return sorted(dup)


def diversity_score(candidates: list[dict]) -> float:
    """시안 집합의 다양성 점수. 1.0에 가까울수록 서로 다름.

    모든 쌍의 평균 유사도를 1에서 뺀 값.
    """
    if len(candidates) < 2:
        return 1.0
    sims = [pair_similarity(a, b) for a, b in combinations(candidates, 2)]
    return round(1.0 - (sum(sims) / len(sims)), 3)


def max_pair_similarity(candidates: list[dict]) -> float:
    """가장 비슷한 쌍의 유사도 (가장 문제되는 지점)."""
    if len(candidates) < 2:
        return 0.0
    return round(max(pair_similarity(a, b) for a, b in combinations(candidates, 2)), 3)

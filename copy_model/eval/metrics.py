"""문구 생성 품질 지표 (규제 준수 + 형식 준수).

키 없이 즉시 계산 가능한 지표만 여기 둔다.
(적합도·창의성 같은 LLM 판단 지표는 별도 모듈로 분리 — 키 필요)

지표
- 규제 위반율: block 표현이 포함된 시안 비율
- 경고율: warn 이상 플래그가 있는 시안 비율
- 안전율: block이 없는 시안 비율 (= 1 - 위반율)
- 글자수 준수율: headline/sub 제한을 지킨 시안 비율
- 다양성 점수: 시안 세트의 평균 다양성 (diversity 모듈 재사용)
"""
from dataclasses import dataclass, field

from copy_model.regulation import check_rules
from copy_model.diversity import diversity_score
from copy_model import config


@dataclass
class EvalResult:
    n_candidates: int = 0
    n_block: int = 0            # block 플래그를 가진 시안 수
    n_warn: int = 0            # warn 이상 플래그를 가진 시안 수
    n_over_limit: int = 0      # 글자수 초과 시안 수
    diversity_scores: list = field(default_factory=list)

    @property
    def violation_rate(self) -> float:
        """규제 위반율 = block 시안 / 전체 시안."""
        return round(self.n_block / self.n_candidates, 3) if self.n_candidates else 0.0

    @property
    def warn_rate(self) -> float:
        return round(self.n_warn / self.n_candidates, 3) if self.n_candidates else 0.0

    @property
    def safe_rate(self) -> float:
        return round(1 - self.violation_rate, 3)

    @property
    def length_ok_rate(self) -> float:
        if not self.n_candidates:
            return 0.0
        return round(1 - self.n_over_limit / self.n_candidates, 3)

    @property
    def avg_diversity(self) -> float:
        if not self.diversity_scores:
            return 0.0
        return round(sum(self.diversity_scores) / len(self.diversity_scores), 3)

    def summary(self) -> dict:
        return {
            "n_candidates": self.n_candidates,
            "violation_rate": self.violation_rate,   # block 포함 비율 (낮을수록 좋음)
            "warn_rate": self.warn_rate,
            "safe_rate": self.safe_rate,             # block 없는 비율 (높을수록 좋음)
            "length_ok_rate": self.length_ok_rate,
            "avg_diversity": self.avg_diversity,
        }


def _over_limit(headline: str, sub: str) -> bool:
    return len(headline) > config.HEADLINE_MAX or len(sub) > config.SUB_MAX


def evaluate_candidates(candidates: list[dict], category: str) -> EvalResult:
    """시안 한 세트를 평가.

    candidates: [{"headline": ..., "sub": ...}, ...]
    """
    r = EvalResult(n_candidates=len(candidates))
    for c in candidates:
        headline = c.get("headline", "")
        sub = c.get("sub", "")
        flags = check_rules(f"{headline} {sub}", category)
        if any(f.severity == "block" for f in flags):
            r.n_block += 1
        if flags:
            r.n_warn += 1
        if _over_limit(headline, sub):
            r.n_over_limit += 1
    if len(candidates) >= 2:
        r.diversity_scores.append(diversity_score(candidates))
    return r


def evaluate_batch(sets: list[tuple[list[dict], str]]) -> EvalResult:
    """여러 시안 세트를 누적 평가.

    sets: [(candidates, category), ...]
    """
    total = EvalResult()
    for candidates, category in sets:
        r = evaluate_candidates(candidates, category)
        total.n_candidates += r.n_candidates
        total.n_block += r.n_block
        total.n_warn += r.n_warn
        total.n_over_limit += r.n_over_limit
        total.diversity_scores.extend(r.diversity_scores)
    return total

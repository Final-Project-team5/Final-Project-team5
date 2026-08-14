"""규제 검증 2차 레이어 — 룰 → LLM 하이브리드 (로드맵 P2, 프로토타입).

배경(골드셋 실측 근거):
    정규식 룰은 '맥락'을 못 본다. 두 방향으로 오류가 난다.
      - 오탐: "최고의 하루를 담은 다이어리" — 룰이 '최고'만 보고 warn.
              (제품이 아니라 '하루'를 수식 → 실제로는 safe)
      - 미탐: "면역 쑥쑥 올려주는 홍삼" — 효능을 의미로 우회해 룰이 못 잡음.
              (실제로는 block)
    두 오류 모두 '맥락 판단'이 필요 → LLM 2차 검증의 실측 근거.

설계 원칙:
    1) 룰이 1차 필터(비용 0, 즉시). 명백한 block/safe는 룰을 신뢰한다.
    2) LLM은 비싸다. '경계 케이스'만 골라 2차로 넘긴다(에스컬레이션).
       - warn 중 '문맥 최상급'류 → 오탐 가능 → 다운그레이드 검토
       - safe 중 '효능 의미회피'류 → 미탐 가능 → 업그레이드 검토
    3) LLM 판정기(judge)는 주입식(injectable)이다. 오프라인/테스트에서는
       가짜 judge로 배선을 검증하고, 운영에서는 실제 LLM judge를 쓴다.

주의:
    LLM 판정의 '실제 교정 효과'는 API 키가 있어야 측정된다. 이 모듈은
    라우팅(어떤 케이스를 LLM으로 넘길지)까지 결정론적으로 구현하며,
    판정 효과 측정은 별도(run 필요)다. run_escalation.py는 라우팅만 잰다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from .regulation import RegulationFlag, check_rules

# ── 에스컬레이션 힌트 어휘 ──────────────────────────────────
# (A) 문맥 최상급: warn을 유발하지만 제품이 아닌 시간/기분/상황을 수식하면
#     오탐이 되는 표현. 이런 표현으로 warn이 걸리면 LLM에 맥락 확인을 맡긴다.
CONTEXT_SENSITIVE = (
    "최고", "최상", "완벽", "제일", "최상의", "베스트", "best",
)

# (B) 효능 의미회피: 룰이 단정어를 못 잡아도 '효과가 있다'는 의미를 암시하는
#     신호. safe로 통과됐지만 이런 신호가 있으면 미탐 가능 → LLM 업그레이드 검토.
#     (푸드/뷰티에서만 의미 있음 — 굿즈는 효능 개념이 약함)
SEMANTIC_RISK = (
    "면역", "기운", "활력", "피로", "노폐물", "붓기", "숙취", "혈액",
    "쑥쑥", "올려주는", "좋아지는", "회복", "개선", "완화", "빠지는",
    "디톡스", "해독", "지방", "다이어트", "살", "탄력", "재생",
)


@dataclass
class EscalationDecision:
    escalate: bool
    reason: str
    direction: Optional[str]   # "maybe_downgrade" | "maybe_upgrade" | None


def _hits(lexicon: tuple, text: str) -> Optional[str]:
    """lexicon 중 text에 등장하는 첫 토큰 반환(없으면 None)."""
    for w in lexicon:
        if re.search(re.escape(w), text, flags=re.IGNORECASE):
            return w
    return None


def escalation_decision(flags: list[RegulationFlag], text: str,
                        category: str, policy: str = "lexicon") -> EscalationDecision:
    """룰 결과를 보고 이 케이스를 LLM 2차로 넘길지 결정(비용 통제).

    공통 정책:
      - block 있음: 룰 신뢰, 에스컬레이션 안 함.
      - warn + 문맥 최상급: 오탐 가능 → 다운그레이드 검토.
      - warn(그 외): 룰 유지.

    safe 케이스의 미탐 방향 정책(policy로 선택):
      - "lexicon": 효능 의미회피 어휘가 잡힐 때만 에스컬레이션(좁음, 저비용).
        새 회피 표현엔 눈이 먼다(어휘 맹점).
      - "broad": food/beauty의 safe는 폭넓게 에스컬레이션(구조적, 고비용).
        어휘에 안 걸린 회피도 재확인하지만 정상 문구까지 LLM을 태운다.
    """
    has_block = any(f.severity == "block" for f in flags)
    has_warn = any(f.severity == "warn" for f in flags)

    if has_block:
        return EscalationDecision(False, "룰 block 확정 — LLM 불필요", None)

    if has_warn:
        matched = " ".join(f.matched for f in flags)
        hit = _hits(CONTEXT_SENSITIVE, matched) or _hits(CONTEXT_SENSITIVE, text)
        if hit:
            return EscalationDecision(
                True, f"문맥 최상급('{hit}') 오탐 가능 — 다운그레이드 검토",
                "maybe_downgrade")
        return EscalationDecision(False, "일반 warn — 룰 유지", None)

    # safe — 미탐 방향
    if category in ("food", "beauty"):
        if policy == "broad":
            return EscalationDecision(
                True, "food/beauty safe — 구조적 재확인(broad)", "maybe_upgrade")
        hit = _hits(SEMANTIC_RISK, text)
        if hit:
            return EscalationDecision(
                True, f"효능 의미회피 신호('{hit}') 미탐 가능 — 업그레이드 검토",
                "maybe_upgrade")
    return EscalationDecision(False, "명백 safe — LLM 생략", None)


# ── LLM 판정기 인터페이스 ──────────────────────────────────
# judge(headline, sub, category, rule_severity, direction) -> LLMVerdict
@dataclass
class LLMVerdict:
    severity: str          # "block" | "warn" | "safe"
    reason: str


_SEV_RANK = {"safe": 0, "warn": 1, "block": 2}


def apply_trust(rule_severity: str, verdict: "LLMVerdict",
                trust: str = "asymmetric") -> str:
    """신뢰 정책에 따라 최종 등급 결정 (실측에서 파손 0 확인된 정책).

    - full: LLM 판정 그대로.
    - asymmetric: 엄격해지는 방향(등급 상향)은 즉시 수용, 완화(하향)는
      근거(reason)가 있을 때만 수용. 규제 도구는 미탐 비용이 커서 LLM
      오판으로 규제가 뚫리는 경로를 정책으로 차단한다.
    """
    if trust == "full":
        return verdict.severity
    if _SEV_RANK[verdict.severity] >= _SEV_RANK[rule_severity]:
        return verdict.severity
    return verdict.severity if verdict.reason.strip() else rule_severity


Judge = Callable[[str, str, str, str, Optional[str]], LLMVerdict]


@dataclass
class HybridResult:
    severity: str              # 최종 등급
    source: str                # "rule" | "llm"
    rule_severity: str         # 룰 1차 등급
    escalation: EscalationDecision
    llm_verdict: Optional[LLMVerdict]
    flags: list[RegulationFlag]


def _rule_severity(flags: list[RegulationFlag]) -> str:
    if any(f.severity == "block" for f in flags):
        return "block"
    if flags:
        return "warn"
    return "safe"


def hybrid_check(headline: str, sub: str, category: str,
                 judge: Optional[Judge] = None,
                 policy: str = "lexicon") -> HybridResult:
    """룰 1차 → (경계 케이스만) LLM 2차. judge=None이면 라우팅만 하고 룰 유지.

    judge가 주어지면 에스컬레이션 케이스에 한해 호출하고, 그 등급으로 교정한다.
    policy: safe 미탐 방향 라우팅 정책("lexicon" | "broad").
    """
    text = f"{headline} {sub}"
    flags = check_rules(text, category)
    rule_sev = _rule_severity(flags)
    decision = escalation_decision(flags, text, category, policy=policy)

    if not decision.escalate or judge is None:
        return HybridResult(rule_sev, "rule", rule_sev, decision, None, flags)

    verdict = judge(headline, sub, category, rule_sev, decision.direction)
    return HybridResult(verdict.severity, "llm", rule_sev, decision, verdict, flags)


# ── 실제 LLM judge 빌더 (운영용, API 키 필요) ──────────────
_JUDGE_PROMPT = """당신은 한국 광고 규제(표시광고법, 식품표시광고법, 화장품법) 심의관입니다.
정규식 룰이 1차로 '{rule_severity}'로 판정했으나 맥락 확인이 필요합니다.
아래 문구가 실제로 규제 위반인지 '맥락'을 보고 판단하세요.

핵심 판단 기준:
- 최상급/단정 표현이 '제품'의 효능·품질을 단정하면 위반입니다.
- 같은 단어라도 시간·기분·상황을 수식할 뿐이면 위반이 아닙니다(safe).
- 효능을 은유·의미로 우회한 표현도 실제 효능 주장이면 위반입니다.

[카테고리] {category}
[headline] {headline}
[sub] {sub}

반드시 JSON으로만 응답:
{{"severity": "block|warn|safe", "reason": "판단 근거 1문장"}}"""


def build_llm_judge(client_chat: Callable[[list], dict]) -> Judge:
    """client_chat(messages)->dict 를 받아 실제 LLM judge를 만든다.

    client_chat은 chatbot._client_chat 같은 JSON 응답 헬퍼를 주입한다.
    (여기서 직접 OpenAI를 부르지 않아 테스트/모킹이 쉽다.)
    """
    def judge(headline: str, sub: str, category: str,
              rule_severity: str, direction: Optional[str]) -> LLMVerdict:
        prompt = _JUDGE_PROMPT.format(
            rule_severity=rule_severity, category=category,
            headline=headline, sub=sub)
        data = client_chat([{"role": "user", "content": prompt}])
        sev = str(data.get("severity", rule_severity)).strip().lower()
        if sev not in ("block", "warn", "safe"):
            sev = rule_severity  # 파싱 실패 시 룰로 폴백(안전)
        return LLMVerdict(sev, str(data.get("reason", "")))
    return judge

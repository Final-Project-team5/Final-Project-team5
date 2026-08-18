"""광고 규제 필터링 모듈 (프로토타입).

2단계 검증:
  1) 룰 기반 (무료·즉시): 카테고리별 금지/주의 표현 사전 매칭
     - 표시광고법 공통 + 식품표시광고법(푸드) + 화장품법(뷰티) + 상표법·환경성고시(굿즈)
     - 룰 정의는 regulation_rules.py 참고 (패턴 / severity / 근거 / 대체표현)
  2) LLM 검증 (선택, use_llm=true): 룰이 못 잡는 맥락상 위반을 판단하고
     안전한 대체 문구 제안

생성 파이프라인 통합: /generate/copy 결과의 각 시안에 룰 체크 결과가
regulation_flags 로 자동 첨부됨 (LLM 검증은 별도 /validate/copy 호출).

TODO(고도화): AI허브 법률 DB 임베딩 + RAG 근거 제시
"""
import re
import time
from typing import Optional

from pydantic import BaseModel, Field

from . import config
from .regulation_rules import CATEGORY_RULES, rule_stats
from .regulation_whitelist import is_whitelisted, approved_expression

# 룰 사전은 regulation_rules.py로 분리 (카테고리별 패턴·근거·대체표현)


class RegulationFlag(BaseModel):
    matched: str = Field(description="걸린 표현")
    severity: str = Field(description="block | warn")
    reason: str = Field(description="관련 규제 및 사유")
    suggestion: str = Field(
        default="", description="대체 표현 예시 (프론트 안내용, 없으면 빈 문자열)")


class ValidateRequest(BaseModel):
    category: str = Field(description="food | beauty | goods")
    headline: str
    sub: str = ""
    use_llm: bool = Field(
        default=False,
        description="하이브리드 LLM 맥락 검증 (경계 케이스만 LLM 호출, API 비용 최소화)")
    policy: str = Field(
        default="broad",
        description="라우팅 정책: broad(전수, 기본 — 팀 확정) | lexicon(어휘, 비용 절감 옵션)")


class ValidateResponse(BaseModel):
    safe: bool = Field(description="최종 등급이 block이 아니면 True")
    flags: list[RegulationFlag]
    severity: str = Field(
        default="safe",
        description="최종 등급 block|warn|safe (하이브리드 반영, 신규 필드)")
    rule_severity: str = Field(
        default="safe", description="룰 1차 등급 (LLM 교정 전, 신규 필드)")
    escalated: bool = Field(
        default=False, description="경계 케이스로 판단되어 LLM 2차 검증을 거쳤는지")
    escalation_reason: Optional[str] = Field(
        default=None, description="에스컬레이션 사유 (라우팅 판단 근거)")
    llm_opinion: Optional[str] = Field(
        default=None, description="LLM 맥락 판단 근거 (use_llm=true, 에스컬레이션 시)")
    suggestion: Optional[dict] = Field(
        default=None, description="안전한 대체 문구 제안 {headline, sub} (차기: 프론트 협의 후)")
    meta: dict


def check_rules(text: str, category: str) -> list[RegulationFlag]:
    """룰 기반 금지/주의 표현 매칭 (비용 0, 즉시).

    block을 앞에, warn을 뒤에 정렬해서 반환 (프론트 표시 우선순위).
    """
    flags = []
    for pattern, severity, reason, suggestion in CATEGORY_RULES.get(
            category, CATEGORY_RULES["food"]):
        m = re.search(pattern, text)
        if m:
            matched = m.group(0)
            # 화이트리스트 guard: 법적 승인 표현('OO에 도움을 주는')이면 오탐으로 보고 통과.
            # 단정어(제거/보장/완치 등)가 함께 있으면 guard 미적용(is_whitelisted 내부 처리).
            if is_whitelisted(matched, text):
                continue
            # 대체표현을 법적 승인 표현으로 강화 (있으면 우선)
            approved = approved_expression(matched)
            flags.append(RegulationFlag(
                matched=matched, severity=severity, reason=reason,
                suggestion=f"'{approved}'" if approved else suggestion))
    flags.sort(key=lambda f: 0 if f.severity == "block" else 1)
    return flags


# [구버전 - 미사용] 하이브리드 전환으로 대체됨. 대체문구 rewrite 기능을
# 차기에 붙일 때 프롬프트 재료로 남겨둠 (프론트 협의 후 결정).
_LLM_VALIDATE_PROMPT = """당신은 한국 광고 규제(표시광고법, 식품표시광고법, 화장품법) 전문 심의관입니다.
아래 광고 문구가 규제 위반 소지가 있는지 판단하고, 위반 소지가 있다면
의미를 최대한 유지하면서 안전한 대체 문구를 제안하세요.

[카테고리] {category}
[headline] {headline}
[sub] {sub}
[룰 검사에서 걸린 표현] {rule_flags}

반드시 JSON으로만 응답:
{{"opinion": "위반 여부와 근거를 2문장 이내로",
  "risky": true|false,
  "suggestion": {{"headline": "대체 headline ({headline_max}자 이내)",
                 "sub": "대체 sub ({sub_max}자 이내)"}}}}
(risky=false면 suggestion은 원문 그대로)"""


def validate_copy(req: ValidateRequest) -> ValidateResponse:
    """룰 1차 + (use_llm=true 시) 하이브리드 LLM 2차 검증.

    하이브리드 (팀 확정 정책, 실측 근거 docs/설계_LLM검증레이어.md):
      - 라우팅: broad 기본(데모 정확도 우선). 경계 케이스만 LLM 호출.
      - 신뢰: asymmetric — 등급 상향은 즉시 반영, 하향은 근거 있을 때만.
      - 실측: HOLDOUT 90.6%→100%, 파손(2차 오판) 0건.
    구버전 단발 LLM opinion 경로는 하이브리드로 대체됨. LLM 대체문구
    rewrite는 프론트 협의 후 차기(suggestion 필드는 유지).
    """
    t0 = time.time()
    full_text = f"{req.headline} {req.sub}"
    flags = check_rules(full_text, req.category)
    rule_sev = ("block" if any(f.severity == "block" for f in flags)
                else ("warn" if flags else "safe"))
    severity = rule_sev

    escalated = False
    esc_reason = None
    llm_opinion = None
    suggestion = None

    if req.use_llm:
        # 순환 import 방지를 위해 함수 내부에서 import
        from .regulation_llm import (
            escalation_decision, build_llm_judge, apply_trust)
        decision = escalation_decision(
            flags, full_text, req.category, policy=req.policy)
        escalated = decision.escalate
        esc_reason = decision.reason
        if decision.escalate:
            if config.MOCK_MODE:
                llm_opinion = "(mock) 맥락 확인 결과 룰 판정 유지."
                suggestion = {"headline": req.headline, "sub": req.sub}
            else:
                from .chatbot import _client_chat
                judge = build_llm_judge(
                    lambda msgs: _client_chat(msgs, temperature=0))
                verdict = judge(req.headline, req.sub, req.category,
                                rule_sev, decision.direction)
                severity = apply_trust(rule_sev, verdict, "monotonic")
                llm_opinion = verdict.reason

    safe = severity != "block"

    return ValidateResponse(
        safe=safe, flags=flags,
        severity=severity, rule_severity=rule_sev,
        escalated=escalated, escalation_reason=esc_reason,
        llm_opinion=llm_opinion, suggestion=suggestion,
        meta={"elapsed": round(time.time() - t0, 3),
              "model": "rules" if not (req.use_llm and escalated) else config.MODEL_NAME,
              "policy": req.policy if req.use_llm else None,
              "trust": "monotonic" if req.use_llm else None,
              "mock": config.MOCK_MODE},
    )

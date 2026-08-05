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
import json
import re
import time
from typing import Optional

from pydantic import BaseModel, Field

from . import config
from .regulation_rules import CATEGORY_RULES, rule_stats

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
        default=False, description="LLM 맥락 검증 + 대체 문구 제안 (API 비용 발생)")


class ValidateResponse(BaseModel):
    safe: bool = Field(description="block 위반이 없으면 True")
    flags: list[RegulationFlag]
    llm_opinion: Optional[str] = Field(
        default=None, description="LLM 맥락 판단 (use_llm=true 시)")
    suggestion: Optional[dict] = Field(
        default=None, description="안전한 대체 문구 제안 {headline, sub}")
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
            flags.append(RegulationFlag(
                matched=m.group(0), severity=severity,
                reason=reason, suggestion=suggestion))
    flags.sort(key=lambda f: 0 if f.severity == "block" else 1)
    return flags


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
    t0 = time.time()
    full_text = f"{req.headline} {req.sub}"
    flags = check_rules(full_text, req.category)
    safe = not any(f.severity == "block" for f in flags)

    llm_opinion = None
    suggestion = None

    if req.use_llm:
        if config.MOCK_MODE:
            llm_opinion = "(mock) 룰 검사 외 추가 위반 소지 없음."
            suggestion = {"headline": req.headline, "sub": req.sub}
        else:
            from openai import OpenAI
            client = OpenAI(api_key=config.OPENAI_API_KEY)
            prompt = _LLM_VALIDATE_PROMPT.format(
                category=req.category, headline=req.headline, sub=req.sub,
                rule_flags=", ".join(f.matched for f in flags) or "(없음)",
                headline_max=config.HEADLINE_MAX, sub_max=config.SUB_MAX,
            )
            resp = client.chat.completions.create(
                model=config.MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            data = json.loads(resp.choices[0].message.content)
            llm_opinion = str(data.get("opinion", ""))
            suggestion = data.get("suggestion")
            if data.get("risky"):
                safe = False

    return ValidateResponse(
        safe=safe, flags=flags,
        llm_opinion=llm_opinion, suggestion=suggestion,
        meta={"elapsed": round(time.time() - t0, 3),
              "model": "rules" if not req.use_llm else config.MODEL_NAME,
              "mock": config.MOCK_MODE},
    )

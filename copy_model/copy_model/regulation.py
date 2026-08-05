"""광고 규제 필터링 모듈 (프로토타입).

2단계 검증:
  1) 룰 기반 (무료·즉시): 카테고리별 금지/주의 표현 사전 매칭
     - 표시광고법 공통 + 식품표시광고법(푸드) + 화장품법(뷰티) 대표 사례
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

# ── 룰 사전 ─────────────────────────────────────────────
# severity: "block"(사용 불가 수준) / "warn"(맥락 확인 필요)
_COMMON_RULES = [
    (r"(최고|최상|제일|넘버\s*원|no\.?\s*1|1\s*위)", "warn",
     "표시광고법: 객관적 근거 없는 최상급 표현은 부당광고 소지"),
    (r"(100\s*%|백\s*퍼센트|완벽|완전\s*무결)", "warn",
     "표시광고법: 검증 불가능한 확정적 표현"),
    (r"(유일|국내\s*유일|세계\s*유일)", "warn",
     "표시광고법: 배타성 주장은 입증 자료 필요"),
    (r"(보장|장담)", "warn",
     "표시광고법: 효과·결과 보장 표현 주의"),
    (r"(타사|경쟁사|타\s*브랜드)\s*(대비|보다)", "warn",
     "표시광고법: 근거 없는 비교광고 금지"),
]

_FOOD_RULES = [
    (r"(치료|치유|낫는다|완치)", "block",
     "식품표시광고법 §8: 질병 치료 효능 표방 금지"),
    (r"(예방|항암|항염|항균|살균)", "block",
     "식품표시광고법 §8: 질병 예방·의약품 오인 표현 금지"),
    (r"(다이어트\s*(효과|보장)|살\s*빠지는|지방\s*분해)", "block",
     "식품표시광고법: 체중 감량 효능 표방 금지 (건기식 인증 필요)"),
    (r"(면역력\s*(강화|증진)|디톡스|해독)", "block",
     "식품표시광고법: 신체 기능 개선 표방 주의 (기능성 인정 필요)"),
    (r"(숙취\s*해소)", "warn",
     "식약처 고시: 숙취해소 표현은 인체적용시험 근거 필요(2025~)"),
]

_BEAUTY_RULES = [
    (r"(치료|치유|의학적|병원\s*급)", "block",
     "화장품법 §13: 의약품 오인 우려 표현 금지"),
    (r"(아토피|여드름\s*(치료|개선)|습진|건선)", "block",
     "화장품법: 질환명 언급은 의약품 오인 광고"),
    (r"(재생|세포\s*(재생|활성)|콜라겐\s*생성)", "warn",
     "화장품법: 신체 개선 효능 단정 주의"),
    (r"(주름\s*(제거|박멸)|미백\s*보장)", "block",
     "화장품법: 기능성 인증 범위 초과 표현 (개선 '도움' 수준만 가능)"),
    (r"(부작용\s*(전혀|절대)\s*없)", "block",
     "화장품법: 부작용 부재 단정 금지"),
]

_GOODS_RULES = [
    (r"(정품\s*보다|명품\s*급|짝퉁)", "warn",
     "상표법/표시광고법: 타 브랜드 연상·비교 표현 주의"),
    (r"(친환경|에코)", "warn",
     "환경성 표시광고 고시: 인증 없는 친환경 주장(그린워싱) 주의"),
]

CATEGORY_RULES = {
    "food": _COMMON_RULES + _FOOD_RULES,
    "beauty": _COMMON_RULES + _BEAUTY_RULES,
    "goods": _COMMON_RULES + _GOODS_RULES,
}


class RegulationFlag(BaseModel):
    matched: str = Field(description="걸린 표현")
    severity: str = Field(description="block | warn")
    reason: str = Field(description="관련 규제 및 사유")


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
    """룰 기반 금지/주의 표현 매칭 (비용 0, 즉시)."""
    flags = []
    for pattern, severity, reason in CATEGORY_RULES.get(category, _COMMON_RULES):
        m = re.search(pattern, text)
        if m:
            flags.append(RegulationFlag(
                matched=m.group(0), severity=severity, reason=reason))
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

"""챗봇 슬롯필링 모듈 (LLM 로직만 — UI/화면 흐름은 프론트 파트 담당).

컨셉 (팀 방향): 사용자가 자유롭게 입력하되, 클로드처럼
"1, 2, 3번 + 기타(직접 입력)" 선택지를 제시하며 니즈를 좁혀 나감.

흐름:
  사용자 메시지 → LLM이 현재까지 파악된 스펙(slot) 갱신
  → 부족한 슬롯이 있으면: 다음 질문 1개 + 선택지 3개 제시 (done=false)
  → 슬롯이 충분하면: done=true + 문구 생성에 바로 쓸 spec 반환
     (spec은 CopyRequest와 동일 구조 → 그대로 /generate/copy 호출 가능)

수집 슬롯: category, product, tone, keywords, (선택) request
"""
import json
import time
from typing import Optional

from pydantic import BaseModel, Field

from . import config

SLOT_SYSTEM_PROMPT = """당신은 소상공인 광고 콘텐츠 제작 서비스의 도우미 챗봇입니다.
사용자와 대화하며 광고 문구 제작에 필요한 정보를 수집합니다.

[수집할 슬롯]
- category: "food" | "beauty" | "goods" 중 하나
- product: 제품/가게 이름 (구체적으로)
- tone: "warm" | "energetic" | "luxury" | "simple" 중 하나
- keywords: 강조할 키워드 1~3개
- request: 추가 요청사항 (선택, 없어도 됨)

[진행 규칙]
1. 대화 이력과 새 메시지에서 파악 가능한 슬롯을 모두 채운다.
2. category, product, tone, keywords가 모두 채워지면 done=true.
3. 부족하면 done=false로 하고, 가장 중요한 미수집 슬롯 1개에 대해
   질문 1개 + 사용자가 고르기 쉬운 선택지 3개를 제시한다.
   선택지는 이미 파악된 맥락에 맞게 구체적으로 만든다.
   (예: 떡볶이 가게라면 톤 선택지를 "매콤한 길거리 감성" 같이 맥락화)
4. 한 번에 질문은 반드시 1개만.
5. 반드시 JSON으로만 응답:
{"spec": {"category": null|"food"|"beauty"|"goods", "product": null|"...",
  "tone": null|"warm"|"energetic"|"luxury"|"simple",
  "keywords": null|["..."], "request": null|"..."},
 "done": true|false,
 "question": "...", "options": ["...", "...", "..."]}
(done=true면 question은 확인 멘트, options는 빈 배열)"""


class ChatTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class SuggestRequest(BaseModel):
    message: str = Field(min_length=1, description="사용자 입력 (자유 텍스트 또는 선택지)")
    history: Optional[list[ChatTurn]] = Field(default=None, description="이전 대화 이력")


class SuggestResponse(BaseModel):
    spec: dict = Field(description="현재까지 채워진 슬롯 (done=true면 /generate/copy 요청 바디로 사용 가능)")
    done: bool
    question: str
    options: list[str] = Field(description="선택지 (프론트에서 '기타' 직접입력 항목을 항상 추가로 노출)")
    meta: dict


_MOCK_FLOW = SuggestResponse(
    spec={"category": "food", "product": "떡볶이 가게", "tone": None,
          "keywords": None, "request": None},
    done=False,
    question="어떤 분위기의 문구를 원하세요?",
    options=["매콤한 길거리 감성", "모던한 K-푸드 스타일", "정겨운 동네 분식집"],
    meta={"elapsed": 0.0, "model": "mock", "mock": True},
)


def suggest_options(req: SuggestRequest) -> SuggestResponse:
    t0 = time.time()

    if config.MOCK_MODE:
        return _MOCK_FLOW

    from openai import OpenAI
    client = OpenAI(api_key=config.OPENAI_API_KEY)

    messages = [{"role": "system", "content": SLOT_SYSTEM_PROMPT}]
    for turn in req.history or []:
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": req.message})

    resp = client.chat.completions.create(
        model=config.MODEL_NAME,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.5,
    )
    data = json.loads(resp.choices[0].message.content)

    return SuggestResponse(
        spec=data.get("spec", {}),
        done=bool(data.get("done", False)),
        question=str(data.get("question", "")),
        options=[str(o) for o in data.get("options", [])][:3],
        meta={"elapsed": round(time.time() - t0, 3),
              "model": config.MODEL_NAME, "mock": False},
    )

"""문구 생성 핵심 로직.

흐름:
1. 카테고리/톤 기반 프롬프트 구성 → OpenAI API 호출 (JSON 응답 강제)
2. 각 시안 글자 수 검증 (공백 포함)
3. 초과 시 LLM 축약 재시도 (SHORTEN_RETRIES회)
4. 그래도 초과하면 over_limit=True 로 표시해서 반환
   (프론트에서 자르지 않기로 팀 합의 — 포스터 쪽 자동 줄바꿈이 최종 안전망)

COPY_MOCK=1 이면 API 호출 없이 샘플 반환 (비용 0, 프론트 연동 테스트용)
"""
import json
import time

from . import config, prompts
from .regulation import check_rules
from .schemas import CopyCandidate, CopyMeta, CopyRequest, CopyResponse

_MOCK_SAMPLES = {
    "food": [
        ("오늘 갓 구운 행복 한 조각", "매일 아침 매장에서 직접 굽는 수제 케이크"),
        ("바삭함이 다르다, 진심의 빵", "천연 발효종으로 24시간 숙성한 반죽"),
        ("하루의 쉼표, 달콤한 한 입", "커피와 어울리는 시그니처 디저트"),
    ],
    "beauty": [
        ("피부가 먼저 아는 촉촉함", "저자극 성분으로 매일 쓰기 좋은 수분 케어"),
        ("가볍게 스며드는 데일리 무드", "끈적임 없이 산뜻한 마무리"),
        ("오늘의 나를 위한 한 겹", "민감한 날에도 부담 없는 순한 처방"),
    ],
    "goods": [
        ("일상에 스미는 작은 취향", "책상 위 분위기를 바꾸는 감성 소품"),
        ("선물하고 싶은 마음을 담다", "받는 사람이 먼저 웃게 되는 굿즈"),
        ("하루를 담는 작은 다이어리", "매일 쓰고 싶어지는 나만의 기록"),
    ],
}


def _count(text: str) -> int:
    """글자 수 카운트: 공백 포함 (팀 기준 확정 전까지 단순 len 사용)."""
    return len(text)


def _client():
    from openai import OpenAI
    return OpenAI(api_key=config.OPENAI_API_KEY)


def _chat_json(client, system: str, user: str) -> dict:
    resp = client.chat.completions.create(
        model=config.MODEL_NAME,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0.9,
    )
    return json.loads(resp.choices[0].message.content)


def _shorten(client, headline: str, sub: str) -> tuple[str, str]:
    prompt = prompts.SHORTEN_PROMPT.format(
        h_len=_count(headline), s_len=_count(sub),
        headline_max=config.HEADLINE_MAX, sub_max=config.SUB_MAX,
        headline=headline, sub=sub,
    )
    data = _chat_json(client, "당신은 광고 문구를 다듬는 카피라이터입니다.", prompt)
    return data.get("headline", headline), data.get("sub", sub)


def _validate(client, headline: str, sub: str) -> tuple[str, str, bool]:
    """글자 수 검증 + 필요 시 축약 재시도. 반환: (headline, sub, over_limit)"""
    retries = config.SHORTEN_RETRIES
    while (_count(headline) > config.HEADLINE_MAX or _count(sub) > config.SUB_MAX):
        if retries <= 0 or client is None:
            return headline, sub, True
        headline, sub = _shorten(client, headline, sub)
        retries -= 1
    return headline, sub, False


_MOCK_EN = ("Freshly Baked Happiness, Daily", "Handcrafted in-store every morning")


def _localize(client, headline: str, sub: str, product: str, category: str) -> tuple[str, str]:
    """한국어 문구를 영어권 감성에 맞게 재창작(transcreation)."""
    prompt = prompts.LOCALIZE_PROMPT.format(
        headline_max_en=config.HEADLINE_MAX_EN, sub_max_en=config.SUB_MAX_EN,
        headline=headline, sub=sub, product=product, category=category,
    )
    data = _chat_json(client, "You are a transcreation copywriter.", prompt)
    return (str(data.get("headline_en", "")).strip()[: config.HEADLINE_MAX_EN + 10],
            str(data.get("sub_en", "")).strip()[: config.SUB_MAX_EN + 20])


def _mock_response(req: CopyRequest, t0: float) -> CopyResponse:
    samples = _MOCK_SAMPLES[req.category][: req.num_candidates]
    candidates = [
        CopyCandidate(
            id=f"c{i+1}", headline=h, sub=s,
            headline_chars=_count(h), sub_chars=_count(s),
            headline_en=_MOCK_EN[0] if req.include_en else None,
            sub_en=_MOCK_EN[1] if req.include_en else None,
        )
        for i, (h, s) in enumerate(samples)
    ]
    meta = CopyMeta(elapsed=round(time.time() - t0, 3),
                    model="mock", mock=True)
    return CopyResponse(candidates=candidates, meta=meta)


def generate_copy(req: CopyRequest) -> CopyResponse:
    t0 = time.time()

    if config.MOCK_MODE:
        return _mock_response(req, t0)

    client = _client()
    system = prompts.build_system_prompt(
        req.category, req.tone, req.num_candidates,
        config.HEADLINE_MAX, config.SUB_MAX)
    user = prompts.build_user_prompt(
        req.product, req.keywords, req.request, req.num_candidates)

    data = _chat_json(client, system, user)
    raw = data.get("candidates", [])[: req.num_candidates]

    candidates = []
    for i, c in enumerate(raw):
        headline, sub, over = _validate(
            client, str(c.get("headline", "")).strip(), str(c.get("sub", "")).strip())
        headline_en = sub_en = None
        if req.include_en:
            headline_en, sub_en = _localize(client, headline, sub,
                                            req.product, req.category)
        flags = check_rules(f"{headline} {sub}", req.category)
        candidates.append(CopyCandidate(
            id=f"c{i+1}", headline=headline, sub=sub,
            headline_chars=_count(headline), sub_chars=_count(sub),
            over_limit=over, headline_en=headline_en, sub_en=sub_en,
            regulation_flags=[f.model_dump() for f in flags],
        ))

    meta = CopyMeta(elapsed=round(time.time() - t0, 3), model=config.MODEL_NAME)
    return CopyResponse(candidates=candidates, meta=meta)

"""카테고리/톤별 프롬프트 템플릿.

- 카테고리: food(맛집·카페·베이커리) / beauty(스킨케어·메이크업) / goods(소품·잡화·문구)
- 톤: warm(따뜻·감성) / energetic(발랄·활기) / luxury(고급·세련) / simple(간결·정보형)

규제 관련: 확정 표현("100% 효과", "최고", 의학적 효능 단정 등)은 시스템 프롬프트에서
1차로 차단. 별도 규제 검증 노드는 추후 규제 필터링 모듈에서 담당 예정.
"""

CATEGORY_GUIDES = {
    "food": (
        "업종: 음식점/카페/베이커리 등 F&B 소상공인.\n"
        "먹음직스러움, 신선함, 갓 만든 느낌을 살린다. "
        "미각·후각을 자극하는 구체적 표현(갓 구운, 바삭한, 진한)을 활용한다."
    ),
    "beauty": (
        "업종: 스킨케어/메이크업 등 뷰티 소상공인.\n"
        "질감·사용감·무드를 살린다. 단, 의학적 효능(치료, 미백 보장, 주름 제거 등)을 "
        "단정하는 표현은 화장품 광고 규제상 금지이므로 절대 쓰지 않는다."
    ),
    "goods": (
        "업종: 소품/잡화/문구 등 굿즈 소상공인.\n"
        "감성, 취향, 소장 가치를 살린다. 일상 속 작은 행복, 선물하기 좋은 느낌을 강조한다."
    ),
}

TONE_GUIDES = {
    "warm": "톤: 따뜻하고 감성적. 부드러운 어미(-요, -해요), 잔잔한 정서.",
    "energetic": "톤: 발랄하고 활기참. 리듬감 있는 짧은 문장, 느낌표 활용 가능.",
    "luxury": "톤: 고급스럽고 세련됨. 절제된 단어, 명사형 마무리 선호.",
    "simple": "톤: 간결하고 정보 중심. 수식어 최소화, 핵심 가치만 전달.",
}

SYSTEM_PROMPT = """당신은 한국 소상공인을 위한 광고 카피라이터입니다.
제품/가게 정보를 받아 광고 포스터에 들어갈 문구를 만듭니다.

[출력 규칙 — 반드시 지킬 것]
1. headline은 공백 포함 {headline_max}자 이내, sub는 공백 포함 {sub_max}자 이내.
   이미지 위에 올라가는 문구라 초과하면 잘리거나 글자가 작아짐. 제한을 엄수할 것.
2. headline은 시선을 끄는 핵심 카피, sub는 이를 보완하는 부가 설명.
3. 서로 다른 방향의 시안 {num}개를 만들 것 (표현·구도가 겹치지 않게).
4. 반드시 아래 JSON 형식으로만 응답:
{{"candidates": [{{"headline": "...", "sub": "..."}}, ...]}}

[광고 규제 — 절대 금지 표현]
- "최고", "제일", "100%", "완벽" 등 검증 불가능한 최상급·확정 표현
- 의학적 효능·효과를 단정하는 표현 (질병 치료·예방, 다이어트 보장 등)
- 근거 없는 수치나 비교 ("타사 대비 2배" 등)

{category_guide}
{tone_guide}"""

USER_PROMPT = """[제품/가게 정보]
- 이름: {product}
- 강조 키워드: {keywords}
- 추가 요청사항: {request}

위 정보로 포스터 문구 시안 {num}개를 JSON으로 만들어주세요."""

SHORTEN_PROMPT = """다음 광고 문구가 글자 수 제한을 초과했습니다.
의미와 톤은 유지하면서 제한 이내로 줄여주세요.

- headline (현재 {h_len}자 → {headline_max}자 이내): {headline}
- sub (현재 {s_len}자 → {sub_max}자 이내): {sub}

반드시 JSON 형식으로만 응답: {{"headline": "...", "sub": "..."}}"""


LOCALIZE_PROMPT = """당신은 한국 브랜드의 글로벌 마케팅을 돕는 현지화 카피라이터입니다.
아래 한국어 광고 문구를 영어로 옮기되, 직역하지 말고
영어권 소비자에게 자연스럽게 매력적인 마케팅 카피로 재창작(transcreation)하세요.

[규칙]
1. headline_en은 {headline_max_en}자 이내, sub_en은 {sub_max_en}자 이내 (영문 기준, 공백 포함).
2. K-푸드/K-뷰티/K-굿즈의 한국적 매력은 살리되, 현지인이 어색해할 표현은 피할 것.
   (예: 콩글리시, 지나친 직역, 문화 설명 없이는 이해 불가한 표현)
3. 원문의 톤(감성/발랄/고급/간결)을 유지할 것.
4. 반드시 JSON으로만 응답: {{"headline_en": "...", "sub_en": "..."}}

[한국어 원문]
- headline: {headline}
- sub: {sub}
- 제품/가게: {product} (카테고리: {category})"""


def build_system_prompt(category: str, tone: str, num: int,
                        headline_max: int, sub_max: int) -> str:
    return SYSTEM_PROMPT.format(
        headline_max=headline_max,
        sub_max=sub_max,
        num=num,
        category_guide=CATEGORY_GUIDES.get(category, CATEGORY_GUIDES["food"]),
        tone_guide=TONE_GUIDES.get(tone, TONE_GUIDES["warm"]),
    )


def build_user_prompt(product: str, keywords: list[str] | None,
                      request: str | None, num: int) -> str:
    return USER_PROMPT.format(
        product=product,
        keywords=", ".join(keywords) if keywords else "(없음)",
        request=request or "(없음)",
        num=num,
    )

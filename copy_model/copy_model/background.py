"""배경 레퍼런스 사진 → 시각 언어(BackgroundContext) 추출.

8/18 확정:
- 이미지 입력은 제품 사진 1장(필수) + 배경 레퍼런스 1장(선택).
- 배경 레퍼런스는 Vision으로 색감/조명/질감/분위기/구도 같은 시각 언어만 추출한다.
- 제품 사진과 달리 사용자 재확인 단계는 두지 않는다(리스크 낮음).

경계(중요):
- 배경 추출 결과는 절대 spec.product로 넘기지 않는다.
  spec.background_context로만 분리 저장한다. product 슬롯은 규제 검증과 문구
  근거의 소유 슬롯이라, 배경 특징이 섞이면 근거가 오염된다.
- 이 background_context는 이후 AI Design Planner의 Visual Prompt 입력으로 쓴다.
- poster API로 어떤 필드를 넘길지는 후속 계약(지우님 poster API)에서 확정한다.
  현재 모듈은 spec에 background_context를 채우는 데까지만 책임진다.
"""
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from . import config
from .vision import validate_image_data_url


class BackgroundImageRequest(BaseModel):
    """프론트가 FileReader.readAsDataURL()로 만든 배경 레퍼런스 사진."""

    image_data_url: str = Field(min_length=32)

    @field_validator("image_data_url")
    @classmethod
    def _validate_image_data_url(cls, value: str) -> str:
        # 제품 사진과 동일한 포맷/크기/시그니처 검증을 재사용.
        return validate_image_data_url(value)


class BackgroundAdvanceRequest(BaseModel):
    """배경 레퍼런스 + 현재 spec을 함께 받는 endpoint 요청 모델."""

    image_data_url: str = Field(min_length=32)
    spec: dict = Field(default_factory=dict)

    @field_validator("image_data_url")
    @classmethod
    def _validate_image_data_url(cls, value: str) -> str:
        return validate_image_data_url(value)


class BackgroundContext(BaseModel):
    """배경 레퍼런스에서 관찰 가능한 시각 언어만 담는다."""

    palette: list[str] = Field(default_factory=list)      # 색감
    lighting: Optional[str] = None                        # 조명
    texture: list[str] = Field(default_factory=list)      # 질감
    mood: Optional[str] = None                            # 분위기
    composition: Optional[str] = None                     # 구도
    # 인식 가능 여부. usable=False면 배경 없이 진행(프론트는 무시 가능).
    usable: bool = True


class BackgroundVisionResponse(BaseModel):
    context: BackgroundContext
    meta: dict = Field(default_factory=dict)


_BACKGROUND_SYSTEM_PROMPT = """당신은 광고 포스터 배경 레퍼런스 분석기입니다.

첨부된 이미지에서 "배경으로 참고할 시각적 특징"만 구조화하세요.
제품명, 브랜드, 문구, 효능 같은 정보는 추출하지 마세요. 오직 시각 언어만.

palette: 주요 색감 2~4개 (예: "웜 베이지", "딥 그린").
lighting: 조명 특징 한 마디 (예: "부드러운 자연광", "따뜻한 스팟 조명").
texture: 질감 특징 (예: "매트한 종이", "우드 그레인").
mood: 전체 분위기 한 마디 (예: "차분하고 고급스러운").
composition: 구도 특징 한 마디 (예: "중앙 여백이 넓은 미니멀 구성").
usable: 배경 참고로 쓸 만하면 true, 분석 불가/부적합하면 false.
        반드시 JSON boolean(true/false)로 반환하세요. "true"/"false" 같은 문자열 금지.

palette/texture는 문자열 배열, lighting/mood/composition은 문자열 또는 null.
관찰되지 않는 항목은 비우세요(빈 배열 또는 null).
JSON 외의 문장은 출력하지 마세요.
"""


def _clean_list(value, limit: int = 4) -> list[str]:
    """문자열 항목만 인정한다. 리스트가 아니거나 비-문자열 항목은 버린다.

    (숫자/객체 등 잘못된 타입이 str()로 변환돼 색감·질감에 섞이는 것을 막는다.)
    """
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _clean_str(value) -> Optional[str]:
    """실제 문자열일 때만 인정한다. 그 외 타입은 None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _finalize_background(raw: dict) -> BackgroundContext:
    """LLM 출력을 서버 규칙으로 정규화한다. 신뢰하지 않고 타입까지 방어한다."""
    if not isinstance(raw, dict):
        raw = {}

    palette = _clean_list(raw.get("palette"), limit=4)
    texture = _clean_list(raw.get("texture"), limit=4)
    lighting = _clean_str(raw.get("lighting"))
    mood = _clean_str(raw.get("mood"))
    composition = _clean_str(raw.get("composition"))

    # usable은 실제 JSON boolean(True)일 때만 인정한다(소원님 리뷰).
    # "false" 같은 문자열/누락/잘못된 타입은 모두 False로 안전 처리 —
    # bool("false")==True 함정으로 사용 불가 배경이 기록되는 것을 막는다.
    usable = raw.get("usable") is True

    # 아무 시각 근거도 없으면(전부 빈 값) 사용 불가로 본다.
    if not any([palette, texture, lighting, mood, composition]):
        usable = False

    return BackgroundContext(
        palette=palette,
        lighting=lighting,
        texture=texture,
        mood=mood,
        composition=composition,
        usable=usable,
    )


def _mock_background() -> BackgroundContext:
    """프론트/API 계약 테스트용 — 외부 API 비용 0."""
    return _finalize_background({
        "palette": ["웜 베이지", "소프트 크림"],
        "lighting": "부드러운 자연광",
        "texture": ["매트한 종이"],
        "mood": "차분하고 고급스러운",
        "composition": "중앙 여백이 넓은 미니멀 구성",
        "usable": True,
    })


def _call_background_vision(req: BackgroundImageRequest) -> dict:
    """GPT Vision 1회 호출. 결과는 dict로만 반환."""
    from openai import OpenAI

    client = OpenAI(api_key=config.OPENAI_API_KEY)

    user_text = (
        "첨부된 배경 레퍼런스 이미지의 시각 언어를 아래 JSON으로 반환하세요:\n"
        "{\n"
        '  "palette": string[],\n'
        '  "lighting": string|null,\n'
        '  "texture": string[],\n'
        '  "mood": string|null,\n'
        '  "composition": string|null,\n'
        '  "usable": boolean\n'
        "}"
    )

    resp = client.chat.completions.create(
        model=config.MODEL_NAME,
        messages=[
            {"role": "system", "content": _BACKGROUND_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": req.image_data_url},
                    },
                ],
            },
        ],
        response_format={"type": "json_object"},
    )

    import json

    content = resp.choices[0].message.content
    # 빈 응답 / 깨진 JSON은 크래시(500) 대신 빈 dict로 안전 처리한다.
    # 빈 dict는 _finalize_background에서 usable=False가 되어 배경 없이 진행된다.
    # (소원님 리뷰: {invalid json 같은 실제 파싱 실패 경로 방어)
    if not content:
        return {}
    try:
        return json.loads(content)
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def analyze_background_image(
    req: BackgroundImageRequest,
) -> BackgroundVisionResponse:
    """배경 레퍼런스를 분석해 BackgroundContext를 반환한다(재확인 단계 없음)."""
    if config.MOCK_MODE:
        return BackgroundVisionResponse(
            context=_mock_background(),
            meta={"model": "mock", "mock": True},
        )

    if not config.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")

    raw = _call_background_vision(req)
    return BackgroundVisionResponse(
        context=_finalize_background(raw),
        meta={"model": config.MODEL_NAME, "mock": False},
    )


def apply_background_context(spec: dict, context: BackgroundContext) -> dict:
    """배경 시각 언어를 spec.background_context로만 저장한다.

    product/product_context 등 다른 슬롯은 절대 건드리지 않는다.
    usable=False면 background_context를 남기지 않는다(배경 없이 진행).
    """
    next_spec = dict(spec or {})

    if not context.usable:
        next_spec.pop("background_context", None)
        return next_spec

    next_spec["background_context"] = {
        "palette": list(context.palette),
        "lighting": context.lighting,
        "texture": list(context.texture),
        "mood": context.mood,
        "composition": context.composition,
    }
    return next_spec


def advance_background_image(
    req: BackgroundAdvanceRequest,
) -> BackgroundVisionResponse:
    """배경 이미지를 분석하고 spec.background_context에 반영해 반환한다.

    반환 meta.spec에 갱신된 spec을 함께 실어 프론트가 그대로 들고 갈 수 있게 한다.
    """
    result = analyze_background_image(
        BackgroundImageRequest(image_data_url=req.image_data_url)
    )
    updated = apply_background_context(req.spec or {}, result.context)
    return BackgroundVisionResponse(
        context=result.context,
        meta={**result.meta, "spec": updated},
    )

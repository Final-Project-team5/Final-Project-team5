"""제품 사진 → 문구 모델용 ProductContext 변환.

목적:
- 제품형(product) 3단계에서 사용자가 제품명을 직접 입력하지 않는다.
- 업로드한 제품 사진을 Vision LLM이 분석해 spec.product의 근거가 되는
  구조화 ProductContext를 반환한다.
- Vision 결과가 애매하거나 사용자가 선택한 category와 맞지 않으면
  자동 채움하지 않고 confirm/reupload로 분기한다.

중요:
- 이미지에서 관찰 가능한 정보만 추출한다.
- 효능, 성분, 지속시간, 품질 등 보이지 않는 사실은 추정하지 않는다.
"""
import base64
import binascii
import json
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from . import config


ProductCategory = Literal["food", "beauty", "goods"]
RecognitionStatus = Literal["clear", "ambiguous", "invalid"]
DetectedCategory = Literal["food", "beauty", "goods", "unknown"]
NextAction = Literal["auto_fill", "confirm", "reupload"]


_DATA_URL_RE = re.compile(
    r"^data:image/(png|jpeg|jpg|webp);base64,",
    re.IGNORECASE,
)

MAX_IMAGE_BYTES = 8 * 1024 * 1024

_IMAGE_MAGIC = {
    "png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
    "jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
    "jpg": lambda b: b.startswith(b"\xff\xd8\xff"),
    "webp": lambda b: (
        len(b) >= 12
        and b[:4] == b"RIFF"
        and b[8:12] == b"WEBP"
    ),
}


def validate_image_data_url(value: str) -> str:
    """PNG/JPEG/WebP Data URL 공통 검증 (제품 사진 / 배경 레퍼런스 공용).

    strict base64, 8 MiB 상한, MIME/binary signature 일치까지 확인한다.
    """
    match = _DATA_URL_RE.match(value)
    if not match:
        raise ValueError(
            "image_data_url must be a png/jpeg/webp base64 Data URL."
        )

    encoded = value[match.end():]

    # Reject oversized payloads before decoding.
    max_encoded = ((MAX_IMAGE_BYTES + 2) // 3) * 4 + 8
    if len(encoded) > max_encoded:
        raise ValueError("image payload exceeds the 8 MiB limit.")

    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(
            "image payload is not valid base64."
        ) from exc

    if not raw:
        raise ValueError("image payload is empty.")

    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("image payload exceeds the 8 MiB limit.")

    image_type = match.group(1).lower()
    if not _IMAGE_MAGIC[image_type](raw):
        raise ValueError(
            "declared image MIME does not match the binary signature."
        )

    return value


class ProductVisionRequest(BaseModel):
    """프론트가 FileReader.readAsDataURL()로 만든 제품 사진을 받는다."""

    image_data_url: str = Field(min_length=32)
    category: ProductCategory

    @field_validator("image_data_url")
    @classmethod
    def _validate_image_data_url(cls, value: str) -> str:
        return validate_image_data_url(value)


class ProductContext(BaseModel):
    """광고 문구 및 후속 챗봇 단계가 사용하는 시각 근거."""

    product: Optional[str] = None

    # 사용자가 1단계에서 고른 업종.
    requested_category: ProductCategory

    # 이미지에서 실제로 보이는 제품의 업종.
    detected_category: DetectedCategory = "unknown"

    # requested_category == detected_category 여부.
    category_match: bool = False

    # 이미지에서 직접 관찰 가능한 특징만 저장.
    visible_features: list[str] = Field(default_factory=list)

    # 패키지 등에 실제로 읽히는 텍스트. 추측 금지.
    visible_text: list[str] = Field(default_factory=list)

    # clear: 단일 제품 종류를 충분히 식별
    # ambiguous: 후보가 여러 개이거나 식별 근거 부족
    # invalid: 제품 사진이 아니거나 분석 불가
    recognition_status: RecognitionStatus

    # ambiguous일 때만 최대 3개 후보.
    candidates: list[str] = Field(default_factory=list)

    # 서버가 결정적으로 계산하는 UX 분기.
    next_action: NextAction


class ProductVisionResponse(BaseModel):
    context: ProductContext
    meta: dict = Field(default_factory=dict)


_VISION_SYSTEM_PROMPT = """당신은 소상공인 광고 제작 서비스의 제품 사진 분석기입니다.

사진에서 직접 확인할 수 있는 사실만 구조화하세요.

절대 추정하면 안 되는 것:
- 제품 효능
- 성분
- 지속 시간
- 치료/개선 효과
- 품질이나 성능
- 보이지 않는 브랜드명
- 보이지 않는 세부 스펙

제품명(product)은 광고에 사용할 수 있는 일반적인 제품 종류로 표현하세요.
예: "립 틴트", "선크림", "쿠키 세트", "다이어리".

detected_category:
- food: 음식, 음료, 식품
- beauty: 화장품, 뷰티 제품
- goods: 생활용품, 문구, 소품, 기타 일반 상품
- unknown: 판단 불가

recognition_status:
- clear: 단일 제품 종류를 충분히 식별 가능
- ambiguous: 2개 이상의 제품 후보가 가능하거나 제품 종류를 확정하기 어려움
- invalid: 제품이 보이지 않음, 제품 사진이 아님, 또는 분석하기 어려움

visible_features에는 색상, 형태, 패키지 등 눈으로 직접 보이는 특징만 넣으세요.
visible_text에는 사진에서 실제로 읽을 수 있는 문자만 넣으세요.
IMPORTANT: visible_features must describe only the advertised product itself. Exclude hands, people, skin, nails, background, props, and surrounding objects.
IMPORTANT: visible_text must come only from the product or its packaging.
읽히지 않으면 빈 배열로 두세요.

JSON 외의 문장은 출력하지 마세요.
"""


def _clean_list(value, limit: int = 5) -> list[str]:
    if not isinstance(value, list):
        return []

    cleaned: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _finalize_context(
    raw: dict,
    requested_category: ProductCategory,
) -> ProductContext:
    """LLM 출력을 그대로 신뢰하지 않고 서버 규칙으로 정규화한다."""

    product_raw = raw.get("product")
    product = str(product_raw).strip() if product_raw else None
    if product == "":
        product = None

    detected = str(raw.get("detected_category", "unknown")).strip().lower()
    if detected not in {"food", "beauty", "goods", "unknown"}:
        detected = "unknown"

    status = str(raw.get("recognition_status", "invalid")).strip().lower()
    if status not in {"clear", "ambiguous", "invalid"}:
        status = "invalid"

    # clear인데 제품명이 없으면 clear로 인정하지 않는다.
    if status == "clear" and not product:
        status = "invalid"

    # invalid는 제품명을 자동 주입하지 않는다.
    if status == "invalid":
        product = None

    category_match = detected == requested_category

    if status == "invalid":
        next_action: NextAction = "reupload"
    elif status == "clear" and category_match:
        next_action = "auto_fill"
    else:
        # ambiguous 또는 category mismatch
        next_action = "confirm"

    candidates = _clean_list(raw.get("candidates"), limit=3)
    if status != "ambiguous":
        candidates = []

    return ProductContext(
        product=product,
        requested_category=requested_category,
        detected_category=detected,
        category_match=category_match,
        visible_features=_clean_list(raw.get("visible_features"), limit=5),
        visible_text=_clean_list(raw.get("visible_text"), limit=5),
        recognition_status=status,
        candidates=candidates,
        next_action=next_action,
    )


def _mock_context(category: ProductCategory) -> ProductContext:
    """프론트/API 계약 테스트용 — 외부 API 비용 0."""

    samples = {
        "food": {
            "product": "쿠키 세트",
            "detected_category": "food",
            "visible_features": ["박스 포장", "개별 쿠키가 보임"],
            "visible_text": [],
            "recognition_status": "clear",
            "candidates": [],
        },
        "beauty": {
            "product": "립 틴트",
            "detected_category": "beauty",
            "visible_features": ["원통형 패키지", "핑크 계열"],
            "visible_text": [],
            "recognition_status": "clear",
            "candidates": [],
        },
        "goods": {
            "product": "다이어리",
            "detected_category": "goods",
            "visible_features": ["책 형태", "하드 커버"],
            "visible_text": [],
            "recognition_status": "clear",
            "candidates": [],
        },
    }
    return _finalize_context(samples[category], category)


def _call_vision(req: ProductVisionRequest) -> dict:
    """GPT Vision 1회 호출. 결과는 아직 신뢰하지 않고 dict로만 반환."""

    from openai import OpenAI

    client = OpenAI(api_key=config.OPENAI_API_KEY)

    user_text = (
        f"사용자가 선택한 category는 '{req.category}'입니다. "
        "첨부된 제품 사진을 분석하세요.\n\n"
        "아래 JSON 스키마로 반환하세요:\n"
        "{\n"
        '  "product": string|null,\n'
        '  "detected_category": "food"|"beauty"|"goods"|"unknown",\n'
        '  "visible_features": string[],\n'
        '  "visible_text": string[],\n'
        '  "recognition_status": "clear"|"ambiguous"|"invalid",\n'
        '  "candidates": string[]\n'
        "}"
    )

    resp = client.chat.completions.create(
        model=config.MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": _VISION_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": user_text,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": req.image_data_url,
                        },
                    },
                ],
            },
        ],
        response_format={"type": "json_object"},
    )

    content = resp.choices[0].message.content
    if not content:
        raise ValueError("Vision 모델이 빈 응답을 반환했습니다.")

    return json.loads(content)



def apply_product_context(
    spec: dict,
    context: ProductContext,
) -> dict:
    """Store trusted Vision provenance without finalizing spec.product.

    8/14 회의 확정: Vision 인식만으로 spec.product를 확정하지 않는다.
    next_action=auto_fill은 "확인 UI에 인식값을 prefill해도 된다"는
    신호일 뿐이며, 최종 spec.product는 사용자 확인
    ([맞아요]/[수정할게요]) 이후 confirm 단계에서만 기록된다.

    A compact product_context is retained as provenance for future
    Evidence Registry / Claim-Locked Copy expansion.
    """
    next_spec = dict(spec or {})

    next_spec["product_context"] = {
        "product": context.product,
        "detected_category": context.detected_category,
        "category_match": context.category_match,
        "visible_features": list(context.visible_features),
        "visible_text": list(context.visible_text),
        "recognition_status": context.recognition_status,
        "next_action": context.next_action,
    }

    # Vision evidence never finalizes the product slot, and a
    # stale/previous product must not survive a new analysis either.
    next_spec.pop("product", None)

    return next_spec

def analyze_product_image(req: ProductVisionRequest) -> ProductVisionResponse:
    """제품 사진을 분석해 광고 문구용 ProductContext를 반환한다."""

    if config.MOCK_MODE:
        context = _mock_context(req.category)
        return ProductVisionResponse(
            context=context,
            meta={
                "model": "mock",
                "mock": True,
            },
        )

    if not config.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")

    raw = _call_vision(req)
    context = _finalize_context(raw, req.category)

    return ProductVisionResponse(
        context=context,
        meta={
            "model": config.MODEL_NAME,
            "mock": False,
        },
    )

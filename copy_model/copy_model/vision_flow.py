"""Product Vision -> user confirmation -> chatbot step-3 bridge.

8/14 회의 확정 흐름:

    제품 사진 업로드 -> Vision 인식 -> confirmation pending
    -> [맞아요]/[수정할게요] -> spec.product 확정 -> tone 단계

원칙:
- Vision 인식값(vision_product)과 사용자 확정값(confirmed_product)은
  같은 필드로 덮어쓰지 않고 provenance로 분리한다.
- 최종 spec.product는 사용자 확정값만 기록한다.
- 인식만으로 자동 확정/자동 다음 단계 진행은 하지 않는다.
- 다운스트림 LLM/mock은 Vision/사용자가 확정한 product를 덮어쓸 수 없다.
"""
import json
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from . import config
from .chatbot import (
    PRODUCT_CATEGORIES,
    SuggestResponse,
    _apply_aspect_ratio,
    _business_type,
    _client_chat,
    _effective_flow,
    _mock_slots_for,
)
from .vision import (
    ProductContext,
    ProductVisionRequest,
    ProductVisionResponse,
    analyze_product_image,
    apply_product_context,
)


ConfirmationSource = Literal["vision_confirmed", "user_corrected"]


def _validate_product_flow_spec(spec: dict) -> None:
    business_type = spec.get("business_type", "product")
    if business_type != "product":
        raise ValueError(
            "product Vision flow only supports business_type=product"
        )

    category = spec.get("category")
    if category not in PRODUCT_CATEGORIES:
        raise ValueError(
            "spec.category must be one of food/beauty/goods"
        )


class ProductVisionAdvanceRequest(BaseModel):
    image_data_url: str = Field(min_length=32)
    spec: dict

    @model_validator(mode="after")
    def validate_flow(self):
        _validate_product_flow_spec(self.spec)

        # Reuse the core Data URL validator.
        ProductVisionRequest(
            image_data_url=self.image_data_url,
            category=self.spec["category"],
        )
        return self


class ProductVisionAdvanceResponse(BaseModel):
    context: ProductContext
    spec: dict
    suggestion: Optional[SuggestResponse] = None
    meta: dict = Field(default_factory=dict)


class ProductVisionConfirmRequest(BaseModel):
    """사용자 확인([맞아요]/[수정할게요]) 결과로 spec.product를 확정한다."""

    spec: dict
    confirmed_product: str = Field(min_length=1)
    confirmation_source: ConfirmationSource

    @field_validator("confirmed_product")
    @classmethod
    def strip_confirmed_product(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("confirmed_product must not be blank.")
        return value

    @model_validator(mode="after")
    def validate_confirm(self):
        _validate_product_flow_spec(self.spec)

        context = self.spec.get("product_context")
        if not isinstance(context, dict):
            raise ValueError(
                "spec.product_context is required — "
                "call POST /vision/product first."
            )

        # pending Vision context 검증(소원님 리뷰):
        # dict 존재만으로 통과시키지 않고, /vision/product가 남긴
        # 결정적 상태(next_action/recognition_status)가 유효한지 확인한다.
        # 빈 context나 변조된 상태는 confirm 불가.
        if context.get("next_action") not in ("auto_fill", "confirm"):
            raise ValueError(
                "confirm requires a pending Vision context "
                "(next_action must be auto_fill or confirm)."
            )

        if context.get("recognition_status") == "invalid":
            raise ValueError(
                "invalid recognition cannot be confirmed — "
                "upload a new product photo."
            )

        if self.confirmation_source == "vision_confirmed":
            vision_product = str(context.get("product") or "").strip()
            if not vision_product:
                raise ValueError(
                    "vision_confirmed requires a Vision-recognized product."
                )
            if self.confirmed_product != vision_product:
                raise ValueError(
                    "vision_confirmed requires confirmed_product to equal "
                    "the Vision-recognized product; "
                    "use user_corrected instead."
                )

        return self


class ProductVisionConfirmResponse(BaseModel):
    spec: dict
    suggestion: SuggestResponse
    meta: dict = Field(default_factory=dict)


def _advance_with_context(
    spec: dict,
    context: ProductContext,
    vision_meta: Optional[dict] = None,
) -> ProductVisionAdvanceResponse:
    """Store Vision evidence and always stop for user confirmation.

    8/14 확정: 인식 결과가 명확(auto_fill)해도 자동으로 다음 단계로
    진행하지 않는다. auto_fill은 확인 UI prefill 신호일 뿐이다.
    """

    trusted_spec = apply_product_context(spec, context)

    return ProductVisionAdvanceResponse(
        context=context,
        spec=trusted_spec,
        suggestion=None,
        meta={
            **(vision_meta or {}),
            "advanced": False,
            "confirmation_required": context.next_action != "reupload",
        },
    )


def advance_product_image(
    req: ProductVisionAdvanceRequest,
) -> ProductVisionAdvanceResponse:
    category = req.spec["category"]

    vision_result: ProductVisionResponse = analyze_product_image(
        ProductVisionRequest(
            image_data_url=req.image_data_url,
            category=category,
        )
    )

    return _advance_with_context(
        req.spec,
        vision_result.context,
        vision_result.meta,
    )


_PRODUCT_STEP = 3  # 고정 흐름에서 product 슬롯 단계(1-indexed).


def _gen_next_options(spec: dict, next_cfg: dict) -> list[str]:
    """실환경에서 다음 단계 질문에 쓸 선택지 4개만 생성한다.

    product 슬롯을 재처리하지 않는다 — 어떤 슬롯 값도 바꾸지 않고
    '다음 질문의 선택지'만 만든다.
    """
    system = (
        "당신은 소상공인 광고 도우미 챗봇입니다. "
        "아래 질문에 사용자가 고를 선택지 4개를 생성하세요. "
        "지금까지 파악된 맥락(업종/제품)에 맞게 구체적으로 만드세요. "
        'JSON으로만 응답: {"options": ["...", "...", "...", "..."]}'
    )
    user = (
        f"질문: {next_cfg['question']}\n"
        f"참고: {next_cfg.get('hint', '')}\n"
        f"현재 정보: {json.dumps(spec, ensure_ascii=False)}"
    )
    data = _client_chat(
        [{"role": "system", "content": system},
         {"role": "user", "content": user}]
    )
    options = [
        str(o).strip() for o in (data.get("options") or []) if str(o).strip()
    ]
    return options[:4]


def _render_next_step(spec: dict, processed_step: int) -> SuggestResponse:
    """processed_step까지 확정된 spec으로 다음 단계 질문/선택지를 결정적으로 만든다.

    현재 슬롯(product)을 LLM으로 재처리하지 않는다. 값 확정은 호출부가 이미 끝냈고,
    여기서는 다음 단계(tone)의 질문/선택지만 생성한다.
    """
    business_type = _business_type(spec)
    flow = _effective_flow(None, business_type)
    total = len(flow)
    step = min(processed_step, total)
    _apply_aspect_ratio(spec)

    done = step >= total
    if done:
        return SuggestResponse(
            spec=spec, done=True, step=step, next_step=None,
            total_steps=total,
            question="제공해주신 정보를 바탕으로 문구를 만들어드릴게요!",
            options=[], allow_multiple=False, confirm_message="",
            meta={"deterministic_confirm": True},
        )

    next_cfg = flow[step]  # step은 1-indexed → flow[step]이 다음 단계
    if config.MOCK_MODE:
        options = list(
            _mock_slots_for(business_type)[next_cfg["slot"]]["options"]
        )
    else:
        options = _gen_next_options(spec, next_cfg)

    return SuggestResponse(
        spec=spec, done=False, step=step, next_step=step + 1,
        total_steps=total,
        question=next_cfg["question"], options=options,
        allow_multiple=next_cfg["multi"], confirm_message="",
        meta={"deterministic_confirm": True},
    )


def confirm_product(
    req: ProductVisionConfirmRequest,
) -> ProductVisionConfirmResponse:
    """사용자 확정값으로 spec.product를 결정적으로 기록하고 tone 단계로 진행한다.

    확정값은 LLM을 거치지 않는다(소원님 리뷰 반영). product는 그대로 확정하고,
    tone 단계 질문/선택지만 _render_next_step으로 별도 생성한다.
    """
    confirmed = req.confirmed_product

    provenance = dict(req.spec.get("product_context") or {})
    provenance["vision_product"] = provenance.get("product")
    provenance["confirmed_product"] = confirmed
    provenance["confirmation_source"] = req.confirmation_source

    spec = dict(req.spec)
    spec["product_context"] = provenance
    spec["product"] = confirmed

    suggestion = _render_next_step(spec, processed_step=_PRODUCT_STEP)

    return ProductVisionConfirmResponse(
        spec=suggestion.spec,
        suggestion=suggestion,
        meta={
            "confirmed_product": confirmed,
            "confirmation_source": req.confirmation_source,
            "deterministic": True,
        },
    )

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
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .chatbot import (
    PRODUCT_CATEGORIES,
    SuggestRequest,
    SuggestResponse,
    suggest_options,
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

        if context.get("next_action") == "reupload":
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


def confirm_product(
    req: ProductVisionConfirmRequest,
) -> ProductVisionConfirmResponse:
    """사용자 확정값으로 spec.product를 기록하고 tone 단계로 진행한다."""

    confirmed = req.confirmed_product

    provenance = dict(req.spec.get("product_context") or {})
    provenance["vision_product"] = provenance.get("product")
    provenance["confirmed_product"] = confirmed
    provenance["confirmation_source"] = req.confirmation_source

    base_spec = dict(req.spec)
    base_spec["product_context"] = provenance
    base_spec["product"] = confirmed

    # Reuse the already tested fixed-flow step 3 to obtain the
    # tone-step question/options.
    suggestion = suggest_options(
        SuggestRequest(
            message=confirmed,
            mode="fixed",
            step=3,
            spec=base_spec,
        )
    )

    # Trust boundary:
    # downstream LLM/mock may not mutate the user-confirmed product
    # or its provenance.
    locked_spec = dict(suggestion.spec or {})
    locked_spec["product"] = confirmed
    locked_spec["product_context"] = dict(provenance)
    suggestion = suggestion.model_copy(
        update={"spec": locked_spec},
    )

    return ProductVisionConfirmResponse(
        spec=locked_spec,
        suggestion=suggestion,
        meta={
            "confirmed_product": confirmed,
            "confirmation_source": req.confirmation_source,
        },
    )

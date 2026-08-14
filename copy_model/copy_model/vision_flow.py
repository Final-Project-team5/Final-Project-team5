"""Product Vision -> chatbot step-3 bridge.

Vision is the authority for the product slot.
The chatbot may generate downstream choices, but it cannot overwrite
a product that passed the Vision deterministic gate.
"""
from typing import Optional

from pydantic import BaseModel, Field, model_validator

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


class ProductVisionAdvanceRequest(BaseModel):
    image_data_url: str = Field(min_length=32)
    spec: dict

    @model_validator(mode="after")
    def validate_flow(self):
        business_type = self.spec.get("business_type", "product")
        if business_type != "product":
            raise ValueError(
                "product Vision flow only supports business_type=product"
            )

        category = self.spec.get("category")
        if category not in PRODUCT_CATEGORIES:
            raise ValueError(
                "spec.category must be one of food/beauty/goods"
            )

        # Reuse the core Data URL validator.
        ProductVisionRequest(
            image_data_url=self.image_data_url,
            category=category,
        )
        return self


class ProductVisionAdvanceResponse(BaseModel):
    context: ProductContext
    spec: dict
    suggestion: Optional[SuggestResponse] = None
    meta: dict = Field(default_factory=dict)


def _advance_with_context(
    spec: dict,
    context: ProductContext,
    vision_meta: Optional[dict] = None,
) -> ProductVisionAdvanceResponse:
    """Apply Vision evidence and advance only when it is safe."""

    trusted_spec = apply_product_context(spec, context)

    # ambiguous / mismatch / invalid:
    # do not invoke the downstream chatbot at all.
    if context.next_action != "auto_fill":
        return ProductVisionAdvanceResponse(
            context=context,
            spec=trusted_spec,
            suggestion=None,
            meta={
                **(vision_meta or {}),
                "advanced": False,
            },
        )

    # Reuse the already tested fixed-flow step 3.
    suggestion = suggest_options(
        SuggestRequest(
            message=context.product,
            mode="fixed",
            step=3,
            spec=trusted_spec,
        )
    )

    # Trust boundary:
    # downstream LLM/mock is not allowed to mutate the Vision-verified product.
    locked_spec = apply_product_context(suggestion.spec, context)
    suggestion = suggestion.model_copy(
        update={"spec": locked_spec},
    )

    return ProductVisionAdvanceResponse(
        context=context,
        spec=locked_spec,
        suggestion=suggestion,
        meta={
            **(vision_meta or {}),
            "advanced": True,
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

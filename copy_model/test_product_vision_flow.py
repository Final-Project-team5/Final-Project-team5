"""Product Vision -> chatbot orchestration tests."""
import os

os.environ["COPY_MOCK"] = "1"

from pydantic import ValidationError  # noqa: E402

from copy_model.vision import _finalize_context  # noqa: E402
from copy_model.vision_flow import (  # noqa: E402
    ProductVisionAdvanceRequest,
    _advance_with_context,
    advance_product_image,
)


TINY_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_auto_fill_advances_to_tone():
    res = advance_product_image(
        ProductVisionAdvanceRequest(
            image_data_url=TINY_PNG,
            spec={
                "business_type": "product",
                "category": "beauty",
                "purpose": "sns",
                "aspect_ratio": "1:1",
            },
        )
    )

    assert res.context.product == "립 틴트"
    assert res.context.next_action == "auto_fill"

    assert res.suggestion is not None
    assert res.suggestion.next_step == 4
    assert res.suggestion.spec["product"] == "립 틴트"
    assert res.spec["product"] == "립 틴트"

    # Existing mock step 3 normally patches a product value.
    # Vision authority must overwrite it back to the verified value.
    assert res.spec["product_context"]["product"] == "립 틴트"
    assert res.meta["advanced"] is True


def test_confirm_does_not_call_next_step():
    ctx = _finalize_context(
        {
            "product": "립 틴트",
            "detected_category": "beauty",
            "recognition_status": "clear",
        },
        "food",
    )

    res = _advance_with_context(
        {
            "business_type": "product",
            "category": "food",
            "purpose": "sns",
        },
        ctx,
        {"model": "synthetic"},
    )

    assert ctx.next_action == "confirm"
    assert res.suggestion is None
    assert "product" not in res.spec
    assert res.meta["advanced"] is False


def test_invalid_does_not_call_next_step():
    ctx = _finalize_context(
        {
            "product": None,
            "detected_category": "unknown",
            "recognition_status": "invalid",
        },
        "goods",
    )

    res = _advance_with_context(
        {
            "business_type": "product",
            "category": "goods",
        },
        ctx,
    )

    assert res.suggestion is None
    assert "product" not in res.spec
    assert res.context.next_action == "reupload"


def test_service_rejected():
    try:
        ProductVisionAdvanceRequest(
            image_data_url=TINY_PNG,
            spec={
                "business_type": "service",
                "category": "academy",
            },
        )
    except ValidationError:
        return

    raise AssertionError("service must not enter product Vision flow")


def test_missing_product_category_rejected():
    try:
        ProductVisionAdvanceRequest(
            image_data_url=TINY_PNG,
            spec={"business_type": "product"},
        )
    except ValidationError:
        return

    raise AssertionError("product Vision requires product category")


if __name__ == "__main__":
    import sys
    import traceback

    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]

    passed = 0

    for test in tests:
        try:
            test()
            print(f"OK  {test.__name__}")
            passed += 1
        except Exception:
            print(f"XX  {test.__name__}")
            traceback.print_exc()

    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)

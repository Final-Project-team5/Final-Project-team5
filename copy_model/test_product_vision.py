"""제품 Vision ProductContext 테스트 — mock 모드, API 비용 0."""
import os

os.environ["COPY_MOCK"] = "1"

from pydantic import ValidationError  # noqa: E402

from copy_model.vision import (  # noqa: E402
    ProductVisionRequest,
    _finalize_context,
    analyze_product_image,
)


TINY_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_request_accepts_image_data_url():
    req = ProductVisionRequest(
        image_data_url=TINY_PNG,
        category="beauty",
    )
    assert req.category == "beauty"


def test_request_rejects_plain_string():
    try:
        ProductVisionRequest(
            image_data_url="not-an-image",
            category="food",
        )
    except ValidationError:
        return
    raise AssertionError("plain string image input must be rejected")


def test_mock_clear_product_auto_fill():
    res = analyze_product_image(ProductVisionRequest(
        image_data_url=TINY_PNG,
        category="beauty",
    ))
    assert res.context.product == "립 틴트"
    assert res.context.recognition_status == "clear"
    assert res.context.category_match is True
    assert res.context.next_action == "auto_fill"


def test_category_mismatch_requires_confirmation():
    ctx = _finalize_context(
        {
            "product": "립 틴트",
            "detected_category": "beauty",
            "recognition_status": "clear",
            "visible_features": ["핑크 패키지"],
        },
        "food",
    )
    assert ctx.category_match is False
    assert ctx.next_action == "confirm"


def test_ambiguous_requires_confirmation():
    ctx = _finalize_context(
        {
            "product": None,
            "detected_category": "beauty",
            "recognition_status": "ambiguous",
            "candidates": ["립 틴트", "립밤"],
        },
        "beauty",
    )
    assert ctx.recognition_status == "ambiguous"
    assert ctx.candidates == ["립 틴트", "립밤"]
    assert ctx.next_action == "confirm"


def test_invalid_requires_reupload_and_drops_product():
    ctx = _finalize_context(
        {
            "product": "무언가",
            "detected_category": "unknown",
            "recognition_status": "invalid",
        },
        "goods",
    )
    assert ctx.product is None
    assert ctx.next_action == "reupload"


def test_clear_without_product_is_not_trusted():
    ctx = _finalize_context(
        {
            "product": None,
            "detected_category": "food",
            "recognition_status": "clear",
        },
        "food",
    )
    assert ctx.recognition_status == "invalid"
    assert ctx.next_action == "reupload"


if __name__ == "__main__":
    import sys
    import traceback

    fns = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]

    passed = 0

    for fn in fns:
        try:
            fn()
            print(f"OK  {fn.__name__}")
            passed += 1
        except Exception:
            print(f"XX  {fn.__name__}")
            traceback.print_exc()

    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)

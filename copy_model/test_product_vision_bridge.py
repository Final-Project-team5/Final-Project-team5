"""Vision -> chatbot spec bridge tests."""
import os

os.environ["COPY_MOCK"] = "1"

from copy_model.vision import (  # noqa: E402
    _finalize_context,
    apply_product_context,
)


def test_auto_fill_writes_product_and_provenance():
    ctx = _finalize_context(
        {
            "product": "립 틴트",
            "detected_category": "beauty",
            "recognition_status": "clear",
            "visible_features": ["핑크 패키지"],
        },
        "beauty",
    )

    spec = apply_product_context(
        {
            "business_type": "product",
            "category": "beauty",
        },
        ctx,
    )

    assert spec["product"] == "립 틴트"
    assert spec["product_context"]["product"] == "립 틴트"
    assert spec["product_context"]["visible_features"] == ["핑크 패키지"]
    assert spec["product_context"]["next_action"] == "auto_fill"


def test_category_mismatch_never_writes_product():
    ctx = _finalize_context(
        {
            "product": "립 틴트",
            "detected_category": "beauty",
            "recognition_status": "clear",
        },
        "food",
    )

    spec = apply_product_context(
        {
            "business_type": "product",
            "category": "food",
            "product": "stale product",
        },
        ctx,
    )

    assert "product" not in spec
    assert spec["product_context"]["next_action"] == "confirm"


def test_invalid_never_writes_product():
    ctx = _finalize_context(
        {
            "product": None,
            "detected_category": "unknown",
            "recognition_status": "invalid",
        },
        "goods",
    )

    spec = apply_product_context(
        {
            "business_type": "product",
            "category": "goods",
            "product": "stale product",
        },
        ctx,
    )

    assert "product" not in spec
    assert spec["product_context"]["next_action"] == "reupload"


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

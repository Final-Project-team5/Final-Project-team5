"""Product Vision public API contract tests — mock, cost 0."""
import os

os.environ["COPY_MOCK"] = "1"

from copy_model.api import app, post_vision_product  # noqa: E402
from copy_model.vision_flow import ProductVisionAdvanceRequest  # noqa: E402


TINY_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _request():
    return ProductVisionAdvanceRequest(
        image_data_url=TINY_PNG,
        spec={
            "business_type": "product",
            "category": "beauty",
            "purpose": "sns",
            "aspect_ratio": "1:1",
        },
    )


def test_single_public_vision_route():
    routes = [
        r for r in app.routes
        if getattr(r, "path", "").startswith("/vision/")
    ]
    assert len(routes) == 1
    assert routes[0].path == "/vision/product"
    assert "POST" in routes[0].methods


def test_vision_route_response_model():
    route = next(
        r for r in app.routes
        if getattr(r, "path", None) == "/vision/product"
    )
    assert route.response_model.__name__ == "ProductVisionAdvanceResponse"


def test_endpoint_auto_fills_and_advances():
    res = post_vision_product(_request())

    assert res.context.product
    assert res.context.next_action == "auto_fill"
    assert res.suggestion is not None
    assert res.suggestion.next_step == 4
    assert res.spec["product"] == res.context.product
    assert res.meta["advanced"] is True


def test_endpoint_preserves_product_provenance():
    res = post_vision_product(_request())
    ctx = res.spec["product_context"]

    assert ctx["product"] == res.context.product
    assert ctx["detected_category"] == "beauty"
    assert ctx["category_match"] is True


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

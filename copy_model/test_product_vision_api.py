"""Product Vision public API contract tests — mock, cost 0."""
import os

os.environ["COPY_MOCK"] = "1"

from copy_model.api import (  # noqa: E402
    app,
    post_vision_product,
    post_vision_product_confirm,
)
from copy_model.vision_flow import (  # noqa: E402
    ProductVisionAdvanceRequest,
    ProductVisionConfirmRequest,
)


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


def test_public_vision_routes():
    routes = {
        r.path: r
        for r in app.routes
        if getattr(r, "path", "").startswith("/vision/")
    }
    assert set(routes) == {"/vision/product", "/vision/product/confirm"}
    for route in routes.values():
        assert "POST" in route.methods


def test_vision_route_response_models():
    models = {
        r.path: r.response_model.__name__
        for r in app.routes
        if getattr(r, "path", "").startswith("/vision/")
    }
    assert models["/vision/product"] == "ProductVisionAdvanceResponse"
    assert models["/vision/product/confirm"] == "ProductVisionConfirmResponse"


def test_endpoint_returns_confirmation_pending():
    res = post_vision_product(_request())

    assert res.context.product
    assert res.context.next_action == "auto_fill"

    # 인식만으로는 확정/진행하지 않는다.
    assert res.suggestion is None
    assert "product" not in res.spec
    assert res.meta["advanced"] is False
    assert res.meta["confirmation_required"] is True


def test_confirm_endpoint_finalizes_and_advances():
    pending = post_vision_product(_request())

    res = post_vision_product_confirm(
        ProductVisionConfirmRequest(
            spec=pending.spec,
            confirmed_product=pending.context.product,
            confirmation_source="vision_confirmed",
        )
    )

    assert res.spec["product"] == pending.context.product
    assert res.suggestion.next_step == 4
    assert res.spec["product_context"]["confirmation_source"] == (
        "vision_confirmed"
    )


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

"""제품 Vision FastAPI 계약 테스트 — mock 모드, 외부 API 비용 0."""
import os

os.environ["COPY_MOCK"] = "1"

from copy_model.api import app, post_vision_product  # noqa: E402
from copy_model.vision import ProductVisionRequest  # noqa: E402


TINY_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_vision_route_registered():
    routes = [
        r for r in app.routes
        if getattr(r, "path", None) == "/vision/product"
    ]
    assert len(routes) == 1
    assert "POST" in routes[0].methods


def test_vision_route_response_model():
    route = next(
        r for r in app.routes
        if getattr(r, "path", None) == "/vision/product"
    )
    assert route.response_model.__name__ == "ProductVisionResponse"


def test_endpoint_returns_product_context():
    res = post_vision_product(
        ProductVisionRequest(
            image_data_url=TINY_PNG,
            category="food",
        )
    )

    assert res.context.product == "쿠키 세트"
    assert res.context.requested_category == "food"
    assert res.context.detected_category == "food"
    assert res.context.category_match is True
    assert res.context.recognition_status == "clear"
    assert res.context.next_action == "auto_fill"


def test_endpoint_meta_is_mock():
    res = post_vision_product(
        ProductVisionRequest(
            image_data_url=TINY_PNG,
            category="goods",
        )
    )

    assert res.meta["mock"] is True
    assert res.meta["model"] == "mock"


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

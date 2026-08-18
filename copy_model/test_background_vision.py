"""배경 레퍼런스 Vision → background_context 분리 테스트 — mock, cost 0."""
import os

os.environ["COPY_MOCK"] = "1"

from pydantic import ValidationError  # noqa: E402

from copy_model.api import app, post_vision_background  # noqa: E402
from copy_model.background import (  # noqa: E402
    BackgroundAdvanceRequest,
    BackgroundContext,
    advance_background_image,
    apply_background_context,
)


TINY_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_background_analysis_returns_visual_language():
    res = advance_background_image(
        BackgroundAdvanceRequest(
            image_data_url=TINY_PNG,
            spec={"business_type": "product", "category": "beauty"},
        )
    )
    ctx = res.context
    assert ctx.usable is True
    assert ctx.palette          # 색감 추출됨
    assert ctx.mood


def test_background_written_only_to_background_context():
    res = advance_background_image(
        BackgroundAdvanceRequest(
            image_data_url=TINY_PNG,
            spec={
                "business_type": "product",
                "category": "beauty",
                "product": "립 틴트",
                "product_context": {"product": "립 틴트"},
            },
        )
    )
    spec = res.meta["spec"]
    # 배경은 background_context로만. product/product_context 오염 금지.
    assert "background_context" in spec
    assert spec["product"] == "립 틴트"
    assert spec["product_context"] == {"product": "립 틴트"}
    assert "palette" in spec["background_context"]


def test_unusable_background_not_written():
    empty = BackgroundContext(usable=False)
    spec = apply_background_context({"product": "립 틴트"}, empty)
    assert "background_context" not in spec
    assert spec["product"] == "립 틴트"


def test_apply_never_touches_product():
    ctx = BackgroundContext(palette=["웜 베이지"], mood="차분한", usable=True)
    spec = apply_background_context(
        {"product": "쿠키", "product_context": {"x": 1}}, ctx
    )
    assert spec["product"] == "쿠키"
    assert spec["product_context"] == {"x": 1}
    assert spec["background_context"]["palette"] == ["웜 베이지"]


def test_invalid_image_rejected():
    try:
        BackgroundAdvanceRequest(
            image_data_url="data:text/plain;base64,aGVsbG8=",
            spec={},
        )
    except ValidationError:
        return
    raise AssertionError("non-image data URL must be rejected")


def test_endpoint_registered_and_response_model():
    route = next(
        r for r in app.routes
        if getattr(r, "path", None) == "/vision/background"
    )
    assert "POST" in route.methods
    assert route.response_model.__name__ == "BackgroundVisionResponse"


def test_endpoint_returns_updated_spec():
    res = post_vision_background(
        BackgroundAdvanceRequest(image_data_url=TINY_PNG, spec={"category": "food"})
    )
    assert res.meta["spec"]["background_context"]["palette"]
    assert res.meta["spec"]["category"] == "food"


if __name__ == "__main__":
    import sys
    import traceback

    tests = [
        v for k, v in sorted(globals().items())
        if k.startswith("test_") and callable(v)
    ]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"OK  {t.__name__}")
            passed += 1
        except Exception:
            print(f"XX  {t.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)

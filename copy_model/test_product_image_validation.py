"""Product image payload validation tests."""
import base64
import os

os.environ["COPY_MOCK"] = "1"

from pydantic import ValidationError  # noqa: E402

from copy_model.vision import ProductVisionRequest  # noqa: E402


VALID_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _reject(payload):
    try:
        ProductVisionRequest(
            image_data_url=payload,
            category="goods",
        )
    except ValidationError:
        return
    raise AssertionError("payload must be rejected")


def test_valid_png_accepted():
    req = ProductVisionRequest(
        image_data_url=VALID_PNG,
        category="goods",
    )
    assert req.category == "goods"


def test_invalid_base64_rejected():
    _reject("data:image/png;base64,!!!!not-base64!!!!")


def test_mime_spoof_rejected():
    jpeg_bytes = b"\xff\xd8\xff" + b"x" * 64
    payload = (
        "data:image/png;base64,"
        + base64.b64encode(jpeg_bytes).decode()
    )
    _reject(payload)


def test_gif_rejected():
    gif = base64.b64encode(b"GIF89a" + b"x" * 64).decode()
    _reject("data:image/gif;base64," + gif)


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

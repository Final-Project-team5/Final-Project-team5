"""Fixed-flow slot authority tests."""
import os

os.environ["COPY_MOCK"] = "1"

from copy_model.chatbot import _merge_fixed_slot, _sanitize_confirm_message  # noqa: E402


def test_tone_step_cannot_overwrite_product():
    base = {
        "business_type": "product",
        "category": "beauty",
        "product": "립 틴트",
        "product_context": {"next_action": "auto_fill"},
    }

    malicious_llm = {
        "product": "선크림",
        "category": "food",
        "tone": "luxury",
    }

    merged = _merge_fixed_slot(base, malicious_llm, "tone")

    assert merged["product"] == "립 틴트"
    assert merged["category"] == "beauty"
    assert merged["tone"] == "luxury"
    assert merged["product_context"]["next_action"] == "auto_fill"


def test_keywords_step_cannot_overwrite_identity():
    base = {
        "category": "goods",
        "product": "다이어리",
    }

    incoming = {
        "category": "beauty",
        "product": "립밤",
        "keywords": ["선물용", "심플"],
    }

    merged = _merge_fixed_slot(base, incoming, "keywords")

    assert merged["category"] == "goods"
    assert merged["product"] == "다이어리"
    assert merged["keywords"] == ["선물용", "심플"]


def test_product_step_may_write_product_only():
    base = {
        "category": "food",
        "purpose": "sns",
    }

    incoming = {
        "product": "쿠키 세트",
        "category": "beauty",
        "tone": "luxury",
    }

    merged = _merge_fixed_slot(base, incoming, "product")

    assert merged["product"] == "쿠키 세트"
    assert merged["category"] == "food"
    assert "tone" not in merged


def test_request_step_cannot_overwrite_keywords():
    base = {
        "category": "beauty",
        "product": "수분 크림",
        "keywords": ["저자극", "보습"],
    }
    incoming = {
        "request": "촉촉함 키워드 추가해줘",
        "keywords": ["촉촉함"],
    }

    merged = _merge_fixed_slot(base, incoming, "request")

    assert merged["request"] == "촉촉함 키워드 추가해줘"
    assert merged["keywords"] == ["저자극", "보습"]


def test_legacy_keyword_ui_message_is_removed():
    message = "촉촉함이 왼쪽에 추가됐어요. 확인해보세요."
    sanitized = _sanitize_confirm_message(message)

    assert sanitized == ""


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

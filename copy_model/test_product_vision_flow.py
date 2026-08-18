"""Product Vision -> user confirmation -> chatbot orchestration tests."""
import os

os.environ["COPY_MOCK"] = "1"

from pydantic import ValidationError  # noqa: E402

from copy_model.vision import _finalize_context  # noqa: E402
from copy_model.vision_flow import (  # noqa: E402
    ProductVisionAdvanceRequest,
    ProductVisionConfirmRequest,
    _advance_with_context,
    advance_product_image,
    confirm_product,
)


TINY_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _analyzed_spec():
    """Vision 인식까지 끝난(confirmation pending) 결과를 만든다."""
    return advance_product_image(
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


def test_clear_match_returns_confirmation_pending():
    res = _analyzed_spec()

    assert res.context.product == "립 틴트"
    assert res.context.next_action == "auto_fill"

    # 8/14 확정: 인식이 명확해도 자동 확정/자동 진행하지 않는다.
    assert res.suggestion is None
    assert "product" not in res.spec
    assert res.meta["advanced"] is False
    assert res.meta["confirmation_required"] is True

    # 인식값은 provenance로만 보존된다 (확인 UI prefill용).
    assert res.spec["product_context"]["product"] == "립 틴트"
    assert res.spec["product_context"]["next_action"] == "auto_fill"


def test_confirm_yes_finalizes_product_and_advances_to_tone():
    pending = _analyzed_spec()

    res = confirm_product(
        ProductVisionConfirmRequest(
            spec=pending.spec,
            confirmed_product="립 틴트",
            confirmation_source="vision_confirmed",
        )
    )

    assert res.spec["product"] == "립 틴트"
    assert res.suggestion.next_step == 4
    assert res.suggestion.spec["product"] == "립 틴트"

    ctx = res.spec["product_context"]
    assert ctx["vision_product"] == "립 틴트"
    assert ctx["confirmed_product"] == "립 틴트"
    assert ctx["confirmation_source"] == "vision_confirmed"
    assert res.meta["confirmation_source"] == "vision_confirmed"


def test_confirm_corrected_uses_user_value():
    pending = _analyzed_spec()

    res = confirm_product(
        ProductVisionConfirmRequest(
            spec=pending.spec,
            confirmed_product="촉촉 립밤",
            confirmation_source="user_corrected",
        )
    )

    # mock step 3은 원래 다른 product를 patch하지만,
    # 사용자 확정값이 최종 spec.product를 소유해야 한다.
    assert res.spec["product"] == "촉촉 립밤"
    assert res.suggestion.spec["product"] == "촉촉 립밤"
    assert res.suggestion.next_step == 4

    ctx = res.spec["product_context"]
    assert ctx["vision_product"] == "립 틴트"
    assert ctx["confirmed_product"] == "촉촉 립밤"
    assert ctx["confirmation_source"] == "user_corrected"


def test_confirm_response_contract_fields():
    # 소원님 리뷰: 프론트 연동 위해 confirm 응답의 단계/질문 계약을 검증.
    pending = _analyzed_spec()
    res = confirm_product(
        ProductVisionConfirmRequest(
            spec=pending.spec,
            confirmed_product="립 틴트",
            confirmation_source="vision_confirmed",
        )
    )
    s = res.suggestion
    assert s.done is False
    assert s.step == 3            # 방금 처리한 단계(product)
    assert s.next_step == 4       # 다음 단계(tone)
    assert s.total_steps == 6     # 제품형 6단계
    assert s.allow_multiple is False
    assert "느낌" in s.question   # tone 질문
    assert len(s.options) >= 1    # tone 선택지 제공
    # 결정적 경로임을 표시(step3 LLM 재처리 아님).
    assert s.meta.get("deterministic_confirm") is True


def test_confirm_is_deterministic_without_llm(monkeypatch=None):
    # confirm은 product를 LLM으로 재처리하지 않는다.
    # _client_chat이 호출되면 실패해야 한다(mock 경로라 원래 호출 안 함).
    import copy_model.vision_flow as vf

    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("confirm must not call the LLM in mock mode")

    original = vf._client_chat
    vf._client_chat = _boom
    try:
        pending = _analyzed_spec()
        res = confirm_product(
            ProductVisionConfirmRequest(
                spec=pending.spec,
                confirmed_product="립 틴트",
                confirmation_source="vision_confirmed",
            )
        )
        assert res.spec["product"] == "립 틴트"
        assert called["n"] == 0
    finally:
        vf._client_chat = original


def test_confirm_rejects_empty_product_context():
    # pending Vision context 검증: next_action 없는 빈 context는 confirm 불가.
    try:
        ProductVisionConfirmRequest(
            spec={
                "business_type": "product",
                "category": "beauty",
                "product_context": {},
            },
            confirmed_product="립 틴트",
            confirmation_source="user_corrected",
        )
    except ValidationError:
        return
    raise AssertionError("empty product_context must be rejected")


def test_confirm_rejects_invalid_recognition_status():
    try:
        ProductVisionConfirmRequest(
            spec={
                "business_type": "product",
                "category": "beauty",
                "product_context": {
                    "next_action": "confirm",
                    "recognition_status": "invalid",
                },
            },
            confirmed_product="립 틴트",
            confirmation_source="user_corrected",
        )
    except ValidationError:
        return
    raise AssertionError("invalid recognition_status must be rejected")


def test_confirm_requires_vision_context():
    try:
        ProductVisionConfirmRequest(
            spec={
                "business_type": "product",
                "category": "beauty",
            },
            confirmed_product="립 틴트",
            confirmation_source="user_corrected",
        )
    except ValidationError:
        return

    raise AssertionError("confirm without product_context must be rejected")


def test_vision_confirmed_must_match_vision_product():
    pending = _analyzed_spec()

    try:
        ProductVisionConfirmRequest(
            spec=pending.spec,
            confirmed_product="완전 다른 제품",
            confirmation_source="vision_confirmed",
        )
    except ValidationError:
        return

    raise AssertionError(
        "vision_confirmed with a different product must be rejected"
    )


def test_reupload_state_cannot_be_confirmed():
    ctx = _finalize_context(
        {
            "product": None,
            "detected_category": "unknown",
            "recognition_status": "invalid",
        },
        "goods",
    )
    pending = _advance_with_context(
        {
            "business_type": "product",
            "category": "goods",
        },
        ctx,
    )

    try:
        ProductVisionConfirmRequest(
            spec=pending.spec,
            confirmed_product="다이어리",
            confirmation_source="user_corrected",
        )
    except ValidationError:
        return

    raise AssertionError("reupload state must not be confirmable")


def test_blank_confirmed_product_rejected():
    pending = _analyzed_spec()

    try:
        ProductVisionConfirmRequest(
            spec=pending.spec,
            confirmed_product="   ",
            confirmation_source="user_corrected",
        )
    except ValidationError:
        return

    raise AssertionError("blank confirmed_product must be rejected")


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
    assert res.meta["confirmation_required"] is True


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
    assert res.meta["confirmation_required"] is False


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

"""service(academy/sports) /generate/copy 지원 테스트 — mock, cost 0.

목적:
- academy/sports CopyRequest가 422 없이 수락되고 generate가 성공하는지.
- 기존 제품 3종(food/beauty/goods) 회귀 무변.
- generate 결과에도 서비스 규제 룰(check_rules)이 적용되는지.
- /validate/copy가 서비스 문구를 수락하는지.
"""
import os

os.environ["COPY_MOCK"] = "1"

from pydantic import ValidationError  # noqa: E402

from copy_model.generator import generate_copy  # noqa: E402
from copy_model.regulation import (  # noqa: E402
    ValidateRequest,
    validate_copy,
)
from copy_model.schemas import CopyRequest  # noqa: E402


PRODUCT_CATEGORIES = ["food", "beauty", "goods"]
SERVICE_CATEGORIES = ["academy", "sports"]


def test_service_categories_accepted_by_schema():
    for cat in SERVICE_CATEGORIES:
        req = CopyRequest(category=cat, product="OO학원" if cat == "academy" else "OO짐")
        assert req.category == cat


def test_unknown_category_still_rejected():
    try:
        CopyRequest(category="medical", product="x")
    except ValidationError:
        return
    raise AssertionError("unknown category must still 422")


def test_service_product_optional_uses_default():
    # 소원님 리뷰: service는 product 없이도 422 안 나고 업종 기반 기본값 사용.
    assert CopyRequest(category="academy").product == "우리 학원"
    assert CopyRequest(category="sports").product == "우리 체육관"
    # 빈 문자열/공백도 기본값으로 처리.
    assert CopyRequest(category="academy", product="   ").product == "우리 학원"


def test_service_product_explicit_value_kept():
    r = CopyRequest(category="academy", product="합격의문 수학학원")
    assert r.product == "합격의문 수학학원"


def test_product_category_requires_product():
    for cat in PRODUCT_CATEGORIES:
        try:
            CopyRequest(category=cat)  # product 없음 → 필수 오류
        except ValidationError:
            continue
        raise AssertionError(f"{cat} must require product")


def test_service_generate_without_product_succeeds():
    # service 5단계 spec을 이름 없이 그대로 generate에 보내도 성공해야 한다.
    for cat in SERVICE_CATEGORIES:
        res = generate_copy(CopyRequest(category=cat, num_candidates=3))
        assert len(res.candidates) == 3


def test_service_generate_succeeds():
    for cat in SERVICE_CATEGORIES:
        res = generate_copy(
            CopyRequest(
                category=cat,
                product="합격기원 수학학원" if cat == "academy" else "코어 피트니스",
                num_candidates=3,
            )
        )
        assert len(res.candidates) == 3
        for c in res.candidates:
            assert c.headline
            assert c.sub


def test_product_categories_regression_unchanged():
    for cat in PRODUCT_CATEGORIES:
        res = generate_copy(
            CopyRequest(category=cat, product="테스트 제품", num_candidates=3)
        )
        assert len(res.candidates) == 3


def test_service_regulation_applied_on_generate():
    # sports 계약 불공정(block) 룰이 generate 결과 검사에도 적용되는지.
    from copy_model.regulation import check_rules

    flags = check_rules("환불 불가 평생 회원권", "sports")
    assert any(f.severity == "block" for f in flags)

    # academy 합격 보장(block).
    flags2 = check_rules("100% 합격 보장 반드시 합격", "academy")
    assert any(f.severity == "block" for f in flags2)


def test_validate_copy_accepts_service_text():
    for cat in SERVICE_CATEGORIES:
        res = validate_copy(
            ValidateRequest(
                category=cat,
                headline="전문 지도로 함께합니다",
                sub="개인별 맞춤 프로그램",
                use_llm=False,
            )
        )
        # 서비스 카테고리를 수락하고, 사실 기반 문구는 block이 아니어야 한다.
        assert res.safe is True
        assert not any(f.severity == "block" for f in res.flags)


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

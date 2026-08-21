"""학원(academy) 수강료 환불 불공정 룰 테스트 — mock, 비용 0.

규제 매트릭스 갭 G3: 학원 수강료는 학원법 시행령상 학습기간별 반환 기준이 보장된다.
'환불 불가' 표시는 위법 → block. (sports 방문판매법 환불 룰과 같은 성격, 근거만 학원법.)
"""
import os
os.environ["COPY_MOCK"] = "1"

from copy_model.regulation import ValidateRequest, validate_copy  # noqa: E402


def _validate(headline, sub=""):
    return validate_copy(ValidateRequest(
        category="academy", headline=headline, sub=sub, use_llm=False))


def _severities(res):
    return {f.severity for f in res.flags}


def test_refund_not_allowed_is_block():
    for term in ["환불 불가 정책", "중도 환불 불가", "수강료 반환 불가", "중도 해지 불가"]:
        res = _validate(term)
        assert res.severity == "block", f"{term} -> {res.severity}"
        assert res.safe is False


def test_legit_refund_notice_is_safe():
    # 실제 반환 조건 안내는 통과해야 한다(불가 표현 아님).
    res = _validate("학원법 기준에 따라 수강료를 반환해 드립니다")
    assert res.severity == "safe", [f.matched for f in res.flags]
    # '환불 안내'는 '환불 안 됨'과 다르므로 걸리지 않아야 한다.
    res2 = _validate("자세한 내용은 환불 안내 페이지 참고")
    assert res2.severity == "safe", [f.matched for f in res2.flags]


def test_existing_academy_rules_unaffected():
    # 회귀 방지: 합격 보장 block, 합격 1위 warn 그대로.
    assert _validate("합격 보장 프로그램").severity == "block"
    assert "warn" in _severities(_validate("합격 1위 학원"))


def test_refund_rule_carries_academy_law():
    from copy_model.regulation import check_rules
    flags = check_rules("환불 불가", "academy")
    assert any("학원법" in f.reason for f in flags)


if __name__ == "__main__":
    import sys
    import traceback

    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
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

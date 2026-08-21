"""체육관(sports) 의료법 오인 룰 테스트 — mock, 비용 0.

규제 매트릭스 갭 G2: 체육시설이 의료기관의 치료(도수/물리/재활 치료 등)를 표방하면
무면허 의료행위 오인 소지. block으로 잡는다. 치료 효과 오인(통증 완화 단정)은 warn.
"""
import os
os.environ["COPY_MOCK"] = "1"

from copy_model.regulation import ValidateRequest, validate_copy  # noqa: E402


def _validate(headline, sub=""):
    return validate_copy(ValidateRequest(
        category="sports", headline=headline, sub=sub, use_llm=False))


def _severities(res):
    return {f.severity for f in res.flags}


def test_medical_treatment_is_block():
    # 도수치료/물리치료 등 명시적 의료행위 표방 → block.
    for term in ["도수치료 전문 헬스장", "물리치료실 완비", "재활치료 프로그램",
                 "통증치료 가능", "디스크 치료 케어"]:
        res = _validate(term)
        assert res.severity == "block", f"{term} -> {res.severity}"
        assert res.safe is False


def test_pain_relief_is_warn():
    # 통증 완화 단정은 치료 오인 소지 → warn(치료가 아닌 운동임을 명확히).
    res = _validate("통증 완화 스트레칭 클래스")
    assert "warn" in _severities(res)
    assert res.severity in ("warn",)   # block은 아님


def test_non_medical_is_safe():
    # 비의료 표현은 통과.
    res = _validate("운동 능력 향상 컨디셔닝 프로그램")
    assert res.severity == "safe", [f.matched for f in res.flags]
    assert res.safe is True


def test_existing_sports_rules_unaffected():
    # 회귀 방지: 기존 sports 룰(환불 불가 block, 최상급 warn) 그대로 동작.
    r1 = _validate("환불 불가 회원권")
    assert r1.severity == "block"
    r2 = _validate("지역 1위 체육관")
    assert "warn" in _severities(r2)


def test_rule_added_to_sports_only():
    # 의료법 룰은 sports에만. food/beauty엔 '도수치료'가 걸리지 않아야 한다.
    from copy_model.regulation import check_rules
    assert any("치료" in f.matched for f in check_rules("도수치료", "sports"))
    # food는 자체 '치료'(질병) 룰이 있으므로 별개 — sports 전용 패턴이 food로
    # 새지 않는지만 확인(카테고리 분리).
    food_flags = check_rules("도수치료 전문", "food")
    assert all("의료법" not in f.reason for f in food_flags)


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

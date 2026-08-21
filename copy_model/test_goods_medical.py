"""굿즈(goods) 의약품·의료기기 오인 룰 테스트 — mock, 비용 0.

규제 매트릭스 갭(진우님 #99): goods는 block 룰이 0개라 어떤 표현도 하드 차단이
안 됐다. 일반 상품이 질병 치료·예방 등 의료 효능을 표방하면 약사법 제61조·
의료기기법 제26조 위반(게르마늄/자석 팔찌, 자세교정 방석 등에서 빈발). block으로
잡고, 혈액순환 개선·통증 완화 같은 건강 효능 오인은 warn.
"""
import os
os.environ["COPY_MOCK"] = "1"

from copy_model.regulation import ValidateRequest, validate_copy  # noqa: E402


def _validate(headline, sub=""):
    return validate_copy(ValidateRequest(
        category="goods", headline=headline, sub=sub, use_llm=False))


def _severities(res):
    return {f.severity for f in res.flags}


def test_disease_treatment_is_block():
    # 질병 치료·예방 단정 → block.
    for term in ["고혈압 치료 게르마늄 팔찌", "디스크 치료 자세교정 방석",
                 "관절염 예방 자석 밴드", "질병 치료 원적외선 매트",
                 "혈압을 낮춰주는 건강 팔찌"]:
        res = _validate(term)
        assert res.severity == "block", f"{term} -> {res.severity}"
        assert res.safe is False


def test_health_effect_is_warn():
    # 혈액순환 개선·통증 완화 등 건강 효능 오인 → warn(치료 아님).
    for term in ["혈액순환 개선 목걸이", "통증 완화 방석", "디톡스 발 패치"]:
        res = _validate(term)
        assert "warn" in _severities(res), f"{term} -> {_severities(res)}"
        assert res.severity == "warn", f"{term} -> {res.severity}"


def test_non_medical_goods_is_safe():
    # 비의료 표현은 통과.
    res = _validate("가벼운 알루미늄 소재 텀블러")
    assert res.severity == "safe", [f.matched for f in res.flags]
    assert res.safe is True


def test_existing_goods_rules_unaffected():
    # 회귀 방지: 기존 goods warn 룰(한정판, 평생 보증 등) 그대로 동작.
    r1 = _validate("한정판 굿즈")
    assert "warn" in _severities(r1)
    r2 = _validate("평생 보증 제품")
    assert "warn" in _severities(r2)


def test_medical_rule_added_to_goods_only():
    # goods 전용 의료 룰이 sports로 새지 않는지(카테고리 분리) 확인.
    from copy_model.regulation import check_rules
    goods_flags = check_rules("고혈압 치료 팔찌", "goods")
    assert any(f.severity == "block" and "약사법" in f.reason
               for f in goods_flags)
    # sports는 자체 의료법 룰이 있으나 '고혈압 치료 팔찌' 문구엔 걸리지 않음
    sports_flags = check_rules("고혈압 치료 팔찌", "sports")
    assert all("약사법" not in f.reason for f in sports_flags)


def test_goods_now_has_block_rules():
    # 갭 해소 확인: goods block 룰이 0개 -> 3개 이상.
    from copy_model.regulation_rules import rule_stats
    assert rule_stats()["goods"]["block"] >= 3, rule_stats()["goods"]


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

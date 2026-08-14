"""/validate/copy 하이브리드 연결 + 비대칭 신뢰(apply_trust) 단위 테스트.

이 PR에서 새로 생긴 것만 검증한다(기존 test_regulation_llm.py는 그대로 유지):
  - regulation_llm.apply_trust: 등급 상향 즉시 / 하향은 근거 있을 때만
  - regulation.validate_copy: 룰 1차 + 하이브리드 2차, 신규 응답 필드
    (severity / rule_severity / escalated / escalation_reason), broad 기본 정책

pytest 없이도 실행 가능:
    COPY_MOCK=1 python test_validate_hybrid.py
"""
from copy_model.regulation import validate_copy, ValidateRequest
from copy_model.regulation_llm import apply_trust, LLMVerdict


# ── 비대칭 신뢰 (apply_trust) ─────────────────────────────
def test_trust_upgrade_always_accepted():
    # 엄격해지는 방향(safe->block)은 근거 없어도 즉시 반영
    assert apply_trust("safe", LLMVerdict("block", ""), "asymmetric") == "block"


def test_trust_downgrade_needs_reason():
    # 완화(warn->safe)는 근거 없으면 룰 유지, 있으면 반영
    assert apply_trust("warn", LLMVerdict("safe", ""), "asymmetric") == "warn"
    assert apply_trust("warn", LLMVerdict("safe", "제품 아닌 시간 수식"),
                       "asymmetric") == "safe"


def test_trust_full_passthrough():
    # full 정책은 근거 없이도 LLM 판정 그대로 반영(비교용)
    assert apply_trust("warn", LLMVerdict("safe", ""), "full") == "safe"


# ── /validate/copy 하이브리드 통합 (mock) ─────────────────
def test_validate_rule_only_has_new_fields():
    # use_llm=False: 룰 단독. 신규 필드가 채워져 나오는지(하위호환 + 확장)
    r = validate_copy(ValidateRequest(
        category="beauty", headline="주름 완전 제거", sub="3일이면 끝"))
    assert r.severity == "block" and r.rule_severity == "block"
    assert r.safe is False and r.escalated is False


def test_validate_hybrid_escalates_boundary_case():
    # broad 기본 정책: food safe 문구도 에스컬레이션(mock은 룰 유지)
    r = validate_copy(ValidateRequest(
        category="food", headline="담백한 사골 국물", sub="깊은 맛",
        use_llm=True))
    assert r.escalated is True
    assert r.severity == r.rule_severity == "safe"   # mock: 룰 유지, 파손 0
    assert r.meta["policy"] == "broad"


def test_validate_lexicon_policy_skips_plain_safe():
    # lexicon 정책: 어휘 힌트 없는 plain safe는 LLM 생략(비용 절감)
    r = validate_copy(ValidateRequest(
        category="food", headline="오늘의 신선한 김밥", sub="아침에 만들어요",
        use_llm=True, policy="lexicon"))
    assert r.escalated is False
    assert r.severity == "safe"


if __name__ == "__main__":
    import sys, traceback
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn(); print(f"OK  {fn.__name__}"); passed += 1
        except Exception:
            print(f"XX  {fn.__name__}"); traceback.print_exc()
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)

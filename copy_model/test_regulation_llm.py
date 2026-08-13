"""regulation_llm(하이브리드 규제 검증 레이어) 단위 테스트.

pytest 없이도 실행 가능:
    COPY_MOCK=1 python test_regulation_llm.py
pytest가 있으면:
    pytest test_regulation_llm.py
"""
from copy_model.regulation import check_rules
from copy_model.regulation_llm import (
    escalation_decision, hybrid_check, LLMVerdict,
)


def _decide(headline, sub, category, policy="lexicon"):
    text = f"{headline} {sub}"
    flags = check_rules(text, category)
    return escalation_decision(flags, text, category, policy=policy)


# ── escalation_decision 분기 ──────────────────────────────
def test_block_no_escalation():
    # 명백 block(단정 효능)은 룰 신뢰, LLM 생략
    d = _decide("주름 완전 제거", "3일이면 끝", "beauty")
    assert d.escalate is False
    assert d.direction is None


def test_warn_context_superlative_downgrade():
    # 문맥 최상급 warn은 오탐 의심 → 다운그레이드 검토로 에스컬레이션
    d = _decide("최고의 하루를 담은 다이어리", "매일 기록해요", "goods")
    assert d.escalate is True
    assert d.direction == "maybe_downgrade"


def test_safe_lexicon_upgrade():
    # safe + 효능 의미회피 어휘(면역) → 미탐 의심 업그레이드
    d = _decide("면역 쑥쑥 올려주는 홍삼", "기운이 솟아요", "food")
    assert d.escalate is True
    assert d.direction == "maybe_upgrade"


def test_safe_plain_no_escalation():
    # 명백 정상(힌트 없음)은 에스컬레이션 안 함
    d = _decide("오늘의 신선한 김밥", "아침에 만들어요", "food")
    assert d.escalate is False


def test_broad_policy_escalates_foodbeauty_safe():
    # broad 정책: 어휘에 안 걸려도 food/beauty safe면 에스컬레이션
    lex = _decide("담백한 사골 국물", "깊은 맛", "food", policy="lexicon")
    broad = _decide("담백한 사골 국물", "깊은 맛", "food", policy="broad")
    assert lex.escalate is False       # 어휘 힌트 없음
    assert broad.escalate is True      # 구조적 재확인


def test_broad_policy_skips_goods_safe():
    # broad는 food/beauty만 대상. goods safe는 에스컬레이션 안 함
    d = _decide("튼튼한 에코백", "매일 들기 좋아요", "goods", policy="broad")
    assert d.escalate is False


# ── hybrid_check judge 라우팅/교정 ────────────────────────
def test_hybrid_no_judge_keeps_rule():
    # judge 없으면 룰 등급 그대로, source=rule
    r = hybrid_check("면역 쑥쑥 올려주는 홍삼", "기운이 솟아요", "food", judge=None)
    assert r.severity == r.rule_severity
    assert r.source == "rule"


def test_hybrid_judge_called_only_on_escalation():
    calls = []

    def judge(h, s, cat, rule_sev, direction):
        calls.append(h)
        return LLMVerdict("block", "test")

    # 에스컬레이션 케이스(미탐 의심) → judge 호출, 교정 반영
    r1 = hybrid_check("면역 쑥쑥 올려주는 홍삼", "기운이 솟아요", "food", judge=judge)
    assert r1.source == "llm"
    assert r1.severity == "block"
    # 명백 safe → 에스컬레이션 없음 → judge 미호출
    r2 = hybrid_check("오늘의 신선한 김밥", "아침에 만들어요", "food", judge=judge)
    assert r2.source == "rule"
    assert len(calls) == 1              # 딱 한 번만 호출


def test_hybrid_downgrade_correction():
    # 오탐(warn) → judge safe → 최종 safe
    r = hybrid_check("최고의 하루를 담은 다이어리", "매일 기록해요", "goods",
                     judge=lambda *a: LLMVerdict("safe", "t"))
    assert r.rule_severity == "warn"
    assert r.severity == "safe"


def test_judge_invalid_severity_falls_back_to_rule():
    # judge가 이상한 값 반환 시 룰 등급으로 폴백(안전)
    from copy_model.regulation_llm import build_llm_judge
    judge = build_llm_judge(lambda msgs: {"severity": "???", "reason": "x"})
    r = hybrid_check("면역 쑥쑥 올려주는 홍삼", "기운이 솟아요", "food", judge=judge)
    assert r.severity == r.rule_severity   # safe로 폴백


# ── apply_trust (비대칭 신뢰 정책) ────────────────────────
def test_trust_upgrade_always_accepted():
    from copy_model.regulation_llm import apply_trust
    # 엄격해지는 방향(safe->block)은 근거 없어도 즉시 반영
    assert apply_trust("safe", LLMVerdict("block", ""), "asymmetric") == "block"


def test_trust_downgrade_needs_reason():
    from copy_model.regulation_llm import apply_trust
    # 완화(warn->safe)는 근거 없으면 룰 유지, 있으면 반영
    assert apply_trust("warn", LLMVerdict("safe", ""), "asymmetric") == "warn"
    assert apply_trust("warn", LLMVerdict("safe", "제품 아닌 시간 수식"),
                       "asymmetric") == "safe"


def test_trust_full_passthrough():
    from copy_model.regulation_llm import apply_trust
    assert apply_trust("warn", LLMVerdict("safe", ""), "full") == "safe"


# ── /validate/copy 하이브리드 통합 (mock) ─────────────────
def test_validate_rule_only_has_new_fields():
    from copy_model.regulation import validate_copy, ValidateRequest
    r = validate_copy(ValidateRequest(
        category="beauty", headline="주름 완전 제거", sub="3일이면 끝"))
    assert r.severity == "block" and r.rule_severity == "block"
    assert r.safe is False and r.escalated is False


def test_validate_hybrid_escalates_boundary_case():
    from copy_model.regulation import validate_copy, ValidateRequest
    # broad 기본 정책: food safe 문구는 에스컬레이션됨 (mock은 룰 유지)
    r = validate_copy(ValidateRequest(
        category="food", headline="담백한 사골 국물", sub="깊은 맛",
        use_llm=True))
    assert r.escalated is True
    assert r.severity == r.rule_severity == "safe"   # mock: 룰 유지
    assert r.meta["policy"] == "broad"


def test_validate_lexicon_policy_skips_plain_safe():
    from copy_model.regulation import validate_copy, ValidateRequest
    # lexicon 정책: 어휘 힌트 없는 safe는 LLM 생략
    r = validate_copy(ValidateRequest(
        category="food", headline="오늘의 신선한 김밥", sub="아침에 만들어요",
        use_llm=True, policy="lexicon"))
    assert r.escalated is False
    assert r.severity == "safe"


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        t()
        print(f"  PASS  {t.__name__}")
        passed += 1
    print(f"\n{passed}/{len(tests)} 통과")


if __name__ == "__main__":
    _run_all()

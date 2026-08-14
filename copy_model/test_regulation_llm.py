"""regulation_llm(하이브리드 규제 검증 레이어) 단위 테스트.

pytest 없이도 실행 가능:
    COPY_MOCK=1 python test_regulation_llm.py
pytest가 있으면:
    pytest test_regulation_llm.py

정책 표기(진우님 리뷰 반영):
    hybrid_check/escalation_decision의 기본 policy는 "lexicon"이지만,
    운영 진입점(/validate/copy)의 기본은 "broad"(팀 확정)다. 아래 테스트는
    lexicon 경로는 policy="lexicon"을 명시하고, broad 경로는 별도 케이스로 검증한다.
"""
from copy_model.regulation import check_rules
from copy_model.regulation_llm import (
    escalation_decision, hybrid_check, LLMVerdict,
)


def _decide(headline, sub, category, policy="lexicon"):
    text = f"{headline} {sub}"
    flags = check_rules(text, category)
    return escalation_decision(flags, text, category, policy=policy)


# ── escalation_decision 분기 (lexicon) ────────────────────
def test_block_no_escalation():
    # 명백 block(단정 효능)은 룰 신뢰, LLM 생략 (정책 무관)
    d = _decide("주름 완전 제거", "3일이면 끝", "beauty", policy="lexicon")
    assert d.escalate is False
    assert d.direction is None


def test_warn_context_superlative_downgrade():
    # 문맥 최상급 warn은 오탐 의심 → 다운그레이드 (정책 무관)
    d = _decide("최고의 하루를 담은 다이어리", "매일 기록해요", "goods", policy="lexicon")
    assert d.escalate is True
    assert d.direction == "maybe_downgrade"


def test_safe_lexicon_upgrade():
    # lexicon: safe + 효능 의미회피 어휘(면역) → 미탐 의심 업그레이드
    d = _decide("면역 쑥쑥 올려주는 홍삼", "기운이 솟아요", "food", policy="lexicon")
    assert d.escalate is True
    assert d.direction == "maybe_upgrade"


def test_safe_plain_no_escalation():
    # lexicon: 어휘 힌트 없는 safe는 에스컬레이션 안 함
    d = _decide("오늘의 신선한 김밥", "아침에 만들어요", "food", policy="lexicon")
    assert d.escalate is False


# ── escalation_decision 분기 (broad, 팀 확정 메인 정책) ────
def test_broad_policy_escalates_foodbeauty_safe():
    # broad: 어휘에 안 걸려도 food/beauty safe면 에스컬레이션
    lex = _decide("담백한 사골 국물", "깊은 맛", "food", policy="lexicon")
    broad = _decide("담백한 사골 국물", "깊은 맛", "food", policy="broad")
    assert lex.escalate is False
    assert broad.escalate is True


def test_broad_policy_escalates_plain_safe():
    # broad: lexicon이면 통과됐을 명백 safe도 재확인 대상
    lex = _decide("오늘의 신선한 김밥", "아침에 만들어요", "food", policy="lexicon")
    broad = _decide("오늘의 신선한 김밥", "아침에 만들어요", "food", policy="broad")
    assert lex.escalate is False
    assert broad.escalate is True


def test_broad_policy_skips_goods_safe():
    # broad는 food/beauty만 대상. goods safe는 에스컬레이션 안 함(설계 의도)
    d = _decide("튼튼한 에코백", "매일 들기 좋아요", "goods", policy="broad")
    assert d.escalate is False


# ── hybrid_check judge 라우팅/교정 ────────────────────────
def test_hybrid_no_judge_keeps_rule():
    r = hybrid_check("면역 쑥쑥 올려주는 홍삼", "기운이 솟아요", "food",
                     judge=None, policy="lexicon")
    assert r.severity == r.rule_severity
    assert r.source == "rule"


def test_hybrid_judge_called_only_on_escalation_lexicon():
    # lexicon 기준: 면역(에스컬)만 judge 호출, 김밥(비에스컬)은 미호출 → 1회
    calls = []

    def judge(h, s, cat, rule_sev, direction):
        calls.append(h)
        return LLMVerdict("block", "test")

    r1 = hybrid_check("면역 쑥쑥 올려주는 홍삼", "기운이 솟아요", "food",
                      judge=judge, policy="lexicon")
    assert r1.source == "llm"
    assert r1.severity == "block"
    r2 = hybrid_check("오늘의 신선한 김밥", "아침에 만들어요", "food",
                      judge=judge, policy="lexicon")
    assert r2.source == "rule"
    assert len(calls) == 1


def test_hybrid_judge_called_broad_escalates_both():
    # broad 기준: food safe 둘 다 에스컬레이션 → judge 2회 (진우님 요청 케이스)
    calls = []

    def judge(h, s, cat, rule_sev, direction):
        calls.append(h)
        return LLMVerdict(rule_sev, "keep")   # 등급 유지(호출 수만 확인)

    hybrid_check("면역 쑥쑥 올려주는 홍삼", "기운이 솟아요", "food",
                 judge=judge, policy="broad")
    hybrid_check("오늘의 신선한 김밥", "아침에 만들어요", "food",
                 judge=judge, policy="broad")
    assert len(calls) == 2


def test_hybrid_downgrade_correction():
    # 오탐(warn) → judge safe → 최종 safe
    r = hybrid_check("최고의 하루를 담은 다이어리", "매일 기록해요", "goods",
                     judge=lambda *a: LLMVerdict("safe", "t"), policy="lexicon")
    assert r.rule_severity == "warn"
    assert r.severity == "safe"


def test_judge_invalid_severity_falls_back_to_rule():
    from copy_model.regulation_llm import build_llm_judge
    judge = build_llm_judge(lambda msgs: {"severity": "???", "reason": "x"})
    r = hybrid_check("면역 쑥쑥 올려주는 홍삼", "기운이 솟아요", "food",
                     judge=judge, policy="lexicon")
    assert r.severity == r.rule_severity


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

"""/validate/copy 하이브리드 연결 + 단조 신뢰(apply_trust monotonic) 테스트.

이 PR에서 검증하는 것(기존 test_regulation_llm.py 12건은 그대로 유지):
  - regulation_llm.apply_trust: 최종 등급은 룰 등급보다 낮아지지 않음(monotonic).
    LLM은 상향/동일만 반영, 하향은 무시. block은 완화 불가.
  - regulation.validate_copy: 룰 1차 + 하이브리드 2차, 신규 응답 필드
    (severity / rule_severity / escalated / escalation_reason), broad 기본 정책.
  - 실제 LLM 경로 통합 테스트: _client_chat을 patch해 verdict를 주입하고
    apply_trust -> 최종 severity/응답 필드까지 배선을 직접 검증(진우/소원 리뷰 반영).

실행:
    COPY_MOCK=1 python test_validate_hybrid.py
    (통합 테스트는 내부에서 config.MOCK_MODE를 잠시 False로 바꿔 실제 경로를 태움)
"""
from copy_model.regulation import validate_copy, ValidateRequest
from copy_model.regulation_llm import apply_trust, LLMVerdict
from copy_model import config as _config
from copy_model import chatbot as _chatbot


# ── 단조 신뢰 (apply_trust monotonic) ─────────────────────
def test_trust_upgrade_accepted():
    # 상향(safe->block, warn->block)은 즉시 반영
    assert apply_trust("safe", LLMVerdict("block", "")) == "block"
    assert apply_trust("safe", LLMVerdict("warn", "")) == "warn"
    assert apply_trust("warn", LLMVerdict("block", "")) == "block"


def test_trust_downgrade_blocked_even_with_reason():
    # 하향(warn->safe, block->*)은 근거가 있어도 무시하고 룰 유지
    assert apply_trust("warn", LLMVerdict("safe", "제품 아닌 시간 수식")) == "warn"
    assert apply_trust("block", LLMVerdict("safe", "오탐 같음")) == "block"
    assert apply_trust("block", LLMVerdict("warn", "완화 근거")) == "block"


def test_trust_same_severity_passthrough():
    assert apply_trust("warn", LLMVerdict("warn", "")) == "warn"
    assert apply_trust("safe", LLMVerdict("safe", "")) == "safe"


def test_trust_full_mode_still_passthrough():
    # full은 실험/오라클 비교용 — LLM 판정 그대로(운영 미사용)
    assert apply_trust("warn", LLMVerdict("safe", ""), "full") == "safe"


def test_trust_invalid_verdict_falls_back_to_rule():
    assert apply_trust("warn", LLMVerdict("garbage", "")) == "warn"


# ── validate_copy 응답 필드 (mock) ────────────────────────
def test_validate_rule_only_has_new_fields():
    r = validate_copy(ValidateRequest(
        category="beauty", headline="주름 완전 제거", sub="3일이면 끝"))
    assert r.severity == "block" and r.rule_severity == "block"
    assert r.safe is False and r.escalated is False


def test_validate_hybrid_escalates_boundary_case():
    r = validate_copy(ValidateRequest(
        category="food", headline="담백한 사골 국물", sub="깊은 맛",
        use_llm=True))
    assert r.escalated is True
    assert r.severity == r.rule_severity == "safe"   # mock: 룰 유지, 파손 0
    assert r.meta["policy"] == "broad"
    assert r.meta["trust"] == "monotonic"


def test_validate_lexicon_policy_skips_plain_safe():
    r = validate_copy(ValidateRequest(
        category="food", headline="오늘의 신선한 김밥", sub="아침에 만들어요",
        use_llm=True, policy="lexicon"))
    assert r.escalated is False
    assert r.severity == "safe"


# ── 실제 LLM 경로 통합 테스트 (_client_chat patch) ─────────
def _run_live(req, fake_verdict, *, expect_llm_called=True):
    """config.MOCK_MODE=False로 실제 경로를 태우되 _client_chat을 patch해
    LLM 없이 verdict를 주입한다. (headline, sub) 검증 후 원상복구."""
    calls = {"n": 0}

    def fake_client_chat(messages, temperature=0):
        calls["n"] += 1
        return fake_verdict

    orig_mock = _config.MOCK_MODE
    orig_chat = _chatbot._client_chat
    _config.MOCK_MODE = False
    _chatbot._client_chat = fake_client_chat
    try:
        resp = validate_copy(req)
    finally:
        _config.MOCK_MODE = orig_mock
        _chatbot._client_chat = orig_chat
    assert calls["n"] == (1 if expect_llm_called else 0), \
        f"LLM 호출수 {calls['n']} != 기대 {expect_llm_called}"
    return resp


def test_live_warn_llm_safe_stays_warn():
    # 룰 warn + 에스컬레이션(문맥 최상급) + LLM이 safe 판정 -> monotonic으로 warn 유지
    r = _run_live(
        ValidateRequest(category="goods", headline="최고의 하루", sub="",
                        use_llm=True),
        {"severity": "safe", "reason": "제품이 아니라 하루를 수식"})
    assert r.rule_severity == "warn"
    assert r.severity == "warn"       # 하향 차단
    assert r.escalated is True
    assert r.safe is True             # warn은 block 아님 -> safe=True
    assert "최고" in (r.escalation_reason or "")


def test_live_safe_llm_block_becomes_block():
    # 룰 safe + broad 에스컬레이션 + LLM이 block 판정 -> 상향 반영
    r = _run_live(
        ValidateRequest(category="food", headline="담백한 사골 국물", sub="",
                        use_llm=True),
        {"severity": "block", "reason": "효능을 의미로 우회"})
    assert r.rule_severity == "safe"
    assert r.severity == "block"      # 상향 반영
    assert r.escalated is True
    assert r.safe is False


def test_live_block_does_not_call_llm():
    # 룰 block은 에스컬레이션 안 함 -> LLM 미호출, block 유지
    r = _run_live(
        ValidateRequest(category="beauty", headline="주름 완전 제거", sub="",
                        use_llm=True),
        {"severity": "safe", "reason": "호출되면 안 됨"},
        expect_llm_called=False)
    assert r.rule_severity == "block"
    assert r.severity == "block"
    assert r.escalated is False
    assert r.safe is False


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

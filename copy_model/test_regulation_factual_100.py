"""사실-100% 오탐 방어 테스트 — mock, 비용 0 (규제 매트릭스 G5 연장).

"100% 순면", "100% 국내산"처럼 검증 가능한 성분·원산지 100%는 표시광고법상 실증
가능한 사실이라 오탐으로 보고 통과. "100% 효과/만족/보장" 등 입증 불가 100%는 유지.
핵심: 오탐 방어가 실제 위반(효능·과장·천연 등)을 가려선 안 된다(R3 정합성).
"""
import os
os.environ["COPY_MOCK"] = "1"

from copy_model.regulation_whitelist import is_factual_100  # noqa: E402
from copy_model.regulation import (  # noqa: E402
    check_rules, ValidateRequest, validate_copy)


def _sev_set(text, cat):
    return {(f.matched, f.severity) for f in check_rules(text, cat)}


def _has_100_flag(text, cat):
    return any(f.matched in ("100%", "백퍼센트") for f in check_rules(text, cat))


# ── is_factual_100 단위 ────────────────────────────────────
def test_factual_100_true_for_material_origin():
    for t in ["100% 순면 티셔츠", "100% 국내산 원료", "백퍼센트 순면",
              "100% 스테인리스 텀블러", "100% 국산 가죽", "100% 면 티셔츠",
              "100% 마 소재 가방"]:
        assert is_factual_100(t) is True, t


def test_factual_100_false_for_hype():
    # 효능·과장 100%는 사실이 아니다.
    for t in ["100% 효과", "100% 만족 보장", "100% 안전", "100% 합격",
              "100% 완벽", "100%"]:
        assert is_factual_100(t) is False, t


def test_factual_100_no_substring_false_positive():
    # 한 글자 소재 토큰(면/울/마)이 면세/마스크/울트라처럼 다른 단어에
    # substring으로 걸리면 안 된다(소원님 #100 오탐 교훈과 동일 계열).
    for t in ["100% 면세 혜택", "100% 마스크팩", "100% 울트라 세일",
              "100% 면접 대비"]:
        assert is_factual_100(t) is False, t


def test_factual_100_false_when_hype_mixed():
    # 사실 명사가 있어도 같은 문장에 과장/효능 100%가 섞이면 미인정(안전 방향).
    assert is_factual_100("100% 순면 100% 만족") is False
    assert is_factual_100("100% 국내산으로 100% 효과 보장") is False


def test_factual_100_false_for_certification_axis():
    # 천연/자연은 인증 필요 축이라 사실-100%로 통과시키지 않는다.
    assert is_factual_100("100% 천연 주스") is False
    assert is_factual_100("100% 자연 유래") is False


# ── check_rules 통합 (오탐 통과) ───────────────────────────
def test_factual_100_passes_common_rule():
    # "100% 순면"은 COMMON 100% warn을 오탐으로 보고 통과 → 100% 플래그 없음.
    assert _has_100_flag("100% 순면 에코백", "goods") is False
    assert _has_100_flag("100% 국내산 원두", "food") is False


def test_hype_100_still_flagged():
    # "100% 효과 보장"은 그대로 걸린다(통과 금지).
    assert _has_100_flag("100% 효과 보장", "goods") is True


def test_substring_false_positive_still_flagged_in_rules():
    # "100% 면세 혜택"은 오탐 통과 대상이 아니므로 100% warn이 그대로 남아야 한다.
    assert _has_100_flag("100% 면세 혜택", "goods") is True


# ── R3 정합성: 오탐 방어가 위반을 가리지 않는다 ────────────
def test_certification_warn_survives():
    # "100% 천연 주스": 100%는 통과 대상 아니고, 천연 warn은 살아있어야 한다.
    sev = _sev_set("100% 천연 주스", "food")
    assert any(m == "천연" and s == "warn" for m, s in sev), sev


def test_no_leak_for_hype_with_guard_word():
    # "미백 100% 보장"은 화이트리스트로 새면 안 된다(100%·보장 유지).
    assert _has_100_flag("미백 100% 보장", "beauty") is True


def test_cosmetic_whitelist_unaffected():
    # 기존 기능성 완곡 형식 화이트리스트는 그대로 동작(회귀 방지).
    assert check_rules("주름 개선에 도움을 주는 크림", "beauty") == []


# ── validate_copy 종단 ─────────────────────────────────────
def test_validate_factual_100_is_safe():
    r = validate_copy(ValidateRequest(
        category="goods", headline="100% 순면 데일리 티셔츠", sub="", use_llm=False))
    assert r.severity == "safe", [f.matched for f in r.flags]


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

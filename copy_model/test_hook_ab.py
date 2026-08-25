"""매력 A/B 하니스 플러밍 스모크 — mock, cost 0.

실효 비교(매력 승률)는 API 키가 필요하므로 여기선 구조/무크래시만 검증한다.
"""
import os

os.environ["COPY_MOCK"] = "1"

from eval.run_hook_ab import HOOK_VARIANTS, SCENARIOS, run  # noqa: E402


def test_variants_present():
    assert "baseline" in HOOK_VARIANTS
    assert set(HOOK_VARIANTS) >= {"baseline", "hook", "persona", "cta"}
    assert HOOK_VARIANTS["baseline"] == ""


def test_run_mock_structure():
    res = run(n=3, num=2, collect_detail=False)
    assert res["n_scenarios"] == 3
    # 변형마다 규제 요약이 계산된다.
    for v in HOOK_VARIANTS:
        assert v in res["regulation"]
        assert "violation_rate" in res["regulation"][v]
    # mock은 판정 스킵 → 승률 비어 있고 verdict의 adopt는 False.
    assert res["win_rate_vs_baseline"] == {}
    for v in ("hook", "persona", "cta"):
        assert res["verdict"][v]["adopt_candidate"] is False


def test_scenarios_cover_product_and_service():
    cats = {s[0] for s in SCENARIOS}
    assert {"food", "beauty", "goods"} <= cats     # 제품형 3종
    assert {"academy", "sports"} <= cats           # 서비스형 2종


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

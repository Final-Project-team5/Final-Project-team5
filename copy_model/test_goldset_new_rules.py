"""신규 규제 룰 골드셋 편입 확인 (진우님 #102 요청) — mock, 비용 0.

#99(sports 의료법, academy 환불), #102(goods 의약품/의료기기 오인),
#110(사실-100% 오탐)로 추가된 룰의 대표 케이스를 gold_cases.json에 편입하고,
현재 룰이 그 정답 라벨을 그대로 맞히는지 pytest로 못박는다(회귀 잠금).

전체 골드셋 지표는 `python -m eval.run_goldset`로 확인.
"""
import os
os.environ["COPY_MOCK"] = "1"

import json  # noqa: E402

from eval.run_goldset import predict, _GOLD  # noqa: E402

# 이번 편입 대상 신규 룰 케이스 id
_NEW_IDS = {
    "SP-B3", "SP-W6", "SP-S6",   # sports 의료법 오인 (#99)
    "G-B1", "G-W7", "G-S6",      # goods 의약품/의료기기 오인 (#102)
    "AC-B4",                     # academy 수강료 환불 (#99)
    "G-S7", "G-S8",              # 사실-100% 오탐 (#110)
}


def _load_cases():
    with open(_GOLD, encoding="utf-8") as f:
        return json.load(f)["cases"]


def test_new_rule_cases_present():
    ids = {c["id"] for c in _load_cases()}
    missing = _NEW_IDS - ids
    assert not missing, f"골드셋에 신규 케이스 누락: {missing}"


def test_new_rule_cases_predict_correctly():
    # 신규 룰 케이스는 현재 룰이 정답 라벨을 그대로 맞혀야 한다.
    by_id = {c["id"]: c for c in _load_cases()}
    for cid in sorted(_NEW_IDS):
        c = by_id[cid]
        pred = predict(c["headline"], c["sub"], c["category"])
        assert pred == c["expected"], (
            f"{cid}: expected {c['expected']}, got {pred} "
            f"({c['headline']} / {c['sub']})")


def test_factual_100_goldset_is_safe():
    # 사실-100% 케이스는 safe여야 한다(오탐 방어 회귀 잠금).
    by_id = {c["id"]: c for c in _load_cases()}
    for cid in ("G-S7", "G-S8"):
        c = by_id[cid]
        assert c["expected"] == "safe"
        assert predict(c["headline"], c["sub"], c["category"]) == "safe", cid


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

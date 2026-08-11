"""LLM 에스컬레이션 '라우팅' 오프라인 평가 (P2 레이어).

무엇을 재나:
    hybrid_check의 라우팅 정책이 어떤 케이스를 LLM 2차로 넘기는지를 골드셋
    전체에 대해 측정한다. LLM 판정 '효과'가 아니라 '라우팅'만 잰다(judge=None).

왜 라우팅만 재나:
    LLM 판정 효과는 API 키가 있어야 측정된다. 하지만 라우팅이 맞는지는
    비용 없이 검증 가능하고, 하이브리드 레이어의 '필요조건'이다:
      - 룰이 틀린 케이스(오탐/미탐)가 에스컬레이션에 잡혀야 교정 기회가 생김.
      - 명백 정상 케이스까지 다 넘기면 비용이 폭발함(에스컬레이션율이 낮아야 함).

사용:
    python -m eval.run_escalation
"""
import json
import os

from copy_model.regulation_llm import hybrid_check, escalation_decision
from copy_model.regulation import check_rules

_HERE = os.path.dirname(__file__)
_GOLD = os.path.join(_HERE, "gold_cases.json")


def main():
    with open(_GOLD, encoding="utf-8") as f:
        gold = json.load(f)
    cases = gold["cases"]

    n = len(cases)
    escalated = []
    rule_errors_routed = 0   # 룰이 틀린 케이스 중 에스컬레이션에 잡힌 수
    rule_error_total = 0
    by_direction = {"maybe_downgrade": 0, "maybe_upgrade": 0}

    for c in cases:
        text = f'{c["headline"]} {c["sub"]}'
        flags = check_rules(text, c["category"])
        res = hybrid_check(c["headline"], c["sub"], c["category"], judge=None)
        rule_sev = res.rule_severity
        exp = c["expected"]
        rule_wrong = (rule_sev != exp)

        d = res.escalation
        if d.escalate:
            escalated.append((c["id"], text, rule_sev, exp, d.direction, d.reason))
            if d.direction in by_direction:
                by_direction[d.direction] += 1

        if rule_wrong:
            rule_error_total += 1
            if d.escalate:
                rule_errors_routed += 1

    print("=" * 64)
    print("LLM 에스컬레이션 라우팅 평가 (효과 아님 — 라우팅만)")
    print("-" * 64)
    print(f"전체 케이스: {n}")
    print(f"에스컬레이션(LLM 2차로 보냄): {len(escalated)}건 "
          f"({len(escalated)/n:.1%})  ← 낮을수록 비용 효율적")
    print(f"  다운그레이드 검토(warn 오탐 의심): {by_direction['maybe_downgrade']}건")
    print(f"  업그레이드 검토(safe 미탐 의심):  {by_direction['maybe_upgrade']}건")
    print("-" * 64)
    cov = (rule_errors_routed / rule_error_total) if rule_error_total else 0.0
    print(f"룰 오류 케이스: {rule_error_total}건 중 "
          f"{rule_errors_routed}건이 에스컬레이션에 포착 (커버리지 {cov:.1%})")
    print("  → 룰이 틀린 케이스가 LLM 교정 기회를 얻는지 = 하이브리드 필요조건")
    print("-" * 64)
    print("에스컬레이션된 케이스:")
    for cid, text, rs, exp, direction, reason in escalated:
        mark = "오류" if rs != exp else "정상"
        print(f"  [{cid}] ({mark}: 룰 {rs}/정답 {exp}) {direction}")
        print(f"        {text}")
        print(f"        사유: {reason}")
    print("=" * 64)


if __name__ == "__main__":
    main()

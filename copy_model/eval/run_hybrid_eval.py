"""하이브리드(룰+LLM) 효과 측정 하니스 (P2 다음 단계).

무엇을 재나:
    룰 단독 대비, 하이브리드(경계 케이스만 LLM 2차)가 라벨 정확일치를
    얼마나 올리는지(fix) / 떨어뜨리는지(break, 2차 오탐)를 split별로 잰다.

judge 모드:
    - "oracle": 에스컬레이션된 케이스에 대해 '정답'을 돌려주는 가짜 판정기.
      = LLM이 완벽하다고 가정한 상한(upper bound). 실제 LLM 효과가 아니라,
        '현재 라우팅이 도달 가능한 천장'을 보여준다. break는 0(정의상).
    - "null": 룰 등급을 그대로 반환 = 룰 단독과 동일(하한/무동작 확인용).
    - 실제 LLM judge는 build_llm_judge로 주입(API 키 필요, 여기선 미측정).

정직한 한계:
    oracle는 '판정이 맞다면'의 상한이다. 실제 LLM은 틀릴 수 있어(2차 오탐)
    이 값보다 낮게 나온다. 실측은 API 키로 별도 수행해야 한다.

사용:
    python -m eval.run_hybrid_eval            # oracle 상한
    python -m eval.run_hybrid_eval --mode null
"""
import argparse
import json
import os

from copy_model.regulation_llm import hybrid_check, LLMVerdict

_HERE = os.path.dirname(__file__)
_GOLD = os.path.join(_HERE, "gold_cases.json")


def _make_judge(mode: str, gold: str):
    """케이스별 judge. oracle=정답 반환, null=룰 등급 유지."""
    def judge(headline, sub, category, rule_severity, direction):
        if mode == "oracle":
            return LLMVerdict(gold, "oracle")
        return LLMVerdict(rule_severity, "null")
    return judge


def _acc(rows):
    n = len(rows)
    return (sum(1 for r in rows if r["ok"]) / n) if n else 0.0


def eval_split(cases: list, mode: str, policy: str = "lexicon") -> dict:
    rows = []
    fixed, broke, missed_by_routing = [], [], []
    escalated = 0
    rule_correct = 0
    for c in cases:
        judge = _make_judge(mode, c["expected"])
        res = hybrid_check(c["headline"], c["sub"], c["category"],
                           judge=judge, policy=policy)
        rule_ok = (res.rule_severity == c["expected"])
        hyb_ok = (res.severity == c["expected"])
        rows.append({"ok": hyb_ok})
        rule_correct += 1 if rule_ok else 0
        if res.escalation.escalate:
            escalated += 1
        if not rule_ok and hyb_ok:
            fixed.append(c["id"])                     # 룰 틀림 → 하이브리드 맞춤
        if rule_ok and not hyb_ok:
            broke.append(c["id"])                     # 룰 맞음 → 하이브리드 틀림(2차 오탐)
        if not rule_ok and not res.escalation.escalate:
            missed_by_routing.append(c["id"])         # 라우팅이 못 잡아 교정 기회 없음
    n = len(cases)
    return {
        "n": n,
        "rule_acc": (rule_correct / n) if n else 0.0,
        "hybrid_acc": _acc(rows),
        "escalation_rate": (escalated / n) if n else 0.0,
        "fixed": fixed,
        "broke": broke,
        "missed_by_routing": missed_by_routing,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", default="oracle", choices=["oracle", "null"])
    p.add_argument("--policy", default="all", choices=["lexicon", "broad", "all"],
                   help="safe 미탐 라우팅 정책. all=두 정책 비교")
    args = p.parse_args()

    with open(_GOLD, encoding="utf-8") as f:
        gold = json.load(f)
    cases = gold["cases"]
    splits = {
        "TRAIN": [c for c in cases if c.get("split", "train") == "train"],
        "HOLDOUT": [c for c in cases if c.get("split") == "holdout"],
        "REDTEAM": [c for c in cases if c.get("split") == "redteam"],
    }
    policies = ["lexicon", "broad"] if args.policy == "all" else [args.policy]

    print("=" * 68)
    print(f"하이브리드 효과 측정 — judge={args.mode} "
          f"({'완벽 판정 가정 상한' if args.mode=='oracle' else '무동작=룰 단독'})")
    if args.mode == "oracle":
        print("주의: oracle는 상한이다. 실제 LLM은 이보다 낮다(2차 오탐 가능).")
    print("정책: lexicon=어휘 매칭(좁음/저비용), broad=food·beauty safe 전수(넓음/고비용)")
    print("=" * 68)
    for policy in policies:
        print(f"\n### 정책 = {policy}")
        for name, cs in splits.items():
            if not cs:
                continue
            r = eval_split(cs, args.mode, policy=policy)
            print(f"[{name}] n={r['n']}  "
                  f"룰 {r['rule_acc']:.1%} → 하이브리드 {r['hybrid_acc']:.1%}  "
                  f"(에스컬레이션율 {r['escalation_rate']:.1%})  "
                  f"교정 {len(r['fixed'])} / 사각 {len(r['missed_by_routing'])}")
    print("=" * 68)


if __name__ == "__main__":
    main()

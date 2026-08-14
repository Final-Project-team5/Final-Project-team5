"""규제 룰 회귀 테스트 하니스 (골드셋 기반).

목적:
    규제 룰을 수정할 때마다 정확도를 측정해, 미탐/오탐/등급오류를 숫자로 잡는다.
    "감으로" 룰을 고치지 않기 위함.

지표 (v2 — PM/강사님 리뷰 반영):
    이진 지표만 보면 block/warn 등급 오류가 가려진다는 지적을 반영해,
    등급까지 정확히 맞췄는지(3-클래스 정확 일치율)를 1차 지표로 둔다.
    - label_accuracy: predicted == expected (라벨 문자열 그대로 일치) 비율  ← 1차
    - detection P/R/F1: flagged(block|warn) vs safe 이진 탐지 (참고용)
    - severity_errors: 둘 다 flagged인데 등급이 다른 케이스(warn↔block, 양방향)
    - 미탐(false_negatives) / 오탐(false_positives)

라벨(gold_cases.json의 expected): block / warn / safe — 사람이 판정한 정답.
비용 0 (룰 검사만). API 불필요.

사용:
    python -m eval.run_goldset
    python -m eval.run_goldset --json baseline.json
"""
import argparse
import json
import os

from copy_model.regulation import check_rules

_HERE = os.path.dirname(__file__)
_GOLD = os.path.join(_HERE, "gold_cases.json")


def predict(headline: str, sub: str, category: str) -> str:
    """현재 룰의 예측 라벨."""
    flags = check_rules(f"{headline} {sub}", category)
    if any(f.severity == "block" for f in flags):
        return "block"
    if flags:
        return "warn"
    return "safe"


def evaluate(cases: list) -> dict:
    rows = []
    for c in cases:
        pred = predict(c["headline"], c["sub"], c["category"])
        exp = c["expected"]
        rows.append({
            "id": c["id"], "category": c["category"],
            "text": f'{c["headline"]} / {c["sub"]}',
            "expected": exp, "predicted": pred,
            "exact": pred == exp,
            "exp_flagged": exp in ("block", "warn"),
            "pred_flagged": pred in ("block", "warn"),
            "note": c.get("note", ""),
        })
    n = len(rows)

    # ── 1차 지표: 3-클래스 정확 일치율 (등급까지 맞췄는지) ──
    exact = sum(1 for r in rows if r["exact"])
    label_accuracy = round(exact / n, 3) if n else 0.0

    # 3-클래스 혼동 (정답→예측)
    conf3 = {}
    for r in rows:
        k = f'{r["expected"]}→{r["predicted"]}'
        conf3[k] = conf3.get(k, 0) + 1

    # ── 참고 지표: 이진 탐지(flagged vs safe) ──
    tp = sum(1 for r in rows if r["exp_flagged"] and r["pred_flagged"])
    fp = sum(1 for r in rows if not r["exp_flagged"] and r["pred_flagged"])
    fn = sum(1 for r in rows if r["exp_flagged"] and not r["pred_flagged"])
    tn = sum(1 for r in rows if not r["exp_flagged"] and not r["pred_flagged"])
    precision = round(tp / (tp + fp), 3) if (tp + fp) else 0.0
    recall = round(tp / (tp + fn), 3) if (tp + fn) else 0.0
    f1 = round(2 * precision * recall / (precision + recall), 3) if (precision + recall) else 0.0

    # ── 오류 분류 ──
    false_pos = [r for r in rows if not r["exp_flagged"] and r["pred_flagged"]]   # 오탐(정상→flag)
    false_neg = [r for r in rows if r["exp_flagged"] and not r["pred_flagged"]]   # 미탐(위반→통과)
    # 등급 오류: 둘 다 flagged인데 등급이 다름(warn↔block). 양방향 모두 잡음.
    severity_errors = [r for r in rows
                       if r["exp_flagged"] and r["pred_flagged"] and not r["exact"]]

    return {
        "n": n,
        "label_accuracy": label_accuracy,       # ← 1차 지표
        "confusion_3class": conf3,
        "detection": {"precision": precision, "recall": recall, "f1": f1,
                      "tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "false_positives": false_pos,           # 오탐
        "false_negatives": false_neg,           # 미탐
        "severity_errors": severity_errors,     # 등급 오류(warn↔block)
        "rows": rows,
    }


def _report(title: str, res: dict):
    d = res["detection"]
    print("-" * 60)
    print(f"[{title}] n={res['n']}  "
          f"라벨 정확일치 {res['label_accuracy']:.1%}  "
          f"(탐지 P {d['precision']:.1%}/R {d['recall']:.1%}/F1 {d['f1']:.1%})")
    print(f"   3-클래스 혼동: " +
          "  ".join(f"{k} {v}" for k, v in sorted(res["confusion_3class"].items())))
    if res["false_negatives"]:
        print(f"   🔴 미탐 {len(res['false_negatives'])}건:")
        for r in res["false_negatives"]:
            print(f"      [{r['id']}] {r['text']} (정답 {r['expected']}→예측 {r['predicted']}) {r['note']}")
    if res["severity_errors"]:
        print(f"   🟠 등급오류 {len(res['severity_errors'])}건:")
        for r in res["severity_errors"]:
            print(f"      [{r['id']}] {r['text']} (정답 {r['expected']}→예측 {r['predicted']}) {r['note']}")
    if res["false_positives"]:
        print(f"   🟡 오탐 {len(res['false_positives'])}건:")
        for r in res["false_positives"]:
            print(f"      [{r['id']}] {r['text']} (정답 {r['expected']}→예측 {r['predicted']}) {r['note']}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--json", type=str, default="", help="결과 저장 경로(전/후 비교용)")
    args = p.parse_args()

    with open(_GOLD, encoding="utf-8") as f:
        gold = json.load(f)
    cases = gold["cases"]
    train = [c for c in cases if c.get("split", "train") == "train"]
    holdout = [c for c in cases if c.get("split") == "holdout"]
    redteam = [c for c in cases if c.get("split") == "redteam"]

    # 대표 지표는 train+holdout(일반 분포)만. redteam은 적대적 진단으로 분리.
    repr_cases = train + holdout
    res_all = evaluate(repr_cases)
    res_train = evaluate(train)
    res_holdout = evaluate(holdout) if holdout else None
    res_redteam = evaluate(redteam) if redteam else None

    print("=" * 60)
    print("규제 룰 골드셋 회귀 테스트  (1차 지표 = 라벨 정확일치율)")
    _report("TRAIN (튜닝 대상)", res_train)
    if res_holdout:
        _report("HOLDOUT (미노출 — 과적합 판단 기준)", res_holdout)
    _report("전체(대표 = TRAIN+HOLDOUT)", res_all)
    print("=" * 60)
    if res_redteam:
        print("[적대적 진단 — 대표 지표에 미포함]")
        print("의미회피 위반을 일부러 넣어 룰 맹점을 노출하는 스트레스셋.")
        print("여기서의 미탐은 '한계 확인'이지 회귀 실패가 아니다.")
        _report("REDTEAM (의미회피 스트레스)", res_redteam)
        print("=" * 60)

    if args.json:
        out = {"train": res_train, "holdout": res_holdout,
               "all": res_all, "redteam": res_redteam}
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"결과 저장: {args.json}")


if __name__ == "__main__":
    main()

"""규제 룰 회귀 테스트 하니스 (골드셋 기반).

목적:
    규제 룰을 수정할 때마다 precision/recall을 측정해, 미탐(놓친 위반)을 줄이려다
    오탐(정상 문구 차단)이 늘어나는 것을 숫자로 잡는다. "감으로" 룰을 고치지 않기 위함.

라벨(gold_cases.json의 expected):
    block / warn / safe — 사람이 판정한 정답.

예측(현재 룰):
    check_rules 결과에서 block 플래그 있으면 block, 그 외 플래그만 있으면 warn, 없으면 safe.

측정:
    - 탐지(위반=block+warn 을 flagged 로) 관점의 precision/recall/F1
    - block 심각도 정확도(expected block 중 실제 block 예측 비율)
    - 오탐 목록(safe인데 flagged) / 미탐 목록(위반인데 safe 예측 또는 심각도 미달)
    비용 0 (룰 검사만). API 불필요.

사용:
    python -m eval.run_goldset
    python -m eval.run_goldset --json baseline.json   # 결과 저장(전/후 비교용)
"""
import argparse
import json
import os

from copy_model.regulation import check_rules

_HERE = os.path.dirname(__file__)
_GOLD = os.path.join(_HERE, "gold_cases.json")

_RANK = {"safe": 0, "warn": 1, "block": 2}


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
        # 탐지 관점: block/warn = 위반(1), safe = 정상(0)
        exp_flagged = exp in ("block", "warn")
        pred_flagged = pred in ("block", "warn")
        rows.append({
            "id": c["id"], "category": c["category"],
            "text": f'{c["headline"]} / {c["sub"]}',
            "expected": exp, "predicted": pred,
            "exp_flagged": exp_flagged, "pred_flagged": pred_flagged,
            "under_severity": _RANK[pred] < _RANK[exp],   # 심각도 미달(예: block인데 warn/safe)
            "note": c.get("note", ""),
        })

    tp = sum(1 for r in rows if r["exp_flagged"] and r["pred_flagged"])
    fp = sum(1 for r in rows if not r["exp_flagged"] and r["pred_flagged"])
    fn = sum(1 for r in rows if r["exp_flagged"] and not r["pred_flagged"])
    tn = sum(1 for r in rows if not r["exp_flagged"] and not r["pred_flagged"])

    precision = round(tp / (tp + fp), 3) if (tp + fp) else 0.0
    recall = round(tp / (tp + fn), 3) if (tp + fn) else 0.0
    f1 = round(2 * precision * recall / (precision + recall), 3) if (precision + recall) else 0.0

    # block 심각도 정확도
    exp_block = [r for r in rows if r["expected"] == "block"]
    block_hit = sum(1 for r in exp_block if r["predicted"] == "block")
    block_recall = round(block_hit / len(exp_block), 3) if exp_block else 0.0

    false_pos = [r for r in rows if not r["exp_flagged"] and r["pred_flagged"]]     # 오탐
    false_neg = [r for r in rows if r["exp_flagged"] and not r["pred_flagged"]]     # 미탐(완전 통과)
    under_sev = [r for r in rows if r["under_severity"] and r["pred_flagged"]]      # 잡았지만 심각도 미달

    return {
        "n": len(rows),
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "detection": {"precision": precision, "recall": recall, "f1": f1},
        "block_severity_recall": block_recall,
        "false_positives": false_pos,   # 오탐
        "false_negatives": false_neg,   # 미탐
        "under_severity": under_sev,
        "rows": rows,
    }


def _report(title: str, res: dict):
    d = res["detection"]
    c = res["confusion"]
    print("-" * 60)
    print(f"[{title}] n={res['n']}  "
          f"Precision {d['precision']:.1%}  Recall {d['recall']:.1%}  F1 {d['f1']:.1%}")
    print(f"   (TP {c['tp']} / FP {c['fp']} / FN {c['fn']} / TN {c['tn']}) "
          f"block 심각도 recall {res['block_severity_recall']:.1%}")
    if res["false_negatives"]:
        print(f"   🔴 미탐 {len(res['false_negatives'])}건:")
        for r in res["false_negatives"]:
            print(f"      [{r['id']}] {r['text']} (정답 {r['expected']}→예측 {r['predicted']}) {r['note']}")
    if res["under_severity"]:
        print(f"   🟠 심각도 미달 {len(res['under_severity'])}건:")
        for r in res["under_severity"]:
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

    res_all = evaluate(cases)
    res_train = evaluate(train)
    res_holdout = evaluate(holdout) if holdout else None

    print("=" * 60)
    print("규제 룰 골드셋 회귀 테스트")
    _report("TRAIN (튜닝 대상)", res_train)
    if res_holdout:
        _report("HOLDOUT (미노출 — 과적합 판단 기준)", res_holdout)
    _report("전체", res_all)
    print("=" * 60)

    if args.json:
        out = {"train": res_train, "holdout": res_holdout, "all": res_all}
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"결과 저장: {args.json}")


if __name__ == "__main__":
    main()

"""LLM 판정 실측 러너 (P2 실측 단계, API 소량 + 캐시).

무엇을 하나:
    에스컬레이션 대상 케이스만 실제 LLM judge로 판정해 캐시에 저장하고,
    라우팅 정책(lexicon/broad) x 신뢰 정책(full/asymmetric) 조합별로
    룰 단독 대비 하이브리드 정확도를 실측한다.

비용 통제 (핵심):
    - 에스컬레이션된 케이스만 호출 (전건 아님).
    - 기본 대상은 HOLDOUT + REDTEAM (TRAIN 제외, --include-train으로 포함).
    - 판정 결과는 캐시(eval/results/llm_judge_cache.json)에 저장 —
      재실행 시 캐시 히트면 API 호출 0회. temperature 0으로 재현성 확보.

신뢰 정책 (2차 오판 가드):
    - full: LLM 판정 그대로 반영.
    - asymmetric: 등급을 올리는 판정(safe->warn/block 등, 더 엄격)은 반영,
      내리는 판정(warn->safe 등, 완화)은 근거(reason)가 있을 때만 반영.
      규제 도구는 미탐 비용이 커서, LLM 오판으로 규제가 뚫리는 경로를 차단.

사용:
    # 사전 점검 (API 호출 0, oracle로 배선만 확인)
    COPY_MOCK=1 python -m eval.run_llm_live --dry-run

    # 실측 (로컬에서, .env에 OPENAI_API_KEY 필요. 키를 커밋/채팅에 넣지 말 것)
    python -m eval.run_llm_live

    # 캐시만으로 재분석 (API 0회)
    python -m eval.run_llm_live --cache-only
"""
import argparse
import hashlib
import json
import os

from copy_model import config
from copy_model.regulation_llm import (
    hybrid_check, build_llm_judge, LLMVerdict,
)

_HERE = os.path.dirname(__file__)
_GOLD = os.path.join(_HERE, "gold_cases.json")
_CACHE = os.path.join(_HERE, "results", "llm_judge_cache.json")

PROMPT_VERSION = "v1"          # judge 프롬프트 바꾸면 올릴 것 (캐시 무효화 키)
_RANK = {"safe": 0, "warn": 1, "block": 2}


def _key(c: dict) -> str:
    raw = f"{PROMPT_VERSION}|{c['category']}|{c['headline']}|{c['sub']}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _load_cache() -> dict:
    if os.path.exists(_CACHE):
        with open(_CACHE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_cache(cache: dict):
    os.makedirs(os.path.dirname(_CACHE), exist_ok=True)
    with open(_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _client_chat_t0(messages: list) -> dict:
    """temperature 0 고정 (재현성). 캐시 미스일 때만 호출됨."""
    from openai import OpenAI
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=config.MODEL_NAME, messages=messages,
        response_format={"type": "json_object"}, temperature=0,
    )
    return json.loads(resp.choices[0].message.content)


def _apply_trust(rule_sev: str, verdict: LLMVerdict, trust: str) -> str:
    """신뢰 정책에 따라 최종 등급 결정."""
    if trust == "full":
        return verdict.severity
    # asymmetric: 엄격해지는 방향은 수용, 완화는 근거 있을 때만
    if _RANK[verdict.severity] >= _RANK[rule_sev]:
        return verdict.severity
    return verdict.severity if verdict.reason.strip() else rule_sev


def measure(cases, judge_fn, routing: str, trust: str) -> dict:
    n = len(cases)
    rule_ok = hyb_ok = 0
    fixed, broke = [], []
    for c in cases:
        res = hybrid_check(c["headline"], c["sub"], c["category"],
                           judge=judge_fn, policy=routing)
        exp = c["expected"]
        r_ok = (res.rule_severity == exp)
        if res.source == "llm" and res.llm_verdict:
            final = _apply_trust(res.rule_severity, res.llm_verdict, trust)
        else:
            final = res.rule_severity
        h_ok = (final == exp)
        rule_ok += r_ok
        hyb_ok += h_ok
        if not r_ok and h_ok:
            fixed.append(c["id"])
        if r_ok and not h_ok:
            broke.append(c["id"])
    return {"n": n, "rule_acc": rule_ok / n if n else 0,
            "hybrid_acc": hyb_ok / n if n else 0,
            "fixed": fixed, "broke": broke}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="API 호출 없이 oracle 판정으로 배선만 점검")
    p.add_argument("--cache-only", action="store_true",
                   help="캐시에 있는 판정만 사용 (API 호출 금지)")
    p.add_argument("--include-train", action="store_true")
    args = p.parse_args()

    with open(_GOLD, encoding="utf-8") as f:
        cases = json.load(f)["cases"]
    if not args.include_train:
        cases = [c for c in cases if c.get("split") in ("holdout", "redteam")]

    cache = _load_cache()
    calls = {"api": 0, "cache": 0}
    expected_by_key = {_key(c): c["expected"] for c in cases}

    if args.dry_run:
        def judge_fn(h, s, cat, rule_sev, direction):
            k = hashlib.sha1(
                f"{PROMPT_VERSION}|{cat}|{h}|{s}".encode()).hexdigest()[:16]
            return LLMVerdict(expected_by_key.get(k, rule_sev), "oracle(dry-run)")
    else:
        real_judge = build_llm_judge(_client_chat_t0)

        def judge_fn(h, s, cat, rule_sev, direction):
            k = hashlib.sha1(
                f"{PROMPT_VERSION}|{cat}|{h}|{s}".encode()).hexdigest()[:16]
            if k in cache:
                calls["cache"] += 1
                v = cache[k]
                return LLMVerdict(v["severity"], v["reason"])
            if args.cache_only:
                return LLMVerdict(rule_sev, "")   # 캐시 미스 → 룰 유지
            if not config.OPENAI_API_KEY:
                raise SystemExit(
                    "OPENAI_API_KEY 없음. .env 설정 후 실행 (키를 커밋/채팅에 넣지 말 것). "
                    "배선 점검만 하려면 --dry-run.")
            calls["api"] += 1
            v = real_judge(h, s, cat, rule_sev, direction)
            cache[k] = {"severity": v.severity, "reason": v.reason,
                        "case": f"{h} / {s}", "category": cat}
            return v

    print("=" * 68)
    mode = "DRY-RUN(oracle)" if args.dry_run else (
        "CACHE-ONLY" if args.cache_only else "LIVE(temperature 0, 캐시 사용)")
    print(f"LLM 판정 실측 — {mode}  대상 {len(cases)}건"
          f"{'' if args.include_train else ' (HOLDOUT+REDTEAM)'}")
    print("=" * 68)
    for routing in ("lexicon", "broad"):
        for trust in ("full", "asymmetric"):
            for split in ("holdout", "redteam"):
                cs = [c for c in cases if c.get("split") == split]
                if not cs:
                    continue
                r = measure(cs, judge_fn, routing, trust)
                print(f"[{routing:7}/{trust:10}] {split.upper():7} n={r['n']:2}  "
                      f"룰 {r['rule_acc']:.1%} → 하이브리드 {r['hybrid_acc']:.1%}  "
                      f"교정 {len(r['fixed'])} 파손 {len(r['broke'])}"
                      + (f"  파손: {','.join(r['broke'])}" if r["broke"] else ""))
    print("-" * 68)
    if not args.dry_run:
        _save_cache(cache)
        print(f"API 호출 {calls['api']}회 / 캐시 히트 {calls['cache']}회  "
              f"(캐시: eval/results/llm_judge_cache.json — 커밋 OK, 키 아님)")
    print("=" * 68)


if __name__ == "__main__":
    main()

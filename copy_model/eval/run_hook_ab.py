"""매력 문구 A/B 실험 하니스 (진우님 요청).

목적:
    현재 생성 프롬프트가 규제 안전 쪽으로 기울어 카피가 안정적이지만 밋밋할 수
    있다. 안전(규제 통과율)을 유지하면서 후킹(매력도)을 올리는 프롬프트 변형을
    찾는다. 매력을 올리다 위반율이 오르는 변형은 탈락시킨다.

측정 두 축:
    1) 규제 통과율 — check_rules로 계산(비용 0, 결정적). 변형이 위반율을
       올리면 안 된다.
    2) 매력도 pairwise 승률 — 변형 vs baseline을 LLM 심사위원이 비교(실환경만).
       position bias를 줄이려 A/B 자리를 바꿔 2회 판정한다.

변형(프로덕션 프롬프트는 안 건드리고, 시스템 프롬프트에 지침 블록만 덧붙임):
    baseline / hook(구체·감각·호기심갭) / persona(타깃 명시) / cta(행동유도).
    모든 변형은 규제 지침을 유지한다(include_regulation=True).

사용:
    # 실측 (VM에서 키 있는 상태) — 상세 덤프까지
    COPY_MOCK=0 python -m eval.run_hook_ab --dump hook_ab.json
    # 플러밍 점검 (비용 0, mock — 매력 비교는 안 되고 크래시 없이 도는지만)
    COPY_MOCK=1 python -m eval.run_hook_ab

주의: mock은 고정 샘플이라 변형 간 차이가 안 난다. 실효 비교는 반드시 키로 실행.
      LLM 심사는 자기 스타일 선호 편향이 있어, 최종 채택 전 사람 확인 10건 권장.
"""
import argparse
import json

from copy_model import config, prompts
from copy_model.generator import _chat_json, _client
from copy_model.regulation import check_rules
from eval.metrics import evaluate_batch


# 각 변형이 시스템 프롬프트 끝에 덧붙이는 지침 블록.
HOOK_VARIANTS = {
    "baseline": "",
    "hook": (
        "\n[매력 강화 지침]\n"
        "- headline 첫 3~5단어로 시선을 잡는다(구체적 장면·감각어).\n"
        "- 추상어 대신 구체(재료·상황·감각)로 표현한다. 단, 검증 불가한 "
        "수치·효능·최상급은 절대 쓰지 않는다.\n"
        "- 한 문장에 호기심 갭을 하나만 심되, 과장·확정 표현은 피한다.\n"
    ),
    "persona": (
        "\n[타깃 페르소나 지침]\n"
        "- 이 제품/서비스를 살 대표 고객 한 명의 상황·고민을 겨냥한다.\n"
        "- 그 고객이 '내 얘기'라고 느낄 구체적 맥락을 headline이나 sub에 담는다.\n"
        "- 규제 금지 표현은 그대로 지킨다.\n"
    ),
    "cta": (
        "\n[행동 유도 지침]\n"
        "- sub 끝에 부담 없는 다음 행동을 자연스럽게 제안한다"
        "(예: 오늘 맛보기, 지금 담기, 상담 받기).\n"
        "- 강매·과장 없이, 규제 금지 표현은 그대로 지킨다.\n"
    ),
}


# 매력 비교용 대표 시나리오 — 위반 유도가 아니라 정상적인 홍보 요청.
# (category, product, keywords, request)
SCENARIOS = [
    ("food", "수제 딸기 생크림 케이크", ["당일 생산", "국내산 생크림"], "주말 한정 판매"),
    ("food", "갓 볶은 싱글오리진 원두", ["직접 로스팅", "당일 배송"], "신규 오픈 이벤트"),
    ("food", "매콤 로제 떡볶이", ["즉석 조리", "포장 가능"], "신메뉴 출시"),
    ("beauty", "저자극 수분 세럼", ["민감성", "데일리"], "체험분 증정"),
    ("beauty", "매트 립 틴트", ["지속력", "선명한 발색"], "신상 컬러 3종"),
    ("beauty", "약산성 클렌징 폼", ["순한 세정", "아침 세안"], "리필 할인"),
    ("goods", "감성 가죽 다이어리", ["수기 기록", "선물용"], "이니셜 각인 무료"),
    ("goods", "미니멀 데스크 매트", ["넓은 사이즈", "논슬립"], "재입고"),
    ("goods", "우드 무드등", ["따뜻한 조명", "취침등"], "집들이 선물 추천"),
    ("academy", "우리 학원", ["소수정예", "1:1 첨삭"], "신학기 개강반 모집"),
    ("academy", "우리 학원", ["성적 향상 사례", "밀착 관리"], "레벨테스트 무료"),
    ("sports", "우리 체육관", ["초보 환영", "1:1 PT"], "신규 등록 상담"),
]


def _build_system(category: str, tone: str, num: int, variant: str) -> str:
    """baseline 시스템 프롬프트 + 변형 지침 블록. 규제 지침은 항상 유지."""
    base = prompts.build_system_prompt(
        category, tone, num, config.HEADLINE_MAX, config.SUB_MAX,
        include_regulation=True)
    return base + HOOK_VARIANTS[variant]


def _generate(client, category, product, keywords, request, num, variant):
    system = _build_system(category, "warm", num, variant)
    user = prompts.build_user_prompt(product, keywords, request, num)
    data = _chat_json(client, system, user)
    return [
        {"headline": str(c.get("headline", "")).strip(),
         "sub": str(c.get("sub", "")).strip()}
        for c in data.get("candidates", [])[:num]
    ]


def _mock_generate(category, num):
    from copy_model.generator import _MOCK_SAMPLES
    samples = _MOCK_SAMPLES.get(category, _MOCK_SAMPLES["food"])
    return [{"headline": h, "sub": s} for h, s in samples[:num]]


_JUDGE_SYSTEM = (
    "너는 광고 카피 심사위원이다. 같은 제품에 대한 두 광고 문구 세트 A와 B 중 "
    "더 매력적인 쪽을 고른다. 기준: 시선을 끄는 후킹, 구체성, 톤 적합성, 신뢰감. "
    "과장·검증불가 표현·규제 위반 소지가 있으면 감점한다. "
    '반드시 JSON으로만 응답: {"winner": "A"|"B"|"tie", "reason": "..."}'
)


def _fmt_set(cands):
    return " / ".join(f"{c['headline']} — {c['sub']}" for c in cands)


def _judge_once(client, product, set_x, set_y):
    user = (
        f"제품: {product}\n\n"
        f"[A]\n{_fmt_set(set_x)}\n\n"
        f"[B]\n{_fmt_set(set_y)}\n\n"
        "어느 쪽이 더 매력적인가?"
    )
    data = _chat_json(client, _JUDGE_SYSTEM, user)
    w = str(data.get("winner", "tie")).strip().upper()
    return w if w in ("A", "B", "TIE") else "TIE"


def _judge_pair(client, product, base_set, var_set):
    """position bias 완화: 자리를 바꿔 2회 판정. 변형 승수(0~2)를 반환."""
    wins = 0
    # 1회차: A=baseline, B=variant → variant는 B
    if _judge_once(client, product, base_set, var_set) == "B":
        wins += 1
    # 2회차: A=variant, B=baseline → variant는 A
    if _judge_once(client, product, var_set, base_set) == "A":
        wins += 1
    return wins


def run(n: int, num: int, collect_detail: bool) -> dict:
    scenarios = SCENARIOS[:n]
    variants = list(HOOK_VARIANTS)
    detail = []

    # 변형별 생성물 수집.
    gen = {v: [] for v in variants}  # v -> list[(cands, category)]
    if config.MOCK_MODE:
        for cat, prod, kw, req in scenarios:
            samp = _mock_generate(cat, num)
            for v in variants:
                gen[v].append((samp, cat))
        note = "MOCK 모드 — 변형 간 동일 샘플. 매력 비교는 API 키 필요."
        client = None
    else:
        client = _client()
        for cat, prod, kw, req in scenarios:
            for v in variants:
                gen[v].append((_generate(client, cat, prod, kw, req, num, v), cat))
        note = "실측 결과 (매력 A/B)"

    # 1축: 규제 통과율(결정적).
    reg = {v: evaluate_batch(gen[v]).summary() for v in variants}

    # 2축: 매력 pairwise 승률(실환경만). 각 변형 vs baseline.
    win_rate = {}
    if not config.MOCK_MODE:
        base_sets = gen["baseline"]
        for v in variants:
            if v == "baseline":
                continue
            total_wins = 0
            for i, (cat, prod, kw, req) in enumerate(scenarios):
                base_cands = base_sets[i][0]
                var_cands = gen[v][i][0]
                w = _judge_pair(client, prod, base_cands, var_cands)
                total_wins += w
                if collect_detail:
                    detail.append({
                        "scenario": prod, "variant": v, "variant_wins_of_2": w,
                        "baseline": _fmt_set(base_cands),
                        "variant_copy": _fmt_set(var_cands),
                    })
            win_rate[v] = round(total_wins / (2 * len(scenarios)), 3)

    # 판정: baseline 대비 위반율을 안 올리면서 승률 > 0.5 인 변형이 후보.
    base_viol = reg["baseline"]["violation_rate"]
    verdict = {}
    for v in variants:
        if v == "baseline":
            continue
        viol_ok = reg[v]["violation_rate"] <= base_viol
        wr = win_rate.get(v)
        verdict[v] = {
            "violation_not_worse": viol_ok,
            "win_rate_vs_baseline": wr,
            "adopt_candidate": bool(viol_ok and wr is not None and wr > 0.5),
        }

    result = {
        "note": note,
        "n_scenarios": len(scenarios),
        "num_candidates": num,
        "regulation": reg,
        "win_rate_vs_baseline": win_rate,
        "verdict": verdict,
    }
    if collect_detail:
        result["detail"] = detail
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=len(SCENARIOS),
                   help=f"시나리오 수 (최대 {len(SCENARIOS)})")
    p.add_argument("--candidates", type=int, default=3, help="시나리오당 시안 수")
    p.add_argument("--dump", type=str, default="",
                   help="상세(생성 문구+판정) JSON 경로")
    args = p.parse_args()

    result = run(min(args.n, len(SCENARIOS)), args.candidates, bool(args.dump))
    summary = {k: v for k, v in result.items() if k != "detail"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.dump and "detail" in result:
        with open(args.dump, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n상세 저장: {args.dump}")

    if config.MOCK_MODE:
        print("\n[주의] MOCK 결과 — 매력 비교 없음. 실효 비교는 COPY_MOCK=0로 실행.")


if __name__ == "__main__":
    main()

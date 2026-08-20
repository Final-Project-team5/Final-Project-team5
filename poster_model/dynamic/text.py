"""줄바꿈 — Step 3.

E11 §7 에서 확인한 것: 한국어 문구는 **폭에 맞춰 기계적으로 자르는 것보다
의미 단위를 먼저 정하는 쪽**이 자연스러웠다. 그래서 줄바꿈은 타이포그래피
시스템의 일부이고 (`typography.break_strategy`), Renderer 가 임의로 정하지
않는다.

두 전략
    width      앞에서부터 채운다.  로고타입·짧은 토큰처럼 의미 단위가
               의미 없는 경우에 쓴다
    semantic   어절을 지키면서 줄 수·줄 폭 균형·고아 줄을 함께 본다

고아(orphan) 줄에 큰 벌점을 준다 — 마지막 줄에 한 어절만 남는 배치가
기계적으로는 최적이어도 광고 문구로는 나쁘다.

**크기를 줄여 맞추지 않는다.** 선언된 크기로 들어가지 않으면 실패다.
`size_step` 은 Planner 의 결정이고, 여기서 몰래 줄이면 디자인 결정을
가로채는 것이 된다 (E12 §6 R3).

모든 비용 계산은 정수다 — 부동소수 비교로 순서가 갈리지 않게 한다.
"""

from __future__ import annotations

from typing import Callable, Sequence, Tuple

from .errors import PlanUnresolvable

Measure = Callable[[str], int]

# 비용 가중치는 measure² 를 단위로 잡는다 — 폭이 달라져도 상대 비중이 같다
ORPHAN_WEIGHT = 3          # 마지막 줄이 한 어절뿐일 때
LINE_WEIGHT = 1            # 줄이 하나 늘 때마다
_JOIN = " "


def _split_long_token(token: str, measure: Measure, limit: int) -> Tuple[str, ...]:
    """어절 하나가 측정 폭을 넘을 때만 글자 단위로 쪼갠다.

    E11 에서 실제로 겪은 경우다 — 공백이 없는 한 어절("맛보세요")이 단 폭을
    531px 넘겼는데, 줄 수만 세고 줄 폭을 안 봐서 통과했다. 그래서 여기서는
    글자 단위 분해를 **명시적인 마지막 수단**으로 둔다.
    """
    chunks: list[str] = []
    current = ""
    for ch in token:
        trial = current + ch
        if current and measure(trial) > limit:
            chunks.append(current)
            current = ch
        else:
            current = trial
    if current:
        chunks.append(current)
    if not chunks or any(measure(c) > limit for c in chunks):
        raise PlanUnresolvable(
            "text.unfittable",
            "copy_blocks",
            f"글자 하나도 {limit}px 에 들어가지 않는다 (어절 {token!r}) — "
            "크기를 몰래 줄이지 않는다",
        )
    return tuple(chunks)


def tokenize(text: str, measure: Measure, limit: int) -> Tuple[str, ...]:
    tokens: list[str] = []
    for raw in text.split():
        if measure(raw) <= limit:
            tokens.append(raw)
        else:
            tokens.extend(_split_long_token(raw, measure, limit))
    if not tokens:
        raise PlanUnresolvable("text.empty", "copy_blocks", "빈 문자열은 블록이 될 수 없다")
    return tuple(tokens)


def _line_text(tokens: Sequence[str], i: int, j: int) -> str:
    return _JOIN.join(tokens[i:j])


def break_width(text: str, measure: Measure, limit: int, max_lines: int) -> Tuple[str, ...]:
    """앞에서부터 채운다. 결정론적이고 설명하기 쉽다."""
    tokens = tokenize(text, measure, limit)
    lines: list[str] = []
    current = ""
    for token in tokens:
        trial = f"{current}{_JOIN}{token}" if current else token
        if current and measure(trial) > limit:
            lines.append(current)
            current = token
        else:
            current = trial
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        raise PlanUnresolvable(
            "text.too_many_lines",
            "copy_blocks",
            f"{len(lines)}줄이 필요한데 max_lines={max_lines} 다",
        )
    return tuple(lines)


def break_semantic(text: str, measure: Measure, limit: int, max_lines: int) -> Tuple[str, ...]:
    """어절을 지키면서 줄 수 · 균형 · 고아 줄을 함께 본다.

    DP 로 전역 최적을 찾는다. 앞에서부터 채우는 방식은 마지막 줄에 한 어절만
    남기는 배치를 자주 만든다.

    동률 처리 — 비용이 같으면 **줄 수가 적은 쪽**을 쓴다. 줄 수도 같으면
    앞쪽 분할을 쓴다 (탐색 순서가 결과를 바꾸지 않도록 고정).
    """
    tokens = tokenize(text, measure, limit)
    n = len(tokens)
    widths = [[0] * (n + 1) for _ in range(n + 1)]
    for i in range(n):
        for j in range(i + 1, n + 1):
            widths[i][j] = measure(_line_text(tokens, i, j))

    unit = max(1, limit) ** 2
    orphan_cost = ORPHAN_WEIGHT * unit
    line_cost = LINE_WEIGHT * unit

    INF = float("inf")
    # best[k][j] = (비용, 직전 분할점) — 앞의 j 어절을 k 줄로 놓은 최선
    best: list[list[object]] = [[(INF, -1)] * (n + 1) for _ in range(max_lines + 1)]
    best[0][0] = (0, -1)

    for k in range(1, max_lines + 1):
        for j in range(1, n + 1):
            chosen = (INF, -1)
            for i in range(j):
                prev = best[k - 1][i][0]
                if prev == INF:
                    continue
                w = widths[i][j]
                if w > limit:
                    continue
                slack = limit - w
                cost = prev + slack * slack + line_cost
                if j == n and (j - i) == 1 and n >= 3:
                    cost += orphan_cost        # 마지막 줄이 한 어절
                if cost < chosen[0]:           # 동률이면 앞쪽 분할 유지
                    chosen = (cost, i)
            best[k][j] = chosen

    for k in range(1, max_lines + 1):          # 줄 수가 적은 쪽부터 본다
        cost, _ = best[k][n]
        if cost != INF:
            return _rebuild(best, tokens, k, n)

    raise PlanUnresolvable(
        "text.too_many_lines",
        "copy_blocks",
        f"{text!r} 를 {limit}px · {max_lines}줄 안에 넣을 수 없다 — "
        "크기를 줄여 맞추지 않는다",
    )


def _rebuild(best, tokens, k: int, n: int) -> Tuple[str, ...]:
    out: list[str] = []
    j = n
    while k > 0:
        _, i = best[k][j]
        out.append(_line_text(tokens, i, j))
        j = i
        k -= 1
    return tuple(reversed(out))


def break_lines(
    text: str, measure: Measure, limit: int, max_lines: int, strategy: str
) -> Tuple[str, ...]:
    if limit <= 0:
        raise PlanUnresolvable("text.no_measure", "copy_blocks", f"측정 폭이 {limit}px 다")
    if strategy == "width":
        return break_width(text, measure, limit, max_lines)
    return break_semantic(text, measure, limit, max_lines)


__all__ = [
    "ORPHAN_WEIGHT",
    "LINE_WEIGHT",
    "tokenize",
    "break_width",
    "break_semantic",
    "break_lines",
]

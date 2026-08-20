"""Grid Resolver — E12 v0.3 §4-1 · Step 2.

RenderSpec 의 **상대적 격자 선언**을 결정론적인 **정수 px 격자**로 바꾼다.
그 이상은 하지 않는다 — anchor 해석 · 제품/타이포/모티프 좌표 계산은 Step 3.

    Planner 결정      columns · margin_density · gutter_scale · baseline_scale
    Renderer 파생      baseline_px · margin · gutter_px · col_w · content · rows

핵심 불변식 (정수 정합)
    content_w == col_w × columns + gutter_px × (columns − 1)
    나눗셈이 남기는 1px 오차가 판면 전체를 미세하게 어긋나게 만들기 때문에
    **근사하지 않는다.**  정수해가 없으면 GridUnresolvable 로 거부한다.

부동소수를 쓰지 않는다
    v0.3 문서의 `round(short × density / baseline)` 는 float 연산이라
    플랫폼/파이썬 버전에 따라 경계값이 갈릴 수 있다. 여기서는 density·scale 을
    **정수 permille** 로 두고 정수 나눗셈만 쓴다. 같은 입력이면 어디서든 같은
    결과가 나온다 (§9 결정론 계약).

축 분리 (§4-1)
    short_side     baseline 후보 · margin density 의 기준
    canvas_width   horizontal — margin_x · gutter · col_w · content_x*
    canvas_height  vertical   — margin_y · rows · content_y*

    1:1 은 셋이 같은 값이라 구분이 드러나지 않는다. 그래서 v1 에서
    `margin_x == margin_y` 지만, **자료구조는 처음부터 분리해 둔다.**
    3:4 / 3:1 을 열 때 ResolvedGrid 를 다시 깨지 않기 위해서다.

capability
    Renderer v1 은 1:1 만 처리한다. 그 밖의 비율은 격자 계산을 **시작하기 전에**
    RatioUnsupported 로 거부한다. 근사·자동 대체·columns 자동 변경을 하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Optional, Tuple

from .errors import GridUnresolvable, RatioUnsupported
from .spec import RenderSpec
from .validate import PLANNER_CONTEXT, ValidationContext

# ── 상수 ─────────────────────────────────────────────────────────────────
# production `pipeline.config` 를 import 하지 않는다 — core_1x1 경로와 분리.
# 값이 같더라도 참조를 만들지 않는 것이 이 패키지의 전제다.
DEFAULT_SHORT_SIDE = 1024

BASELINE_MIN = 8
BASELINE_MAX = 32

# density / scale 을 permille(1/1000) 정수로 둔다 — float 없음
MARGIN_PERMILLE = {"tight": 50, "normal": 80, "loose": 120}      # 0.05 · 0.08 · 0.12
GUTTER_PERMILLE = {"tight": 1000, "normal": 1500, "loose": 2000}  # 1.0 · 1.5 · 2.0

RATIO_TERMS = {"1:1": (1, 1), "3:4": (3, 4), "3:1": (3, 1)}


# ── tie-break 규칙 (§4-1) ────────────────────────────────────────────────
# 아래 셋은 결과가 둘 이상 가능한 지점이다. 반복문의 우연한 순서나
# 파이썬 `round()` 의 은행가 반올림에 결과가 의존하지 않도록 **명시적으로**
# 고정한다. 규칙을 바꾸면 같은 Spec 의 픽셀이 달라지므로
# renderer_version 을 올려야 한다 (§9).
#
#   T1  baseline "normal" 이 중앙 후보 두 개 사이일 때  →  **작은 쪽**
#       candidates[(n - 1) // 2].  n=3 → index 1, n=4 → index 1
#
#   T2  gutter 탐색에서 target−d 와 target+d 가 둘 다 정수해일 때
#       →  **작은 gutter 우선** (target−d 를 먼저 본다)
#       거터가 좁으면 열이 넓어진다 — 판면을 더 쓰는 쪽을 택한다
#
#   T3  margin / gutter 를 정수로 반올림할 때 정확히 0.5 인 경우
#       →  **half-up** (올림).  `round()` 는 half-even 이라 쓰지 않는다
TIE_BREAKS: Tuple[Tuple[str, str], ...] = (
    ("T1 baseline middle", "후보가 짝수 개면 작은 쪽"),
    ("T2 gutter ±d", "같은 거리면 작은 gutter 우선"),
    ("T3 round half", "half-up (half-even 아님)"),
)


def round_half_up_div(num: int, den: int) -> int:
    """양의 정수 나눗셈을 half-up 으로 반올림한다 (T3).

    `(2·num + den) // (2·den)` — float 를 거치지 않는다.
    """
    if den <= 0:
        raise ValueError(f"분모는 양수여야 한다: {den}")
    return (2 * num + den) // (2 * den)


# ── 자료구조 ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CanvasSize:
    """실제 출력 크기. RenderSpec 은 비율만 갖고 크기는 서버 정책이다."""

    width: int
    height: int

    @property
    def short_side(self) -> int:
        return min(self.width, self.height)

    @classmethod
    def for_ratio(cls, ratio: str, short_side: int = DEFAULT_SHORT_SIDE) -> "CanvasSize":
        if ratio not in RATIO_TERMS:
            raise ValueError(f"알 수 없는 비율: {ratio!r}")
        rw, rh = RATIO_TERMS[ratio]
        if rw <= rh:
            return cls(width=short_side, height=short_side * rh // rw)
        return cls(width=short_side * rw // rh, height=short_side)


@dataclass(frozen=True)
class ResolvedGrid:
    """정수 px 격자. horizontal / vertical 축이 분리돼 있다.

    v1 은 1:1 만 지원하므로 `margin_x == margin_y` 지만, 자료구조는 3:4 / 3:1
    확장을 그대로 받도록 처음부터 나뉘어 있다.
    """

    canvas_width: int
    canvas_height: int
    short_side: int
    baseline_px: int
    margin_x: int
    margin_y: int
    gutter_px: int
    col_w: int
    content_x0: int
    content_x1: int
    content_y0: int
    content_y1: int
    rows: int
    columns: int

    @property
    def content_w(self) -> int:
        return self.content_x1 - self.content_x0

    @property
    def content_h(self) -> int:
        return self.content_y1 - self.content_y0

    def check_integer_exact(self) -> bool:
        """content 폭이 열과 거터로 **정확히** 나뉘는가."""
        return self.content_w == self.col_w * self.columns + self.gutter_px * (
            self.columns - 1
        )

    def as_dict(self) -> dict:
        return {
            "canvas_width": self.canvas_width,
            "canvas_height": self.canvas_height,
            "short_side": self.short_side,
            "baseline_px": self.baseline_px,
            "margin_x": self.margin_x,
            "margin_y": self.margin_y,
            "gutter_px": self.gutter_px,
            "col_w": self.col_w,
            "content_x0": self.content_x0,
            "content_x1": self.content_x1,
            "content_y0": self.content_y0,
            "content_y1": self.content_y1,
            "rows": self.rows,
            "columns": self.columns,
        }


# ── 1단계: capability ────────────────────────────────────────────────────
def check_capability(
    spec: RenderSpec, canvas: CanvasSize, context: Optional[ValidationContext] = None
) -> None:
    """격자 계산을 **시작하기 전에** 비율을 확인한다.

    지원하지 않는 비율을 조용히 1:1 규칙으로 해석하면 3:1 에서 열이 판면의
    1/3 만 덮는다. 그래서 근사하지 않고 거부한다 (§4-1 B안).
    """
    ctx = context or PLANNER_CONTEXT
    ratio = spec.canvas.ratio

    if ratio not in ctx.supported_ratios:
        raise RatioUnsupported(
            "canvas.ratio_unsupported",
            "canvas.ratio",
            f"현재 Renderer 는 {ctx.supported_ratios} 만 처리한다 (받음: {ratio!r}) — "
            "근사·자동 대체를 하지 않는다",
        )

    rw, rh = RATIO_TERMS[ratio]
    if canvas.width * rh != canvas.height * rw:
        raise GridUnresolvable(
            "grid.canvas_ratio_mismatch",
            "canvas",
            f"선언된 비율 {ratio} 와 실제 크기 {canvas.width}×{canvas.height} 가 다르다",
        )


# ── 2단계: baseline ──────────────────────────────────────────────────────
def baseline_candidates(short_side: int) -> Tuple[int, ...]:
    """짧은 변의 약수 중 8~32. 약수여야 세로 리듬이 캔버스에 딱 맞는다."""
    return tuple(
        d for d in range(BASELINE_MIN, BASELINE_MAX + 1) if short_side % d == 0
    )


def resolve_baseline(short_side: int, scale: str) -> int:
    cands = baseline_candidates(short_side)
    if not cands:
        raise GridUnresolvable(
            "grid.no_baseline_candidate",
            "grid.baseline_scale",
            f"짧은 변 {short_side} 에는 {BASELINE_MIN}~{BASELINE_MAX} 범위의 약수가 없다",
        )
    if scale == "fine":
        return cands[0]
    if scale == "coarse":
        return cands[-1]
    return cands[(len(cands) - 1) // 2]  # T1 — 짝수 개면 작은 쪽


# ── 3단계: margin ────────────────────────────────────────────────────────
def resolve_margin(short_side: int, baseline: int, density: str) -> int:
    """짧은 변 기준 여백을 baseline 배수로 맞춘다 (T3 half-up)."""
    units = round_half_up_div(short_side * MARGIN_PERMILLE[density], 1000 * baseline)
    return units * baseline


# ── 4단계: gutter 정수해 탐색 ────────────────────────────────────────────
def gutter_target(baseline: int, scale: str) -> int:
    return round_half_up_div(baseline * GUTTER_PERMILLE[scale], 1000)  # T3


def gutter_candidates(target: int, lo: int, hi: int) -> Iterator[int]:
    """target 에서 가까운 순. 같은 거리면 **작은 쪽 먼저** (T2)."""
    if lo > hi:
        return
    span = max(target - lo, hi - target, 0)
    for d in range(span + 1):
        for g in ((target,) if d == 0 else (target - d, target + d)):
            if lo <= g <= hi:
                yield g


def resolve_gutter(content_w: int, columns: int, target: int) -> Tuple[int, int]:
    """(gutter_px, col_w) 를 돌려준다. 정수해가 없으면 GridUnresolvable.

    탐색 불변식 — gutter ≥ 1 이고 col_w ≥ 1 이다. 그래서 `col_w <= 0` 은
    이 함수를 통과한 뒤에는 나올 수 없고, 관측되는 실패는
    `grid.gutter_unresolvable` 하나다.
    """
    gaps = columns - 1
    if gaps <= 0:
        raise GridUnresolvable("grid.columns_too_few", "grid.columns", f"{columns}")

    hi = (content_w - columns) // gaps  # col_w ≥ 1 을 보장하는 상한
    for gutter in gutter_candidates(target, 1, hi):
        remainder = content_w - gutter * gaps
        if remainder > 0 and remainder % columns == 0:
            return gutter, remainder // columns

    raise GridUnresolvable(
        "grid.gutter_unresolvable",
        "grid.gutter_scale",
        f"content {content_w}px 를 {columns}단으로 정수 분할하는 거터가 "
        f"1~{hi} 범위에 없다 — 가까운 값으로 보정하지 않는다",
    )


# ── 조립 ─────────────────────────────────────────────────────────────────
def build_grid(
    *,
    canvas_width: int,
    canvas_height: int,
    short_side: int,
    columns: int,
    baseline_px: int,
    margin_x: int,
    margin_y: int,
    target_gutter: int,
) -> ResolvedGrid:
    """이미 정해진 baseline/margin 으로 나머지를 계산한다.

    `resolve_grid` 의 하위 단계이자, 가드를 직접 시험하기 위한 진입점이다.
    """
    content_w = canvas_width - 2 * margin_x
    if content_w <= 0:
        raise GridUnresolvable(
            "grid.content_empty",
            "grid.margin_density",
            f"좌우 여백 {margin_x}×2 가 캔버스 폭 {canvas_width} 를 덮는다",
        )

    content_h = canvas_height - 2 * margin_y
    if content_h <= 0:
        raise GridUnresolvable(
            "grid.content_empty",
            "grid.margin_density",
            f"상하 여백 {margin_y}×2 가 캔버스 높이 {canvas_height} 를 덮는다",
        )

    gutter_px, col_w = resolve_gutter(content_w, columns, target_gutter)

    if col_w <= 0:  # 방어적 — 탐색 불변식상 도달하지 않는다
        raise GridUnresolvable(
            "grid.col_width_empty", "grid.columns", f"col_w={col_w}"
        )

    grid = ResolvedGrid(
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        short_side=short_side,
        baseline_px=baseline_px,
        margin_x=margin_x,
        margin_y=margin_y,
        gutter_px=gutter_px,
        col_w=col_w,
        content_x0=margin_x,
        content_x1=canvas_width - margin_x,
        content_y0=margin_y,
        content_y1=canvas_height - margin_y,
        rows=canvas_height // baseline_px,
        columns=columns,
    )

    if not grid.check_integer_exact():  # 방어적 — resolve_gutter 가 보장한다
        raise GridUnresolvable(
            "grid.not_integer_exact",
            "grid",
            f"content {grid.content_w} ≠ col_w {col_w}×{columns} + gutter {gutter_px}×{columns - 1}",
        )
    return grid


def resolve_grid(
    spec: RenderSpec,
    canvas: Optional[CanvasSize] = None,
    context: Optional[ValidationContext] = None,
) -> ResolvedGrid:
    """RenderSpec 의 상대 격자 선언 → 정수 px 격자.

    실패는 전부 예외다. 가까운 값으로 자동 보정하거나 columns 를 바꾸거나
    임의 기본값으로 되돌아가지 않는다.
    """
    canvas = canvas or CanvasSize.for_ratio(spec.canvas.ratio)
    check_capability(spec, canvas, context)

    short_side = canvas.short_side
    baseline_px = resolve_baseline(short_side, spec.grid.baseline_scale)
    margin = resolve_margin(short_side, baseline_px, spec.grid.margin_density)

    return build_grid(
        canvas_width=canvas.width,
        canvas_height=canvas.height,
        short_side=short_side,
        columns=spec.grid.columns,
        baseline_px=baseline_px,
        # v1: 두 축이 같은 값이지만 자료구조는 분리돼 있다.
        # 3:4 / 3:1 을 열 때 margin_y 를 canvas_height 기준으로 바꾸면 된다
        margin_x=margin,
        margin_y=margin,
        target_gutter=gutter_target(baseline_px, spec.grid.gutter_scale),
    )


__all__ = [
    "DEFAULT_SHORT_SIDE",
    "BASELINE_MIN",
    "BASELINE_MAX",
    "MARGIN_PERMILLE",
    "GUTTER_PERMILLE",
    "RATIO_TERMS",
    "TIE_BREAKS",
    "round_half_up_div",
    "CanvasSize",
    "ResolvedGrid",
    "check_capability",
    "baseline_candidates",
    "resolve_baseline",
    "resolve_margin",
    "gutter_target",
    "gutter_candidates",
    "resolve_gutter",
    "build_grid",
    "resolve_grid",
]

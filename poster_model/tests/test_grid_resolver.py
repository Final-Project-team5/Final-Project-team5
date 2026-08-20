"""Grid Resolver 테스트 — E12 v0.3 §4-1 · Step 2.

확인하는 것
    · AD-C 격자(16 / 80 / 24 / 124 / 64) 재현
    · tight / normal / loose 세 조합의 확정값
    · 정수 정합 불변식 — content_w == col_w×C + gutter×(C−1)
    · tie-break 세 규칙이 실제로 결과를 고정하는가
    · 실패는 전부 명시적 거부인가 (자동 보정 없음)
    · 결정론 — 반복 호출 · 전체 조합 스윕이 안정적인가

실행:  python tests/test_grid_resolver.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dynamic import RatioUnsupported, ValidationContext, load  # noqa: E402
from dynamic.errors import GridUnresolvable  # noqa: E402
from dynamic.grid import (  # noqa: E402
    BASELINE_MAX,
    BASELINE_MIN,
    RATIO_TERMS,
    CanvasSize,
    baseline_candidates,
    build_grid,
    gutter_candidates,
    gutter_target,
    resolve_baseline,
    resolve_gutter,
    resolve_grid,
    resolve_margin,
    round_half_up_div,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_renderspec_schema import valid_brief, valid_spec  # noqa: E402

FAILS: list[str] = []
CHECKS = 0

# 전체 조합 스윕의 기준 digest. 값이 바뀌면 같은 Spec 의 픽셀이 달라진다는 뜻이므로
# renderer_version 을 올려야 한다 (§9).
SWEEP_DIGEST = "1eb020f80652aef2"


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILS.append(label)


def section(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 62 - len(title)))


def spec_with(columns=6, margin="normal", gutter="normal", baseline="normal", ratio="1:1"):
    raw = valid_spec()
    raw["canvas"]["ratio"] = ratio
    raw["grid"] = {
        "columns": columns,
        "margin_density": margin,
        "gutter_scale": gutter,
        "baseline_scale": baseline,
    }
    if columns != 6:  # 열 수를 바꾸면 zone/grid_ref 도 맞춰 준다 (검증 통과용)
        raw["zones"] = {
            "type": {"col_start": 0, "col_span": max(1, columns - 2)},
            "product": {"col_start": 1, "col_span": max(1, columns - 1)},
            "overlap_intent": "allowed",
        }
        raw["typography"]["measure_cols"] = min(4, columns)
        for blk in raw["copy_blocks"]:
            if isinstance(blk["grid_ref"].get("col_start"), int):
                blk["grid_ref"]["col_span"] = columns - blk["grid_ref"]["col_start"]
        for inst in raw["motif"]["instances"]:
            if isinstance(inst["grid_ref"].get("col_start"), int):
                inst["grid_ref"]["col_span"] = columns - inst["grid_ref"]["col_start"]
        raw["motif"]["instances"][1]["split_at"] = {"col": min(2, columns)}
    # Spec 객체를 만들기 위한 것이므로 비율 제한을 풀고 load 한다.
    # 비율 거부는 **resolver 자신의 capability check** 로 확인한다
    # (검증 단계에도 같은 규칙이 있어 실제 경로에서는 이중으로 막힌다)
    return load(raw, valid_brief(), ValidationContext(supported_ratios=tuple(RATIO_TERMS)))


# ──────────────────────────────────────────────────────────────────────────
def test_adc_reference() -> None:
    section("AD-C 격자 재현 — 1024×1024 · 6단 · normal×3")

    grid = resolve_grid(spec_with())
    expected = {
        "baseline_px": 16,
        "margin_x": 80,
        "margin_y": 80,
        "gutter_px": 24,
        "col_w": 124,
        "rows": 64,
    }
    for key, want in expected.items():
        got = getattr(grid, key)
        check(got == want, f"AD-C {key}: 기대 {want} / 실제 {got}")
        print(f"  {'PASS' if got == want else 'FAIL'}  {key:12} = {got:4}  (기대 {want})")

    check(grid.content_x0 == 80 and grid.content_x1 == 944, "content x 경계")
    check(grid.content_y0 == 80 and grid.content_y1 == 944, "content y 경계")
    check(grid.content_w == 864, f"content_w 864 / 실제 {grid.content_w}")
    check(grid.short_side == 1024, "short_side")
    print(f"  PASS  content   x[{grid.content_x0}, {grid.content_x1}] "
          f"y[{grid.content_y0}, {grid.content_y1}]  {grid.content_w}×{grid.content_h}")

    exact = grid.check_integer_exact()
    check(exact, "정수 정합")
    print(f"  {'PASS' if exact else 'FAIL'}  정수 정합  {grid.content_w} = "
          f"{grid.col_w}×{grid.columns} + {grid.gutter_px}×{grid.columns - 1}")


def test_density_table() -> None:
    section("tight / normal / loose 확정값")

    table = {
        "tight": (16, 48, 14, 143),
        "normal": (16, 80, 24, 124),
        "loose": (16, 128, 30, 103),
    }
    for name, (bl, mg, gt, cw) in table.items():
        grid = resolve_grid(spec_with(margin=name, gutter=name))
        got = (grid.baseline_px, grid.margin_x, grid.gutter_px, grid.col_w)
        ok = got == (bl, mg, gt, cw)
        check(ok, f"{name}: 기대 {(bl, mg, gt, cw)} / 실제 {got}")
        print(f"  {'PASS' if ok else 'FAIL'}  {name:7} baseline {got[0]:3} · "
              f"margin {got[1]:4} · gutter {got[2]:3} · col_w {got[3]:4}"
              f"   정수정합 {grid.check_integer_exact()}")

    # tight / loose 는 목표 거터(16 / 32)가 정수해를 못 준다.
    # **탐색이 실제로 필요하다**는 증거이자, 그 조정이 Renderer 몫이라는 근거다
    for name, want_target in (("tight", 16), ("loose", 32)):
        got_target = gutter_target(16, name)
        grid = resolve_grid(spec_with(margin=name, gutter=name))
        adjusted = grid.gutter_px != got_target
        check(got_target == want_target, f"{name} 목표 거터 {want_target}")
        check(adjusted, f"{name} 은 목표에서 조정돼야 한다")
        print(f"  PASS  {name:7} 목표 {got_target} → 정수해 {grid.gutter_px} "
              f"(차이 {grid.gutter_px - got_target:+d})")


def test_baseline_scale() -> None:
    section("baseline_scale — fine / normal / coarse")

    cands = baseline_candidates(1024)
    check(cands == (8, 16, 32), f"1024 의 baseline 후보: {cands}")
    print(f"  PASS  1024 의 {BASELINE_MIN}~{BASELINE_MAX} 약수 → {cands}")

    for scale, want in (("fine", 8), ("normal", 16), ("coarse", 32)):
        grid = resolve_grid(spec_with(baseline=scale))
        ok = grid.baseline_px == want
        check(ok, f"baseline {scale} = {want} / 실제 {grid.baseline_px}")
        print(f"  {'PASS' if ok else 'FAIL'}  {scale:7} baseline {grid.baseline_px:3} · "
              f"margin {grid.margin_x:4} · gutter {grid.gutter_px:3} · "
              f"col_w {grid.col_w:4} · rows {grid.rows:4}")


def test_tie_breaks() -> None:
    section("tie-break 세 규칙")

    # T1 — 후보가 짝수 개일 때 normal 은 작은 쪽
    even = [n for n in range(100, 4000) if len(baseline_candidates(n)) % 2 == 0
            and len(baseline_candidates(n)) >= 2]
    sample = even[0]
    cands = baseline_candidates(sample)
    picked = resolve_baseline(sample, "normal")
    lower = cands[len(cands) // 2 - 1]
    ok = picked == lower
    check(ok, f"T1: {sample} 후보 {cands} → {picked} (작은 쪽 {lower})")
    print(f"  {'PASS' if ok else 'FAIL'}  T1 baseline 짝수 후보 {sample}: {cands} → {picked} "
          f"(중앙 두 개 중 작은 쪽)")

    # T2 — target±d 가 둘 다 후보일 때 작은 쪽을 먼저 본다
    order = list(gutter_candidates(24, 1, 40))
    ok = order[:5] == [24, 23, 25, 22, 26]
    check(ok, f"T2 탐색 순서: {order[:5]}")
    print(f"  {'PASS' if ok else 'FAIL'}  T2 gutter 탐색 순서 (target 24) → {order[:7]} …")

    # 실제로 양쪽 다 정수해인 상황을 만들어 작은 쪽이 뽑히는지 본다
    #   content 864 · 6단에서 g ≡ 0 (mod 6) 이면 해.  target 3 → 6 과 0 중 6 선택,
    #   target 9 이면 6(=9−3) 과 12(=9+3) 가 동시에 해 → 작은 6 이 나와야 한다
    both = [g for g in (6, 12) if (864 - g * 5) % 6 == 0]
    check(both == [6, 12], "양쪽 다 정수해인 상황 구성")
    gutter, col_w = resolve_gutter(864, 6, 9)
    ok = gutter == 6
    check(ok, f"T2 동률에서 작은 gutter: {gutter}")
    print(f"  {'PASS' if ok else 'FAIL'}  T2 동률 (target 9, 해 {both}) → gutter {gutter} · col_w {col_w}")

    # T3 — half-up.  파이썬 round() 는 half-even 이라 결과가 갈린다
    cases = [(1, 2, 1), (3, 2, 2), (5, 2, 3), (7, 2, 4)]
    ok_all = True
    for num, den, want in cases:
        got = round_half_up_div(num, den)
        ok_all &= got == want
    check(ok_all, "T3 half-up")
    py_round = [round(n / d) for n, d, _ in cases]
    ours = [round_half_up_div(n, d) for n, d, _ in cases]
    check(ours != py_round, "half-up 과 half-even 이 실제로 다르다")
    print(f"  {'PASS' if ok_all else 'FAIL'}  T3 half-up   ours={ours}  python round()={py_round}")
    print(f"        → round() 를 썼다면 0.5/2.5 에서 결과가 갈렸다")

    # float 를 쓰지 않는다 — 경계값에서 갈리지 않는지 확인
    ok = resolve_margin(1024, 16, "normal") == 80
    check(ok, "정수 연산 margin")
    print(f"  {'PASS' if ok else 'FAIL'}  정수 연산만 사용 — margin(1024, 16, normal) = "
          f"{resolve_margin(1024, 16, 'normal')}")


def test_capability() -> None:
    section("capability — 지원하지 않는 비율은 계산 전에 거부")

    for ratio in ("3:4", "3:1"):
        raised = None
        try:
            resolve_grid(spec_with(ratio=ratio))
        except RatioUnsupported as exc:
            raised = exc
        except Exception as exc:  # noqa: BLE001
            raised = exc
        ok = isinstance(raised, RatioUnsupported)
        check(ok, f"{ratio} → RatioUnsupported (실제 {type(raised).__name__})")
        print(f"  {'PASS' if ok else 'FAIL'}  {ratio} → {type(raised).__name__}: "
              f"{getattr(raised, 'code', '')}")

    # capability 를 넓히면 계산 자체는 돌아간다 — 규칙이 하드코딩이 아니다.
    # 다만 v1 의 축 규칙은 1:1 전용이므로 기본 context 로는 계속 막힌다
    ctx = ValidationContext(supported_ratios=("1:1", "3:4"))
    grid = resolve_grid(spec_with(ratio="3:4"), CanvasSize(768, 1024), ctx)
    check(grid.canvas_width == 768 and grid.canvas_height == 1024, "3:4 캔버스 축")
    check(grid.short_side == 768, "3:4 short_side 는 폭")
    check(grid.margin_x == grid.margin_y, "v1 은 두 축 여백이 같다")
    print(f"  PASS  capability 확장 시 3:4 계산 — {grid.canvas_width}×{grid.canvas_height} "
          f"short {grid.short_side} · margin_x {grid.margin_x} / margin_y {grid.margin_y}")
    print(f"        (축 분리 자료구조 확인용.  v1 기본 context 에서는 계속 거부된다)")

    # 선언 비율과 실제 캔버스가 다르면 거부
    raised = None
    try:
        resolve_grid(spec_with(ratio="1:1"), CanvasSize(1024, 768))
    except GridUnresolvable as exc:
        raised = exc
    ok = raised is not None and raised.code == "grid.canvas_ratio_mismatch"
    check(ok, "비율과 캔버스 불일치 거부")
    print(f"  {'PASS' if ok else 'FAIL'}  1:1 선언 + 1024×768 캔버스 → "
          f"{getattr(raised, 'code', 'None')}")


def test_failures() -> None:
    section("실패 정책 — 자동 보정 없음")

    # ① baseline 후보 없음 — 1021 은 소수라 8~32 약수가 없다
    raised = None
    try:
        resolve_grid(spec_with(), CanvasSize(1021, 1021))
    except GridUnresolvable as exc:
        raised = exc
    ok = raised is not None and raised.code == "grid.no_baseline_candidate"
    check(ok, "baseline 후보 없음")
    print(f"  {'PASS' if ok else 'FAIL'}  1021×1021 (소수) → {getattr(raised, 'code', 'None')}")
    check(baseline_candidates(1021) == (), "1021 은 후보가 없다")

    # ② 정수 정합 거터 해 없음 — 64px 캔버스에 12단
    raised = None
    try:
        resolve_grid(spec_with(columns=12), CanvasSize(64, 64))
    except GridUnresolvable as exc:
        raised = exc
    ok = raised is not None and raised.code == "grid.gutter_unresolvable"
    check(ok, "거터 정수해 없음")
    print(f"  {'PASS' if ok else 'FAIL'}  64×64 · 12단 → {getattr(raised, 'code', 'None')}")

    # ③ content <= 0 — 여백이 캔버스를 덮는다
    for axis, kwargs in (
        ("가로", dict(margin_x=600, margin_y=80)),
        ("세로", dict(margin_x=80, margin_y=600)),
    ):
        raised = None
        try:
            build_grid(
                canvas_width=1024,
                canvas_height=1024,
                short_side=1024,
                columns=6,
                baseline_px=16,
                target_gutter=24,
                **kwargs,
            )
        except GridUnresolvable as exc:
            raised = exc
        ok = raised is not None and raised.code == "grid.content_empty"
        check(ok, f"content_empty ({axis})")
        print(f"  {'PASS' if ok else 'FAIL'}  {axis} 여백이 캔버스를 덮음 → "
              f"{getattr(raised, 'code', 'None')}")

    # col_w <= 0 은 탐색 불변식(col_w ≥ 1)이 막으므로 도달하지 않는다.
    # 관측되는 실패는 gutter_unresolvable 하나다 — 가드는 방어적으로만 남긴다
    raised = None
    try:
        resolve_gutter(content_w=4, columns=6, target=2)
    except GridUnresolvable as exc:
        raised = exc
    ok = raised is not None and raised.code == "grid.gutter_unresolvable"
    check(ok, "col_w<1 상황은 gutter_unresolvable 로 나온다")
    print(f"  {'PASS' if ok else 'FAIL'}  content 4px · 6단 (col_w 확보 불가) → "
          f"{getattr(raised, 'code', 'None')}")

    # 금지 사항 확인 — 실패했을 때 값이 나오지 않는다
    fell_back = False
    try:
        resolve_grid(spec_with(columns=12), CanvasSize(64, 64))
        fell_back = True
    except GridUnresolvable:
        pass
    check(not fell_back, "실패 시 임의 기본값을 돌려주지 않는다")
    print(f"  {'PASS' if not fell_back else 'FAIL'}  실패 시 기본값 fallback 없음 "
          "(가까운 값 보정 · columns 변경 · ratio 변환 전부 없음)")


def test_determinism() -> None:
    section("결정론")

    spec = spec_with()
    first = resolve_grid(spec).as_dict()
    same = all(resolve_grid(spec).as_dict() == first for _ in range(50))
    check(same, "반복 호출 동일")
    print(f"  {'PASS' if same else 'FAIL'}  같은 Spec 50회 호출 → 동일 결과")

    # 전체 조합 스윕 — 값이 바뀌면 renderer_version 을 올려야 한다
    rows = []
    for columns in (4, 6, 8, 12):
        for margin in ("tight", "normal", "loose"):
            for gutter in ("tight", "normal", "loose"):
                for baseline in ("fine", "normal", "coarse"):
                    key = f"{columns}/{margin}/{gutter}/{baseline}"
                    try:
                        g = resolve_grid(spec_with(columns, margin, gutter, baseline))
                        rows.append((key, g.as_dict()))
                        check(g.check_integer_exact(), f"정수 정합 {key}")
                    except GridUnresolvable as exc:
                        rows.append((key, {"error": exc.code}))

    payload = json.dumps(rows, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    solved = sum(1 for _, v in rows if "error" not in v)
    print(f"  PASS  108개 조합 스윕 — 해결 {solved} / 거부 {len(rows) - solved}")
    print(f"        digest {digest}")
    if SWEEP_DIGEST != "PLACEHOLDER":
        ok = digest == SWEEP_DIGEST
        check(ok, f"스윕 digest: 기대 {SWEEP_DIGEST} / 실제 {digest}")
        print(f"  {'PASS' if ok else 'FAIL'}  스윕 digest 고정")

    check(solved == len(rows), f"1024 캔버스에서는 108개 조합이 전부 풀려야 한다: {solved}")

    # 정수 정합이 전 조합에서 성립하는가
    bad = [k for k, v in rows if "error" not in v
           and v["content_x1"] - v["content_x0"]
           != v["col_w"] * v["columns"] + v["gutter_px"] * (v["columns"] - 1)]
    check(not bad, f"정수 정합 위반: {bad}")
    print(f"  {'PASS' if not bad else 'FAIL'}  108개 조합 전부 정수 정합")


def test_axis_separation() -> None:
    section("축 분리 — ResolvedGrid 구조")

    grid = resolve_grid(spec_with())
    required = (
        "canvas_width", "canvas_height", "short_side", "baseline_px",
        "margin_x", "margin_y", "gutter_px", "col_w",
        "content_x0", "content_x1", "content_y0", "content_y1", "rows",
    )
    missing = [f for f in required if not hasattr(grid, f)]
    check(not missing, f"필드 누락: {missing}")
    print(f"  {'PASS' if not missing else 'FAIL'}  요구 필드 {len(required)}개 전부 존재")

    frozen = False
    try:
        grid.col_w = 200  # type: ignore[misc]
    except Exception:
        frozen = True
    check(frozen, "ResolvedGrid 는 frozen")
    print(f"  {'PASS' if frozen else 'FAIL'}  ResolvedGrid frozen")

    # rows 는 세로 축에서만 나온다
    check(grid.rows == grid.canvas_height // grid.baseline_px, "rows 는 canvas_height 기준")
    print(f"  PASS  rows = canvas_height {grid.canvas_height} // baseline {grid.baseline_px} "
          f"= {grid.rows}")


def test_scope_and_isolation() -> None:
    section("범위 · production 분리")

    import dynamic.grid as g

    src = open(g.__file__, encoding="utf-8").read()
    bad = [
        line.strip()
        for line in src.splitlines()
        if line.strip().startswith(("import pipeline", "from pipeline", "import api", "from api"))
    ]
    check(not bad, f"production import: {bad}")
    print(f"  {'PASS' if not bad else 'FAIL'}  dynamic.grid production import 없음")

    loaded = [n for n in sys.modules if n == "pipeline" or n.startswith("pipeline.")]
    check(not loaded, f"pipeline 로드됨: {loaded}")
    print(f"  {'PASS' if not loaded else 'FAIL'}  sys.modules 에 pipeline 없음")

    # Step 3 이후 기능이 섞여 들어오지 않았는지 — 좌표 해석 API 가 없어야 한다
    leaked = [n for n in dir(g) if n in ("col_x", "row_y", "resolve_anchor", "build_plan")]
    check(not leaked, f"Step 3 기능 유입: {leaked}")
    print(f"  {'PASS' if not leaked else 'FAIL'}  좌표/anchor 해석 API 없음 (Step 3 범위)")


def main() -> int:
    print("=" * 72)
    print("Grid Resolver 테스트 — E12 v0.3 Step 2")
    print("=" * 72)

    test_adc_reference()
    test_density_table()
    test_baseline_scale()
    test_tie_breaks()
    test_capability()
    test_failures()
    test_determinism()
    test_axis_separation()
    test_scope_and_isolation()

    print("\n" + "=" * 72)
    if FAILS:
        print(f"실패 {len(FAILS)} / 검사 {CHECKS}")
        for f in FAILS:
            print(f"  ✗ {f}")
        return 1
    print(f"전체 통과 — 검사 {CHECKS}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

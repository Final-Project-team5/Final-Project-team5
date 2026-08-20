"""schema 0.5 경로 테스트 — 팀 spec → CreativeBrief → RenderSpec → Plan.

**LLM 호출 없음 · 네트워크 없음 · 결정성만 본다.**

다섯 경로를 같은 방식으로 통과시킨다.

    A  product  + 배경 참고 없음              background_context = None
    B  product  + 배경 참고 있음 (usable)      6개 확인 필드가 프롬프트에 실린다
    C  product  + 배경 참고 못 씀 (usable=False) 한 필드도 실리지 않는다
    D  product  + 사용자 선호색 (preferred)     palette.source=preferred 가 돈다
    E  service  + generated 배경               업종이 달라도 같은 계약이다

이 파일이 지키는 것은 하나다 — **같은 입력이면 같은 결과가 나온다.**
adapter 든 resolver 든 어디선가 dict 순회 순서나 임의 기본값이 끼면
여기서 깨진다.

실행:  python tests/test_schema_05_paths.py
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dynamic import (  # noqa: E402
    SCHEMA_VERSION,
    PlannerInput,
    ServiceRequest,
    background_context_from_team,
    load,
    normalize_preferred_color,
    resolve_palette,
    service_request_from_team_spec,
    to_creative_brief,
)
from dynamic.planner_io import TEAM_SPEC_EXCLUDED  # noqa: E402
from dynamic.planner_prompt import build_user_prompt  # noqa: E402
from fixtures_renderspec import FIXTURES, brief as fixture_brief  # noqa: E402

FAILS: list[str] = []
CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILS.append(label)


def section(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 62 - len(title)))


def report(cond: bool, line: str) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {line}")


# ──────────────────────────────────────────────────────────────────────────
# 팀이 실제로 만드는 spec 모양 (E21 §1)
# ──────────────────────────────────────────────────────────────────────────
def team_spec(**over) -> dict:
    spec = {
        "business_type": "product",
        "category": "beauty",
        "purpose": "promotion",              # ← 가져오지 않는다
        "aspect_ratio": "1:1",
        "product": "독도토너 1025",
        "product_context": {
            "product": "토너",
            "vision_product": "토너",
            "detected_category": "beauty",
            "category_match": True,
            "visible_features": ["투명 용기", "미니멀 라벨"],
            "visible_text": ["1025"],
            "recognition_status": "clear",    # ← 가져오지 않는다
            "next_action": "auto_fill",       # ← 가져오지 않는다
            "confirmed_product": "독도토너 1025",
            "confirmation_source": "vision_confirmed",
        },
        "background_context": None,
        "purpose_locked": True,
        "purpose_invalid": False,
    }
    spec.update(over)
    return spec


TEAM_BACKGROUND = {
    "palette": ["웜 베이지", "딥 그린"],       # ★ 자연어. HEX 아님
    "lighting": "부드러운 자연광",
    "texture": ["매트한 종이"],
    "mood": "차분하고 고급스러운",
    "composition": "중앙 여백이 넓은 미니멀 구성",
    "usable": True,
}


def request_for(path: str) -> ServiceRequest:
    """다섯 경로의 입력. **차이는 배경/선호색 축 하나뿐이다.**"""
    base = fixture_brief()
    spec = team_spec()
    kw = dict(
        tone="minimal_product",
        keywords=("수분", "신제품"),
        request="밝고 깨끗한 느낌으로",
        copy=base.copy,
        product_signals=base.product_signals,
    )

    if path == "A":
        pass
    elif path == "B":
        spec = team_spec(background_context=dict(TEAM_BACKGROUND))
    elif path == "C":
        spec = team_spec(background_context=dict(TEAM_BACKGROUND, usable=False))
    elif path == "D":
        kw["preferred_color"] = "#2E6F5E"
    elif path == "E":
        spec = team_spec(business_type="service", category="cafe",
                         background_context=dict(TEAM_BACKGROUND))
        kw["visual_style"] = "realistic"
    else:
        raise ValueError(path)

    return service_request_from_team_spec(spec, **kw)


PATHS = {
    "A": "product · 배경 참고 없음",
    "B": "product · 배경 참고 있음 (usable)",
    "C": "product · 배경 참고 못 씀 (usable=False)",
    "D": "product · 사용자 선호색",
    "E": "service · generated 배경",
}


# ──────────────────────────────────────────────────────────────────────────
def test_adapter_excludes() -> None:
    section("① adapter — 가져오지 않기로 한 값은 넘어오지 않는다")

    brief = to_creative_brief(request_for("B"))
    blob = json.dumps(dataclasses.asdict(brief), ensure_ascii=False, default=str)

    # 제품 확정 **이전** flow control 값. 넘어오면 Planner 가 그걸 보고
    # 디자인을 바꿀 수 있다 — 확정 이후에만 시작한다는 계약이 깨진다
    leaked = [tok for tok in ("auto_fill", "clear", "promotion") if f'"{tok}"' in blob]
    check(not leaked, f"제외 값 유입: {leaked}")
    report(not leaked, f"{len(TEAM_SPEC_EXCLUDED)}개 제외 계약 · 유입 {leaked or '없음'}")
    for key, why in TEAM_SPEC_EXCLUDED.items():
        print(f"        {key:38} {why}")

    ok = brief.product_identity.confirmed_product == "독도토너 1025"
    check(ok, "confirmed_product 는 문자열 그대로")
    report(ok, f"spec['product'] → confirmed_product = "
               f"{brief.product_identity.confirmed_product!r} (문자열 · E21 §1-1)")

    ok = brief.output_ratio == "1:1"
    check(ok, "aspect_ratio → output_ratio")
    report(ok, "aspect_ratio → output_ratio 로 이름만 갈아탄다")


def test_background_paths() -> None:
    section("② 배경 참고 — usable 이 아니면 한 필드도 새지 않는다")

    for path in ("A", "B", "C", "E"):
        pin = PlannerInput.of(to_creative_brief(request_for(path)))
        user = build_user_prompt(pin)
        status = pin.background_context_status
        expected = {"A": "absent", "B": "present", "C": "unusable", "E": "present"}[path]

        ok = status == expected
        check(ok, f"{path}: status={status}")
        report(ok, f"{path}  {PATHS[path]:<34} status = {status!r}")

        if path == "C":
            # ★ 못 쓴다고 표시된 분석에서 일부만 골라 쓰지 않는다
            leaked = [v for v in ("웜 베이지", "부드러운 자연광", "차분하고 고급스러운",
                                  "매트한 종이", "중앙 여백") if v in user]
            check(not leaked, f"unusable 유출: {leaked}")
            report(not leaked, f"      usable=False → 유출 {leaked or '없음'} "
                               "(일부만 살려 쓰지 않는다)")
        if path in ("B", "E"):
            # ★ palette 는 자연어 그대로. HEX 로 바꾸면 다른 값이 된다
            ok = "웜 베이지" in user and "#" not in "".join(
                pin.brief.background_context.palette)
            check(ok, f"{path}: palette 자연어 유지")
            report(ok, "      palette 를 자연어 그대로 전달 — 색 계산 입력이 아니다")


def test_preferred_color_branch() -> None:
    section("③ palette.source = preferred — 독립 branch")

    brief = to_creative_brief(request_for("D"))
    spec_raw = FIXTURES["A"][1]()
    spec_raw["palette"] = dict(spec_raw["palette"], source="preferred")
    spec = load(spec_raw, brief)
    pal = resolve_palette(spec, brief)

    ok = pal.source == "preferred"
    check(ok, "preferred 로 해석된다")
    report(ok, f"source={pal.source} · base_hue={pal.base_hue} · "
               f"colors={ {k: pal.hex(k) for k in sorted(pal.colors)} }")

    # ★ 선호색이 그대로 bg 가 되는 것이 아니다 — seed 다
    ok = pal.hex("bg") != "#2E6F5E"
    check(ok, "선호색을 그대로 칠하지 않는다")
    report(ok, f"preferred_color=#2E6F5E → bg={pal.hex('bg')} "
               "(seed 이지 최종 RGB 지시가 아니다)")

    # ★ 무채색을 골라도 accent 로 갈아치우지 않는다 (E16 §Q3-2)
    gray = dataclasses.replace(brief, preferred_color="#808080")
    gray_pal = resolve_palette(load(spec_raw, gray), gray)
    product_pal = resolve_palette(
        load(dict(spec_raw, palette=dict(spec_raw["palette"], source="product")), brief),
        brief)
    ok = gray_pal.base_hue != product_pal.base_hue
    check(ok, "무채색 fallback 없음")
    report(ok, f"무채색 선호색 → base_hue={gray_pal.base_hue} · "
               f"product 경로 base_hue={product_pal.base_hue} "
               "(accent 로 갈아치우지 않는다)")

    # ★ 선호색이 없는데 preferred 를 고르면 거부한다
    no_color = dataclasses.replace(brief, preferred_color=None)
    errs = []
    try:
        load(spec_raw, no_color)
    except Exception as exc:                       # SpecInvalid 묶음
        errs = [e.code for e in getattr(exc, "errors", [])] or [type(exc).__name__]
    ok = "palette.preferred_color_missing" in errs
    check(ok, f"거부 코드: {errs}")
    report(ok, f"선호색 없이 source=preferred → {errs} "
               "(product 로 조용히 넘어가지 않는다)")


def test_determinism() -> None:
    section("④ 결정성 — 같은 입력이면 같은 결과")

    for path in PATHS:
        req = request_for(path)
        a, b = to_creative_brief(req), to_creative_brief(req)
        ok = dataclasses.asdict(a) == dataclasses.asdict(b)
        check(ok, f"{path}: adapter 결정성")

        p1 = build_user_prompt(PlannerInput.of(a))
        p2 = build_user_prompt(PlannerInput.of(b))
        ok_prompt = p1 == p2
        check(ok_prompt, f"{path}: 프롬프트 결정성")

        # 색까지 확정해 본다 — 여기가 흔들리면 같은 브리프로 다른 포스터가 나온다
        raw = FIXTURES["A"][1]()
        if a.preferred_color:
            raw["palette"] = dict(raw["palette"], source="preferred")
        spec = load(raw, a)
        ok_color = resolve_palette(spec, a).as_dict() == resolve_palette(spec, a).as_dict()
        check(ok_color, f"{path}: palette 결정성")

        report(ok and ok_prompt and ok_color,
               f"{path}  {PATHS[path]:<34} brief · prompt · palette 모두 동일")


def test_version_and_boundary() -> None:
    section("⑤ 버전과 경계")

    ok = SCHEMA_VERSION == "0.5"
    check(ok, "schema_version")
    report(ok, f"SCHEMA_VERSION = {SCHEMA_VERSION}")

    # 팀 payload 에 모르는 key 가 섞여도 신뢰하지 않는다
    ctx = background_context_from_team(
        dict(TEAM_BACKGROUND, dominant="#EFEAE3", saturation=0.4))
    ok = sorted(ctx.unconfirmed) == ["dominant", "saturation"]
    check(ok, "모르는 key 는 unconfirmed 로")
    report(ok, f"확인 안 된 key {sorted(ctx.unconfirmed)} → 보존만 하고 "
               "프롬프트로 내보내지 않는다")

    ok = normalize_preferred_color(None) is None
    check(ok, "선호색 없음은 정상")
    report(ok, "preferred_color 없음 → None (기본색을 만들지 않는다)")

    ok = "pipeline" not in sys.modules and "api" not in sys.modules
    check(ok, "production 미import")
    report(ok, "sys.modules 에 pipeline / api 없음")


def main() -> int:
    print("=" * 72)
    print("schema 0.5 경로 테스트 — 팀 spec → CreativeBrief → RenderSpec → Plan")
    print("=" * 72)

    test_adapter_excludes()
    test_background_paths()
    test_preferred_color_branch()
    test_determinism()
    test_version_and_boundary()

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

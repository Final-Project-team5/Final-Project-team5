"""Safety Validator — Step 6.

    RenderSpec.safety(무엇이 중요한가)  ×  SystemPolicy(최소 얼마나 안전한가)
              ×  RenderEvidence(실제로 무엇이 그려졌는가)
                          ↓
                     SafetyResult

**판정하는 계층이지 고치는 계층이 아니다.** 대비를 올리거나 문구를 옮기거나
제품을 줄이지 않는다. 자동 수정/재시도 정책은 Planner 를 연결할 때 별도로
설계한다.

측정 원칙 두 가지

  ① **bbox 겹침을 글자 가림으로 쓰지 않는다.**
     텍스트 bbox 는 획보다 훨씬 넓은 빈 공간을 품는다. bbox 의 50% 가 제품과
     겹쳐도 실제 획은 10% 만 덮였을 수 있다. 그래서
         overlap_intent 검사   → bbox / 기하로 충분
         핵심 가림 검사        → **실제 잉크 마스크** 기준
     로 목적을 나눈다.

  ② **layer 에 따라 재는 것이 다르다** (E11 §3 의 교훈).
         type_under → 제품이 획을 얼마나 덮었나   = 가림
         type_over  → 글자 자리의 실제 바탕과의 대비 = 대비
     제품 위에 있는 글자를 "가려졌다"고 재면 늘 100% 가 나온다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np

from .errors import EvidenceMismatch
from .evidence import ElementEvidence, RenderEvidence
from .palette import relative_luminance
from .plan import RenderPlan
from .policy import DEFAULT_POLICY, DEFERRED_CHECKS, SystemPolicy
from .render import RENDERER_VERSION

FAIL = "fail"
WARN = "warn"

#: `SafetyResult.passed` 가 뜻하는 것 — **넓게 읽지 않는다.**
#:
#:   ○ 현재 구현되어 **실제 수행된** 검사에서 FAIL 이 없었다
#:   ✗ 지원하지 않는 검사와 보류 검사까지 포함해 모든 안전성이 증명됐다
#:
#: 그래서 `unsupported` / `deferred` 를 결과에 함께 실어, 호출자가 커버리지
#: 공백을 별도로 볼 수 있게 한다.
PASSED_SCOPE = (
    "현재 구현되어 실제 수행된 검사에서 FAIL 이 없었다는 뜻이다. "
    "unsupported_checks / deferred_checks 는 검사되지 않았으므로 "
    "'모든 안전성이 증명됐다'로 읽지 않는다."
)


#: `Violation.detail` 계약 — **observation-only.**
#:
#: detail 은 두 가지만 담는다.
#:   ① 무엇이 관측됐는가      "none 을 선언했는데 실제 2D 교집합이 있다"
#:   ② 무엇을 어떻게 쟀는가    "보이는 획 아래 실제 바탕과의 대비 하위 5%"
#:
#: 담지 않는 것 — 해결 방법. "글자를 줄여라" · "제품을 옮겨라" · "색을 바꿔라"
#: 는 Design Planner 의 몫이다. Safety 가 처방하면 디자인 결정을 가로챈다.
#:
#: 이 계약 덕분에 detail 을 SafetyFeedback 으로 Planner 에 그대로 실어 보낼 수
#: 있다 (prompt v1.4). **새 Safety rule 을 추가할 때도 같은 계약을 지킨다** —
#: `test_safety.py` 의 detail 회귀가 등록되지 않은 새 문구를 발견하면 실패하므로,
#: 사람이 관측 서술인지 확인하고 등록해야 한다.
DETAIL_CONTRACT = "observation-only — 관측 사실과 측정 방식만. 처방 없음"


@dataclass(frozen=True)
class Violation:
    """무엇이 왜 실패했는가 — **객관적 근거만.**

    해결 방법은 담지 않는다. "색을 흰색으로", "제품을 옮겨라" 같은 처방은
    Design Planner 의 몫이다. Validator 가 처방까지 하면 디자인 결정을
    가로채는 것이 된다.
    """

    code: str
    severity: str
    element_id: str
    element_kind: str          # "copy" | "motif" | "product" | "zones"
    measured: float
    threshold: float
    layer: str = ""            # 요소가 속한 레이어
    relation: str = ""         # 제품과의 관계: type_over | type_under | ""
    detail: str = ""           # 무엇을 쟀는지 설명 (처방 아님)

    @property
    def target(self) -> str:
        return f"{self.element_kind}[{self.element_id}]"

    def __str__(self) -> str:
        rel = f" ({self.relation})" if self.relation else ""
        return (f"[{self.severity.upper()}] {self.code} @ {self.target}{rel} "
                f"— 측정 {self.measured} / 기준 {self.threshold}"
                + (f" · {self.detail}" if self.detail else ""))

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "element_id": self.element_id,
            "element_kind": self.element_kind,
            "layer": self.layer,
            "relation": self.relation,
            "measured": self.measured,
            "threshold": self.threshold,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class SafetyResult:
    passed: bool
    violations: Tuple[Violation, ...]
    measurements: dict
    deferred: Tuple[str, ...] = ()
    unsupported: Tuple[str, ...] = ()   # 지원하지 않아 **건너뛴** 검사 (조용히 넘기지 않는다)

    @property
    def failures(self) -> Tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity == FAIL)

    @property
    def warnings(self) -> Tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity == WARN)

    @property
    def codes(self) -> Tuple[str, ...]:
        return tuple(v.code for v in self.violations)

    def has(self, code: str) -> bool:
        return code in self.codes

    def for_planner(self) -> dict:
        """Planner 에 그대로 넘길 수 있는 구조.

        **실패 사실과 근거만** 담는다. 어떻게 고칠지는 여기 없다.

        `passed` 의 의미는 `PASSED_SCOPE` 그대로다 — 넓게 읽지 않도록
        payload 에도 함께 싣는다.
        """
        return {
            "passed": self.passed,
            "passed_scope": PASSED_SCOPE,
            "violations": [v.as_dict() for v in self.violations],
            "policy": self.measurements.get("policy", {}),
            "plan_digest": self.measurements.get("plan_digest"),
            "renderer_version": self.measurements.get("renderer_version"),
            "unsupported_checks": list(self.unsupported),
            "deferred_checks": list(self.deferred),
        }

    def report(self) -> str:
        head = "PASS" if self.passed else f"FAIL ({len(self.failures)}건)"
        lines = [f"SafetyResult {head}"] + [f"  {v}" for v in self.violations]
        if self.unsupported:
            lines += [f"  (미지원) {u}" for u in self.unsupported]
        if self.deferred:
            lines += [f"  (보류) {d}" for d in self.deferred]
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────
# 측정 헬퍼 — 전부 **실제 렌더 근거**에서 나온다
# ──────────────────────────────────────────────────────────────────────────
def ink_occlusion(el: ElementEvidence, product_alpha: np.ndarray) -> float:
    """제품이 이 요소의 **획**을 덮은 비율. bbox 가 아니라 잉크 기준이다."""
    total = el.ink_px
    if not total:
        return 0.0
    return float((el.ink & product_alpha).sum()) / total


def char_occlusions(el: ElementEvidence, product_alpha: np.ndarray) -> Tuple[float, ...]:
    """글자 하나 단위 가림 비율. '핵심 글자가 가려졌다'를 잡기 위한 것."""
    out = []
    for x0, y0, x1, y1 in el.char_boxes:
        sub_ink = el.ink[max(0, y0):y1, max(0, x0):x1]
        n = int(sub_ink.sum())
        if n == 0:
            continue
        sub_prod = product_alpha[max(0, y0):y1, max(0, x0):x1]
        out.append(float((sub_ink & sub_prod).sum()) / n)
    return tuple(out)


def contrast_of(fg: Tuple[int, int, int], bg_pixels: np.ndarray, percentile: int) -> float:
    """글자 자리에 **실제로 깔려 있던** 픽셀들과의 대비.

    팔레트 값끼리 비교하지 않는다 — 그라데이션이나 제품 위에서는 자리마다
    바탕이 다르다. 가장 나쁜 한 픽셀은 앤티앨리어싱 잡음일 수 있어
    하위 백분위(기본 5%)로 본다. 그 기준도 SystemPolicy 에 있다.
    """
    if bg_pixels is None or len(bg_pixels) == 0:
        return float("inf")
    lf = relative_luminance(tuple(int(c) for c in fg))
    srgb = bg_pixels.astype(np.float64) / 255.0
    lin = np.where(srgb <= 0.03928, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
    lb = lin @ np.array([0.2126, 0.7152, 0.0722])
    hi = np.maximum(lb, lf)
    lo = np.minimum(lb, lf)
    ratios = (hi + 0.05) / (lo + 0.05)
    return float(round(np.percentile(ratios, percentile), 2))


def outside_canvas(bbox, width: int, height: int) -> dict:
    x0, y0, x1, y1 = bbox
    return {
        "left": max(0, -x0),
        "top": max(0, -y0),
        "right": max(0, x1 - width),
        "bottom": max(0, y1 - height),
    }


# ──────────────────────────────────────────────────────────────────────────
# 검사
# ──────────────────────────────────────────────────────────────────────────
def _check_overlap_intent(plan, out, m) -> None:
    """겹침 **의도**만 본다. 누가 위인지는 layer 가 정하고 여기서 안 본다.

    여기서는 bbox 기반 2D 관계로 충분하다 — "겹쳤는가"는 기하 문제다.
    """
    rel = plan.type_product_relation()
    m["overlap"] = {"declared": rel["declared"], "overlap_px": rel["overlap_px"],
                    "summary": rel["summary"], "per_block": rel["per_block"]}
    intent = rel["declared"]
    if intent == "none" and rel["overlap_px"] > 0:
        out.append(Violation(
            code="safety.overlap_declared_none", severity=FAIL,
            element_id="overlap_intent", element_kind="zones",
            measured=rel["overlap_px"], threshold=0,
            detail="none 을 선언했는데 실제 2D 교집합이 있다"))
    if intent == "required" and rel["overlap_px"] == 0:
        out.append(Violation(
            code="safety.overlap_required_absent", severity=FAIL,
            element_id="overlap_intent", element_kind="zones",
            measured=0, threshold=1,
            detail="required 를 선언했는데 실제 겹침이 없다 (선언-강제)"))
    # allowed — 겹침 유무로 판정하지 않는다. 개별 규칙만 적용된다


def _check_copy_blocks(plan, ev, policy, out, m, unsupported) -> None:
    product_index = plan.layers.index("product")
    critical = set(plan.critical_blocks)
    m["blocks"] = {}

    for el in ev.of_kind("copy"):
        block = next((b for b in plan.copy_blocks if b.id == el.id), None)
        if block is None:
            continue
        above = plan.layers.index(el.layer) > product_index
        relation = "type_over" if above else "type_under"
        is_critical = el.id in critical
        entry = {
            "layer": el.layer,
            "relation": relation,
            "above_product": above,
            "critical": is_critical,
            "orientation": block.orientation,
            "size_px": el.size_px,
            "weight": el.weight,
            "ink_px": el.ink_px,
            "visible_ink_px": el.visible_px,
            "large_text": policy.is_large_text(el.size_px, el.weight),
        }

        def flag(code, severity, measured, threshold, detail):
            out.append(Violation(
                code=code, severity=severity, element_id=el.id, element_kind="copy",
                layer=el.layer, relation=relation,
                measured=measured, threshold=threshold, detail=detail))

        if not above:
            # ── type_under → **획 가림**을 잰다
            occ = ink_occlusion(el, ev.product_alpha)
            entry["ink_occlusion"] = round(occ, 4)
            entry["checked"] = "occlusion"
            limit = policy.critical_occlusion_max if is_critical else policy.block_occlusion_max
            if occ > limit:
                flag("safety.critical_occlusion" if is_critical else "safety.block_occlusion",
                     FAIL if is_critical else WARN, round(occ, 4), limit,
                     f"제품이 실제 획의 {occ:.1%} 를 덮었다 (bbox 아님)")

            # 글자 단위는 **가로쓰기만** 지원한다 (§15-7)
            if block.orientation == "horizontal":
                chars = char_occlusions(el, ev.product_alpha)
                worst = max(chars) if chars else 0.0
                entry["worst_char_occlusion"] = round(worst, 4)
                entry["char_check"] = "supported"
                if worst > policy.char_occlusion_max:
                    flag("safety.char_occlusion", FAIL if is_critical else WARN,
                         round(worst, 4), policy.char_occlusion_max,
                         f"가장 많이 가린 글자 {worst:.1%} — 글자가 읽히지 않는다")
            else:
                entry["worst_char_occlusion"] = None
                entry["char_check"] = f"unsupported:{block.orientation}"
                unsupported.append(
                    f"safety.char_occlusion @ copy[{el.id}] — "
                    f"{block.orientation} 는 글자 상자를 신뢰할 수 없어 건너뛴다 "
                    "(블록 단위 가림은 검사함)"
                )
        else:
            entry["checked"] = "contrast"

        # ── 대비는 **최종 화면에 남은 획**만 대상으로 한다.
        #    이미 제품에 덮인 획으로 재면 보이지도 않는 글자의 가독성을 재게 된다
        need = policy.contrast_min_for(el.size_px, el.weight)
        sample = el.visible_under()
        entry["contrast_min"] = need
        entry["contrast_sample_px"] = 0 if sample is None else int(len(sample))

        if el.visible_px == 0:
            entry["contrast"] = None
            flag("safety.block_fully_occluded", FAIL if is_critical else WARN,
                 0.0, 1.0, "최종 화면에 남은 획이 없다 — 대비를 잴 대상 자체가 없다")
        else:
            got = contrast_of(el.color, sample, policy.contrast_percentile)
            entry["contrast"] = got
            if got < need:
                flag("safety.text_contrast", FAIL, got, need,
                     f"{'큰' if entry['large_text'] else '작은'} 글자"
                     f"({el.size_px}px {el.weight}) — 보이는 획 아래 실제 바탕과의 대비 "
                     f"하위 {policy.contrast_percentile}%")

        m["blocks"][el.id] = entry


def _check_must_be_visible(plan, ev, policy, out, m) -> None:
    """선언한 요소가 **실제 결과에 남아 있는가.**

    RenderPlan 에 이름이 있다는 이유로 통과시키지 않는다. 뒤에 그려진 것에
    덮이거나 캔버스 밖으로 나갔으면 실패다.

    ★ v0.4 — 대상은 motif role **과 copy block id** 다. evidence 의 id
    이름공간이 원래 평면이라 측정은 예전부터 가능했다. `element_kind` 를
    "motif" 로 박아 두면 copy block 을 재고도 motif 라고 보고하게 된다 —
    무엇을 쟀는지 틀리게 적는 판정은 쓸 수 없으므로 evidence 의 kind 를 쓴다.
    """
    m["must_be_visible"] = {}
    for role in plan.must_be_visible:
        el = ev.by_id(role)
        if el is None:
            out.append(Violation(
                code="safety.must_be_visible_missing", severity=FAIL,
                element_id=role, element_kind="unknown", measured=0, threshold=1,
                detail="렌더 결과에 존재하지 않는다"))
            continue
        ratio = el.visible_ratio
        m["must_be_visible"][role] = {"kind": el.kind, "ink_px": el.ink_px,
                                      "visible_px": el.visible_px,
                                      "visible_ratio": round(ratio, 4), "layer": el.layer}
        if ratio < policy.motif_visible_min:
            out.append(Violation(
                code="safety.must_be_visible_occluded", severity=FAIL,
                element_id=role, element_kind=el.kind, layer=el.layer,
                measured=round(ratio, 4), threshold=policy.motif_visible_min,
                detail=f"{el.ink_px}px 중 {el.visible_px}px 만 남았다"))


def _check_overflow(plan, ev, policy, out, m) -> None:
    """선언된 bleed 외 캔버스 이탈. 텍스트·모티프는 허용 계약이 없다."""
    W, H = ev.canvas_width, ev.canvas_height
    m["overflow"] = {}
    allowed_product = set(plan.product.bleed)   # Spec 이 선언한 것만 허용된다

    for el in ev.elements:
        box = el.intended_bbox or el.bbox
        over = outside_canvas(box, W, H)
        sides = {k: v for k, v in over.items() if v > policy.canvas_overflow_max}
        if not sides:
            continue
        allowed = allowed_product if el.kind == "product" else set()
        bad = {k: v for k, v in sides.items() if k not in allowed}
        m["overflow"][el.id] = {"sides": sides, "allowed": sorted(allowed), "violating": bad}
        if bad:
            out.append(Violation(
                code="safety.canvas_overflow", severity=FAIL,
                element_id=el.id, element_kind=el.kind, layer=el.layer,
                measured=max(bad.values()), threshold=policy.canvas_overflow_max,
                detail=f"선언되지 않은 방향으로 벗어남: {bad}"
                       + (f" (허용: {sorted(allowed)})" if allowed else "")))


# ──────────────────────────────────────────────────────────────────────────
def check_integrity(plan: RenderPlan, evidence: RenderEvidence,
                    expected_renderer: Optional[str] = None) -> None:
    """이 근거가 **이 plan 에서 나온 것인지** 먼저 확인한다.

    다른 plan 의 evidence 로 판정하면 무엇을 판정한 것인지 알 수 없다.
    조용히 계속하지 않고 거부한다.
    """
    actual = plan.digest()
    if evidence.plan_digest != actual:
        raise EvidenceMismatch(
            "evidence.plan_mismatch", "RenderEvidence.plan_digest",
            f"이 plan 의 digest 는 {actual} 인데 근거는 {evidence.plan_digest} 에서 왔다",
        )
    expected = expected_renderer or RENDERER_VERSION
    if evidence.renderer_version != expected:
        raise EvidenceMismatch(
            "evidence.renderer_version_mismatch", "RenderEvidence.renderer_version",
            f"기대 {expected} / 근거 {evidence.renderer_version} — "
            "다른 Renderer 로 그린 결과를 현재 기준으로 판정하지 않는다",
        )


def validate_safety(
    plan: RenderPlan,
    evidence: RenderEvidence,
    policy: Optional[SystemPolicy] = None,
    expected_renderer: Optional[str] = None,
) -> SafetyResult:
    """실제 렌더 근거로 판정한다. **아무것도 고치지 않는다.**"""
    check_integrity(plan, evidence, expected_renderer)

    policy = policy or DEFAULT_POLICY
    violations: list = []
    unsupported: list = []
    measurements: dict = {"policy": policy.as_dict(),
                          "renderer_version": evidence.renderer_version,
                          "plan_digest": evidence.plan_digest}

    _check_overlap_intent(plan, violations, measurements)
    _check_copy_blocks(plan, evidence, policy, violations, measurements, unsupported)
    _check_must_be_visible(plan, evidence, policy, violations, measurements)
    _check_overflow(plan, evidence, policy, violations, measurements)

    passed = not any(v.severity == FAIL for v in violations)
    return SafetyResult(
        passed=passed,
        violations=tuple(violations),
        measurements=measurements,
        deferred=tuple(f"{k} — {v}" for k, v in DEFERRED_CHECKS.items()),
        unsupported=tuple(unsupported),
    )


__all__ = [
    "DETAIL_CONTRACT",
    "FAIL",
    "WARN",
    "PASSED_SCOPE",
    "Violation",
    "SafetyResult",
    "validate_safety",
    "check_integrity",
    "ink_occlusion",
    "char_occlusions",
    "contrast_of",
    "outside_canvas",
]

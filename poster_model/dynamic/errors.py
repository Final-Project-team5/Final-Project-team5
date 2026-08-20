"""RenderSpec 검증 에러.

설계 원칙 (E12 v0.3 §9) — **잘못된 Spec 을 조용히 보정하지 않는다.**
Renderer 까지 내려가기 전에 거부한다.

에러 *클래스*는 실패의 성격을 구분하고, `code` 는 어떤 규칙이 걸렸는지
가리킨다. 테스트는 `code` 로 단정한다 — 메시지 문구에 의존하지 않는다.
클래스를 늘리는 것 자체가 목적이 아니므로, 교차 필드 모순은 대부분
`SpecRejected` + 고유 code 로 표현한다.
"""

from __future__ import annotations


class SpecError(Exception):
    """모든 검증 에러의 기반 클래스. code / path / detail 을 들고 다닌다."""

    def __init__(self, code: str, path: str = "", detail: str = "") -> None:
        self.code = code
        self.path = path
        self.detail = detail
        super().__init__(str(self))

    def __str__(self) -> str:
        loc = f" at {self.path}" if self.path else ""
        det = f" — {self.detail}" if self.detail else ""
        return f"[{type(self).__name__}:{self.code}]{loc}{det}"

    def __repr__(self) -> str:  # pragma: no cover - 디버깅 편의
        return f"{type(self).__name__}(code={self.code!r}, path={self.path!r})"


class SchemaError(SpecError):
    """타입 · enum · 범위 · 필수 필드 누락 · 미지의 필드."""


class SpecRejected(SpecError):
    """교차 필드 모순. planner 경로의 정수 row index 도 여기 속한다."""


class RatioUnsupported(SpecError):
    """canvas.ratio 가 현재 Renderer 의 supported_ratios 밖 (§4-1).

    Renderer v1 은 1:1 만 지원한다. 근사·추정·자동 대체를 하지 않는다.
    """


class GridUnresolvable(SpecError):
    """정수 정합 격자 해가 없음 (§4-1).

    Step 1 에서는 발생하지 않는다 — Grid Resolver(Step 2) 용으로 예약.
    """


class AnchorUnresolvable(SpecError):
    """anchor 순환 · 전방 참조 · 미지의 대상 (§4-2)."""


class LayerUnassigned(SpecError):
    """요소에 layer 가 없거나 고정 스택 밖의 값 (§3-2 / H4)."""


class CriticalEmpty(SpecError):
    """safety.critical_blocks 가 비었다 (H3).

    무엇이 중요한지 디자인이 선언하지 않으면 판정할 수 없다.
    """


class CoordinateMixing(SpecError):
    """열 번호와 명명 영역을 한 grid_ref 에서 혼용 (§8-4)."""


class TrustBoundaryViolation(SpecError):
    """Planner 출력에 spec_source 가 들어왔다 (§4-2).

    경로는 신뢰된 호출자(server / test harness)가 정한다. Spec 이 자기
    경로를 선언하면 제약을 스스로 해제할 수 있으므로 무시하지 않고 거부한다.
    """


class ContentRefUnresolved(SpecError):
    """content_ref 가 CreativeBrief.copy 에서 해석되지 않음 (§5)."""


class ProductGeometryInvalid(SpecError):
    """ProductGeometry 입력이 스스로 모순이거나 비어 있다 (Step 3 입력 계약).

    geometry 는 상위 단계가 계산해 **명시적으로** 넘긴다. plan builder 가
    파일을 열어 직접 분석하거나 전역 상태에서 꺼내 오지 않는다.
    """


class RenderUnsupported(SpecError):
    """Renderer 가 처리할 수 없는 요구 (Step 4 capability).

    `background.mode = generated` 처럼 이 계층이 만들 수 없는 것은 **명시적으로
    거부**한다. production diffusion 경로를 몰래 호출하지 않는다.
    """


class RenderAssetInvalid(SpecError):
    """픽셀 asset 이 plan/geometry 와 맞지 않는다 (Step 4 입력 계약).

    Renderer 는 파일을 찾아 읽거나 마스킹을 다시 하지 않는다. 상위 계층이
    명시적으로 넘긴 것만 쓴다.
    """


class EvidenceMismatch(SpecError):
    """RenderEvidence 가 이 RenderPlan 에서 나온 것이 아니다 (Step 6).

    다른 plan 의 근거로 판정하면 "무엇을 판정한 것인지" 알 수 없다.
    조용히 계속하지 않고 거부한다.
    """


class PlannerOutputInvalid(SpecError):
    """LLM 출력이 계약 구조가 아니다 (Step 9).

    **고쳐서 파싱하지 않는다** — 앞뒤 텍스트를 잘라내거나 따옴표를 손보면
    "모델이 실제로 무엇을 냈는지" 를 알 수 없게 된다.
    """


class PlanUnresolvable(SpecError):
    """RenderPlan 을 만들 수 없다 (Step 3).

    측정·배치가 성립하지 않는 경우다 — 문구가 선언된 크기로 들어가지 않거나,
    zone 이 비었거나, 폰트가 없거나. **크기를 몰래 줄여 맞추지 않는다.**
    size_step 은 Planner 의 결정이므로 Renderer 가 바꾸면 디자인 결정을
    가로채는 것이 된다.
    """


class SpecInvalid(Exception):
    """검증 실패 묶음. 개별 에러를 모두 담아 한 번에 올린다."""

    def __init__(self, errors) -> None:
        self.errors: tuple[SpecError, ...] = tuple(errors)
        lines = "\n".join(f"  {e}" for e in self.errors)
        super().__init__(f"RenderSpec 검증 실패 {len(self.errors)}건\n{lines}")

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(e.code for e in self.errors)

    def has(self, code: str) -> bool:
        return code in self.codes


__all__ = [
    "SpecError",
    "SchemaError",
    "SpecRejected",
    "RatioUnsupported",
    "GridUnresolvable",
    "AnchorUnresolvable",
    "LayerUnassigned",
    "CriticalEmpty",
    "CoordinateMixing",
    "TrustBoundaryViolation",
    "ContentRefUnresolved",
    "ProductGeometryInvalid",
    "PlanUnresolvable",
    "RenderUnsupported",
    "RenderAssetInvalid",
    "EvidenceMismatch",
    "PlannerOutputInvalid",
    "SpecInvalid",
]

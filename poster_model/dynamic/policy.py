"""SystemPolicy — 최소 안전 기준 (E12 §7-4).

    RenderSpec(Planner)   "무엇이 중요한가"      critical_blocks · must_be_visible
    SystemPolicy(고정)     "최소 얼마나 안전한가"  ← 이 파일
    Validator             둘을 곱한다

**Planner 가 낮출 수 없다.** 그래서 Spec 이 아니라 여기 있다.

판정 기준은 전부 이 파일에 **명시**한다. Validator 안에 숨은 상수가 있으면
"왜 실패했는가"를 설명할 수 없고, 기준을 바꿀 때 어디를 고쳐야 할지도 모른다.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── large text 기준을 정한 근거 ───────────────────────────────────────────
#
# WCAG 는 **화면에 보이는 크기** 기준이다 (large = 18pt/24px regular,
# 14pt/18.66px bold @96dpi). 우리 캔버스는 1024px 이고 실제로는 축소돼 보인다.
# 그래서 "표시 크기" 가정을 명시하고 캔버스 px 로 환산한다.
#
#   가정   모바일 피드에서 짧은 변 480px 로 표시된다
#   환산   canvas_px = wcag_px × (1024 / 480) ≈ wcag_px × 2.133
#
#   regular  24px × 2.133 ≈ 51.2  →  52
#   bold     18.66px × 2.133 ≈ 39.8  →  40
#
# 가정을 바꾸면 이 두 수가 바뀐다. 그래서 가정 자체를 필드로 들고 있는다.
REFERENCE_DISPLAY_SHORT_SIDE = 480
WCAG_LARGE_REGULAR_PX = 24.0
WCAG_LARGE_BOLD_PX = 18.66

# 굵기가 이 이상이면 "bold" 기준을 적용한다
BOLD_WEIGHTS = ("bold", "black")


@dataclass(frozen=True)
class SystemPolicy:
    """모든 포스터가 지켜야 하는 하한. Planner 접근 불가."""

    # ── 대비 ────────────────────────────────────────────────────────────
    text_contrast_min: float = 4.5          # 작은 글자
    large_text_contrast_min: float = 3.0    # 큰 글자
    large_text_min_px: int = 52             # regular/medium 기준 (위 환산)
    large_bold_min_px: int = 40             # bold/black 기준
    contrast_percentile: int = 5            # 글자 아래 픽셀 중 하위 5% 로 판정

    # ── 가림 ────────────────────────────────────────────────────────────
    critical_occlusion_max: float = 0.15    # 핵심 블록의 **잉크** 가림 상한
    char_occlusion_max: float = 0.55        # 글자 하나 기준
    block_occlusion_max: float = 0.40       # 핵심이 아닌 블록의 상한 (경고)

    # ── 모티프 ──────────────────────────────────────────────────────────
    motif_visible_min: float = 0.30         # must_be_visible 이 남아 있어야 할 비율

    # ── 이탈 ────────────────────────────────────────────────────────────
    canvas_overflow_max: int = 0            # 선언된 bleed 외 이탈 픽셀

    # ── 잉크 판정 임계 ──────────────────────────────────────────────────
    ink_alpha_min: int = 128                # 이 알파 이상을 "글자 획"으로 본다
    cover_alpha_min: int = 128              # 이 알파 이상을 "덮었다"고 본다

    def contrast_min_for(self, size_px: int, weight: str) -> float:
        """이 글자에 적용할 최소 대비. Validator 가 임의로 정하지 않는다."""
        threshold = self.large_bold_min_px if weight in BOLD_WEIGHTS else self.large_text_min_px
        return self.large_text_contrast_min if size_px >= threshold else self.text_contrast_min

    def is_large_text(self, size_px: int, weight: str) -> bool:
        threshold = self.large_bold_min_px if weight in BOLD_WEIGHTS else self.large_text_min_px
        return size_px >= threshold

    def as_dict(self) -> dict:
        return {
            "text_contrast_min": self.text_contrast_min,
            "large_text_contrast_min": self.large_text_contrast_min,
            "large_text_min_px": self.large_text_min_px,
            "large_bold_min_px": self.large_bold_min_px,
            "contrast_percentile": self.contrast_percentile,
            "critical_occlusion_max": self.critical_occlusion_max,
            "char_occlusion_max": self.char_occlusion_max,
            "block_occlusion_max": self.block_occlusion_max,
            "motif_visible_min": self.motif_visible_min,
            "canvas_overflow_max": self.canvas_overflow_max,
            "reference_display_short_side": REFERENCE_DISPLAY_SHORT_SIDE,
        }


DEFAULT_POLICY = SystemPolicy()

# ── 이번 단계에서 **구현하지 않고 보류**하는 항목 ─────────────────────────
#
# 계약이 없는 것을 억지로 재면 틀린 것을 재게 된다.
DEFERRED_CHECKS = {
    "label_visible_min": (
        "제품 라벨/브랜드 영역의 가시성 기준. "
        "ProductGeometry 에 label region / label mask / brand bbox 가 없어서 "
        "제품 bbox 전체를 라벨로 가정할 수밖에 없는데, 그건 틀린 측정이다. "
        "라벨 영역을 검출하거나 입력받는 계약이 생기면 구현한다"
    ),
}

__all__ = [
    "SystemPolicy",
    "DEFAULT_POLICY",
    "DEFERRED_CHECKS",
    "BOLD_WEIGHTS",
    "REFERENCE_DISPLAY_SHORT_SIDE",
    "WCAG_LARGE_REGULAR_PX",
    "WCAG_LARGE_BOLD_PX",
]

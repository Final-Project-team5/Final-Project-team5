"""RenderEvidence — Renderer 가 **실제로 합성한 것**을 그대로 남긴다 (Step 6).

    RenderPlan
        ↓
    Renderer
        ├ final_image
        └ RenderEvidence
             ├ 요소별 잉크 마스크 (실제 합성에 쓴 알파 그대로)
             ├ 제품 알파 마스크
             ├ 요소별 "글자 아래에 실제로 깔린 픽셀"
             ├ 요소별 남은 가시 영역
             └ bbox · layer · 색
        ↓
    Safety Validator

**Validator 가 글자를 다시 그리지 않는다.** 다시 그리면 "Renderer 가 그린 것"과
"Validator 가 재구성한 것"이 갈릴 수 있고, 그러면 무엇을 판정한 것인지 모르게 된다.
여기 담기는 마스크는 Renderer 가 `alpha_composite` 에 넘긴 바로 그 알파다.

메모리 — 1024² bool 마스크 하나가 1MB 다. 요소가 10개 안팎이라 그대로 들고 있는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np

Box = Tuple[int, int, int, int]
RGB = Tuple[int, int, int]


@dataclass(frozen=True)
class ElementEvidence:
    """한 요소가 실제로 남긴 것."""

    id: str
    kind: str                 # "copy" | "motif" | "product"
    layer: str
    bbox: Box                 # plan 이 정한 자리 (캔버스 밖일 수도 있다)
    ink: np.ndarray           # bool, 캔버스 크기. 합성에 쓴 알파 ≥ 임계
    visible: np.ndarray       # bool. 이후 레이어에 덮이고 남은 부분
    color: Optional[RGB] = None          # 전경색 (copy/motif)
    under: Optional[np.ndarray] = None   # (N,3) uint8 — 잉크 자리에 **깔려 있던** 픽셀
    char_boxes: Tuple[Box, ...] = ()     # 가로쓰기 글자 단위 상자 (근사)
    size_px: int = 0
    weight: str = ""
    # 캔버스 이탈은 **기하로** 판정한다 — 캔버스 밖 픽셀은 애초에 그려지지 않아
    # 잉크 마스크에 남지 않기 때문이다. bbox 와 캔버스 경계를 비교한다
    intended_bbox: Optional[Box] = None

    @property
    def ink_px(self) -> int:
        return int(self.ink.sum())

    @property
    def visible_px(self) -> int:
        return int(self.visible.sum())

    @property
    def visible_ratio(self) -> float:
        return self.visible_px / self.ink_px if self.ink_px else 0.0

    def visible_under(self) -> Optional[np.ndarray]:
        """**최종 화면에 남은** 잉크 자리의 바탕 픽셀만 고른다.

        `under` 는 합성 직전에 잉크 전체 자리에서 뜬 것이라, 나중에 제품이
        덮어 버린 부분까지 들어 있다. 이미 안 보이는 획으로 대비를 재면
        "보이지도 않는 글자가 잘 읽힌다/안 읽힌다"를 재는 셈이 된다.

        `under` 는 `ink` 를 행 우선으로 훑은 순서라, 같은 순서의 `visible`
        선택자로 부분집합을 만들 수 있다.
        """
        if self.under is None or len(self.under) == 0:
            return None
        keep = self.visible[self.ink]
        if not keep.any():
            return None
        return self.under[keep]


@dataclass(frozen=True)
class RenderEvidence:
    """렌더 한 번의 근거 전체."""

    canvas_width: int
    canvas_height: int
    elements: Tuple[ElementEvidence, ...]
    product_alpha: np.ndarray            # bool, 캔버스 크기 — 제품이 실제 덮은 자리
    renderer_version: str
    plan_digest: str

    def by_id(self, element_id: str) -> Optional[ElementEvidence]:
        for e in self.elements:
            if e.id == element_id:
                return e
        return None

    def of_kind(self, kind: str) -> Tuple[ElementEvidence, ...]:
        return tuple(e for e in self.elements if e.kind == kind)

    def digest_source(self) -> dict:
        """결정론 확인용 요약 — 마스크 자체는 무겁다."""
        return {
            "canvas": [self.canvas_width, self.canvas_height],
            "renderer_version": self.renderer_version,
            "plan_digest": self.plan_digest,
            "product_alpha_px": int(self.product_alpha.sum()),
            "elements": [
                {
                    "id": e.id,
                    "kind": e.kind,
                    "layer": e.layer,
                    "bbox": list(e.bbox),
                    "ink_px": e.ink_px,
                    "visible_px": e.visible_px,
                    "color": list(e.color) if e.color else None,
                    "chars": len(e.char_boxes),
                }
                for e in self.elements
            ],
        }


__all__ = ["ElementEvidence", "RenderEvidence"]

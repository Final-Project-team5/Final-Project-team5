"""ProductGeometry — Step 3 입력 계약.

RenderSpec 과 CreativeBrief 만으로는 제품 bbox 를 계산할 수 없다.

    product.fit = zone_width
    product.anchor = right / bottom
    product.rotation = slight_ccw

를 실제 좌표로 바꾸려면 cutout 의 크기와 마스크 bbox 를 알아야 한다.
그래서 Step 3 의 입력은 셋이다.

    RenderSpec + CreativeBrief + ProductGeometry  →  RenderPlan

**geometry 를 몰래 가져오지 않는다.**

    ✗ dynamic 안에서 pipeline.masking import
    ✗ build_plan() 이 파일 경로를 받아 이미지를 직접 분석
    ✗ 전역 상태에서 mask bbox 조회
    ○ 상위 단계가 계산해 이 immutable 값으로 명시적으로 넘긴다

이렇게 해야 production 분리와 결정론 계약(§9)이 함께 유지된다.
같은 geometry 를 넣으면 같은 plan 이 나오고, 그 geometry 가 어디서 왔는지는
호출자의 책임으로 남는다.

좌표 규약 — `mask_bbox` 는 **양끝을 포함**하는 (x0, y0, x1, y1) 이다.
production `masking.product_bbox_px()` 와 같은 규약이라 값을 그대로 옮길 수
있다. 따라서 폭은 `x1 - x0 + 1` 이다. 이 +1 을 빼먹으면 판정 경계에서
1px 씩 어긋난다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .errors import ProductGeometryInvalid


@dataclass(frozen=True)
class ProductGeometry:
    """제품 원본 · cutout · 마스크 bbox.

    source_*   사용자가 올린 원본 크기 (추적용.  배치 계산에는 쓰지 않는다)
    cutout_*   배경을 제거한 cutout 캔버스 크기.  마스크와 같은 크기다
    mask_bbox  cutout 좌표계의 제품 실제 범위.  **양끝 포함**
    """

    source_width: int
    source_height: int
    cutout_width: int
    cutout_height: int
    mask_bbox: Tuple[int, int, int, int]

    # ── 파생값 ────────────────────────────────────────────────────────────
    @property
    def bbox_width(self) -> int:
        return self.mask_bbox[2] - self.mask_bbox[0] + 1

    @property
    def bbox_height(self) -> int:
        return self.mask_bbox[3] - self.mask_bbox[1] + 1

    @property
    def bbox_offset(self) -> Tuple[int, int]:
        """cutout 좌상단에서 제품이 시작하는 지점."""
        return self.mask_bbox[0], self.mask_bbox[1]

    def validate(self) -> None:
        """스스로 모순이면 거부한다. 보정하지 않는다."""
        for name in ("source_width", "source_height", "cutout_width", "cutout_height"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ProductGeometryInvalid(
                    "geometry.non_positive_size", name, f"양의 정수여야 한다 (받음: {value!r})"
                )

        if not (isinstance(self.mask_bbox, tuple) and len(self.mask_bbox) == 4):
            raise ProductGeometryInvalid(
                "geometry.bbox_shape", "mask_bbox", f"(x0, y0, x1, y1) 여야 한다 (받음: {self.mask_bbox!r})"
            )
        x0, y0, x1, y1 = self.mask_bbox
        for label, value in (("x0", x0), ("y0", y0), ("x1", x1), ("y1", y1)):
            if not isinstance(value, int) or isinstance(value, bool):
                raise ProductGeometryInvalid(
                    "geometry.bbox_shape", f"mask_bbox.{label}", f"정수여야 한다 (받음: {value!r})"
                )

        if x1 < x0 or y1 < y0:
            raise ProductGeometryInvalid(
                "geometry.bbox_empty",
                "mask_bbox",
                f"제품 픽셀이 없다 ({self.mask_bbox}) — 마스크가 비었을 때 조용히 넘기지 않는다",
            )
        if x0 < 0 or y0 < 0 or x1 >= self.cutout_width or y1 >= self.cutout_height:
            raise ProductGeometryInvalid(
                "geometry.bbox_out_of_cutout",
                "mask_bbox",
                f"{self.mask_bbox} 가 cutout {self.cutout_width}×{self.cutout_height} 를 벗어난다",
            )

    @classmethod
    def from_mask_size(
        cls,
        *,
        cutout_width: int,
        cutout_height: int,
        mask_bbox: Tuple[int, int, int, int],
        source_width: int = 0,
        source_height: int = 0,
    ) -> "ProductGeometry":
        """원본 크기를 모를 때(=cutout 이 곧 원본일 때) 쓰는 편의 생성자."""
        geo = cls(
            source_width=source_width or cutout_width,
            source_height=source_height or cutout_height,
            cutout_width=cutout_width,
            cutout_height=cutout_height,
            mask_bbox=tuple(mask_bbox),  # type: ignore[arg-type]
        )
        geo.validate()
        return geo


__all__ = ["ProductGeometry"]

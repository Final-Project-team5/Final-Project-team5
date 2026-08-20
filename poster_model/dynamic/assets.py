"""픽셀 asset 입력 계약 — Step 4.

`ProductGeometry` 는 배치를 계산하기에는 충분하지만 **그릴 픽셀**을 갖고 있지
않다. 그래서 Renderer 의 입력은 셋이다.

    RenderPlan + ProductRenderAsset (+ BackgroundRenderAsset)  →  pixels

```text
금지   ✗ Renderer 가 파일 경로를 찾아 제품 이미지를 다시 읽음
      ✗ pipeline.masking 을 import 해 rembg/mask 를 다시 돌림
      ✗ 전역 상태에서 제품 asset 조회
○     상위 계층이 배경 제거를 끝낸 RGBA 를 명시적으로 넘긴다
```

Plan 은 geometry 를 정하고, Renderer 는 그 geometry 에 맞춰 **넘겨받은** 픽셀을
놓는다. 두 책임이 섞이면 "같은 Plan 인데 결과가 다른" 경우가 생긴다.

immutability 에 대해 — dataclass 자체는 frozen 이지만 PIL 이미지는 가변이다.
그래서 Renderer 는 asset 을 **절대 제자리에서 고치지 않고** 항상 복사본을
변형한다. `digest()` 로 렌더 전후 asset 이 그대로인지 확인할 수 있다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from PIL import Image

from .errors import RenderAssetInvalid
from .geometry import ProductGeometry


def _digest(image: Image.Image) -> str:
    return hashlib.sha256(image.tobytes()).hexdigest()[:16]


@dataclass(frozen=True)
class ProductRenderAsset:
    """배경이 제거된 제품 RGBA. 크기는 ProductGeometry 의 cutout 과 같아야 한다."""

    image: Image.Image

    def validate(self, geometry: ProductGeometry) -> None:
        if not isinstance(self.image, Image.Image):
            raise RenderAssetInvalid(
                "asset.product_not_image", "ProductRenderAsset.image", f"{type(self.image).__name__}"
            )
        if self.image.mode != "RGBA":
            raise RenderAssetInvalid(
                "asset.product_mode",
                "ProductRenderAsset.image",
                f"RGBA 여야 한다 (받음: {self.image.mode}) — 여기서 변환하지 않는다",
            )
        want = (geometry.cutout_width, geometry.cutout_height)
        if self.image.size != want:
            raise RenderAssetInvalid(
                "asset.product_size_mismatch",
                "ProductRenderAsset.image",
                f"geometry 의 cutout {want} 와 다르다 (받음: {self.image.size})",
            )

    def digest(self) -> str:
        return _digest(self.image)


@dataclass(frozen=True)
class BackgroundRenderAsset:
    """외부에서 생성된 배경. `background.mode = generated` 일 때만 쓴다."""

    image: Image.Image

    def validate(self, canvas_width: int, canvas_height: int) -> None:
        if not isinstance(self.image, Image.Image):
            raise RenderAssetInvalid(
                "asset.background_not_image",
                "BackgroundRenderAsset.image",
                f"{type(self.image).__name__}",
            )
        if self.image.size != (canvas_width, canvas_height):
            raise RenderAssetInvalid(
                "asset.background_size_mismatch",
                "BackgroundRenderAsset.image",
                f"캔버스 {canvas_width}×{canvas_height} 와 다르다 (받음: {self.image.size})",
            )

    def digest(self) -> str:
        return _digest(self.image.convert("RGB"))


__all__ = ["ProductRenderAsset", "BackgroundRenderAsset"]

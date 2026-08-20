"""배경 해석 — `RenderSpec.background` → `ResolvedBackground` (Step 4 전 계약).

Renderer 가 배경까지 판단하지 않도록 색·방향·강도를 Plan 에서 확정한다.

지원 범위 (Renderer v1)

    flat        이 계층이 그린다.  palette 의 bg 색 하나
    gradient    이 계층이 그린다.  bg 에서 명도를 밀어 두 색을 만든다
    generated   **직접 만들지 않는다.**  외부에서 생성한 BackgroundRenderAsset 을
                명시적으로 받아야 하고, 없으면 RenderUnsupported 로 거부한다

```text
금지   ✗ dynamic 안에서 production diffusion pipeline import
      ✗ generated 를 만났다고 몰래 generate.py 호출
```

`lighting` 이 그라데이션 방향과 세기를 정한다 — 조명이 곧 명암의 방향이므로
따로 축을 만들지 않았다. `material` 은 v1 의 flat/gradient 픽셀에는 영향을
주지 않는다. generated 프롬프트를 조립할 때 쓰이는 값이라 **통과만 시키고
그 사실을 적어 둔다** (조용히 무시하는 것과 다르다).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

from .errors import RenderUnsupported
from .fonts import round_half_up
from .palette import RGB, ResolvedPalette, _hsl_to_rgb, _rgb_to_hsl
from .spec import RenderSpec

# lighting → (그라데이션 방향, 명도 차이 %)
GRADIENT_BY_LIGHTING: Mapping[str, Tuple[str, int]] = MappingProxyType(
    {
        "flat": ("vertical", 6),
        "soft_top": ("vertical", 14),
        "soft_side": ("horizontal", 14),
        "dramatic": ("diagonal", 26),
    }
)

# texture → 그레인 진폭 (± 값)
GRAIN_BY_TEXTURE: Mapping[str, int] = MappingProxyType(
    {"none": 0, "subtle_grain": 4, "paper_grain": 9}
)

GRADIENT_DIRECTIONS: Tuple[str, ...] = ("vertical", "horizontal", "diagonal")


@dataclass(frozen=True)
class ResolvedBackground:
    mode: str
    base_color: RGB
    gradient_from: Optional[RGB]
    gradient_to: Optional[RGB]
    gradient_direction: Optional[str]
    material: str
    lighting: str
    texture: str
    grain_amplitude: int
    requires_asset: bool
    material_affects_pixels: bool

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "base_color": list(self.base_color),
            "gradient_from": list(self.gradient_from) if self.gradient_from else None,
            "gradient_to": list(self.gradient_to) if self.gradient_to else None,
            "gradient_direction": self.gradient_direction,
            "material": self.material,
            "lighting": self.lighting,
            "texture": self.texture,
            "grain_amplitude": self.grain_amplitude,
            "requires_asset": self.requires_asset,
        }


def _shift_lightness(rgb: RGB, delta_pct: int) -> RGB:
    h, s, l = _rgb_to_hsl(rgb)
    return _hsl_to_rgb(h, s, max(0.0, min(100.0, l + delta_pct)))


def resolve_background(spec: RenderSpec, palette: ResolvedPalette) -> ResolvedBackground:
    bg = spec.background
    base = palette.rgb("bg")
    grain = GRAIN_BY_TEXTURE[bg.texture]

    if bg.mode == "generated":
        # 여기서 만들지 않는다. 외부 asset 을 요구한다는 사실만 확정한다
        return ResolvedBackground(
            mode="generated",
            base_color=base,
            gradient_from=None,
            gradient_to=None,
            gradient_direction=None,
            material=bg.material,
            lighting=bg.lighting,
            texture=bg.texture,
            grain_amplitude=grain,
            requires_asset=True,
            material_affects_pixels=True,
        )

    if bg.mode == "flat":
        return ResolvedBackground(
            mode="flat",
            base_color=base,
            gradient_from=None,
            gradient_to=None,
            gradient_direction=None,
            material=bg.material,
            lighting=bg.lighting,
            texture=bg.texture,
            grain_amplitude=grain,
            requires_asset=False,
            material_affects_pixels=False,
        )

    direction, delta = GRADIENT_BY_LIGHTING[bg.lighting]
    half = round_half_up(delta / 2)
    return ResolvedBackground(
        mode="gradient",
        base_color=base,
        gradient_from=_shift_lightness(base, half),
        gradient_to=_shift_lightness(base, -half),
        gradient_direction=direction,
        material=bg.material,
        lighting=bg.lighting,
        texture=bg.texture,
        grain_amplitude=grain,
        requires_asset=False,
        material_affects_pixels=False,
    )


def require_supported(background: ResolvedBackground, has_asset: bool) -> None:
    """Renderer 진입 시 capability 확인. 근사·자동 생성을 하지 않는다."""
    if background.mode == "generated" and not has_asset:
        raise RenderUnsupported(
            "background.generated_requires_asset",
            "background.mode",
            "Renderer v1 은 배경을 생성하지 않는다 — 외부에서 만든 "
            "BackgroundRenderAsset 을 명시적으로 넘겨야 한다 "
            "(production diffusion 경로를 호출하지 않는다)",
        )


__all__ = [
    "GRADIENT_BY_LIGHTING",
    "GRAIN_BY_TEXTURE",
    "GRADIENT_DIRECTIONS",
    "ResolvedBackground",
    "resolve_background",
    "require_supported",
]

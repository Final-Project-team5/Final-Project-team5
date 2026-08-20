"""Palette Resolver — 역할을 **실제 색 값**으로 확정한다 (Step 4 전 계약).

    RenderSpec.palette  +  CreativeBrief(product_signals / brand_palette / fixed_values)
            ↓
      Palette Resolver
            ↓
      ResolvedPalette   →  RenderPlan

이 단계가 없으면 Renderer 가 "spot 이니까 이 색" 이라고 정하게 되고, 그건
디자인 판단이다 (E12 §6 R3). 색은 Plan 에서 끝난다.

**조용한 fallback 을 만들지 않는다.**

    source=product    제품 색 신호가 없으면 실패
    source=brand      brand 색 정보가 없으면 실패
    source=preferred  brief.preferred_color 가 없으면 실패        (v0.5)
    source=fixed      fixed_values 사용.  역할이 하나라도 비면 실패
    ✗ 정보가 없다고 임의 기본색으로 대체
    ✗ 한 source 가 비었다고 다른 source 로 넘어가기

네 source 는 **독립 branch** 다. 어느 것을 쓸지는 Planner 가 고르고, 고른
source 의 입력이 없으면 그 자리에서 거부한다 (E16 §Q3-2).

strategy 는 **base hue 에서 spot hue 를 어떻게 잡는가**를 정한다. 그 표는
아래 STRATEGY_SPOT_SHIFT 에 있고, 역할별 S/L 은 ROLE_TONE 에 있다. 두 표가
곧 "어떤 색이 나오는가"의 전부다 — 코드 곳곳에 흩어 두지 않는다.

E10 §9 에서 확인한 것 하나를 규칙으로 옮겨 왔다: **지배색이 무채색에 가까우면
지배색의 hue 를 쓰면 안 된다.** 그때 제품 4종의 배경이 전부 거의 검정으로
수렴했고(제품 간 ΔE 5.3), accent 클러스터를 base 로 바꿔서 갈라졌다.
"""

from __future__ import annotations

import colorsys
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

from .brief import CreativeBrief
from .color_roles import (BACKGROUND_TONES, MONOCHROME_BG,
                          ROLE_TONE_BY_GROUND, SUPPORTED_COLOR_ROLES)
from .errors import PlanUnresolvable
from .fonts import round_half_up
from .spec import RenderSpec

_HEX = re.compile(r"#([0-9A-Fa-f]{6})\Z")

RGB = Tuple[int, int, int]

# 제품 신호에서 반드시 있어야 하는 키
REQUIRED_PRODUCT_SIGNALS: Tuple[str, ...] = ("dominant", "accent")

# 지배색이 이 채도 아래면 무채색으로 보고 accent 를 base hue 로 쓴다 (E10 §9)
NEUTRAL_SATURATION_MAX = 18          # 퍼센트

# strategy → base hue 에서 spot hue 까지의 각도
STRATEGY_SPOT_SHIFT: Mapping[str, int] = MappingProxyType(
    {
        "complementary": 180,
        "analogous": 30,
        "split_complementary": 150,
        "monochromatic": 0,
        "neutral_support": 0,
    }
)

# ↑ 색 역할 표는 `dynamic/color_roles.py` 로 옮겼다 — spec.py 도 같은 값을
#   봐야 하는데 palette.py 를 import 하면 순환이 된다. 값은 그대로다.


def hex_to_rgb(value: str) -> RGB:
    m = _HEX.match(value or "")
    if not m:
        raise PlanUnresolvable("palette.bad_hex", "palette", f"#RRGGBB 여야 한다 (받음: {value!r})")
    h = m.group(1)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(rgb: RGB) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _rgb_to_hsl(rgb: RGB) -> Tuple[float, float, float]:
    r, g, b = (c / 255 for c in rgb)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h * 360, s * 100, l * 100


def _hsl_to_rgb(h: float, s: float, l: float) -> RGB:
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360, l / 100, s / 100)
    return round_half_up(r * 255), round_half_up(g * 255), round_half_up(b * 255)


def relative_luminance(rgb: RGB) -> float:
    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


@dataclass(frozen=True)
class ResolvedPalette:
    """역할 → 실제 RGB. Renderer 는 이 표만 본다."""

    colors: Mapping[str, RGB]
    strategy: str
    source: str
    base_hue: int
    spot_hue: int
    background_tone: str = "light"

    def rgb(self, role: str) -> RGB:
        try:
            return self.colors[role]
        except KeyError:
            raise PlanUnresolvable(
                "palette.role_missing",
                f"palette[{role}]",
                f"확정된 색에 {role!r} 이 없다 (있는 것: {sorted(self.colors)})",
            ) from None

    def hex(self, role: str) -> str:
        return rgb_to_hex(self.rgb(role))

    def contrast(self, role_a: str, role_b: str) -> float:
        """WCAG 명도 대비. 여기서 **강제하지는 않는다** — Step 6 Validator 몫."""
        la, lb = relative_luminance(self.rgb(role_a)), relative_luminance(self.rgb(role_b))
        hi, lo = max(la, lb), min(la, lb)
        return round((hi + 0.05) / (lo + 0.05), 2)

    def as_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "source": self.source,
            "background_tone": self.background_tone,
            "base_hue": self.base_hue,
            "spot_hue": self.spot_hue,
            "colors": {k: rgb_to_hex(v) for k, v in sorted(self.colors.items())},
        }


def _product_signals(brief: CreativeBrief) -> Mapping[str, str]:
    signals = (brief.product_signals or {}).get("palette")
    if not isinstance(signals, dict):
        raise PlanUnresolvable(
            "palette.product_signal_missing",
            "brief.product_signals.palette",
            "source=product 인데 제품 색 신호가 없다 — 임의 기본색으로 대체하지 않는다",
        )
    missing = [k for k in REQUIRED_PRODUCT_SIGNALS if not signals.get(k)]
    if missing:
        raise PlanUnresolvable(
            "palette.product_signal_missing",
            "brief.product_signals.palette",
            f"필수 신호 누락: {missing} (필요: {list(REQUIRED_PRODUCT_SIGNALS)})",
        )
    return signals


def _from_table(table: Mapping[str, str], roles: Tuple[str, ...], where: str, code: str):
    missing = [r for r in roles if not table.get(r)]
    if missing:
        raise PlanUnresolvable(code, where, f"역할 색이 없다: {missing}")
    return {r: hex_to_rgb(table[r]) for r in roles}


def resolve_palette(spec: RenderSpec, brief: CreativeBrief) -> ResolvedPalette:
    pal = spec.palette
    roles = tuple(pal.roles)

    if pal.strategy == "fixed" and pal.source != "fixed":
        raise PlanUnresolvable(
            "palette.strategy_source_mismatch",
            "palette",
            f"strategy=fixed 는 source=fixed 와만 함께 쓴다 (받음: source={pal.source})",
        )

    # source=fixed / brand 는 값이 이미 주어졌으므로 background_tone 이 색을
    # 바꾸지 않는다. 값은 그대로 싣고 tone 은 기록만 한다 (조용히 뒤집지 않는다)
    if pal.source == "fixed":
        colors = _from_table(
            dict(pal.fixed_values or {}), roles, "palette.fixed_values", "palette.fixed_role_missing"
        )
        return ResolvedPalette(
            colors=MappingProxyType(colors),
            strategy=pal.strategy,
            source=pal.source,
            base_hue=-1,
            spot_hue=-1,
            background_tone=pal.background_tone,
        )

    if pal.source == "brand":
        colors = _from_table(
            dict(brief.brand_palette or {}), roles, "brief.brand_palette", "palette.brand_missing"
        )
        return ResolvedPalette(
            colors=MappingProxyType(colors),
            strategy=pal.strategy,
            source=pal.source,
            base_hue=-1,
            spot_hue=-1,
            background_tone=pal.background_tone,
        )

    # ── seed hue 결정 — source 별 **독립 branch** (E16 §Q3-2) ─────────────
    #
    # 두 branch 가 다른 것은 **seed 를 어떻게 뽑는가** 하나뿐이다. 뽑고 나면
    # 아래 조합 규칙은 같다. 조합까지 갈라 두면 같은 표를 두 번 관리하게 된다.
    if pal.source == "preferred":
        seed_hex = getattr(brief, "preferred_color", None)
        if not seed_hex:
            raise PlanUnresolvable(
                "palette.preferred_color_missing",
                "brief.preferred_color",
                "source=preferred 인데 사용자 선호색이 없다 — "
                "product_signals 로 대체하지 않는다",
            )
        seed = hex_to_rgb(seed_hex)
        seed_h, _, _ = _rgb_to_hsl(seed)
        # ★ product 의 `saturation < 18 → accent fallback` 을 **적용하지 않는다.**
        #   사용자가 무채색을 골랐다면 그것도 의도다. accent 로 갈아치우면
        #   고른 색과 다른 색이 나온다 (E16 §Q3-2).
        base_hue = round_half_up(seed_h) % 360
        dominant_hue = base_hue
    else:
        signals = _product_signals(brief)
        dominant = hex_to_rgb(signals["dominant"])
        accent = hex_to_rgb(signals["accent"])

        dom_h, dom_s, _ = _rgb_to_hsl(dominant)
        acc_h, _, _ = _rgb_to_hsl(accent)

        # 지배색이 무채색에 가까우면 accent 를 base 로 (E10 §9)
        base_hue = round_half_up(acc_h if dom_s < NEUTRAL_SATURATION_MAX else dom_h) % 360
        dominant_hue = dom_h

    shift = STRATEGY_SPOT_SHIFT.get(pal.strategy)
    if shift is None:
        raise PlanUnresolvable("palette.unknown_strategy", "palette.strategy", pal.strategy)
    spot_hue = (base_hue + shift) % 360

    ground = pal.background_tone
    table = ROLE_TONE_BY_GROUND.get(ground)
    if table is None:
        raise PlanUnresolvable(
            "palette.unknown_background_tone", "palette.background_tone", repr(ground)
        )

    hues = {"base": base_hue, "spot": spot_hue, "dominant": dominant_hue}
    colors: dict = {}
    for role in roles:
        if role == "bg" and pal.strategy == "monochromatic":
            tone = MONOCHROME_BG[ground]
        else:
            tone = table.get(role)
        if tone is None:
            raise PlanUnresolvable(
                "palette.role_unmapped",
                f"palette.roles[{role}]",
                f"{role!r} 의 색을 어떻게 만들지 표에 없다 (있는 것: {sorted(table)})",
            )
        which, sat, light = tone
        colors[role] = _hsl_to_rgb(hues[which], sat, light)

    return ResolvedPalette(
        colors=MappingProxyType(colors),
        strategy=pal.strategy,
        source=pal.source,
        base_hue=base_hue,
        spot_hue=spot_hue,
        background_tone=ground,
    )


__all__ = [
    "RGB",
    "REQUIRED_PRODUCT_SIGNALS",
    "NEUTRAL_SATURATION_MAX",
    "STRATEGY_SPOT_SHIFT",
    "ROLE_TONE_BY_GROUND",
    "SUPPORTED_COLOR_ROLES",
    "MONOCHROME_BG",
    "BACKGROUND_TONES",
    "ResolvedPalette",
    "resolve_palette",
    "hex_to_rgb",
    "rgb_to_hex",
    "relative_luminance",
]

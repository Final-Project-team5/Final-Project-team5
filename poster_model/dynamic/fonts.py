"""서체 해석과 문자열 측정 — Step 3.

RenderSpec 은 `family: sans|serif|display` + `weight` 라는 **추상값**만 갖는다
(§7-2). 실제 파일로 바꾸는 것이 Renderer 몫이고, 그 표가 여기 있다.

production `pipeline.config.FONTS` 를 import 하지 않는다. 값이 겹치더라도
참조를 만들지 않는 것이 이 패키지의 전제다 (core_1x1 분리).

**대체를 조용히 하지 않는다.** 번들된 파일이 5개뿐이라 (family, weight) 조합
전부에 이상적인 파일이 있지는 않다. 그래서 표에 대체 여부를 함께 적고,
RenderPlan 이 `font_substituted` 로 그 사실을 들고 나간다. 폴백 체인을 숨겨
두는 것과, 표에 적어 결과에 노출하는 것은 다르다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from PIL import ImageFont

from .errors import PlanUnresolvable

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

# (family, weight) → 번들 파일. **정확히 표현되는 조합만 있다.**
#
# 이전 판에는 12조합이 모두 있었고 그중 7개가 대체였다. 특히
# serif/regular → NanumMyeongjo**Bold** 는 Planner 가 regular 를 골랐는데
# 결과가 bold 로 나오는 것이라, RenderSpec 을 그대로 렌더한 것이 아니었다.
# weight 는 인상을 만드는 축이므로(E11 §1-4) 조용히 바꾸지 않는다.
#
# 이제 표에 없는 조합은 대체하지 않고 **거부**한다. 파일이 늘면 줄이 는다.
# 허용 목록의 단일 출처는 `spec.SUPPORTED_TYPE_FACES` 이고 아래 표와 일치한다.
FONT_TABLE: Dict[Tuple[str, str], str] = {
    ("sans", "regular"): "Pretendard/Pretendard-Regular.ttf",
    ("sans", "medium"): "Pretendard/Pretendard-Medium.ttf",
    ("serif", "bold"): "NanumMyeongjo/NanumMyeongjoBold.ttf",
    ("display", "bold"): "GmarketSans/GmarketSansTTFBold.ttf",
    ("display", "black"): "BlackHanSans/BlackHanSans-Regular.ttf",
}


def round_half_up(value: float) -> int:
    """float → int 를 half-up 으로 고정한다 (Grid Resolver 의 T3 와 같은 규칙).

    파이썬 `round()` 는 half-even 이라 0.5 / 2.5 에서 결과가 갈린다.
    측정값이 int 로 내려오는 지점은 **전부** 이 함수를 지난다.
    """
    return math.floor(value + 0.5)


@dataclass(frozen=True)
class ResolvedFont:
    family: str
    weight: str
    path: str
    size_px: int
    substituted: bool
    substitution_reason: str

    @property
    def name(self) -> str:
        return Path(self.path).stem


class FontBook:
    """(family, weight, size) → PIL 폰트. 같은 인자는 같은 객체를 준다."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self._root = Path(root) if root else FONT_DIR
        self._cache: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}

    def resolve(self, family: str, weight: str, size_px: int) -> ResolvedFont:
        rel = FONT_TABLE.get((family, weight))
        if rel is None:
            raise PlanUnresolvable(
                "font.unsupported_face",
                f"typography[{family}/{weight}]",
                f"({family}, {weight}) 는 번들 폰트로 정확히 표현할 수 없다 — "
                f"다른 굵기로 대체하지 않는다 (가능: {sorted(FONT_TABLE)})",
            )
        substituted, reason = False, ""
        path = self._root / rel
        if not path.exists():
            raise PlanUnresolvable(
                "font.missing",
                f"typography[{family}/{weight}]",
                f"{path} 가 없다 — 다른 폰트로 대신하지 않는다",
            )
        return ResolvedFont(
            family=family,
            weight=weight,
            path=str(path),
            size_px=size_px,
            substituted=substituted,
            substitution_reason=reason,
        )

    def load(self, font: ResolvedFont) -> ImageFont.FreeTypeFont:
        key = (font.path, font.size_px)
        cached = self._cache.get(key)
        if cached is None:
            cached = ImageFont.truetype(font.path, font.size_px)
            self._cache[key] = cached
        return cached

    # ── 측정 ─────────────────────────────────────────────────────────────
    def advance_px(self, font: ResolvedFont, text: str, tracking_px: int = 0) -> int:
        """가로쓰기 한 줄의 진행 폭.

        `getlength()` 는 커닝까지 반영한 advance 합이다. 자간은 **글자 사이**에만
        더한다 — 마지막 글자 뒤에 붙이면 우측 정렬이 자간만큼 밀린다.
        """
        if not text:
            return 0
        loaded = self.load(font)
        if tracking_px == 0:
            return round_half_up(loaded.getlength(text))
        # 자간이 있으면 Renderer 가 글자마다 따로 그린다 (커닝이 적용되지 않는다).
        # 측정도 같은 방식이어야 **잰 폭과 그린 폭이 정확히 같다**
        return sum(round_half_up(loaded.getlength(ch)) for ch in text) + tracking_px * (
            len(text) - 1
        )

    def char_advance_px(self, font: ResolvedFont, ch: str) -> int:
        """글자 하나의 진행량. Renderer 의 자간 그리기와 측정이 공유한다."""
        return round_half_up(self.load(font).getlength(ch))

    def vertical_advance_px(
        self, font: ResolvedFont, text: str, tracking_px: int = 0
    ) -> int:
        """세로쓰기 한 열의 진행 높이.

        v0.3 단순화 — 한 글자의 진행량을 **em 사각형(size_px)** 으로 본다.
        한글·한자 세로조판의 통상 규약이고, 로마자가 섞이면 실제보다 넉넉하게
        잡힌다. 넉넉한 쪽이 겹침보다 안전해서 이 방향으로 둔다.
        """
        if not text:
            return 0
        return font.size_px * len(text) + tracking_px * max(0, len(text) - 1)


__all__ = [
    "FONT_DIR",
    "FONT_TABLE",
    "round_half_up",
    "ResolvedFont",
    "FontBook",
]

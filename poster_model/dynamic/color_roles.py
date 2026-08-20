"""색 역할의 **단일 출처**.

첫 live run 에서 Planner 가 `dominant · accent · neutral` 을 역할 이름으로
냈고 `resolve_palette()` 가 `palette.role_unmapped` 로 거부했다. 모델 잘못이
아니다 — 스키마가 `Tuple[str, ...]` 로 열려 있어서 **합법인 이름을 알 방법이
없었다.** 실제로 색을 만들 줄 아는 이름은 아래 표의 key 뿐이다.

그래서 표를 여기 한 곳에 두고 셋이 같은 값을 본다.

    Renderer 가 이해하는 role   ROLE_TONE_BY_GROUND 의 key
    Validator 가 허용하는 role  SUPPORTED_COLOR_ROLES
    Planner schema 의 role      SUPPORTED_COLOR_ROLES

`palette.py` 도 `spec.py` 도 이 모듈을 import 한다. 두 방향 import 가 생기지
않도록 표를 여기로 옮겼고, **값은 한 글자도 바꾸지 않았다** — 기존 fixture 가
픽셀 단위로 그대로 재현돼야 이 이동이 회귀가 아님을 확인할 수 있다.

새 역할을 늘리는 작업이 아니다. 이미 구현이 아는 것을 적어 둘 뿐이다.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping, Tuple

# 역할별 (hue 출처, 채도 %, 명도 %).
#
# **background_tone 이 명암을 뒤집는다.** strategy 는 hue 관계만 정하므로 두 축이
# 서로 독립이다 — complementary+dark · monochromatic+dark 가 모두 성립한다.
# bg 와 ink 가 함께 뒤집히고, spot/emphasis 도 그 바탕에서 읽히도록 명도를 옮긴다
# (밝은 바탕에서는 낮추고, 짙은 바탕에서는 올린다).
ROLE_TONE_BY_GROUND: Mapping[str, Mapping[str, Tuple[str, int, int]]] = MappingProxyType(
    {
        # light 값은 v0.3 초판과 **동일하다** — 기존 fixture 가 픽셀 단위로
        # 그대로 재현돼야 이번 변경이 회귀가 아님을 확인할 수 있다
        "light": MappingProxyType(
            {
                "bg": ("base", 6, 94),
                "ink": ("base", 12, 12),
                "spot": ("spot", 78, 48),
                "emphasis": ("dominant", 62, 42),
            }
        ),
        "dark": MappingProxyType(
            {
                "bg": ("base", 14, 11),
                "ink": ("base", 8, 95),
                "spot": ("spot", 82, 62),
                "emphasis": ("dominant", 55, 68),
            }
        ),
    }
)

# monochromatic 은 배경에도 색을 남긴다 — 아니면 그냥 회색 판면이 된다
MONOCHROME_BG: Mapping[str, Tuple[str, int, int]] = MappingProxyType(
    {"light": ("base", 18, 92), "dark": ("base", 26, 13)}
)

BACKGROUND_TONES: Tuple[str, ...] = ("light", "dark")


def _supported() -> Tuple[str, ...]:
    """표에서 직접 뽑는다 — 이름을 두 번 적지 않는다.

    두 ground 가 서로 다른 역할을 지원하면 "light 에서만 되는 색"이 생기고,
    `background_tone` 을 바꾸는 순간 조용히 실패한다. 그래서 여기서 잡는다.
    """
    sets = {g: frozenset(t) for g, t in ROLE_TONE_BY_GROUND.items()}
    first = next(iter(sets.values()))
    for ground, names in sets.items():
        if names != first:
            raise AssertionError(
                f"ground 별 역할 집합이 다르다: {ground}={sorted(names)} "
                f"≠ {sorted(first)} — 한쪽에서만 되는 역할은 만들지 않는다"
            )
    # 선언 순서(bg → ink → spot → emphasis)를 유지한다. 정렬하면 프롬프트에서
    # 읽히는 순서가 배경→글자→강조 라는 실제 위계와 어긋난다
    return tuple(ROLE_TONE_BY_GROUND["light"])


#: Renderer 가 실제로 색을 만들 줄 아는 역할 이름. Planner schema 의 enum 이자
#: Validator 의 허용 집합이다.
SUPPORTED_COLOR_ROLES: Tuple[str, ...] = _supported()

__all__ = [
    "ROLE_TONE_BY_GROUND",
    "MONOCHROME_BG",
    "BACKGROUND_TONES",
    "SUPPORTED_COLOR_ROLES",
]

"""CreativeBrief — E12 v0.3 §5.

사용자 요구 + 제품 분석 + 카피. **디자인 결정이 없다.**

copy 를 블록으로 나누는 목적 (§5) — 문구만 다시 합성하는 기능은 **이미
production 에 있다.** 이 구조가 그것을 새로 만드는 것이 아니다.
  ① Renderer 가 텍스트를 역할별 블록으로 다룰 수 있게 한다
  ② safety 에서 어떤 정보가 critical 인지 block id 로 참조한다
  ③ Planner 가 각 정보의 위계와 배치를 설계할 수 있게 한다

RenderSpec 은 문자열을 담지 않고 `content_ref` 로 **참조만** 한다.
같은 RenderSpec + 다른 copy = 다른 픽셀이며, 이는 결정론 계약(§9)의
"동일 source assets" 에 copy content 가 포함되기 때문이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Tuple

# copy 고정 슬롯
COPY_SLOTS: Tuple[str, ...] = ("eyebrow", "headline", "benefit", "token", "cta")

# 규칙으로 유도되는 참조 — 열거된 것만 허용한다
DERIVED_REFS: Tuple[str, ...] = ("brief.category_label", "brief.business_label")

CONTENT_SOURCES: Tuple[str, ...] = ("user", "generated", "derived")

_SLOT_PREFIX = "brief.copy."
_EXTRA_PREFIX = "brief.copy.extra."


@dataclass(frozen=True)
class CopyItem:
    content: str
    source: str = "user"          # user | generated | derived
    editable: bool = True


@dataclass(frozen=True)
class CopyExtra:
    id: str
    content: str
    source: str = "generated"
    editable: bool = True


@dataclass(frozen=True)
class BriefCopy:
    eyebrow: Optional[CopyItem] = None
    headline: Optional[CopyItem] = None
    benefit: Optional[CopyItem] = None
    token: Optional[CopyItem] = None
    cta: Optional[CopyItem] = None
    extra: Tuple[CopyExtra, ...] = ()

    def slot(self, name: str) -> Optional[CopyItem]:
        return getattr(self, name, None) if name in COPY_SLOTS else None

    def extra_by_id(self, block_id: str) -> Optional[CopyExtra]:
        for item in self.extra:
            if item.id == block_id:
                return item
        return None


@dataclass(frozen=True)
class CreativeBrief:
    """사용자 요구 + 제품 분석 + 카피.

    `product_signals` 와 `brand_palette` 는 palette resolver 의 입력이다 (§4-5).
    필요한 신호가 없으면 **실패한다** — 임의 기본색으로 대체하지 않는다.

        product_signals["palette"] = {
            "dominant": "#RRGGBB",   # 마스크 내부 지배색.  필수
            "accent":   "#RRGGBB",   # 가장 채도 높은 클러스터.  필수
            "neutral":  "#RRGGBB",   # 선택
        }
        brand_palette = {"bg": "#…", "ink": "#…", …}   # source=brand 일 때 필수
    """

    business_type: str
    category: str
    tone: str = "minimal_product"
    output_ratio: str = "1:1"
    visual_style: Optional[str] = None
    keywords: Tuple[str, ...] = ()
    copy: BriefCopy = field(default_factory=BriefCopy)
    product_signals: dict = field(default_factory=dict)
    brand_palette: dict = field(default_factory=dict)

    # 유도 라벨 — DERIVED_REFS 가 가리키는 값
    category_label: Optional[str] = None
    business_label: Optional[str] = None

    # ── Planner 연결용 (planner_io.ServiceRequest 에서 채워진다) ──────────
    #
    # `product_identity` 는 "제품이 **무엇**인가" 다.
    # `RenderSpec.product`("제품을 **어떻게** 놓는가")와 다른 개념이므로
    # 이름을 갈라 둔다 — 혼용하면 Planner 계약이 흐려진다.
    product_identity: Optional[object] = None      # planner_io.ProductIdentity
    background_context: Optional[object] = None    # planner_io.BackgroundContextInput
    request: str = ""                              # 자연어 추가 요청 (E5 additional_request)

    # ── v0.5 · 사용자 선호색 ────────────────────────────────────────────
    #
    # `#RRGGBB` 단일 HEX. **soft hint 다** — 최종 RGB 를 강제하지 않는다.
    #   ○  palette seed / color anchor
    #   ✗  "이 색을 그대로 bg 로 써라"
    #
    # 이 값이 있다고 `palette.source` 가 `preferred` 가 되는 것이 아니다.
    # Planner 가 product · brand · preferred 중에서 **고른다**. 고른 경우에만
    # resolver 가 이 값을 seed 로 읽는다 (E16 §Q3-2).
    #
    # brand constraint 와 충돌하면 brand 가 우선한다 (E16 §Q2).
    preferred_color: Optional[str] = None


#: `preferred_color` 형식. 축약형(#RGB)·색이름을 받지 않는다 — 조용히
#: 확장하면 사용자가 고른 색과 다른 색이 된다.
_HEX6 = re.compile(r"^#[0-9A-Fa-f]{6}$")


def normalize_preferred_color(value: Optional[str]) -> Optional[str]:
    """`#RRGGBB` 만 통과시킨다. 형식이 틀리면 거부한다.

    **추측 보정하지 않는다.** `#FFF` 를 `#FFFFFF` 로 늘리거나 `red` 를
    해석하지 않는다 — adapter 경계에서 거부하고 서비스가 사용자에게 묻는다.
    """
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not _HEX6.match(value):
        raise ValueError(
            f"preferred_color 는 '#RRGGBB' 형식만 받는다 (받음: {value!r}) — "
            f"축약형·색이름을 임의로 해석하지 않는다"
        )
    return "#" + value[1:].upper()


def resolve_content_ref(brief: CreativeBrief, ref: str) -> Optional[str]:
    """content_ref 를 실제 문자열로 해석한다.

    해석 불가면 None 을 돌려준다 — 호출부(검증기)가
    ContentRefUnresolved 로 거부한다. **빈 문자열도 실패로 본다.**
    """
    if not isinstance(ref, str) or not ref:
        return None

    if ref in DERIVED_REFS:
        attr = ref.rsplit(".", 1)[1]          # category_label / business_label
        value = getattr(brief, attr, None)
        return value or None

    if ref.startswith(_EXTRA_PREFIX):
        item = brief.copy.extra_by_id(ref[len(_EXTRA_PREFIX):])
        return item.content or None if item else None

    if ref.startswith(_SLOT_PREFIX):
        name = ref[len(_SLOT_PREFIX):]
        if name not in COPY_SLOTS:            # 알 수 없는 슬롯
            return None
        item = brief.copy.slot(name)
        return item.content or None if item else None

    return None


def known_content_refs(brief: CreativeBrief) -> Tuple[str, ...]:
    """해석 가능한 참조 목록. 에러 메시지에 후보를 실어 주기 위한 것."""
    out = [r for r in DERIVED_REFS if getattr(brief, r.rsplit(".", 1)[1], None)]
    out += [
        f"{_SLOT_PREFIX}{name}"
        for name in COPY_SLOTS
        if (brief.copy.slot(name) and brief.copy.slot(name).content)
    ]
    out += [f"{_EXTRA_PREFIX}{item.id}" for item in brief.copy.extra if item.content]
    return tuple(out)


__all__ = [
    "COPY_SLOTS",
    "DERIVED_REFS",
    "CONTENT_SOURCES",
    "CopyItem",
    "CopyExtra",
    "BriefCopy",
    "CreativeBrief",
    "normalize_preferred_color",
    "resolve_content_ref",
    "known_content_refs",
]

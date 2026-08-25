"""사용자의 짧은 시각 요구 → `VisualPromptSpec` (프롬프트 구체화 · ).

배치 — `copy_model/copy_model/visual_prompt_spec.py`
무엇인가
   챗봇이 모은 `tone` · `keywords` · `request` (+ 선택적 `background_context`)를
    **이미지 생성에 필요한 시각 정보**로 바꾼다.

    "촉촉하고 깨끗하게"
        ↓
    palette · lighting · texture · mood · composition ·
    background · subject_treatment · avoid
경계 — **여기서 다루지 않는 것**
    ✗ grid · col_span · max_lines · typography hierarchy
    ✗ copy/product overlap · product placement layout · 전체 RenderSpec
    → 그건 **AI 디자인 플래너** 책임이다. 이 모듈은 **시각 언어만** 만든다.

`BackgroundContext` 와의 관계
    background_context 배경 참고 **이미지** → Vision 추출 (background.py · 기존)
     VisualPromptSpec 사용자 **텍스트** 요구 → LLM 구체화 (이 모듈)

   앞 5축(palette · lighting · texture · mood · composition)은
    **필드명·타입이 같다.** 새 어휘를 만들지 않고 그대로 이어받는다.
우선순위 (확정)
    명시적인 사용자 텍스트 요구 > reference image background_context
    · reference 는 **사용자가 명시하지 않은 축만** 보완한다
    · `usable=False` 면 쓰지 않는다
    · 둘 다 없으면 **비운다** — 억지로 채우지 않는다

fallback
    LLM 이 실패해도 이 모듈은 **항상 VisualPromptSpec 을 돌려준다.**
   규칙 기반 fallback 으로 tone/keywords/request 를 축에 매핑한다.
    → 구체화 실패가 **포스터 제작을 막지 않는다.**
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

#: 이 계약의 판번호. 변경 시 기록에 남긴다.
VISUAL_PROMPT_SPEC_VERSION = "v1"

#: 축 이름 — 8개. 이 목록을 늘리지 않는다.
#: 앞 5개는 `BackgroundContext` 와 필드명·타입이 같다.
SHARED_AXES = ("palette", "lighting", "texture", "mood", "composition")
OWN_AXES = ("background", "subject_treatment", "avoid")
ALL_AXES = SHARED_AXES + OWN_AXES

#: 축별 출처. report-only — 프롬프트 문자열로 나가지 않는다.
SOURCE_USER = "user"
SOURCE_REFERENCE = "reference"
SOURCE_EMPTY = "empty"


class VisualPromptSpec(BaseModel):
    """구체화 결과. 8필드. 명시되지 않은 축은 비워 둔다.

     `subject_treatment` 는 product / service **공용** 의미다.
        product 제품을 어떻게 보이게 할지 (단독 · 정면 · 질감이 드러나게 …)
        service 공간/활동을 어떻게 보이게 할지 (넓은 공간감 · 활동 중인 분위기 …)

     `avoid` 는 **1차에서 구조화 결과에만 보존**한다.
       diffusion negative 반영은 후속이다.
       positive prompt 에 `without ...` 같은 문구를 넣지 않는다.
    """

    palette: List[str] = Field(default_factory=list) # 색감
    lighting: Optional[str] = None # 조명
    texture: List[str] = Field(default_factory=list) # 질감
    mood: Optional[str] = None # 분위기
    composition: Optional[str] = None # 구도
    background: Optional[str] = None # 배경 자체의 서술
    subject_treatment: Optional[str] = None # 대상 표현
    avoid: List[str] = Field(default_factory=list) # 금지 요소 (1차 보존만)

    def is_empty(self) -> bool:
        """어떤 축도 채워지지 않았는가."""
        return not any([self.palette, self.lighting, self.texture, self.mood,
                        self.composition, self.background, self.subject_treatment])

    def filled_axes(self) -> tuple:
        return tuple(a for a in ALL_AXES if _has(getattr(self, a)))


# ──────────────────────────────────────────────────────────────────────────
# 정규화 — background.py 의 `_clean_list` / `_clean_str` 과 같은 규칙
# ──────────────────────────────────────────────────────────────────────────
def _clean_list(value: Any, limit: int = 4) -> List[str]:
    """문자열 항목만 인정한다. 리스트가 아니거나 비-문자열 항목은 버린다."""
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _clean_str(value: Any) -> Optional[str]:
    """실제 문자열일 때만 인정한다. 그 외 타입은 None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _has(value: Any) -> bool:
    if isinstance(value, list):
        return bool(value)
    return value is not None and value != ""


def is_ascii_text(value: Any) -> bool:
    """언어 게이트 — 이 값이 diffusion 에 실어도 되는 영어인가.

    왜 필요한가.
      지시문에서 "영어로 써라" 고 해도 LLM 이 항상 지키지는 않는다.
      지시문은 계약이 아니다 — 계약은 코드가 건다.

    무엇을 검사하는가 — "한국어인가" 가 아니라 "ASCII 인가" 다.
       CJK 만 막으면 다른 비-라틴 문자가 그대로 통과한다.
      토큰 비효율은 한국어만의 문제가 아니다.

    이 함수는 판정만 한다. 버리는 결정은 builder 가 한다.
    """
    if isinstance(value, list):
        return all(is_ascii_text(v) for v in value)
    if not isinstance(value, str):
        return True
    return value.isascii()


def normalize(raw: Any) -> VisualPromptSpec:
    """LLM 출력을 서버 규칙으로 정규화한다. 신뢰하지 않고 타입까지 방어한다.

    없는 축을 지어내지 않는다 — 없으면 그대로 빈 값이다.
    """
    if not isinstance(raw, dict):
        raw = {}
    return VisualPromptSpec(
        palette=_clean_list(raw.get("palette"), limit=4),
        lighting=_clean_str(raw.get("lighting")),
        texture=_clean_list(raw.get("texture"), limit=4),
        mood=_clean_str(raw.get("mood")),
        composition=_clean_str(raw.get("composition")),
        background=_clean_str(raw.get("background")),
        subject_treatment=_clean_str(raw.get("subject_treatment")),
        avoid=_clean_list(raw.get("avoid"), limit=6),
    )


# ──────────────────────────────────────────────────────────────────────────
# reference 병합 — deterministic
# ──────────────────────────────────────────────────────────────────────────
def merge_reference(spec: VisualPromptSpec,
                    background_context: Optional[Dict[str, Any]]
                    ) -> tuple[VisualPromptSpec, Dict[str, str]]:
    """사용자가 **명시하지 않은 축만** reference 로 보완한다.

     LLM 이 아니라 코드가 병합한다 — 그래야 축별 출처를 기록할 수 있다.

     `background_context` 는 `apply_background_context()` 가 저장한 모양이다
      (`usable` 은 이미 걸러져 있고, 없으면 키 자체가 없다).
     그래도 방어적으로 `usable is False` 면 쓰지 않는다.

    Returns (병합된 spec, 축별 출처)
    """
    source: Dict[str, str] = {
        a: (SOURCE_USER if _has(getattr(spec, a)) else SOURCE_EMPTY) for a in ALL_AXES
    }

    if not isinstance(background_context, dict) or background_context.get("usable") is False:
        return spec, source

    merged = spec.model_copy(deep=True)
    for axis in SHARED_AXES: # 공유 5축만 보완한다
        if _has(getattr(merged, axis)):
            continue # 사용자 요구가 이긴다
        value = background_context.get(axis)
        value = (_clean_list(value, limit=4) if axis in ("palette", "texture")
                 else _clean_str(value))
        if _has(value):
            setattr(merged, axis, value)
            source[axis] = SOURCE_REFERENCE
    return merged, source


# ──────────────────────────────────────────────────────────────────────────
# fallback — LLM 없이 규칙만으로 (1단계)
# ──────────────────────────────────────────────────────────────────────────
#: tone enum 4개 → 시각 축. 챗봇이 보장하는 값이라 안전하게 매핑할 수 있다.
#: 없는 축은 비워 둔다 — 억지로 채우지 않는다.
#:
#: 값을 영어로 바꿨다.
#: 이 값들은 사용자에게 보이는 문구가 아니라 diffusion 에 들어가는 값이다.
#: CLIP BPE 는 영어 중심이라 한국어는 같은 뜻에서 3~6배 토큰을 쓴다 (실측).
#: 77 예산 안에서 같은 정보를 더 많이 실으려면 영어여야 한다.
#: 사용자 화면 문구를 영어로 바꾸는 것이 아니다 — 여기는 모델 입력 경로다.
_TONE_AXES: Dict[str, Dict[str, Any]] = {
    "warm": {
        "palette": ["warm beige", "soft cream"],
        "lighting": "soft natural light",
        "mood": "warm and comfortable",
    },
    "energetic": {
        "palette": ["vivid contrasting colors"],
        "lighting": "bright crisp light",
        "mood": "lively and upbeat",
    },
    "luxury": {
        "palette": ["deep tones", "muted mid tones"],
        "lighting": "low angled subtle light",
        "mood": "calm and luxurious",
    },
    "simple": {
        "palette": ["bright neutral tones"],
        "lighting": "even diffused light",
        "mood": "clean and understated",
    },
}

#: subject_kind 별 기본 대상 표현. 영어.
_SUBJECT_TREATMENT = {
    "product": "single product shown clearly",
    "service": "natural sense of space and atmosphere",
}

# ──────────────────────────────────────────────────────────────────────────
# 업종별 장면 — "업종별로 나누지 않는다" 를 여기서만 뒤집는다
# ──────────────────────────────────────────────────────────────────────────
#
# 원래 원칙과 왜 뒤집는가
#
# 원래 원칙은 "업종별 템플릿을 만들지 않는다. 업종 차이는 사용자 prompt 가
# 담당한다" 였다. 그 원칙은 정상 경로(LLM)에서는 여전히 유효하다 —
# LLM 이 한국어 요청을 읽고 업종에 맞는 영어 장면을 만들어 내기 때문이다.
#
# 그러나 fallback 에는 번역기가 없다.
# 한국어 keywords/request 를 버리고 나면 업종을 알려 줄 것이 아무것도
# 남지 않는다. 학원이든 체육관이든 같은 문장이 나온다.
# 그건 이번에 고치려는 결함 그 자체다 (2026-08-24 실측).
#
# 그래서 "업종 차이는 사용자 prompt 가 담당한다" 는
# LLM 경로에 한정된 원칙으로 범위를 좁힌다.
# fallback 은 업종을 스스로 들고 있어야 한다.
#
# 왜 service 만 채우는가 — product 는 이미 서버가 붙인다
#
# poster_model.resolve_prompt() 가 앞에 baseline 을 붙인다.
# product PROMPT_TEMPLATES[food|beauty|goods] 업종별로 이미 있음
# service SERVICE_QUALITY_BASELINE 업종 중립 하나뿐
#
# product 에 여기서 또 배경을 넣으면 같은 뜻이 두 번 들어가고
# 77 토큰 예산만 태운다 (prompt_budget 이 지키려는 그 예산이다).
# 그래서 product 는 비워 둔다 — 없어서가 아니라 중복이라서다.
#
#: category enum 은 챗봇이 보장한다 (copy_model.chatbot).
#: product food | beauty | goods
#: service academy | sports
_CATEGORY_SCENE: Dict[str, Dict[str, Any]] = {
    "academy": {
        "background": "tutoring classroom interior with desks and whiteboard",
        "composition": "wide view of an empty study space",
    },
    "sports": {
        "background": "training gym interior with exercise equipment",
        "composition": "open training floor seen from a wide angle",
    },
}


def fallback_spec(tone: Optional[str] = None,
                  keywords: Optional[List[str]] = None,
                  request: Optional[str] = None,
                  subject_kind: str = "product",
                  category: Optional[str] = None) -> VisualPromptSpec:
    """LLM 없이 만드는 VisualPromptSpec. 결과 값은 전부 영어다.

    두 자리에서 쓴다.
     ① LLM 호출이 실패했을 때 (1단계)
     ② 1단계 구현에서 LLM 없이 경로를 먼저 닫을 때

     `keywords` 를 더 이상 문자열에 붙이지 않는다.
       keywords 는 사용자가 쓴 한국어다 ("수분" · "저자극").
       fallback 에는 번역기가 없다 — 그대로 붙이면 한국어가 CLIP 으로 간다.
      실측 기준 한국어 25 tok vs 영어 4 tok — 예산을 그것만으로 태운다.
      그래서 지어내지 않고 버린다. 대신 버렸다는 사실을 남긴다.

       keywords 반영은 정상 경로(LLM)의 책임이다 — LLM 이 영어로 번역해 낸다.
       fallback 은 품질이 낮아지는 경로이지 같은 품질의 경로가 아니다.

     category — _CATEGORY_SCENE 참고.
      업종을 아는 축(background/composition)만 채운다.
       product 는 서버가 이미 업종별 baseline 을 붙이므로 비어 있는 게 정상이다.
      모르는 업종이면 지어내지 않고 비운다.
    """
    axes = dict(_TONE_AXES.get(tone or "", {}))
    treatment = _SUBJECT_TREATMENT.get(subject_kind, _SUBJECT_TREATMENT["product"])
    scene = dict(_CATEGORY_SCENE.get(category or "", {}))

    return VisualPromptSpec(
        palette=_clean_list(axes.get("palette"), limit=4),
        lighting=_clean_str(axes.get("lighting")),
        texture=[], # 근거 없음 — 비운다
        mood=_clean_str(axes.get("mood")),
        composition=_clean_str(scene.get("composition")),
        background=_clean_str(scene.get("background")),
        subject_treatment=treatment,
        avoid=[],
    )


__all__ = [
    "VISUAL_PROMPT_SPEC_VERSION",
    "SHARED_AXES",
    "OWN_AXES",
    "ALL_AXES",
    "SOURCE_USER",
    "SOURCE_REFERENCE",
    "SOURCE_EMPTY",
    "VisualPromptSpec",
    "is_ascii_text",
    "normalize",
    "merge_reference",
    "fallback_spec",
]

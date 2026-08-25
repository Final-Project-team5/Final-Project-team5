"""`VisualPromptSpec` → `visual_prompt` 문자열 ( deterministic builder · · 개정).

배치 — `copy_model/copy_model/visual_prompt.py`

이 모듈이 만드는 것은 **사용자 시각 요구 부분뿐**이다.

    quality baseline + visual_prompt + 경로별 suffix
    └── poster_model ──┘ └── 이 모듈 ──┘ └── poster_model ──┘

그래서 카테고리 품질 템플릿(`PROMPT_TEMPLATES`)을 여기에 두지 않는다.
   복제하면 poster_model/pipeline/config.py 와 두 곳이 된다.

 LLM 을 부르지 않는다. 같은 입력 → 항상 같은 출력이다.

══════════════════════════════════════════════════════════════════════════
개정 — 세 가지가 바뀌었다
══════════════════════════════════════════════════════════════════════════

① 문자 상한(`MAX_CHARS`) 을 최종 방어선으로 쓰지 않는다
     문자 수는 토큰 수가 아니다. 한국어 11자가 11토큰이 아니다.
     실제 예산 집행은 poster_model 이 진짜 tokenizer 로 한다
        (`poster_model/prompt_budget.py` · ).
     여기서는 "concise 하게 만든다" 까지만 한다 — 상한은 안전망으로만 남긴다.

② 축 순서를 subject_kind 별로 나눈다
      product 와 service 는 중요한 축이 다르다.
     조립 순서 = 보존 우선순위다. 예산이 부족하면 뒤에서부터 버린다.

③ 한 축 = 한 쉼표 조각 을 불변식으로 만든다
     예전에는 `palette=["a","b"]` 가 쉼표 조각 2개가 됐다.
     그러면 poster_model 이 뒤에서 자를 때 한 축의 절반만 남는다.
     그래서 리스트 축은 " and " 로 잇는다 — 그래야 드롭 단위 = 축 이다.

 `avoid` 는 여전히 넣지 않는다 — 1차에서는 구조화 결과에만 보존한다.
   positive prompt 에 `without ...` 을 억지로 넣지 않는다.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .visual_prompt_spec import VisualPromptSpec, is_ascii_text

#: builder 판번호. 에서 v2 로 올린다 (조립 규칙이 바뀌었다).
VISUAL_PROMPT_BUILDER_VERSION = "v2"

# ──────────────────────────────────────────────────────────────────────────
# 보존 우선순위 (사용자 확정안)
# ──────────────────────────────────────────────────────────────────────────
#: 앞이 더 중요하다. 예산이 부족하면 뒤에서부터 버린다.
#: 그리고 앞쪽이 diffusion 에서 더 강하게 작용한다 — 두 목적이 같은 방향이다.
#:
#: 이 순서는 고정 template 가 아니다.
#: "무엇을 쓸지" 가 아니라 "예산이 모자랄 때 무엇부터 포기할지" 다.
#:
#: LLM 에게 매번 중요도를 묻지 않는다 — 여기서 한 번 정한다.
AXIS_PRIORITY: Dict[str, Tuple[str, ...]] = {
    # 제품 — 제품을 어떻게 보이게 할지 > 배경 > 빛 > 색 > 구도 > 분위기 > 질감
    "product": ("subject_treatment", "background", "lighting", "palette",
                "composition", "mood", "texture"),
    # 서비스 — 공간 자체가 주인공이라 구도가 빛보다 앞선다
    "service": ("subject_treatment", "background", "composition", "lighting",
                "mood", "palette", "texture"),
}

#: subject_kind 를 모를 때. 기존 호출 호환 — product 로 본다.
DEFAULT_SUBJECT_KIND = "product"

#: 하위호환 — 예전 이름. product 순서를 가리킨다.
AXIS_ORDER = AXIS_PRIORITY["product"]

#: 리스트 축을 몇 개까지 실을지. concise 를 구조로 강제한다.
#: spec 자체는 4개까지 담을 수 있다 — 담는 것과 싣는 것은 다르다.
#: VisualPromptSpec = 풍부한 내부 표현
#: visual_prompt = 예산 안에서 선택된 표현
LIST_AXIS_LIMIT = 2

#: 리스트 축 결합자. 쉼표가 아니다 — §③ 불변식 때문이다.
LIST_JOINER = " and "

#: 최종 문자열 길이 상한 (문자 수). 이제는 안전망일 뿐이다.
#: 실제 77-token 보장은 poster_model/prompt_budget.py 가 한다.
#: 여기 값이 토큰 예산을 뜻한다고 읽지 마라.
MAX_CHARS = 320


def _render_axis(spec: VisualPromptSpec, axis: str) -> Optional[str]:
    """한 축을 쉼표 없는 한 조각으로 만든다. 비었으면 None."""
    value = getattr(spec, axis, None)
    if isinstance(value, list):
        items = [v.strip() for v in value if isinstance(v, str) and v.strip()]
        if not items:
            return None
        return LIST_JOINER.join(items[:LIST_AXIS_LIMIT])
    if isinstance(value, str):
        # 축 안에 쉼표가 있으면 조각이 쪼개진다 → 불변식이 깨진다.
        # LLM 이 "a, b" 처럼 낼 수 있으므로 여기서 결합자로 바꾼다.
        text = value.strip().strip(",").strip()
        if not text:
            return None
        if "," in text:
            items = [p.strip() for p in text.split(",") if p.strip()]
            text = LIST_JOINER.join(items[:LIST_AXIS_LIMIT])
        return text
    return None


def segments(spec: VisualPromptSpec,
             subject_kind: str = DEFAULT_SUBJECT_KIND,
             *,
             ascii_only: bool = True) -> Tuple[List[Tuple[str, str]], List[str]]:
    """(축, 조각) 목록을 보존 우선순위 순서로 돌려준다.

    이것이 이 모듈의 진짜 출력이다.
       문자열은 이걸 이어붙인 것일 뿐이다.
        poster_model 은 문자열을 ", " 로 다시 쪼개서 같은 단위를 얻는다.

    Returns (조각 목록, 언어 게이트에서 버린 축 이름)
    """
    order = AXIS_PRIORITY.get(subject_kind, AXIS_PRIORITY[DEFAULT_SUBJECT_KIND])
    out: List[Tuple[str, str]] = []
    dropped: List[str] = []
    for axis in order:
        text = _render_axis(spec, axis)
        if text is None:
            continue
        if ascii_only and not is_ascii_text(text):
            # 언어 게이트.
            # 지시문이 영어를 요구해도 LLM 이 한국어를 낼 수 있다.
            # 그대로 실으면 예산을 3~6배로 태우고 효과는 검증되지 않았다.
            # 그래서 버린다. 그리고 버렸다고 기록한다.
            dropped.append(axis)
            continue
        out.append((axis, text))
    return out, dropped


def build_visual_prompt(spec: VisualPromptSpec,
                        subject_kind: str = DEFAULT_SUBJECT_KIND,
                        max_chars: int = MAX_CHARS,
                        *,
                        ascii_only: bool = True) -> str:
    """사용자 시각 요구 부분만 문자열로 만든다.

    비어 있으면 빈 문자열을 돌려준다 — 그때는 poster_model 이
       quality baseline 만으로 그린다 (기존 동작과 같다).

    여기서 77-token 을 보장하지 않는다.
       그건 poster_model 의 책임이다 — 거기서만 최종 문자열 전체를 안다.
    """
    parts, _dropped = segments(spec, subject_kind, ascii_only=ascii_only)
    texts = [t for _a, t in parts]
    while texts and len(", ".join(texts)) > max_chars:
        texts.pop() # 우선순위 낮은 뒤쪽부터 버린다
    return ", ".join(texts)


def build(spec: VisualPromptSpec,
          subject_kind: str = DEFAULT_SUBJECT_KIND,
          max_chars: int = MAX_CHARS,
          *,
          ascii_only: bool = True) -> dict:
    """문자열 + 무엇이 실렸고 무엇이 왜 빠졌는지 ( 기록용).

     `included_axes` · `dropped_*` 는 report-only 다 — 프롬프트에 나가지 않는다.
    """
    parts, dropped_lang = segments(spec, subject_kind, ascii_only=ascii_only)
    text = build_visual_prompt(spec, subject_kind, max_chars, ascii_only=ascii_only)

    kept = text.split(", ") if text else []
    included = [a for (a, t), _ in zip(parts, kept)]
    dropped_len = [a for a, _t in parts[len(kept):]]

    return {
        "visual_prompt": text,
        "builder_version": VISUAL_PROMPT_BUILDER_VERSION,
        "subject_kind": subject_kind,
        "included_axes": included,
        "dropped_non_ascii": dropped_lang, # 언어 게이트에서 버린 축
        "dropped_by_length": dropped_len, # 안전망 상한에서 버린 축
        "segment_count": len(kept),
    }


__all__ = [
    "VISUAL_PROMPT_BUILDER_VERSION",
    "AXIS_PRIORITY",
    "AXIS_ORDER",
    "DEFAULT_SUBJECT_KIND",
    "LIST_AXIS_LIMIT",
    "LIST_JOINER",
    "MAX_CHARS",
    "segments",
    "build_visual_prompt",
    "build",
]

"""LLM 구체화 + 서비스 진입점.

LLM 을 부르는 코드와 순수 규칙 코드를 파일로 갈라 둔다.

흐름
   완성된 spec (+ optional background_context)
        ↓ LLM 1회
    VisualPromptSpec ← visual_prompt_spec.normalize()
        ↓ deterministic merge ← visual_prompt_spec.merge_reference()
    (병합된 spec, 축별 source)
        ↓ deterministic builder ← visual_prompt.build()
    visual_prompt 문자열

최종 문자열은 오직 deterministic builder 만 만든다.
    LLM 이 문자열을 직접 만들지 않는다 — 구조만 낸다.

fallback
    LLM 이 어떤 이유로든 실패하면 규칙 fallback 으로 내려간다.
    그리고 정상 응답을 돌려준다 — 예외를 밖으로 던지지 않는다.
    실패를 조용히 삼키지 않는다 — `source.origin` 과 `meta.error` 에 남긴다.

    · LLM 성공 origin = "llm"
    · LLM 실패 origin = "fallback" + meta.error 에 사유
    · 아무 근거 없음 origin = "fallback" (tone 도 없을 때)
경계
    ✗ grid · typography · layout · RenderSpec — Planner 책임이다.
    ✗ avoid → negative prompt 연결 — 1차 범위 밖 (구조에만 보존).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .visual_prompt import build as build_prompt
from .visual_prompt_spec import (VISUAL_PROMPT_SPEC_VERSION, VisualPromptSpec,
                                 fallback_spec, is_ascii_text, merge_reference,
                                 normalize)

#: 이 서비스의 판번호 (구체화 지시문이 바뀌면 올린다).
#: 출력 언어를 영어로 바꿨으므로 c2.
#: 2채널 병합 — 출력을 2채널로 나눴으므로 c3.
#: c4 — 서비스형에서 "활동" 대신 "공간" 을 묘사하도록 지시문을 고쳤다.
#: 2026-08-24 실측에서 LLM 이 `personal training in active gym space` 처럼
#: 사람이 있어야 성립하는 표현을 냈고, 같은 응답의 `avoid` 에는 `people` 이
#: 들어 있었다. 한 응답 안에서 서로 반대되는 말을 한 것이다.
#: 실제로 이미지를 망치는 것은 positive 축이다 (`avoid` 는 조립기가 버린다).
#: c5 — 업종 이름을 값에 남기지 않도록 고쳤다.
#: 2026-08-26 실측에서 학원이 `academy interior space` 로 나왔고, 이미지 모델이
#: 강의실을 그리지 않고 로비·라운지·거실 같은 일반적인 실내를 냈다. `gym` 은
#: 단어 자체가 기구 있는 공간을 가리켜 정상이었고, 업종에 따라 결과가 갈렸다.
#: 물건을 덧붙이는 것(`academy interior with desks and whiteboard`)만으로는
#: 부족해 사무실 느낌이 남았고, 업종 이름을 빼야 `classroom` 이 나왔다.
CONCRETIZE_VERSION = "c5"

#: 구체화 호출의 temperature. generator 쪽(0.9)과 일부러 다르게 둔다.
#:
#: 문구 생성은 후보를 다양하게 뽑는 것이 목적이라 높은 값이 맞다.
#: 시각 프롬프트는 반대다 — 같은 요청이면 같은 장면이 나와야 한다.
#:
#: 낮추는 이유 두 가지
#: ① draft 3장의 차이는 seed 에서만 와야 한다.
#: 프롬프트까지 흔들리면 무엇 때문에 달라졌는지 추적이 안 된다.
#: ② 시연 재현성 — 같은 입력을 두 번 넣었을 때 같은 결과가 나와야 한다.
CONCRETIZE_TEMPERATURE = 0.2

#: LLM 출력 채널 이름. 이 두 개가 A+ 의 핵심이다.
#: 채널 → 출처 매핑은 코드가 한다. LLM 은 채널에 넣기만 한다.
CH_REQUEST = "from_request" # 사용자 요구에서 근거를 찾은 것 → user
CH_REFERENCE = "from_reference" # 제공된 배경 참고를 옮긴 것 → reference

ORIGIN_LLM = "llm"
ORIGIN_FALLBACK = "fallback"
#: COPY_MOCK=1 로 의도적으로 LLM 을 건너뛴 경우.
#:
#: fallback 과 반드시 구분한다.
#: fallback 은 실패의 결과다 — 로그에서 조사 대상이어야 한다.
#: mock 은 정상 동작이다 — 조사할 것이 없다.
#: 둘을 같은 값으로 내보내면 시연 때마다 가짜 장애가 보고된다.
ORIGIN_MOCK = "mock"

#: LLM 에게 주는 지시문.
#:
#: 세 가지를 지킨다.
#: ① 없는 축을 지어내지 말라고 명시한다 (테스트 조건)
#: ② 레이아웃/타이포/문구 축을 금지한다 (Planner 책임과 분리)
#: ③ 최종 문자열을 만들지 말라고 한다 — 조립은 코드가 한다
#: ④ — 값을 영어로 낸다. 그리고 짧게 낸다.
#:
#: 왜 영어인가 (실측)
#: 이 값은 사용자에게 보이는 문구가 아니라 CLIP text encoder 입력이다.
#: 같은 뜻에서 한국어는 영어의 3~6배 토큰을 쓴다.
#: "제품 하나가 또렷하게 보이도록" 25 tok vs "single product shown clearly" 4 tok
#: 예산이 77 이므로 이 차이가 곧바로 버려지는 축의 수가 된다.
#: 한국어가 CLIP 에서 무의미하다는 뜻이 아니다 —
#: 이 프로젝트 기준으로 토큰 효율이 크게 불리하고 효과도 검증되지 않았다.
#:
#: 지시문은 계약이 아니다. 모델이 한국어를 낼 수 있다.
#: 실제 보장은 builder 의 언어 게이트가 한다 (`visual_prompt.segments`).
CONCRETIZE_INSTRUCTION = """\
너는 광고 포스터의 **이미지 생성**에 쓸 시각 정보를 정리한다.
사용자의 짧고 추상적인 요구를 읽고, 이미지 생성 모델이 쓸 수 있는
구체적인 시각 언어로 바꿔라.
반드시 아래 JSON 스키마로만 답한다.

{
  "from_request": {
    "palette": string[], // 색감 1~2개. 예: "warm beige", "deep green"
    "lighting": string|null, // 조명 한 마디. 예: "soft natural light"
    "texture": string[], // 질감 0~2개. 예: "matte paper"
    "mood": string|null, // 분위기 한 마디. 예: "calm and premium"
    "composition": string|null, // 구도 한 마디. 예: "centered with wide margins"
    "background": string|null, // 배경 서술. 예: "smooth solid studio backdrop"
    "subject_treatment": string|null, // 대상을 어떻게 보이게 할지
    "avoid": string[] // 이미지에 없어야 할 요소. 예: "text", "people"
  },
  "from_reference": {
    "palette": string[], "lighting": string|null, "texture": string[],
    "mood": string|null, "composition": string|null
  }
}

두 칸의 뜻

- "from_request" : **사용자가 말한 요구**에서 근거를 찾은 것만 넣는다.
- "from_reference" : 아래 [배경 참고]에 값이 주어졌을 때, **그 뜻을 영어로 옮긴 것**만
                    넣는다. 배경 참고가 없으면 전부 비운다.

매우 중요 — 네가 하지 않는 일

- **어느 쪽을 쓸지 고르지 마라.** 두 칸을 다 채우면 된다.
 같은 축에 둘 다 값이 있어도 괜찮다. 무엇이 이기는지는 **서버가 정한다.**
- **출처를 표시하지 마라.** 어느 칸에 넣었는지가 곧 출처다.
배경 참고 값을 "from_request" 에 넣지 마라. 그 반대도 마찬가지다.
배경 참고를 **번역만** 해라. 없는 걸 덧붙이거나 더 예쁘게 각색하지 마라.
지켜야 할 것
값은 반드시 **영어**로 쓴다. 한국어를 값에 넣지 마라.
 이 값은 사용자에게 보여 주는 문구가 아니라 이미지 생성 모델에 들어가는
 입력이다. 모델이 영어 캡션으로 학습됐다.
각 값은 **최대 4~5 단어**로 짧게 쓴다. 문장으로 쓰지 마라.
 전체 예산이 매우 좁다(77 토큰). 길면 뒤쪽 축이 통째로 버려진다.
사용자 요구에서 **근거를 찾을 수 없는 축은 반드시 null 또는 [] 로 둔다.**
 그럴듯하게 채우지 마라. 비어 있는 편이 낫다.
위 두 칸과 그 안의 키 외에 다른 키를 만들지 마라.
레이아웃·글자 크기·글꼴·문구 배치·여백 수치는 다루지 마라. 네 역할이 아니다.
완성된 프롬프트 문장을 만들지 마라. 위 구조만 낸다.
사용자가 한국어로 말한 강조점(예: "수분", "저자극")은 뜻을 살려
 영어 시각 어휘로 옮긴다. 음차(romanization)하지 마라.

서비스형(subject_kind=service)에서 특히 지킬 것

- **활동이 아니라 공간을 묘사한다.** 사람이 있어야 성립하는 표현을 쓰지 마라.
    ✗ personal training in active gym space
    ✗ students studying in a classroom
    ✗ instructor coaching a member
    ✓ training gym interior with exercise equipment
    ✓ tutoring classroom interior with desks and whiteboard
 광고 배경에는 사람을 만들지 않는다. 사람이 필요한 장면은 우리가 쓰지 못한다.

- **업종 이름을 값에 남기지 마라. 그 공간에 실제로 있는 물건으로만 쓴다.**
    ✗ academy interior space
    ✗ academy interior with desks and whiteboard   ← academy 가 아직 남아 있다
    ✓ classroom interior with desks and whiteboard
    ✗ sports facility interior
    ✓ gym interior with exercise equipment
 이미지 모델은 "academy" 를 학교 건물로 이해해서 로비를 그린다. 물건을
 덧붙이는 것만으로는 부족하고 업종 이름 자체를 빼야 한다. 이건 없는 걸
 지어내는 것이 아니라 **같은 뜻을 모델이 아는 말로 바꾸는 것**이다.

- **"avoid" 에 넣은 것을 다른 축에서 전제하지 마라.**
  "avoid" 에 "people" 을 넣었으면 "subject_treatment" 나 "background" 에
 사람을 전제한 표현이 들어가면 안 된다. 한 응답 안에서 서로 반대되는 말을
 하는 셈이다.
"""

#: subject_kind 별 대상 설명 (지시문에 넣는 한 줄).
_SUBJECT_HINT = {
    "product": "이 포스터의 주인공은 **제품 하나**다.",
    "service": "이 포스터의 주인공은 **공간·활동**이다. 제품 사진이 아니다.",
}


#: 배경 참고에서 LLM 에 보여줄 축. 공유 5축뿐이다.
_REF_LABELS = (("palette", "색감"), ("lighting", "조명"), ("texture", "질감"),
               ("mood", "분위기"), ("composition", "구도"))


def usable_reference(background_context: Any) -> Optional[Dict[str, Any]]:
    """LLM 에 보여도 되는 배경 참고인가.

     `apply_background_context()` 가 usable=False 면 키 자체를 지우지만,
      방어적으로 여기서도 한 번 더 본다.
     `merge_reference()` 와 같은 판정 규칙이어야 한다 — 안 그러면
       LLM 에는 보여주고 병합은 안 하는 엇갈림이 생긴다.
    """
    if not isinstance(background_context, dict):
        return None
    if background_context.get("usable") is False:
        return None
    if not any(_has(background_context.get(a)) for a, _ko in _REF_LABELS):
        return None
    return background_context


def _has(value: Any) -> bool:
    if isinstance(value, list):
        return bool([v for v in value if v])
    return bool(value)


def _reference_text(background_context: Optional[Dict[str, Any]]) -> str:
    """배경 참고를 LLM 입력에 그대로 보여준다 ( 한국어 그대로).

    여기가 A+ 의 입구다.
       지금까지 이 값은 LLM 을 거치지 않고 코드 병합으로만 들어왔다.
       그래서 한국어인 채로 프롬프트까지 갔고 언어 게이트에 전부 걸렸다.
       이제는 LLM 에게 보여주고 영어로 옮기게 한다.

    그러나 우선순위는 여기서 정하지 않는다.
        LLM 은 그냥 옮기기만 한다. 무엇이 이기는지는 `merge_reference()` 가 정한다.
    """
    ref = usable_reference(background_context)
    if ref is None:
        return ""
    lines = ["", "[배경 참고] — 사용자가 올린 참고 이미지에서 뽑은 값이다.",
             " 아래 값의 **뜻을 영어로 옮겨** \"from_reference\" 에 넣어라.",
             " 이것을 쓸지 말지는 네가 정하지 않는다."]
    for axis, ko in _REF_LABELS:
        value = ref.get(axis)
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value if v)
        if value:
            lines.append(f" - {ko}({axis}): {value}")
    return "\n".join(lines)


def _user_text(spec: Dict[str, Any], subject_kind: str) -> str:
    """LLM 에 보낼 사용자 요구 요약. 완성된 spec 을 읽기만 한다."""
    tone = spec.get("tone")
    keywords = spec.get("keywords")
    request = spec.get("request")
    category = spec.get("category")
    product = spec.get("product")

    lines: List[str] = [_SUBJECT_HINT.get(subject_kind, _SUBJECT_HINT["product"])]
    if category:
        lines.append(f"업종: {category}")
    if product:
        lines.append(f"대상: {product}")
    if tone:
        lines.append(f"원하는 느낌(tone): {tone}")
    if isinstance(keywords, list) and keywords:
        lines.append(f"강조점: {', '.join(str(k) for k in keywords if k)}")
    elif isinstance(keywords, str) and keywords.strip():
        lines.append(f"강조점: {keywords.strip()}")
    if request:
        lines.append(f"추가 요청: {request}")
    ref_block = _reference_text(spec.get("background_context"))
    if ref_block:
        lines.append(ref_block)
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────
# 채널 분리 — 여기서 출처가 결정된다 ( LLM 이 아니라)
# ──────────────────────────────────────────────────────────────────────────
def split_channels(raw: Any) -> tuple[Any, Any]:
    """LLM 출력을 (사용자 채널, 참고 채널) 로 가른다.

    이 함수가 A+ 의 경계다.

       LLM 이 한 일 뜻을 짧은 영어 시각 어휘로 옮겼다
      코드가 하는 일 어느 채널이 어느 출처인지 정한다
                        그리고 무엇이 이기는지 정한다 (`merge_reference`)

     LLM 이 "이건 user 출처야" 라고 말할 수 있는 자리가 없다.
       채널에 넣는 것 말고는 아무 권한이 없다.

    하위호환 — 예전처럼 8축을 평평하게 낸 응답도 받는다.
      그때는 전부 사용자 채널로 본다 ( 종전 동작과 같다).
    """
    if not isinstance(raw, dict):
        return {}, {}
    if CH_REQUEST in raw or CH_REFERENCE in raw:
        return raw.get(CH_REQUEST) or {}, raw.get(CH_REFERENCE) or {}
    return raw, {} # 구형 평면 응답


def _mock_mode() -> bool:
    """`COPY_MOCK=1` 인가.

     config 를 모듈 로드 시점이 아니라 호출 시점에 읽는다.
      테스트가 환경변수를 바꿔 가며 돌리는 경우가 있어서다.
     config import 자체가 실패해도 여기서 예외를 내지 않는다 — 기본은 실서비스다.
    """
    try:
        from . import config
        return bool(getattr(config, "MOCK_MODE", False))
    except Exception: # noqa: BL
        return False


def _call_llm(spec: Dict[str, Any], subject_kind: str) -> dict:
    """구체화 1회 호출. 결과는 아직 신뢰하지 않고 dict 로만 반환한다.

     `vision.py: _call_vision()` 과 같은 형태를 따른다.
    """
    from . import config
    # 클라이언트를 새로 만들지 않는다. generator._client() 를 재사용한다.
    # 그래야 PR #120 에서 들어간 timeout / 재시도 백오프를 그대로 상속받는다.
    # 자체 클라이언트를 만들면 그 방어가 이 경로에만 빠진다.
    from .generator import _client

    resp = _client().chat.completions.create(
        model=config.MODEL_NAME,
        messages=[
            {"role": "system", "content": CONCRETIZE_INSTRUCTION},
            {"role": "user", "content": _user_text(spec, subject_kind)},
        ],
        response_format={"type": "json_object"},
        # generator._chat_json 을 직접 호출하지 않는 이유가 여기다.
        # 그쪽은 temperature=0.9 — 문구 다양성을 위해 튜닝된 값이다.
        # 시각 프롬프트는 같은 입력에 같은 결과가 나와야 한다.
        # 흔들리면 draft 3장의 차이가 seed 때문인지 프롬프트 때문인지
        # 구분할 수 없고, 시연 재현성도 깨진다.
        temperature=CONCRETIZE_TEMPERATURE,
    )
    content = resp.choices[0].message.content
    if not content:
        raise ValueError("구체화 모델이 빈 응답을 반환했습니다.")
    return json.loads(content)


def concretize(spec: Optional[Dict[str, Any]] = None,
               subject_kind: str = "product",
               *,
               llm=None) -> dict:
    """진입점. 어떤 경우에도 예외를 밖으로 던지지 않는다.

    Parameters
        spec 챗봇이 완성한 spec (tone/keywords/request/background_context…)
        subject_kind "product" | "service"
        llm 테스트 주입용. 주면 `_call_llm` 대신 이것을 부른다.

    Returns
        {
          "visual_prompt_spec": {...8필드...},
          "visual_prompt": "...", deterministic builder 결과
          "source": {"origin": "llm"|"fallback", "axes": {축: user|reference|empty}},
          "meta": {...}
        }
    """
    spec = dict(spec or {})
    background_context = spec.get("background_context")
    origin = ORIGIN_LLM
    error: Optional[str] = None
    raw: Any = None

    # 2채널 병합 — 병합에 쓸 reference.
    # 기본은 원본(한국어)이다. LLM 이 영어로 옮겨 주면 그것으로 갈아끼운다.
    # 갈아끼우는 것은 값의 표현뿐이다 — 우선순위도 출처도 그대로다.
    merge_source: Any = background_context
    ref_translated: List[str] = []
    ref_untranslated: List[str] = []

    # ── COPY_MOCK=1 — LLM 을 부르지 않고 고정 영어 프롬프트를 돌려준다 ──
    #
    # 왜 필요한가
    # ① 시연을 비용 0 으로 재현할 수 있어야 한다.
    # ② 테스트 스위트가 키 없이 그대로 통과해야 한다.
    #
    # 값을 따로 만들지 않고 fallback_spec 을 그대로 쓴다.
    # mock 전용 문자열을 별도로 두면 업종이 늘 때 두 군데를 고쳐야 하고
    # 한쪽만 고치는 사고가 난다. 표는 한 곳이어야 한다.
    #
    # origin 은 "mock" 이다 — fallback 과 구분한다 (ORIGIN_MOCK 주석 참고).
    # 테스트 주입(llm=)이 있으면 mock 보다 그쪽이 우선이다 —
    # 주입은 "이 호출자를 써라" 는 명시적 지시이기 때문이다.
    if llm is None and _mock_mode():
        base = fallback_spec(
            tone=spec.get("tone"),
            keywords=spec.get("keywords"),
            request=spec.get("request"),
            subject_kind=subject_kind,
            category=spec.get("category"),
        )
        merged, axes_source = merge_reference(base, merge_source)
        built = build_prompt(merged, subject_kind)
        # meta 키는 정상 경로와 완전히 같아야 한다.
        # mock 에서만 키가 빠지면 그 키를 읽는 쪽이 mock 에서만 터진다.
        # 그건 시연 당일에 발견된다.
        return {
            "visual_prompt_spec": merged.model_dump(),
            "visual_prompt": built["visual_prompt"],
            "source": {"origin": ORIGIN_MOCK, "axes": axes_source},
            "meta": {
                "spec_version": VISUAL_PROMPT_SPEC_VERSION,
                "builder_version": built["builder_version"],
                "concretize_version": CONCRETIZE_VERSION,
                "subject_kind": subject_kind,
                "used_reference": background_context is not None,
                "reference_translated": [],
                "reference_untranslated": [],
                "included_axes": built["included_axes"],
                "dropped_non_ascii": built["dropped_non_ascii"],
                "error": None, # mock 은 실패가 아니다
            },
        }

    caller = llm or _call_llm
    try:
        raw = caller(spec, subject_kind)
        user_raw, ref_raw = split_channels(raw) # 출처는 코드가 가른다
        base = normalize(user_raw)
        # LLM 이 아무 축도 못 채웠으면 실패로 본다 — 빈 결과를 그대로 쓰지 않는다.
        if base.is_empty():
            raise ValueError("구체화 결과가 비어 있습니다.")

        # 참고 채널 — 영어로 옮겨진 값만 받아 쓴다.
        original = usable_reference(background_context)
        if original is not None:
            ref_en = normalize(ref_raw)
            # 원본에서 출발해서 필요한 축만 영어로 갈아끼운다.
            # 축 구성을 바꾸지 않는다 — merge_reference 가 보는 모양은 그대로다.
            swapped: Dict[str, Any] = dict(original)
            for axis, _ko in _REF_LABELS:
                origin_value = original.get(axis)
                if not _has(origin_value):
                    continue
                # 이미 영어면 번역이 필요 없다 — 원본을 그대로 쓴다.
                # LLM 이 안 돌려줬다고 멀쩡한 값을 버리면 안 된다.
                # 그리고 나중에 background.py 가 영어를 내게 되면
                # 이 경로가 그대로 맞아떨어진다.
                if is_ascii_text(origin_value):
                    continue # merge_source 원본 유지
                value = getattr(ref_en, axis, None)
                if _has(value) and is_ascii_text(value):
                    swapped[axis] = value # 영어로 갈아끼움
                    ref_translated.append(axis)
                else:
                    # 원본(한국어)을 남겨 두지 않는다.
                    # 남기면 언어 게이트에 어차피 걸리고,
                    # 출처만 reference 로 찍힌 채 프롬프트에는 없는
                    # 엇갈린 기록이 남는다.
                    # 그래서 빼고 뺐다고 남긴다.
                    swapped.pop(axis, None)
                    ref_untranslated.append(axis)
            merge_source = swapped
    except Exception as exc: # noqa: BL
        # 어떤 실패든 여기서 멈춘다. endpoint 실패로 번지지 않는다.
        origin = ORIGIN_FALLBACK
        error = f"{type(exc).__name__}: {exc}"
        base = fallback_spec(
            tone=spec.get("tone"),
            keywords=spec.get("keywords"),
            request=spec.get("request"),
            subject_kind=subject_kind,
            # 업종을 넘긴다 — fallback 에는 번역기가 없어서
            # category 가 없으면 학원/체육관이 같은 문장이 된다.
            category=spec.get("category"),
        )
        # fallback 에는 번역기가 없다. 원본(한국어)이 그대로 병합되고
        # 언어 게이트가 그것을 버린다. 그 사실은 meta 에 남는다.

    # 여기는 손대지 않았다 — 기존 계약 그대로다.
    # user > reference > empty 우선순위도
    # 축별 출처(user/reference/empty) 판정도 여전히 이 코드가 소유한다.
    merged, axes_source = merge_reference(base, merge_source)
    built = build_prompt(merged, subject_kind)

    # 언어 게이트 2차.
    # LLM 이 전부 한국어로 냈다면 게이트가 전부 버린다 → 빈 문자열.
    # 그러면 구체화가 아무 일도 하지 않은 것이 된다.
    # 그건 실패다. 실패는 fallback 이 받는다 — 영어 fallback 이다.
    # 조용히 빈 프롬프트를 흘려보내지 않는다.
    if origin == ORIGIN_LLM and not built["visual_prompt"]:
        origin = ORIGIN_FALLBACK
        dropped = built["dropped_non_ascii"]
        error = (f"LanguageGate: 구체화 결과가 영어가 아니어서 전부 버려졌습니다 "
                 f"(dropped={dropped})") if dropped else \
                "LanguageGate: 조립 결과가 비었습니다"
        merged, axes_source = merge_reference(
            fallback_spec(tone=spec.get("tone"),
                          keywords=spec.get("keywords"),
                          request=spec.get("request"),
                          subject_kind=subject_kind,
                          category=spec.get("category")),
            merge_source) # 영어로 옮겨진 참고가 있으면 그것을 쓴다
        built = build_prompt(merged, subject_kind)

    return {
        "visual_prompt_spec": merged.model_dump(),
        "visual_prompt": built["visual_prompt"],
        "source": {"origin": origin, "axes": axes_source},
        "meta": {
            "spec_version": VISUAL_PROMPT_SPEC_VERSION,
            "builder_version": built["builder_version"],
            "concretize_version": CONCRETIZE_VERSION,
            "subject_kind": subject_kind,
            "used_reference": background_context is not None,
            # 2채널 병합 — 참고가 실제로 살아서 들어갔는가
            # `reference_untranslated` 가 계속 차 있으면
            # 참고 번역 지시가 안 먹고 있다는 신호다
            "reference_translated": ref_translated,
            "reference_untranslated": ref_untranslated,
            "included_axes": built["included_axes"],
            # 언어 게이트에서 버린 축 — 조용히 삼키지 않는다.
            # 이 값이 계속 차 있으면 지시문이 안 먹고 있다는 신호다.
            "dropped_non_ascii": built["dropped_non_ascii"],
            "error": error, # 실패를 조용히 삼키지 않는다
        },
    }


__all__ = [
    "CONCRETIZE_VERSION",
    "CONCRETIZE_INSTRUCTION",
    "CH_REQUEST",
    "CH_REFERENCE",
    "ORIGIN_LLM",
    "ORIGIN_FALLBACK",
    "usable_reference",
    "split_channels",
    "concretize",
]

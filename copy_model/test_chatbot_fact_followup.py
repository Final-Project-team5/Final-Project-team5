"""챗봇 강조점 후속질문(사실값) + 추가요청 자유입력 + 규제 처리 테스트 (mock).

계약(0821): 톤 -> 강조점 -> [후속질문(조건부)] -> 추가요청.
- 후속질문: 사실값 키워드(가격/할인 등) 골랐을 때만. 우선순위 최상위 하나.
- 추가요청: 프리셋 없이 자유 입력(text).
- 자유 입력은 규제 룰 즉시 검증(block 재입력 / warn 경고 / safe 통과).
"""
import os
os.environ["COPY_MOCK"] = "1"

from copy_model.chatbot import (  # noqa: E402
    SuggestRequest, SuggestResponse, suggest_options, _post_fixed,
    _detect_fact_type, _regulation_of_text, FACT_QUESTION, REQUEST_QUESTION,
)


def _run(step, spec, message="선택"):
    return suggest_options(SuggestRequest(
        message=message, mode="fixed", step=step, spec=spec))


# ── 결정적 사실 키워드 판정 ────────────────────────────────
def test_detect_fact_priority():
    assert _detect_fact_type(["할인 행사", "수제"]) == "price"
    assert _detect_fact_type(["접근성(위치·시간)"]) == "place"
    # 가격/할인이 위치보다 우선
    assert _detect_fact_type(["접근성(위치·시간)", "20% 할인"]) == "price"
    # 사실 키워드 없음
    assert _detect_fact_type(["수제", "당일 생산"]) is None
    assert _detect_fact_type(None) is None


def test_detect_fact_no_false_positive_single_char():
    # 한 글자 토큰 오탐 방지(소원님 #100 리뷰): 원/역/분이 일반 키워드에
    # 부분일치해도 후속질문이 뜨면 안 된다.
    for kw in ["전문 지원", "역동적인 느낌", "천연 성분", "밝은 분위기",
               "응원 메시지", "고급 원단", "충분한 구성"]:
        assert _detect_fact_type([kw]) is None, kw


def test_detect_fact_numeric_fact_value():
    # 실제 사실값(숫자+단위)은 정규식으로 정확히 잡는다.
    assert _detect_fact_type(["3900원 특가"]) == "price"   # 숫자+원
    assert _detect_fact_type(["20% 할인"]) == "price"       # 숫자+%
    assert _detect_fact_type(["50 퍼센트"]) == "price"
    assert _detect_fact_type(["강남역 5분"]) == "place"      # 숫자+분(역만으론 안 잡힘)
    assert _detect_fact_type(["2번 출구"]) == "place"
    # 다글자 단어 토큰은 그대로 유지
    assert _detect_fact_type(["역세권 위치"]) == "place"
    assert _detect_fact_type(["가격"]) == "price"


def test_regulation_of_text():
    # 위반 표현
    reg = _regulation_of_text("100% 효과 보장", "food")
    assert reg is not None and reg["severity"] in ("block", "warn")
    # 정상 표현
    assert _regulation_of_text("신메뉴 출시", "food") is None


# ── 후속질문 주입 (keywords 확정 시) ───────────────────────
def test_followup_injected_for_fact_keyword():
    # keywords 확정 응답에 사실 키워드가 있으면 _post_fixed가 후속질문으로 오버라이드.
    # (mock은 keywords를 고정 샘플로 덮어써서 후처리 로직을 직접 검증한다.)
    base = SuggestResponse(
        spec={"category": "food", "keywords": ["할인 행사", "수제"]},
        done=False, step=5, next_step=6, total_steps=6,
        question="다음 질문", options=["a", "b"], allow_multiple=False,
        confirm_message="", meta={})
    req = SuggestRequest(message="선택", mode="fixed", step=5,
                         spec={"category": "food"})
    r = _post_fixed(base, req)
    assert r.input_type == "text"
    assert r.question == FACT_QUESTION["price"]
    assert r.spec.get("_await_fact") == "price"
    assert r.options == []


def test_no_followup_goes_to_request_text():
    # 사실 키워드가 없으면 후속질문 없이 바로 추가요청(text)으로.
    spec = {"category": "food", "keywords": ["수제", "당일 생산"]}
    r = _run(5, spec)
    assert r.input_type == "text"
    assert r.question == REQUEST_QUESTION
    assert "_await_fact" not in r.spec
    assert r.max_length is not None


# ── 후속질문 답변 처리 ─────────────────────────────────────
def test_fact_answer_stored_and_advances():
    spec = {"category": "food", "keywords": ["할인 행사"], "_await_fact": "price"}
    r = _run(5, spec, message="3900원")
    assert r.spec["highlight_fact"] == {
        "type": "token", "value": "3900원", "source": "user_input"}
    assert "_await_fact" not in r.spec
    assert r.question == REQUEST_QUESTION    # 추가요청으로 진행
    assert r.regulation is None


def test_fact_answer_block_reasks():
    # food block 표현(살 빠지는)으로 재입력 유도 확인.
    spec = {"category": "food", "keywords": ["할인 행사"], "_await_fact": "price"}
    r = _run(5, spec, message="살 빠지는 특가")
    assert r.regulation is not None and r.regulation["severity"] == "block"
    assert r.spec.get("_await_fact") == "price"   # 재입력 대기
    assert "highlight_fact" not in r.spec
    assert r.input_type == "text"


def test_fact_answer_skip():
    spec = {"category": "food", "keywords": ["할인 행사"], "_await_fact": "price"}
    r = _run(5, spec, message="없어요")
    assert "highlight_fact" not in r.spec
    assert r.question == REQUEST_QUESTION


def test_fact_answer_has_user_source():
    # Claim-Lock I1(진우님 #100): 저장되는 사실값엔 출처(user_input)가 붙는다.
    spec = {"category": "food", "keywords": ["할인 행사"], "_await_fact": "price"}
    r = _run(5, spec, message="20% 할인")
    assert r.spec["highlight_fact"]["source"] == "user_input"


def test_skip_with_filler_is_skipped():
    # "딱히 없어요"처럼 부가어 붙은 부정도 스킵으로 처리(값 저장 안 함, 진우님 #100).
    for msg in ["딱히 없어요", "특별히 없습니다", "그냥 없음", "모르겠어요",
                "아직 없어요", "글쎄요"]:
        spec = {"category": "food", "keywords": ["할인 행사"], "_await_fact": "price"}
        r = _run(5, spec, message=msg)
        assert "highlight_fact" not in r.spec, msg
        assert r.question == REQUEST_QUESTION, msg


def test_negation_inside_real_value_is_stored():
    # 부정어가 더 큰 의미의 일부인 실제 값은 저장돼야 한다(과잉 스킵 방지).
    spec = {"category": "food", "keywords": ["할인 행사"], "_await_fact": "price"}
    r = _run(5, spec, message="없는 메뉴가 없어요")
    assert "highlight_fact" in r.spec
    assert r.spec["highlight_fact"]["value"] == "없는 메뉴가 없어요"


# ── 추가요청(자유 입력) 처리 ───────────────────────────────
def test_request_answer_done():
    spec = {"category": "food", "keywords": ["수제"]}
    r = _run(6, spec, message="리뉴얼 오픈 기념")
    assert r.done is True
    assert r.spec["request"] == "리뉴얼 오픈 기념"


def test_request_answer_block_reasks():
    spec = {"category": "food", "keywords": ["수제"]}
    r = _run(6, spec, message="다이어트 효과 보장")
    assert r.done is False
    assert r.regulation is not None and r.regulation["severity"] == "block"
    assert r.input_type == "text"


def test_request_answer_skip_done():
    spec = {"category": "food", "keywords": ["수제"]}
    r = _run(6, spec, message="없어요")
    assert r.done is True
    assert "request" not in r.spec


def test_request_answer_skip_with_filler():
    # 추가요청에서도 "딱히 없어요" 스킵 처리(포스터에 실릴 위험 차단, 진우님 #100).
    spec = {"category": "food", "keywords": ["수제"]}
    r = _run(6, spec, message="딱히 없어요")
    assert r.done is True
    assert "request" not in r.spec


# ── 하위호환: 앞 단계(category 등) select 그대로 ───────────
def test_early_steps_still_select():
    r = _run(1, None)
    assert r.input_type == "select"
    assert r.options  # 선택지 존재


if __name__ == "__main__":
    import sys
    import traceback

    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"OK  {t.__name__}")
            passed += 1
        except Exception:
            print(f"XX  {t.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)

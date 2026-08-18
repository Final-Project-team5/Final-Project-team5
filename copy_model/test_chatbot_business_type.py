"""챗봇 business_type 분기(방식 B) 테스트 — mock 모드(비용 0).

검증:
  - 제품형(business_type 없음/product): 기존 동작 불변(하위호환).
  - 서비스형(service): 업종 academy/sports, 질문·강조점 서비스 세트, 1:1 고정.
  - purpose 비율 가드: 서비스형 비정사각(banner/detail) → sns(1:1)로 강제 보정.
"""
import os
os.environ["COPY_MOCK"] = "1"  # import 전에 mock 강제

from copy_model.chatbot import (  # noqa: E402
    SuggestRequest, suggest_options, _apply_aspect_ratio, _effective_flow,
    _business_type, _prompt_bits, PRODUCT_CATEGORIES, SERVICE_CATEGORIES,
)


def _run(step, spec, target_slots=None):
    return suggest_options(SuggestRequest(
        message="선택", mode="fixed", step=step, spec=spec, target_slots=target_slots))


# ── _business_type 정규화 ─────────────────────────────
def test_business_type_default_product():
    assert _business_type(None) == "product"
    assert _business_type({}) == "product"
    assert _business_type({"business_type": "이상값"}) == "product"

def test_business_type_service():
    assert _business_type({"business_type": "service"}) == "service"


# ── 하위호환: 제품형 동작 불변 ─────────────────────────
def test_product_default_flow_unchanged():
    # business_type 없음 → 제품형. 1단계 category = food, 6단계.
    r = _run(1, None)
    assert r.spec["category"] in PRODUCT_CATEGORIES
    assert r.total_steps == 6
    # 2단계 질문(용도)로 넘어감
    assert r.next_step == 2

def test_product_purpose_banner_maps_3x1():
    # 제품형은 banner→3:1 그대로 (가드 영향 없음)
    spec = {"purpose": "banner"}
    _apply_aspect_ratio(spec)
    assert spec["aspect_ratio"] == "3:1"
    assert "purpose_locked" not in spec

def test_product_invalid_purpose_coerced():
    spec = {"purpose": "unknown"}
    _apply_aspect_ratio(spec)
    assert spec["aspect_ratio"] == "1:1"
    assert spec["purpose_invalid"] == "unknown"


# ── 서비스형 분기 ─────────────────────────────────────
def test_service_category_is_service_set():
    r = _run(1, {"business_type": "service"})
    assert r.spec["category"] in SERVICE_CATEGORIES
    assert r.spec["business_type"] == "service"

def test_service_step1_question_overridden():
    flow = _effective_flow(None, "service")
    q = next(s["question"] for s in flow if s["slot"] == "category")
    assert "서비스 업종" in q

def test_service_flow_excludes_product():
    # 8/18 확정: service는 가게/서비스 이름(product) 단계를 챗봇에서 묻지 않는다.
    flow = _effective_flow(None, "service")
    slots = [s["slot"] for s in flow]
    assert "product" not in slots
    assert slots == ["category", "purpose", "tone", "keywords", "request"]
    # 재번호가 1..5로 연속인지 확인(진행률 어긋남 방지).
    assert [s["step"] for s in flow] == [1, 2, 3, 4, 5]

def test_service_total_steps_is_five():
    r = _run(1, {"business_type": "service"})
    assert r.total_steps == 5
    assert r.next_step == 2

def test_product_flow_still_has_product_step():
    # 하위호환: 제품형은 product 단계와 6단계를 그대로 유지.
    flow = _effective_flow(None, "product")
    assert [s["slot"] for s in flow] == [
        "category", "purpose", "product", "tone", "keywords", "request"]

def test_service_keywords_options_are_service_set():
    # service 3단계(tone) 처리하며 다음(4단계 keywords) 선택지를 서비스 세트로 노출.
    r = _run(3, {"business_type": "service"})
    assert r.next_step == 4
    assert "전문성·경력" in r.options

def test_service_purpose_forced_1x1():
    # 서비스형에서 banner가 들어와도 1:1로 강제, 원본은 purpose_locked에 보존
    spec = {"business_type": "service", "purpose": "banner"}
    _apply_aspect_ratio(spec)
    assert spec["purpose"] == "sns"
    assert spec["aspect_ratio"] == "1:1"
    assert spec["purpose_locked"] == "banner"

def test_service_purpose_sns_no_lock():
    spec = {"business_type": "service", "purpose": "sns"}
    _apply_aspect_ratio(spec)
    assert spec["aspect_ratio"] == "1:1"
    assert "purpose_locked" not in spec


# ── 프롬프트 조각 분기 ────────────────────────────────
def test_prompt_bits_service_vs_product():
    p = _prompt_bits("product")
    s = _prompt_bits("service")
    assert "food" in p["category_enum"] and "academy" in s["category_enum"]
    assert "banner" in p["purpose_enum"] and "banner" not in s["purpose_enum"]


if __name__ == "__main__":
    import sys, traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn(); print(f"OK  {fn.__name__}"); passed += 1
        except Exception:
            print(f"XX  {fn.__name__}"); traceback.print_exc()
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)

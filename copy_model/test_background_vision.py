"""배경 레퍼런스 Vision → background_context 분리 테스트 — mock, cost 0."""
import os

os.environ["COPY_MOCK"] = "1"

from pydantic import ValidationError  # noqa: E402

from copy_model.api import app, post_vision_background  # noqa: E402
from copy_model.background import (  # noqa: E402
    BackgroundAdvanceRequest,
    BackgroundContext,
    advance_background_image,
    apply_background_context,
)


TINY_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_background_analysis_returns_visual_language():
    res = advance_background_image(
        BackgroundAdvanceRequest(
            image_data_url=TINY_PNG,
            spec={"business_type": "product", "category": "beauty"},
        )
    )
    ctx = res.context
    assert ctx.usable is True
    assert ctx.palette          # 색감 추출됨
    assert ctx.mood


def test_background_written_only_to_background_context():
    res = advance_background_image(
        BackgroundAdvanceRequest(
            image_data_url=TINY_PNG,
            spec={
                "business_type": "product",
                "category": "beauty",
                "product": "립 틴트",
                "product_context": {"product": "립 틴트"},
            },
        )
    )
    spec = res.meta["spec"]
    # 배경은 background_context로만. product/product_context 오염 금지.
    assert "background_context" in spec
    assert spec["product"] == "립 틴트"
    assert spec["product_context"] == {"product": "립 틴트"}
    assert "palette" in spec["background_context"]


def test_unusable_background_not_written():
    empty = BackgroundContext(usable=False)
    spec = apply_background_context({"product": "립 틴트"}, empty)
    assert "background_context" not in spec
    assert spec["product"] == "립 틴트"


def test_apply_never_touches_product():
    ctx = BackgroundContext(palette=["웜 베이지"], mood="차분한", usable=True)
    spec = apply_background_context(
        {"product": "쿠키", "product_context": {"x": 1}}, ctx
    )
    assert spec["product"] == "쿠키"
    assert spec["product_context"] == {"x": 1}
    assert spec["background_context"]["palette"] == ["웜 베이지"]


def test_invalid_image_rejected():
    try:
        BackgroundAdvanceRequest(
            image_data_url="data:text/plain;base64,aGVsbG8=",
            spec={},
        )
    except ValidationError:
        return
    raise AssertionError("non-image data URL must be rejected")


def test_endpoint_registered_and_response_model():
    route = next(
        r for r in app.routes
        if getattr(r, "path", None) == "/vision/background"
    )
    assert "POST" in route.methods
    assert route.response_model.__name__ == "BackgroundVisionResponse"


def test_endpoint_returns_updated_spec():
    res = post_vision_background(
        BackgroundAdvanceRequest(image_data_url=TINY_PNG, spec={"category": "food"})
    )
    assert res.meta["spec"]["background_context"]["palette"]
    assert res.meta["spec"]["category"] == "food"


# ── production 경로 검증 (소원님 리뷰) ─────────────────────
# OpenAI 호출부(_call_background_vision)만 stub하고 MOCK_MODE를 꺼서
# 실제 analyze_background_image() -> _finalize_background 경로를 직접 탄다.
def _run_prod(raw):
    """비-mock 경로로 raw(LLM 출력 가정)를 finalize까지 통과시킨다."""
    from copy_model import config
    import copy_model.background as bg

    old_mock, old_key = config.MOCK_MODE, config.OPENAI_API_KEY
    old_call = bg._call_background_vision
    config.MOCK_MODE = False
    config.OPENAI_API_KEY = "test-key"          # 실제 호출 안 함(아래 stub)
    bg._call_background_vision = lambda req: raw
    try:
        return bg.analyze_background_image(
            bg.BackgroundImageRequest(image_data_url=TINY_PNG)
        )
    finally:
        bg._call_background_vision = old_call
        config.MOCK_MODE = old_mock
        config.OPENAI_API_KEY = old_key


def test_prod_string_usable_false_is_rejected():
    # LLM이 boolean 아닌 문자열 "false"를 반환해도 usable=False로 처리돼야 한다.
    res = _run_prod({
        "usable": "false",
        "palette": ["웜 베이지"], "mood": "차분한",
    })
    assert res.context.usable is False
    spec = apply_background_context({"product": "립 틴트"}, res.context)
    assert "background_context" not in spec       # 기록되면 안 됨
    assert spec["product"] == "립 틴트"


def test_prod_string_usable_true_is_also_rejected():
    # "true"(문자열)도 boolean이 아니므로 인정하지 않는다(strict).
    res = _run_prod({"usable": "true", "palette": ["웜 베이지"]})
    assert res.context.usable is False


def test_prod_usable_false_bool():
    res = _run_prod({"usable": False, "palette": ["웜 베이지"]})
    assert res.context.usable is False


def test_prod_usable_true_bool_records():
    res = _run_prod({
        "usable": True,
        "palette": ["웜 베이지"], "lighting": "부드러운 자연광", "mood": "차분한",
    })
    assert res.context.usable is True
    spec = apply_background_context({"product": "립 틴트"}, res.context)
    assert spec["background_context"]["palette"] == ["웜 베이지"]
    assert spec["product"] == "립 틴트"           # product 무오염


def test_prod_missing_usable_defaults_false():
    # usable 키 누락 → 안전하게 False(기록 안 함).
    res = _run_prod({"palette": ["웜 베이지"]})
    assert res.context.usable is False


def test_prod_empty_or_malformed_json():
    # 빈 dict / None 모두 크래시 없이 usable=False.
    assert _run_prod({}).context.usable is False
    assert _run_prod(None).context.usable is False


def test_prod_wrong_types_are_scrubbed():
    # palette 문자열, texture 숫자 항목, mood 객체, lighting 숫자 → 전부 버려짐.
    res = _run_prod({
        "usable": True,
        "palette": "not-a-list",
        "texture": [1, 2, {"x": 1}],
        "mood": {"nested": "obj"},
        "lighting": 42,
        "composition": None,
    })
    ctx = res.context
    assert ctx.palette == []
    assert ctx.texture == []
    assert ctx.mood is None
    assert ctx.lighting is None
    # 유효한 시각 근거가 하나도 없으므로 usable도 False.
    assert ctx.usable is False


def test_prod_partial_valid_types_kept():
    # 유효한 문자열 항목만 선별적으로 남는다.
    res = _run_prod({
        "usable": True,
        "palette": ["웜 베이지", 123, "소프트 크림"],   # 숫자만 제거
        "mood": "차분한",
    })
    assert res.context.palette == ["웜 베이지", "소프트 크림"]
    assert res.context.mood == "차분한"
    assert res.context.usable is True


# ── 실제 JSON 파싱 경로 검증 (소원님 approve 후속) ─────────
# 위 _run_prod는 _call_background_vision을 dict로 stub해서 json.loads를
# 건너뛴다. 여기서는 openai.OpenAI 클라이언트만 가짜로 바꿔서
# _call_background_vision 내부의 실제 json.loads 경로까지 태운다.
# {invalid json 같은 깨진 응답이 크래시(500) 없이 usable=False로
# 안전 처리되는지 확인한다.
def _run_prod_raw(content):
    """LLM이 반환한 원본 content(문자열)를 실제 파싱 경로로 통과시킨다."""
    import openai

    from copy_model import config
    import copy_model.background as bg

    class _Msg:
        def __init__(self):
            self.content = content

    class _Choice:
        def __init__(self):
            self.message = _Msg()

    class _Resp:
        def __init__(self):
            self.choices = [_Choice()]

    class _Completions:
        def create(self, **kwargs):
            return _Resp()

    class _Chat:
        def __init__(self):
            self.completions = _Completions()

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self.chat = _Chat()

    old_mock, old_key = config.MOCK_MODE, config.OPENAI_API_KEY
    old_openai = openai.OpenAI
    config.MOCK_MODE = False
    config.OPENAI_API_KEY = "test-key"
    openai.OpenAI = _FakeClient          # from openai import OpenAI가 이걸 집는다
    try:
        return bg.analyze_background_image(
            bg.BackgroundImageRequest(image_data_url=TINY_PNG)
        )
    finally:
        openai.OpenAI = old_openai
        config.MOCK_MODE = old_mock
        config.OPENAI_API_KEY = old_key


def test_prod_malformed_json_is_safe():
    # {invalid json → json.loads 실패 → 크래시 없이 usable=False.
    res = _run_prod_raw("{invalid json")
    assert res.context.usable is False
    spec = apply_background_context({"product": "립 틴트"}, res.context)
    assert "background_context" not in spec       # 기록되면 안 됨
    assert spec["product"] == "립 틴트"


def test_prod_empty_content_is_safe():
    # 빈 문자열 응답도 예외 없이 usable=False.
    assert _run_prod_raw("").context.usable is False


def test_prod_non_json_text_is_safe():
    # JSON이 아닌 평문도 예외 없이 usable=False.
    assert _run_prod_raw("배경 분석 실패했습니다").context.usable is False


def test_prod_valid_json_string_still_parses():
    # 정상 JSON 문자열은 실제 파싱 경로로도 그대로 통과한다(회귀 방지).
    res = _run_prod_raw(
        '{"usable": true, "palette": ["웜 베이지"], "mood": "차분한"}'
    )
    assert res.context.usable is True
    assert res.context.palette == ["웜 베이지"]


if __name__ == "__main__":
    import sys
    import traceback

    tests = [
        v for k, v in sorted(globals().items())
        if k.startswith("test_") and callable(v)
    ]
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

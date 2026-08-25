"""visual-prompt mock 경로 테스트 — mock 모드(비용 0, LLM 호출 0회).

★ 이 파일이 놓일 위치:  `copy_model/test_visual_prompt_mock.py`
   (팀 관례대로 프로젝트 루트. 패키지 안이 아니다.)

검증:
  - COPY_MOCK=1이면 LLM을 호출하지 않는다(_client가 불리면 실패시킨다).
  - origin이 "mock"이다 — "fallback"(실패)과 구분된다.
  - 업종이 다르면 결과가 다르다(학원 ≠ 체육관). 모르는 업종은 지어내지 않는다.
  - 같은 입력이면 같은 결과가 나온다(시연 재현성).
  - meta 키가 정상 경로와 동일하다(mock에서만 키가 빠지지 않는다).
  - llm 주입이 mock보다 우선한다(기존 테스트 보호).
"""
import os

os.environ["COPY_MOCK"] = "1"  # import 전에 mock 강제

import pytest  # noqa: E402

from copy_model.visual_prompt_service import (  # noqa: E402
    ORIGIN_FALLBACK, ORIGIN_LLM, ORIGIN_MOCK, concretize,
)

ACADEMY = {"category": "academy", "tone": "simple", "request": "차분한 학원 느낌"}
SPORTS = {"category": "sports", "tone": "energetic", "request": "활기찬 체육관 느낌"}
BEAUTY = {"category": "beauty", "tone": "simple", "product": "토너",
          "request": "촉촉하고 깨끗하게"}


@pytest.fixture
def no_llm(monkeypatch):
    """_client()가 불리면 즉시 실패시킨다.

    "호출 0회"를 말이 아니라 구조로 잠근다. mock 경로가 실수로 LLM을 부르면
    테스트가 그 자리에서 깨진다.
    """
    def _boom():
        raise AssertionError("COPY_MOCK=1인데 _client()가 호출됐다")

    monkeypatch.setattr("copy_model.generator._client", _boom)
    return _boom


def _fake_llm(spec, subject_kind):
    """주입용 가짜 LLM. 실제 호출은 하지 않는다."""
    return {"from_request": {"background": "reference scene", "mood": "calm"}}


# ── mock 경로가 LLM을 부르지 않는다 ──────────────────────
def test_mock_does_not_call_llm(no_llm):
    r = concretize(ACADEMY, "service")          # _client가 불리면 AssertionError
    assert r["visual_prompt"]


# ── origin이 mock이다 (fallback과 구분) ───────────────────
def test_origin_is_mock_not_fallback(no_llm):
    r = concretize(ACADEMY, "service")
    assert r["source"]["origin"] == ORIGIN_MOCK
    assert r["source"]["origin"] != ORIGIN_FALLBACK
    assert r["meta"]["error"] is None           # mock은 실패가 아니다


# ── 업종이 다르면 결과가 다르다 ───────────────────────────
def test_category_changes_scene(no_llm):
    academy = concretize(ACADEMY, "service")["visual_prompt"]
    sports = concretize(SPORTS, "service")["visual_prompt"]
    assert academy != sports
    assert "classroom" in academy
    assert "gym" in sports
    assert "gym" not in academy and "classroom" not in sports


def test_unknown_category_does_not_invent(no_llm):
    r = concretize({"tone": "simple"}, "service")["visual_prompt"]
    assert "classroom" not in r and "gym" not in r


def test_product_leaves_background_empty(no_llm):
    """제품형은 서버(poster_model)가 카테고리 baseline을 붙이므로 비운다.

    여기서 또 넣으면 같은 뜻이 두 번 들어가 CLIP 77토큰 예산만 태운다.
    """
    r = concretize(BEAUTY, "product")
    assert not r["visual_prompt_spec"]["background"]


# ── 재현성 ────────────────────────────────────────────────
def test_same_input_same_output(no_llm):
    a = concretize(ACADEMY, "service")
    b = concretize(ACADEMY, "service")
    assert a["visual_prompt"] == b["visual_prompt"]
    assert a["visual_prompt_spec"] == b["visual_prompt_spec"]


# ── meta 계약이 정상 경로와 같다 ──────────────────────────
def test_meta_keys_match_llm_path(no_llm):
    """mock에서만 meta 키가 빠지면 그 키를 읽는 쪽이 mock에서만 터진다.

    정상 경로를 주입으로 한 번 태워서 키 집합을 실제로 비교한다.
    하드코딩한 목록과 대조하면 정상 경로가 바뀔 때 같이 바뀌지 않아 무의미해진다.
    """
    mock = concretize(ACADEMY, "service")
    llm = concretize(ACADEMY, "service", llm=_fake_llm)
    assert set(mock["meta"]) == set(llm["meta"])
    assert set(mock) == set(llm)


# ── 주입이 mock보다 우선한다 ──────────────────────────────
def test_injected_llm_wins_over_mock(no_llm):
    """llm= 주입은 "이 호출자를 써라"는 명시적 지시라 mock보다 우선한다.

    이게 깨지면 COPY_MOCK 환경에서 기존 주입 테스트가 전부 무력화된다.
    """
    r = concretize(ACADEMY, "service", llm=_fake_llm)
    assert r["source"]["origin"] == ORIGIN_LLM
    assert "reference scene" in r["visual_prompt"]

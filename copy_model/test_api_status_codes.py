"""API 상태코드 매핑 테스트 — 입력 오류 400 vs 업스트림 502 vs 스키마 422.

배경: 이전엔 모든 예외가 except Exception -> 502로 뭉뚱그려져,
service+auto 같은 클라이언트 입력 오류도 502(서버/업스트림 오류)로 나갔다.
이제 CopyInputError -> 400, 그 외 -> 502, 스키마 오류는 FastAPI 기본 422.
"""
import os
os.environ["COPY_MOCK"] = "1"  # import 전에 mock 강제(비용 0)

from fastapi.testclient import TestClient  # noqa: E402

import copy_model.api as api  # noqa: E402
from copy_model.api import app  # noqa: E402
from copy_model.errors import CopyInputError  # noqa: E402

client = TestClient(app)


def test_service_auto_is_400_not_502():
    # service(business_type=service) + auto 모드는 미지원 조합 → 클라이언트 오류(400).
    r = client.post("/suggest/options", json={
        "message": "안녕", "mode": "auto", "step": 1,
        "spec": {"business_type": "service"},
    })
    assert r.status_code == 400, r.text
    assert "fixed" in r.json()["detail"]


def test_service_fixed_is_ok():
    # 정상 조합(service + fixed)은 200.
    r = client.post("/suggest/options", json={
        "message": "안녕", "mode": "fixed", "step": 1,
        "spec": {"business_type": "service"},
    })
    assert r.status_code == 200, r.text


def test_product_auto_is_ok():
    # 제품형 + auto는 지원 조합 → 200(회귀 방지).
    r = client.post("/suggest/options", json={
        "message": "커피", "mode": "auto", "step": 1, "spec": {},
    })
    assert r.status_code == 200, r.text


def test_schema_error_is_422():
    # 잘못된 category enum 등 스키마 위반은 FastAPI 기본 422(불변).
    r = client.post("/generate/copy", json={
        "category": "not_a_category", "product": "라떼",
    })
    assert r.status_code == 422, r.text


def test_upstream_error_is_502(monkeypatch=None):
    # 핸들러 내부에서 CopyInputError가 아닌 예외가 나면 502로 매핑돼야 한다.
    orig = api.suggest_options

    def boom(req):
        raise RuntimeError("simulated upstream failure")

    api.suggest_options = boom
    try:
        r = client.post("/suggest/options", json={
            "message": "안녕", "mode": "fixed", "step": 1, "spec": {},
        })
        assert r.status_code == 502, r.text
        assert "선택지 생성 실패" in r.json()["detail"]
    finally:
        api.suggest_options = orig


def test_run_maps_input_error_directly():
    # _run 헬퍼 단위: CopyInputError -> 400, 그 외 -> 502.
    from fastapi import HTTPException

    def raise_input(_):
        raise CopyInputError("bad input")

    def raise_other(_):
        raise RuntimeError("boom")

    try:
        api._run(raise_input, None, "x")
    except HTTPException as e:
        assert e.status_code == 400
    else:
        raise AssertionError("CopyInputError는 400이어야 한다")

    try:
        api._run(raise_other, None, "x")
    except HTTPException as e:
        assert e.status_code == 502
    else:
        raise AssertionError("일반 예외는 502여야 한다")


def test_run_passes_through_httpexception():
    # 핸들러가 직접 던진 HTTPException은 상태코드 보존해 그대로 전파(502로 안 덮임).
    from fastapi import HTTPException

    def raise_http(_):
        raise HTTPException(status_code=404, detail="not found")

    try:
        api._run(raise_http, None, "x")
    except HTTPException as e:
        assert e.status_code == 404
        assert e.detail == "not found"
    else:
        raise AssertionError("HTTPException은 그대로 전파돼야 한다")


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

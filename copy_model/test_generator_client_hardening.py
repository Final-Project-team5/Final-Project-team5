"""문구 서버 OpenAI 호출 안정화 회귀 잠금 (동시 요청 pending/레이트리밋 방어).

증상: 문구 생성 요청이 동시에 몰릴 때 브라우저 네트워크에서 한동안 pending으로
매달렸다가 뒤늦게 완료되는 간헐 지연(소원님/진우님 리포트, 2026-08-24).
원인: 한 요청이 내부에서 LLM 호출 여러 개로 순차 팬아웃되는데 클라이언트에
타임아웃/재시도 방어가 없어, 느린 호출 하나가 요청 전체를 오래 매단다.

여기선 _client()가 config의 타임아웃/재시도 설정을 실제로 반영하는지 못박는다.
실제 API 호출은 없다(클라이언트 구성만 검사, 비용 0).
"""
import os

os.environ["COPY_MOCK"] = "1"

from copy_model import config, generator  # noqa: E402


def test_client_applies_timeout_and_retries():
    # 실제 호출은 하지 않고 구성만 검사하므로 더미 키로 충분하다.
    old_key = config.OPENAI_API_KEY
    config.OPENAI_API_KEY = "test-key"
    try:
        c = generator._client()
    finally:
        config.OPENAI_API_KEY = old_key
    assert c.timeout == config.OPENAI_TIMEOUT
    assert c.max_retries == config.OPENAI_MAX_RETRIES


def test_hardening_defaults_are_bounded():
    # 무한 대기 방지: 타임아웃은 유한한 양수, 재시도는 1회 이상.
    assert isinstance(config.OPENAI_TIMEOUT, float)
    assert 0 < config.OPENAI_TIMEOUT <= 120
    assert isinstance(config.OPENAI_MAX_RETRIES, int)
    assert config.OPENAI_MAX_RETRIES >= 1


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

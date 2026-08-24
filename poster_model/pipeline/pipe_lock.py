"""★ E92 — ★ 공유 pipeline 사용 구간 ★ 직렬화 (★ 최소 적용안).

★ 배치 — `poster_model/pipeline/pipe_lock.py`  (신규 파일)

══════════════════════════════════════════════════════════════════════════
★ 무엇을 막는가
══════════════════════════════════════════════════════════════════════════

★ 지금 구조는 이렇다.

    poster_model/api.py:482   def generate_drafts(req)      ← ★ sync def
    poster_model/api.py:526   def generate_refine(req)      ← ★ sync def
              ↓  ★ FastAPI 가 ★ threadpool 에서 ★ 병렬 실행한다
    pipeline/generate.py:15   _pipes = {}                   ← ★ 모듈 전역 캐시
              ↓  ★ 같은 key → ★ ★ 같은 pipe 인스턴스
    ★ ★ 여러 스레드가 ★ 하나의 pipe 를 ★ 동시에 만진다

★ 그 pipe 안에는 ★ 스레드 간에 ★ 공유되면 안 되는 것이 ★ 최소 두 가지 있다.

  ★ ① Rust fast tokenizer
       ★ `RefCell` 을 쓴다.  ★ 한쪽이 ★ 쓰기 borrow 를 잡은 사이
       ★ 다른 쪽이 borrow 하면 ★ ★ `RuntimeError: Already borrowed`.

  ★ ② scheduler 등 ★ pipe 자신의 ★ 가변 상태
       ★ `set_timesteps()` · step index 같은 것이 ★ 호출마다 바뀐다.

══════════════════════════════════════════════════════════════════════════
★ ★ 왜 ★ tokenizer 만 잠그지 ★ 않는가
══════════════════════════════════════════════════════════════════════════

★ `Already borrowed` 는 ★ tokenizer 에서 ★ 난다.
★ ★ 그래서 ★ tokenizer 만 잠그면 ★ ★ 그 예외는 ★ 사라진다.

★ ★ 그러나 ★ 예외가 사라지는 것과 ★ 안전해지는 것은 ★ 다르다.
   ★ ②는 ★ 예외를 내지 ★ 않는다 — ★ ★ 조용히 ★ 잘못된 이미지를 만든다.
   ★ ★ 눈에 안 보이는 실패가 ★ 눈에 보이는 실패보다 ★ 낫지 않다.

★ ★ 그리고 ★ 실행 구조 쪽 이유가 ★ 하나 더 있다.

  ★ 단일 GPU 에서도 ★ 여러 diffusion 작업의 ★ 병렬 실행 ★ 자체는 ★ 가능하다.

  ★ ★ 다만 ★ 현재 구조는 ★ 하나의 GPU 에서 ★ 공유 pipeline 인스턴스를
     ★ 여러 요청이 ★ 함께 사용하며,
     ★ tokenizer · scheduler 등의 ★ 가변 상태에 ★ 동시 접근할 수 있다.

  ★ ★ 또한 ★ 현재 서비스 구조에서는 ★ VRAM · 공유 상태 · 처리량 측면을 고려해
     ★ ★ 최소 안정화 단계에서 ★ pipeline 사용 구간 ★ 직렬화를 ★ 우선 채택한다.

★ ★ 그래서 ★ ★ pipe 사용 구간 ★ 전체를 ★ 직렬화한다.

══════════════════════════════════════════════════════════════════════════
★ 왜 `RLock` 인가
══════════════════════════════════════════════════════════════════════════

★ ★ 향후 ★ guard 구간이 ★ 중첩되더라도
   ★ ★ 같은 스레드의 ★ 재진입으로 ★ 교착이 ★ 발생하지 않도록 한다.

★ 일반 `Lock` 이면 ★ 같은 스레드가 ★ 두 번 잡을 때 ★ ★ 자기 자신을 기다린다.
★ ★ `RLock` 은 ★ 그 재진입을 ★ 허용한다.

★ ★ 다만 ★ 현재 A1 에서는 ★ ★ 함수 전체를 guard 하지 않고
   ★ ★ 실제 pipe 사용 구간만 ★ 감싼다.  ★ 그래서 ★ 지금은 ★ 중첩이 ★ 발생하지 않는다.
   ★ ★ RLock 은 ★ 그 전제가 ★ 나중에 바뀌어도 ★ 안전하도록 ★ 미리 둔 것이다.

══════════════════════════════════════════════════════════════════════════
★ ★ 어디까지 잠그는가 — ★ ★ 함수 전체가 ★ 아니다
══════════════════════════════════════════════════════════════════════════

★ ★ `@guarded` 로 ★ 함수 전체를 감싸면 ★ ★ 안 된다.

    generate_drafts(...)
        if background_mode != "ai":
            return _flat_background_drafts(...)   ★ ★ diffusion 을 ★ 안 쓴다
        ...

★ ★ main 의 `generate_drafts` · `refine` 은 ★ 맨 앞에서
   ★ solid/gradient 경로로 ★ ★ 조기 반환한다 (generate.py:450 · 586).
   ★ 그 경로는 ★ PIL 로만 배경을 칠한다 — ★ pipe 를 ★ 만지지 않는다.

★ ★ 함수 전체를 잠그면 ★ 그 요청까지 ★ 앞선 diffusion 30초를 ★ 기다린다.
   ★ ★ 고칠 이유가 없는 요청을 ★ 느리게 만드는 것이다.

★ ★ 그래서 ★ 원칙은 이렇다.

    ★ ★ `_load()` 부터 ★ `pipe(...)` 호출이 ★ 끝날 때까지 ★ ★ 그 구간만 잠근다.

★ 그 뒤 후처리(add_ground_shadow · composite_product · resize)는
  ★ pipe 를 만지지 않는다 → ★ ★ 구간 밖에 둔다.  ★ 대기 시간이 그만큼 짧아진다.

★ ★ `guarded` 데코레이터도 남겨 뒀지만 ★ ★ 지금 경로에는 ★ 쓰지 않는다.
   ★ 조기 반환이 없는 ★ 순수 diffusion 함수가 ★ 생겼을 때만 쓴다.

══════════════════════════════════════════════════════════════════════════
★ ★ 배포 전제 — ★ ★ single worker
══════════════════════════════════════════════════════════════════════════

★ ★ `threading.RLock` 은 ★ ★ 프로세스 안에서만 ★ 유효하다.

★ 지금 구조 — ★ Uvicorn ★ single process / single worker → ★ 유효하다.
★ ★ 그러나 ★ 같은 GPU 에 ★ worker 를 ★ 여러 개 띄우면
   ★ ★ worker 끼리는 ★ 직렬화되지 ★ 않는다.  ★ 이 Lock 은 ★ 그때 ★ 무력하다.

★ ★ 지금 분산 Lock 을 ★ 만들지 않는다 — ★ 현재 배포 형태에 ★ 필요 없다.
★ ★ 대신 ★ 전제를 ★ 여기에 적어 둔다.
   ★ ★ worker 를 늘릴 일이 생기면 ★ ★ 이 파일을 ★ 먼저 다시 봐야 한다.

══════════════════════════════════════════════════════════════════════════
★ 이 파일이 ★ 하지 않는 것
══════════════════════════════════════════════════════════════════════════

✗ 대기열 길이를 ★ 정하지 않는다 (★ 열린 결정 — E92 §7)
   ★ diffusion 은 ★ 한 건에 ★ 수십 초다.  ★ 무한정 기다리게 두면
   ★ 늦게 온 요청은 ★ 타임아웃으로 ★ 죽는다.
   ★ ★ `timeout` 을 ★ 넣을 수는 있게 해 뒀지만 ★ 기본값은 ★ 무제한이다
     — ★ 지금 동작을 ★ 바꾸지 않기 위해서다.

✗ pipe 마다 ★ 다른 lock 을 주지 않는다
   ★ draft 와 refine 을 ★ 따로 돌릴 수는 있지만 ★ 같은 GPU 자원을 ★ 나눠 쓴다.
   ★ ★ 최소 적용 단계에서는 ★ 하나로 간다.

✗ 프로세스 간 직렬화를 ★ 하지 않는다 (★ 위 전제 참고)
"""
from __future__ import annotations

import functools
import threading
import time
from contextlib import contextmanager

#: 이 계약의 판번호.
PIPE_LOCK_VERSION = "l2"

#: ★ ★ 배포 전제. ★ 코드에서도 읽을 수 있게 ★ 상수로 남긴다.
#: ★ worker 를 늘리면 ★ 이 Lock 은 ★ worker 간에는 ★ 동작하지 않는다.
SINGLE_WORKER_ONLY = True

#: ★ ★ 하나의 lock 이 ★ 모든 pipe 사용 구간을 ★ 지킨다.
#: ★ 재진입 가능 — ★ 중첩 호출에서 ★ 교착을 내지 않는다.
_PIPE_LOCK = threading.RLock()

#: ★ 관측값. ★ report-only — ★ 동작에 영향을 주지 않는다.
STATS = {
    "acquired": 0,        # 총 획득 횟수
    "waited": 0,          # ★ 실제로 기다린 횟수 (즉시 획득이 아닌 경우)
    "wait_total_s": 0.0,  # 누적 대기 시간
    "wait_max_s": 0.0,    # ★ 최악의 대기 — ★ 이게 커지면 ★ 대기열 결정이 필요하다
    "timeouts": 0,
}
_STATS_LOCK = threading.Lock()


def _record(waited_s: float) -> None:
    with _STATS_LOCK:
        STATS["acquired"] += 1
        if waited_s > 0.001:
            STATS["waited"] += 1
            STATS["wait_total_s"] += waited_s
            STATS["wait_max_s"] = max(STATS["wait_max_s"], waited_s)


def reset_stats() -> None:
    with _STATS_LOCK:
        for k in STATS:
            STATS[k] = 0 if isinstance(STATS[k], int) else 0.0


class PipeBusy(RuntimeError):
    """★ timeout 을 준 경우에만 난다. ★ 기본 경로에서는 ★ 발생하지 않는다."""


@contextmanager
def pipe_guard(label: str = "", timeout: float = None):
    """★ 공유 pipe 를 만지는 ★ 구간 전체를 ★ 감싼다.

    ★ ★ `_load()` 부터 ★ `pipe(...)` 호출이 ★ 끝날 때까지가 ★ 한 구간이다.
       ★ `_load()` 만 잠그면 ★ 소용이 없다 — ★ 실제 동시 접근은 ★ 그 뒤에 일어난다.
    """
    started = time.monotonic()
    if timeout is None:
        _PIPE_LOCK.acquire()
    else:
        if not _PIPE_LOCK.acquire(timeout=timeout):
            with _STATS_LOCK:
                STATS["timeouts"] += 1
            raise PipeBusy(f"pipe busy: {label} (>{timeout}s)")
    _record(time.monotonic() - started)
    try:
        yield
    finally:
        _PIPE_LOCK.release()


def guarded(fn):
    """함수 ★ 전체를 ★ 한 구간으로 잠근다. ★ 데코레이터."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with pipe_guard(fn.__name__):
            return fn(*args, **kwargs)
    return wrapper


__all__ = [
    "PIPE_LOCK_VERSION",
    "STATS",
    "PipeBusy",
    "pipe_guard",
    "guarded",
    "reset_stats",
]

"""CLIP 토큰 예산 집행.

최종 프롬프트는 세 조각이 합쳐진 것이다.

    quality baseline  +  사용자/visual prompt  +  경로별 constraint

copy_model 쪽은 자기 조각만 알아서 전체 길이를 알 수 없다. 전체를 아는 것은
여기뿐이므로 예산 보장은 이 모듈의 책임이다. 문자 수나 단어 수 같은 추정치로
대신하지 않고 실제 tokenizer로 센다.

보호 영역 — 절대 버리지 않는다
    quality baseline (PROMPT_TEMPLATES / SERVICE_QUALITY_BASELINE)
    제품 경로 constraint (SHADOW_PROMPT_SUFFIX / ISOLATION_PROMPT_SUFFIX)

    실서버 로그에서 잘려 나갔던 것이 정확히 이 부분이다.
        under product / grounded / sitting on surface /
        single product only / isolated product shot / no other objects

가변 영역 — 예산이 모자라면 뒤에서부터 버린다
    사용자/visual prompt의 각 조각. 앞쪽일수록 중요하다는 전제이며,
    여기서 중요도를 다시 판단하지 않고 뒤에서 자르기만 한다.

하지 않는 것
    - tokenizer.model_max_length를 임의로 늘리지 않는다. 77은 앱 설정값이
      아니라 CLIP text encoder 구조와 엮여 있다. 숫자만 바꾸면 은폐다.
    - Compel / prompt_embeds / chunking을 도입하지 않는다. 영어화 후 초과분이
      작아서 인프라를 새로 들일 이유가 없다. 77 안으로 압축한 결과에서 실제
      품질 손실이 확인되면 그때 재검토한다.
    - 잘린 사실을 조용히 넘기지 않는다. 항상 report로 남긴다.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence

from . import config

PROMPT_BUDGET_VERSION = "b1"

# CLIP text encoder의 구조적 상한. 바꾸지 않는다.
HARD_LIMIT = 77

# 목표 예산. 77을 딱 채우지 않는다.
#   - tokenizer 판올림이나 모델 교체로 몇 토큰이 움직일 수 있다
#   - 경계에 붙여 두면 사소한 문구 수정이 곧바로 절단으로 바뀐다
# 77은 hard ceiling이고 72는 우리가 지키는 선이다.
TARGET_BUDGET = 72

SEPARATOR = ", "

# 모델별로 실제 사용하는 tokenizer 폴더.
# SDXL은 text encoder가 둘이라 tokenizer_2까지 본다. 실측에서는 세 tokenizer의
# 토큰 수가 같았지만 같다고 가정하지 않는다. 하나라도 넘치면 그 encoder에서
# 잘리므로 둘 중 큰 값을 기준으로 삼는다.
TOKENIZER_SUBFOLDERS = {
    "sd15": ("tokenizer",),
    "sdxl": ("tokenizer", "tokenizer_2"),
}


# --------------------------------------------------------------------------
# tokenizer 확보 — 여기서 fast tokenizer를 쓰지 않는다
# --------------------------------------------------------------------------
_TOKENIZERS: Dict[str, object] = {}
_COUNTERS: Dict[str, Callable[[str], int]] = {}


def tokenizer_for(repo: str, subfolder: str = "tokenizer"):
    """토큰 세기용 tokenizer. 반드시 slow(Python) tokenizer다.

    resolve_prompt()는 _load()보다 앞에서 불리므로 그 시점에 pipe.tokenizer가
    아직 없다. 그래서 별도 tokenizer를 여기서 들고 있어야 한다.

    그런데 그것을 fast tokenizer로 캐시해 두면 `Already borrowed`를 낼 자리를
    하나 더 만드는 셈이다. Rust tokenizers 객체는 동시 접근에서 RefCell을 이중
    borrow한다. slow tokenizer는 순수 Python BPE라 그 문제가 없고, 토큰 세기는
    diffusion 대비 비용이 무시할 수준이다.

    A1에서 직렬화한 공유 pipeline의 tokenizer를 budgeting에 끌어다 쓰지 않는
    것도 같은 이유다.
    """
    key = f"{repo}#{subfolder}"
    if key not in _TOKENIZERS:
        from transformers import CLIPTokenizer
        _TOKENIZERS[key] = CLIPTokenizer.from_pretrained(
            repo, subfolder=subfolder, use_fast=False)
    return _TOKENIZERS[key]


def make_counter(tokenizer) -> Callable[[str], int]:
    """실제 tokenizer로 세는 함수.

    add_special_tokens=True — 77은 BOS/EOS를 포함한 길이다. 빼고 세면 2토큰을
    놓친다. truncation=False — 자른 뒤 세면 언제나 77이 나온다. 그건 측정이
    아니다.
    """
    def count(text: str) -> int:
        return len(tokenizer(text, truncation=False,
                             add_special_tokens=True)["input_ids"])
    return count


def make_multi_counter(tokenizers: Sequence) -> Callable[[str], int]:
    """tokenizer가 여럿이면 가장 큰 값을 쓴다."""
    counters = [make_counter(t) for t in tokenizers if t is not None]

    def count(text: str) -> int:
        return max((c(text) for c in counters), default=0)
    return count


def counter_for(model_kind: str) -> Callable[[str], int]:
    """모델 종류에 맞는 카운터. sd15는 1개, sdxl은 2개 중 max."""
    if model_kind not in _COUNTERS:
        repo = config.MODELS[model_kind]["text2img"]
        subs = TOKENIZER_SUBFOLDERS.get(model_kind, ("tokenizer",))
        _COUNTERS[model_kind] = make_multi_counter(
            [tokenizer_for(repo, s) for s in subs])
    return _COUNTERS[model_kind]


# --------------------------------------------------------------------------
def fit_prompt(base: str,
               variable: Optional[str],
               extras: Sequence[str],
               *,
               count: Callable[[str], int],
               budget: int = TARGET_BUDGET,
               hard_limit: int = HARD_LIMIT) -> Dict:
    """보호 영역을 지키면서 예산 안에 맞춘다.

    조립 순서는 기존과 같다 — base -> variable -> extras.
    예전에 extras가 잘린 이유는 뒤에 있어서가 맞지만, 이제는 예산 안에서
    끝나므로 아무것도 잘리지 않는다. 그러면 순서를 바꿀 이유가 사라진다.
    순서를 바꾸면 diffusion 결과가 바뀌므로 근거 없이 출력을 흔들지 않는다.
    """
    protected_head = (base or "").strip()
    protected_tail = [s.strip() for s in extras if s and s.strip()]

    def assemble(vis: List[str]) -> str:
        parts = ([protected_head] if protected_head else []) + vis + protected_tail
        return SEPARATOR.join(parts)

    vis_all = [s.strip() for s in (variable or "").split(SEPARATOR) if s.strip()]

    protected_only = assemble([])
    protected_tokens = count(protected_only) if protected_only else 0

    # 보호 영역만으로 이미 넘치는 경우. 버릴 것이 보호 영역뿐이라 여기서는
    # 해결할 수 없다. 그래도 조용히 넘어가지 않고 깃발을 세운다. 이 깃발이
    # 서면 constraint 자체를 줄여야 한다는 신호다.
    if protected_tokens > hard_limit:
        return {
            "prompt": protected_only,
            "tokens": protected_tokens,
            "report": {
                "budget_version": PROMPT_BUDGET_VERSION,
                "budget": budget,
                "hard_limit": hard_limit,
                "protected_tokens": protected_tokens,
                "kept_segments": 0,
                "dropped_segments": len(vis_all),
                "dropped": vis_all,
                "within_budget": False,
                "within_hard_limit": False,
                "protected_over_limit": True,
            },
        }

    kept = list(vis_all)
    dropped: List[str] = []
    while kept and count(assemble(kept)) > budget:
        dropped.insert(0, kept.pop())        # 우선순위 낮은 뒤쪽부터

    prompt = assemble(kept)
    tokens = count(prompt)

    return {
        "prompt": prompt,
        "tokens": tokens,
        "report": {
            "budget_version": PROMPT_BUDGET_VERSION,
            "budget": budget,
            "hard_limit": hard_limit,
            "protected_tokens": protected_tokens,
            "kept_segments": len(kept),
            "dropped_segments": len(dropped),
            "dropped": dropped,
            "within_budget": tokens <= budget,
            "within_hard_limit": tokens <= hard_limit,
            "protected_over_limit": False,
        },
    }


__all__ = [
    "PROMPT_BUDGET_VERSION",
    "HARD_LIMIT",
    "TARGET_BUDGET",
    "SEPARATOR",
    "TOKENIZER_SUBFOLDERS",
    "tokenizer_for",
    "make_counter",
    "make_multi_counter",
    "counter_for",
    "fit_prompt",
]

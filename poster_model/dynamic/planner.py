"""AI Design Planner — Step 9 MVP.

    PlannerInput  →  prompt  →  LLM  →  structured JSON  →  PlannerResult

**디자인 계약과 특정 LLM SDK 를 섞지 않는다.** Planner 는 `LLMClient` 프로토콜만
알고, OpenAI 어댑터는 그 구현 하나다. 테스트는 `FakeLLMClient` 로 고정 응답을
넣어 결정론적으로 돈다.

```text
dynamic/planner_prompt.py   프롬프트 · JSON schema  (spec 모듈이 단일 출처)
dynamic/planner.py          이 파일 — orchestration + LLM 어댑터
dynamic/planner_io.py       입출력 자료구조
```

**잘못된 출력을 보정하지 않는다.** 파싱이 안 되면 `PlannerOutputInvalid`,
스키마를 어기면 `review_candidates()` 가 거부한다. Planner 가 px 좌표를 지우거나
enum 을 고쳐 주지 않는다 — 그 순간 "무엇이 잘못됐는지" 가 보이지 않게 된다.

결정론 — Renderer 의 결정론(`같은 RenderSpec + assets → 같은 pixels`)은 그대로
강제한다. 하지만 **외부 LLM 에 대해 `같은 brief → 같은 RenderSpec` 을 보장한다고
선언하지 않는다.** 대신 실행 metadata(model · temperature · prompt_version ·
schema_version · candidate_count)를 남긴다. 단위 테스트의 결정론은 FakeLLM 이
확보한다.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Optional, Protocol, Sequence

from .errors import PlannerOutputInvalid
from .planner_io import PlannerCandidate, PlannerInput, PlannerResult
from .planner_prompt import (
    PROMPT_VERSION,
    build_system_prompt,
    build_user_prompt,
    planner_output_schema,
    prompt_metadata,
    strict_planner_output_schema,
)

DEFAULT_MODEL = "gpt-4o-2024-08-06"      # structured output 지원 모델
RESPONSE_FORMATS = ("json_schema", "json_object")


@dataclass(frozen=True)
class PlannerConfig:
    """실행 파라미터. 전부 metadata 로 기록된다."""

    model: str = DEFAULT_MODEL
    temperature: float = 0.9              # 후보 다양성을 위해 조금 높게
    response_format: str = "json_schema"  # 가장 강한 구조 강제
    strict_schema: bool = True
    #: ★ 첫 live run 의 결론. `strict:false` 는 스키마를 **힌트로만** 쓴다 —
    #: 세 후보가 전부 required 인 `copy_blocks` 를 빠뜨렸고, 우리가 준 계약을
    #: 어긴 것이었다. 구조 정확성을 모델의 주의력이 아니라 Structured Output
    #: 계약으로 보장한다.
    #:
    #: strict 는 "모든 property 가 required" 를 요구하므로 그대로는 못 보낸다.
    #: `strict_planner_output_schema()` 가 선택 필드를 `T | null` 로 옮겨 준다
    #: (default 를 지어내지 않는다 — 이미 null 이던 것만 nullable 로 남긴다).
    #:
    #: strict 가 켜져도 **Validator 는 그대로 필요하다.** strict 가 보장하는
    #: 것은 key 존재·enum·구조뿐이고, cross-field 정합·content_ref·anchor·
    #: palette 관계·trust rule 은 여전히 우리 검증기가 본다.
    max_output_tokens: int = 16000
    timeout_s: float = 180.0

    def __post_init__(self) -> None:
        if self.response_format not in RESPONSE_FORMATS:
            raise ValueError(
                f"response_format 은 {RESPONSE_FORMATS} 중 하나여야 한다: "
                f"{self.response_format!r}"
            )

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "temperature": self.temperature,
            "response_format": self.response_format,
            "strict_schema": self.strict_schema,
            "max_output_tokens": self.max_output_tokens,
        }


# ──────────────────────────────────────────────────────────────────────────
# LLM 경계
# ──────────────────────────────────────────────────────────────────────────
class LLMClient(Protocol):
    """Planner 가 LLM 에 대해 아는 전부.

    구현체는 **파싱된 dict** 를 돌려준다. 자유 텍스트에서 JSON 을 찾아내는
    방식은 쓰지 않는다.
    """

    name: str

    def complete_json(
        self, system: str, user: str, schema: Mapping[str, Any], config: PlannerConfig
    ) -> dict:
        ...


class OpenAIClient:
    """팀이 이미 쓰는 `openai>=1.30` 을 그대로 재사용한다.

    새 SDK 를 들이지 않았다 — `copy_model` 이 같은 client 로
    `response_format` 을 쓰고 있다. 다만 그쪽은 `json_object` 고, 여기서는
    schema 를 실어 보내는 `json_schema` 를 기본으로 둔다.
    """

    name = "openai"

    def __init__(self, api_key: Optional[str] = None, client: Any = None) -> None:
        self._client = client
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")

    def _ensure(self):
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI          # 지연 import — 테스트는 필요 없다
        except ImportError as exc:  # pragma: no cover
            raise PlannerOutputInvalid(
                "planner.sdk_missing", "OpenAIClient",
                "openai 패키지가 없다. 팀 requirements 의 openai>=1.30 을 설치한다",
            ) from exc
        if not self._api_key:
            raise PlannerOutputInvalid(
                "planner.api_key_missing", "OpenAIClient",
                "OPENAI_API_KEY 가 없다 — 키를 넣어 직접 실행해야 한다",
            )
        self._client = OpenAI(api_key=self._api_key)
        return self._client

    def complete_json(self, system, user, schema, config) -> dict:
        client = self._ensure()
        if config.response_format == "json_schema":
            fmt = {"type": "json_schema", "json_schema": {
                "name": "planner_result", "schema": dict(schema),
                "strict": config.strict_schema}}
        else:
            fmt = {"type": "json_object"}

        resp = client.chat.completions.create(
            model=config.model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            response_format=fmt,
            temperature=config.temperature,
            max_tokens=config.max_output_tokens,
            timeout=config.timeout_s,
        )
        text = resp.choices[0].message.content or ""
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            # **고쳐서 파싱하지 않는다** — 앞뒤 텍스트를 잘라내거나 따옴표를
            # 손보는 순간 "모델이 무엇을 냈는지" 를 알 수 없게 된다
            raise PlannerOutputInvalid(
                "planner.not_json", "llm.response",
                f"structured output 을 요청했는데 JSON 이 아니다: {text[:160]!r}",
            ) from exc


@dataclass
class FakeLLMClient:
    """테스트용. 정해진 응답을 그대로 돌려준다 — 결정론이 여기서 나온다."""

    responses: Sequence[Any]
    name: str = "fake"
    calls: list = field(default_factory=list)

    def complete_json(self, system, user, schema, config) -> dict:
        self.calls.append({"system": system, "user": user,
                           "schema": schema, "config": config})
        idx = min(len(self.calls) - 1, len(self.responses) - 1)
        payload = self.responses[idx]
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, str):
            try:
                return json.loads(payload)
            except json.JSONDecodeError as exc:
                raise PlannerOutputInvalid(
                    "planner.not_json", "llm.response", payload[:160]) from exc
        return payload

    @property
    def last_system(self) -> str:
        return self.calls[-1]["system"] if self.calls else ""

    @property
    def last_user(self) -> str:
        return self.calls[-1]["user"] if self.calls else ""

    @property
    def last_prompt(self) -> str:
        return self.last_system + "\n" + self.last_user


# ──────────────────────────────────────────────────────────────────────────
# Planner
# ──────────────────────────────────────────────────────────────────────────
_REQUIRED_CANDIDATE_KEYS = ("id", "label", "rationale", "render_spec")


@dataclass(frozen=True)
class DesignPlanner:
    """`PlannerInput` → `PlannerResult`. **후보를 고치지 않는다.**"""

    client: LLMClient
    config: PlannerConfig = field(default_factory=PlannerConfig)

    def plan(self, pin: PlannerInput) -> PlannerResult:
        system = build_system_prompt(pin)
        user = build_user_prompt(pin)
        # ★ generic schema 가 아니라 **capability projection** 을 넘긴다.
        #   Planner 가 만들 수 없는 값을 schema 에서부터 못 만들게 한다
        ratios = list((pin.capabilities or {}).get("canvas_ratios") or ("1:1",))
        build = (strict_planner_output_schema if self.config.strict_schema
                 else planner_output_schema)
        schema = build(pin.candidate_count, ratios)

        raw = self.client.complete_json(system, user, schema, self.config)
        candidates = self._parse(raw, pin)

        meta = {
            **prompt_metadata(pin),
            **self.config.as_dict(),
            "client": getattr(self.client, "name", type(self.client).__name__),
            # ⚠ 같은 brief → 같은 RenderSpec 을 **보장하지 않는다.**
            #   외부 모델 호출이라 재현은 metadata 기록으로만 지원한다
            "determinism": "not_guaranteed_for_llm",
        }
        return PlannerResult(
            candidates=candidates,
            input_digest=prompt_digest(system, user),
            notes=str(raw.get("notes", "")) if isinstance(raw, dict) else "",
            metadata=MappingProxyType(meta),
        )

    # ── 파싱 — 구조가 어긋나면 **거부한다** ──────────────────────────────
    def _parse(self, raw: Any, pin: PlannerInput) -> tuple:
        if not isinstance(raw, dict):
            raise PlannerOutputInvalid(
                "planner.not_object", "llm.response", f"dict 이어야 한다 ({type(raw).__name__})")
        items = raw.get("candidates")
        if not isinstance(items, list) or not items:
            raise PlannerOutputInvalid(
                "planner.no_candidates", "llm.response.candidates",
                f"후보 배열이 없다 (받음: {type(items).__name__})")
        if len(items) != pin.candidate_count:
            raise PlannerOutputInvalid(
                "planner.candidate_count_mismatch", "llm.response.candidates",
                f"{pin.candidate_count}개를 요청했는데 {len(items)}개가 왔다")

        derived = pin.feedback[0].candidate_id if pin.feedback else ""
        out = []
        seen: set = set()
        for i, item in enumerate(items):
            where = f"llm.response.candidates[{i}]"
            if not isinstance(item, dict):
                raise PlannerOutputInvalid("planner.candidate_shape", where,
                                           f"object 여야 한다 ({type(item).__name__})")
            missing = [k for k in _REQUIRED_CANDIDATE_KEYS if k not in item]
            if missing:
                raise PlannerOutputInvalid("planner.candidate_fields", where,
                                           f"필수 키 누락: {missing}")
            if not isinstance(item["render_spec"], dict):
                raise PlannerOutputInvalid("planner.render_spec_shape",
                                           f"{where}.render_spec", "object 여야 한다")
            cid = str(item["id"])
            if cid in seen:
                raise PlannerOutputInvalid("planner.duplicate_id", where, cid)
            seen.add(cid)
            out.append(PlannerCandidate(
                id=cid, render_spec=item["render_spec"],
                label=str(item.get("label", "")),
                rationale=str(item.get("rationale", "")),
                derived_from=derived,
            ))
        return tuple(out)


def prompt_digest(system: str, user: str) -> str:
    import hashlib
    return hashlib.sha256((system + "\x00" + user).encode()).hexdigest()[:16]


__all__ = [
    "DEFAULT_MODEL",
    "RESPONSE_FORMATS",
    "PlannerConfig",
    "LLMClient",
    "OpenAIClient",
    "FakeLLMClient",
    "DesignPlanner",
    "prompt_digest",
    "PROMPT_VERSION",
]

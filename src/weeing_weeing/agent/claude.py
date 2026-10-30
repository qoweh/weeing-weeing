"""Anthropic Claude API 클라이언트. interface.LlmClient 구현 (#101).

- generate_json: output_config.format(JSON 스키마)으로 응답 모양을 강제하는 단발 호출.
  make llm-check와 챗봇(#89)이 쓴다.
- create: 도구 호출 루프의 한 걸음. 에이전트 실행기(runtime.py)가 쓴다. 응답 content를
  그대로 돌려줘 다음 요청에 thinking 블록까지 이어 붙일 수 있게 한다.
- 생각 단계는 모델이 알아서 정한다(adaptive). 깊이는 effort로만 조절한다.
- 안전 정책 거부에 대비해 서버 측 대체 모델(fallbacks="default")을 켠다.
- 실패는 LlmError 하위 예외로 알린다. 429·5xx·연결 오류는 전체 예산 안에서 최대 2번 재시도한다.
  SDK 내부 재시도는 끄고 _send에서 시간 예산·대기를 제어한다.
- API 키는 SDK가 ANTHROPIC_API_KEY(또는 ant auth login 프로필)에서 직접 읽는다.
- 호출 1번을 tracer에 generation 1개로 남긴다(모델·토큰·오류, #113).
"""

import json
import time
from typing import Any

import anthropic

from weeing_weeing.agent.errors import (
    LlmAuthenticationError,
    LlmInvalidResponseError,
    LlmModelMissingError,
    LlmRateLimitError,
    LlmRefusedError,
    LlmRequestError,
    LlmServiceError,
    LlmTimeoutError,
    LlmUsage,
)
from weeing_weeing.agent.tracing import NULL_TRACER, Tracer

PROVIDER = "anthropic"
# "default"는 거부 사유에 맞는 대체 모델을 서버가 고른다. 헤더는 이 형식 전용이다.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 16000  # 비스트리밍 요청이 HTTP 제한 시간에 걸리지 않는 선

# 구조화 출력·strict 도구가 받지 않는 JSON 스키마 키워드. 값 검사는 pydantic이 다시 한다.
_UNSUPPORTED = {
    "default",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "pattern",
}


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """pydantic 스키마를 Claude 구조화 출력용으로 바꾼다.

    모든 객체는 additionalProperties=false이고 모든 칸이 required여야 한다. 범위·길이 같은
    제약은 지원하지 않아 빼고, 받은 뒤 pydantic 검증과 호출한 쪽의 검사로 대신한다.
    """
    if isinstance(schema, list):
        return [strict_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    out = {k: strict_schema(v) for k, v in schema.items() if k not in _UNSUPPORTED}
    if out.get("type") == "object" and "properties" in out:
        out["required"] = list(out["properties"])
        out["additionalProperties"] = False
    return out


class ClaudeClient:
    provider = PROVIDER

    def __init__(
        self,
        model: str,
        *,
        effort: str = "medium",
        sdk: Any | None = None,
        tracer: Tracer = NULL_TRACER,
        api_key: str | None = None,
    ) -> None:
        if not model:
            raise ValueError("LLM_MODEL이 비어 있다. .env에 모델 ID를 넣는다")
        self.model_name = model
        self._effort = effort
        self._sdk = sdk
        self.tracer = tracer
        self._api_key = (
            api_key  # 숨김 입력한 키는 파일·로그·요청 추적에 기록하지 않는다.
        )
        self.last_usage: LlmUsage | None = None
        self.last_response_model: str | None = None
        self.last_attempts = 0

    def generate_json(
        self,
        system: str,
        user: str,
        *,
        timeout_s: float,
        schema: dict[str, Any] | None = None,
    ) -> str:
        output_config: dict[str, Any] = {"effort": self._effort}
        if schema is not None:
            output_config["format"] = {
                "type": "json_schema",
                "schema": strict_schema(schema),
            }
        response = self._call(
            timeout_s,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config=output_config,
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        if not text.strip():
            raise LlmInvalidResponseError("Claude API가 빈 응답을 반환했습니다.")
        if schema is None:
            try:
                json.loads(text)
            except ValueError as exc:
                raise LlmInvalidResponseError("Claude JSON 응답 형식 오류") from exc
        return text

    def create(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        timeout_s: float,
    ) -> Any:
        """도구 호출 루프 한 걸음. SDK 응답(Message)을 그대로 돌려준다."""
        return self._call(
            timeout_s,
            system=system,
            messages=messages,
            tools=tools,
            output_config={"effort": self._effort},
        )

    def close(self) -> None:
        """CLI 종료 시 추적을 보내고 SDK 연결을 닫는다. 키를 디스크로 저장하지 않는다."""
        try:
            self.tracer.flush()
        finally:
            try:
                if self._sdk is not None:
                    self._sdk.close()
            finally:
                self._api_key = None

    def _client(self) -> Any:
        if self._sdk is None:
            try:
                self._sdk = anthropic.Anthropic(api_key=self._api_key)
            except anthropic.AnthropicError as exc:
                raise LlmAuthenticationError(
                    "Claude API 인증 정보가 없다. .env에 ANTHROPIC_API_KEY를 넣거나 "
                    "ant auth login"
                ) from exc
        return self._sdk

    def _call(self, timeout_s: float, **params: Any) -> Any:
        with self.tracer.observe(
            "claude",
            as_type="generation",
            input=params.get("messages"),
            model=self.model_name,
        ) as observation:
            response = self._request(timeout_s, **params)
            observation.update(
                output=[_dump(b) for b in response.content],
                usage_details=_usage_details(response),
                metadata={
                    "stop_reason": response.stop_reason,
                    "effort": self._effort,
                    "attempts": self.last_attempts,
                    "retry_usage_unknown": self.last_attempts > 1,
                },
                # 서버 측 대체 모델이 답했으면 실제 모델로 단가를 계산한다
                model=getattr(response, "model", None) or self.model_name,
            )
            return self._check(response)

    def _send(self, timeout_s: float, **params: Any) -> Any:
        """SDK 내부 중복 재시도를 끄고 같은 시간 예산에서 최대 2번만 재시도한다.

        인증·입력 오류는 재시도하지 않는다. 대기와 네트워크 요청은 남은 예산 안에 둔다.
        통신 장애 후 공급자 과금 여부가 불명확할 수 있으며, 비용은 사용량 미확인으로 남긴다.
        """
        deadline = time.monotonic() + timeout_s
        for attempt in range(3):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LlmTimeoutError("Claude API 시간 예산 초과")
            try:
                self.last_attempts += 1
                return (
                    self._client()
                    .with_options(timeout=remaining, max_retries=0)
                    .beta.messages.create(
                        model=self.model_name,
                        max_tokens=MAX_TOKENS,
                        betas=[FALLBACK_BETA],
                        fallbacks="default",
                        **params,
                    )
                )
            except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
                transient = (
                    isinstance(exc, anthropic.APIConnectionError)
                    or exc.status_code == 429
                    or exc.status_code >= 500
                )
                if not transient or attempt == 2:
                    raise
                wait = 0.25 * (2**attempt)
                if wait >= deadline - time.monotonic():
                    raise LlmTimeoutError("Claude API 재시도 시간 예산 초과") from exc
                time.sleep(wait)
        raise AssertionError("도달할 수 없는 재시도 상태")

    def _request(self, timeout_s: float, **params: Any) -> Any:
        started = time.perf_counter()
        self.last_response_model = None
        self.last_attempts = 0
        self.last_usage = None  # 실패 시 이전 호출의 사용량을 재사용하지 않는다.
        try:
            response = self._send(timeout_s, **params)
        except anthropic.APITimeoutError as exc:
            raise LlmTimeoutError(
                f"{self.model_name}: {timeout_s:g}초 안에 응답 없음"
            ) from exc
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise LlmAuthenticationError(
                "Claude API 인증 실패. ANTHROPIC_API_KEY를 확인한다"
            ) from exc
        except anthropic.NotFoundError as exc:
            raise LlmModelMissingError(
                f"모델 {self.model_name}을 쓸 수 없다. LLM_MODEL을 확인한다"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LlmServiceError(
                f"Claude API에 연결하지 못함: {type(exc).__name__}"
            ) from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code == 429:
                raise LlmRateLimitError(429) from exc
            if exc.status_code >= 500:
                raise LlmServiceError("Claude API 일시 장애") from exc
            # 요청 본문·공급자 메시지는 남기지 않고 알려진 파라미터 이름만 분류한다.
            detail = str(getattr(exc, "body", "")).lower()
            hint = next(
                (
                    name
                    for name in (
                        "effort",
                        "fallbacks",
                        "json_schema",
                        "max_tokens",
                        "output_config",
                        "model",
                    )
                    if name in detail
                ),
                None,
            )
            raise LlmRequestError(exc.status_code, parameter_hint=hint) from exc
        except TypeError as exc:
            # 키·토큰·프로필이 하나도 없으면 SDK가 요청 직전에 TypeError를 낸다
            if "authentication" not in str(exc):
                raise
            raise LlmAuthenticationError(
                "Claude API 인증 정보가 없다. .env에 ANTHROPIC_API_KEY를 넣거나 "
                "ant auth login"
            ) from exc
        usage = getattr(response, "usage", None)
        self.last_response_model = getattr(response, "model", None)
        # 공급자가 토큰을 주지 않으면 0이 아니라 None으로 남긴다.
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        if (
            type(input_tokens) is int
            and type(output_tokens) is int
            and min(input_tokens, output_tokens) >= 0
        ):
            self.last_usage = LlmUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_s=time.perf_counter() - started,
                cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0)
                or 0,
                cache_creation_input_tokens=getattr(
                    usage, "cache_creation_input_tokens", 0
                )
                or 0,
            )

        return response

    def _check(self, response: Any) -> Any:
        if response.stop_reason == "refusal":
            raise LlmRefusedError(f"{self.model_name}: 안전 정책으로 응답 거부")
        if response.stop_reason == "max_tokens":
            raise LlmInvalidResponseError("Claude 출력이 토큰 상한에서 잘렸습니다.")
        return response


def _usage_details(response: Any) -> dict[str, int]:
    """Langfuse 단가 등록 키와 같은 이름으로 토큰 수를 낸다(docs/USAGE_TRACKING.md)."""
    usage = getattr(response, "usage", None)
    names = (
        ("input", "input_tokens"),
        ("output", "output_tokens"),
        ("cache_read_input_tokens", "cache_read_input_tokens"),
        ("cache_creation_input_tokens", "cache_creation_input_tokens"),
    )
    return {
        key: value
        for key, attr in names
        if type(value := getattr(usage, attr, None)) is int and value >= 0
    }


def _dump(block: Any) -> Any:
    try:
        return block.model_dump() if hasattr(block, "model_dump") else vars(block)
    except TypeError:
        return str(block)

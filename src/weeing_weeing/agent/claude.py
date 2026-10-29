"""Anthropic Claude API 클라이언트. interface.LlmClient 구현 (#101).

- generate_json: output_config.format(JSON 스키마)으로 응답 모양을 강제하는 단발 호출.
  make llm-check와 챗봇(#89)이 쓴다.
- create: 도구 호출 루프의 한 걸음. 에이전트 실행기(runtime.py)가 쓴다. 응답 content를
  그대로 돌려줘 다음 요청에 thinking 블록까지 이어 붙일 수 있게 한다.
- 생각 단계는 모델이 알아서 정한다(adaptive). 깊이는 effort로만 조절한다.
- 안전 정책 거부에 대비해 서버 측 대체 모델(fallbacks="default")을 켠다.
- 실패는 LlmError 하위 예외로 알린다. 429·5xx·연결 오류는 SDK가 max_retries만큼 다시 보낸다.
- API 키는 SDK가 ANTHROPIC_API_KEY(또는 ant auth login 프로필)에서 직접 읽는다.
"""

import json
import time
from typing import Any

import anthropic

from weeing_weeing.agent.errors import (
    LlmError,
    LlmModelMissingError,
    LlmRefusedError,
    LlmTimeoutError,
    LlmUnavailableError,
    LlmUsage,
)

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
    ) -> None:
        if not model:
            raise ValueError("LLM_MODEL이 비어 있다. .env에 모델 ID를 넣는다")
        self.model_name = model
        self._effort = effort
        self._sdk = sdk
        self.last_usage: LlmUsage | None = None

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
            raise LlmError(f"{self.model_name}: 빈 응답")
        if schema is None:
            json.loads(text)  # 스키마 없이도 JSON이어야 한다(아니면 JSONDecodeError)
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

    def _client(self) -> Any:
        if self._sdk is None:
            try:
                self._sdk = anthropic.Anthropic()
            except anthropic.AnthropicError as exc:
                raise LlmUnavailableError(
                    "Claude API 인증 정보가 없다. .env에 ANTHROPIC_API_KEY를 넣거나 "
                    "ant auth login"
                ) from exc
        return self._sdk

    def _call(self, timeout_s: float, **params: Any) -> Any:
        started = time.perf_counter()
        try:
            response = (
                self._client()
                .with_options(timeout=timeout_s)
                .beta.messages.create(
                    model=self.model_name,
                    max_tokens=MAX_TOKENS,
                    betas=[FALLBACK_BETA],
                    fallbacks="default",
                    **params,
                )
            )
        except anthropic.APITimeoutError as exc:
            raise LlmTimeoutError(
                f"{self.model_name}: {timeout_s:g}초 안에 응답 없음"
            ) from exc
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise LlmUnavailableError(
                "Claude API 인증 실패. ANTHROPIC_API_KEY를 확인한다"
            ) from exc
        except anthropic.NotFoundError as exc:
            raise LlmModelMissingError(
                f"모델 {self.model_name}을 쓸 수 없다. LLM_MODEL을 확인한다"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LlmUnavailableError(
                f"Claude API에 연결하지 못함: {type(exc).__name__}"
            ) from exc
        except anthropic.APIStatusError as exc:
            raise LlmError(f"Claude API 오류 HTTP {exc.status_code}") from exc
        except TypeError as exc:
            # 키·토큰·프로필이 하나도 없으면 SDK가 요청 직전에 TypeError를 낸다
            if "authentication" not in str(exc):
                raise
            raise LlmUnavailableError(
                "Claude API 인증 정보가 없다. .env에 ANTHROPIC_API_KEY를 넣거나 "
                "ant auth login"
            ) from exc
        usage = getattr(response, "usage", None)
        self.last_usage = LlmUsage(
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            total_s=time.perf_counter() - started,
        )
        if response.stop_reason == "refusal":
            raise LlmRefusedError(f"{self.model_name}: 안전 정책으로 응답 거부")
        if response.stop_reason == "max_tokens":
            raise LlmError(f"{self.model_name}: 출력이 {MAX_TOKENS}토큰에서 잘림")
        return response

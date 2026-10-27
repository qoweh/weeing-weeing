"""Ollama 네이티브 API(/api/chat) 클라이언트. interface.LlmClient 구현.

- 구조화 출력: format에 JSON 스키마를 넘기면 Ollama가 그 모양으로만 생성한다(문법 제약).
  스키마가 없으면 format="json"(아무 JSON 객체).
- think: qwen3처럼 생각 단계가 있는 모델은 기본으로 끈다(응답이 길어지고 느려짐).
- keep_alive: 마지막 호출 뒤 모델을 메모리에 남겨 둘 시간. 다음 호출의 로딩 시간을 없앤다.
- timeout_s: 응답을 기다리는 시간(stream=False라 사실상 전체 시간). 연결은 최대 5초.
- 실패는 LlmError 하위 예외로 알린다. 호출한 쪽(Analyzer)이 status=FAILED로 바꾼다.
"""

from typing import Any

import httpx

from weeing_weeing.agent.errors import (
    LlmError,
    LlmModelMissingError,
    LlmTimeoutError,
    LlmUnavailableError,
    LlmUsage,
)


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        think: bool = False,
        keep_alive: str = "10m",
        options: dict[str, Any] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not model:
            raise ValueError(
                "OLLAMA_MODEL이 비어 있다. .env에 모델명을 넣는다(예: qwen3:8b)"
            )
        self.model_name = model
        self._base_url = base_url.rstrip("/")
        self._think = think
        self._keep_alive = _keep_alive(keep_alive)
        # 같은 입력에 같은 답이 나오게 기본은 temperature 0
        self._options = {"temperature": 0, **(options or {})}
        self._transport = transport
        self.last_usage: LlmUsage | None = None

    def generate_json(
        self,
        system: str,
        user: str,
        *,
        timeout_s: float,
        schema: dict[str, Any] | None = None,
    ) -> str:
        body = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": schema if schema is not None else "json",
            "think": self._think,
            "keep_alive": self._keep_alive,
            "options": self._options,
        }
        data = self._post("/api/chat", body, timeout_s=timeout_s)
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise LlmError(f"{self.model_name}: 빈 응답")
        self.last_usage = LlmUsage(
            prompt_tokens=_number(data, "prompt_eval_count"),
            output_tokens=_number(data, "eval_count"),
            total_s=_number(data, "total_duration") / 1e9,
            load_s=_number(data, "load_duration") / 1e9,
            eval_s=_number(data, "eval_duration") / 1e9,
        )
        return content

    def _post(self, path: str, body: dict, *, timeout_s: float) -> dict:
        timeout = httpx.Timeout(timeout_s, connect=min(5.0, timeout_s))
        try:
            with httpx.Client(
                base_url=self._base_url, timeout=timeout, transport=self._transport
            ) as client:
                response = client.post(path, json=body)
        except httpx.TimeoutException as exc:
            raise LlmTimeoutError(
                f"{self.model_name}: {timeout_s:g}초 안에 응답 없음"
            ) from exc
        except (httpx.RequestError, httpx.InvalidURL) as exc:
            raise LlmUnavailableError(
                f"Ollama({self._base_url})에 연결하지 못함: {type(exc).__name__}. "
                "Ollama 앱을 켜거나 make ollama-up, OLLAMA_BASE_URL 확인"
            ) from exc
        if response.is_error:
            error = _error_text(response)
            if response.status_code == 404 and _ollama_says_not_found(response):
                raise LlmModelMissingError(
                    f"모델 {self.model_name}이 없다. ollama pull {self.model_name}"
                )
            raise LlmError(f"Ollama 오류 HTTP {response.status_code}: {error}")
        try:
            data = response.json()
        except ValueError as exc:
            raise LlmError("Ollama 응답이 JSON이 아니다") from exc
        if not isinstance(data, dict):
            raise LlmError("Ollama 응답 모양이 예상과 다르다")
        return data


def _keep_alive(value: str) -> str | int:
    """'-1'·'300'처럼 단위 없는 숫자는 초(정수)로 보낸다. 문자열이면 단위가 필요하다."""
    try:
        return int(value)
    except ValueError:
        return value


def _number(data: dict, key: str) -> float:
    value = data.get(key)
    return value if isinstance(value, int | float) else 0


def _ollama_says_not_found(response: httpx.Response) -> bool:
    """Ollama는 모델이 없으면 JSON {"error": "model '…' not found"}로 답한다."""
    try:
        body = response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and "not found" in str(body.get("error", "")).lower()


def _error_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(body, dict):
        return str(body.get("error", ""))[:300]
    return str(body)[:300]

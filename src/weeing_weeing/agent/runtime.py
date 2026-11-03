"""에이전트 실행기: 에이전트 정의(AgentSpec) + 도구 호출 루프(run_agent) + 실행 기억(RunMemory) (#102).

사건 분석과 챗봇이 같은 실행기를 쓴다. 각 실행은 하나의 역할과 허용 도구를 가진다.
에이전트 하나 = 역할 프롬프트 + 허용 도구 + 결과를 받는 제출 도구 + 반복 상한.
설계와 멀티 에이전트·메모리 확장 계획은 docs/AGENT.md.

- 모델이 도구를 부르면 실행해 결과를 돌려주고, 제출 도구가 검사를 통과하면 끝난다.
- 도구 입력이 잘못됐거나 제출 내용이 검사에 걸리면 is_error 결과로 돌려줘 모델이 고치게 한다.
- 검색 장애처럼 모델이 고칠 수 없는 실패는 예외로 올려 호출한 쪽이 FAILED로 바꾼다.
- 반복 상한(max_turns)을 넘거나 제출 없이 두 번 끝나면 AgentError.
- 실행 1번을 client.tracer에 agent 기록으로, 도구 호출을 tool 기록으로 남긴다(#113).
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from weeing_weeing.agent.claude import strict_schema
from weeing_weeing.agent.errors import LlmError, LlmUsage
from weeing_weeing.agent.tracing import NULL_TRACER, Tracer
from weeing_weeing.contracts import Evidence

T = TypeVar("T")


class AgentError(LlmError):
    """에이전트가 정해진 반복 안에 결과를 내지 못했다."""


class ToolInputError(ValueError):
    """모델이 넘긴 도구 입력이 잘못됐다. 메시지는 모델에게 그대로 돌려준다."""


@dataclass
class ToolCall:
    name: str
    input: dict[str, Any]
    ok: bool
    note: str = ""  # 실패 사유 등


@dataclass
class RunMemory:
    """실행 한 번의 작업 기억. 실행이 끝나면 버린다(사건 단위 공유 기억은 docs/AGENT.md).

    - messages: LLM에 다시 보내는 대화 기록(응답 content를 그대로 쌓아 thinking 블록 보존)
    - evidence: 이번 실행에서 도구가 실제로 돌려준 근거. 인용은 여기 있는 ID만 허용한다
    - sensor_windows: 이번 실행의 센서 요약. 통계 인용 대조용이며 원시 행은 보관하지 않는다
    - tool_calls: 도구 호출 기록(추적·평가용)
    """

    messages: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    sensor_windows: dict[str, dict[str, Any]] = field(default_factory=dict)
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: LlmUsage = field(default_factory=lambda: LlmUsage(0, 0, 0.0))
    turns: int = 0
    usage_missing_calls: int = (
        0  # 공급자가 사용량을 주지 않은 호출은 0으로 확정하지 않는다.
    )

    def remember(self, items: list[Evidence]) -> None:
        for item in items:
            self.evidence.setdefault(item.evidence_id, item)


@dataclass(frozen=True)
class AgentTool:
    """모델이 부를 수 있는 도구. handler는 모델에게 돌려줄 문자열을 만든다."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any], RunMemory], str]

    def to_api(self) -> dict[str, Any]:
        return _tool_param(self.name, self.description, self.input_schema)


@dataclass(frozen=True)
class FinishTool(Generic[T]):
    """결과를 받는 도구. parse가 ValueError를 내면 모델에게 고치라고 돌려준다."""

    name: str
    description: str
    input_schema: dict[str, Any]
    parse: Callable[[dict[str, Any], RunMemory], T]

    def to_api(self) -> dict[str, Any]:
        return _tool_param(self.name, self.description, self.input_schema)


def _tool_param(name: str, description: str, schema: dict[str, Any]) -> dict[str, Any]:
    # strict: 모델이 넘기는 입력이 스키마를 지키도록 API가 보장한다
    return {
        "name": name,
        "description": description,
        "input_schema": strict_schema(schema),
        "strict": True,
    }


@dataclass(frozen=True)
class AgentSpec(Generic[T]):
    name: str  # 예: incident-analyst. 멀티 에이전트에서 역할 이름이 된다
    system: str
    tools: tuple[AgentTool, ...]
    finish: FinishTool[T]
    prompt_version: str
    max_turns: int = 8


def run_agent(
    client: Any,
    spec: AgentSpec[T],
    task: str,
    *,
    timeout_s: float,
    memory: RunMemory | None = None,
    session_id: str | None = None,
) -> tuple[T, RunMemory]:
    """session_id: 사용량 기록에서 실행을 묶는 값(사건 ID). 멀티 에이전트도 같은 값을 쓴다."""
    memory = memory or RunMemory()
    tracer: Tracer = getattr(client, "tracer", NULL_TRACER)
    with tracer.observe(
        spec.name,
        as_type="agent",
        input=task,
        session_id=session_id,
        tags=[spec.prompt_version],
    ) as observation:
        output = _loop(client, spec, task, timeout_s, memory, tracer)
        observation.update(
            output=output.model_dump() if hasattr(output, "model_dump") else output,
            metadata={
                "turns": memory.turns,
                "tool_calls": len(memory.tool_calls),
                "input_tokens": memory.usage.input_tokens
                if not memory.usage_missing_calls
                else None,
                "output_tokens": memory.usage.output_tokens
                if not memory.usage_missing_calls
                else None,
                "usage_missing_calls": memory.usage_missing_calls,
            },
        )
    return output, memory


def _loop(
    client: Any,
    spec: AgentSpec[T],
    task: str,
    timeout_s: float,
    memory: RunMemory,
    tracer: Tracer,
) -> T:
    tools = {tool.name: tool for tool in spec.tools}
    api_tools = [tool.to_api() for tool in spec.tools] + [spec.finish.to_api()]
    memory.messages.append({"role": "user", "content": task})
    nudged = False

    while memory.turns < spec.max_turns:
        memory.turns += 1
        response = client.create(
            system=spec.system,
            messages=memory.messages,
            tools=api_tools,
            timeout_s=timeout_s,
        )
        if client.last_usage is not None:
            memory.usage = memory.usage + client.last_usage
        else:
            memory.usage_missing_calls += 1
        memory.usage_missing_calls += max(0, getattr(client, "last_attempts", 1) - 1)
        memory.messages.append({"role": "assistant", "content": response.content})

        uses = [b for b in response.content if b.type == "tool_use"]
        if not uses:
            # 도구 선택을 강제할 수 없는 모델이라(tool_choice auto) 한 번은 다시 요청한다
            if nudged:
                raise AgentError(f"{spec.name}: {spec.finish.name} 없이 끝남")
            nudged = True
            memory.messages.append(
                {
                    "role": "user",
                    "content": f"{spec.finish.name} 도구로 결과를 제출한다.",
                }
            )
            continue

        results, output, finished = [], None, False
        for block in uses:
            # 첫 유효 제출 뒤에는 남은 도구를 실행하지 않아 추가 검토·결과 변경을 막는다.
            if finished:
                break
            with tracer.observe(block.name, as_type="tool", input=block.input) as obs:
                content, is_error = _run_tool(block, tools, spec.finish, memory)
                obs.update(
                    output=content if isinstance(content, str) else None,
                    level="WARNING" if is_error else None,
                )
            if block.name == spec.finish.name and not is_error:
                output, finished = content, True
                content = "제출을 받았다."
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                    "is_error": is_error,
                }
            )
        # 같은 응답의 도구 결과는 한 메시지로 돌려준다(나눠 보내면 병렬 호출을 덜 쓰게 된다)
        memory.messages.append({"role": "user", "content": results})
        if finished:
            return output

    raise AgentError(f"{spec.name}: {spec.max_turns}번 안에 결과를 내지 못함")


def _run_tool(
    block: Any,
    tools: dict[str, AgentTool],
    finish: FinishTool,
    memory: RunMemory,
) -> tuple[Any, bool]:
    """(모델에게 돌려줄 내용 또는 제출 결과, 오류 여부)."""
    data = block.input if isinstance(block.input, dict) else {}
    try:
        if block.name == finish.name:
            result = finish.parse(data, memory)
        elif block.name in tools:
            result = tools[block.name].handler(data, memory)
        else:
            raise ToolInputError(f"없는 도구: {block.name}")
    except (ToolInputError, ValueError) as exc:
        # pydantic ValidationError도 ValueError다
        memory.tool_calls.append(ToolCall(block.name, data, False, str(exc)[:300]))
        return f"오류: {exc}", True
    memory.tool_calls.append(ToolCall(block.name, data, True))
    return result, False


def to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)

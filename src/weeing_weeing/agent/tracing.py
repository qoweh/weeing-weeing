"""LLM 호출 사용량 기록(Langfuse) (#113).

Claude 키를 팀원 6명이 각자 쓰고 콘솔 사용량 화면을 볼 수 없어서, 호출마다 누가·어떤 기능에서·
어떤 모델로·토큰을 얼마나 썼는지 홈서버 Langfuse에 남긴다. 설명은 docs/USAGE_TRACKING.md.

- 기록 단위: 에이전트 실행 1번 = trace(agent), LLM 호출 1번 = generation, 도구 호출 = tool.
  가장 바깥 기록에 user_id(LLM_USER)·session_id(사건 ID)·tags(진입점·프롬프트 버전)를 붙인다.
- LANGFUSE_BASE_URL이나 키가 없으면 NullTracer(아무것도 안 함). 테스트·CI가 그대로 돈다.
- 기록은 보조 기능이다. 전송·기록 실패는 경고만 남기고 LLM 호출과 분석을 막지 않는다.
  보내기는 SDK가 백그라운드에서 모아서 한다.
- 프롬프트·응답 본문은 LANGFUSE_CAPTURE_CONTENT=true일 때만 보낸다(기본은 토큰·메타데이터만).
"""

import logging
import os
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, ExitStack, contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from weeing_weeing.config import Settings

logger = logging.getLogger(__name__)

# 지금 열려 있는 기록 깊이. 0이면 가장 바깥이라 사람·사건·태그를 붙인다.
_depth: ContextVar[int] = ContextVar("weeing_trace_depth", default=0)
TIMEOUT_S = (
    5  # 서버로 보내기 한 번의 제한 시간. 서버가 꺼져 있어도 이 이상 기다리지 않는다
)


class Observation(Protocol):
    def update(self, **fields: Any) -> None:
        """output·usage_details·metadata·level·status_message 등을 덧붙인다."""
        ...


class Tracer(Protocol):
    def observe(
        self,
        name: str,
        *,
        as_type: str = "span",
        input: Any = None,
        model: str | None = None,
        session_id: str | None = None,
        tags: Sequence[str] = (),
    ) -> AbstractContextManager[Observation]:
        """기록 하나를 연다. 안에서 예외가 나면 ERROR로 남기고 예외는 그대로 올린다."""
        ...

    def flush(self) -> None:
        """모아 둔 기록을 보낸다. 짧게 끝나는 스크립트는 끝나기 전에 부른다."""
        ...


class _NullObservation:
    def update(self, **fields: Any) -> None:
        pass


_NULL_OBSERVATION = _NullObservation()


class NullTracer:
    """기록하지 않는다(설정이 없을 때·테스트)."""

    enabled = False

    @contextmanager
    def observe(self, name: str, **_: Any) -> Iterator[Observation]:
        yield _NULL_OBSERVATION

    def flush(self) -> None:
        pass


NULL_TRACER = NullTracer()


class _LangfuseObservation:
    def __init__(self, raw: Any, capture_content: bool) -> None:
        self._raw = raw
        self._capture = capture_content

    def update(self, **fields: Any) -> None:
        if not self._capture:
            fields.pop("output", None)
        try:
            self._raw.update(**fields)
        except Exception as exc:  # 기록 실패가 분석을 막지 않게
            logger.warning("Langfuse 기록 실패: %s", type(exc).__name__)


class LangfuseTracer:
    """Langfuse SDK 클라이언트를 감싼다. client·propagate는 테스트에서 가짜로 바꾼다."""

    enabled = True

    def __init__(
        self,
        client: Any,
        *,
        user_id: str,
        entrypoint: str,
        capture_content: bool = False,
        propagate: Callable[..., AbstractContextManager[Any]] | None = None,
    ) -> None:
        if propagate is None:
            from langfuse import propagate_attributes as propagate
        self._client = client
        self._user_id = user_id
        self._entrypoint = entrypoint
        self._capture = capture_content
        self._propagate = propagate

    @contextmanager
    def observe(
        self,
        name: str,
        *,
        as_type: str = "span",
        input: Any = None,
        model: str | None = None,
        session_id: str | None = None,
        tags: Sequence[str] = (),
    ) -> Iterator[Observation]:
        stack = ExitStack()
        observation: Observation = _NULL_OBSERVATION
        try:
            if _depth.get() == 0:
                stack.enter_context(
                    self._propagate(
                        user_id=self._user_id,
                        session_id=session_id,
                        tags=[self._entrypoint, *tags],
                        trace_name=name,
                    )
                )
            raw = stack.enter_context(
                self._client.start_as_current_observation(
                    name=name,
                    as_type=as_type,
                    input=input if self._capture else None,
                    model=model,
                )
            )
            observation = _LangfuseObservation(raw, self._capture)
        except Exception as exc:
            logger.warning("Langfuse 기록 시작 실패(%s): %s", name, type(exc).__name__)

        token = _depth.set(_depth.get() + 1)
        try:
            yield observation
        except BaseException as exc:
            observation.update(level="ERROR", status_message=type(exc).__name__)
            raise
        finally:
            _depth.reset(token)
            try:
                stack.close()
            except Exception as exc:
                logger.warning(
                    "Langfuse 기록 종료 실패(%s): %s", name, type(exc).__name__
                )

    def flush(self) -> None:
        try:
            self._client.flush()
        except Exception as exc:
            logger.warning("Langfuse 전송 실패: %s", type(exc).__name__)


def build_tracer(settings: "Settings", *, entrypoint: str) -> Tracer:
    """설정이 다 있으면 LangfuseTracer, 아니면 NullTracer.

    키(LANGFUSE_PUBLIC_KEY·LANGFUSE_SECRET_KEY)는 비밀 값이라 Settings에 두지 않고
    여기서 있는지만 본다. 값은 SDK가 환경변수에서 직접 읽는다.
    """
    if not settings.langfuse_base_url:
        return NULL_TRACER
    missing = [
        k
        for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
        if not os.environ.get(k)
    ]
    if missing:
        logger.warning("LANGFUSE_BASE_URL은 있지만 %s가 없어 기록하지 않는다", missing)
        return NULL_TRACER
    try:
        from langfuse import Langfuse

        client = Langfuse(
            base_url=settings.langfuse_base_url,
            environment=settings.langfuse_tracing_environment,
            timeout=TIMEOUT_S,
        )
    except Exception as exc:
        logger.warning(
            "Langfuse를 시작하지 못해 기록하지 않는다: %s", type(exc).__name__
        )
        return NULL_TRACER
    return LangfuseTracer(
        client,
        user_id=settings.llm_user or "unknown",
        entrypoint=entrypoint,
        capture_content=settings.langfuse_capture_content,
    )

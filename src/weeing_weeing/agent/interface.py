from typing import Protocol

from weeing_weeing.contracts import AnalysisResult, Incident


class LlmClient(Protocol):
    """Ollama와 상용 API를 바꿔 끼울 수 있게 하는 경계(품질·토큰 비교 평가용)."""

    model_name: str

    def generate_json(self, system: str, user: str, *, timeout_s: float) -> str:
        """JSON 문자열을 돌려준다. 시간 초과·연결 실패는 예외로 알린다."""
        ...


class Analyzer(Protocol):
    def analyze(self, incident: Incident) -> AnalysisResult:
        """실패해도 예외 대신 status=FAILED 결과를 돌려준다(HMI에 '관리자 호출' 표시)."""
        ...

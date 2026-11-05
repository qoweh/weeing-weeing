"""agent 테스트 공통 설정."""

import pytest


@pytest.fixture(autouse=True)
def _no_retry_wait(monkeypatch):
    """Claude 재시도 대기(0.25·0.5초)를 실제로 기다리지 않는다. 대기 계산·예산 검사는 그대로다."""
    from weeing_weeing.agent import claude

    monkeypatch.setattr(claude.time, "sleep", lambda seconds: None)

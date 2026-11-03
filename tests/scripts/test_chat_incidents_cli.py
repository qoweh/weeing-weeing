"""사건 조회 CLI는 DB만 사용하며 .env·LLM·RAG를 열지 않는다."""

import json
import runpy
from datetime import UTC, datetime
from pathlib import Path

from weeing_weeing.contracts import Incident
from weeing_weeing.db.interface import open_incidents


def test_db_only_cli_and_incident_source_output(tmp_path, monkeypatch, capsys):
    repo = open_incidents(f"sqlite:///{tmp_path / 'cli.db'}")
    at = datetime(2026, 11, 2, tzinfo=UTC)
    repo.save_incident(
        Incident(
            incident_id="CLI-1",
            process_id="P1",
            asset_id="A1",
            codes=["BTT2-P03"],
            severity="Warning",
            first_detected_at=at,
            last_detected_at=at,
        )
    )
    main = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/check_chat.py")
    )["main"]
    monkeypatch.setitem(main.__globals__, "get_incidents", lambda: repo)

    def forbidden():
        raise AssertionError("LLM/RAG must not be called")

    monkeypatch.setitem(main.__globals__, "get_chat_knowledge", forbidden)
    monkeypatch.setitem(main.__globals__, "close_rag_resources", forbidden)
    try:
        assert main(["incidents", "--severity", "Warning"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["source"]["warning_count"] == 1
        assert result["incidents"][0]["incident_id"] == "CLI-1"
    finally:
        repo._engine.dispose()

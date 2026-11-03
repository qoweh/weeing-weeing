from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from weeing_weeing.contracts import ReportDocument, ReportDraft, ReportFormData


def test_report_index_status_values():
    adapter = TypeAdapter(ReportDocument.model_fields["index_status"].annotation)
    for value in (None, "pending", "indexed", "failed"):
        assert adapter.validate_python(value) == value
    with pytest.raises(ValidationError):
        adapter.validate_python("draft")


def test_empty_draft_and_partial_time_are_allowed():
    assert ReportDraft().incident_id is None
    assert (
        ReportFormData(downtime_start=datetime.now(timezone.utc)).downtime_end is None
    )


def test_unknown_fields_cannot_spoof_author_or_approval():
    for extra in ({"author_id": "ADMIN"}, {"approval": []}, {"ai_analysis": {}}):
        with pytest.raises(ValidationError):
            ReportDraft(**extra)


@pytest.mark.parametrize("field", ["action_at", "downtime_start", "downtime_end"])
def test_naive_dates_are_rejected(field):
    with pytest.raises(ValidationError):
        ReportFormData(**{field: "2026-10-28T10:00:00"})


def test_downtime_cannot_run_backwards():
    with pytest.raises(ValidationError):
        ReportFormData(
            downtime_start="2026-10-28T11:00:00Z", downtime_end="2026-10-28T10:00:00Z"
        )

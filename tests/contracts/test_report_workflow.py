from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from weeing_weeing.contracts import ReportDraft, ReportFormData


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

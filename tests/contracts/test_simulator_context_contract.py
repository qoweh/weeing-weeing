from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from weeing_weeing.contracts import SimulatorOperatingContext


def source_context(**updates):
    return (
        dict(
            version="unreal-state-v1",
            source_id="source-1",
            run_cmd=True,
            run_started_at=datetime(2026, 11, 4, tzinfo=UTC),
            simulation_seconds=0,
            run_started_simulation_seconds=0,
            last_infeed_simulation_seconds=None,
            last_outfeed_simulation_seconds=None,
            fixed_speed=True,
            same_load=True,
            vibration_comparable=True,
            downstream_ready=True,
            recipe_id="synthetic-1",
            config_version="1",
            origin_verified_empty=True,
            events_complete=True,
            sequence=0,
            last_infeed_at=None,
            last_outfeed_at=None,
            pending=[],
            events=[],
            **updates,
        )
        if not updates
        else {**source_context(), **updates}
    )


def test_context_preserves_unknown_and_aware_time():
    context = SimulatorOperatingContext.model_validate(source_context(same_load=None))
    assert context.same_load is None
    assert context.run_started_at.utcoffset().total_seconds() == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"run_cmd": "true"},
        {"sequence": True},
        {"sequence": -1},
        {"run_started_at": "2026-11-04T00:00:00"},
        {"source_id": "two words"},
        {"unexpected": True},
        {
            "events": [
                dict(item_id="a", at="2026-11-04T00:00:00Z", sequence=1, kind="infeed")
            ]
        },
        {
            "pending": [
                dict(item_id="a", entered_at="2026-11-04T00:00:00Z", sequence=1)
            ]
            * 65
        },
    ],
)
def test_context_rejects_invalid_provenance(changes):
    with pytest.raises(ValidationError):
        SimulatorOperatingContext.model_validate(source_context(**changes))

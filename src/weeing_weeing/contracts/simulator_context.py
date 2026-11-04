"""Unreal 합성 시뮬레이터의 관측 문맥. 실제 PLC 확인으로 간주하지 않는다."""

from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    model_validator,
)

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^\S+$")]
SimulationSeconds = Annotated[
    float, Field(strict=True, ge=0, le=1_000_000_000, allow_inf_nan=False)
]


class SourceTray(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: Identifier
    entered_at: AwareDatetime
    simulation_seconds: SimulationSeconds
    sequence: Annotated[StrictInt, Field(ge=1)]


class SourceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: Identifier
    at: AwareDatetime
    simulation_seconds: SimulationSeconds
    sequence: Annotated[StrictInt, Field(ge=1)]
    kind: Literal["infeed", "outfeed"]


class SimulatorOperatingContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal["unreal-state-v1"]
    source_id: Identifier
    run_cmd: StrictBool
    run_started_at: AwareDatetime | None
    simulation_seconds: SimulationSeconds
    run_started_simulation_seconds: SimulationSeconds | None
    fixed_speed: StrictBool | None
    same_load: StrictBool | None
    vibration_comparable: StrictBool | None
    downstream_ready: StrictBool
    recipe_id: Identifier
    config_version: Identifier
    origin_verified_empty: StrictBool
    events_complete: StrictBool
    sequence: Annotated[StrictInt, Field(ge=0)]
    last_infeed_at: AwareDatetime | None
    last_outfeed_at: AwareDatetime | None
    last_infeed_simulation_seconds: SimulationSeconds | None
    last_outfeed_simulation_seconds: SimulationSeconds | None
    pending: Annotated[list[SourceTray], Field(max_length=64)]
    events: Annotated[list[SourceEvent], Field(max_length=128)]

    @model_validator(mode="after")
    def ordered(self):
        for wall, clock in (
            (self.run_started_at, self.run_started_simulation_seconds),
            (self.last_infeed_at, self.last_infeed_simulation_seconds),
            (self.last_outfeed_at, self.last_outfeed_simulation_seconds),
        ):
            if (wall is None) != (clock is None):
                raise ValueError("Missing paired simulation clock")
        clocks = [e.simulation_seconds for e in self.events] + [
            p.simulation_seconds for p in self.pending
        ]
        clocks += [
            v
            for v in (
                self.run_started_simulation_seconds,
                self.last_infeed_simulation_seconds,
                self.last_outfeed_simulation_seconds,
            )
            if v is not None
        ]
        if any(v > self.simulation_seconds for v in clocks):
            raise ValueError("Future simulation clock")
        for items in (self.events, self.pending):
            if any(
                a.simulation_seconds > b.simulation_seconds
                for a, b in zip(items, items[1:])
            ):
                raise ValueError("Simulation clock moved backwards")
        sequences = [item.sequence for item in self.events]
        if sequences != sorted(set(sequences)) or any(
            n > self.sequence for n in sequences
        ):
            raise ValueError("Invalid event order")
        if len({item.item_id for item in self.pending}) != len(self.pending):
            raise ValueError("Duplicate pending tray")
        pending_sequences = [item.sequence for item in self.pending]
        if pending_sequences != sorted(set(pending_sequences)) or any(
            n > self.sequence for n in pending_sequences
        ):
            raise ValueError("Invalid inventory order")
        if any(a.at > b.at for a, b in zip(self.events, self.events[1:])):
            raise ValueError("Event clock moved backwards")
        if any(
            a.entered_at > b.entered_at for a, b in zip(self.pending, self.pending[1:])
        ):
            raise ValueError("Inventory clock moved backwards")
        if self.pending and (
            self.last_infeed_at is None
            or self.pending[-1].entered_at > self.last_infeed_at
            or self.pending[-1].simulation_seconds > self.last_infeed_simulation_seconds
        ):
            raise ValueError("Inventory has no matching infeed time")
        return self

import csv
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SAMPLE_CSV = DATA_DIR / "telemetry" / "battery_tray_transfer_telemetry_v3_15cols.csv"


@pytest.fixture
def sample_rows() -> list[dict[str, str]]:
    """Telemetry v3 원본 60행. 첫 컬럼에 BOM이 있어 utf-8-sig로 읽는다."""
    with SAMPLE_CSV.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

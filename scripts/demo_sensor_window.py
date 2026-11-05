"""#105 오프라인 시연: 센서 조회 → 틀린 수치 거절 → 수정 제출. 외부 API·DB 사용 없음."""

import csv
import json
import logging
from datetime import timedelta
from types import SimpleNamespace

from weeing_weeing.agent.interface import LlmUsage, SensorBatch, get_analyzer
from weeing_weeing.config import PROJECT_ROOT
from weeing_weeing.contracts import Incident, TelemetryRecord


class DemoLlm:
    provider = "fake"
    model_name = "sensor-window-demo"
    last_usage = LlmUsage(0, 0, 0)

    def __init__(self):
        self.turn = 0

    def create(self, **kwargs):
        self.turn += 1
        if self.turn == 1:
            name = "get_sensor_window"
            data = {
                "before_seconds": 1,
                "after_seconds": 2,
                "fields": ["rpm", "infeed_present", "motor_housing_temp_c"],
            }
        else:
            name = "submit_analysis"
            value = 9999 if self.turn == 2 else 1200
            print(f"\n[가짜 LLM 제출] rpm.mean={value}", flush=True)
            if self.turn == 2:
                window = json.loads(kwargs["messages"][-1]["content"][0]["content"])
                print(json.dumps(window, ensure_ascii=False, indent=2), flush=True)
            data = {
                "observed_facts": "서버가 검증한 관측으로 작성",
                "suspected_causes": [],
                "recommended_checks": [],
                "recommended_actions": [],
                "actions_requiring_approval": [],
                "additional_checks": [
                    "오프라인 시연이므로 정비 문서 검색은 실행하지 않음"
                ],
                "limitations": "가짜 LLM·합성 센서 표본 시연",
                "status": "INSUFFICIENT_EVIDENCE",
                "sensor_claims": [
                    {
                        "window_id": "window-1",
                        "field": "rpm",
                        "statistic": "mean",
                        "value": value,
                    }
                ],
            }
        block = SimpleNamespace(
            type="tool_use", id=f"demo-{self.turn}", name=name, input=data
        )
        return SimpleNamespace(content=[block], stop_reason="tool_use")


class NoSearch:
    def search(self, *args, **kwargs):
        raise AssertionError("시연에서 RAG를 호출하지 않는다")


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    incident = Incident.model_validate_json(
        (PROJECT_ROOT / "data/eval/incident_p03_demo.json").read_text("utf-8")
    )
    incident = incident.model_copy(
        update={
            "incident_id": "INC-SENSOR-WINDOW-DEMO",
            "evidence": [],
            "plc_context": {},
        }
    )
    path = PROJECT_ROOT / "data/telemetry/battery_tray_transfer_telemetry_v3_15cols.csv"
    with path.open(encoding="utf-8-sig", newline="") as source:
        base = TelemetryRecord.model_validate(next(csv.DictReader(source)))
    rows = [
        base.model_copy(
            update={
                "timestamp": incident.last_detected_at + timedelta(seconds=offset),
                "process_id": incident.process_id,
                "asset_id": incident.asset_id,
                "rpm": rpm,
                "infeed_present": True,
                "motor_housing_temp_c": None,
            }
        )
        for offset, rpm in [(-1, 1000.0), (-0.5, 1200.0), (0, 1400.0)]
    ]

    def reader(item, start, end, *, limit):
        return SensorBatch(
            [r for r in rows if start <= r.timestamp < end][:limit], rows[-1].timestamp
        )

    print("[오프라인 시연] 합성 표본 3개 / 실제 Claude 호출·DB 변경 없음", flush=True)
    analyzer = get_analyzer(
        NoSearch(), client=DemoLlm(), sensor_reader=reader, mode="single"
    )
    result = analyzer.analyze(incident)
    print("\n[최종 관측]\n" + result.observed_facts)
    print("\n[관측 한계]\n" + (result.limitations or ""))
    for call in analyzer.last_memory.tool_calls:
        print(f"[도구 처리] {call.name}: {'통과' if call.ok else '거절'} {call.note}")
    return int(result.status == "FAILED")


if __name__ == "__main__":
    raise SystemExit(main())

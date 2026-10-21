"""detector — Main Engine 룰 판정과 Incident 관리 (1차 분담: 이상탐지 모듈 2·3번).

책임: TelemetryRecord를 순서대로 받아 BTT-RULE v2.0 룰을 평가하고 Incident를 만들거나 갱신한다.
      지속시간 확정, 회복 대기, 같은 현상의 Incident 묶기, 사전 경고(Warning)를 여기서 처리한다.
입력: TelemetryRecord (+ PLC 문맥: run_cmd, 운전모드 등)
출력: 새로 생기거나 바뀐 Incident 목록  (interface.Detector)
의존 가능: contracts
금지: plc 제어 명령 직접 호출. 정지 판단은 plc 모듈이 독립적으로 한다.
"""

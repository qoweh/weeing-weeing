"""ingest — 센서 데이터 수집·재생·검증 (1차 분담: 이상탐지 모듈 1번).

책임: CSV(또는 시뮬레이터)에서 Telemetry를 읽어 TelemetryRecord로 검증해 내보낸다.
입력: CSV 파일 / 시뮬레이터 스트림
출력: Iterator[TelemetryRecord]  (interface.TelemetrySource)
의존 가능: contracts
"""

# simulator — Unreal 가상 공정 연동 (4차)

Unreal 프로젝트 자체는 용량이 커서 이 레포에 넣지 않는다. 여기에는 연동 규격과 보조 스크립트만 둔다.

- Unreal이 내보내는 센서값은 `contracts.TelemetryRecord`(15컬럼) 모양을 그대로 따른다.
- PLC와의 연동 방식(HTTP / WebSocket)은 3차 시작 전에 정해 이 문서에 적는다.
- Unreal 연동이 늦어져도 시연할 수 있도록 CSV 재생(`ingest`)을 항상 대안으로 유지한다.

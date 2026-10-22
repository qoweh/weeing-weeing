"""plc — Virtual PLC: 운전 상태와 보호 제어 (3차).

책임: 운전·대기·정지·보류 상태 전환, 트레이 추적(FIFO), 이상 시 투입 보류·정지 요청.
      명시적 시작 요청 없이는 재기동하지 않는다. 리셋(알람 해제)과 재가동(모터 기동)을 분리한다.
입력: TelemetryRecord, HMI의 리셋·재가동 승인 요청
출력: PlcState, 제어 명령  (interface.VirtualPlc)
의존 가능: contracts
금지: api·agent·rag import. FastAPI나 AI가 죽어도 이 모듈만으로 정지가 동작해야 한다.
"""

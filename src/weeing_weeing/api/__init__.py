"""api — FastAPI 백엔드 (2차).

책임: Telemetry 수신·저장, Incident·분석·보고서·결재 API. 모듈들을 이어 붙이는 유일한 자리다.
입력/출력: HTTP JSON. 요청·응답 모델은 contracts를 그대로 쓴다.
의존 가능: contracts, 각 모듈의 interface, db
실행: make api (uv run --no-sync uvicorn --app-dir src weeing_weeing.api.app:app --reload)
"""

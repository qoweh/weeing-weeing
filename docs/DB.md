# DB 테이블과 사용법

코드: `src/weeing_weeing/db/`. 다른 모듈은 `db/interface.py`만 import한다(ARCHITECTURE 의존 규칙).
환경 준비는 [LOCAL_SETUP 3절](LOCAL_SETUP.md), 결정 이유는 [DECISIONS](DECISIONS.md) D-20·D-23.

## 테이블

| 테이블 | 무엇 | 계약 | 쓰는 쪽 | 이슈 |
|---|---|---|---|---|
| `document` | 색인 대상 문서 목록(기준 문서·업로드·승인 보고서) | `DocumentRecord` | rag(`make index`), api(업로드) | #60 |
| `incident` | 이상 사건. 같은 `incident_id`는 갱신 | `Incident` | detector → api | #61 |
| `analysis` | AI 분석 결과. 한 사건에 여러 건(재분석·모델 비교) | `AnalysisResult` | agent → api | #61 |
| `telemetry` | 센서 1초 데이터(v3 15컬럼) | `TelemetryRecord` | ingest → api, HMI 그래프 | #63 |
| `app_user`·`user_session` | 사용자 계정(비밀번호 scrypt 해시)·로그인 세션(토큰 SHA-256) | `UserAccount` | api 로그인([AUTH.md](AUTH.md)) | #62 |
| `report`·`report_version`·`approval` | 보고서·버전·결재 | `ReportDraft`, `ReportDocument`, 제출 후 `MaintenanceReport` | 보고서·HMI([REPORTS](REPORTS.md)) | #62 |
| `report_index_job` | 승인 판의 검색 등록 대기(실제 색인은 #29) | `MaintenanceReport` | 이후 api·실행 스크립트 | #62·#29 |

저장 방식은 공통으로 **조회에 쓰는 값은 칼럼, 계약 전체는 `data`(PostgreSQL JSONB)** 다. 꺼낼 때는 `data`를 계약 모델로 다시 검증하므로, 계약에 칸이 늘어도 마이그레이션 없이 저장된다. 단, 새 칸으로 **필터·정렬**하려면 칼럼과 마이그레이션을 추가한다.
`telemetry`만 예외로 15컬럼을 모두 칼럼으로 둔다(값이 고정이고 양이 많아 구간 조회가 잦다).

## 사용 예

```python
from weeing_weeing.db import interface as db

# .env의 DATABASE_URL. 첫 호출 때 연결·마이그레이션
incidents = db.get_incidents()
# 새 사건은 추가, 같은 incident_id는 덮어씀(갱신·회복)
incidents.save_incident(incident)
incidents.list_incidents(asset_id="BLDC-001", statuses=[IncidentStatus.OPEN])
# 사건이 먼저 저장돼 있어야 함(없으면 UnknownIncidentError)
incidents.save_analysis(result)
incidents.latest_analysis(incident_id)

telemetry = db.get_telemetry()
# 새로 저장된 줄 수를 돌려줌. 같은 설비·같은 시각은 건너뜀
telemetry.save_many(records)
# [start, end) 시각순
telemetry.between("BLDC-001", start, end)
```

- 모든 저장소는 엔진 하나를 함께 쓴다. 연결 실패·잠금 대기 초과는 `DatabaseUnavailableError`(API는 503으로 바꾼다).
- 시각 칼럼은 UTC로 저장한다. telemetry는 UTC로 돌려주고, incident·analysis는 `data`에 저장한 그대로(예: `+09:00`) 돌려준다. 같은 순간이면 비교 결과는 같다.
- `save_incident`는 한 문장 업서트라 동시 저장에도 충돌하지 않는다. 저장된 것보다 `last_detected_at`이 이른 내용(늦게 도착한 옛 갱신)은 무시한다.
- 테스트용으로는 `open_incidents(url)`·`open_telemetry(url)`로 다른 DB를 연다.

## 아직 연결하지 않은 곳

보고서 저장·조회·결재 API와 hmi/web 화면은 연결됐다. 기존 로그인 계정을 사용한다.
실제 벡터 색인과 사진 영구 저장은 이번 범위 밖이다([REPORTS](REPORTS.md)).

저장 함수만 있고 호출하는 곳은 각 담당이 붙인다.

| 할 일 | 어디서 | 담당 |
|---|---|---|
| Incident 생성·갱신·회복 때 `save_incident` | detector 결과를 받는 쪽(`api/telemetry.py` 등) | detector·api |
| 분석이 끝나면 `save_analysis` | Agent 워크플로(#11) | agent |
| 수신한 센서 줄을 `save_many`로 저장(배치 권장) | `api/telemetry.py`·CSV 재생 | ingest·api |

## 스키마 바꾸기

1. `db/models.py`를 고친다
2. `PYTHONPATH=src uv run --no-sync alembic revision --autogenerate -m "설명"`으로 초안을 만들고, `db/migrations/versions/`의 파일을 0001·0002처럼 손으로 정리한다(SQLite에서도 돌아야 함)
3. `uv run --no-sync pytest tests/db`. PostgreSQL 확인은 LOCAL_SETUP 3절

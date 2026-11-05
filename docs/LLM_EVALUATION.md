# Claude 실제 평가 (#106)

## 평가를 나누는 이유

고정 근거 비교는 모델의 판단·인용·출력 계약을 비교한다. 실제 RAG 검색 품질과 센서 조회,
Unreal·DB 지연은 포함하지 않는다. 별도로 `analyze_incident.py --sensor-window`의 실제
검색·도구 호출 경로를 확인한다. 두 시험의 시간을 같은 의미로 비교하지 않는다.

## 무료 준비와 터미널 실행

PowerShell, 저장소 루트 기준:

```powershell
$env:PYTHONPATH="src"
$env:PYTHONUTF8="1"
uv run --no-sync python scripts/compare_llm.py
```

기본은 계획만 출력하며 클라이언트도 만들지 않는다. 고정 4사례 × 3회 ×
Sonnet medium = 12개 애플리케이션 요청이다. 팀의 비용 합의(D-30)에 따라 Opus는
프로젝트 사용·평가 범위에서 제외했고, 기본 계획에 포함하지 않는다.
실제 실행은 유료이며 `--execute`를 명시한다. `--max-calls` 기본 40은 계획 요청 수의 상한이다.
SDK 내부 통신 재시도와 토큰·금액의 강제 상한은 아니므로 실제 HTTP 요청 수가 더 많을 수 있다.

```powershell
uv run --no-sync --env-file .env python scripts/compare_llm.py --execute
```

모델·effort를 직접 지정하거나 일부 사례만 선택할 수 있다:

```powershell
uv run --no-sync python scripts/compare_llm.py --setting claude-sonnet-5-5:medium --repeat 1 --case-id c01-p03-occupancy
```

위 명령은 실행 계획만 표시한다. `--execute`는 승인한 범위에서만 추가한다.
중복 설정·데이터의 중복 사례 ID·없는 사례 선택은 API 실행 전에 거부한다. 같은 사례를
여러 번 선택해도 한 번만 선택하고 반복은 `--repeat`로 지정한다. 모델 접근 권한과 지원 effort는
실제 계정에서 확인해야 하며, 접근 불가 시 다른 모델로 임의 대체하지 않고 중단한다.

## 사례와 판정

- `llm_cases_v1.toml`: 소규모 4사례. P03 예시의 정상 RPM은 현재 규격에 맞게
  1480→1015로 보정했다. 이전 실측과 입력이 완전히 같지 않으므로 새 데이터 해시를 기록한다.
- `llm_cases_v2.toml`: 주요 8코드 × 4조건 = 32사례. P01/P03/P04/M02/M07/M10/M12/M14,
  정답 근거만 / 정답+방해 근거 / 무관한 근거만 / 근거 없음이다.
- `llm_cases_v2_sources.json`: UTF-8/LF 정규화한 원문 해시와 페이지를 기록한다.
  근거는 저장소 파싱 매뉴얼의 페이지 전체를 수정 없이 발췌했다. 사건은 합성이며 Detector나
  실제 과열·진동 실측을 재현한 것이 아니다. 평가용 ID를 실제 RAG 청크 ID로 사용하지 않는다.
  32사례는 전문가 검토 전 평가 초안이다.
- 형식·계약 통과와 기대 상태 일치, 지정한 정답 근거 ID 인용을 구별해 집계한다.
  형식이 맞아도 기대 상태가 다르거나 방해 근거를 인용하면 종합 실패다.
- 정답 ID 검사는 인용 문장의 의미, 임의 원인 확정, 부적절한 재가동/교체 지시를 자동 보증하지 않는다.
  이 항목은 사람의 검토표로 남긴다. 형식 통과율만으로 모델을 선정하지 않는다.

32사례 확장의 계획을 먼저 확인한다(기본 반복 3회면 96요청이므로 별도 실행 범위가 필요하다):

```powershell
uv run --no-sync python scripts/compare_llm.py --cases data/eval/llm_cases_v2.toml --repeat 1 --setting claude-sonnet-5-5:medium
```

## 결과와 복구

결과는 `outputs/llm_evaluation/<UTC시각>/`에 저장한다.

- `plan.json`: 모델·effort·사례 선택·반복·타임아웃·데이터/Agent 코드 해시와 요청 수.
- `results.json`: 각 사례의 판정, 모델별 평균·중앙값·P95 시간, 입력/출력 및 캐시 토큰.
  공급자가 돌려준 실제 응답 모델도 요청 모델과 별도로 기록한다. 서버 측 대체 모델이
  활성화된 기존 클라이언트를 재사용하므로 `actual_models`를 확인한 뒤 모델 간 비교를 해석한다.
- `report.md`: 비교 표와 기본값 결정·내용 검토 체크리스트. 기본 설정이나 관련도 하한을 자동 변경하지 않는다.
- 완료된 사례마다 즉시 저장한다. 인증/모델 접근 실패·사용자 중단 시 마지막 완료 결과를 보존한다.
  HTTP 오류(429 포함)도 첫 건에서 중단하고 `results.json`의 `plan.termination`에 상태 코드와
  허용 목록의 파라미터 힌트만 남긴다. 공급자 오류 메시지·요청 본문은 남기지 않는다.
  자동 재개·재호출은 하지 않는다. 새 실행은 새 폴더를 사용하며 기존 폴더는 덮어쓰지 않는다.
- 기본 보고서는 요청·응답 원문을 저장하지 않는다. `--review-output`을 명시하면 내용 검토용
  **응답**만 로컬 `response-*.json`에 추가한다. 관측 내용이 포함되므로 공유 문서·이슈에 복사하지 않는다.
  API 키·요청 원문은 보고서·문서·이슈에 남기지 않는다. 원본 로컬 산출물은 Git 제외 대상이다.
- CLI 종료 코드: 0 전부 종합 통과, 1 평가 실패/불일치 있음, 2 입력·설정·실행 중단·기록 실패.
- 사용량이 없는 실패 요청은 직전 요청 토큰을 재사용하지 않는다. `usage_reported_runs`로
  사용량 기록 수를 확인한다. 공급자가 실패 요청 사용량을 돌려주지 않으면 누락될 수 있다.
  토큰 수는 청구액이 아니며 실제 단가·캐시 정책·요금 기록과 별도 대조한다.
- 모델별 순차 실행이므로 캐시·서비스 부하·시간대 효과가 섞일 수 있다. 소규모 결과를 일반화하지 않는다.

## 검색·센서 결합 회귀 검사

`tests/agent/test_sensor_relevance_integration.py`는 실제 네트워크 없이 다음을 확인한다.

1. 문서가 관련도 필터에서 모두 제외되면 센서 데이터가 있어도 근거 부족으로 멈춤.
2. 관련도가 높아도 잘못 제출한 센서 수치를 거절하고 수정한 값만 수락.
3. 관측 공백을 최종 한계에 보존하고 결측 통계를 생성하지 않음.

실제 검색·센서 평가는 기존 Qdrant 로컬 모드 서버와 동시에 별도 분석 스크립트를 실행하지 않는다.
같은 사건과 센서 구간을 고정하고 `RAG_MIN_RELEVANCE` 비활성/후보값을 비교한다.
`0.02`는 #75의 실험 후보이며 #106에서 운영 기본값으로 임의 활성화하지 않는다.

```powershell
uv run --no-sync --env-file .env python scripts/analyze_incident.py --incident 사건.json --sensor-window --evaluation-out outputs/llm_evaluation/agent-new.json
```

이 명령도 유료다. `--evaluation-out`에는 원문 없이 Agent 전체 시간·trace 전송 시간·LLM/도구 호출 수·
입력 사건 해시·필터 설정·인용 ID 대조·센서 조회/검증 수·사용량을 저장한다. 기존 파일은 덮어쓰지 않는다.
Agent 전체 시간에는 검색·센서 조회·지연이 포함되고, `usage.total_s`는 LLM 호출 구간 합계다.
두 값의 차이만으로 검색·리랭커·모델 로딩 각각의 시간을 확정하지 않는다.

## 실측 기록

[2026-10-30 결과](llm_evaluation/2026-10-30.md)를 참고한다. 팀 합의로 Sonnet medium을
사용하며 Opus 비교는 완료 조건에서 제외했다. 과거 HTTP 429 진단은 보존한다. 첫 실측의 실제 응답 모델 ID 미기록과
사례 검토 범위도 결과 문서에 명시했다.

## 챗봇 지연 기준선 (#215)

지연 개선(#216~#221) 전후를 같은 질문 10개(`data/eval/chat_latency_v1.toml`)로 비교한다. 질문별로 전체 시간, LLM 호출 수(도구 루프+근거 검토), 목적별 시간, 그 외(검색·DB·검증) 시간, 토큰·캐시 읽기 토큰, 사용 도구를 표로 남긴다. 서비스의 호출 기록(`last_run`)으로 재므로 Langfuse가 없어도 된다. 질문·응답 본문은 결과에 남기지 않는다.

```bash
make chat-baseline                                   # 계획만(호출 없음)
make chat-baseline ARGS="--replay"                   # 재생 LLM·샘플 문서로 흐름 확인(비용 0)
make chat-baseline ARGS="--execute --label before"   # 실제 Claude·프로젝트 DB/색인(유료, 확인 질문 있음)
make chat-baseline ARGS="--execute --only L01,L05 --label after-216"
```

- 결과: `outputs/chat_baseline/report-<시각>-<label>.md`·`.json`(Git 제외). 개선 PR 본문에 전후 요약 줄을 붙인다.
- 재생 모드의 상태·시간은 측정 흐름 확인용이며 기준선 값이 아니다.
- 실제 실행은 질문당 LLM 3~5번이다. 같은 설정으로 전후를 재고, 모델·effort를 바꾸는 비교(#216·#217)는 `--label`로 구분한다.
- 첫 질문은 프롬프트 캐시가 비어 있어 느릴 수 있다. 캐시 효과(#218)를 볼 때는 같은 실행 안의 2번째 질문부터 비교한다.

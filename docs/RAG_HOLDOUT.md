# 새 질문 기준값 검증과 o02 Agent 확인

기존 36개 질의로 선택했던 관련도 후보 하한 `0.02`를 새로운 질문에서 검증한다.
`data/eval/rag_queries_holdout_v1.toml`은 정상 12개(매뉴얼·룰·SOP 각 4개)와
직접 답변 근거가 없는 12개로 구성한다. 기존 질의와 문장 중복이 없고, 점수를
보기 전에 정답 문서·키워드와 하한을 고정한다. 전문가 검토 전 질의 초안이며
동일한 문서군을 사용하므로 문서·의미 범주까지 독립인 검증은 아니다.

근거 없음 질문 중 n01~n06은 문서와 용어가 가깝지만 요청한 공식·정격·품번 등
상세 정보가 없다. 문서가 적용 한계나 금지 사항을 설명할 수는 있다.
따라서 이 질문의 검색 오반환은 곧 Agent의 허위·위험 답변을 뜻하지 않는다.

## 기준값 검증

기본 실행은 계획만 출력하고 모델을 로드하지 않는다. `--execute`를 지정하면
구조 기반 청킹과 Qdrant 임시 저장소에서 문서를 색인하고, 각 질문의 후보 30개를
리랭커로 한 번 채점한다. 같은 후보에서 필터 없음과 `0.02`를 각각 적용한 뒤
최종 5개를 고른다. 공개 Retriever와 동일하게 하한 이상을 포함한다.
보류셋으로 임계값을 재선정하거나 운영 설정을 자동 변경하지 않는다.
사용자 지정 질문 파일도 정상 질문과 근거 없음 질문을 각각 1개 이상 포함해야 한다.
빈 파일이나 한 범주만 있는 파일은 모델을 호출하기 전에 오류로 종료한다.

PowerShell, 저장소 루트 기준:

```powershell
$env:PYTHONPATH = "src"
$env:PYTHONUTF8 = "1"
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:EMBEDDING_MODEL = "BAAI/bge-m3"
$env:RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
$env:RAG_CANDIDATE_K = "30"
$env:OMP_NUM_THREADS = "4"
$env:MKL_NUM_THREADS = "4"
$env:TOKENIZERS_PARALLELISM = "false"
uv run --no-sync python scripts/validate_rag_holdout.py
uv run --no-sync python -u scripts/validate_rag_holdout.py --execute --out outputs/rag_e2e/holdout-new
```

후보 하한은 `--minimum`으로 재현할 수 있고 기본값은 `0.02`다.
각 질의 완료 시 `results.json`·`report.md`를 저장한다. 기존 출력 폴더는 거부하며
실패 시 완료한 질문만 보존하고 `complete=false`와 `failure.json`을 남긴다.
종료 코드 0은 측정 완료이며 검색 품질·거절률의 합격을 의미하지 않는다.
기존 `o02`는 대조 질문으로 별도 측정하고 보류셋 지표에서 제외한다.

## 실제 o02 Agent

`o02`는 일반 질문이므로 사건을 새로 만들지 않고 실제 자유 대화 Agent를 사용한다.
평가용 SQLite 문서 레지스트리와 Qdrant에 같은 PDF 3종을 등록한다.
`DatabaseChatKnowledge`의 승인·판·해시·출처 검사와 실제 Claude 도구 루프를 거치며,
대화나 분석 결과를 운영 DB에 저장하지 않는다. 평가용 보고서 레지스트리는 비어 있다.

아래 실제 유료 실행은 사용자가 자기 터미널에서 직접 수행한다. AI 에이전트는
실제 비밀 파일·SDK 인증 프로필을 열거나 인증 유무·유효성을 확인하지 않으며,
실제 `.env`를 로드하거나 유료 LLM 실행을 대신 수행하지 않는다.
자동 검증은 가짜 SDK·클라이언트로만 진행한다(`AGENTS.md`).

```powershell
uv run --no-sync python scripts/check_rag_agent.py
uv run --no-sync python -u scripts/check_rag_agent.py --execute --out outputs/llm_evaluation/o02-new
```

실제 실행에는 기존 SDK 로그인 또는 환경변수로 제공한 Claude 인증이 필요하다.
프로젝트에서 `.env`를 사용한다면 사용자가 직접 `uv run --no-sync --env-file .env`로 실행한다.
기본 계획은 질문 1개, Sonnet 설정을 포함한 현재 `LLM_MODEL`·`LLM_EFFORT`,
대화 최대 4턴과 근거 검토 최대 2회다. 앱 호출은 최대 6회이며, 기존 클라이언트의
통신 재시도로 HTTP 요청 수는 더 많을 수 있다. 실제 응답 모델과 호출별 사용량·
재시도 횟수는 `summary.json`에서 확인한다. 실패한 질문을 자동으로 재실행하지 않는다.

CPU 내용 검증의 전체 시간 예산은 기본 300초이며 `--timeout`으로 지정할 수 있다.
운영 기본 타임아웃이나 응답 지연 SLA를 검증한 것은 아니다.
실행 전 정확한 o02 문장으로 잔존 후보를 확인하되 Agent에게 결과를 강제로 주입하지
않는다. Agent는 평소처럼 검색 도구를 선택한다. 검색하지 않고 범위 밖으로 판단했다면
그 사실도 기록하고, 무관한 검색 결과를 읽고 거절한 경로와 구분한다.

기대 상태는 `INSUFFICIENT_EVIDENCE` 또는 `OUT_OF_SCOPE`다. 상태 일치와 별도로
소화약제·진압 절차를 근거 없이 생성했는지, 한계를 명확히 밝히는지 응답을 검토한다.
원문 응답은 Git 제외 로컬 `response.json`에만 저장한다. 공유 보고서는 상태·호출·
근거 ID와 내용 검토 결과만 기록한다. HTTP 인증·대화 저장 경로는 평가 범위가 아니다.

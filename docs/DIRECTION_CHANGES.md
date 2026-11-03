# 방향 전환 기록

프로젝트 방향을 바꾸면서 **무엇을 없애고 무엇을 바꿨는지** 영역별로 남긴다. 코드 세부는 PR과 커밋에서 보고, 여기에는 "어디에서 어떤 역할을 하던 것이 어떻게 됐는지"만 적는다. 기술 결정의 이유는 [DECISIONS](DECISIONS.md), 새 구조는 [AGENT](AGENT.md).

새 전환은 위에 추가한다.

---

## 2026-11-03 로컬 임베딩·리랭커 모델 제거 (D-31)

| 영역 | 전 | 후 |
|---|---|---|
| 임베딩 | 로컬 `BAAI/bge-m3`(약 2.2GB, `rag/embedder.py`의 HuggingFaceEmbeddings) | `EMBEDDING_PROVIDER=hashing`(기본, 외부 호출 없음) 또는 `voyage`(Voyage AI API) |
| 리랭커 | 로컬 CrossEncoder `BAAI/bge-reranker-v2-m3`(기본 켜짐) | `RERANKER_MODEL` 빈 값이면 끔(기본). 지정하면 Voyage 리랭크 API |
| 의존성 | torch(CPU판 인덱스 설정 포함)·sentence-transformers·langchain-huggingface | 제거. API 호출은 기존 httpx |
| 모델 받기 | `make models`·`scripts/download_models.py` | 제거 |
| 배포 | `HF_HUB_OFFLINE=1`, `hf_models` 볼륨, `HF_HOME=/models` | 제거 |
| 설정 | `EMBEDDING_MODEL=BAAI/bge-m3`, `RERANKER_MODEL=BAAI/bge-reranker-v2-m3` | `EMBEDDING_PROVIDER`·`EMBEDDING_MODEL`(빈 값=공급자 기본)·`EMBEDDING_DIM`·`VOYAGE_BASE_URL`·`VOYAGE_TIMEOUT_S`·`VOYAGE_API_KEY`(키), `RERANKER_MODEL=` |
| 컬렉션 기록 | 모델 이름 | `공급자:모델:차원`. 바꾸면 새 컬렉션에서 문서 재등록 |
| 스모크 테스트 | `test_real_model_smoke.py`(`RAG_SLOW_TESTS=1`) | `test_live_embedding_api.py`(`RAG_LIVE_API_TESTS=1`, 유료, 사용자가 실행) |

### 그대로 둔 것

- 저장소(Qdrant·Chroma)의 dense + Kiwi BM25 + RRF 하이브리드 구조, 리랭커 끄기 설정(빈 값), `RAG_MIN_RELEVANCE`(리랭커 있을 때만).
- 과거 실측 기록(RAG_E2E·RAG_HOLDOUT 등)은 지우지 않고 "재현되지 않음" 안내만 붙였다.

## 2026-10-29 문서 관리를 웹·PostgreSQL로 통일

- 운영 카탈로그 파일, 카탈로그의 DB seed 동기화·중복 검사, `RAG_CATALOG`, `make index`와 전용 실행 스크립트를 제거한다(D-28).
- 웹 등록 시 자동 파싱·청킹·임베딩·벡터 저장, DB 기반 해시 중복 검사, 관제 담당자 권한은 유지한다.
- 삭제 성공 시 PostgreSQL 문서 행도 실제 제거한다. 실패 상태는 재시도를 위해 남기고 원본 PDF는 보관한다. 이전 `deleted` 행은 마이그레이션 0006에서 정리한다. 미공유 문서 정리 0005를 먼저 적용한 개발 DB에는 누락된 공식 0005의 `analysis_job`도 보완한다.
- 검색 평가 도구는 별도 평가 자료 목록과 임시 저장소를 사용한다. 운영 DB나 등록 문서에는 영향을 주지 않는다.


## 2026-10-29 로컬 LLM(Ollama) 폐지 → 상용 LLM(Claude) + 싱글 에이전트

- 계기: 10/29 멘토링 피드백("비용은 고려하지 않는다, 로컬 LLM이 오히려 비싸다", "에이전틱 서비스가 먼저", "싱글보다 멀티 에이전트·메모리 관리")
- 결정: DECISIONS D-25(D-21 번복), D-26
- 이슈: #11 하위 #101(전환), #102(싱글 에이전트), #103(멀티 에이전트·메모리 설계)

### 없앤 것

| 영역 | 있던 것 | 하던 역할 |
|---|---|---|
| agent 모듈 | Ollama 클라이언트 | 로컬 qwen3:8b에 JSON 스키마로 분석 초안을 요청 |
| 설정 | `OLLAMA_BASE_URL`·`OLLAMA_MODEL`·`OLLAMA_THINK`·`OLLAMA_KEEP_ALIVE` | 로컬 서버 주소, 모델명, 생각 단계 켜기, 모델 메모리 유지 시간 |
| docker compose | `ollama` 서비스(선택 프로필)와 모델 볼륨 | Linux 서버에서 Ollama 컨테이너 실행 |
| Makefile | `make ollama-up` | Ollama 컨테이너 기동 |
| 모델 받기 스크립트 | LLM 다운로드(`ollama pull`)와 `--skip-ollama` 옵션 | 새 PC에서 LLM 모델(5.2GB) 받기 |
| 테스트 | Ollama 클라이언트 테스트 | 로컬 서버 응답·오류 처리 검증 |
| 문서 | LOCAL_SETUP의 Ollama 설치 절, README의 "로컬 LLM" 원칙 | 설치 안내, "데이터를 외부로 보내지 않음" 원칙 |
| 팀 스킬 | ww-setup의 Ollama 단계, ww-review-before-pr의 Ollama 문구 | 새 팀원 환경에서 모델 확인·설치 |

### 바꾼 것

| 영역 | 전 | 후 |
|---|---|---|
| LLM 호출 | 로컬 Ollama | Claude API(`agent/claude.py`). 키는 `.env`의 `ANTHROPIC_API_KEY` |
| 설정 | Ollama 4종 | `LLM_MODEL`·`LLM_EFFORT`·`AGENT_MAX_TURNS` 추가, `LLM_TIMEOUT_S` 기본 60→120초 |
| Agent 워크플로 | 없음(LLM 클라이언트만) | 도구 호출 루프 싱글 에이전트(`runtime.py`·`analyst.py`), `make analyze` |
| LLM 점검(`make llm-check`) | Ollama 모델·생각 단계 비교 | 같은 사례로 Claude 모델·effort 비교, 제출 검사를 에이전트와 공유 |
| 분석 결과의 모델 표기 | `ollama/<모델>` | `anthropic/<모델 ID>`(계약 모양은 그대로, 예시 주석만) |
| 모델 받기(`make models`) | 임베딩·리랭커·LLM 약 10GB | 임베딩·리랭커 약 4.5GB |
| 원칙 | 로컬 LLM으로 데이터 외부 반출 금지 | 사건 정보·검색 조각만 API로 보내고 사번·결재 정보는 보내지 않음 |

### 그대로 둔 것

- 임베딩·리랭커(bge-m3·bge-reranker-v2-m3)는 계속 로컬에서 돈다. RAG 검색 구조(D-08~D-22)는 바뀌지 않았다. (2026-11-03 로컬 모델 제거로 바뀜, 위 절)
- `AnalysisResult` 계약과 "근거가 없으면 멈춘다" 규칙.
- 평가 사례(`data/eval/llm_cases_v1.toml`). 같은 사례로 전후를 비교할 수 있다.
- 과거 실측(D-21의 qwen3:8b 수치)은 기록으로 남긴다.

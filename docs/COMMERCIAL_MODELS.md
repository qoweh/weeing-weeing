# 로컬 모델 → 상용 API 전환 점검

프로젝트 초반에는 로컬 모델로 개발했다. 지금은 셋 다 상용 API다. 이 문서는 전환으로 **신경 쓸 필요가 없어진 것**과 **새로 신경 써야 하는 것**, 그리고 로컬 모델을 기준으로 정했던 값 중 **다시 정해야 하는 것**을 정리한다(2026-11-04 점검).

| 역할 | 예전(로컬) | 지금(상용) | 결정 |
|---|---|---|---|
| LLM | Ollama `qwen3:8b` | Claude API (`LLM_MODEL`, 기본 `claude-sonnet-5-5`) | D-21 → D-25·D-30 |
| 임베딩 | `BAAI/bge-m3` (1024차원) | Voyage `voyage-4-lite` (1024차원). 키가 없으면 `hashing` | D-31 |
| 리랭커 | `BAAI/bge-reranker-v2-m3` | Voyage `rerank-3-lite`. 비우면 끔 | D-31 |

없앤 코드·설정 목록은 [DIRECTION_CHANGES](DIRECTION_CHANGES.md), 공급자 선정 이유는 [EMBEDDING_API](EMBEDDING_API.md), 외부 전송 점검표는 [AI_DATA_SECURITY](AI_DATA_SECURITY.md).

## 1. 이제 고려하지 않아도 되는 것

| 항목 | 예전에 했던 일 | 지금 |
|---|---|---|
| 모델 받기·보관 | `make models`로 임베딩 2.2GB·리랭커 2.3GB, Ollama 모델을 받고 `hf_models` 볼륨에 보관 | 받을 것이 없다. 서버 남은 `hf_models` 볼륨은 지워도 된다([DEPLOY](DEPLOY.md)) |
| 서버 사양·메모리 | 모델을 메모리에 올릴 RAM, CPU 추론 속도를 걱정 | API 서버는 HTTP 호출만 한다. EC2 사양은 DB·Qdrant 기준으로만 본다 |
| GPU·플랫폼 차이 | macOS 컨테이너 Ollama는 GPU를 못 써서 앱을 컨테이너 밖에서 실행(D-03) | 플랫폼과 무관하게 같은 속도·결과 |
| 첫 호출 지연(모델 로드) | 첫 임베딩·리랭크 때 가중치 로딩, `Loading weights` 로그 | 없다(Kiwi 형태소 분석기 로드만 남음) |
| 배포 이미지 크기 | torch·sentence-transformers 포함 | 의존성 제거(uv.lock −473줄). 이미지가 작고 빌드가 빠르다 |
| 오프라인 고정 | `local_files_only=True`, `trust_remote_code=False`로 원격 코드 실행 차단 | 원격 가중치·코드를 불러오지 않는다 |
| 로컬 LLM 출력 다듬기 | qwen의 생각 끄기, `format` JSON 스키마로 문법 제약, 사례당 10~32초 | Claude 구조화 출력(strict 도구·`output_config.format`)과 서버 측 `fallbacks` |
| 리랭커 배치 크기 조정 | CPU 메모리 때문에 `--reranker-batch-size 2` | 한 요청 최대 1,000개. 기본 100 |
| 모델 버전 고정 | 가중치 파일 자체가 버전 | 이름만 고정(아래 2-6 참고) |

## 2. 새로 고려해야 하는 것

### 2-1. 데이터가 밖으로 나간다 (가장 중요)

- 문서 본문·승인 보고서·질문이 Voyage로, 사건·센서 근거·대화가 Anthropic으로 나간다
- Voyage(MongoDB) 조직 설정의 "모델 개선에 데이터 사용"을 꺼야 한다. 꺼졌는지는 아직 기록이 없다 → **확인 필요**
- 정리: [AI_DATA_SECURITY](AI_DATA_SECURITY.md) 점검표. 시연 데이터는 가상 공정이라 지금은 문제 없지만, 실제 설비 문서를 넣기 전에는 점검표를 통과해야 한다

### 2-2. 비용과 한도

| 공급자 | 지금 관리 | 빈 곳 |
|---|---|---|
| Claude | Langfuse에 사람별·모델별 비용 기록, Slack 알림(1인 일 $1.5, 콘솔 월 한도 $30의 95%) | 콘솔 월 한도에 닿으면 **팀 전체 분석·챗봇이 멈춘다**. 알림만 하고 막지는 않는다 |
| Voyage | 4세대 모델 무료 2억 토큰, 이후 $0.02/1M | `VoyageEmbedder.total_tokens`·`VoyageReranker.total_tokens`를 세기만 하고 **어디에도 기록하지 않는다**. 사용량은 Voyage 대시보드에서만 보인다 |

- Voyage는 결제 수단이 없는 계정의 요청 한도가 아주 낮다(분당 요청 수 몇 회 수준, 공식 문서 "Rate Limits"). 팀 키에 결제 수단이 있는지 **확인 필요**. 없으면 문서 여러 개를 연달아 등록하거나 챗봇이 한 질문에 검색을 여러 번 할 때 429가 난다
- 챗봇은 한 질문에 검색을 최대 8번 한다. 리랭커를 켜면 검색 1번 = 임베딩 1회 + 리랭크 1회 호출이라 최대 16회다

### 2-3. 장애·지연이 네트워크에 묶인다

- 예전에는 로컬 모델이 느려도 결과는 나왔다. 지금은 Voyage·Anthropic이 안 되면 검색·분석·챗봇이 같이 실패한다
- 실패할 때 동작(지금 코드):

  | 기능 | Voyage 실패 | Claude 실패 |
  |---|---|---|
  | 문서 등록 | 문서 상태 `failed`, 다시 올려야 함 | 해당 없음 |
  | 승인 보고서 색인 | `report_index_job` `failed`, `make index-reports ARGS=--retry-failed` | 해당 없음 |
  | 사건 분석 | `FAILED` | `FAILED` |
  | 챗봇 | "검색 불가" | 오류 안내 |

- Voyage 호출은 타임아웃 30초에 429·5xx 재시도 2회(1초, 2초 대기)다. 최악이면 검색 한 번에 약 90초가 걸린다. 챗봇 체감 시간에는 길다 → `VOYAGE_TIMEOUT_S`를 10초 안팎으로 줄일지 시연 전에 정한다
- 시연장 네트워크가 막히면 아무 기능도 돌지 않는다. 대비책은 `EMBEDDING_PROVIDER=hashing` + `RERANKER_MODEL=`(검색만 동작, 품질 낮음)뿐이고, LLM은 대체 경로가 없다

### 2-4. 키 관리

- 키가 셋이다: `ANTHROPIC_API_KEY`(팀원별), `VOYAGE_API_KEY`(팀 공용), Langfuse 키(팀원별)
- Voyage 키는 서버 `.env`와 각자 `.env`에 들어간다. 노출되면 Voyage 대시보드에서 교체하고 서버 `.env`를 바꾼 뒤 `ops/aws.sh up`
- 키 종류와 주소가 맞아야 한다: Voyage 대시보드 키는 `https://api.voyageai.com/v1`, MongoDB Atlas 키는 `https://ai.mongodb.com/v1`. 다르면 HTTP 403

### 2-5. 컬렉션 전환과 다시 색인

공급자·모델·차원이 바뀌면 이전 벡터와 섞을 수 없어서 새 컬렉션(`knowledge_voyage`)을 쓴다. **기존 문서·보고서는 새 컬렉션으로 자동으로 옮겨지지 않는다.**

- 2026-11-04 서버 확인(`ops/aws.sh rag`): 설정은 voyage·`knowledge_voyage`인데 Qdrant 컬렉션이 **하나도 없다**. 컬렉션은 첫 저장 때 만들어지므로, 전환 뒤 문서가 한 번도 등록되지 않았다는 뜻이다. 지금 서버의 챗봇·분석은 근거를 찾지 못한다
- 팀 문서(매뉴얼·룰·규정): `ops/aws.sh seed-docs`(로컬 `make seed-docs`). 같은 파일이 지금 컬렉션에 이미 있으면 건너뛰고, 없으면 임베딩한다(D-32)
- 그 밖에 웹에서 올린 문서: 문서 목록에서 같은 문서 ID로 다시 올리고 교체를 확인한다
- 승인 보고서: DB에 이미 `indexed`로 표시돼 저절로는 다시 등록되지 않는다. `ops/aws.sh reindex-reports`(로컬 `make index-reports ARGS=--all`)로 최신 승인 판을 전부 다시 등록한다
- 확인: `ops/aws.sh rag`의 포인트 수와 DB 집계(`document`·`report_index_job` 상태별 개수)를 비교한다

### 2-6. 모델 이름·가격·동작이 바뀐다

- 로컬 가중치는 그대로였지만 API 모델은 공급자가 바꾸거나 없앤다. `voyage-4-lite`·`rerank-3-lite`·`claude-sonnet-5-5`는 이름으로만 고정돼 있다
- 같은 이름이라도 공급자 쪽 개선으로 점수 분포가 바뀔 수 있다. 하한값(2-7)을 쓰려면 주기적으로 다시 잰다
- 가격·무료 범위는 [EMBEDDING_API](EMBEDDING_API.md)에 2026-11-03 기준으로 적혀 있다. 쓰기 전에 다시 확인한다

### 2-7. 로컬 모델 기준으로 정한 값 — 다시 정해야 한다

| 값 | 어디에 | 왜 문제인가 | 할 일 |
|---|---|---|---|
| 관련도 하한 `0.02` | `scripts/check_rag_agent.py`(고정), `scripts/validate_rag_holdout.py`(기본값), `data/eval/rag_queries_holdout_v1.toml`, 문서 | bge-reranker 점수 분포로 고른 값. Voyage 리랭커 점수(0~1)는 분포가 달라 그대로 쓰면 근거를 너무 많이·적게 거른다 | 운영 기본값은 빈 값(끔)이라 당장 영향 없음. 켜려면 Voyage로 `make rag-e2e`·보류셋을 다시 재서 고른다 |
| 검색 품질 수치 | [RAG_E2E](RAG_E2E.md)·[RAG_RETRIEVAL](RAG_RETRIEVAL.md)의 MRR 0.917, hit@1 15/18 등 | bge-m3 + bge-reranker 결과. 지금 설정의 품질을 말해 주지 않는다 | Voyage 설정으로 `make rag-e2e`를 한 번 돌려 새 기준을 남긴다(수백~수천 토큰) |
| 청킹 비교 결론 | [CHUNKING_COMPARISON](CHUNKING_COMPARISON.md) | legacy·structured 비교가 bge 기준. 명령의 `BAAI/...` 모델은 이제 없다 | 다시 비교할지 결정. 하지 않으면 지금처럼 "당시 기록"으로 둔다 |
| 청크 크기 1,000자·겹침 150자 | `rag/chunker.py` `ChunkerConfig` | 검색 품질을 bge로 재며 정한 값. 입력 길이 한도와는 상관없다(`truncation=True`라 넘쳐도 잘려 들어간다) | 바꿀 필요는 없다. 바꾸면 비용(토큰)과 품질을 같이 잰다 |
| 후보 수 `RAG_CANDIDATE_K=30` | `.env.example` | CPU 리랭커 속도 때문에 작게 둔 값 | 리랭크 1회 요청이라 늘려도 지연은 거의 같고 토큰만 는다. 품질을 재고 정한다 |
| LLM 평가 결과 | [LLM_EVALUATION](LLM_EVALUATION.md) | Claude 기준이라 유효하다. 다만 근거 검색이 bge였던 사례가 섞여 있다 | 검색까지 묶은 사례는 Voyage로 다시 볼지 결정 |
| 워커 1개 | `deploy/api.Dockerfile` | 예전 주석은 "모델이 프로세스 안에 있어서"였다. 지금 이유는 분석 작업 큐·센서 실시간 상태가 프로세스 메모리에 있기 때문이다 | 주석을 고쳤다(이 문서와 같은 PR). 워커 1개는 그대로 둔다 |

### 2-8. 테스트

- 자동 테스트는 가짜 클라이언트만 쓴다(키 없이 돈다). 실제 API 동작은 `RAG_LIVE_API_TESTS=1 uv run --no-sync pytest tests/rag/test_live_embedding_api.py`(각자 터미널, 수백 토큰)로만 확인된다
- 공급자 응답 형식이 바뀌면 자동 테스트는 통과하고 실제로는 실패할 수 있다. 시연·배포 전에 라이브 스모크를 한 번 돌린다

## 3. 우선순위

| 순위 | 할 일 | 담당 판단 |
|---|---|---|
| 1 | 서버에서 `ops/aws.sh seed-docs`, `ops/aws.sh reindex-reports` 실행 후 `rag`로 확인 (2-5) | 시연 전 필수 |
| 2 | ~~승인 보고서 전체 다시 색인 명령~~ → `index_reports.py --all`로 추가함 | 완료 |
| 3 | Voyage 키의 결제 수단·요청 한도, 데이터 학습 사용 끄기 확인 (2-1, 2-2) | 키 관리자 |
| 4 | `VOYAGE_TIMEOUT_S` 시연용 값 결정 (2-3) | 팀 |
| 5 | Voyage 설정으로 `make rag-e2e` 한 번 실행해 새 품질 기준 기록 (2-7) | RAG 담당 |
| 6 | Voyage 토큰 사용량 기록(Langfuse 또는 로그) (2-2) | 선택 |
| 7 | 관련도 하한을 켤지 결정, 켜면 Voyage 점수로 다시 선정 (2-7) | 선택 |

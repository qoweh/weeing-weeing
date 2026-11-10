# RAG 색인·검색·챗봇 연결

매뉴얼·룰·SOP·승인 보고서를 검색 가능한 근거로 만들고 Agent·챗봇에 제공한다.
이 문서는 구현·계약을 설명한다. 실측은 [RAG 성능 평가](rag_e2e/README.md),
실행 방법은 [평가 가이드](RAG_EVALUATION_GUIDE.md), 사건 정답은
[E2E 사례](RAG_E2E_CASES.md)에서 관리한다.

## 구현한 흐름

1. PDF 원본·버전·해시를 등록하고 페이지별 파싱·구조 기반 청킹을 수행한다.
2. 임베딩과 한국어 Kiwi BM25를 저장하고 Dense·BM25 검색 후보를 RRF로 결합한다.
3. 선택한 리랭커로 후보를 재정렬하고, 설정된 관련도 하한을 적용해 상위 K개를 고른다.
4. 본문과 문서 ID·버전·쪽·절·출처·점수를 공통 Evidence로 반환한다.
5. 문서 변경은 해시·버전으로 감지해 해당 문서의 청크를 교체한다.

## 코드와 책임

| 위치 | 책임 |
|---|---|
| `rag/pdf_parser.py`, `parsers.py` | PDF 본문·쪽·표 등 파싱 |
| `rag/chunker.py`, `structured_chunker.py` | 길이·표 행 보존, 조항·대응 사례 및 문맥을 고려한 분할 |
| `rag/indexer.py` | 문서별 변경 감지·청크 생성·갱신 |
| `rag/embedder.py`, `sparse.py` | 해시/Voyage 임베딩, 한국어 BM25 |
| `rag/store.py`, `qdrant_store.py`, `chroma_store.py` | 저장·필터·Dense/BM25·RRF |
| `rag/retriever.py`, `reranker.py` | 후보·리랭킹·관련도 필터·근거 변환 |
| `rag/report.py` | 승인된 정비 보고서의 사람 작성 원인·조치를 검색 사례로 구성 |
| `rag/interface.py`, `factory.py` | 외부 공개 경계·설정 조립·색인기와 검색기의 저장소 공유 |
| `rag/eval_corpus.py`, `eval_sync.py`, `e2e.py` | 운영 목록과 분리한 평가 입력·색인·검색 검사 |

다른 모듈은 `rag/interface.py`와 contracts만 import한다.
PLC는 RAG에 의존하지 않는다. 인덱서·검색기는 프로세스 안에서 저장소를 공유하며
매 요청 새로 만들거나 공유 저장소를 닫지 않는다.

## 후보·점수·실패 규칙

- `k`는 최종 반환 개수다. 리랭킹을 켜면 `max(k, RAG_CANDIDATE_K)`개를 저장소에서 받는다.
  저장소 내부 dense·BM25 prefetch는 기존처럼 이 후보 수의 4배다.
- 리랭킹을 끄면 기존대로 저장소에 `k`를 전달한다. 후보 수 기본값 30은 조정 시작값이다.
- 필터는 후보 검색 전에 적용한다. `code`는 `codes` 별칭이며 두 키를 함께 쓰면 오류다.
- 리랭커는 모델 점수를 `Hit.relevance`에 담은 새 Hit를 관련도순으로 반환한다. 원본 후보를 수정하지 않고 ID·버전·본문·출처·RRF 점수는 보존한다.
- 반환 목록의 순서가 최종 관련도다. `Evidence.score`는 원래 RRF 점수이므로 다시 score로 정렬하지 않는다.
  모델 점수와 RRF 점수를 합산하거나, RRF 점수를 확률·근거 충분성 임계값으로 사용하지 않는다.
- `Evidence.relevance`는 모델 출력 점수다. 리랭커를 끄면 `None`(미측정)이다. 0점·관련 없음으로 간주하지 않는다. 점수 범위는 모델에 따라 다르며 확률로 해석하지 않는다.
- `HybridRetriever(..., min_relevance=값)` 또는 `RAG_MIN_RELEVANCE`를 지정하면 모델 점수가 하한 **이상**인 후보만 남긴 뒤 k개를 고른다. 전부 미달하면 `[]`다. 빈 값/None은 필터를 끄며, 리랭커 없이 하한을 지정하면 설정 오류다. 점수 누락·비정상 값도 오류로 전달한다.
- 동점이면 입력 순서를 유지한다. 점수 개수 불일치·NaN·무한대는 오류다.
- 빈 검색 결과는 `[]`다. 검색·임베딩·리랭크 API 실패는 예외로 전달한다. 실패를 근거 없음으로 바꾸거나 조용히 RRF로 대체하지 않는다.
- Agent는 근거가 없으면 `INSUFFICIENT_EVIDENCE`로 멈춘다. 검색 결과가 있다는 사실만으로 근거가 충분하다고 판단하지 않는다.

## 설정과 공개 검색 예시

기본은 해시 임베딩·리랭커 끔이다. Voyage 구성·모델·차원 변경과 새 컬렉션 정책은
[EMBEDDING_API](EMBEDDING_API.md)를 따른다. 리랭커 없이 관련도 하한만 설정할 수
없다. 모델이 바뀌면 기존 하한을 그대로 적용하지 않고 같은 평가셋으로 다시 검증한다.

```python
from weeing_weeing.rag.interface import get_retriever, incident_query

retriever = get_retriever()
evidence = retriever.search("입구 센서 장기 점유 시 점검 방법", k=5)
# 사건 검색은 retriever.search(incident_query(incident), k=5)로 연결한다.
```

고장 코드가 없는 SOP 절차도 필요하므로 사건 검색에 코드 필터를 기본 강제하지 않는다.
코드·승인 상태 필터는 호출 목적에 맞게 선택한다. RAG의 공통 검색과 챗봇의 승인·판·
출처 정책은 구분한다. 전체 저장소 Markdown을 자동 색인하지 않는다.

## 챗봇·승인 보고서 연결

`MetadataRetriever.search_hits()`는 페이지·제목·해시를 유지한다.
API는 DB에서 현재 검색 대상의 ID→버전을 선택하고 그 판이 완전히 색인됐는지
확인한다. 이 대상 집합은 사용자별 ACL이 아니라 존재·버전·승인·조건 정책이다.
문서 위치 누락, 파일과 다른 해시, 개정·삭제 등은 최종 출처 반환 전에도 검사한다.
자세한 정책은 [CHATBOT](CHATBOT.md)을 따른다.

승인 보고서는 사람이 작성한 확인 원인·실제 조치·설비·조치일을 사례로 색인하며
AI 추정·결재 정보·개인정보는 검색 본문에 넣지 않는다. 가상 여부는 출처에 보존한다.
정확한 기간·보고서 전체 건수는 벡터 top-K가 아닌 DB 구조화 경로로 계산한다.

## 문서 목록·등록·삭제 (#110)

운영 문서는 HMI의 **자료 관리 → 문서 목록 / 문서 등록**에서 관리하며 PostgreSQL의 `document` 테이블이 기준 목록이다. 새 문서는 별도 파일 목록에서 자동으로 들어오지 않는다.

- 로그인한 사용자는 `GET /documents`로 매뉴얼·SOP·룰의 제목(업로드 PDF 파일명), 버전·검색 등록 상태를 조회한다. 승인 보고서는 목록·삭제 대상에서 제외한다.
- 관제 담당자만 `POST /documents`로 등록하거나 `DELETE /documents/{doc_id}`로 삭제한다. 관리자 표시만으로는 허용되지 않는다.
- 웹 등록은 원본·DB 접수 정보 저장 → 파싱 → 청킹 → 임베딩 → 벡터 저장 → 완료 순서다. 중복 검사는 현재 DB의 완료된 문서와 최근 처리 중인 문서의 파일 해시를 기준으로 한다. 같은 문서 ID는 개정판으로 허용한다.
- DELETE 본문은 목록에서 받은 `doc_version`, `source_sha256`, `upload_id`다. 그사이 새 판이 등록되면 409로 거절하므로 목록을 새로고침한다.
- 삭제는 해당 문서 ID의 벡터 청크 제거 후 DB 모든 판의 행을 실제 삭제한다. 원본 PDF·검토 파일은 보관한다. 필요하면 웹에서 재업로드한다.
- 삭제 중에는 `deleting`, 실패하면 `delete_failed`로 남겨 재시도한다. 벡터 삭제 후 DB 처리가 실패해도 다음 삭제 요청에서 청크 0건 삭제를 허용하고 DB 정리를 마친다. 성공한 문서의 DB 행은 남기지 않는다.
- 마이그레이션 `0005`는 이전 구현에서 `deleted`로 남긴 매뉴얼·SOP·룰 행만 정리한다. 활성 문서와 삭제 진행·실패 문서는 유지한다.
- 문서 ID별 PostgreSQL 세션 advisory lock으로 등록·삭제를 직렬화하고 진행률을 커밋한다. 개발용 SQLite는 `BEGIN IMMEDIATE`를 사용한다.
- 운영 카탈로그·자동 seed 동기화·`make index`는 제거했다. 이미 등록된 기존 `origin=seed` 문서는 일반 문서처럼 조회·삭제·새 업로드로 대체할 수 있다. 평가용 목록 `data/eval/rag_documents_v1.toml`은 운영 DB와 별개다.
- 영향 모듈: contracts·db·rag·api·HMI. 승인 보고서의 자동 검색 등록과 `make index-reports`는 유지한다.

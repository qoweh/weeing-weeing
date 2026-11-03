# RAG E2E 검증 결과 (#28)

실제 문서 3종·실제 임베딩 모델·실제 Indexer로 벡터 DB(#7)를 처음부터 끝까지 확인한 기록이다. 측정 도구는 `make rag-e2e`(`scripts/verify_rag_e2e.py`), 원본 보고서는 [`rag_e2e/`](rag_e2e/)에 날짜별로 둔다.

> **2026-11-03 이후**: 로컬 임베딩·리랭커(bge-m3·bge-reranker-v2-m3)는 제거됐다(D-31). 아래 수치와 명령은 그때의 기록이며 지금 코드로는 그대로 재현되지 않는다. 현재 구성은 [EMBEDDING_API](EMBEDDING_API.md).

## 2026-10-27 측정 ② 리랭커 실측·Incident 질의 (#8)

#71의 리랭커(`RERANKER_MODEL`, 후보 `RAG_CANDIDATE_K`=30)에 `BAAI/bge-reranker-v2-m3`를 넣어 처음으로 실제 모델 품질을 쟀다. 질의는 Incident 코드 질의 6개를 더해 18개(코드 → `interface.incident_query`와 같은 질의문, 정답은 대응 절 본문 문구).
`RERANKER_MODEL=BAAI/bge-reranker-v2-m3 make rag-e2e ARGS="--backends qdrant,chroma"`, 원본 [`rag_e2e/report-2026-10-27-rerank.md`](rag_e2e/report-2026-10-27-rerank.md).

| 방식(Qdrant·Chroma 같은 값) | hit@1 | hit@5 | MRR |
|---|---|---|---|
| dense | 12/18 | 18/18 | 0.798 |
| hybrid | 11/18 | 18/18 | 0.773 |
| **reranked** | **15/18** | 18/18 | **0.917** |

- 리랭커가 hybrid의 약점(코드 목록 표 쏠림 q05·q06)과 표현이 다른 질의(q01·q02·q12)를 함께 끌어올렸다. Incident 코드 질의 6개는 reranked에서 모두 1위.
- Incident 질의문 형태가 결과를 크게 바꿨다(코드 질의 6개, 리랭크 MRR): 전체 코드+짧은 코드+이름 0.458 → **짧은 코드+이름+대응 문구 1.000**(D-22, `rag/query.py` 주석).
- 비용(M1 Pro): 모델 약 2.3GB, 첫 호출 로딩 약 10초, 이후 후보 20~30개에 1초 안팎.

## 2026-10-27 측정 ①

**환경**

| 항목 | 값 |
|---|---|
| 코드 | `feat/28-e2e-verification` 커밋 `65d2ebc`(dev `d36e6cf` 포함, PR #58 색인 경로 통합 반영) |
| 문서 | 현재 평가 입력 `data/eval/rag_documents_v1.toml`의 PDF 3종(운영 등록과 분리): BTT-MANUAL 2.0, BTT-RULE 2.0, BTT-SOP-001 1.1(draft) |
| 임베딩 | `BAAI/bge-m3`(정규화), 키워드 `kiwi-bm25-v2` |
| 백엔드 | Qdrant 로컬 모드 · Chroma 내장 모드 · **Qdrant 서버(Docker `qdrant/qdrant:v1.20.0`)** |
| 질의 | `data/eval/rag_queries_v1.toml` 12개(정답 = 기대 문서 + 기대 키워드) |
| 명령 | `make qdrant-up` 후 `HF_HUB_OFFLINE=1 EMBEDDING_MODEL=BAAI/bge-m3 QDRANT_URL=http://localhost:6333 make rag-e2e ARGS="--backends qdrant,chroma,qdrant-server"` (약 2분) |
| 원본 | [`rag_e2e/report-2026-10-27.md`](rag_e2e/report-2026-10-27.md) |

**결과 요약**

| 확인할 것 | 결과 |
|---|---|
| **#7 완료 조건**: 청크가 저장되고, 문서를 수정하면 인덱스가 갱신된다 | ✅ 세 백엔드 모두 색인 → 재실행 unchanged → 버전을 올리면 옛 청크 0·새 청크 28 |
| **로컬 vs 서버** | ✅ 차이 없음. Qdrant 로컬·서버·Chroma의 순위·점수가 모두 같다 |
| 문서별 청크 수 | 매뉴얼 28 · 룰 21 · SOP 32 (총 81) |
| 메타데이터 | `page`·`citation` 누락 0, `section` 누락 3(표지), `codes` 없는 청크 51(SOP 32개 전부 + 코드가 안 나오는 본문, 정상) |

**검색 비교** (세 백엔드 같은 값)

| 방식 | hit@1 | hit@5 | MRR |
|---|---|---|---|
| dense(의미) | **9/12** | 12/12 | **0.822** |
| hybrid(의미 + Kiwi BM25, RRF k=60) | 7/12 | 12/12 | 0.743 |

| 질의 | dense 순위 | hybrid 순위 |
|---|---|---|
| q01 입구 센서 장기 점유 | 5 | 4 |
| q02 출구 지연·미도착 | 3 | 3 |
| q05 RPM 하한 이탈(M02) | **1** | 2 |
| q06 구동측 진동 RMS 상한(M12) | **1** | 3 |
| q12 결측 시 룰 판정 | 3 | **2** |
| 나머지 7개 | 1 | 1 |

## 해석

- **벡터 DB는 완료 조건을 만족한다.** 저장·갱신·삭제가 세 백엔드에서 같게 동작하고, 개발용 로컬 모드와 실제 서버 엔진의 결과가 같다.
- **이 질의 세트에서는 hybrid가 dense보다 1위 적중이 적다.** 손해 본 q05·q06은 질의에 코드(M02·M12)가 들어가는데, 매뉴얼의 **코드 목록 표** 청크가 여러 코드를 나열해 키워드 점수가 높게 나오고, 실제 대응 절을 밀어냈다. 대신 q01·q12처럼 표현이 다른 질의에서는 hybrid가 순위를 올렸다.
- 질의가 12개라 표본이 작고, 두 방식 모두 상위 5개 안에는 정답이 들어온다. 결론은 "기본은 hybrid 유지, 다음 개선의 기준선으로 이 숫자를 쓴다"이다.

## 다음에 비교할 것 (이 기준선 대비)

| 개선 | 담당 | 기대 |
|---|---|---|
| ~~`codes` 필터 기본 적용~~ | #8 | 하지 않기로 함: 코드 없는 SOP 절차 조각이 빠진다. 질의문의 짧은 코드로 대신(D-22) |
| ~~리랭커~~ | #8 | #71 구현 + ② 실측(MRR 0.773 → 0.917) |
| 구조 기준 청킹(조·사례 단위) + 문맥 머리줄 | #6 | 표 청크·조항 끊김 완화 |
| dense·sparse 가중치(RRF 대신 가중 결합) | #7 후속 | 코드 표 쏠림 완화 |
| 한국어 임베딩 모델 비교(KURE-v1 등) | #6 | dense 자체 품질 |
| 평가셋 확대(질문 20~30개 + 정답 청크) | #8 | 표본 크기 |

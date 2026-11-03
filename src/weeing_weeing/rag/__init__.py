"""rag — 정비 지식베이스 구축과 근거 검색 (1차 분담: RAG 지식베이스).

책임: 매뉴얼·룰 정의서·SOP·승인된 보고서를 파싱·청킹·임베딩해 저장하고(Indexer),
      Incident 정보로 근거를 찾아 출처와 함께 돌려준다(Retriever).
입력: 웹에서 업로드한 PDF, 승인된 MaintenanceReport의 사람 작성 칸
출력: list[Evidence]
의존 가능: contracts
담당 메모: 전처리·인덱싱 승민 / Vector DB 민우 / 검색·Reranking 동인 (1차 분담)

내부 파일 (다른 모듈은 interface.py만 import)
- pdf_parser.py, chunker.py: 파싱·청킹 (#6)
- embedder.py: 임베더. hashing(기본, 비용 0) 또는 Voyage API. 로컬 모델 없음
- store.py: 저장 계층 계약. Chunk·Hit·Embedder·VectorStore (#7, #22)
- qdrant_store.py: VectorStore Qdrant 구현, 기본 백엔드 (#23)
- chroma_store.py: VectorStore Chroma 구현, 대체 백엔드 (#24)
- sparse.py: Kiwi 형태소 BM25 인코더와 메모리 BM25. hybrid_query의 키워드 쪽 (#25)
- retriever.py: HybridRetriever. 후보 검색·선택적 리랭킹·상위 k개 Evidence 변환
- reranker.py: Voyage 리랭크 API(선택). 청크·출처·RRF 점수는 보존하고 순서만 변경
- eval_corpus.py, eval_sync.py: 검색 평가 전용 자료 목록·임시 저장소 구성
- factory.py: 설정으로 저장소를 한 번 조립(build_store) (#27)
- parsers.py, indexer.py: 형식별 파서 등록과 범용 Indexer. 웹 업로드·검색 평가 공용 (#6·#7)
- e2e.py: 실제 문서 E2E 검증(색인·멱등·갱신·검색 비교), make rag-e2e (#28)
"""

"""rag — 정비 지식베이스 구축과 근거 검색 (1차 분담: RAG 지식베이스).

책임: 매뉴얼·룰 정의서·SOP·승인된 보고서를 파싱·청킹·임베딩해 저장하고(Indexer),
      Incident 정보로 근거를 찾아 출처와 함께 돌려준다(Retriever).
입력: data/knowledge 문서, 승인된 MaintenanceReport의 사람 작성 칸
출력: list[Evidence]
의존 가능: contracts
담당 메모: 전처리·인덱싱 승민 / Vector DB 민우 / 검색·Reranking 동인 (1차 분담)
"""

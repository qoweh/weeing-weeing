"""agent — Ollama LLM 기반 원인 추론과 대응 제안 (1차 분담: AI Agent).

책임: Incident를 해석해 rag.Retriever로 근거를 찾고, 원인 후보·점검 순서·대응 절차를
      AnalysisResult로 만든다. 근거가 없으면 INSUFFICIENT_EVIDENCE로 멈춘다.
입력: Incident
출력: AnalysisResult  (interface.Analyzer)
의존 가능: contracts, rag.interface
금지: 보고서의 maintenance·approval 칸 작성, PLC 제어

- errors.py: LLM 실패 예외와 사용량(LlmUsage). 공급자와 무관
- ollama.py: Ollama 네이티브 /api/chat 클라이언트(LlmClient), JSON 스키마 구조화 출력 (#10)
- llm_check.py: 구조화 출력 점검(make llm-check) (#10)
"""

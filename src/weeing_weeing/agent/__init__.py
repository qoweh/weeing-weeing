"""agent — 상용 LLM(Claude) 에이전트의 원인 추론과 대응 제안 (1차 분담: AI Agent).

책임: Incident를 해석해 rag.Retriever로 근거를 찾고, 원인 후보·점검 순서·대응 절차를
      AnalysisResult로 만든다. 근거가 없으면 INSUFFICIENT_EVIDENCE로 멈춘다.
      챗봇 질문에는 주입된 검색기·FAQ로 출처가 연결된 ChatResponse를 만든다.
입력: Incident, ChatQuestion
출력: AnalysisResult (interface.Analyzer), ChatResponse (interface.ChatService)
의존 가능: contracts, rag.interface, config
금지: 보고서의 maintenance·approval 칸 작성, PLC 제어, db·api 내부 import

- errors.py: LLM 실패 예외와 사용량(LlmUsage). 공급자와 무관
- claude.py: Claude API 클라이언트(LlmClient), 구조화 출력·도구 호출 한 걸음 (#101)
- runtime.py: 에이전트 정의·도구 호출 루프·실행 기억. 멀티 에이전트 확장의 기반 (#102)
- analyst.py: 사건 분석 에이전트(Analyzer 구현), 근거 검색 도구와 제출 검사 (#102)
- multi_analysis.py, analysis_briefs.py, baseline_sensors.py: LangGraph 멀티 분석·역할별 요약 기준·기본 센서 조회 정책
- sensor_window.py: 주입된 읽기 경계로 사건 센서 구간 요약·제출 수치 대조 (#105, DB 직접 접근 없음)
- chat.py: 챗봇 도구 호출 루프(ChatService 구현). 서버 검증 검색과 인용 검증 (#89)
- chat_grounding.py, chat_efficiency.py, chat_usage.py: 답변 근거 검토·정형 건수 답변·호출별 사용량
- faq.py: 파일 기반 FAQ 조회 (#87)
- tracing.py, trace_smoke.py: Langfuse 사용량 기록 (#113)과 무과금 재생 확인 (#206)
- llm_check.py, chat_baseline.py: 구조화 출력 점검(make llm-check)·챗봇 지연 기준선(make chat-baseline)
설계: docs/AGENT.md
"""

# RAG 평가 방법

청킹 비교·검색 E2E·새 질문 하한 검증·챗봇 응답 검토의 실행 방법을 한곳에 모았다.
측정된 수치는 [평가 결과](rag_e2e/README.md), 사건 분석 사례와 재현 준비는
[승인 사례](RAG_E2E_CASES.md)·[스냅샷](RAG_E2E_SNAPSHOT.md)에서 관리한다.
과거 BGE 모델·하한 0.02는 과거 실측 조건이며 현재 Voyage 구성의 권장값이 아니다.

## 1. 청킹 본문 비교

`compare_chunking.py`는 PDF를 기존/구조 기반으로 나눈 Markdown을 만든다.
DB·벡터 저장소·모델을 호출하지 않는다. PowerShell, 저장소 루트 기준:

```powershell
$env:PYTHONPATH = "src"
$env:PYTHONUTF8 = "1"
uv run --no-env-file --no-sync python scripts/compare_chunking.py data/manuals/BTT-MANUAL_v2.0.pdf --output-dir outputs/chunking-comparison --doc-id BTT-MANUAL --version 2.0 --doc-type manual --asset-id BLDC-001
```

같은 ID로 다시 실행하면 비교용 두 Markdown을 덮어쓴다. 본문이 포함되므로 공유 전
자료 공개 범위를 확인한다. 구조 기반은 페이지 안의 조항·대응 사례 경계, 문맥·반복
제목을 보존하며 경계를 인식하지 못하면 기존 분할기를 사용한다. 페이지 사이의
조항을 자동 결합하거나 모든 PDF 구조를 인식하는 방식은 아니다.
웹 신규 업로드는 구조 기반이고 기존 색인은 자동 변환하지 않는다.

## 2. API 없는 검색 기준선

다음 명령은 해시 임베딩·BM25·리랭커 끔으로 고정해 외부 API를 사용하지 않는다.
실제 비밀 파일을 로드하지 않는다. 임시 로컬 Qdrant에 문서를 색인한다.

```powershell
$env:PYTHONPATH = "src"
$env:PYTHONUTF8 = "1"
$env:EMBEDDING_PROVIDER = "hashing"
$env:RERANKER_MODEL = ""
$env:RAG_MIN_RELEVANCE = ""
uv run --no-env-file --no-sync python scripts/verify_rag_e2e.py --backends qdrant --chunking structured --queries data/eval/rag_queries_independent_v2.toml --out outputs/rag_e2e/independent-hashing.md
```

`--backends`는 `qdrant,chroma,qdrant-server`, `--chunking`은 `legacy|structured`,
`-k` 기본값은 5다. `qdrant-server`는 별도 서버 설정이 필요하며 임시 컬렉션을 쓴다.
최종 보고서에서 색인·재실행 unchanged·버전 갱신과 정상 질문 순위, 근거 없음의 빈
결과 여부를 구분한다. 종료 코드 0은 실행 검사를 통과했다는 뜻이며 검색 품질의
업무 합격 기준이 아니다.

## 3. 임베딩·리랭킹·하한 비교

실제 Voyage 호출이 필요한 평가는 사용자가 자기 터미널에서 수행한다.
공급자·모델·차원·문서/질문·청킹·후보/K·필터를 고정하고 하한 없음과 후보값을
별도 출력 파일로 비교한다. 동일 질문으로 값을 고른 뒤 새 질문 검증셋에서는 값을
다시 고르지 않는다. 정상 Hit@K·MRR과 근거 없음 빈 결과를 함께 본다.

현재 `--reranker-batch-size`는 리랭크 API 요청당 후보 수이며 기본 100이다.
과거 BGE 실측의 로컬 추론 배치 2와 구분한다. `--no-embedding-cache`는 임베딩
재사용을 끄고, `--keep-embedding-model`은 캐시 사용 시 모델 참조 유지 옵션이다.
캐시가 켜진 시간은 순수 추론 속도가 아니므로 속도 비교는 부하·초기화 범위도 고정한다.

## 4. 새 질문과 실제 챗봇 응답

```powershell
uv run --no-env-file --no-sync python scripts/validate_rag_holdout.py
uv run --no-env-file --no-sync python scripts/check_rag_agent.py
```

기본은 실행 계획 확인이다. `--execute`를 붙이는 실측은 사용자가 직접 수행한다.
`validate_rag_holdout.py`는 같은 후보의 점수에서 하한 두 조건을 비교하며
`--minimum` 기본 0.02는 과거 실험 재현용 값이다. 현재 모델에 적합한 하한은 별도
검증해야 한다. 정상/근거 없음 두 범주의 질문이 모두 있어야 하며 o02는 대조 사례로
보류셋 집계에서 제외한다. 실행 결과의 `complete`와 질문별 결과를 함께 확인한다.

`check_rag_agent.py`는 평가용 SQLite·검색과 자유 대화 Agent를 연결한다.
직접 답하는 정답이 없는 질문은 정답 순위를 만들지 않고 실제 도구 호출·본문·출처·
근거 밖 주장을 대조한다. 검색하지 않고 거절한 경로와 실제 검색 후 거절을 구분한다.
HTTP 인증·대화 저장·화면 검증은 별도다. 실패한 질문을 자동으로 유료 재실행하지 않는다.

## 5. 공유 결과와 검증

새 원본은 `outputs/`에 보관하고 공유 문서에는 코드/모델·문서/질문 해시·청킹·
후보/K/하한·표본 분모·순위/빈 결과·최종 상태·사용량·검토 범위를 남긴다.
본문·인용 ID·개인정보·운영 자료가 있는 원본은 공유 전 검토한다.
새 청킹의 제목·문맥만 키워드에 일치하는 경우는 본문 정답 여부를 따로 확인한다.

자동 검증은 가짜 SDK·클라이언트와 `make check`를 사용한다. 실제 인증 유무 확인·
비밀 파일·SDK 프로필 열람·유료 LLM 실행은 AI가 대신하지 않는다.
IDE 열린 파일·선택 코드가 자동 문맥에 포함될 수 있으므로 실제 키는 편집기·예시
파일·채팅에 입력하지 않는다. 공급자 구성은 [EMBEDDING_API](EMBEDDING_API.md)를 따른다.

# 결정 기록

중요한 기술 결정을 한 줄 요약과 이유로 남긴다. 새 결정은 위에 추가한다.
번복할 때는 지우지 말고 새 항목에 "D-00 번복"이라고 적는다.

| # | 날짜 | 결정 | 이유 | 상태 |
|---|---|---|---|---|
| D-21 | 2026-10-27 | LLM 기본 모델 `qwen3:8b`(Q4_K_M), 호출은 Ollama 네이티브 `/api/chat`(`agent/ollama.py`). 구조화 출력은 `format`에 JSON 스키마를 넘겨 문법으로 제약한다. 스키마는 모든 칸을 required로 두고(`status`는 맨 뒤), 원인 후보의 `evidence_ids`는 필수·주어진 근거 ID enum으로 묶는다. "근거 부족이면 원인 후보 없음"은 스키마로 표현할 수 없어 생성 뒤 확인한다. 생각 단계(`OLLAMA_THINK`)는 기본으로 끔 | 네이티브 API는 `think`·`keep_alive` 등 Ollama 고유 옵션을 쓸 수 있다. Ollama(llama.cpp)는 required 칸을 먼저 쓰고 나머지는 건너뛸 수 있어, required가 일부면 판단(status)을 먼저 내리고 근거 ID 칸을 빠뜨렸다. enum으로 묶으면 없는 근거 인용이 원천 차단된다. 실측(`make llm-check`, 사례 4개, 프롬프트 v3): 생각 끔 = 스키마·계약 8/8, 상태 일치 6/8, 사례당 10~32초 · 생각 켬 = 3/4, 4/4, 18~47초(관련 없는 근거 사례에서 근거 부족이라 하고 원인 후보를 채워 생성 뒤 검사에 걸림). 관련 없는 근거를 OK로 보는 약점은 #8 검색(리랭커 점수 등)에서 먼저 거른다 | 확정 |
| D-20 | 2026-10-27 | D-18 번복: 문서 목록은 PostgreSQL `document` 테이블이 원본. 모든 문서를 한 테이블에 두고 `origin`(seed·upload·report)으로 구분한다. `data/catalog.toml`은 seed로 `make index`가 DB에 반영(추가·수정·빠진 seed 삭제)하고, 업로드 매니페스트 파일(`metadata.json`)은 없앤다. 스택은 SQLAlchemy 2.x + psycopg 3(동기) + Alembic, 핵심 칼럼 + JSONB(`extra`). 같은 doc_id의 completed는 부분 유니크 인덱스로 하나만, 개정판 교체는 트랜잭션 하나. `make index`·업로드 API는 DB가 필요(없으면 종료 코드 2·503). 개발용으로 `DATABASE_URL=sqlite:///storage/dev.db`도 같은 코드로 동작 | 파일 매니페스트는 트랜잭션·제약이 없어 우회 코드(깨진 파일 건너뛰기, 대체 순서)가 필요했다. 한 테이블이면 카탈로그·업로드·보고서(#29)를 같은 규칙으로 다룬다. SQLite 옵션은 Docker 없이도 개발을 막지 않기 위해서이고, CI는 PostgreSQL 서비스 컨테이너로 같은 테스트를 돌린다 | 확정 |
| D-19 | 2026-10-27 | 색인은 범용 `DocumentIndexer` 하나(`rag/indexer.py`)로 업로드 API와 `make index`가 같이 쓴다. 파일 형식은 파서 등록 구조(`rag/parsers.py`)로 고르고 지금은 PDF만. #56의 `ManualIndexer`(Chroma 직접 저장)는 이것으로 대체 | 색인 경로가 둘이면 저장소·청크 ID·메타데이터가 갈라져 검색·인용·변경 감지가 깨짐. 새 형식은 파서 클래스 하나로 추가 | 확정 |
| D-18 | 2026-10-27 | 문서 목록(레지스트리) = git의 `data/catalog.toml` + git 밖 `UPLOAD_DIR`(`storage/uploads`)의 완료된 업로드 매니페스트. 서버는 git 파일을 고치지 않고, 업로드 doc_id·내용이 카탈로그와 겹치면 409. 카탈로그는 엄격하게 검증하고 업로드는 항목별로(문제 항목은 건너뛰고 경고) 처리 | 목록은 하나로 유지하면서(모델 교체 시 업로드도 재색인) git 추적 파일을 서버가 바꾸는 문제를 피함. 2차 PostgreSQL `document` 테이블이 생기면 업로드 쪽 읽기를 DB로 교체 | D-20으로 번복 |
| D-17 | 2026-10-26 | 색인 대상 문서 목록은 `data/catalog.toml`(경로는 `data/` 기준). 문서 ID·버전·종류·상태를 명시하고 초안도 `status=draft`로 색인. 서로 다른 항목의 SHA-256이 같으면 오류 | 파일명 파싱은 규칙을 어기면 조용히 틀리고 초안/승인을 표현 못 함. #7 결정은 `data/knowledge/catalog.toml`이었으나 #41에서 `data/knowledge/`가 종류별 폴더(`manuals/` 등)로 바뀌어 위치만 옮김 | 확정 |
| D-16 | 2026-10-22 | 컬렉션은 `knowledge` 하나. 문서 종류는 메타데이터 `doc_type`(manual/rule/sop/report)으로 거름 | Agent는 매뉴얼·룰·SOP·보고서를 한 순위로 받아야 함. Qdrant 공식 문서도 종류별 컬렉션 대신 payload 분할을 권장 | 확정 |
| D-15 | 2026-10-22 | 청크 ID `{doc_id}:{doc_version}:{seq:04d}`(= `Evidence.evidence_id`). Qdrant point ID는 `uuid5(chunk_id)` | 읽기 쉽고 항상 같은 값. Qdrant는 UUID·정수 ID만 받음(`BTT-MANUAL:2.0:0001`은 거부됨) | 확정 |
| D-14 | 2026-10-22 | Qdrant 기본은 로컬 모드(`QDRANT_PATH`), `QDRANT_URL`이 있으면 서버 접속. compose에는 `profiles: ["qdrant"]` 선택형 서비스 | 1차는 Docker 없이 개발하고 통합·6차는 설정만 바꿈. 로컬 모드는 파이썬 재구현이라 서버 모드로도 주기적으로 테스트 | 확정 |
| D-13 | 2026-10-22 | sparse 표현은 Kiwi 형태소 BM25. 코드는 정규식으로 먼저 뽑고 도메인 용어는 사용자 사전에 넣음 | `Qdrant/bm25`는 한국어를 어절 단위로만 자름(`이송시간이` ≠ `이송시간`). 임베딩 모델과 독립 | 확정 |
| D-12 | 2026-10-22 | 하이브리드 검색(`hybrid_query`)은 저장 계층에서 끝냄. Qdrant는 네이티브 sparse+RRF, Chroma는 같은 토크나이저로 파이썬 BM25+RRF(k=60) | #8은 메서드 한 번만 부르고 리랭킹·Evidence에 집중. Chroma 하이브리드는 Cloud 전용이라 로컬에서 쓸 수 없음 | 확정 |
| D-11 | 2026-10-22 | 갱신은 문서 단위 교체. 원본 SHA-256으로 변경 감지. 임베딩 먼저 계산 → 새 청크 쓰기 → 남은 옛 청크 삭제. 청크마다 저장 당시 전체 수(`chunk_total`)를 기록 | 수백 청크 규모라 단순·멱등한 방식이 나음. 쓰기 전 실패는 기존 색인이 그대로 남고, 쓰는 도중 끊기면 `documents()`가 `complete=False`로 알려 다음 동기화가 다시 색인 | 확정 |
| D-10 | 2026-10-22 | 임베딩은 저장소가 주입받은 `Embedder`로 색인·검색 모두 계산. 모델 이름을 컬렉션에 기록하고 다른 모델로 열면 거부 | 색인 모델과 검색 모델이 어긋나도 에러 없이 품질만 떨어지는 버그를 구조적으로 막음. 모델 선정·임베더 구현은 #6 | 확정 |
| D-09 | 2026-10-22 | 네이티브 클라이언트(qdrant-client, chromadb) 위에 rag 내부 Protocol(`rag/store.py`)을 둠. LangChain 벡터스토어 래퍼는 쓰지 않음 | 래퍼는 재실행 시 중복 적재, ID로만 삭제, 랜덤 `uuid4` ID, DB마다 다른 기본 거리(Chroma l2, Qdrant Cosine), 변경 감지 없음 | 확정 |
| D-08 | 2026-10-22 | 벡터 DB는 `VectorStore` Protocol 하나에 Qdrant(기본)·Chroma 두 구현. 설정 `VECTOR_STORE`로 고름 | 같은 계약 테스트를 두 구현에 돌려 교체를 보증하고 성능 비교. Qdrant는 온프레미스에서 하이브리드를 DB 안에서 처리 | 확정 |
| D-07 | 2026-10-20 | 스킬 원본은 `.agents/skills`, Claude Code용 `.claude/skills`는 `scripts/sync_skills.py`로 만든 복사본을 커밋 | Codex와 Claude Code가 찾는 위치가 다름. 심볼릭 링크는 Windows에서 깨질 수 있음. CI·pre-commit이 두 폴더가 같은지 검사 | 확정 |
| D-06 | 2026-10-20 | 문서만 바뀐 PR은 Lint·Test를 건너뜀. 잡 단위 `if`로 건너뛰고 트리거 `paths` 필터는 쓰지 않음. Secret scan·Skills sync는 항상 실행 | Actions 시간 절약(private 레포는 월 사용량 한도). 트리거 필터는 필수 검사 지정 시 PR이 '대기 중'으로 멈춤. 판단이 불확실하면 실행하고, 건너뛸 경로만 목록으로 둠 | 확정 |
| D-05 | 2026-10-20 | CI 액션은 커밋 SHA로 고정. `actions/checkout`은 v6.1.0 유지 | 태그 바꿔치기 공급망 공격 방지. v7은 fork PR 체크아웃 동작이 바뀌는 큰 변경이라 보류함 | 확정 |
| D-04 | 2026-10-20 | 운영용 기능(배포 자동화·백업·모니터링·dependabot)은 지금 넣지 않음 | 11월 첫째~둘째 주 완성이 우선. 6차(온프레미스 배포) 때 필요한 만큼만 추가 | 확정 |
| D-03 | 2026-10-20 | 앱은 컨테이너 없이 `uv run`으로 실행, PostgreSQL·Ollama만 docker compose | 개발 중 재시작이 빠르고, macOS에서 컨테이너 Ollama는 GPU를 못 씀 | 확정 |
| D-02 | 2026-10-20 | 모듈 간 데이터는 `contracts/`의 pydantic 모델로만 주고받고, 다른 모듈은 `interface.py`만 import | 1차 세 파트가 병렬로 개발해도 연결 지점이 어긋나지 않게. 나중에 서비스로 분리할 때 모델이 그대로 API 스키마가 됨 | 확정 |
| D-01 | 2026-10-20 | 단일 uv 프로젝트 + 모듈별 하위 패키지 (`src/weeing_weeing/<모듈>`) | `uv sync` 한 번으로 6명 환경이 같아짐. 서비스별 레포·pyproject는 3주 프로젝트에 관리 부담이 큼 | 확정 |

## 나중에 검토할 것

- **CI 설치 시간**: `sentence-transformers`가 Linux에서 CUDA용 torch(수 GB)를 받는다. Test 잡이 느려지면 torch를 직접 의존성으로 두고 Linux에서 CPU 전용 인덱스를 쓰도록 바꾼다(uv PyTorch 가이드 참고)
- **`uv_build` 버전 범위**: 설치된 uv(0.13.x)가 `uv_build<0.13`보다 새로워 경고가 난다. 동작에는 문제없고, 팀원 uv 버전이 맞춰지면 범위를 올린다

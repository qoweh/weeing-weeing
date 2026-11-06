# 위잉위잉 — 설비 이상 대응 AI Agent

> 한화 K-뉴딜 아카데미 캡스톤 · 제조 설비 이상정보 기반 원인·대응정보 생성 Agent

가상의 **배터리 트레이 자동 이송 공정**(BLDC 모터 벨트 컨베이어 1기, 센서 7종)을 대상으로, 센서 이상을 감지하면 AI Agent가 매뉴얼·SOP·정비 이력을 근거로 원인 후보와 점검 순서를 제안합니다. 사람이 점검·조치한 결과는 보고서와 결재를 거쳐 다음 진단의 지식이 됩니다.

- **근거 기반**: 모든 제안에 센서값·룰 코드·문서 인용을 붙이고, 근거가 없으면 멈춘다
- **사람 우선**: AI는 제안까지. 원인 확정·정지 해제·재가동은 사람이 한다
- **에이전트**: 상용 LLM(Claude)이 검색 도구로 근거를 모은다. 기본 단일 분석과 LangGraph 기반 멀티 분석·선택 검증을 제공한다([docs/AGENT.md](docs/AGENT.md), [단계별 근거 확인](docs/MULTI_AGENT_ANALYSIS.md))

## 빠른 시작

```bash
uv sync --locked --no-install-project   # Python 3.12 + 의존성 설치 (= make setup)
cp .env.example .env
uv run --no-sync pytest                 # 테스트 (= make test)
make api                                # FastAPI 개발 서버
```

챗봇 단일 질문 실행은 `make chat ARGS='"P03 점검 절차는?" --asset-id BLDC-001'`을 사용합니다.
DB·색인·Claude API 키가 필요하고 실제 API 비용이 발생합니다. 키를 파일에 남기지 않고
직접 대화하려면 `make chat-private ARGS='--asset-id BLDC-001'`을 실행해 터미널에서 숨김
입력하세요. 이 명령은 .env를 자동으로 로드하지 않습니다. [CHATBOT](docs/CHATBOT.md)을 참고하세요.
로그인한 사용자용 HTTP API는 `make api` 실행 후 `/docs`에서 확인할 수 있습니다.
FAQ 버튼 선택·대화 저장·중복 요청·본인 조회 흐름은 [CHAT_API](docs/CHAT_API.md)에 정리했습니다.
챗봇 LLM 왕복·재작성 개선과 실제 지연 비교 명령은
[CHAT_ROUNDTRIP_PERFORMANCE](docs/CHAT_ROUNDTRIP_PERFORMANCE.md)를 참고하세요.

자세한 설치(uv·Docker·Claude API 키)와 문제 해결: [docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md)

## 팀 공지

팀원이 해야 할 일(환경 설정 변경 등)은 [`announcement` 라벨 이슈](https://github.com/qoweh/weeing-weeing/issues?q=is%3Aissue%20is%3Aopen%20label%3Aannouncement)로 알리고 이슈 목록 맨 위에 고정합니다. 이슈의 체크리스트에서 본인 줄을 체크하고, 막히면 그 이슈에 댓글을 남깁니다.

- 지금 진행 중: **LLM 사용량 기록(Langfuse) 도입**: `.env`에 `LLM_USER`와 개별로 받은 Langfuse 키를 넣는다([공지 #115](https://github.com/qoweh/weeing-weeing/issues/115), [USAGE_TRACKING](docs/USAGE_TRACKING.md))

## 구조

```
src/weeing_weeing/
  contracts/   모듈 간 데이터 모양 (Telemetry, Incident, AnalysisResult, 보고서)
  ingest/      CSV·시뮬레이터 수집, 검증, 재생           ← 1차
  detector/    룰 판정, Incident 생성 (Main Engine)     ← 1차
  rag/         문서 색인, 근거 검색                      ← 1차
  agent/       Claude 에이전트: 근거 검색·원인 추론·대응 제안 ← 1차
  api/  db/    FastAPI, PostgreSQL                       ← 2차
  plc/         Virtual PLC 상태·보호 제어                ← 3차
hmi/           Streamlit 화면                            ← 5차
simulator/     Unreal 연동                               ← 4차
data/          원본 데이터, 룰 정의서·매뉴얼·SOP
tests/  scripts/  docs/
ops/           로컬·운영 서버 명령 모음 (local.sh, aws.sh)
```

각 모듈의 책임은 `__init__.py` 첫 주석에, 바깥에 내놓는 함수 모양은 `interface.py`에 있습니다. 다른 모듈은 `interface.py`와 `contracts`만 import합니다.

## 문서

| 문서 | 내용 |
|---|---|
| [ARCHITECTURE](docs/ARCHITECTURE.md) | 전체 흐름, 모듈 표, 의존 규칙 **← 먼저 읽기** |
| [CONTRACTS](docs/CONTRACTS.md) | 데이터 계약 요약, 근거 자료, 미결 사항 |
| [JSON_INPUT](docs/JSON_INPUT.md) | 공통 JSON 입력 API, CSV 재생과 0.5초 주기 제한 |
| [WEBSOCKET_TELEMETRY](docs/WEBSOCKET_TELEMETRY.md) | Unreal WebSocket 수신, CSV 테스트 송신기와 터미널 실행 방법 |
| [AWS_TELEMETRY](docs/AWS_TELEMETRY.md) | AWS 송신 인증, 최신 센서 조회 API, 개인용 터미널 모니터 |
| [AWS_FIRST_SETUP](docs/AWS_FIRST_SETUP.md) | AWS 계정·EC2를 처음 만들고 프로젝트 배포 및 Unreal 센서를 연결하는 순서 |
| [AUTO_ANALYSIS](docs/AUTO_ANALYSIS.md) | Error 자동 분석·저장·조회·무과금 터미널 시연 (#104) |
| [SENSOR_WINDOWS](docs/SENSOR_WINDOWS.md) | 사건 센서 구간 조회·수치 검증·무료 터미널 시연 (#105) |
| [LOCAL_SETUP](docs/LOCAL_SETUP.md) | 개발 환경 설치, 실행, 문제 해결 |
| [DEPLOY](docs/DEPLOY.md) | 운영 서버(EC2) 배포: 구조, Secrets, 첫 배포, 롤백, 백업 (#117) |
| [AWS_ACCESS](docs/AWS_ACCESS.md) | 운영 서버 접속: 주소, SSH 키 등록, DB·Qdrant 터널, Langfuse |
| [ops/README](ops/README.md) | 자주 쓰는 명령 모음: 로컬 실행(`ops/local.sh`)·운영 서버 상태·로그·볼륨(`ops/aws.sh`) |
| [repo-stats 브랜치](https://github.com/qoweh/weeing-weeing/tree/repo-stats) | 커밋·PR·이슈 활동 손그림 차트(발표용). Actions → **Repo stats** → Run workflow로 갱신 |
| [CHANGE_WORKFLOW](docs/CHANGE_WORKFLOW.md) | 이슈·브랜치·커밋·PR·머지 규칙 |
| [DECISIONS](docs/DECISIONS.md) | 기술 결정 기록 |
| [AGENT](docs/AGENT.md) | 에이전트 구조(싱글), 도구·검사, 멀티 에이전트·메모리 확장 계획 |
| [MULTI_AGENT_ANALYSIS](docs/MULTI_AGENT_ANALYSIS.md) | LangGraph 사건 분석·선택 검증·HMI 단계별 근거 확인 |
| [LLM_EVALUATION](docs/LLM_EVALUATION.md) | Claude 모델·effort 비교, 32사례 평가셋과 센서·검색 결합 검증 (#106) |
| [USAGE_TRACKING](docs/USAGE_TRACKING.md) | LLM 사용량 기록(Langfuse): 무엇을 남기는지, 팀원 설정 |
| [DIRECTION_CHANGES](docs/DIRECTION_CHANGES.md) | 방향 전환 때 없앤 것·바꾼 것 기록(로컬 LLM 폐지 등) |
| [RAG_RETRIEVAL](docs/RAG_RETRIEVAL.md) | 폴더별 역할, 검색·리랭킹 구조, 공개 연결 방법과 평가 |
| [EMBEDDING_API](docs/EMBEDDING_API.md) | 임베딩·리랭크 공급자 선정(해시 기본·Voyage), 후보 비교와 가격 |
| [COMMERCIAL_MODELS](docs/COMMERCIAL_MODELS.md) | 로컬 모델 → 상용 API 전환 점검: 안 해도 되는 것, 새로 챙길 것, 다시 정할 값 |
| [AI_DATA_SECURITY](docs/AI_DATA_SECURITY.md) | 외부 AI로 나가는 데이터, 기업의 일반적 관리 방식, 도입 전 점검표 |
| [REPORTS](docs/REPORTS.md) | 보고서 로그인·임시 저장·내 보고서·결재·개정판과 #29 연결 지점 |
| [data/README](data/README.md) | 데이터·문서 출처 |

에이전트(Claude Code·Codex 등) 작업 규칙은 [CLAUDE.md](CLAUDE.md) / [AGENTS.md](AGENTS.md)에, 팀 공용 스킬(환경 설치·PR 전 점검·PR 생성)은 [.agents/skills](.agents/skills/README.md)에 있습니다.

## 팀

임보영(팀장) · 길용현 · 김민우 · 안규현 · 이승민 · 홍동인

## 미래 Error 예측 실험

센서 최근 30초로 미래 60초 내 첫 Error를 예측하는 독립 RandomForest 실험은
[ML 사용 설명서](docs/ML_FUTURE_ERROR.md)와 [평가 결과](docs/ML_FUTURE_ERROR_RESULTS.md)를 따른다.
선택 의존성은 `uv sync --locked --no-install-project --group ml`로 설치한다.

실시간 관찰 연결과 로그인 후 결과 확인은 [ML_LIVE](docs/ML_LIVE.md)를 참고하세요.

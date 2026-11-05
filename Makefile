# 자주 쓰는 명령 모음. make가 없는 환경(Windows)은 docs/LOCAL_SETUP.md의 원래 명령을 쓴다.
# 사용법: make help

ifeq ($(OS),Windows_NT)
SHELL := cmd.exe
endif

# Windows·Linux 공통: make의 하위 Python 프로세스에 UTF-8을 자동 적용한다.
export PYTHONUTF8 := 1
export PYTHONIOENCODING := utf-8
# 인라인 VAR=value 문법 대신 make가 전달하므로 Windows cmd에서도 실행된다.
export PYTHONPATH := $(CURDIR)/src
# ARGS를 명령 문자열에 붙이지 않고 Python 실행기가 유니코드로 읽게 한다.
export ARGS
# Windows용 make의 ANSI 인자 변환을 피할 때는 UTF-8 파일의 내용을 Python이 읽는다.
RUN_MAKE_OPTIONS = $(if $(ARGS_FILE),--args-file "$(ARGS_FILE)",)

ENV_FILE := $(if $(wildcard .env),--env-file .env,)
# 팀 규칙: 프로젝트 자체는 설치하지 않는다(uv sync --no-install-project).
# 그냥 uv run을 쓰면 실행 전에 프로젝트를 설치하므로 --no-sync로 실행한다.
# 의존성이 바뀌면(pull 후 등) make setup을 다시 실행한다.
RUN := uv run --no-sync

.PHONY: help setup lint fmt test check env-check skills db-up db-migrate qdrant-up down api index-reports seed-docs seed-users rag-e2e llm-check llm-eval analyze chat

help: ## 명령 목록
	@$(RUN) python scripts/make_help.py

setup: ## 의존성 설치 (uv.lock 기준)
	uv sync --locked --no-install-project

lint: ## 린트·포맷 검사 (CI와 같음)
	$(RUN) ruff check .
	$(RUN) ruff format --check .

fmt: ## 린트 자동 수정 + 포맷
	$(RUN) ruff check --fix .
	$(RUN) ruff format .

test: ## 테스트 (CPU 수만큼 병렬, 한 줄씩 보려면 uv run --no-sync pytest)
	$(RUN) pytest -n logical

check: lint test ## PR 올리기 전 전체 검사
	$(RUN) python scripts/sync_skills.py --check

env-check: ## 내 .env를 .env.example과 비교 (값은 출력 안 함, ARGS="--file 경로")
	$(RUN) python scripts/run_make.py $(RUN_MAKE_OPTIONS) python scripts/check_env.py

skills: ## 스킬 원본(.agents/skills)을 Claude Code용 사본(.claude/skills)으로 복사
	$(RUN) python scripts/sync_skills.py

db-up: ## PostgreSQL 기동
	docker compose up -d postgres

db-migrate: ## DB 스키마를 최신으로 (API도 시작할 때 자동으로 올린다)
	$(RUN) python scripts/run_make.py $(RUN_MAKE_OPTIONS) $(ENV_FILE) alembic upgrade head

qdrant-up: ## Qdrant 서버 기동 (서버 모드, .env에 QDRANT_URL=http://localhost:6333)
	docker compose --profile qdrant up -d qdrant

down: ## 보조 서비스 정지
	docker compose --profile qdrant down

index-reports: ## 승인 보고서 검색 등록 대기 처리 (실패 재시도: ARGS=--retry-failed, 컬렉션 바꾼 뒤 전부: ARGS=--all)
	$(RUN) python scripts/run_make.py $(RUN_MAKE_OPTIONS) $(ENV_FILE) python scripts/index_reports.py

seed-docs: ## 팀 문서(data/seed/documents_v1.toml) 미리 등록·임베딩. 이미 임베딩된 같은 파일은 건너뜀 (ARGS=--replace)
	$(RUN) python scripts/run_make.py $(RUN_MAKE_OPTIONS) $(ENV_FILE) python scripts/seed_documents.py

seed-users: ## 시연용 계정 만들기 (DB 필요, 있는 사번은 건너뜀, ARGS=--ask-password)
	$(RUN) python scripts/run_make.py $(RUN_MAKE_OPTIONS) $(ENV_FILE) python scripts/seed_users.py

rag-e2e: ## RAG 실제 문서 E2E 검증·백엔드 비교 (#28, ARGS="--backends qdrant,chroma,qdrant-server")
	$(RUN) python scripts/run_make.py $(RUN_MAKE_OPTIONS) $(ENV_FILE) python scripts/verify_rag_e2e.py

llm-check: ## LLM(Claude) 구조화 출력 점검 (ANTHROPIC_API_KEY 필요, ARGS="--model claude-sonnet-5-5 --repeat 3")
	$(RUN) python scripts/run_make.py $(RUN_MAKE_OPTIONS) $(ENV_FILE) python scripts/check_llm.py

llm-eval: ## 모델·effort 비교 계획 (#106). ARGS="--execute"는 유료 실행
	$(RUN) python scripts/run_make.py $(RUN_MAKE_OPTIONS) $(ENV_FILE) python scripts/compare_llm.py

analyze: ## 사건 하나를 에이전트로 분석 (ANTHROPIC_API_KEY·색인 필요, ARGS="--incident 경로.json")
	$(RUN) python scripts/run_make.py $(RUN_MAKE_OPTIONS) $(ENV_FILE) python scripts/analyze_incident.py

api: ## FastAPI 개발 서버 (http://localhost:8000/docs)
	$(RUN) python scripts/run_make.py $(RUN_MAKE_OPTIONS) $(ENV_FILE) uvicorn --app-dir src weeing_weeing.api.app:app --reload

chat: ## 챗봇 질문 실행 (Claude API 비용 발생, DB·색인 필요, ARGS='"P03 점검 절차는?" --asset-id BLDC-001')
	$(RUN) python scripts/run_make.py $(RUN_MAKE_OPTIONS) $(ENV_FILE) python scripts/chat.py

.PHONY: chat-check
chat-check: ## Claude 없이 FAQ·검색·DB 조회 확인 (ARGS='faq' 또는 'search "P03 점검"' 또는 'history')
	$(RUN) python scripts/run_make.py $(RUN_MAKE_OPTIONS) $(ENV_FILE) python scripts/check_chat.py

.PHONY: langfuse-smoke
langfuse-smoke: ## Claude·Voyage 없이 챗봇 1건을 재생해 Langfuse 기록 확인 (비용 0, ARGS='"질문" --session 대화ID')
	$(RUN) python scripts/run_make.py $(RUN_MAKE_OPTIONS) $(ENV_FILE) python scripts/langfuse_smoke.py

.PHONY: chat-baseline
chat-baseline: ## 챗봇 지연 기준선(#215). 기본은 계획만, ARGS=--replay(비용 0) / --execute(유료, 10문항)
	$(RUN) python scripts/run_make.py $(RUN_MAKE_OPTIONS) $(ENV_FILE) python scripts/chat_baseline.py

.PHONY: chat-private
chat-private: ## .env 자동 로딩 없이 Claude 키를 숨김 입력해 직접 대화 (API 비용 발생)
	$(RUN) python scripts/run_make.py $(RUN_MAKE_OPTIONS) --no-env-file python scripts/chat.py --interactive --ask-key

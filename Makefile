# 자주 쓰는 명령 모음. make가 없는 환경(Windows)은 docs/LOCAL_SETUP.md의 원래 명령을 쓴다.
# 사용법: make help

ENV_FILE := $(if $(wildcard .env),--env-file .env,)
# 팀 규칙: 프로젝트 자체는 설치하지 않는다(uv sync --no-install-project).
# 그냥 uv run을 쓰면 실행 전에 프로젝트를 설치하므로 --no-sync로 실행한다.
# 의존성이 바뀌면(pull 후 등) make setup을 다시 실행한다.
RUN := uv run --no-sync

.PHONY: help setup lint fmt test check skills db-up db-migrate ollama-up qdrant-up down api models index index-reports seed-users rag-e2e llm-check

help: ## 명령 목록
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

setup: ## 의존성 설치 (uv.lock 기준)
	uv sync --locked --no-install-project

lint: ## 린트·포맷 검사 (CI와 같음)
	$(RUN) ruff check .
	$(RUN) ruff format --check .

fmt: ## 린트 자동 수정 + 포맷
	$(RUN) ruff check --fix .
	$(RUN) ruff format .

test: ## 테스트
	$(RUN) pytest

check: lint test ## PR 올리기 전 전체 검사
	python3 scripts/sync_skills.py --check

skills: ## 스킬 원본(.agents/skills)을 Claude Code용 사본(.claude/skills)으로 복사
	python3 scripts/sync_skills.py

db-up: ## PostgreSQL 기동
	docker compose up -d postgres

db-migrate: ## DB 스키마를 최신으로 (make index·API도 시작할 때 자동으로 올린다)
	PYTHONPATH=src $(RUN) $(ENV_FILE) alembic upgrade head

ollama-up: ## Ollama 컨테이너 기동 (Linux용, Mac은 Ollama 앱 권장)
	docker compose --profile ollama up -d ollama

qdrant-up: ## Qdrant 서버 기동 (서버 모드, .env에 QDRANT_URL=http://localhost:6333)
	docker compose --profile qdrant up -d qdrant

down: ## 보조 서비스 정지
	docker compose --profile ollama --profile qdrant down

models: ## 임베딩·리랭커·LLM 모델 미리 받기 (새 PC에서 한 번, 약 10GB, ARGS=--skip-ollama)
	PYTHONPATH=src $(RUN) $(ENV_FILE) python scripts/download_models.py $(ARGS)

index: ## RAG 색인: catalog.toml을 DB에 반영 → DB 문서 목록과 벡터 DB 동기화 (DB 필요, ARGS=--dry-run|--force|--recreate)
	PYTHONPATH=src $(RUN) $(ENV_FILE) python scripts/build_index.py $(ARGS)

index-reports: ## 승인 보고서 검색 등록 대기 처리 (실패 재시도: ARGS=--retry-failed)
	PYTHONPATH=src $(RUN) $(ENV_FILE) python scripts/index_reports.py $(ARGS)

seed-users: ## 시연용 계정 만들기 (DB 필요, 있는 사번은 건너뜀, ARGS=--ask-password)
	PYTHONPATH=src $(RUN) $(ENV_FILE) python scripts/seed_users.py $(ARGS)

rag-e2e: ## RAG 실제 문서 E2E 검증·백엔드 비교 (#28, ARGS="--backends qdrant,chroma,qdrant-server")
	PYTHONPATH=src $(RUN) $(ENV_FILE) python scripts/verify_rag_e2e.py $(ARGS)

llm-check: ## LLM 로컬 실행·구조화 출력 점검 (#10, ARGS="--model qwen3:8b --repeat 3")
	PYTHONPATH=src $(RUN) $(ENV_FILE) python scripts/check_llm.py $(ARGS)

api: ## FastAPI 개발 서버 (http://localhost:8000/docs)
	$(RUN) $(ENV_FILE) uvicorn --app-dir src weeing_weeing.api.app:app --reload

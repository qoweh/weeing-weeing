#!/usr/bin/env bash
# 내 PC(로컬 개발) 명령 모음. 사용법: ops/local.sh help
#
# - 저장소 루트 어디서 불러도 루트로 옮겨서 실행한다.
# - Python 쪽은 Makefile 대상을 그대로 부른다(make help와 같은 동작). 여기서는 순서와 프론트·HMI·Docker를 묶는다.
# - Windows는 Git Bash·WSL에서 쓰거나 docs/LOCAL_SETUP.md의 원래 명령을 쓴다.
set -euo pipefail

cd "$(dirname "$0")/.."

usage() {
  cat <<'EOF'
사용법: ops/local.sh <명령> [인자]

설치·점검
  setup                  Python 의존성(uv.lock)과 프론트·HMI npm 패키지 설치
  check                  PR 전 전체 검사 (= make check: ruff·format·pytest)
  env-check              내 .env를 .env.example과 비교 (값은 출력 안 함)

보조 서비스 (Docker)
  db                     PostgreSQL 기동 후 스키마 최신화 (make db-up + make db-migrate)
  qdrant                 Qdrant 서버 기동 (.env에 QDRANT_URL=http://localhost:6333일 때만 필요)
  ps                     로컬 컨테이너 상태
  logs [서비스]           로컬 컨테이너 로그 따라가기 (postgres|qdrant, 기본 postgres)
  volumes                로컬 볼륨 이름·경로·크기
  down                   보조 서비스 정지 (데이터 볼륨은 유지)

실행 (각각 터미널 하나씩 켜 둔다)
  api                    백엔드 FastAPI  http://localhost:8000/docs  (= make api)
  front                  프론트(Next.js) http://localhost:3100       (API_ORIGIN 기본 http://127.0.0.1:8000)
  hmi                    HMI(Vite)       http://localhost:5173       (/api를 8000으로 프록시)
  seed                   시연용 계정 만들기 (= make seed-users)
  urls                   로컬 주소 모음

처음 한 번 순서: setup → cp .env.example .env(값 채우기) → db → seed → api / front / hmi
EOF
}

need() { command -v "$1" >/dev/null 2>&1 || { echo "$1이 필요하다 (docs/LOCAL_SETUP.md)"; exit 1; }; }

cmd="${1:-help}"
shift || true

case "$cmd" in
  setup)
    need uv; need npm
    uv sync --locked --no-install-project
    (cd frontend && npm ci)
    (cd hmi/web && npm ci) ;;
  check)
    make check ;;
  env-check)
    make env-check ;;
  db)
    need docker
    make db-up
    make db-migrate ;;
  qdrant)
    need docker
    make qdrant-up ;;
  ps)
    docker compose --profile qdrant ps ;;
  logs)
    docker compose --profile qdrant logs -f --tail 100 "${1:-postgres}" ;;
  volumes)
    project="$(basename "$PWD")"
    for v in $(docker volume ls -q --filter "label=com.docker.compose.project=$project"); do
      printf '%-40s %s\n' "$v" "$(docker volume inspect -f '{{.Mountpoint}}' "$v")"
    done
    echo
    echo "[크기] docker system df -v 의 볼륨 부분 (Docker Desktop은 경로가 VM 안이라 Finder에서 보이지 않는다)"
    docker system df -v | awk -v pre="${project}_" '/^VOLUME NAME/{p=1; print; next} p&&/^$/{exit} p&&index($1,pre)==1' ;;
  down)
    make down ;;
  api)
    make api ;;
  front)
    [ -d frontend/node_modules ] || (cd frontend && npm ci)
    cd frontend && exec npm run dev ;;
  hmi)
    [ -d hmi/web/node_modules ] || (cd hmi/web && npm ci)
    cd hmi/web && exec npm run dev ;;
  seed)
    make seed-users ;;
  urls)
    cat <<'EOF'
API 문서    http://localhost:8000/docs   (헬스: http://localhost:8000/health)
프론트      http://localhost:3100
HMI        http://localhost:5173
PostgreSQL localhost:5432
Qdrant     http://localhost:6333/dashboard (qdrant 기동 시)
EOF
    ;;
  help|-h|--help)
    usage ;;
  *)
    echo "모르는 명령: $cmd"; echo; usage; exit 2 ;;
esac

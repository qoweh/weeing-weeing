#!/usr/bin/env bash
# 운영 서버(AWS EC2) 명령 모음 — macOS·Linux·Git Bash용. 사용법: ops/aws.sh help
# Windows PowerShell은 ops/aws.ps1. 서버 안에서는 ops/server.sh를 직접 쓴다.
#
# 접속·터널은 여기서 처리하고, 나머지 명령은 ops/server.sh를 SSH로 보내 서버에서 실행한다.
# 서버 별칭은 기본 ww-team(docs/AWS_ACCESS.md 2절). 바꾸기: WW_HOST=별칭 ops/aws.sh ...
set -euo pipefail

HOST="${WW_HOST:-ww-team}"
HERE="$(cd "$(dirname "$0")" && pwd)"

usage() {
  cat <<'EOF'
사용법: ops/aws.sh <명령> [인자]        (서버 별칭 바꾸기: WW_HOST=별칭 ops/aws.sh ...)

내 PC에서
  ssh                    서버 셸 접속
  tunnel                 DB·Qdrant SSH 터널 (localhost:15432 → 5432, localhost:16333 → 6333). Ctrl+C로 종료
  urls                   웹·HMI·API 문서·Langfuse 주소
  deploys                최근 배포 워크플로 실행 기록 (gh 필요)

EOF
  bash "$HERE/server.sh" help
}

# server.sh를 base64로 보내 서버 임시 파일로 실행한다. 인자는 영문·숫자·-·_만 받는다.
on_server() {
  local arg b64
  for arg in "$@"; do
    [[ "$arg" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "잘못된 인자: $arg" >&2; exit 2; }
  done
  b64="$(base64 < "$HERE/server.sh" | tr -d '\n')"
  exec ssh -t "$HOST" "f=\$(mktemp) && echo $b64 | base64 -d > \$f && bash \$f $*; rc=\$?; rm -f \$f; exit \$rc"
}

cmd="${1:-help}"

case "$cmd" in
  ssh)
    exec ssh "$HOST" ;;
  tunnel)
    echo "터널 열림: PostgreSQL localhost:15432, Qdrant http://localhost:16333/dashboard (Ctrl+C로 종료)"
    exec ssh -N -L 15432:localhost:5432 -L 16333:localhost:6333 "$HOST" ;;
  urls)
    cat <<'EOF'
웹(프론트)  https://<EC2_IP>/
HMI        https://<EC2_IP>/hmi/
API 문서    https://<EC2_IP>/api/docs
Langfuse   https://langfuse.<EC2_IP>.sslip.io
DB·Qdrant  ops/aws.sh tunnel 후 localhost:15432 / http://localhost:16333/dashboard
EOF
    ;;
  deploys)
    exec gh run list --workflow deploy.yml --limit 10 ;;
  help|-h|--help)
    usage ;;
  *)
    on_server "$@" ;;
esac

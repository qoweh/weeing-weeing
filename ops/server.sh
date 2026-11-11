#!/usr/bin/env bash
# 운영 서버(EC2) 안에서 도는 명령. 사용법: bash server.sh help
#
# 내 PC에서는 ops/aws.sh(macOS·Linux) 또는 ops/aws.ps1(Windows)이 이 파일을 SSH로 보내 실행한다.
# 서버에 직접 올려 써도 된다: scp ops/server.sh ww-team:~/ 후 bash ~/server.sh ps
# .env 값은 출력하지 않는다. rag만 비밀이 아닌 RAG 설정 값과 키 유무를 보여 준다.
set -euo pipefail

APP_DIR="$HOME/weeing-weeing"
LANGFUSE_DIR="$HOME/langfuse"
PROJECT=weeing-weeing

usage() {
  cat <<'EOF'
서버 명령 (ops/aws.sh <명령> 또는 서버에서 bash server.sh <명령>)

상태·로그
  ps                     앱 컨테이너 상태 (api는 healthy여야 정상)
  health                 /api/health 호출
  logs [서비스] [줄수]    로그 따라가기. 서비스: api|frontend|web|postgres|qdrant (기본 api, 100줄)
  logs-all [줄수]         모든 앱 서비스 로그 따라가기
  images                 지금 떠 있는 이미지 태그 (배포 버전 확인)

볼륨·디스크
  volumes                앱 볼륨 이름·서버 경로(Mountpoint)·크기
  disk                   서버 디스크 사용량과 Docker 전체 사용량

데이터
  rag                    RAG 설정(비밀 아닌 값만), Qdrant 컬렉션·포인트 수, DB 문서·보고서 색인 상태 개수
  db                     운영 DB psql 접속 (컨테이너 안 계정 사용). 조회 위주
  env-keys               서버 .env에 있는 변수 이름만 (값은 출력 안 함)
  env-check              서버 .env를 .env.example과 비교 (비밀 값은 설정됨/비어 있음만)
  env-sync               .env에 키가 아예 없는 .env.example 줄만 템플릿과 같은 위치에 추가 (배포 때 자동 실행)
  seed-docs [--replace]  팀 문서(매뉴얼·룰·규정) 미리 등록·임베딩. 이미 임베딩된 같은 파일은 건너뜀
  reindex-reports        승인 보고서를 지금 컬렉션에 전부 다시 등록 (컬렉션을 바꾼 뒤)
  retry-reports          실패한 승인 보고서 색인만 다시 시도

운영
  restart <서비스>        한 서비스 재시작 (.env는 다시 읽지 않는다)
  up                     .env를 다시 읽어 바뀐 서비스만 다시 띄움 (docker compose up -d)
  pull-up                최신 태그 이미지를 받고 다시 띄움 (보통은 배포 워크플로가 한다)
  langfuse-ps            Langfuse 컨테이너 상태
  langfuse-logs [줄수]    Langfuse 웹 로그
EOF
}

# 서비스 이름·줄 수만 받는다(셸 명령에 그대로 들어가므로).
token() {
  [[ "$1" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "잘못된 인자: $1" >&2; exit 2; }
  printf '%s' "$1"
}

cmd="${1:-help}"
shift || true

case "$cmd" in
  help|-h|--help)
    usage; exit 0 ;;
  langfuse-ps)
    cd "$LANGFUSE_DIR" && exec docker compose ps ;;
  langfuse-logs)
    cd "$LANGFUSE_DIR" && exec docker compose logs -f --tail "$(token "${1:-100}")" langfuse-web ;;
  disk)
    df -h /; echo; exec docker system df ;;
esac

cd "$APP_DIR"

case "$cmd" in
  ps)
    docker compose ps ;;
  health)
    curl -fsS localhost/api/health && echo ;;
  logs)
    exec docker compose logs -f --tail "$(token "${2:-100}")" "$(token "${1:-api}")" ;;
  logs-all)
    exec docker compose logs -f --tail "$(token "${1:-50}")" ;;
  images)
    docker compose images ;;
  volumes)
    for v in $(docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT"); do
      printf '%-32s %s\n' "$v" "$(docker volume inspect -f '{{.Mountpoint}}' "$v")"
    done
    echo; echo "[크기] docker system df -v 의 볼륨 부분"
    docker system df -v | awk -v pre="${PROJECT}_" '/^VOLUME NAME/{p=1; print; next} p&&/^$/{exit} p&&index($1,pre)==1' ;;
  rag)
    echo "[RAG 설정] (.env에 없으면 기본값)"
    grep -E '^(EMBEDDING_PROVIDER|EMBEDDING_MODEL|EMBEDDING_DIM|RERANKER_MODEL|RAG_COLLECTION|RAG_CANDIDATE_K|RAG_MIN_RELEVANCE|VOYAGE_BASE_URL)=' .env \
      | sed -E 's/[[:space:]]+$/  ← 끝에 공백 있음/' || true
    if grep -qE '^VOYAGE_API_KEY=.+' .env; then echo "VOYAGE_API_KEY=(설정됨)"; else echo "VOYAGE_API_KEY=(없음)"; fi

    echo; echo "[Qdrant 컬렉션]"
    if ! list=$(curl -fsS localhost:6333/collections 2>&1); then
      echo "Qdrant 조회 실패: $list"
    else
      names=$(printf '%s' "$list" | python3 -c 'import json,sys; print(" ".join(c["name"] for c in json.load(sys.stdin)["result"]["collections"]))')
      [ -n "$names" ] || echo "(컬렉션 없음) 컬렉션은 문서·승인 보고서가 처음 저장될 때 만들어진다. 아래 DB 집계와 비교한다"
      for c in $names; do
        curl -fsS "localhost:6333/collections/$c" | python3 -c '
import json, sys
r = json.load(sys.stdin)["result"]
m = (r.get("config") or {}).get("metadata") or {}
print(sys.argv[1], "points=%s" % r.get("points_count"), m.get("embedding_model", ""))' "$c"
      done
    fi

    echo; echo "[DB 집계] 개수만"
    docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB" -X -q -P pager=off' <<'SQL'
select 'document' as 대상, status as 상태, count(*) as 개수 from document group by status
union all
select 'report_index_job', status, count(*) from report_index_job group by status
order by 1, 2;
SQL
    ;;
  db)
    exec docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"' ;;
  env-keys)
    grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' .env | tr -d '=' | sort ;;
  env-check|env-sync)
    # 배포 워크플로가 복사해 둔 .env.example·check_env.py를 떠 있는 api 이미지의 Python으로 돌린다.
    # docker compose run을 쓰지 않는다: 새 compose 파일이 요구하는 변수가 .env에 없으면
    # compose가 파일을 읽다가 멈춰서, 그 변수를 채우려는 이 명령도 돌지 못한다.
    for f in .env .env.example check_env.py; do
      [ -f "$f" ] || { echo "$APP_DIR/$f 가 없다. .env는 docs/DEPLOY.md, 나머지는 배포 워크플로가 복사한다"; exit 1; }
    done
    # docker ps의 {{.Image}}는 같은 태그를 다시 빌드·pull하면 이름 없는 ID(bf21d13aa372)로 바뀌고,
    # containerd 이미지 저장소에서는 그 ID로 docker run을 못 한다. 컨테이너가 쓰는 이미지 이름(태그)을 쓴다.
    image=""
    cid=$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" \
      --filter label=com.docker.compose.service=api | head -n1)
    [ -n "$cid" ] && image=$(docker inspect --format '{{.Config.Image}}' "$cid")
    if [ -n "$image" ] && ! docker image inspect "$image" >/dev/null 2>&1; then
      echo "api 이미지($image)가 서버에 없어 $cmd를 건너뛴다"; exit 0
    fi
    if [ -z "$image" ]; then
      echo "떠 있는 api 컨테이너가 없어 $cmd를 건너뛴다. 처음 설치는 docs/DEPLOY.md 서버 .env 절을 따른다"
      exit 0
    fi
    opts=(--no-shell-check)
    [ "$cmd" = env-sync ] && opts=(--add-missing)
    # 네트워크 없이, 서버 사용자 권한으로 실행해 .env·.env.bak 소유자와 권한(600)을 유지한다.
    docker run --rm --pull never --network none --user "$(id -u):$(id -g)" \
      -v "$APP_DIR:/work" -v "$APP_DIR/check_env.py:/tmp/check_env.py:ro" "$image" \
      python /tmp/check_env.py --file /work/.env --example /work/.env.example "${opts[@]}" ;;
  seed-docs)
    # 떠 있는 api 컨테이너 안에서 실행한다(같은 .env·업로드 볼륨·Qdrant).
    if [ -n "${1:-}" ] && [ "$1" != "--replace" ]; then echo "seed-docs 인자는 --replace만 받는다"; exit 2; fi
    docker compose exec -T api python scripts/seed_documents.py ${1:+"$1"} ;;
  reindex-reports)
    docker compose exec -T api python scripts/index_reports.py --all ;;
  retry-reports)
    docker compose exec -T api python scripts/index_reports.py --retry-failed ;;
  restart)
    [ -n "${1:-}" ] || { echo "서비스 이름이 필요하다: restart api"; exit 2; }
    docker compose restart "$(token "$1")" ;;
  up)
    docker compose up -d && docker compose ps ;;
  pull-up)
    docker compose pull --quiet && docker compose up -d && docker compose ps ;;
  *)
    echo "모르는 명령: $cmd"; echo; usage; exit 2 ;;
esac

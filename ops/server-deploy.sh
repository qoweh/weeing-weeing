#!/usr/bin/env bash
# 운영 서버(EC2) 안에서 직접 이미지를 빌드하고 배포한다. GitHub Actions 없이 쓰는 수동 CD.
#
# 사용법 (서버에서):
#   ~/ww-deploy.sh                 # origin/main 최신 커밋 빌드·배포 (api, frontend, web)
#   ~/ww-deploy.sh dev             # 다른 브랜치·태그·커밋 SHA
#   ~/ww-deploy.sh main api        # 일부 서비스만 (api | frontend | web, 여러 개 가능)
#   ~/ww-deploy.sh --rollback      # 직전 배포 이미지로 되돌리기 (빌드 없음)
#
# 동작: 소스 받기(~/weeing-weeing-src, deploy key) → ML 모델 확보·SHA-256 검증 → 이미지 빌드
#       (태그 = 커밋 SHA, 이름은 deploy.yml과 같음) → compose·.env.example 복사, .env 키 보충
#       → .env 이미지 태그 교체 → up → 헬스체크 → 실패 시 이전 태그로 자동 복귀 → 오래된 이미지 정리.
# deploy.yml과 같은 compose·.env 규칙을 쓰므로 Actions 배포와 섞어 써도 된다.
# .env 값은 출력하지 않는다.
set -euo pipefail

SRC_DIR="${WW_SRC_DIR:-$HOME/weeing-weeing-src}"
APP_DIR="$HOME/weeing-weeing"
REPO_URL="${WW_REPO_URL:-git@github-ww:qoweh/weeing-weeing.git}"
IMAGE_PREFIX="ghcr.io/qoweh/weeing-weeing"
ML_CACHE="$HOME/.cache/ww-ml"
ALL_SERVICES=(api frontend web)
TAG_KEYS='^(IMAGE_PREFIX|IMAGE_TAG|API_IMAGE_TAG|WEB_IMAGE_TAG)='

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m오류: %s\033[0m\n' "$*" >&2; exit 1; }

# 동시에 두 번 돌지 않게 한다.
exec 9>"$HOME/.ww-deploy.lock"
flock -n 9 || die "다른 배포가 진행 중입니다."

cd "$APP_DIR" 2>/dev/null || die "$APP_DIR 가 없습니다."
[ -f .env ] || die "$APP_DIR/.env 가 없습니다(docs/DEPLOY.md 서버 .env)."

# .env에서 이미지 태그 줄을 지우고 새 값을 붙인다.
set_tags() { # $1=IMAGE_TAG $2=API_IMAGE_TAG $3=WEB_IMAGE_TAG
  sed -i -E "/${TAG_KEYS}/d" .env
  if [ -s .env ] && [ -n "$(tail -c1 .env)" ]; then echo >> .env; fi
  printf 'IMAGE_PREFIX=%s\nIMAGE_TAG=%s\nAPI_IMAGE_TAG=%s\nWEB_IMAGE_TAG=%s\n' \
    "$IMAGE_PREFIX" "$1" "$2" "$3" >> .env
}

current_tag() { # $1=서비스. 지금 떠 있는 컨테이너의 이미지 태그
  local cid img
  cid=$(docker compose ps -q "$1" 2>/dev/null || true)
  [ -n "$cid" ] || { echo ""; return; }
  img=$(docker inspect --format '{{.Config.Image}}' "$cid")
  echo "${img##*:}"
}

health_check() {
  local total running status i
  total=$(docker compose config --services | wc -l)
  for i in $(seq 1 30); do
    status=$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q api)" 2>/dev/null || echo none)
    running=$(docker compose ps --services --status running | wc -l)
    if [ "$status" = healthy ] && [ "$running" -eq "$total" ]; then
      docker compose ps --format 'table {{.Service}}\t{{.Image}}\t{{.Status}}'
      echo "모든 서비스 정상 (api healthy, $running/$total running)"
      return 0
    fi
    sleep 5
  done
  docker compose ps -a
  docker compose logs --tail 60
  echo "150초 안에 정상이 되지 않았습니다 (api: $status, running: $running/$total)"
  return 1
}

restore_previous() {
  [ -s .deploy-previous-tags ] || die "되돌릴 이전 태그 기록(.deploy-previous-tags)이 없습니다."
  sed -i -E "/${TAG_KEYS}/d" .env
  if [ -s .env ] && [ -n "$(tail -c1 .env)" ]; then echo >> .env; fi
  cat .deploy-previous-tags >> .env
  # 이전 이미지가 서버에 없으면 GHCR에서 받으려 한다(docker login 필요).
  docker compose up -d --remove-orphans --wait --wait-timeout 150
  docker compose ps --format 'table {{.Service}}\t{{.Image}}\t{{.Status}}'
}

# ---------- 롤백 ----------
if [ "${1:-}" = "--rollback" ]; then
  log "직전 배포로 되돌립니다"
  grep -E "$TAG_KEYS" .env > .deploy-rollback-current || true
  restore_previous
  mv .deploy-rollback-current .deploy-previous-tags
  echo "롤백 완료. 한 번 더 --rollback 하면 롤백 전 버전으로 돌아갑니다."
  exit 0
fi

REF="${1:-main}"
shift || true
if [ "$#" -gt 0 ]; then SERVICES=("$@"); else SERVICES=("${ALL_SERVICES[@]}"); fi
for s in "${SERVICES[@]}"; do
  [[ " ${ALL_SERVICES[*]} " == *" $s "* ]] || die "모르는 서비스: $s (api | frontend | web)"
done
[[ "$REF" =~ ^[A-Za-z0-9._/-]+$ ]] || die "잘못된 ref: $REF"

# ---------- 1. 소스 ----------
log "소스 받기 ($REF)"
if [ ! -d "$SRC_DIR/.git" ]; then
  git clone --quiet "$REPO_URL" "$SRC_DIR" \
    || die "clone 실패. deploy key 설정을 확인하세요: ssh -T github-ww"
fi
cd "$SRC_DIR"
git fetch --quiet --prune --tags origin
if git rev-parse --verify --quiet "origin/$REF^{commit}" >/dev/null; then
  git checkout --quiet --force --detach "origin/$REF"
else
  git checkout --quiet --force --detach "$REF" || die "ref를 찾지 못했습니다: $REF"
fi
git clean -fdxq -e deploy/ml-models
SHA=$(git rev-parse HEAD)
echo "커밋: $(git log -1 --format='%h %s (%an, %ad)' --date=short)"
running=$(cd "$APP_DIR" && for s in "${SERVICES[@]}"; do
  c=$(docker compose ps -q "$s" 2>/dev/null || true)
  [ -n "$c" ] && docker inspect --format '{{.Config.Image}}' "$c" | sed 's/.*://'
done | sort -u)
if [ "$running" = "$SHA" ] && [ "${FORCE:-0}" != 1 ]; then
  echo "이미 이 커밋($SHA)이 배포돼 있습니다. 다시 빌드하려면: FORCE=1 ~/ww-deploy.sh $REF ${SERVICES[*]}"
  exit 0
fi

# ---------- 2. ML 모델 (api만) ----------
if [[ " ${SERVICES[*]} " == *" api "* ]]; then
  log "ML 모델 확보·검증"
  want=$(python3 -c 'import json;print(json.load(open("deploy/ml_model.json"))["sha256"])')
  mkdir -p "$ML_CACHE" deploy/ml-models
  cached="$ML_CACHE/$want.joblib"
  if [ ! -f "$cached" ] || [ "$(sha256sum "$cached" | cut -d' ' -f1)" != "$want" ]; then
    # 지금 떠 있는 api 이미지 안의 모델을 꺼내 본다(같은 모델이면 그대로 재사용).
    img=$(docker inspect --format '{{.Config.Image}}' "$(cd "$APP_DIR" && docker compose ps -q api)" 2>/dev/null || true)
    if [ -n "$img" ]; then
      cid=$(docker create "$img")
      docker cp "$cid:/app/models/future_error.joblib" "$cached.tmp" >/dev/null 2>&1 || true
      docker rm "$cid" >/dev/null
      if [ -f "$cached.tmp" ] && [ "$(sha256sum "$cached.tmp" | cut -d' ' -f1)" = "$want" ]; then
        mv "$cached.tmp" "$cached"
      else
        rm -f "$cached.tmp"
      fi
    fi
  fi
  [ -f "$cached" ] || die "ML 모델(sha256 $want)이 없습니다. 내 PC에서:
  gh release download \$(jq -r .release_tag deploy/ml_model.json) -R qoweh/weeing-weeing -p model.joblib -D /tmp/ml
  scp /tmp/ml/model.joblib ww-team:$ML_CACHE/$want.joblib"
  cp "$cached" deploy/ml-models/model.joblib
  echo "모델 검증 완료: $want"
fi

# ---------- 3. 설정 파일 반영 ----------
# 빌드 전에 한다: env-sync는 떠 있는 api 이미지로 도는데, 같은 SHA를 다시 빌드하면
# 그 이미지가 태그를 잃어 docker run으로 못 쓰게 된다(containerd 이미지 저장소).
log "compose·.env.example 반영"
cp deploy/docker-compose.prod.yml "$APP_DIR/docker-compose.yml"
cp .env.example "$APP_DIR/.env.example"
cp scripts/check_env.py "$APP_DIR/check_env.py"
# 서버에 ~/ww-server.sh(고친 server.sh)가 있으면 그걸 쓴다. 레포 반영 뒤엔 지워도 된다.
if [ -f "$HOME/ww-server.sh" ]; then bash "$HOME/ww-server.sh" env-sync; else bash ops/server.sh env-sync; fi

# ---------- 4. 빌드 (메모리 8GB라 하나씩) ----------
for s in "${SERVICES[@]}"; do
  log "빌드: $s → $IMAGE_PREFIX-$s:$SHA"
  DOCKER_BUILDKIT=1 docker build -f "deploy/$s.Dockerfile" -t "$IMAGE_PREFIX-$s:$SHA" .
done

# ---------- 5. 교체 ----------
cd "$APP_DIR"
grep -E "$TAG_KEYS" .env > .deploy-previous-tags || true
api_tag=$(current_tag api); fe_tag=$(current_tag frontend); web_tag=$(current_tag web)
in_list() { [[ " ${SERVICES[*]} " == *" $1 "* ]]; }
in_list api && api_tag=$SHA
in_list frontend && fe_tag=$SHA
in_list web && web_tag=$SHA
[ -n "$api_tag" ] && [ -n "$fe_tag" ] && [ -n "$web_tag" ] \
  || die "빌드하지 않은 서비스의 현재 태그를 알 수 없습니다. 전체 배포(~/ww-deploy.sh $REF)로 하세요."
# frontend는 IMAGE_TAG를 쓴다(compose 참고).
set_tags "$fe_tag" "$api_tag" "$web_tag"

log "컨테이너 교체"
docker compose up -d --remove-orphans

log "헬스체크"
if ! health_check || ! docker compose exec -T api python scripts/check_ml_runtime.py; then
  log "실패 → 이전 이미지로 되돌립니다"
  restore_previous
  die "새 배포($SHA)가 헬스체크를 통과하지 못해 이전 버전으로 되돌렸습니다."
fi
printf '%s %s %s\n' "$(date '+%F %T')" "$SHA" "${SERVICES[*]}" >> "$APP_DIR/.deploy-history"

# ---------- 6. 정리 (지금 + 직전 태그만 남김) ----------
log "오래된 이미지·빌드 캐시 정리"
keep=$(cat .env .deploy-previous-tags | grep -E "$TAG_KEYS" | cut -d= -f2 | sort -u)
docker images --format '{{.Repository}}:{{.Tag}}' | grep "^$IMAGE_PREFIX-" | while read -r ref; do
  grep -qxF "${ref##*:}" <<<"$keep" || docker rmi "$ref" >/dev/null 2>&1 || true
done
docker image prune -f >/dev/null
docker builder prune -f --keep-storage 4GB >/dev/null
df -h / | tail -1
log "배포 완료: $SHA (${SERVICES[*]})"

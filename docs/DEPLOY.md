# 운영 서버(EC2) 배포

팀 전용 AWS EC2 서버에 앱 전체를 올리고, GitHub Actions로 배포를 자동화한다(#117).

- 서버: 서울 리전, Ubuntu 24.04, 메모리 8GB, 디스크 30GB, 고정 IP, 사용자 `ubuntu`
- **서버는 11/14 00:00에 자동으로 꺼진다.** 서버에만 있는 데이터는 그 전에 [백업](#백업-1114-종료-전)한다
- 서버 IP는 `<EC2_IP>`(고정). 접속 방법은 [AWS_ACCESS](AWS_ACCESS.md)
- 키 파일·`.env`는 레포·이슈·PR에 올리지 않는다(`.gitignore`에 `*.pem`, `*credentials*.csv`)

## 구조

```
GitHub (main push 또는 Run workflow)
  └─ Actions: 이미지 3개 빌드 → GHCR(ghcr.io/qoweh/weeing-weeing-*:<커밋 SHA>)
       └─ SSH로 서버 접속 → docker compose pull && up -d → API 헬스체크

EC2 ~/weeing-weeing/          (레포 clone 없음. 이 두 파일만 있다)
  docker-compose.yml          ← deploy/docker-compose.prod.yml을 워크플로가 복사
  .env                        ← 서버에서 직접 작성(비밀 값)

web(Caddy :80/:443) ─┬─ /api/*  → api(FastAPI :8000)  ─┬─ postgres
                     ├─ /hmi/*  → hmi/web 정적 파일     ├─ qdrant
                     ├─ 그 외   → frontend(Next.js :3100) └─ langfuse-web (기록 전송)
                     └─ langfuse.<EC2_IP>.sslip.io → langfuse-web (~/langfuse, 따로 띄움)
```

| 서비스 | 이미지 | 데이터(볼륨) |
|---|---|---|
| web | `deploy/web.Dockerfile` (Caddy + hmi/web 빌드) | `caddy_data`(인증서) |
| frontend | `deploy/frontend.Dockerfile` | - |
| api | `deploy/api.Dockerfile` | `storage`(업로드), `outputs`(사건 이력) |
| postgres | `postgres:16-alpine` | `postgres_data` |
| qdrant | `qdrant/qdrant:v1.20.0` | `qdrant_data` |

- 서버는 빌드하지 않는다. 8GB에서 Next.js 빌드·의존성 설치를 피하고, 이미지 태그로 롤백하기 위해서다
- API 이미지에는 torch·로컬 AI 모델이 없다(D-31). 임베딩은 해시 방식 또는 외부 API다
- 모든 서비스가 `restart: unless-stopped`라 서버를 껐다 켜면 2~3분 뒤 저절로 다시 뜬다
- 경로: `https://<EC2_IP>/`(frontend), `/hmi/`(hmi/web), `/api/health`, `/api/docs`(API 문서)

## 처음 한 번: 서버 초기 설정

서버에 `ssh`로 접속해 실행한다. 이미 해 둔 상태다(#117). 서버를 새로 받았을 때만 다시 한다.

```
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl ca-certificates htop jq

# 시간대 KST
sudo timedatectl set-timezone Asia/Seoul

# 스왑 2GB
if [ ! -f /swapfile ]; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-swap.conf && sudo sysctl --system > /dev/null

# Docker (공식 저장소)
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker containerd
sudo usermod -aG docker ubuntu

# Docker 로그 용량 제한(없으면 디스크가 로그로 찬다)
sudo tee /etc/docker/daemon.json > /dev/null <<'EOF'
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
EOF
sudo systemctl restart docker
```

다시 로그인한 뒤 확인한다: `timedatectl`(Asia/Seoul), `free -h`(Swap 2.0Gi), `docker run --rm hello-world`, `groups`(docker 포함).

`ufw`는 켜지 않는다. Docker가 ufw를 우회해 효과가 없고, 잘못 켜면 SSH까지 막힌다. 포트는 AWS 보안그룹에서 **22·80·443**만 연다. 22는 GitHub Actions가 접속하므로 IP를 제한할 수 없다(키 인증만 허용).

## 접속 키 관리

공용 `team1.pem`을 돌려 쓰지 않고, 사람마다 키를 따로 등록한다. 한 명만 막을 때는 서버 `~/.ssh/authorized_keys`에서 그 줄만 지운다. **처음부터 있던 강사 키 줄은 지우지 않는다.**

키 만들기·등록·`~/.ssh/config`(별칭 `ww-team`)와 접속 방법은 [AWS_ACCESS](AWS_ACCESS.md)에 순서대로 정리했다.

## 처음 한 번: GitHub Secrets와 서버 .env

### 1. 배포 전용 키

사람 키와 따로 둔다. 유출되면 이 줄만 지우고 다시 만든다.

```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/ww-team/deploy_ed25519 -N ""
```
```bash
ssh-copy-id -i ~/.ssh/ww-team/deploy_ed25519.pub ww-team
```

### 2. Environment `production`에 Secrets 등록

접속 정보는 레포 Secrets가 아니라 **Environment `production`**에 둔다. Environment가 허용한 브랜치에서 `environment: production`을 선언한 job(deploy)만 값을 받는다. 다른 브랜치에 워크플로를 만들어 push해도 서버 키를 꺼낼 수 없다.

레포 Settings → Environments → `production`:

1. **Deployment branches and tags** → Selected branches and tags → `main`, `dev` 추가
2. **Environment secrets**

   | 이름 | 값 |
   |---|---|
   | `EC2_HOST` | 서버 고정 IP |
   | `EC2_SSH_KEY` | 배포 전용 개인 키 내용(`deploy_ed25519`, `.pub` 아님) |
   | `EC2_KNOWN_HOSTS` | 서버 ED25519 호스트 키 한 줄(아래 명령으로 확인 후 등록) |

3. **Environment variables**(선택): `EC2_USER`. 없으면 `ubuntu`. 비밀이 아니므로 Secret에 넣지 않는다(Secret에 넣으면 로그의 같은 글자가 모두 `***`로 가려진다)
4. 같은 이름의 **레포 Secrets는 지운다**(Settings → Secrets and variables → Actions). 남아 있으면 다른 브랜치의 워크플로가 계속 읽을 수 있다

`gh` CLI로 등록할 때(`--env production`):

```bash
gh secret set EC2_SSH_KEY --env production -R qoweh/weeing-weeing < ~/.ssh/ww-team/deploy_ed25519
```

`EC2_KNOWN_HOSTS`는 서버에서 읽은 지문과 인터넷으로 받은 지문이 같은지 확인한 뒤 등록한다.

```bash
ssh ww-team 'ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub'
```
```bash
ssh-keyscan -t ed25519 <EC2_IP> 2>/dev/null | ssh-keygen -lf -
```
```bash
ssh-keyscan -t ed25519 <EC2_IP> 2>/dev/null | gh secret set EC2_KNOWN_HOSTS --env production -R qoweh/weeing-weeing
```

### 3. 서버 .env

서버에서 `.env.example`을 기준으로 작성한다. 레포를 clone하지 않으므로 내용을 붙여 넣는다.

```
mkdir -p ~/weeing-weeing && cd ~/weeing-weeing
nano .env          # .env.example 내용을 붙여 넣고 아래 항목을 바꾼다
chmod 600 .env
```

- `ANTHROPIC_API_KEY=` 주석을 풀고 키를 넣는다. 콘솔에서 사용량 한도를 걸어 둔다
- `POSTGRES_PASSWORD`는 새로 만든다(`openssl rand -hex 16`). URL에 들어가므로 영문·숫자만 쓴다. **DB를 처음 띄운 뒤에는 바꿔도 적용되지 않는다**(볼륨에 처음 값이 남는다)
- `DATABASE_URL`·`QDRANT_URL`·`VECTOR_STORE`는 compose가 컨테이너 주소로 덮어쓰므로 그대로 둬도 된다
- `EMBEDDING_PROVIDER=hashing`, `RERANKER_MODEL=`(빈 값)이 기본이다. 외부 임베딩 API를 켤 때만 바꾼다([RAG 검색](#rag-검색-로컬-모델-없음))
- `ANALYSIS_AUTO_ENABLED=true`는 사건마다 Claude API를 호출한다(비용). 시연할 때만 켠다
- `SITE_ADDRESS=<EC2_IP>`로 HTTPS를 켠다. 자세한 내용은 [HTTPS·Langfuse·내부 서비스 접속](#httpslangfuse내부-서비스-접속)
- `IMAGE_TAG`·`IMAGE_PREFIX`는 배포 워크플로가 적는다. 직접 고치지 않는다

## 배포

- **자동:** release PR(dev → main)이 머지되면 `Deploy (EC2)` 워크플로가 돈다
- **수동:** Actions → Deploy (EC2) → Run workflow → `dev` 선택. Environment가 main·dev만 허용하므로 작업 브랜치는 빌드까지만 되고 배포 단계에서 막힌다
- 워크플로 파일이 기본 브랜치(dev)에 있어야 Run workflow 버튼이 보인다

### 첫 배포 뒤 한 번: 시연 계정

로그인할 계정을 DB에 만든다. 비밀번호는 계정마다 임의로 만들어 **한 번만** 화면에 출력하므로 바로 보관한다(같은 비밀번호로 하려면 `--ask-password`). 이미 있는 사번은 건드리지 않는다. DB 테이블은 API가 처음 DB에 접근할 때 자동으로 만든다.

```
cd ~/weeing-weeing
docker compose run --rm api python scripts/seed_users.py
```

### RAG 검색 (로컬 모델 없음)

서버에는 AI 모델을 받지 않는다. 검색은 다음으로 돈다([EMBEDDING_API](EMBEDDING_API.md)).

- 기본: `EMBEDDING_PROVIDER=hashing`(해시 임베딩) + Kiwi BM25 + 리랭커 끔. 외부 호출·토큰 비용이 없다
- 문서는 웹의 **문서 등록**에서 올린다. 파싱·청킹·임베딩·벡터 저장이 자동으로 진행된다. 운영 카탈로그와 `scripts/build_index.py`·`make index`는 사용하지 않는다
- 품질이 필요하면 서버 `.env`에 `EMBEDDING_PROVIDER=voyage`·`VOYAGE_API_KEY`(·선택 `RERANKER_MODEL=rerank-3-lite`)를 넣고 `docker compose up -d api`. 문서 본문이 외부로 나가므로 [AI_DATA_SECURITY](AI_DATA_SECURITY.md) 점검표를 먼저 본다
- 공급자·모델·차원을 바꾸면 기존 컬렉션과 섞을 수 없다. `.env`의 `RAG_COLLECTION`을 새 이름으로 바꾸고 문서를 다시 등록한다
- 예전 배포에서 남은 `hf_models` 볼륨은 쓰지 않는다. 지우려면 `docker volume ls`로 이름을 확인한 뒤 `docker volume rm <이름>`

### 확인

```
docker compose ps                     # 모두 Up, api는 (healthy)
curl -fsS localhost/api/health
docker compose logs -f --tail 100 api
df -h / && docker system df           # 디스크 30GB
```

## HTTPS·Langfuse·내부 서비스 접속

보안그룹은 22·80·443만 연다. 그래서 웹은 443 하나로 모으고, DB 같은 나머지는 SSH 터널로 본다.

**HTTPS (IP 주소).** 서버 `.env`에 `SITE_ADDRESS=<EC2_IP>`를 넣고 `docker compose up -d web`을 실행한다.
- Let's Encrypt가 IP에 주는 shortlived 인증서(약 6일)를 받고 Caddy가 자동으로 갱신한다. http는 https로 넘어간다
- IP 접속은 SNI가 없어서 `default_sni`로 인증서를 고른다(`deploy/Caddyfile`)
- 문제가 생기면 `SITE_ADDRESS` 줄을 지우고 `docker compose up -d web`으로 되돌린다(:80, HTTP)

**Langfuse (EC2 서버의 LLM 기록).** 팀원 PC는 그대로 홈서버에 기록하고, EC2 api·챗봇만 여기에 기록한다.
- 공식 이미지가 하위 경로를 지원하지 않아 `langfuse.<EC2_IP>.sslip.io`(IP를 가리키는 무료 이름)로 연다
- 앱과 따로 `~/langfuse/`에서 띄운다(`deploy/langfuse/`). 앱 배포 때 재시작되지 않는다. 앱을 먼저 한 번 띄워 네트워크 `weeing-weeing_default`가 있어야 한다
- 가입은 막혀 있다. 관리자 계정·API 키는 `~/langfuse/.env`의 `LANGFUSE_INIT_*` 값으로 **처음 한 번만** 만들어진다. 나중에 `.env`의 비밀번호를 바꿔도 반영되지 않는다([AWS_ACCESS](AWS_ACCESS.md#5-langfuse-ec2-서버의-llm-기록))

```
mkdir -p ~/langfuse && cd ~/langfuse
# deploy/langfuse/docker-compose.yml을 docker-compose.yml로, .env.example을 .env로 복사해 값을 채운다
chmod 600 .env && docker compose up -d
```

앱 `~/weeing-weeing/.env`에 넣고 `docker compose up -d api web`:

```
LANGFUSE_ADDRESS=langfuse.<EC2_IP>.sslip.io
LANGFUSE_BASE_URL=http://langfuse-web:3000      # 서버 안 통신
LANGFUSE_PUBLIC_KEY=<~/langfuse/.env의 INIT_PROJECT_PUBLIC_KEY>
LANGFUSE_SECRET_KEY=<~/langfuse/.env의 INIT_PROJECT_SECRET_KEY>
LLM_USER=ec2
LANGFUSE_TRACING_ENVIRONMENT=demo
```

**DB·Qdrant.** 서버 안(`127.0.0.1`)에만 열려 있다. 팀원은 SSH 터널로 접속한다([AWS_ACCESS](AWS_ACCESS.md#4-ssh-터널로-dbqdrant-접속)).

## 롤백

Actions에서 예전 `Deploy (EC2)` 실행을 열고 **Re-run all jobs**를 누른다. 그 실행의 커밋 SHA 이미지로 다시 배포된다.

급할 때 서버에서 직접 바꿀 수도 있다. `.env`의 `IMAGE_TAG`를 예전 SHA로 바꾸고 `docker compose up -d`를 실행한다. 다만 private 레포라 GHCR 로그인이 필요하므로, 되도록 Re-run을 쓴다.

## 백업 (11/14 종료 전)

서버에만 있는 것: DB, 업로드 원본(`storage`), 사건 이력(`outputs`). Qdrant 색인과 모델은 다시 만들 수 있다.

```
cd ~/weeing-weeing && set -a && . ./.env && set +a
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup-$(date +%m%d).sql
docker run --rm -v weeing-weeing_storage:/s -v weeing-weeing_outputs:/o -v "$PWD":/b alpine \
  tar czf /b/files-$(date +%m%d).tgz -C / s o
```

내 PC로 가져온다. DB 덤프에는 계정·보고서가 들어 있으므로 레포에 올리지 않는다.

```bash
scp 'ww-team:~/weeing-weeing/backup-*.sql' 'ww-team:~/weeing-weeing/files-*.tgz' .
```

## 문제 해결

| 증상 | 확인 |
|---|---|
| 워크플로가 `Secret이 필요합니다`로 실패 | Environment `production`의 Secrets 3개 이름 확인. 허용 브랜치(main·dev)가 아닌 곳에서 실행하면 값이 비어 이 오류가 난다 |
| `Host key verification failed` / `No ED25519 host key is known` | `EC2_KNOWN_HOSTS`에 서버 ED25519 지문이 없음. [위 명령](#2-environment-production에-secrets-등록)으로 다시 등록. 이때 접속 실패가 `.env가 없습니다`로 함께 표시된다 |
| `Connection timed out`(SSH) | 서버가 꺼져 있거나 보안그룹 22번이 닫혀 있음 |
| `.env가 없습니다` | [서버 .env](#3-서버-env) 작성 |
| API가 healthy가 안 됨 | `docker compose logs api`. DB 비밀번호 불일치(처음 값과 다름)가 흔하다 |
| 디스크 부족 | `docker system df`. 배포 때마다 쓰지 않는 이미지를 지운다(`prune -af`). 그래도 차면 볼륨 크기 확인 |
| 메모리 부족(OOM) | `docker stats`. 로컬 임베딩 모델(약 1.5GB)을 뺐으므로 그 전보다 적게 쓴다. 필요하면 강사에게 16GB 요청 |

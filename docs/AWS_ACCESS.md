# 운영 서버(AWS EC2) 접속 안내

팀원이 운영 서버의 웹·Langfuse·DB·Qdrant에 접속하는 방법을 순서대로 정리했다. 배포·서버 설정은 [DEPLOY](DEPLOY.md)를 본다.

- 서버 IP: **`<EC2_IP>`** (고정)
- **서버는 11/14 00:00에 자동으로 꺼진다.** 그 뒤에는 아래 주소가 모두 닫힌다
- AWS 보안그룹은 **22(SSH)·80·443(웹)**만 연다. 팀이 직접 바꿀 수 없다. 그래서 웹은 443 하나로 모으고, 나머지는 SSH 터널로 접속한다

## 1. 한눈에 보기

| 대상 | 주소 | 필요한 것 |
|---|---|---|
| 웹(프론트) | `https://<EC2_IP>/` | 없음 |
| HMI | `https://<EC2_IP>/hmi/` | 없음 |
| API 문서 | `https://<EC2_IP>/api/docs` | 없음 |
| Langfuse(EC2 기록) | `https://langfuse.<EC2_IP>.sslip.io` | 아래 관리자 계정 |
| PostgreSQL | SSH 터널 후 `localhost:15432` | 서버에 등록한 SSH 키 |
| Qdrant 대시보드 | SSH 터널 후 `http://localhost:16333/dashboard` | 서버에 등록한 SSH 키 |

- `http://`로 접속하면 `https://`로 자동으로 넘어간다
- 인증서는 Let's Encrypt가 IP 주소에 주는 약 6일짜리 인증서이고, 서버(Caddy)가 자동으로 갱신한다
- sslip.io는 `langfuse.1-2-3-4.sslip.io`처럼 이름에 들어 있는 IP를 그대로 돌려주는 무료 DNS다. Langfuse 공식 이미지는 `https://<IP>/langfuse` 같은 하위 경로를 지원하지 않아 이름으로 나눴다

## 2. SSH 키 등록 (처음 한 번)

공용 `team1.pem`은 돌려 쓰지 않는다. 사람마다 키를 따로 만들어 서버에 등록한다.

1. 내 PC에서 키를 만든다.
   ```bash
   ssh-keygen -t ed25519 -C "<GitHub 핸들>" -f ~/.ssh/ww_ed25519
   ```
2. **공개 키**(`~/.ssh/ww_ed25519.pub`, `.pub` 파일)만 서버 관리자(김민우)에게 보낸다. 개인 키(`.pub` 없는 파일)는 절대 보내지 않는다
3. 관리자가 서버 `~/.ssh/authorized_keys`에 한 줄로 추가한다
4. `~/.ssh/config`에 별칭을 등록한다. 아래 명령들은 이 별칭 `ww-team`을 쓴다.
   ```
   Host ww-team
     HostName <EC2_IP>
     User ubuntu
     IdentityFile ~/.ssh/ww_ed25519
     IdentitiesOnly yes
     ServerAliveInterval 60
   ```

## 3. SSH 접속

```bash
ssh ww-team
```

별칭 없이 쓸 때:

```bash
ssh -i ~/.ssh/ww_ed25519 ubuntu@<EC2_IP>
```

- `Permission denied (publickey)`: 공개 키가 아직 등록되지 않았거나 다른 키를 쓰고 있다
- `Connection timed out`: 서버가 꺼져 있다(11/14 이후 포함)

## 4. SSH 터널로 DB·Qdrant 접속

DB(5432)·Qdrant(6333)는 서버 안(`127.0.0.1`)에서만 열려 있다. SSH 터널은 내 PC의 포트를 서버 안의 포트로 이어 준다. 내 PC에서 PostgreSQL·Qdrant를 이미 쓰고 있을 수 있어 15432·16333으로 받는다.

터널을 연다. 이 터미널은 접속하는 동안 **켜 둔다**(출력 없이 멈춰 있는 것이 정상). 끝나면 `Ctrl+C`.

```bash
ssh -N -L 15432:localhost:5432 -L 16333:localhost:6333 ww-team
```

별칭 없이 쓸 때:

```bash
ssh -N -i ~/.ssh/ww_ed25519 -L 15432:localhost:5432 -L 16333:localhost:6333 ubuntu@<EC2_IP>
```

### PostgreSQL

DBeaver·DataGrip·psql에서 다음 값으로 접속한다.

| 항목 | 값 |
|---|---|
| Host / Port | `localhost` / `15432` |
| Database·User·Password | 서버 `~/weeing-weeing/.env`의 `POSTGRES_DB`·`POSTGRES_USER`·`POSTGRES_PASSWORD`(관리자에게 개별로 받는다) |

```bash
psql -h localhost -p 15432 -U <POSTGRES_USER> <POSTGRES_DB>
```

운영 DB다. 조회 위주로 쓰고, 수정·삭제는 팀에 알린 뒤 한다.

### Qdrant

브라우저에서 `http://localhost:16333/dashboard`를 연다. API는 `http://localhost:16333`.

## 5. Langfuse (EC2 서버의 LLM 기록)

- EC2의 api·챗봇 호출만 여기에 기록된다(사용자 `ec2`, 환경 `demo`). **팀원 PC의 기록은 그대로 홈서버 Langfuse**에 간다([USAGE_TRACKING](USAGE_TRACKING.md))
- 가입은 막혀 있다(`AUTH_DISABLE_SIGNUP=true`). 팀원 계정이 필요하면 관리자가 잠시 가입을 열고(`deploy/langfuse/docker-compose.yml`에서 `false`로 바꾼 뒤 `docker compose up -d langfuse-web`), 팀원이 가입하면 Settings → Members에서 프로젝트에 추가한 뒤 다시 막는다
- 관리자 계정(팀 공용). 서버 `~/langfuse/.env`의 `LANGFUSE_INIT_USER_*`와 같다

  | 항목 | 값 |
  |---|---|
  | 이메일 | `admin@example.com` |
  | 비밀번호 | `12345678` |

  private 레포라 팀 결정으로 적어 둔다(2026-11-03). 인터넷에 열린 화면이므로 레포 밖으로 옮기지 않고, 바꾸면 이 표도 고친다

**관리자 비밀번호를 바꿀 때 주의:** `LANGFUSE_INIT_USER_PASSWORD`는 계정을 **처음 만들 때 한 번만** 쓰인다. `.env`만 바꾸면 로그인되지 않는다. Langfuse 화면(Settings)에서 바꾸거나, 서버에서 `.env` 값을 DB에 다시 반영한다.

```
cd ~/langfuse
pw=$(grep '^LANGFUSE_INIT_USER_PASSWORD=' .env | cut -d= -f2-)
email=$(grep '^LANGFUSE_INIT_USER_EMAIL=' .env | cut -d= -f2-)
hash=$(docker exec weeing-weeing-web-1 caddy hash-password --plaintext "$pw")
docker compose exec -T langfuse-postgres psql -U postgres -v h="$hash" -v e="$email" <<'EOF'
update users set password = :'h' where email = :'e';
EOF
```

인터넷에 열린 화면이므로 짧은 비밀번호(예: 숫자 8자리)는 시연 직후 바꾼다.

## 6. 서버 안 파일 위치

| 위치 | 내용 |
|---|---|
| `~/weeing-weeing/docker-compose.yml` | 앱 구성. 배포 워크플로가 `deploy/docker-compose.prod.yml`로 덮어쓴다 |
| `~/weeing-weeing/.env` | 앱 비밀 값. `SITE_ADDRESS`(HTTPS), `LANGFUSE_*` 포함 |
| `~/langfuse/docker-compose.yml` · `.env` | Langfuse 구성과 비밀 값(`deploy/langfuse/`). 앱 배포와 따로 움직인다 |

자주 쓰는 확인 명령(서버에서):

```
cd ~/weeing-weeing && docker compose ps            # 앱
cd ~/langfuse && docker compose ps                 # Langfuse
docker logs --tail 50 weeing-weeing-web-1          # HTTPS 인증서·Caddy
```

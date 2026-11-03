# 입구(Caddy) 이미지. 경로별로 frontend·API로 넘기고, hmi/web 정적 파일을 직접 서빙한다.
#   docker build -f deploy/web.Dockerfile -t weeing-web .
FROM node:24-alpine AS hmi
WORKDIR /hmi
COPY hmi/web/package.json hmi/web/package-lock.json ./
RUN npm ci
COPY hmi/web/ ./
# /hmi/ 아래에서 서빙하므로 자산 경로 기준을 바꾼다(vite.config.js는 개발용 그대로 둔다).
RUN npx vite build --base=/hmi/

FROM caddy:2-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=hmi /hmi/dist /srv/hmi

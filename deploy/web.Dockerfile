# 입구(Caddy) 이미지. 경로별로 frontend·API로 넘기고, hmi/web 정적 파일을 직접 서빙한다.
#   docker build -f deploy/web.Dockerfile -t weeing-web .
FROM node:24-alpine@sha256:8a32c8cf649a49915a66e81e7a609223c708d0adabf288ee3f4077d765542f85 AS hmi
WORKDIR /hmi
COPY hmi/web/package.json hmi/web/package-lock.json ./
RUN npm ci
COPY hmi/web/ ./
# /hmi/ 아래에서 서빙하므로 자산 경로 기준을 바꾼다(vite.config.js는 개발용 그대로 둔다).
RUN npx vite build --base=/hmi/

FROM caddy:2-alpine@sha256:f6228111e5fafa1a5238258d0858e103f10599b8d1659a146e7726681a002bb9
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY deploy/cctv-viewer.html /srv/cctv-viewer.html
COPY --from=hmi /hmi/dist /srv/hmi

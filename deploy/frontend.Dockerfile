# frontend(Next.js) 운영 이미지. 빌드 위치는 레포 루트다(docs/DEPLOY.md).
#   docker build -f deploy/frontend.Dockerfile -t weeing-frontend .
FROM node:24-alpine@sha256:8a32c8cf649a49915a66e81e7a609223c708d0adabf288ee3f4077d765542f85 AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# 빌드에는 devDependencies(typescript·tailwind)가 필요하고, 실행에는 필요 없어 빌드 뒤에 지운다.
RUN npm run build && npm prune --omit=dev

FROM node:24-alpine@sha256:8a32c8cf649a49915a66e81e7a609223c708d0adabf288ee3f4077d765542f85
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=build /app/package.json /app/next.config.mjs ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/.next ./.next
# next start는 public/(아이콘·이미지·글꼴)을 실행 위치에서 서빙한다. 빠지면 /assets/*가 404다.
COPY --from=build /app/public ./public
USER node
EXPOSE 3100
CMD ["node_modules/.bin/next", "start", "-H", "0.0.0.0", "-p", "3100"]

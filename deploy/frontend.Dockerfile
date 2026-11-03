# frontend(Next.js) 운영 이미지. 빌드 위치는 레포 루트다(docs/DEPLOY.md).
#   docker build -f deploy/frontend.Dockerfile -t weeing-frontend .
FROM node:24-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# 빌드에는 devDependencies(typescript·tailwind)가 필요하고, 실행에는 필요 없어 빌드 뒤에 지운다.
RUN npm run build && npm prune --omit=dev

FROM node:24-alpine
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=build /app/package.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/.next ./.next
USER node
EXPOSE 3100
CMD ["node_modules/.bin/next", "start", "-H", "0.0.0.0", "-p", "3100"]

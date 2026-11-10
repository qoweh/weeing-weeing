# hmi/web

Vite + React로 만든 HMI 화면이다. 사건 분석 결과·단계별 근거, 보고서 작성·결재, 문서(RAG) 관리,
챗봇을 다룬다. 배포에서는 `deploy/web.Dockerfile`이 빌드해 Caddy가 `/hmi/` 경로로 서빙한다.
메인 화면(대시보드·정비 이력)은 `frontend/`(Next.js)이며, 두 화면은 같은 API를 쓴다.

## 실행

API(`make api`, http://127.0.0.1:8000)를 먼저 띄운 뒤 다른 터미널에서 실행한다.
개발 서버는 `/api` 요청을 `vite.config.js`의 프록시로 API에 넘긴다.

```bash
cd hmi/web
npm ci
npm run dev        # http://localhost:5173
```

## 검사

```bash
npm run lint
npm run build
node --test 'tests/*.test.js'
```

## 관련 문서

- [보고서 저장·결재](../../docs/REPORTS.md)
- [멀티 에이전트 분석 화면](../../docs/MULTI_AGENT_ANALYSIS.md)
- [배포 구성](../../docs/DEPLOY.md)

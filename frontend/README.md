<div align="center">

# ⚙️ weeing-weeing

### AI-powered Equipment Maintenance Assistant

**제조업 설비·장비 정비를 위한 RAG 기반 AI 서비스**

설비 매뉴얼과 정비 관련 문서를 검색하고, 필요한 정보를 빠르게 확인할 수 있도록 돕는 웹 애플리케이션입니다.

<br />

<img src="https://img.shields.io/badge/React-149ECA?style=for-the-badge&logo=react&logoColor=white" alt="React" />
<img src="https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white" alt="TypeScript" />
<img src="https://img.shields.io/badge/Next.js-000000?style=for-the-badge&logo=nextdotjs&logoColor=white" alt="Next.js" />
<img src="https://img.shields.io/badge/Tailwind_CSS-06B6D4?style=for-the-badge&logo=tailwindcss&logoColor=white" alt="Tailwind CSS" />
<img src="https://img.shields.io/badge/Sass-CC6699?style=for-the-badge&logo=sass&logoColor=white" alt="Sass" />

<br />

**Frontend** · Next.js + React + TypeScript (TSX) · **Backend API** · FastAPI

</div>

---

## 📌 About

**weeing-weeing**은 제조 현장의 설비 및 장비 정비 업무를 지원하기 위한 프론트엔드 프로젝트입니다.

RAG(Retrieval-Augmented Generation) 시스템과 연동하여 정비 문서 기반 검색 및 AI 질의응답 경험을 제공하는 것을 목표로 합니다.

> 현재 개발 중인 프로젝트입니다. 아래 기능 및 폴더 구조는 개발 목표와 권장 구성을 포함합니다.

## ✨ Key Features

- 🔎 **정비 정보 검색** — 설비 매뉴얼과 정비 문서에서 필요한 정보 탐색 _(계획)_
- 💬 **AI 질의응답** — RAG 기반 정비 질문 및 답변 인터페이스 _(계획)_
- 🧩 **Custom UI** — 재사용 가능한 컴포넌트 직접 구현 _(계획)_
- 🔗 **API Integration** — FastAPI 백엔드와 연동 _(계획)_

## 🛠️ Tech Stack

| Category    | Stack                            |
| :---------- | :------------------------------- |
| **Core**    | Next.js, React, TypeScript (TSX) |
| **Styling** | Tailwind CSS, Sass (SCSS)        |
| **Routing** | Next.js App Router               |
| **State**   | Redux _(도입 예정)_              |
| **API**     | FastAPI (REST API 연동)          |
| **Quality** | 설정 예정                        |
| **UI**      | Custom Components                |

## 📸 Preview

> UI가 완성되면 주요 화면의 스크린샷 또는 GIF를 이곳에 추가할 예정입니다.

<!-- 예시: ![weeing-weeing preview](./docs/images/preview.png) -->

## 🚀 Getting Started

### Requirements

- Node.js 및 npm (지원 버전은 프로젝트 설정에 따라 확인)
- FastAPI 백엔드 서버 (API 연동 기능 사용 시)

### Installation

```bash
git clone <YOUR_REPOSITORY_URL>
cd weeing-weeing/frontend
npm install
```

### Environment Variables

Next.js 서버가 `/api` 요청을 FastAPI로 전달합니다. 기본 주소는 `http://127.0.0.1:8000`이며, 다른 주소를 사용할 경우 `frontend/.env.local`에 설정한 뒤 서버를 다시 시작합니다.

```env
API_ORIGIN=http://127.0.0.1:8000
```

### Run

```bash
npm run dev
```

Next.js 개발 서버: `http://localhost:3100`

백엔드도 별도로 실행해야 로그인과 문서 등록, 분석, 보고서 기능을 사용할 수 있습니다. 화면은 `src/views`, 공통 UI는 `src/components`, API 연결은 `src/api`에서 관리하며 현재 단일 페이지에서 전환됩니다.

### 센서 대시보드

로그인 후 `/api/telemetry/latest`로 최초 상태를 조회하고 `/api/telemetry/stream`의
Bearer 인증 SSE로 실제 센서값을 갱신합니다. 기존 8개 수치 그래프와 입구·출구 감지를
표시하며, 그래프는 최신 수신 표본 시각 기준 최근 60초만 유지합니다. UI에서 RMS·첨도나
이상 판정을 새로 계산하지 않고 서버가 제공한 값을 사용합니다.

그래프 설정의 0.5·1·5초는 화면 갱신 주기입니다. SSE 수신과 표본 수집은 계속하며
같은 표본을 반복 수신해도 그래프에 중복 추가하지 않습니다. 누락값은 `—`로 표시하고
그래프를 끊으며, 2초를 초과한 표본 간격도 선으로 연결하지 않습니다.
지연·송신 종료·조회 단절 시 마지막 수신값임을 표시합니다. 새 프로세스 또는 감지 세션이면
그래프를 초기화하며, 기존 사건 회복이나 사람 승인을 뜻하지 않습니다.
조회 오류는 대기시간을 늘려 재접속하고, 401/403이면 로그인 화면으로 돌아갑니다.
센서 SSE 응답은 `Cache-Control: no-store, no-transform`으로 압축 중계의 버퍼링을
막습니다. 중계 서버도 `text/event-stream` 응답을 모아서 전송하지 않아야 합니다.

```bash
npm run test:sensor  # 가짜 센서·SSE로 그래프, 세션 전환, 인증·취소·크기 제한 검증
```

### Build

```bash
npm run build
npm run start
```

## 🌐 Deployment

배포 플랫폼은 아직 결정되지 않았습니다.

---

<div align="center">
  <sub>Built with Next.js · React · TypeScript</sub>
</div>

## 챗봇 패널

로그인 후 오른쪽 아래 챗봇을 열면 서버의 FAQ 목록을 조회합니다. ‘채팅 시작’을 누른 뒤
질문을 전송하면 기존 챗봇 API로 검색·답변합니다. 여러 답변 부분은 하나의 말풍선에 표시하며
출처 버튼에서 매뉴얼 PDF와 인용 버전 보고서 내용을 확인합니다. 검색 조건·내 대화·새 대화도
패널에서 관리합니다. API 키는 화면에서 입력하지 않습니다.

```bash
npm run test:chat  # API 경로·요청 ID·상태 확인/재시도 회귀 테스트
npm run build
```

백엔드·인증·중복 요청·장애 정책은 [CHAT_API](../docs/CHAT_API.md)를 참고하세요.

### 채팅 마크다운·검증 후 스트리밍

`npm ci --ignore-scripts` 후 `npm run dev`로 실행한다. 답변은 react-markdown과 remark-gfm으로
제목·목록·표·강조·코드를 렌더링하고 remark-breaks로 한 번 개행도 보존한다. 자유 질문은 인증된 POST SSE를 사용하며, 상태 문구는
실제 검색/작성/근거 검토 단계마다 같은 자리에서 갱신한다. 본문은 검증·DB 저장 후 전송하므로
검토 전 초안은 표시하지 않는다. 연결 중단 후에는 기존 상태 확인 버튼을 사용한다.
`npm run test:chat`은 수신 분할·중단·중복 방지와 마크다운 렌더링을 함께 검사한다.

검증된 본문은 화면에서 순차적으로 나타나며, 긴 답변의 표시 효과는 최대 6초다.
운영체제의 모션 줄이기 설정에서는 즉시 표시한다. 생성 중인 초안은 계속 비공개다.

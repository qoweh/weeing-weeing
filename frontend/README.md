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

- 🔎 **정비 정보 검색** — 설비 매뉴얼과 정비 문서에서 필요한 정보 탐색 *(계획)*
- 💬 **AI 질의응답** — RAG 기반 정비 질문 및 답변 인터페이스 *(계획)*
- 🧩 **Custom UI** — 재사용 가능한 컴포넌트 직접 구현 *(계획)*
- 🔗 **API Integration** — FastAPI 백엔드와 연동 *(계획)*

## 🛠️ Tech Stack

| Category | Stack |
| :--- | :--- |
| **Core** | Next.js, React, TypeScript (TSX) |
| **Styling** | Tailwind CSS, Sass (SCSS) |
| **Routing** | Next.js App Router |
| **State** | Redux *(도입 예정)* |
| **API** | FastAPI (REST API 연동) |
| **Quality** | 설정 예정 |
| **UI** | Custom Components |



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

백엔드도 별도로 실행해야 로그인과 문서 등록, 분석, 보고서 기능을 사용할 수 있습니다. 화면은 `src/views`, 공통 UI는 `src/components`, API 연결은 `src/api`에서 관리하며 현재 단일 페이지에서 전환됩니다. 대시보드 수치는 예시입니다.

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

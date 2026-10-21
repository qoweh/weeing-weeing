# 결정 기록

중요한 기술 결정을 한 줄 요약과 이유로 남긴다. 새 결정은 위에 추가한다.
번복할 때는 지우지 말고 새 항목에 "D-00 번복"이라고 적는다.

| # | 날짜 | 결정 | 이유 | 상태 |
|---|---|---|---|---|
| D-07 | 2026-10-20 | 스킬 원본은 `.agents/skills`, Claude Code용 `.claude/skills`는 `scripts/sync_skills.py`로 만든 복사본을 커밋 | Codex와 Claude Code가 찾는 위치가 다름. 심볼릭 링크는 Windows에서 깨질 수 있음. CI·pre-commit이 두 폴더가 같은지 검사 | 확정 |
| D-06 | 2026-10-20 | 문서만 바뀐 PR은 Lint·Test를 건너뜀. 잡 단위 `if`로 건너뛰고 트리거 `paths` 필터는 쓰지 않음. Secret scan·Skills sync는 항상 실행 | Actions 시간 절약(private 레포는 월 사용량 한도). 트리거 필터는 필수 검사 지정 시 PR이 '대기 중'으로 멈춤. 판단이 불확실하면 실행하고, 건너뛸 경로만 목록으로 둠 | 확정 |
| D-05 | 2026-10-20 | CI 액션은 커밋 SHA로 고정. `actions/checkout`은 v6.1.0 유지 | 태그 바꿔치기 공급망 공격 방지. v7은 fork PR 체크아웃 동작이 바뀌는 큰 변경이라 보류함 | 확정 |
| D-04 | 2026-10-20 | 운영용 기능(배포 자동화·백업·모니터링·dependabot)은 지금 넣지 않음 | 11월 첫째~둘째 주 완성이 우선. 6차(온프레미스 배포) 때 필요한 만큼만 추가 | 확정 |
| D-03 | 2026-10-20 | 앱은 컨테이너 없이 `uv run`으로 실행, PostgreSQL·Ollama만 docker compose | 개발 중 재시작이 빠르고, macOS에서 컨테이너 Ollama는 GPU를 못 씀 | 확정 |
| D-02 | 2026-10-20 | 모듈 간 데이터는 `contracts/`의 pydantic 모델로만 주고받고, 다른 모듈은 `interface.py`만 import | 1차 세 파트가 병렬로 개발해도 연결 지점이 어긋나지 않게. 나중에 서비스로 분리할 때 모델이 그대로 API 스키마가 됨 | 확정 |
| D-01 | 2026-10-20 | 단일 uv 프로젝트 + 모듈별 하위 패키지 (`src/weeing_weeing/<모듈>`) | `uv sync` 한 번으로 6명 환경이 같아짐. 서비스별 레포·pyproject는 3주 프로젝트에 관리 부담이 큼 | 확정 |

## 나중에 검토할 것

- **CI 설치 시간**: `sentence-transformers`가 Linux에서 CUDA용 torch(수 GB)를 받는다. Test 잡이 느려지면 torch를 직접 의존성으로 두고 Linux에서 CPU 전용 인덱스를 쓰도록 바꾼다(uv PyTorch 가이드 참고)
- **`uv_build` 버전 범위**: 설치된 uv(0.13.x)가 `uv_build<0.13`보다 새로워 경고가 난다. 동작에는 문제없고, 팀원 uv 버전이 맞춰지면 범위를 올린다

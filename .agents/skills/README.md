# 팀 공용 에이전트 스킬

**원본은 이 폴더(`.agents/skills/`)다.** 스킬은 여기서만 고친다.

| 도구 | 스킬을 찾는 위치 | 부르는 법 |
|---|---|---|
| Codex | `.agents/skills/` (이 폴더) | `$ww-setup` 또는 `/skills` 목록에서 선택 |
| Claude Code | `.claude/skills/` (자동 생성 사본) | `/ww-setup` |

Claude Code용 사본은 `scripts/sync_skills.py`가 만든다. Windows에서 깨질 수 있는 심볼릭 링크 대신 복사본을 커밋하고, CI의 `Skills sync` 검사와 pre-commit이 두 폴더가 같은지 확인한다.

```bash
# 원본을 고친 뒤
uv run --no-sync python scripts/sync_skills.py   # 또는 make skills
git add .agents/skills .claude/skills
```

## 스킬 목록

| 스킬 | 하는 일 |
|---|---|
| [`ww-setup`](ww-setup/SKILL.md) | 로컬 개발 환경 설치와 단계별 동작 확인 |
| [`ww-review-before-pr`](ww-review-before-pr/SKILL.md) | PR 전 셀프 리뷰: 깨끗한 환경 동작 + 프로젝트 규칙 점검 |
| [`ww-pr`](ww-pr/SKILL.md) | 규칙대로 커밋·push·PR 생성/갱신, merge 충돌·push 거절 등 꼬인 git 상태 해결, CI·자동 리뷰 확인 |
| [`ww-release`](ww-release/SKILL.md) | dev → main release 전 점검과 release PR 생성(merge commit으로 머지) |

## 권장 흐름

```
ww-setup                 처음 1회 (새 머신, 새 팀원)
   │
(개발 작업)
   │
ww-review-before-pr      PR 올리기 전
   │
ww-pr                    커밋·push·PR (→ dev)
   ⋮
ww-release               dev → main 반영 (담당자)
```

## 스킬을 고치거나 추가할 때

- 이름은 `ww-` 접두사를 붙인다(개인 전역 스킬과 이름이 겹치지 않게).
- `SKILL.md` 맨 위에 `name`과 `description`이 반드시 있어야 한다. 에이전트는 `description`을 보고 스킬을 고르므로 언제 쓰는지를 구체적으로 적는다.
- 특정 도구에만 있는 기능(예: 한 도구 전용 명령)에 기대지 않게 쓴다. 두 도구가 같은 파일을 읽는다.
- 스킬이 참조하는 문서(`docs/`)·명령(`Makefile`)이 바뀌면 스킬도 같은 PR에서 고친다.

# 작업 흐름: 이슈 → 브랜치 → PR → 머지

## 흐름

```
이슈 등록 → dev에서 브랜치 → 구현 + 테스트 → make check → PR(→ dev) → CI 통과 + 리뷰 1명 → 머지
                                                                   ⋮ (모아서)
                                                       release PR(dev → main)
```

`dev`가 기본 브랜치이자 모든 작업 PR의 대상이다. `main`은 release PR로만 바뀐다.

| 단계 | 규칙 |
|---|---|
| 이슈 | 이슈 템플릿(기능·버그·기타) 사용. 완료 조건을 적는다 |
| 브랜치 | 최신 `origin/dev`에서 만든다. 이름: `<종류>/<이슈번호>-<짧은설명>` 예: `feat/12-csv-replay` |
| 커밋 | `<종류>: <한국어 제목>`. 종류: `feat` `fix` `docs` `refactor` `test` `chore` `ci`. 성격이 다르면 커밋을 나눈다 |
| PR | base는 `dev`. 템플릿 4개 절(작업 내용·변경 사항·테스트 방법·관련 이슈) 채우기. `closes #N`으로 이슈 자동 종료 |
| 머지 조건 | CI(Lint·Test·Skills sync·Secret scan) 통과 + 팀원 1명 승인. 문서만 바꾼 PR은 Lint·Test가 skipped로 표시되며 통과로 본다 |
| 머지 방식 | 작업 PR(→ `dev`)은 Squash and merge (PR 하나당 커밋 하나). release PR(`dev` → `main`)은 **Create a merge commit** — squash하면 `main`에만 있는 커밋이 생겨 다음 release에서 충돌한다 |

- `main`·`dev`에 직접 push하지 않는다. 작업 PR을 `main`으로 올리지 않는다.
- PR은 작게 나눈다. 리뷰어가 15분 안에 읽을 수 있는 크기가 목표다.
- `contracts/`를 바꾸는 PR은 영향받는 모듈 담당자를 리뷰어로 지정한다.

## 건너뛰면 안 되는 것

- **CI는 검사가 다 붙은 뒤에 판단한다.** push 직후에는 검사가 아직 등록되지 않아 초록처럼 보일 수 있다
- **워크플로 파일(`.github/workflows/`)을 바꾼 PR은 자기 자신으로 검증되지 않는 경우가 있다.** 머지 뒤 다음 PR의 CI 기록으로 한 번 더 확인한다
- **"안 쓰는 것 같은" 코드를 지우기 전에 grep으로 쓰는 곳을 확인한다.** 다른 팀원의 진행 중 브랜치가 쓰고 있을 수 있다

## 여러 작업을 동시에 할 때 (git worktree)

브랜치를 오가며 미커밋 변경이 섞이지 않게, 작업마다 worktree를 따로 만든다.

```bash
git fetch origin
git worktree add .claude/worktrees/<이름> -b <브랜치> origin/dev
```

worktree에서는 `main`·`dev`를 checkout하지 않는다(한 브랜치는 한 worktree에서만 열 수 있음). `.claude/worktrees/`는 `.gitignore` 대상이다.

## release (dev → main)

`dev`에 모인 작업을 `main`에 반영한다. 담당자가 `ww-release` 스킬로 점검 후 PR을 올린다.

- `dev`의 CI가 통과한 상태에서만 올린다
- 머지 방식은 Create a merge commit (위 표 참고)
- 충돌이 나면 `dev`·`main`에서 직접 풀지 않고, `origin/dev`에서 브랜치를 만들어 `origin/main`을 merge한 뒤 `dev`로 PR을 올린다

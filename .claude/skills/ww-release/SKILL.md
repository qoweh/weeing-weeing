---
name: ww-release
description: weeing-weeing에서 dev에 모인 작업을 main에 반영(release)할 때 사용한다. "release PR 올려", "main에 반영", "dev를 main으로", "ww-release" 요청, release PR에서 충돌·CI 실패가 났을 때 쓴다. 일반 작업 PR은 ww-pr.
---

# ww-release — dev → main release PR

`dev`(기본 브랜치)에 머지된 작업을 `main`에 반영하는 PR을 점검하고 올린다. `main`은 이 PR로만 바뀐다.

| 파일 | 쓰는 때 |
|---|---|
| `scripts/release_check.py` | release 전 점검. `origin/dev`를 임시 worktree에 받아 검사하므로 작업 중인 파일과 무관하다 |

## 반드시 지킬 것

1. **release PR은 Create a merge commit으로 머지한다. Squash 금지.** squash하면 `main`에만 있는 커밋이 생겨 다음 release에서 충돌하고, 그 충돌을 풀려다 `uv.lock`이 깨진 적이 있다.
2. **`main`·`dev`에 직접 push하지 않는다.** 충돌도 `main`·`dev`에서 직접 풀지 않는다(아래 4).
3. **점검에서 ❌가 하나라도 있으면 PR을 올리지 않고** 문제와 고칠 방법을 보고한다. 고치는 일은 `dev`로 가는 별도 작업 PR(`ww-pr`)이다.
4. **머지는 사용자가 요청한 경우에만** 한다. 이 스킬을 부른 것은 PR 생성까지의 승인이다.

## 순서

### 1. 점검
```bash
python .agents/skills/ww-release/scripts/release_check.py
```
확인하는 것: 반영할 커밋·PR 목록, `main`에만 있는 커밋, dev → main merge 충돌, 충돌 표시, `uv.lock` 정합, 스킬 사본, 깨끗한 환경의 `ruff`·`pytest`, 이미 열린 release PR, 아직 `dev`로 열려 있는 PR.

- ⚠️ "main에만 있는 커밋"이 있어도 merge 충돌이 없으면 진행할 수 있다(이전 squash release 흔적). 보고에 적는다
- ⚠️ "dev로 열린 PR"은 이번 release에 안 들어간다. 기다릴지 사용자에게 묻는다

### 2. PR 본문 작성
`.github/pull_request_template.md`의 4개 절을 채운다.
- **작업 내용**: `release: dev → main (<YYYY-MM-DD>)`의 목적 한 줄
- **변경 사항**: 점검이 보여준 PR 목록을 `#번호 제목` 불릿으로. 사람이 알아야 할 것(의존성 변경, `contracts/` 변경, 환경변수 추가)은 따로 표시
- **테스트 방법**: 점검 결과(✅ 항목과 pytest 통과 수). 생략한 검사는 이유와 함께
- **관련 이슈**: 없으면 `-`

### 3. PR 생성 또는 갱신
```bash
gh pr create --base main --head dev --title "release: dev → main (<YYYY-MM-DD>)" --body-file <본문 파일>
```
이미 열린 release PR이 있으면 새로 만들지 말고 `gh pr edit <번호> --body-file <본문 파일>`.

### 4. 충돌이 났을 때
```bash
git fetch origin
git switch -c chore/sync-main-into-dev origin/dev
git merge origin/main          # 충돌은 ww-pr의 references/conflicts.md C절대로
make check
git push -u origin chore/sync-main-into-dev
gh pr create --base dev ...    # 이 PR이 dev에 머지되면 release PR의 충돌이 사라진다
```

### 5. CI 확인
```bash
gh pr checks <번호>        # Lint·Test·Skills sync·Secret scan이 모두 보일 때 판단
```

### 6. 머지 (사용자가 요청했을 때만)
```bash
gh pr merge <번호> --merge     # --squash·--rebase 금지
git fetch origin
git rev-list --count origin/main..origin/dev   # 0이어야 한다
```
머지 후 `main` push로 CI가 한 번 더 돈다. `gh run list --branch main --limit 1`로 결과를 확인한다.

## 보고

PR 링크, 포함된 PR 목록, 점검 결과(✅·⚠️·❌), CI 결과, 머지했다면 머지 방식과 머지 후 `main` CI 결과를 짧게 보고한다. 실패는 숨기지 않는다.

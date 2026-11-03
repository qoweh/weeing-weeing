# 꼬인 상황별 해결법

`ww_git.py diagnose`가 알려준 글자(A~L)의 절만 읽으면 된다. 모든 절의 공통 원칙:

- **되돌릴 수 있게 먼저 백업한다.** `git branch backup/<브랜치>-<시각>` (`sync`는 자동으로 만든다)
- **지우는 명령은 사용자 확인 후에만**: `reset --hard`, `checkout -- .`, `restore .`, `clean -fd`, `stash drop`, `branch -D`, `push --force`
- **다른 팀원의 코드를 이해하지 못하면 지우지 않고 묻는다.** `sync` 출력의 "바꾼 사람"이 물어볼 사람이다
- 아래에서 `<base>`는 `diagnose`가 보여준 base 브랜치(지금은 `dev`)다

## 충돌 표시 읽는 법

```text
  <<<<<<< HEAD
  내 브랜치의 내용
  =======
  base(origin/dev)의 내용 — 다른 팀원이 먼저 머지한 것
  >>>>>>> origin/dev
```

(실제 파일에서는 줄 맨 앞에 붙어 있다. 이 예시는 검사에 걸리지 않게 들여 썼다.)
세 줄짜리 표시(`<<<<<<<`, `=======`, `>>>>>>>`)를 **모두** 지우고, 그 사이를 올바른 최종 내용으로 바꾼다. 하나라도 남으면 I번 상황이 된다(실제로 `.gitignore`에 `=======` 한 줄이 남아 커밋된 적이 있다).

---

## A. `main`·`dev`에서 작업했다

| 상태 | 해결 |
|---|---|
| 커밋 안 함 | `git switch -c <종류>/<이슈>-<설명>` — 변경이 새 브랜치로 그대로 따라온다 |
| 로컬에 커밋함, push 안 함 | ① `git switch -c <새 브랜치>` (커밋이 새 브랜치에 남음) ② 사용자 확인 후 `git switch dev && git reset --hard origin/dev` ③ `git switch <새 브랜치>` |
| 이미 `dev`·`main`에 push함 | **혼자 되돌리지 않는다.** 다른 팀원이 그 위에 작업했을 수 있다. 사용자에게 알리고 팀에 공유하도록 한다 |

## B. "Your local changes would be overwritten" (switch·pull이 막힘)

커밋 안 한 변경이 있어서다. 지우지 말고 보존한다.

1. 작업 브랜치에 있으면 **커밋**(권장): `git add <파일들> && git commit -m "<종류>: 작업 중"`
2. 커밋하기 애매하면: `git stash push -u -m "<설명>"` → 일을 마친 뒤 `git stash pop`
3. `stash pop`에서 충돌이 나도 stash는 사라지지 않는다(`git stash list`). C 순서로 해결한 뒤 사용자 확인 후 `git stash drop`

## C. merge 충돌 해결 (가장 흔함)

`sync`가 충돌 파일과 처리 방법을 알려준다. 파일마다:

1. 양쪽이 **무엇을 왜** 바꿨는지 본다
   ```bash
   git diff <파일>                                    # 충돌 부분
   git log --oneline -3 HEAD -- <파일>                # 내 쪽 변경
   git log --oneline -3 MERGE_HEAD -- <파일>          # base 쪽 변경
   ```
2. 결정한다
   - 서로 다른 것을 추가했다(import 두 줄, 함수 두 개, 설정 항목 두 개) → **둘 다 남긴다**
   - 같은 줄을 다르게 고쳤다 → 의도가 분명하면 합치고, 아니면 **"바꾼 사람"에게 묻는다**
   - 한쪽이 지웠고 한쪽이 고쳤다(`deleted by them/us`) → 사용자에게 묻는다
3. 표시를 지우고 저장 → `git add <파일>`
4. 모든 파일이 끝나면
   ```bash
   uv run --no-sync python .agents/skills/ww-pr/scripts/ww_git.py markers   # 0줄이어야 함
   make check                                              # 합친 결과가 실제로 도는지
   git commit --no-edit                                    # merge 커밋 완료
   ```

**하지 않는 것**: 코드 파일 전체를 `git checkout --ours/--theirs`로 한쪽만 고르기(상대 작업이 통째로 사라진다), 테스트가 깨진 채 커밋하기.

### C-1. `uv.lock` 충돌

`uv.lock`은 손으로 합치지 않는다.

```bash
# 1) pyproject.toml 충돌을 먼저 해결 (양쪽 의존성 모두 남기기)
git checkout --theirs uv.lock        # base 쪽 lock에서 시작
uv lock                              # pyproject.toml 기준으로 다시 계산
uv sync --locked --no-install-project
git add pyproject.toml uv.lock
```

`uv lock`이 `Failed to parse uv.lock`으로 실패하면 base의 lock이 이미 깨진 것이다(손으로 합친 lock이 머지된 경우). 내 PR에서 고치지 말고 사용자에게 알려 base를 고치는 별도 PR을 먼저 올리게 한다.

### C-2. `.claude/skills/` 충돌

사본이다. 원본 `.agents/skills/`의 충돌만 해결한 뒤 `make skills`로 다시 만들고 둘 다 `git add`.

### C-3. 같은 파일을 둘이 새로 만들었다 (`both added`)

내용을 비교해 하나로 합친다. 목적이 다른 파일이면 한쪽 이름을 바꾸는 것을 사용자에게 제안한다.

### C-4. 데이터·바이너리 파일 (`data/`, csv, pdf, 이미지)

줄 단위로 합칠 수 없다. 어느 쪽을 쓸지 **사용자에게 확인한 뒤**:
```bash
git checkout --ours -- <파일>     # 내 것
git checkout --theirs -- <파일>   # base 것
git add <파일>
```

## D. 충돌 해결이 꼬였다 / 처음부터 다시 하고 싶다

| 시점 | 명령 |
|---|---|
| merge 커밋 전 | `git merge --abort` → 원래 상태로 돌아간다 |
| merge 커밋 후, push 전 | 사용자 확인 후 `git reset --hard backup/<브랜치>-<시각>` |
| push 후 | 되돌리지 않는다. 잘못된 부분을 고치는 새 커밋을 만든다 |

## E. push가 거절됐다 (`rejected`, `non-fast-forward`, `fetch first`)

원격 브랜치에 내 로컬에 없는 커밋이 있다(GitHub 웹에서 충돌 해결, 다른 컴퓨터, 같이 작업하는 팀원).

```bash
git pull --no-rebase origin <내 브랜치>   # 합치기. 충돌 나면 C
git push
```

**`git push --force` 금지.** 그 커밋들이 사라진다.

## F. base에 새 커밋이 있다 / GitHub에 "This branch has conflicts"

```bash
uv run --no-sync python .agents/skills/ww-pr/scripts/ww_git.py sync
```
충돌이 나면 C. 끝나면 `make check` → `git push`. PR은 자동으로 갱신된다.
GitHub 웹 편집기로도 풀 수 있지만 테스트를 못 돌리므로 로컬에서 푼다.

**rebase가 아니라 merge를 쓰는 이유**: PR은 Squash and merge로 커밋 하나가 되므로 브랜치 이력이 깔끔할 필요가 없다. rebase는 이미 push한 브랜치에 force push를 요구한다.

## G. PR base가 틀렸다 (`main`으로 올림 등)

```bash
gh pr edit <번호> --base <base>
git log --oneline origin/<base>..HEAD     # 내 커밋만 보여야 한다
```
남의 커밋이 섞여 보이면(엉뚱한 브랜치에서 시작함): `origin/<base>`에서 새 브랜치를 만들고 내 커밋만 `git cherry-pick <해시>...` 한 뒤 새 PR을 올리고 이전 PR은 닫는다(사용자 확인).

## H. `dev` → `main` 반영 PR에서 충돌

`main`에 직접 머지된 PR이 있으면 생긴다. `dev`·`main`에서 직접 풀지 않는다.

```bash
git switch -c chore/sync-main-into-dev origin/dev
git merge origin/main                     # 충돌은 C 순서로
git push -u origin chore/sync-main-into-dev
gh pr create --base dev ...
```
이 PR이 `dev`에 머지되면 반영 PR의 충돌이 사라진다.

## I. 충돌 표시가 남아 있다 / 이미 커밋됐다

```bash
uv run --no-sync python .agents/skills/ww-pr/scripts/ww_git.py markers          # 이 브랜치 변경분
uv run --no-sync python .agents/skills/ww-pr/scripts/ww_git.py markers --all    # 저장소 전체
```
표시 줄과 그 사이 내용을 올바르게 정리하고 `fix: 남은 충돌 표시 제거`로 커밋한다. 표시 사이 내용이 둘 다 필요한지 꼭 확인한다(중복된 설정이면 하나만).

## J. rebase 중에 멈췄다 (`rebase in progress`)

`git pull`이 rebase로 설정돼 있으면 생긴다. 이 팀은 merge 방식을 쓴다.
```bash
git rebase --abort
git config pull.rebase false              # 이 저장소에서 pull을 merge로
```
그 다음 F 또는 E.

## K. detached HEAD (브랜치가 아닌 커밋 위)

```bash
git switch -c <종류>/<이슈>-<설명>         # 지금 커밋에서 브랜치를 만든다
```

## L. 올리면 안 되는 파일(`.env`, 키)을 커밋했다

| 시점 | 해결 |
|---|---|
| push 전 | `git rm --cached <파일>` → `.gitignore` 확인 → `git commit --amend` |
| push 후 | 키가 이미 노출된 것으로 본다. **즉시 사용자에게 알리고 키를 폐기·재발급**하도록 한다. 이력 삭제는 혼자 하지 않는다 |

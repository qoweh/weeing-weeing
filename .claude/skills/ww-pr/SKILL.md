---
name: ww-pr
description: weeing-weeing에서 커밋·push·PR 생성/갱신을 할 때, 그리고 git이 꼬였을 때 사용한다. "PR 올려", "PR 만들어", "push해", "ww-pr" 요청, merge conflict·충돌, "This branch has conflicts", push rejected·non-fast-forward, pull·switch가 막힘, dev·main에서 잘못 작업함, 충돌 표시(<<<<<<<)가 남음, rebase in progress 같은 상황에 쓴다.
---

# ww-pr — 커밋·push·PR (충돌 해결 포함)

git에 익숙하지 않은 팀원도 같은 순서로 안전하게 PR을 올리게 한다. **상태 진단 → 브랜치·커밋 → base 반영(충돌 해결) → 검사 → push → PR** 순서로 하고, 순서를 건너뛰지 않는다.

| 파일 | 쓰는 때 |
|---|---|
| `scripts/ww_git.py` | 상태 진단(`diagnose`), base 반영(`sync`), 충돌 표시 검사(`markers`) |
| `references/conflicts.md` | `diagnose`·`sync`가 알려준 글자(A~L)의 절만 읽는다 |

명령은 저장소 루트에서 `uv run --no-sync python .agents/skills/ww-pr/scripts/ww_git.py <명령>`으로 실행한다(팀 규칙대로 uv의 Python 3.12를 쓴다. 시스템 `python3`는 버전이 달라 쓰지 않는다).

## 반드시 지킬 것

1. **이 스킬을 부른 것 자체가 작업 브랜치 push 승인이다.** 그 외 상황에서는 커밋까지만 하고 보고한다.
2. **`main`·`dev`에는 push하지 않는다.** PR 머지도 하지 않는다(팀원 1명 승인 후 사람이 Squash and merge).
3. **stage는 경로를 적어서만 한다.** `git add -A`, `git add .` 금지.
4. **커밋하지 않는 것**: `.env`, `.env.*`(`.env.example` 제외), `storage/`, `.venv/`, `.omc/`, `.claude/worktrees/`, API 키·개인정보.
5. **작업을 지울 수 있는 명령은 사용자 확인 후에만**: `push --force`, `reset --hard`, `checkout -- .`, `restore .`, `clean -fd`, `stash drop`, `branch -D`. 확인을 받아도 `push --force`는 쓰지 않는다.
6. **충돌은 양쪽을 읽고 합친다.** 다른 팀원의 변경을 이해하지 못하면 지우지 말고 사용자에게 묻는다. 코드 파일을 `--ours`/`--theirs`로 통째 고르지 않는다.
7. **충돌 표시 0줄 + `make check` 통과 전에는 merge 커밋·push를 하지 않는다.**

## 순서

### 0. 진단
```bash
uv run --no-sync python .agents/skills/ww-pr/scripts/ww_git.py diagnose
```
`[A]`~`[L]`이 나오면 `references/conflicts.md`의 그 절을 먼저 처리하고 다시 진단한다. "PR 진행 가능"이 나와야 다음 단계로 간다. base 브랜치도 여기서 확인한다(GitHub 기본 브랜치, 지금은 `dev`).

### 1. 브랜치
새 작업이면 `git fetch origin && git switch -c <종류>/<이슈번호>-<짧은설명> origin/<base>`.
종류: `feat` `fix` `docs` `refactor` `test` `chore` `ci`. worktree에서는 `main`·`dev`를 checkout하지 않는다.

### 2. stage와 커밋
```bash
git add <파일1> <파일2> ...
git status --short          # 무관한 파일이 섞이지 않았는지
git diff --cached --stat
git commit -m "<종류>: <한국어 제목>" -m "<무엇을 왜 - 불릿>"
```
성격이 다르면 커밋을 나눈다. 커밋 끝에는 사용 중인 에이전트 규칙에 따른 공동 작성자 트레일러를 붙인다.

### 3. base 반영 (충돌은 여기서 푼다)
```bash
uv run --no-sync python .agents/skills/ww-pr/scripts/ww_git.py sync
```
백업 브랜치를 만들고 `origin/<base>`를 merge한다. rebase는 쓰지 않는다(force push가 필요해지므로).
- 종료 코드 0: 충돌 없음 → 4단계
- 1: 충돌. 출력된 파일별 처리 방법과 `conflicts.md`의 C절대로 하나씩 해결한다. 판단이 필요한 파일은 "바꾼 사람"과 양쪽 내용을 사용자에게 보여 주고 묻는다
- 2: 진행 전 정리할 상태. 출력대로 처리한다

### 4. 검사
```bash
uv run --no-sync python .agents/skills/ww-pr/scripts/ww_git.py markers   # 0줄
make check
```
`ww-review-before-pr`를 통과했는지 확인한다. 안 했으면 먼저 하자고 제안한다.

### 5. push
```bash
git push -u origin <브랜치>
```
거절되면 force하지 말고 `conflicts.md`의 E.

### 6. PR 생성 또는 갱신
이미 PR이 있으면(`gh pr view --json number,url,baseRefName`) base가 맞는지 보고, 본문의 '변경 사항'·'테스트 방법'만 고친다(`gh pr edit --body-file`).

없으면 `.github/pull_request_template.md`의 4개 절을 채워 만든다.
```bash
gh pr create --base <base> --title "<종류>: <제목>" --body-file <본문 파일>
```
- **작업 내용**: 무엇을 왜, 1~3문장
- **변경 사항**: 모듈·파일 단위. `contracts/`를 바꿨으면 영향 모듈과 담당자. 충돌을 풀었으면 어느 파일을 어떻게 합쳤는지
- **테스트 방법**: 실제로 실행한 명령과 결과. 실행하지 못한 검사는 이유와 함께 체크하지 않은 채로
- **관련 이슈**: `closes #N`

### 7. 결과 확인
```bash
gh pr checks <번호>
gh pr view <번호> --json mergeable          # CONFLICTING이면 3단계부터 다시
gh api repos/{owner}/{repo}/pulls/<번호>/comments --jq '.[] | "\(.path):\(.line) \(.body[0:300])"'
```
- 검사가 아직 등록되지 않은 상태의 "통과"를 믿지 않는다. Lint·Test·Skills sync·Secret scan이 모두 보일 때 판단한다.
- 자동 리뷰(Codex) 지적은 맞는지 직접 확인한 뒤 고친다. 새 커밋 뒤 재리뷰가 필요하면 PR에 `@codex review` 댓글을 단다.

## 이런 생각이 들면 멈춘다

| 생각 | 실제 |
|---|---|
| "force push 한 번이면 깔끔해진다" | 원격에만 있던 커밋(웹에서 푼 충돌, 팀원 커밋)이 사라진다. `conflicts.md` E |
| "충돌 난 쪽은 내 것으로 덮으면 된다" | 먼저 머지된 팀원 작업이 조용히 사라진다. 리뷰에서도 잘 안 보인다 |
| "표시만 지우면 끝" | `=======` 한 줄이 남아 커밋된 적이 있다. `markers`로 확인한다 |
| "충돌만 풀었으니 테스트는 생략" | 양쪽이 각각 맞아도 합친 결과는 깨질 수 있다. `make check` |
| "꼬였으니 reset --hard로 처음부터" | 미커밋 변경이 사라진다. `merge --abort` 또는 백업 브랜치로(`conflicts.md` D) |

## 보고

PR 링크, 커밋 목록, 충돌이 있었다면 파일별 해결 방법과 물어본 사항, 검사 결과(통과·실패·대기), 자동 리뷰 지적과 처리 여부, 남은 백업 브랜치(`backup/...`, 확인 후 `git branch -D`로 정리 가능)를 짧게 보고한다. 실패는 숨기지 않는다.

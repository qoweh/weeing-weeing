---
name: ww-pr
description: weeing-weeing 규칙(docs/CHANGE_WORKFLOW.md)대로 커밋·push하고 PR을 만들거나 갱신한 뒤 CI와 자동 리뷰 결과를 확인한다. "PR 올려", "PR 만들어", "push해", "ww-pr" 요청에 사용. main·dev에는 직접 push하지 않는다.
---

# ww-pr — 커밋·push·PR

## 반드시 지킬 것

1. **이 스킬을 부른 것 자체가 작업 브랜치 push 승인이다.** 그 외 상황에서는 커밋까지만 하고 보고한다.
2. **`main`·`dev`에는 push하지 않는다.** push 직전 `git rev-parse --abbrev-ref HEAD`가 `main`·`dev`면 중단하고 브랜치부터 만든다.
3. **stage는 경로를 적어서만 한다.** `git add -A`, `git add .` 금지. stage 후 `git status --short`로 무관한 파일이 섞이지 않았는지 본다.
4. **커밋하지 않는 것**: `.env`, `.env.*`(`.env.example` 제외), `storage/`, `.venv/`, `.omc/`, `.claude/worktrees/`, API 키·개인정보.
5. PR 전에 `ww-review-before-pr`를 통과했는지 확인한다. 안 했으면 먼저 하자고 제안한다.

## 순서

### 1. 브랜치
```bash
git rev-parse --abbrev-ref HEAD
# 새 작업이면 최신 main에서:
git fetch origin && git switch -c <종류>/<이슈번호>-<짧은설명> origin/main
```
종류: `feat` `fix` `docs` `refactor` `test` `chore` `ci`. worktree에서는 `main`·`dev`를 checkout하지 않는다.

### 2. stage와 커밋
```bash
git add <파일1> <파일2> ...
git status --short
git diff --cached --stat
git commit -m "<종류>: <한국어 제목>" -m "<무엇을 왜 - 불릿>"
```
- 성격이 다르면 커밋을 나눈다(예: 로직 `fix:`와 문서 `docs:`).
- 커밋 끝에는 사용 중인 에이전트 규칙에 따른 공동 작성자 트레일러를 붙인다.

### 3. push
```bash
git fetch origin
git rev-list --left-right --count origin/main...HEAD   # 뒤처졌으면 사용자에게 rebase/merge 여부를 묻는다
git push -u origin <브랜치>
```

### 4. PR 생성 또는 갱신
이미 PR이 있으면(`gh pr view --json number,url`) 본문의 '변경 사항'·'테스트 방법'만 새 내용에 맞게 고친다(`gh pr edit --body-file`).

없으면 `.github/pull_request_template.md`의 4개 절을 채워 만든다.
```bash
gh pr create --base main --title "<종류>: <제목>" --body-file <본문 파일>
```
- **작업 내용**: 무엇을 왜, 1~3문장
- **변경 사항**: 모듈·파일 단위. `contracts/`를 바꿨으면 영향 모듈과 담당자
- **테스트 방법**: 실제로 실행한 명령과 결과. 실행하지 못한 검사는 이유와 함께 체크하지 않은 채로
- **관련 이슈**: `closes #N`

### 5. 결과 확인
```bash
gh pr checks <번호>                                        # Lint·Test·Secret scan
gh api repos/{owner}/{repo}/pulls/<번호>/comments --jq '.[] | "\(.path):\(.line) \(.body[0:300])"'
```
- 검사가 아직 등록되지 않은 상태의 "통과"를 믿지 않는다. 세 검사가 모두 보일 때 판단한다.
- 자동 리뷰(Codex) 지적은 맞는지 직접 확인한 뒤 고친다. 새 커밋 뒤 재리뷰가 필요하면 PR에 `@codex review` 댓글을 단다.
- 머지는 하지 않는다. 팀원 1명 승인 후 사람이 Squash and merge 한다.

## 보고

PR 링크, 커밋 목록, 검사 결과(통과·실패·대기), 자동 리뷰 지적과 처리 여부를 짧게 보고한다. 실패는 숨기지 않는다.

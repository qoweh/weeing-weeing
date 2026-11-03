"""ww-pr 보조 스크립트: git 상태 진단, base 브랜치 반영, 충돌 표시 검사.

git에 익숙하지 않은 팀원도 같은 순서로 안전하게 PR을 올리도록, 위험한 상황을 먼저 찾아
references/conflicts.md의 해당 절을 알려준다. 표준 라이브러리만 쓴다(어느 환경에서든 실행).

    uv run --no-sync python .agents/skills/ww-pr/scripts/ww_git.py diagnose   # 지금 상태와 다음 할 일
    uv run --no-sync python .agents/skills/ww-pr/scripts/ww_git.py sync       # 백업 후 origin/<base>를 merge
    uv run --no-sync python .agents/skills/ww-pr/scripts/ww_git.py markers    # 남은 충돌 표시(<<<<<<< 등) 검사

base 브랜치는 WW_BASE 환경변수 → GitHub 기본 브랜치 → dev 순서로 정한다.
종료 코드: 0 정상, 1 충돌·충돌 표시 발견, 2 진행 전에 사람이 정리해야 할 상태.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROTECTED = {"main", "dev"}
FALLBACK_BASE = "dev"
TIMEOUT = 30  # fetch·gh 호출이 네트워크 문제로 멈추지 않게
MARKER = re.compile(r"^(<{7}( |$)|={7}$|>{7}( |$)|\|{7}( |$))")
GUIDE = "references/conflicts.md"
# 줄 단위로 합칠 수 없는 파일. 한쪽을 골라야 한다.
DATA_EXT = (".csv", ".pdf", ".png", ".jpg", ".jpeg", ".xlsx", ".ipynb", ".parquet")


def run(*args: str, timeout: int = TIMEOUT) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(args, 124, "", str(e))


def git(*args: str) -> str:
    return run("git", *args).stdout.strip()


def git_ok(*args: str) -> bool:
    return run("git", *args).returncode == 0


def base_branch() -> str:
    if os.environ.get("WW_BASE"):
        return os.environ["WW_BASE"]
    r = run(
        "gh",
        "repo",
        "view",
        "--json",
        "defaultBranchRef",
        "-q",
        ".defaultBranchRef.name",
    )
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else FALLBACK_BASE


def current_branch() -> str | None:
    name = git("symbolic-ref", "--quiet", "--short", "HEAD")
    return name or None


def in_progress() -> str | None:
    """끝나지 않은 merge·rebase·cherry-pick이 있으면 그 이름."""
    for path, name in [
        ("MERGE_HEAD", "merge"),
        ("rebase-merge", "rebase"),
        ("rebase-apply", "rebase"),
        ("CHERRY_PICK_HEAD", "cherry-pick"),
        ("REVERT_HEAD", "revert"),
    ]:
        if Path(git("rev-parse", "--git-path", path)).exists():
            return name
    return None


def unmerged_files() -> list[str]:
    return [f for f in git("diff", "--name-only", "--diff-filter=U").splitlines() if f]


def fetch() -> bool:
    return run("git", "fetch", "--quiet", "origin").returncode == 0


def counts(left: str, right: str) -> tuple[int, int] | None:
    """(left에만 있는 커밋 수, right에만 있는 커밋 수)."""
    out = git("rev-list", "--left-right", "--count", f"{left}...{right}")
    if not out:
        return None
    a, b = out.split()
    return int(a), int(b)


def find_markers(files: list[str]) -> list[str]:
    hits = []
    for f in files:
        p = Path(f)
        if not p.is_file():
            continue
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue  # 바이너리는 건너뛴다
        hits += [
            f"{f}:{i}: {line}" for i, line in enumerate(lines, 1) if MARKER.match(line)
        ]
    return hits


def changed_files(base: str) -> list[str]:
    """이 브랜치가 base 대비 바꾼 파일 + 아직 커밋 안 한 파일."""
    names = set(git("diff", "--name-only", f"origin/{base}...HEAD").splitlines())
    names |= set(git("diff", "--name-only", "HEAD").splitlines())
    return sorted(n for n in names if n)


def hint(path: str) -> str:
    if path == "uv.lock":
        return "직접 고치지 말 것 → C-1 (pyproject.toml 먼저 해결 후 uv lock)"
    if path.startswith(".claude/skills/"):
        return "사본 → C-2 (.agents/skills 해결 후 make skills)"
    if path.startswith("data/") or path.endswith(DATA_EXT):
        return "데이터·바이너리일 수 있음 → C-4 (한쪽 선택, 사용자 확인)"
    return "양쪽 내용을 읽고 합치기 → C"


def sides(path: str) -> str:
    """충돌 파일을 양쪽에서 누가 바꿨는지(누구에게 물어볼지)."""
    out = git("log", "--format=%an: %s", "-3", "HEAD...MERGE_HEAD", "--", path)
    return "; ".join(out.splitlines()) or "-"


def report(code: str, msg: str) -> None:
    print(f"  [{code}] {msg}  → {GUIDE} 의 '{code}'")


def cmd_diagnose(_: argparse.Namespace) -> int:
    base = base_branch()
    branch = current_branch()
    fetched = fetch()
    problems = 0

    print(f"base 브랜치: {base}   현재 브랜치: {branch or '(detached HEAD)'}")
    if not fetched:
        print(
            "  ! git fetch 실패 — 네트워크·인증 확인. 아래 비교는 오래된 정보일 수 있음"
        )

    op = in_progress()
    if op:
        problems += 1
        files = unmerged_files()
        code = "J" if op == "rebase" else "C"
        report(code, f"{op} 작업이 끝나지 않은 상태. 충돌 파일 {len(files)}개")
        for f in files:
            print(f"      - {f}  ({hint(f)})")
    if branch is None:
        problems += 1
        report("K", "브랜치가 아닌 커밋 위에 있음(detached HEAD)")
    elif branch in PROTECTED:
        problems += 1
        report("A", f"{branch}에서 작업 중. 작업 브랜치로 옮겨야 push 가능")

    dirty = [line for line in git("status", "--porcelain").splitlines() if line]
    if dirty and not op:
        print(f"  · 커밋 안 한 변경 {len(dirty)}개 (커밋 대상인지 사용자와 확인)")

    if branch and branch not in PROTECTED:
        c = counts(f"origin/{base}", "HEAD")
        if c:
            behind, ahead = c
            print(f"  · origin/{base}보다 {ahead}개 앞, {behind}개 뒤")
            if behind:
                report("F", f"base에 새 커밋 {behind}개. sync로 반영 후 push")
        if git_ok("rev-parse", "--verify", "--quiet", f"origin/{branch}"):
            c = counts(f"origin/{branch}", "HEAD")
            if c and c[0]:
                problems += 1
                report(
                    "E", f"원격 {branch}에 내 로컬에 없는 커밋 {c[0]}개 (push가 거절됨)"
                )

    hits = find_markers(changed_files(base)) if branch else []
    if hits:
        problems += 1
        report("I", f"충돌 표시가 남은 줄 {len(hits)}개")
        for h in hits[:20]:
            print(f"      {h}")

    pr = run("gh", "pr", "view", "--json", "number,url,baseRefName,mergeable")
    if pr.returncode == 0:
        info = json.loads(pr.stdout)
        print(f"  · PR #{info['number']} {info['url']} (base: {info['baseRefName']})")
        if info["baseRefName"] != base:
            report("G", f"PR base가 {base}가 아님")
        if info["mergeable"] == "CONFLICTING":
            report("F", "GitHub에서 충돌 상태(This branch has conflicts)")
    else:
        print("  · 이 브랜치의 PR 없음")

    print("결과:", "정리할 것 있음" if problems else "PR 진행 가능")
    return 2 if problems else 0


def cmd_sync(_: argparse.Namespace) -> int:
    base = base_branch()
    branch = current_branch()
    if branch is None or branch in PROTECTED:
        print(f"중단: 작업 브랜치가 아님({branch}). {GUIDE} 의 'A'/'K' 먼저")
        return 2
    if in_progress():
        print(f"중단: 끝나지 않은 {in_progress()} 작업이 있음. diagnose 결과를 따른다")
        return 2
    if git("status", "--porcelain", "--untracked-files=no"):
        print("중단: 커밋 안 한 변경이 있음. 커밋하거나(권장) 사용자 확인 후 stash")
        return 2
    if not fetch():
        print("중단: git fetch 실패 — 네트워크·인증 확인")
        return 2

    backup = f"backup/{branch}-{datetime.now():%Y%m%d-%H%M%S}"
    git("branch", backup)
    print(f"백업 브랜치: {backup}  (로컬 전용, push하지 않음)")

    r = run("git", "merge", "--no-edit", f"origin/{base}")
    files = unmerged_files()
    if r.returncode == 0 and not files:
        hits = find_markers(changed_files(base))
        if hits:
            print("merge는 됐지만 충돌 표시가 남아 있음:", *hits, sep="\n  ")
            return 1
        print(f"origin/{base} 반영 완료(충돌 없음). make check 후 push")
        return 0
    if not files:
        print("merge 실패(충돌 아님):", r.stdout, r.stderr, sep="\n")
        git("merge", "--abort")
        return 2

    print(f"충돌 {len(files)}개. {GUIDE} 의 'C' 순서로 하나씩 해결:")
    for f in files:
        print(f"  - {f}\n      처리: {hint(f)}\n      바꾼 사람: {sides(f)}")
    print("포기하고 원래대로: git merge --abort")
    return 1


def cmd_markers(args: argparse.Namespace) -> int:
    files = git("ls-files").splitlines() if args.all else changed_files(base_branch())
    hits = find_markers(files)
    for h in hits:
        print(h)
    print(f"충돌 표시 {len(hits)}줄" if hits else "충돌 표시 없음")
    return 1 if hits else 0


def main() -> int:
    root = git("rev-parse", "--show-toplevel")
    if not root:
        print("git 저장소 안에서 실행해야 한다")
        return 2
    os.chdir(root)
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("diagnose").set_defaults(fn=cmd_diagnose)
    sub.add_parser("sync").set_defaults(fn=cmd_sync)
    m = sub.add_parser("markers")
    m.add_argument(
        "--all", action="store_true", help="브랜치 변경분이 아닌 전체 파일 검사"
    )
    m.set_defaults(fn=cmd_markers)
    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

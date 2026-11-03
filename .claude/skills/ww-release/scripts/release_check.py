"""release(dev → main) 전 점검. 표준 라이브러리만 쓴다.

    uv run --no-sync python .agents/skills/ww-release/scripts/release_check.py            # 전체 점검
    uv run --no-sync python .agents/skills/ww-release/scripts/release_check.py --no-tests # 테스트 생략

origin/dev를 깨끗한 임시 worktree에 받아 검사하므로 지금 작업 중인 파일과 무관하다.
종료 코드: 0 release 가능, 1 막는 문제 있음, 2 실행 불가(네트워크·git).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

DEV, MAIN = "origin/dev", "origin/main"
TIMEOUT = 60
TEST_TIMEOUT = 900
MARKER = r"^(<{7}( |$)|={7}$|>{7}( |$))"


def run(*args: str, cwd: str | None = None, timeout: int = TIMEOUT, env=None):
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(args, 124, "", str(e))


def git(*args: str) -> str:
    return run("git", *args).stdout.strip()


class Report:
    def __init__(self) -> None:
        self.blockers = 0

    def ok(self, msg: str) -> None:
        print(f"  ✅ {msg}")

    def warn(self, msg: str) -> None:
        print(f"  ⚠️  {msg}")

    def fail(self, msg: str) -> None:
        self.blockers += 1
        print(f"  ❌ {msg}")


def check_history(r: Report, dev: str) -> None:
    pending = git("log", "--format=%h %s", f"{MAIN}..{dev}").splitlines()
    if not pending:
        r.fail("dev에 main보다 새 커밋이 없음 — release할 것이 없다")
    else:
        prs = sorted({int(n) for n in re.findall(r"\(#(\d+)\)", "\n".join(pending))})
        r.ok(
            f"반영할 커밋 {len(pending)}개, PR {', '.join(f'#{n}' for n in prs) or '-'}"
        )

    only_main = git("log", "--format=%h %s", f"{dev}..{MAIN}").splitlines()
    if only_main:
        r.warn(
            f"main에만 있는 커밋 {len(only_main)}개 (squash release·main 직접 머지 흔적): "
            + "; ".join(only_main[:5])
        )

    res = run("git", "merge-tree", "--write-tree", "--name-only", MAIN, dev)
    if res.returncode == 0:
        r.ok("dev → main merge 충돌 없음")
    elif res.returncode == 1:
        # 출력: 첫 줄 tree id, 빈 줄까지 충돌 파일 이름, 그 뒤 설명
        lines = res.stdout.splitlines()[1:]
        files = lines[: lines.index("")] if "" in lines else lines
        r.fail(f"dev → main merge 충돌: {', '.join(files) or res.stdout[:300]}")
    else:
        r.warn(f"충돌 사전 검사 실패(git 2.38+ 필요): {res.stderr.strip()[:200]}")


def check_tree(r: Report, tree: str, tests: bool) -> None:
    hits = run("git", "grep", "-nE", MARKER, "--", ".", cwd=tree).stdout.strip()
    if hits:
        r.fail("충돌 표시가 남은 줄:\n      " + hits.replace("\n", "\n      "))
    else:
        r.ok("충돌 표시 없음")

    lock = run("uv", "lock", "--check", cwd=tree)
    if lock.returncode == 0:
        r.ok("uv.lock이 pyproject.toml과 일치")
    else:
        r.fail(f"uv lock --check 실패: {lock.stderr.strip().splitlines()[-1:]}")
        return  # lock이 깨지면 설치·테스트도 불가

    sync = run("python3", "scripts/sync_skills.py", "--check", cwd=tree)
    (r.ok if sync.returncode == 0 else r.fail)("스킬 사본 동기화")

    if not tests:
        r.warn("테스트 생략(--no-tests) — release PR의 CI 결과로 확인할 것")
        return
    env = {**os.environ, "UV_PROJECT_ENVIRONMENT": f"{tree}/.venv"}
    env.pop("VIRTUAL_ENV", None)
    inst = run(
        "uv",
        "sync",
        "--locked",
        "--no-install-project",
        cwd=tree,
        env=env,
        timeout=TEST_TIMEOUT,
    )
    if inst.returncode != 0:
        r.fail(f"uv sync 실패: {inst.stderr.strip()[-300:]}")
        return
    for name, cmd in [
        ("ruff check", ["ruff", "check", "."]),
        ("ruff format", ["ruff", "format", "--check", "."]),
        ("pytest", ["pytest"]),
    ]:
        res = run(
            "uv", "run", "--no-sync", *cmd, cwd=tree, env=env, timeout=TEST_TIMEOUT
        )
        tail = (res.stdout + res.stderr).strip().splitlines()[-1:]
        (r.ok if res.returncode == 0 else r.fail)(f"{name}: {' '.join(tail)}")


def check_github(r: Report) -> None:
    res = run(
        "gh",
        "pr",
        "list",
        "--base",
        "main",
        "--head",
        "dev",
        "--state",
        "open",
        "--json",
        "number,url",
    )
    if res.returncode != 0:
        r.warn("gh로 열린 release PR을 확인하지 못함(gh auth status 확인)")
        return
    prs = json.loads(res.stdout or "[]")
    if prs:
        r.warn(f"이미 열린 release PR: {prs[0]['url']} — 새로 만들지 말고 갱신")
    res = run(
        "gh", "pr", "list", "--base", "dev", "--state", "open", "--json", "number,title"
    )
    if res.returncode == 0 and (open_prs := json.loads(res.stdout or "[]")):
        listed = "; ".join(f"#{p['number']} {p['title']}" for p in open_prs[:8])
        r.warn(f"dev로 열린 PR {len(open_prs)}개(이번 release에 안 들어감): {listed}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--no-tests", action="store_true", help="설치·린트·테스트 생략")
    p.add_argument(
        "--head", default=DEV, help="반영할 쪽(기본 origin/dev). 점검 시험용"
    )
    args = p.parse_args()
    dev = args.head

    root = git("rev-parse", "--show-toplevel")
    if not root:
        print("git 저장소 안에서 실행해야 한다")
        return 2
    os.chdir(root)
    if run("git", "fetch", "--quiet", "origin").returncode != 0:
        print("git fetch 실패 — 네트워크·인증 확인")
        return 2

    r = Report()
    print(
        f"release 점검: {dev} {git('rev-parse', '--short', dev)} → "
        f"{MAIN} {git('rev-parse', '--short', MAIN)}"
    )
    check_history(r, dev)
    tree = tempfile.mkdtemp(prefix="ww-release-")
    try:
        if run("git", "worktree", "add", "--detach", tree, dev).returncode != 0:
            print("임시 worktree를 만들지 못함")
            return 2
        check_tree(r, tree, tests=not args.no_tests)
    finally:
        run("git", "worktree", "remove", "--force", tree)
        shutil.rmtree(tree, ignore_errors=True)
    check_github(r)

    print("결과:", f"막는 문제 {r.blockers}개" if r.blockers else "release 가능")
    return 1 if r.blockers else 0


if __name__ == "__main__":
    sys.exit(main())

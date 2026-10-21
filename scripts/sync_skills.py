"""팀 스킬 원본(.agents/skills)을 Claude Code용 사본(.claude/skills)으로 복사한다.

Codex는 .agents/skills, Claude Code는 .claude/skills에서 스킬을 찾는다. 심볼릭 링크는
Windows에서 깨질 수 있어 복사본을 커밋하고, CI가 두 폴더가 같은지 검사한다.

    uv run --no-sync python scripts/sync_skills.py          # 복사 (= make skills)
    uv run --no-sync python scripts/sync_skills.py --check  # 검사만, 다르면 종료 코드 1

표준 라이브러리만 쓴다(CI에서 의존성 설치 없이 실행).
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / ".agents" / "skills"
DST = ROOT / ".claude" / "skills"
NOTICE_NAME = "README.md"
NOTICE = (
    "# 자동 생성 폴더 — 직접 고치지 마세요\n\n"
    "원본은 `.agents/skills/`입니다. 원본을 고친 뒤 "
    "`uv run --no-sync python scripts/sync_skills.py`(또는 `make skills`)로 복사합니다.\n"
)


def expected_files() -> dict[str, bytes]:
    """사본 폴더에 있어야 할 파일(상대 경로 → 내용)."""
    files = {
        p.relative_to(SRC).as_posix(): p.read_bytes()
        for p in sorted(SRC.rglob("*"))
        if p.is_file() and p.relative_to(SRC).as_posix() != NOTICE_NAME
    }
    files[NOTICE_NAME] = NOTICE.encode("utf-8")
    return files


def actual_files() -> dict[str, bytes]:
    if not DST.exists():
        return {}
    return {
        p.relative_to(DST).as_posix(): p.read_bytes()
        for p in sorted(DST.rglob("*"))
        if p.is_file()
    }


def check() -> int:
    want, have = expected_files(), actual_files()
    problems = [f"없음: {k}" for k in want.keys() - have.keys()]
    problems += [f"남는 파일: {k}" for k in have.keys() - want.keys()]
    problems += [
        f"내용 다름: {k}" for k in want.keys() & have.keys() if want[k] != have[k]
    ]
    if problems:
        print(".claude/skills가 .agents/skills와 다릅니다:")
        print("\n".join(f"  - {p}" for p in sorted(problems)))
        print("해결: uv run --no-sync python scripts/sync_skills.py 실행 후 커밋")
        return 1
    print(".claude/skills 동기화 상태 정상")
    return 0


def sync() -> int:
    if DST.exists():
        shutil.rmtree(DST)
    for rel, content in expected_files().items():
        target = DST / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    print(f"{SRC.relative_to(ROOT)} → {DST.relative_to(ROOT)} 복사 완료")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="복사하지 않고 검사만")
    args = parser.parse_args()
    if not SRC.is_dir():
        print(f"원본 폴더가 없습니다: {SRC}", file=sys.stderr)
        return 2
    return check() if args.check else sync()


if __name__ == "__main__":
    sys.exit(main())

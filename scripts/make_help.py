"""Makefile의 도움말 주석을 UTF-8로 읽는다. 외부 셸 도구를 사용하지 않는다."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def format_help(makefile: Path) -> str:
    entries = []
    for line in makefile.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([a-zA-Z0-9_-]+):.*?##\s*(.+)$", line)
        if match:
            target, description = match.groups()
            entries.append(f"  {target:<15} {description}")
    return "\n".join(entries)


if __name__ == "__main__":
    print(format_help(ROOT / "Makefile"))

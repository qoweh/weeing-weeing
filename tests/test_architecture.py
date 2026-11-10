"""docs/ARCHITECTURE.md의 의존 규칙을 코드로 확인한다.

1. 다른 모듈은 그 모듈의 interface와 contracts만 import한다.
2. plc는 api·agent·rag를 import하지 않는다.
함수 안의 지연 import도 같은 규칙을 따른다.
"""

import ast
from pathlib import Path

PACKAGE = Path(__file__).parents[1] / "src/weeing_weeing"
MODULES = {path.name for path in PACKAGE.iterdir() if (path / "__init__.py").exists()}
PLC_FORBIDDEN = {"api", "agent", "rag"}


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.lineno, node.module
            # `from weeing_weeing.db import reports`처럼 내부 파일을 이름으로 가져오는 경우
            for alias in node.names:
                yield node.lineno, f"{node.module}.{alias.name}"


def _violations():
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        owner = path.relative_to(PACKAGE).parts[0]
        if owner not in MODULES:
            continue
        for lineno, name in _imports(path):
            parts = name.split(".")
            if parts[0] != "weeing_weeing" or len(parts) < 2:
                continue
            target = parts[1]
            if target not in MODULES or target in {owner, "contracts"}:
                continue
            where = f"{path.relative_to(PACKAGE)}:{lineno} → {name}"
            if owner == "plc" and target in PLC_FORBIDDEN:
                found.append(f"plc 금지 import: {where}")
            elif len(parts) > 2 and parts[2] != "interface":
                # `from weeing_weeing.db.interface import X`의 X는 parts[3]이라 허용된다.
                found.append(f"interface 밖 import: {where}")
    return found


def test_modules_import_only_interfaces_and_contracts():
    assert _violations() == []

"""코드·compose가 읽는 환경변수가 .env.example 템플릿에 모두 있는지 확인한다.

.env는 열지 않는다. 템플릿(.env.example)이 기준이며, 새 키를 코드에 추가하면 같은 PR에서
템플릿에도 넣어야 팀원 PC와 서버(배포 때 env-sync)가 같은 키를 받는다.

    uv run --no-sync python scripts/check_env_template.py

- 루트 .env.example ↔ src·scripts의 env()/os.environ.get()/getenv(), docker-compose.yml·
  deploy/docker-compose.prod.yml의 ${KEY}
- deploy/langfuse/.env.example ↔ deploy/langfuse/docker-compose.yml의 ${KEY}
- 주석 처리된 줄(# KEY=)도 템플릿에 있는 것으로 본다(선택·비밀 키)

종료 코드: 0 빠진 키 없음 / 1 빠진 키 있음(키 이름만 출력)
"""

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
READ = re.compile(
    r"(?:\benv|getenv|environ\.get|environ\[)\(?\s*[\"']([A-Z][A-Z0-9_]{2,})[\"']"
)
COMPOSE = re.compile(r"\$\{([A-Z][A-Z0-9_]{2,})(?::?[-?][^}]*)?\}")
TEMPLATE_KEY = re.compile(r"^#?\s?([A-Z][A-Z0-9_]*)=", re.M)

# 템플릿 → (그 템플릿으로 채우는 파일, 템플릿에 두지 않는 키)
GROUPS = {
    ".env.example": (
        ["src", "scripts", "docker-compose.yml", "deploy/docker-compose.prod.yml"],
        {"ARGS"},  # make가 넘기는 명령 인수(scripts/run_make.py)
    ),
    "deploy/langfuse/.env.example": (["deploy/langfuse/docker-compose.yml"], set()),
}


def used_keys(paths: list[str], root: pathlib.Path) -> set[str]:
    listed = subprocess.run(
        ["git", "ls-files", *paths], cwd=root, capture_output=True, text=True
    ).stdout.split()
    keys: set[str] = set()
    for name in listed:
        if name == "scripts/check_env_template.py":
            continue
        text = (root / name).read_text(encoding="utf-8")
        if name.endswith(".py"):
            keys |= set(READ.findall(text))
        elif name.endswith((".yml", ".yaml")):
            keys |= set(COMPOSE.findall(text))
    return keys


def missing_keys(root: pathlib.Path = ROOT) -> dict[str, list[str]]:
    result = {}
    for template, (paths, ignore) in GROUPS.items():
        defined = set(
            TEMPLATE_KEY.findall((root / template).read_text(encoding="utf-8"))
        )
        result[template] = sorted(used_keys(paths, root) - defined - ignore)
    return result


def main() -> int:
    bad = False
    for template, keys in missing_keys().items():
        if keys:
            bad = True
            print(f"❌ {template}에 없음: {', '.join(keys)}")
        else:
            print(f"✅ {template}")
    if bad:
        print(
            "관련 키 옆 같은 절에 비밀 값 없이 추가한다(선택·비밀 키는 '# KEY=' 주석 줄)."
        )
    return int(bad)


if __name__ == "__main__":
    sys.exit(main())

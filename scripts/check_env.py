"""내 .env를 .env.example과 비교해 빠진·낡은·중복·주석 처리된 변수를 알려 준다.

비밀 값(키·비밀번호·토큰·DATABASE_URL)은 출력하지 않고 "설정됨/비어 있음"만 보여 준다.
.env를 환경변수로 불러오지 않고 파일을 글자로만 읽는다.

    make env-check                                    # 레포 루트 .env
    make env-check ARGS="--file 다른/경로/.env"
    # 운영 서버(~/weeing-weeing): 컨테이너 안의 .env.example과 서버 .env를 비교
    docker compose run --rm --no-deps -v "$PWD/.env:/tmp/check.env:ro" api \
        python scripts/check_env.py --file /tmp/check.env --no-shell-check
    # 빠진 키만 템플릿과 같은 위치에 추가(배포 워크플로가 실행. 서버: ops/aws.sh env-sync)
    python scripts/check_env.py --file .env --example .env.example --add-missing

종료 코드: 0 고칠 것 없음 / 1 고칠 것 있음(중복·형식 오류·빈 키·셸 값 충돌) / 2 파일 없음
--add-missing은 0(추가했거나 추가할 것 없음) / 2(파일 없음)
"""

import argparse
import datetime
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY = r"[A-Z][A-Z0-9_]*"
ACTIVE = re.compile(rf"^(?:export\s+)?({KEY})=(.*)$")
COMMENTED = re.compile(rf"^#\s*({KEY})=")
SECRET_WORDS = ("KEY", "SECRET", "PASSWORD", "TOKEN")


def is_secret(name: str) -> bool:
    return name == "DATABASE_URL" or any(word in name for word in SECRET_WORDS)


def clean(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value.split(" #", 1)[0].strip()


@dataclass
class EnvFile:
    values: dict[str, str] = field(default_factory=dict)  # 마지막 값
    lines: dict[str, list[int]] = field(default_factory=dict)  # 줄 번호(중복 확인)
    commented: dict[str, int] = field(default_factory=dict)
    malformed: list[int] = field(default_factory=list)


def parse(path: Path) -> EnvFile:
    # utf-8-sig: Windows 메모장이 붙이는 BOM 때문에 첫 변수 이름이 깨지지 않게 한다.
    return parse_text(path.read_text(encoding="utf-8-sig"))


def parse_text(text: str) -> EnvFile:
    env = EnvFile()
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if match := COMMENTED.match(line):
                env.commented.setdefault(match[1], number)
            continue
        if match := ACTIVE.match(line):
            env.values[match[1]] = clean(match[2])
            env.lines.setdefault(match[1], []).append(number)
        else:
            env.malformed.append(number)
    return env


def check(
    env: EnvFile, example: EnvFile, *, shell: dict[str, str] | None
) -> tuple[list[str], int]:
    """보고서 줄과 고칠 것의 개수를 돌려준다. 비밀 값은 줄에 넣지 않는다."""
    order = list(dict.fromkeys([*example.lines, *example.commented]))
    known = set(order)
    fix: list[str] = []
    for name, numbers in env.lines.items():
        if len(numbers) > 1:
            fix.append(
                f"{name}: {', '.join(map(str, numbers))}번 줄에 중복. 마지막 줄 값이 쓰인다. 하나만 남긴다"
            )
    for number in env.malformed:
        fix.append(f"{number}번 줄: KEY=값 형식이 아니다")
    if env.values.get("ANTHROPIC_API_KEY", None) == "":
        fix.append(
            "ANTHROPIC_API_KEY: 빈 값이라 ant 프로필보다 우선해 인증이 실패한다. 값을 넣거나 줄을 지운다"
        )
    for name, value in (shell or {}).items():
        if name in env.values and value != env.values[name]:
            fix.append(
                f"{name}: 셸에 export된 값이 .env와 다르다. `unset {name}` 후 다시 실행한다"
            )

    unknown = [n for n in env.values if n not in known]
    commented = [n for n in order if n in env.commented and n not in env.values]
    missing = [n for n in order if n in example.lines and n not in env.values]
    changed = [
        n
        for n in order
        if n in env.values
        and n in example.values
        and not is_secret(n)
        and env.values[n] != example.values[n]
    ]
    secrets = [n for n in order if is_secret(n) and n in env.values]

    report = []

    def section(title: str, items: list[str]) -> None:
        if items:
            report.append(f"\n[{title}]")
            report.extend(f"  - {item}" for item in items)

    section("고칠 것", fix)
    section(
        ".env.example에 없는 변수 (예전 이름이거나 오타일 수 있다. 지워도 된다)",
        [f"{n} ({env.lines[n][0]}번 줄)" for n in unknown],
    )
    section(
        "주석이라 적용되지 않는 변수",
        [f"{n} ({env.commented[n]}번 줄)" for n in commented],
    )
    section(
        "없어서 기본값을 쓰는 변수 (그대로 둬도 된다)",
        [f"{n} = {example.values[n] or '(빈 값)'}" for n in missing],
    )
    section(
        "기본값과 다르게 설정한 값",
        [
            f"{n} = {env.values[n] or '(빈 값)'}  (기본 {example.values[n] or '빈 값'})"
            for n in changed
        ],
    )
    section(
        "비밀 값 (값은 표시하지 않음)",
        [f"{n}: {'설정됨' if env.values[n] else '비어 있음'}" for n in secrets],
    )
    return report, len(fix)


def missing_lines(env: EnvFile, example_text: str) -> list[tuple[str, str]]:
    """.env에 키가 아예 없는 .env.example 줄을 (키, 원래 줄)로 돌려준다.

    값이 있든 비었든(KEY=), 주석(# KEY=)이든 .env에 키가 보이면 있는 것으로 본다.
    .env.example의 줄은 주석이면 주석 그대로, 예시 값이 있으면 그 값 그대로 옮긴다.
    """
    present = set(env.lines) | set(env.commented)
    found: list[tuple[str, str]] = []
    for raw in example_text.splitlines():
        line = raw.strip()
        match = COMMENTED.match(line) or ACTIVE.match(line)
        if match and match[1] not in present:
            present.add(match[1])
            found.append((match[1], line))
    return found


def _key(line: str) -> str | None:
    line = line.strip()
    match = COMMENTED.match(line) or ACTIVE.match(line)
    return match[1] if match else None


def _description(example: list[str], index: int) -> list[str]:
    """템플릿에서 키 줄 바로 위의 설명 주석(빈 줄·다른 키·절 제목 전까지)."""
    lines: list[str] = []
    for raw in reversed(example[:index]):
        line = raw.strip()
        if not line.startswith("#") or _key(line) or line.startswith("# ──"):
            break
        lines.insert(0, line)
    return lines


def add_missing(env_path: Path, example_path: Path) -> list[str]:
    """빠진 키를 .env.example과 같은 위치에 넣고 추가한 키 이름을 돌려준다.

    위치: 템플릿에서 바로 앞에 있는 키 중 .env에 있는 가장 가까운 키 다음 줄. 앞쪽에
    없으면 뒤쪽 가장 가까운 키 앞, 둘 다 없으면 파일 끝에 덧붙인다. 템플릿에서 그 키
    바로 위에 있던 설명 주석도 함께 옮긴다. 기존 줄은 고치거나 지우지 않는다.
    바꾸기 전 .env를 같은 폴더의 .env.bak으로 남긴다(권한 유지). 같은 파일에 다시 써서
    소유자·권한·마운트가 그대로다.
    """
    # newline="": 줄바꿈을 바꾸지 않고 읽어 원래 방식(LF·CRLF)대로 다시 쓴다.
    with env_path.open(encoding="utf-8-sig", newline="") as file:
        text = file.read()
    example_text = example_path.read_text(encoding="utf-8-sig")
    missing = missing_lines(parse_text(text), example_text)
    if not missing:
        return []
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    example = example_text.splitlines()
    example_keys = [_key(line) for line in example]
    names = {name for name, _ in missing}

    def last_line(key: str) -> int | None:
        found = [i for i, line in enumerate(lines) if _key(line) == key]
        return found[-1] if found else None

    def first_line(key: str) -> int | None:
        found = [i for i, line in enumerate(lines) if _key(line) == key]
        return found[0] if found else None

    tail: list[str] = []
    for index, key in enumerate(example_keys):
        if key not in names:
            continue
        description = _description(example, index)
        existing = {line.strip() for line in lines}
        # 키 줄만 지우고 설명은 남긴 .env에서 같은 설명을 두 번 넣지 않는다.
        block = [line for line in description if line not in existing]
        block.append(example[index].strip())
        anchor = None
        for previous in reversed(example_keys[:index]):
            if previous and (at := last_line(previous)) is not None:
                anchor = at + 1  # 앞 키 다음 줄
                # 남아 있는 설명 주석이 바로 뒤에 있으면 그 아래에 넣는다.
                while anchor < len(lines) and lines[anchor].strip() in description:
                    anchor += 1
                break
        if anchor is None:
            for following in example_keys[index + 1 :]:
                if following and following not in names:
                    if (at := first_line(following)) is not None:
                        anchor = at  # 뒤 키 앞
                        break
        if anchor is None:
            tail += block
        else:
            lines[anchor:anchor] = block
        names.discard(key)
    shutil.copy2(env_path, env_path.with_name(env_path.name + ".bak"))
    if tail:
        today = datetime.date.today().isoformat()
        lines += ["", f"# ── {example_path.name}에서 자동 추가 ({today}) ──", *tail]
    # 새 파일로 바꾸지 않고 같은 파일을 다시 써서 소유자·권한·마운트를 유지한다.
    with env_path.open("w", encoding="utf-8", newline="") as file:
        file.write(newline.join(lines) + newline)
    return [name for name, _ in missing]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", type=Path, default=ROOT / ".env")
    parser.add_argument("--example", type=Path, default=ROOT / ".env.example")
    parser.add_argument(
        "--no-shell-check",
        action="store_true",
        help="셸 환경변수와 비교하지 않는다(컨테이너 안에서 실행할 때)",
    )
    parser.add_argument(
        "--add-missing",
        action="store_true",
        help="키가 아예 없는 .env.example 줄을 템플릿과 같은 위치에 추가한다(키 이름만 출력)",
    )
    args = parser.parse_args(argv)
    for path in (args.file, args.example):
        if not path.is_file():
            print(f"{path} 파일이 없다. cp .env.example .env로 만든다", file=sys.stderr)
            return 2
    if args.add_missing:
        added = add_missing(args.file, args.example)
        if added:
            print(
                f"{args.file}에 {len(added)}개 추가 (이전 파일: {args.file.name}.bak)"
            )
            print("\n".join(f"  + {name}" for name in added))
        else:
            print(f"{args.file}: 추가할 키 없음")
        return 0
    env, example = parse(args.file), parse(args.example)
    shell = None if args.no_shell_check else dict(os.environ)
    report, problems = check(env, example, shell=shell)
    print(f"{args.file} ↔ {args.example.name}")
    print("\n".join(report) if report else "\n차이 없음")
    print(f"\n고칠 것 {problems}개" if problems else "\n고칠 것 없음")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

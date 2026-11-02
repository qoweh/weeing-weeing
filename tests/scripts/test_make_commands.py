"""실제 make·셸의 환경변수와 인수 전달을 검사한다. 서비스는 호출하지 않는다."""

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAKE = shutil.which("make")
pytestmark = pytest.mark.skipif(MAKE is None, reason="GNU make가 설치되지 않음")


def run_make(*arguments):
    env = dict(os.environ, PYTHONUTF8="0", PYTHONIOENCODING="cp949", PYTHONPATH="")
    result = subprocess.run(
        [MAKE, "--no-print-directory", "--silent", *arguments],
        cwd=ROOT,
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    if result.returncode:
        pytest.fail(
            f"make 종료 코드 {result.returncode}: {ascii(result.stderr)}", pytrace=False
        )
    return result.stdout


def test_help_runs_without_grep_or_awk():
    output = run_make("help")
    assert "명령 목록" in output
    assert "chat-private" in output
    assert "RAG 실제 문서" in output


@pytest.mark.parametrize(
    ("target", "prefix"),
    [
        ("db-migrate", ["alembic", "upgrade", "head"]),
        ("models", ["python", "scripts/download_models.py"]),
        ("index-reports", ["python", "scripts/index_reports.py"]),
        ("seed-users", ["python", "scripts/seed_users.py"]),
        ("rag-e2e", ["python", "scripts/verify_rag_e2e.py"]),
        ("llm-check", ["python", "scripts/check_llm.py"]),
        ("llm-eval", ["python", "scripts/compare_llm.py"]),
        ("analyze", ["python", "scripts/analyze_incident.py"]),
        (
            "api",
            ["uvicorn", "--app-dir", "src", "weeing_weeing.api.app:app", "--reload"],
        ),
        ("chat", ["python", "scripts/chat.py"]),
        ("chat-check", ["python", "scripts/check_chat.py"]),
        (
            "chat-private",
            [
                "--no-env-file",
                "python",
                "scripts/chat.py",
                "--interactive",
                "--ask-key",
            ],
        ),
    ],
)
def test_targets_pass_unicode_arguments_and_python_environment(
    tmp_path, target, prefix
):
    runner = tmp_path / "path with spaces" / "capture.py"
    runner.parent.mkdir()
    runner.write_text(
        "import json, os, sys\n"
        "print(json.dumps({'args': sys.argv[1:], 'utf8': sys.flags.utf8_mode, "
        "'stdio': sys.stdout.encoding, 'path': os.environ['PYTHONPATH'], "
        "'source_args': os.environ.get('ARGS')}, "
        "ensure_ascii=True))\n",
        encoding="utf-8",
    )
    output = run_make(
        target,
        f'RUN=uv run --no-sync python "{runner}"',
        "ENV_FILE=",
        'ARGS=--file "한글 공백/입력.json"',
    )
    result = json.loads(output)
    assert result["args"] == ["python", "scripts/run_make.py", *prefix]
    assert result["source_args"] == '--file "한글 공백/입력.json"'
    assert result["utf8"] == 1
    assert result["stdio"].lower() == "utf-8"
    assert Path(result["path"]).resolve() == ROOT / "src"


def test_wrapper_delivers_unicode_arguments_and_exit_code(tmp_path):
    runner = tmp_path / "capture.py"
    runner.write_text(
        "import json, sys\nprint(json.dumps(sys.argv[1:], ensure_ascii=True))\n"
        "sys.stderr.buffer.write('실패 메시지\\n'.encode('cp949'))\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )
    # 실제 Python 실행기까지 연결한다. 실제 서비스는 부르지 않는다.
    makefile = tmp_path / "probe.mk"
    makefile.write_text(
        'probe:\n\t@$(RUN) python scripts/run_make.py python "'
        + runner.as_posix()
        + '"\n',
        encoding="utf-8",
    )
    env = dict(os.environ, PYTHONUTF8="0", PYTHONIOENCODING="cp949")
    result = subprocess.run(
        [
            MAKE,
            "--no-print-directory",
            "--silent",
            "-f",
            "Makefile",
            "-f",
            str(makefile),
            "probe",
            'ARGS=--file "한글 공백/입력.json"',
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=30,
    )
    assert json.loads(result.stdout) == ["--file", "한글 공백/입력.json"]
    assert result.returncode != 0
    # make·셸의 오류 출력은 Python의 UTF-8 설정과 다른 인코딩일 수 있다.
    assert "실패 메시지".encode("cp949") in result.stderr
    assert b"7" in result.stderr


def test_wrapper_preserves_env_policy_and_has_no_shell(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "run_make", ROOT / "scripts/run_make.py"
    )
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    monkeypatch.setenv("ARGS", '--file "한글 공백/입력.json"')
    commands = []
    monkeypatch.setattr(
        wrapper.subprocess, "call", lambda command: commands.append(command) or 9
    )
    assert wrapper.main(["--no-env-file", "python", "scripts/chat.py"]) == 9
    assert commands == [
        [
            "uv",
            "run",
            "--no-sync",
            "--no-env-file",
            "python",
            "scripts/chat.py",
            "--file",
            "한글 공백/입력.json",
        ]
    ]

"""check_env.py: 가짜 .env로 비교 결과와 비밀 값 비노출을 검사한다."""

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "check_env", ROOT / "scripts" / "check_env.py"
)
check_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_env)

EXAMPLE = """\
# ── 1. 비밀 키 ──
# VOYAGE_API_KEY=
# ANTHROPIC_API_KEY=
LLM_MODEL=claude-sonnet-5-5
VOYAGE_BASE_URL=https://ai.mongodb.com/v1
POSTGRES_PASSWORD=weeing
RAG_COLLECTION=knowledge_voyage
"""
FAKE_KEY = "fake-voyage-value-000"


def run(tmp_path, env_text, capsys, *args):
    example = tmp_path / "example"
    example.write_text(EXAMPLE, encoding="utf-8")
    env = tmp_path / "env"
    env.write_text(env_text, encoding="utf-8")
    code = check_env.main(
        ["--file", str(env), "--example", str(example), "--no-shell-check", *args]
    )
    return code, capsys.readouterr().out


def test_reports_each_kind_without_secret_values(tmp_path, capsys):
    code, out = run(
        tmp_path,
        f"VOYAGE_API_KEY={FAKE_KEY}\n"
        "POSTGRES_PASSWORD=fakepw000\n"
        "LLM_MODEL=claude-haiku-5-5\n"
        "# VOYAGE_BASE_URL=https://api.voyageai.com/v1\n"
        "HF_HOME=/models\n",
        capsys,
    )
    assert code == 0
    assert FAKE_KEY not in out and "fakepw000" not in out
    assert "VOYAGE_API_KEY: 설정됨" in out
    assert "POSTGRES_PASSWORD: 설정됨" in out
    assert "HF_HOME (5번 줄)" in out
    assert "VOYAGE_BASE_URL (4번 줄)" in out  # 주석이라 적용 안 됨
    assert "VOYAGE_BASE_URL = https://ai.mongodb.com/v1" in out  # 기본값 사용
    assert "RAG_COLLECTION = knowledge_voyage" in out
    assert "LLM_MODEL = claude-haiku-5-5  (기본 claude-sonnet-5-5)" in out


def test_duplicates_malformed_and_empty_claude_key_need_fixing(tmp_path, capsys):
    code, out = run(
        tmp_path,
        "LLM_MODEL=a\nLLM_MODEL=b\nnot a line\nANTHROPIC_API_KEY=\n",
        capsys,
    )
    assert code == 1
    assert "LLM_MODEL: 1, 2번 줄에 중복" in out
    assert "3번 줄: KEY=값 형식이 아니다" in out
    assert "ANTHROPIC_API_KEY: 빈 값" in out
    assert "고칠 것 3개" in out


def test_shell_value_that_differs_is_reported_by_name_only(tmp_path):
    env = check_env.EnvFile(values={"VOYAGE_BASE_URL": "https://api.voyageai.com/v1"})
    example = check_env.parse_text(EXAMPLE)
    report, problems = check_env.check(
        env, example, shell={"VOYAGE_BASE_URL": "https://other"}
    )
    assert problems == 1
    assert "https://other" not in "\n".join(report)


def test_quotes_export_and_inline_comment(tmp_path, capsys):
    code, out = run(
        tmp_path,
        'export LLM_MODEL="claude-haiku-5-5"\nRAG_COLLECTION=kv # 새 컬렉션\n',
        capsys,
    )
    assert code == 0
    assert "LLM_MODEL = claude-haiku-5-5" in out
    assert "RAG_COLLECTION = kv  (기본 knowledge_voyage)" in out


def test_missing_file_exit_2(tmp_path):
    assert check_env.main(["--file", str(tmp_path / "none")]) == 2


def test_repo_env_example_parses_cleanly():
    example = check_env.parse(ROOT / ".env.example")
    assert not example.malformed
    assert all(len(lines) == 1 for lines in example.lines.values())


# ── --add-missing: 빠진 키만 .env 끝에 추가 ──
SYNC_EXAMPLE = """\
# ── 1. 비밀 키 ──
ANTHROPIC_API_KEY=
POSTGRES_PASSWORD=weeing
LLM_MODEL=claude-sonnet-5-5
# 설명 줄(키 아님)
RERANKER_MODEL=
# SITE_ADDRESS=
NEW_FLAG=true
"""


def sync(tmp_path, env_text, capsys):
    example = tmp_path / ".env.example"
    example.write_text(SYNC_EXAMPLE, encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text(env_text, encoding="utf-8")
    env.chmod(0o600)
    code = check_env.main(
        ["--file", str(env), "--example", str(example), "--add-missing"]
    )
    return code, env, capsys.readouterr().out


def test_add_missing_appends_only_absent_keys_verbatim(tmp_path, capsys):
    original = (
        "ANTHROPIC_API_KEY=fake-anthropic-000\n"  # 값 있음
        "POSTGRES_PASSWORD=fakepw000\n"
        "RERANKER_MODEL=\n"  # 값만 빈 키
        "# LLM_MODEL=claude-haiku-5-5\n"  # 주석 처리된 키
        "OLD_ONLY=1"  # .env에만 있는 키, 마지막 줄바꿈 없음
    )
    code, env, out = sync(tmp_path, original, capsys)
    assert code == 0
    text = env.read_text(encoding="utf-8")
    assert text.startswith(original + "\n")  # 기존 줄은 그대로
    added = text[len(original) :].strip().splitlines()
    assert added[0].startswith("# ── .env.example에서 자동 추가 (")
    assert added[1:] == [
        "# SITE_ADDRESS=",
        "NEW_FLAG=true",
    ]  # 주석은 주석, 예시 값 그대로
    assert (tmp_path / ".env.bak").read_text(encoding="utf-8") == original
    if os.name != "nt":  # Windows는 POSIX 권한 비트가 없다
        assert (tmp_path / ".env.bak").stat().st_mode & 0o777 == 0o600
        assert env.stat().st_mode & 0o777 == 0o600
    assert "+ SITE_ADDRESS" in out and "+ NEW_FLAG" in out
    assert "fake-anthropic-000" not in out and "fakepw000" not in out
    assert "true" not in out  # 값은 출력하지 않는다


def test_add_missing_is_idempotent_and_skips_backup_when_nothing_to_add(
    tmp_path, capsys
):
    code, env, _ = sync(tmp_path, "LLM_MODEL=x\n", capsys)
    first = env.read_text(encoding="utf-8")
    (tmp_path / ".env.bak").unlink()
    code, env, out = sync(tmp_path, first, capsys)
    assert code == 0
    assert env.read_text(encoding="utf-8") == first
    assert not (tmp_path / ".env.bak").exists()
    assert "추가할 키 없음" in out


def test_repo_env_example_fills_empty_env_with_every_key(tmp_path):
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    added = check_env.add_missing(env, ROOT / ".env.example")
    example = check_env.parse(ROOT / ".env.example")
    assert set(added) == set(example.lines) | set(example.commented)
    synced = check_env.parse(env)
    assert synced.values == example.values
    assert not synced.malformed


def test_deploy_syncs_env_before_replacing_containers():
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    copy = workflow.index('scp .env.example "$EC2":~/weeing-weeing/.env.example')
    script = workflow.index(
        'scp scripts/check_env.py "$EC2":~/weeing-weeing/check_env.py'
    )
    sync_step = workflow.index("ssh \"$EC2\" 'bash -s env-sync' < ops/server.sh")
    replace = workflow.index("name: 이미지 받기·교체")
    assert copy < sync_step and script < sync_step < replace
    server = (ROOT / "ops/server.sh").read_text(encoding="utf-8")
    assert "env-check|env-sync)" in server
    assert "--network none" in server and "--add-missing" in server


def run_server_sync(tmp_path, running_image):
    bash = shutil.which("bash")
    if os.name == "nt" or not bash:
        pytest.skip("POSIX bash가 필요합니다")
    app = tmp_path / "weeing-weeing"
    app.mkdir()
    for name in (".env", ".env.example", "check_env.py"):
        (app / name).write_text("FAKE=1\n", encoding="utf-8")  # 가짜 파일만
    tools = tmp_path / "bin"
    tools.mkdir()
    docker = tools / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = ps ]; then printf "%s" "$FAKE_IMAGE"; exit 0; fi\n'
        'printf "%s\\n" "$*" >> "$HOME/docker-calls"\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    environment = {
        "PATH": f"{tools}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "FAKE_IMAGE": running_image,
    }
    result = subprocess.run(
        [bash, str(ROOT / "ops/server.sh"), "env-sync"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    calls = tmp_path / "docker-calls"
    return result, calls.read_text().splitlines() if calls.exists() else []


def test_server_env_sync_runs_offline_in_running_api_image(tmp_path):
    result, calls = run_server_sync(tmp_path, "ghcr.io/fake/app-api:old\n")
    assert result.returncode == 0, result.stderr
    assert len(calls) == 1
    call = calls[0]
    assert call.startswith("run --rm --pull never --network none --user ")
    assert "ghcr.io/fake/app-api:old python /tmp/check_env.py" in call
    assert call.endswith("--file /work/.env --example /work/.env.example --add-missing")


def test_server_env_sync_skips_without_running_api(tmp_path):
    result, calls = run_server_sync(tmp_path, "")
    assert result.returncode == 0, result.stderr
    assert calls == []
    assert "건너뛴다" in result.stdout

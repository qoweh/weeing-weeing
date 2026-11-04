"""check_env.py: 가짜 .env로 비교 결과와 비밀 값 비노출을 검사한다."""

import importlib.util
from pathlib import Path

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

"""템플릿 점검: 지금 레포는 빠진 키가 없고, 코드에만 있는 키는 잡는다. .env는 열지 않는다."""

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load():
    spec = importlib.util.spec_from_file_location(
        "check_env_template", ROOT / "scripts/check_env_template.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repository_templates_cover_all_read_keys():
    assert all(not keys for keys in load().missing_keys().values())


def test_key_only_in_code_or_compose_is_reported(tmp_path):
    module = load()
    (tmp_path / "src").mkdir()
    (tmp_path / "deploy/langfuse").mkdir(parents=True)
    (tmp_path / "src/config.py").write_text(
        'x = env(\n    "NEW_FLAG", "")\ny = os.environ.get("KNOWN")\n', encoding="utf-8"
    )
    (tmp_path / "docker-compose.yml").write_text(
        "a: ${COMPOSE_ONLY:-1}\nb: ${OPTIONAL_SECRET}\n", encoding="utf-8"
    )
    (tmp_path / "deploy/langfuse/docker-compose.yml").write_text(
        "a: ${SALT:?필요}\n", encoding="utf-8"
    )
    (tmp_path / ".env.example").write_text(
        "KNOWN=1\n# OPTIONAL_SECRET=\n", encoding="utf-8"
    )
    (tmp_path / "deploy/langfuse/.env.example").write_text("", encoding="utf-8")
    (tmp_path / ".env").write_text("NEW_FLAG=secret-value\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)

    result = module.missing_keys(tmp_path)
    assert result[".env.example"] == ["COMPOSE_ONLY", "NEW_FLAG"]  # .env에 있어도 빠짐
    assert result["deploy/langfuse/.env.example"] == ["SALT"]

from dataclasses import fields
from pathlib import Path

from weeing_weeing.config import get_settings

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"
# docker compose만 읽는 항목
COMPOSE_ONLY = {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"}


def _example() -> dict[str, str]:
    pairs = (
        line.split("=", 1)
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    return {k: v for k, v in pairs if k not in COMPOSE_ONLY}


def test_env_example_and_settings_have_same_keys():
    assert set(_example()) == {f.name.upper() for f in fields(get_settings())}


def test_defaults_match_env_example(monkeypatch):
    example = _example()
    for key in example:
        monkeypatch.delenv(key, raising=False)
    settings = get_settings()

    for key, value in example.items():
        actual = getattr(settings, key.lower())
        assert actual == type(actual)(value), key

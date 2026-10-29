from dataclasses import fields
from pathlib import Path

import pytest

from weeing_weeing.config import get_settings

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"
# docker compose만 읽는 항목, Anthropic SDK가 직접 읽는 비밀 값(Settings에 두지 않음)
COMPOSE_ONLY = {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"}
SDK_ONLY = {"ANTHROPIC_API_KEY"}


def _example() -> dict[str, str]:
    pairs = (
        line.split("=", 1)
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    return {k: v for k, v in pairs if k not in COMPOSE_ONLY | SDK_ONLY}


def test_env_example_and_settings_have_same_keys():
    assert set(_example()) == {f.name.upper() for f in fields(get_settings())}


def test_defaults_match_env_example(monkeypatch):
    example = _example()
    for key in example:
        monkeypatch.delenv(key, raising=False)
    settings = get_settings()

    for key, value in example.items():
        actual = getattr(settings, key.lower())
        if isinstance(actual, bool):  # bool("false")는 True라 문자열로 비교한다
            assert actual == (value.lower() in ("1", "true", "yes")), key
        elif actual is None:
            assert value == "", key
        else:
            assert actual == type(actual)(value), key


@pytest.mark.parametrize(
    "value, expected", [("", None), ("  ", None), ("0", 0.0), ("0.5", 0.5)]
)
def test_min_relevance_from_environment(monkeypatch, value, expected):
    monkeypatch.setenv("RAG_MIN_RELEVANCE", value)
    assert get_settings().rag_min_relevance == expected


def test_invalid_min_relevance_from_environment(monkeypatch):
    monkeypatch.setenv("RAG_MIN_RELEVANCE", "low")
    with pytest.raises(ValueError):
        get_settings()

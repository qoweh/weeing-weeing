from dataclasses import fields
from pathlib import Path

import pytest

from weeing_weeing.config import get_settings

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"
# docker compose만 읽는 항목, Anthropic SDK가 직접 읽는 비밀 값(Settings에 두지 않음)
COMPOSE_ONLY = {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"}
SDK_ONLY = {
    "ANTHROPIC_API_KEY",
    "VOYAGE_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
}
# 예시 파일은 실제 코드 기본값과 다른 멀티 분석 시연 설정을 제공한다.
EXAMPLE_OVERRIDES = {
    "ANALYSIS_MODE",
    "ANALYSIS_VERIFICATION_ENABLED",
    "ANALYSIS_TOTAL_TIMEOUT_S",
}


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
        if key in EXAMPLE_OVERRIDES:
            continue
        actual = getattr(settings, key.lower())
        if isinstance(actual, bool):  # bool("false")는 True라 문자열로 비교한다
            assert actual == (value.lower() in ("1", "true", "yes")), key
        elif actual is None:
            assert value == "", key
        else:
            assert actual == type(actual)(value), key


def test_example_analysis_overrides_are_valid(monkeypatch):
    example = _example()
    for key in EXAMPLE_OVERRIDES:
        monkeypatch.setenv(key, example[key])
    settings = get_settings()
    assert settings.analysis_mode in {"single", "multi"}
    assert example["ANALYSIS_VERIFICATION_ENABLED"].lower() in {"true", "false"}
    assert settings.analysis_total_timeout_s > 0


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


@pytest.mark.parametrize(
    "value,enabled",
    [("false", False), ("0", False), ("true", True), ("1", True), ("yes", True)],
)
def test_telemetry_storage_flag_does_not_enable_analysis(monkeypatch, value, enabled):
    monkeypatch.setenv("TELEMETRY_DB_ENABLED", value)
    monkeypatch.setenv("ANALYSIS_AUTO_ENABLED", "false")
    settings = get_settings()
    assert settings.telemetry_db_enabled is enabled
    assert settings.analysis_auto_enabled is False


def test_voyage_url_and_collection_ignore_surrounding_spaces(monkeypatch):
    # 서버 .env 값 끝 공백이 URL·컬렉션 이름에 섞이면 Voyage 호출·검색 대상이 바뀐다.
    monkeypatch.setenv("VOYAGE_BASE_URL", "https://api.voyageai.com/v1 ")
    monkeypatch.setenv("RAG_COLLECTION", " knowledge_voyage ")
    settings = get_settings()
    assert settings.voyage_base_url == "https://api.voyageai.com/v1"
    assert settings.rag_collection == "knowledge_voyage"

"""scripts/download_models.py: .env의 모델만 받고, 하나라도 못 받으면 종료 코드 1."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _script():
    spec = importlib.util.spec_from_file_location(
        "download_models", ROOT / "scripts/download_models.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _env(monkeypatch, *, embedding="emb/model", reranker=""):
    monkeypatch.setenv("EMBEDDING_MODEL", embedding)
    monkeypatch.setenv("RERANKER_MODEL", reranker)


def test_downloads_configured_models(monkeypatch, tmp_path):
    script = _script()
    _env(monkeypatch, reranker="rr/model")
    got = []
    monkeypatch.setattr(script, "download_hf", lambda m: got.append(m) or tmp_path)

    assert script.main([]) == 0
    assert got == ["emb/model", "rr/model"]


def test_empty_reranker_is_skipped(monkeypatch, tmp_path):
    script = _script()
    _env(monkeypatch)
    got = []
    monkeypatch.setattr(script, "download_hf", lambda m: got.append(m) or tmp_path)

    assert script.main([]) == 0
    assert got == ["emb/model"]


def test_local_path_is_not_downloaded(monkeypatch, tmp_path):
    script = _script()
    _env(monkeypatch, embedding=str(tmp_path))
    monkeypatch.setattr(
        script, "download_hf", lambda m: (_ for _ in ()).throw(AssertionError)
    )

    assert script.main([]) == 0


def test_failure_exit_code(monkeypatch, capsys):
    script = _script()
    _env(monkeypatch, reranker="rr/model")

    def boom(_model):
        raise OSError("network down")

    monkeypatch.setattr(script, "download_hf", boom)

    assert script.main([]) == 1
    assert "받지 못함: emb/model, rr/model" in capsys.readouterr().out

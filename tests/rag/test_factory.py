"""build_store 조립과 색인 명령(scripts/build_index.py)."""

import dataclasses
import importlib.util
from pathlib import Path

import pytest
from fakes import FakeEmbedder, TextIndexer
from test_catalog_sync import Workspace

from weeing_weeing.config import get_settings
from weeing_weeing.rag import factory
from weeing_weeing.rag.chroma_store import ChromaVectorStore
from weeing_weeing.rag.qdrant_store import QdrantVectorStore
from weeing_weeing.rag.sparse import KiwiBm25Encoder
from weeing_weeing.rag.store import Chunk

ROOT = Path(__file__).resolve().parents[2]


def no_indexer():
    """Indexer 구현이 연결되지 않은 상태를 흉내 낸다(색인 명령이 저장소를 열기 전에 멈춰야 함)."""
    raise NotImplementedError("#6 Indexer가 아직 없다")


def settings(tmp_path, **overrides):
    base = get_settings()
    values = dict(
        embedding_model="fake-embedder-v1",
        vector_store="qdrant",
        qdrant_path=tmp_path / "qdrant",
        qdrant_url="",
        chroma_dir=tmp_path / "chroma",
        upload_dir=tmp_path / "uploads",
    )
    return dataclasses.replace(base, **{**values, **overrides})


def test_qdrant_local_by_default(tmp_path):
    store = factory.build_store(settings(tmp_path), embedder=FakeEmbedder())

    assert isinstance(store, QdrantVectorStore)
    assert store._client.init_options["path"] == str(tmp_path / "qdrant")
    assert isinstance(store._sparse, KiwiBm25Encoder)
    store._client.close()


def test_chroma_with_telemetry_off(tmp_path):
    store = factory.build_store(
        settings(tmp_path, vector_store="chroma"), embedder=FakeEmbedder()
    )

    assert isinstance(store, ChromaVectorStore)
    assert store._client.get_settings().anonymized_telemetry is False


def test_qdrant_server_mode_uses_url_and_timeout(tmp_path, monkeypatch):
    seen = {}

    class FakeClient:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def collection_exists(self, name):
            return False

    monkeypatch.setattr("qdrant_client.QdrantClient", FakeClient)
    factory.build_store(
        settings(tmp_path, qdrant_url="http://qdrant:6333", qdrant_timeout_s=3.0),
        embedder=FakeEmbedder(),
    )
    assert seen == {"url": "http://qdrant:6333", "timeout": 3.0}


def test_missing_embedding_model_is_clear_error(tmp_path):
    with pytest.raises(factory.StoreConfigError, match="EMBEDDING_MODEL"):
        factory.build_store(settings(tmp_path, embedding_model=" "))


def test_unknown_backend_is_rejected(tmp_path):
    with pytest.raises(factory.StoreConfigError, match="VECTOR_STORE='milvus'"):
        factory.build_store(
            settings(tmp_path, vector_store="milvus"), embedder=FakeEmbedder()
        )


def test_locked_local_folder_explains_fix(tmp_path):
    first = factory.build_store(settings(tmp_path), embedder=FakeEmbedder())

    with pytest.raises(factory.StoreLockedError, match="QDRANT_URL 서버 모드"):
        factory.build_store(settings(tmp_path), embedder=FakeEmbedder())
    first._client.close()


def test_default_embedder_is_issue_6_model_loaded_once_on_first_use(
    tmp_path, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        factory, "_default_embedder", lambda name: calls.append(name) or FakeEmbedder()
    )
    store = factory.build_store(settings(tmp_path, vector_store="chroma"))
    assert calls == []  # 조립만으로는 모델을 올리지 않는다

    store.query("이송")  # 빈 저장소는 임베딩하지 않는다
    store.replace_document("A", [Chunk("A:1:0000", "A", "1", "이송", {})])
    store.query("이송")
    assert calls == ["fake-embedder-v1"]


# --- scripts/build_index.py ---


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "build_index", ROOT / "scripts/build_index.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cli(tmp_path, monkeypatch):
    """임베더는 가짜, Indexer는 스텁, 설정은 tmp_path를 쓰는 build_index.main."""
    script = _load_script()
    ws = Workspace(tmp_path)
    ws.add("MAN", "이송 시간 초과\n\n광전 센서")
    ws.catalog()
    monkeypatch.setattr(script, "get_settings", lambda: settings(tmp_path))
    monkeypatch.setattr(factory, "_default_embedder", lambda name: FakeEmbedder())
    monkeypatch.setattr(factory, "indexer_class", lambda: TextIndexer)

    def run(*args):
        return script.main(["--catalog", str(tmp_path / "catalog.toml"), *args])

    run.script = script
    return run


def test_cli_indexes_then_reports_unchanged(cli, capsys):
    assert cli() == 0
    assert "added        1  MAN" in capsys.readouterr().out

    assert cli() == 0
    assert "unchanged    1  MAN" in capsys.readouterr().out


def test_cli_dry_run_changes_nothing(cli, capsys):
    assert cli("--dry-run") == 0
    assert "[dry-run]" in capsys.readouterr().out
    assert cli("--dry-run") == 0
    assert "added        1  MAN" in capsys.readouterr().out  # 아직 색인 안 됨


def test_cli_exit_code_1_on_failed_document(cli, capsys, monkeypatch):
    class Failing(TextIndexer):
        def index_file(self, path, metadata):
            raise RuntimeError("파싱 실패")

    monkeypatch.setattr(factory, "indexer_class", lambda: Failing)
    assert cli() == 1
    assert "failed       1  MAN (RuntimeError: 파싱 실패)" in capsys.readouterr().out


def test_cli_exit_code_2_without_indexer(cli, capsys, monkeypatch):
    monkeypatch.setattr(factory, "indexer_class", no_indexer)
    assert cli() == 2
    assert "#6 Indexer" in capsys.readouterr().err


def test_cli_model_change_needs_recreate(cli, capsys, monkeypatch, tmp_path):
    assert cli() == 0
    monkeypatch.setattr(
        cli.script, "get_settings", lambda: settings(tmp_path, embedding_model="other")
    )

    assert cli() == 2
    assert "--recreate" in capsys.readouterr().err
    assert cli("--recreate") == 0
    assert "added        1  MAN" in capsys.readouterr().out


def test_cli_recreate_without_indexer_keeps_index(cli, capsys, monkeypatch):
    assert cli() == 0
    monkeypatch.setattr(factory, "indexer_class", no_indexer)

    assert cli("--recreate") == 2
    monkeypatch.setattr(factory, "indexer_class", lambda: TextIndexer)
    assert cli("--dry-run") == 0
    assert "unchanged    1  MAN" in capsys.readouterr().out  # 색인이 지워지지 않았다


def test_build_indexer_uses_indexer_class(monkeypatch):
    monkeypatch.setattr(factory, "indexer_class", lambda: TextIndexer)
    store = object()
    assert factory.build_indexer(store).store is store


def test_cli_catalog_error_is_exit_code_2(cli, capsys, tmp_path):
    (tmp_path / "man.txt").unlink()
    assert cli() == 2
    assert "파일 없음" in capsys.readouterr().err


def test_cli_bad_setting_is_exit_code_2(cli, capsys, monkeypatch):
    def broken():
        raise ValueError("could not convert string to float: 'abc'")

    monkeypatch.setattr(cli.script, "get_settings", broken)
    assert cli() == 2
    assert "float" in capsys.readouterr().err


def test_cli_server_unreachable_is_exit_code_2(cli, capsys, monkeypatch):
    def unreachable(settings, **kwargs):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(factory, "build_store", unreachable)
    assert cli() == 2
    assert "연결하지 못함(ConnectionError)" in capsys.readouterr().err


def test_cli_store_read_failure_is_exit_code_2_and_closes(cli, capsys, monkeypatch):
    closed = []

    class Broken:
        def documents(self, where=None):
            raise TimeoutError("read timeout")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(factory, "build_store", lambda settings, **kw: Broken())
    assert cli() == 2
    assert "상태를 읽지 못함(TimeoutError)" in capsys.readouterr().err
    assert closed == [True]


def test_real_indexer_is_connected():
    from weeing_weeing.rag.indexer import DocumentIndexer

    assert factory.indexer_class() is DocumentIndexer

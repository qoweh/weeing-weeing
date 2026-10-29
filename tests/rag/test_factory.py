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
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
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
    store.close()


def test_chroma_factory_releases_client_on_constructor_failure(tmp_path, monkeypatch):
    configured = settings(tmp_path, vector_store="chroma")
    first = factory.build_store(configured, embedder=FakeEmbedder())
    first.replace_document("A", [Chunk("A:1:0000", "A", "1", "probe", {})])
    real_client = factory._chroma_client
    closed = []

    def tracked_client(settings):
        client = real_client(settings)
        close = client.close

        def tracked_close():
            closed.append(1)
            close()

        monkeypatch.setattr(client, "close", tracked_close)
        return client

    monkeypatch.setattr(factory, "_chroma_client", tracked_client)
    try:
        from weeing_weeing.rag.store import StoreMismatchError

        with pytest.raises(StoreMismatchError):
            factory.build_store(
                dataclasses.replace(configured, embedding_model="other-model"),
                embedder=FakeEmbedder(),
            )
        assert closed == [1]
        assert first.query("probe")
    finally:
        first.close()


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
    run.ws = ws
    run.db_url = f"sqlite:///{tmp_path / 'test.db'}"
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


def test_build_retriever_uses_configured_reranker(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from weeing_weeing.rag import reranker
    from weeing_weeing.rag.store import Hit

    model = Mock()
    model.predict.return_value = [0.1, 0.9]
    load = Mock(return_value=model)
    monkeypatch.setattr(reranker, "_load_model", load)
    store = Mock()
    store.hybrid_query.return_value = [
        Hit(Chunk(f"MAN:1:{i:04d}", "MAN", "1", text), 0.03 - i * 0.01)
        for i, text in enumerate(["모터 점검", "광전 센서 점검"])
    ]
    retriever = factory.build_retriever(
        settings(
            tmp_path, reranker_model="local", rag_candidate_k=12, rag_min_relevance=0.5
        ),
        store,
    )
    load.assert_not_called()
    found = retriever.search("센서", k=2)
    assert len(found) == 1
    assert found[0].text == "광전 센서 점검"
    assert found[0].relevance == 0.9
    store.hybrid_query.assert_called_once_with("센서", k=12, where=None)


def test_factory_rejects_relevance_filter_without_reranker(tmp_path):
    with pytest.raises(ValueError, match="리랭커가 필요"):
        factory.build_retriever(
            settings(tmp_path, reranker_model="", rag_min_relevance=0.5), None
        )


def test_public_indexer_and_retriever_share_one_store(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from weeing_weeing.rag import interface

    store = Mock()
    store.hybrid_query.return_value = []
    build_store = Mock(return_value=store)
    monkeypatch.setattr(factory, "build_store", build_store)
    monkeypatch.setenv("RERANKER_MODEL", "")
    interface.get_indexer.cache_clear()
    interface.get_retriever.cache_clear()
    interface._get_store.cache_clear()
    try:
        indexer = interface.get_indexer()
        retriever = interface.get_retriever()
        assert interface.get_indexer() is indexer
        assert interface.get_retriever() is retriever
        assert retriever.search("센서") == []
        build_store.assert_called_once()
        store.hybrid_query.assert_called_once_with("센서", k=5, where=None)
    finally:
        interface.get_indexer.cache_clear()
        interface.get_retriever.cache_clear()
        interface._get_store.cache_clear()


# --- DB(document 테이블)와 함께 ---


def _db(cli):
    from weeing_weeing.db.interface import open_documents

    return open_documents(cli.db_url)


def test_cli_without_database_is_exit_code_2_with_hint(
    cli, capsys, monkeypatch, tmp_path
):
    down = settings(
        tmp_path, database_url="postgresql://x:y@127.0.0.1:9/none", db_timeout_s=1
    )
    monkeypatch.setattr(cli.script, "get_settings", lambda: down)
    assert cli() == 2
    err = capsys.readouterr().err
    assert "DB에 연결하지 못함" in err
    assert "sqlite:///storage/dev.db" in err


def test_cli_seeds_catalog_into_db_and_records_result(cli, capsys):
    assert cli() == 0
    assert "카탈로그 추가 1 · 수정 0 · 삭제 0" in capsys.readouterr().out
    [record] = _db(cli).listed()
    assert (record.doc_id, record.origin) == ("MAN", "seed")
    assert record.indexed_at is not None and record.index_error is None

    assert cli() == 0
    assert "카탈로그 추가 0 · 수정 0 · 삭제 0" in capsys.readouterr().out


def test_cli_removes_seed_dropped_from_catalog(cli, capsys):
    cli.ws.add("SOP", "정지 후 에너지 격리", doc_type="sop")
    cli.ws.catalog()
    assert cli() == 0
    del cli.ws.entries["SOP"]
    cli.ws.catalog()
    capsys.readouterr()

    assert cli() == 0
    out = capsys.readouterr().out
    assert "삭제 1" in out
    assert "removed      1  SOP" in out
    assert [r.doc_id for r in _db(cli).listed()] == ["MAN"]


def test_cli_indexes_completed_uploads_from_db(cli, capsys, tmp_path):
    from weeing_weeing.contracts import DocumentRecord

    folder = tmp_path / "uploads/u1"
    folder.mkdir(parents=True)
    (folder / "up.txt").write_text("업로드 문서 본문", encoding="utf-8")
    repo = _db(cli)
    repo.add_upload(
        DocumentRecord(
            doc_id="UP-A",
            doc_version="1.0",
            doc_type="manual",
            origin="upload",
            upload_id="u1",
            title="up.txt",
            source="u1/up.txt",
            source_sha256="sha-up",
            status="processing",
        )
    )
    assert cli() == 0
    assert "UP-A" not in capsys.readouterr().out  # 완료 전에는 목록에 없다

    repo.complete_upload("u1", chunk_count=1)
    assert cli() == 0
    assert "added        1  UP-A" in capsys.readouterr().out


def test_cli_dry_run_does_not_write_db(cli, capsys):
    assert cli("--dry-run") == 0
    assert "added        1  MAN" in capsys.readouterr().out
    assert _db(cli).listed() == []


def test_cli_imports_legacy_manifest_uploads_once(cli, capsys, tmp_path):
    """#58의 metadata.json 업로드는 DB로 옮겨져 색인에서 빠지지 않는다."""
    import hashlib
    import json

    folder = tmp_path / "uploads/old1"
    folder.mkdir(parents=True)
    (folder / "old.txt").write_text("예전 업로드 본문", encoding="utf-8")
    manifest = {
        "upload_id": "old1",
        "doc_id": "UP-OLD",
        "doc_version": "1.0",
        "doc_type": "manual",
        "doc_status": "approved",
        "asset_id": "BLDC-001",
        "title": "old.txt",
        "source": "old.txt",
        "source_sha256": hashlib.sha256("예전 업로드 본문".encode()).hexdigest(),
        "uploaded_at": "2026-10-27T01:00:00+00:00",
        "status": "completed",
        "chunk_count": 1,
    }
    (folder / "metadata.json").write_text(json.dumps(manifest), encoding="utf-8")
    broken = tmp_path / "uploads/bad"
    broken.mkdir()
    (broken / "metadata.json").write_text("{not json", encoding="utf-8")

    assert cli() == 0
    captured = capsys.readouterr()
    assert "added        2  MAN, UP-OLD" in captured.out
    assert "old1(UP-OLD)를 DB로 옮김: completed" in captured.err
    assert "bad: 옮기지 못함" in captured.err
    assert (folder / "metadata.json.imported").is_file()
    assert _db(cli).get_upload("old1").extra == {"asset_id": "BLDC-001"}

    assert cli() == 0
    assert "unchanged    2  MAN, UP-OLD" in capsys.readouterr().out

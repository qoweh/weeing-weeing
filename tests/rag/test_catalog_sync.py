"""카탈로그 검증과 sync(스텁 Indexer + FakeEmbedder + 각 저장소 백엔드)."""

from pathlib import Path

import pytest
from fakes import TextIndexer

from weeing_weeing.rag.catalog import CatalogError, file_sha256, load_catalog
from weeing_weeing.rag.store import Chunk
from weeing_weeing.rag.sync import sync

DATA = Path(__file__).resolve().parents[2] / "data"

ENTRY = """
[[documents]]
doc_id = "{doc_id}"
doc_version = "{version}"
doc_type = "{doc_type}"
status = "{status}"
path = "{path}"
title = "{doc_id} 문서"
"""


class Workspace:
    """tmp_path에 문서 파일과 catalog.toml을 만든다."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.entries: dict[str, dict] = {}

    def write(self, name: str, text: str) -> None:
        (self.root / name).write_text(text, encoding="utf-8")

    def add(self, doc_id, text, *, version="1.0", doc_type="manual", status="approved"):
        path = f"{doc_id.lower()}.txt"
        self.write(path, text)
        self.entries[doc_id] = dict(
            doc_id=doc_id, version=version, doc_type=doc_type, status=status, path=path
        )

    def catalog(self):
        body = "".join(ENTRY.format(**e) for e in self.entries.values())
        (self.root / "catalog.toml").write_text(body, encoding="utf-8")
        return load_catalog(self.root / "catalog.toml")


@pytest.fixture
def ws(tmp_path):
    w = Workspace(tmp_path)
    w.add("MAN", "이송 시간 초과 점검\n\n광전 센서 렌즈 오염")
    w.add("SOP", "정지 후 에너지 격리", doc_type="sop", status="draft")
    return w


def test_repo_catalog_is_valid():
    catalog = load_catalog(DATA / "catalog.toml")

    assert [e.doc_id for e in catalog.documents] == [
        "BTT-MANUAL",
        "BTT-RULE",
        "BTT-SOP-001",
    ]
    assert {e.doc_type for e in catalog.documents} == {"manual", "rule", "sop"}
    assert catalog.file(catalog.documents[0]).is_file()


def test_first_run_adds_then_rerun_is_unchanged(ws, store):
    indexer = TextIndexer(store)

    first = sync(ws.catalog(), indexer, store)
    assert (first.added, first.updated, first.unchanged) == (["MAN", "SOP"], [], [])
    assert first.ok

    second = sync(ws.catalog(), indexer, store)
    assert (second.added, second.updated, second.unchanged) == ([], [], ["MAN", "SOP"])
    assert indexer.calls == ["MAN", "SOP"]  # 두 번째에는 색인하지 않았다


def test_metadata_reaches_chunks(ws, store):
    sync(ws.catalog(), TextIndexer(store), store)

    chunk = store.chunks(where={"doc_id": "SOP"})[0]
    assert chunk.metadata["status"] == "draft"
    assert chunk.metadata["source_path"] == "sop.txt"
    assert chunk.metadata["source_sha256"] == file_sha256(ws.root / "sop.txt")


def test_changed_file_is_updated(ws, store):
    indexer = TextIndexer(store)
    sync(ws.catalog(), indexer, store)
    ws.write("man.txt", "새 내용\n\n둘째 청크\n\n셋째 청크")

    report = sync(ws.catalog(), indexer, store)
    assert (report.updated, report.unchanged) == (["MAN"], ["SOP"])
    assert store.documents()["MAN"].chunk_count == 3


def test_new_version_replaces_old_chunks(ws, store):
    sync(ws.catalog(), TextIndexer(store), store)
    ws.entries["MAN"]["version"] = "2.0"

    report = sync(ws.catalog(), TextIndexer(store), store)
    assert report.updated == ["MAN"]
    assert {c.doc_version for c in store.chunks(where={"doc_id": "MAN"})} == {"2.0"}


def test_status_change_without_file_change_is_updated(ws, store):
    sync(ws.catalog(), TextIndexer(store), store)
    ws.entries["SOP"]["status"] = "approved"

    assert sync(ws.catalog(), TextIndexer(store), store).updated == ["SOP"]
    assert store.chunks(where={"doc_id": "SOP"})[0].metadata["status"] == "approved"


def test_removed_from_catalog_is_deleted_but_reports_stay(ws, store):
    sync(ws.catalog(), TextIndexer(store), store)
    report_chunk = Chunk(
        "MR-1:1:0001", "MR-1", "1", "과거 정비 이력", {"doc_type": "report"}
    )
    store.replace_document("MR-1", [report_chunk])
    del ws.entries["SOP"]

    report = sync(ws.catalog(), TextIndexer(store), store)
    assert report.removed == ["SOP"]
    assert set(store.documents()) == {"MAN", "MR-1"}


def test_document_completed_meanwhile_is_not_deleted(ws, store):
    """동기화 중에 업로드 API가 새로 완료한 문서(목록을 읽은 뒤 생김)는 지우지 않는다."""
    sync(ws.catalog(), TextIndexer(store), store)
    del ws.entries["SOP"]

    report = sync(
        ws.catalog(), TextIndexer(store), store, still_listed=lambda d: d == "SOP"
    )
    assert report.removed == []
    assert set(store.documents()) == {"MAN", "SOP"}


def test_force_reindexes_everything(ws, store):
    indexer = TextIndexer(store)
    sync(ws.catalog(), indexer, store)

    report = sync(ws.catalog(), indexer, store, force=True)
    assert report.updated == ["MAN", "SOP"]
    assert indexer.calls == ["MAN", "SOP", "MAN", "SOP"]


def test_dry_run_changes_nothing(ws, store):
    report = sync(ws.catalog(), None, store, dry_run=True)

    assert report.added == ["MAN", "SOP"]
    assert store.documents() == {}
    with pytest.raises(ValueError, match="dry_run"):
        sync(ws.catalog(), None, store)


def test_one_failure_does_not_stop_others(ws, store):
    class Flaky(TextIndexer):
        def index_file(self, path, metadata):
            if metadata["doc_id"] == "MAN":
                raise RuntimeError("파싱 실패")
            return super().index_file(path, metadata)

    report = sync(ws.catalog(), Flaky(store), store)
    assert report.failed == {"MAN": "RuntimeError: 파싱 실패"}
    assert report.added == ["SOP"]
    assert not report.ok


def test_indexer_that_drops_metadata_is_reported(ws, store):
    class Forgetful(TextIndexer):
        def index_file(self, path, metadata):
            return super().index_file(
                path, {k: metadata[k] for k in ("doc_id", "doc_version")}
            )

    report = sync(ws.catalog(), Forgetful(store), store)
    assert set(report.failed) == {"MAN", "SOP"}
    assert "metadata" in report.failed["MAN"]


def test_failed_update_keeps_previous_index(ws, store_factory):
    from fakes import BrokenEmbedder

    store = store_factory()
    sync(ws.catalog(), TextIndexer(store), store)
    ws.write("man.txt", "바뀐 내용")
    broken = store_factory(embedder=BrokenEmbedder())

    report = sync(ws.catalog(), TextIndexer(broken), broken)
    assert "MAN" in report.failed
    assert store.documents()["MAN"].chunk_count == 2  # 옛 색인 그대로


# --- 카탈로그 검증 ---


def test_duplicate_doc_id_is_rejected(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    body = ENTRY.format(
        doc_id="A", version="1", doc_type="manual", status="draft", path="a.txt"
    )
    body += ENTRY.format(
        doc_id="A", version="1", doc_type="manual", status="draft", path="b.txt"
    )
    (tmp_path / "catalog.toml").write_text(body)

    with pytest.raises(CatalogError, match="doc_id 중복: A"):
        load_catalog(tmp_path / "catalog.toml")


def test_same_file_content_under_two_ids_is_rejected(tmp_path):
    (tmp_path / "a.txt").write_text("같은 내용")
    (tmp_path / "b.txt").write_text("같은 내용")
    body = ENTRY.format(
        doc_id="A", version="1", doc_type="manual", status="draft", path="a.txt"
    )
    body += ENTRY.format(
        doc_id="B", version="1", doc_type="manual", status="draft", path="b.txt"
    )
    (tmp_path / "catalog.toml").write_text(body)

    with pytest.raises(CatalogError, match="내용이 같은 파일.*A, B"):
        load_catalog(tmp_path / "catalog.toml")


def test_missing_file_is_rejected(tmp_path):
    body = ENTRY.format(
        doc_id="A", version="1", doc_type="manual", status="draft", path="x.pdf"
    )
    (tmp_path / "catalog.toml").write_text(body)

    with pytest.raises(CatalogError, match="파일 없음 x.pdf"):
        load_catalog(tmp_path / "catalog.toml")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("doc_type", "rulebook"),
        ("status", "review_draft"),
        ("doc_id", "A:B"),
        ("version", "1 0"),
    ],
)
def test_invalid_values_are_rejected(tmp_path, field, value):
    (tmp_path / "a.txt").write_text("a")
    values = dict(
        doc_id="A", version="1", doc_type="manual", status="draft", path="a.txt"
    )
    values[field] = value
    (tmp_path / "catalog.toml").write_text(ENTRY.format(**values))

    with pytest.raises(CatalogError):
        load_catalog(tmp_path / "catalog.toml")


def test_unknown_key_is_rejected(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    body = ENTRY.format(
        doc_id="A", version="1", doc_type="manual", status="draft", path="a.txt"
    )
    (tmp_path / "catalog.toml").write_text(body + 'vresion = "2"\n')

    with pytest.raises(CatalogError, match="vresion"):
        load_catalog(tmp_path / "catalog.toml")


def test_interrupted_write_is_reindexed_next_run(ws):
    """저장이 중간에 끊겨 청크가 모자란 문서는 sha가 같아도 다시 색인한다."""
    from fakes import FakeEmbedder, MemoryVectorStore

    storage: dict = {}
    store = MemoryVectorStore(storage, embedder=FakeEmbedder(), embedding_model="m")
    indexer = TextIndexer(store)
    sync(ws.catalog(), indexer, store)
    points = storage["knowledge"]["points"]
    del points["MAN:1.0:0001"]  # 2개 중 1개만 남은 상태(쓰다 끊김)
    assert store.documents()["MAN"].complete is False

    report = sync(ws.catalog(), indexer, store)
    assert report.updated == ["MAN"]
    assert store.documents()["MAN"].complete

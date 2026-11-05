import sys
from pathlib import Path

import pytest

from weeing_weeing.api import document_seed as seed
from weeing_weeing.api import documents
from weeing_weeing.db import interface as db
from weeing_weeing.rag import interface

ROOT = Path(__file__).resolve().parents[2]
MANUAL = ROOT / "data/manuals/BTT-MANUAL_v2.0.pdf"


@pytest.fixture
def env(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "tests/rag"))
    from fakes import FakeEmbedder, MemoryVectorStore

    holder = {
        "store": MemoryVectorStore({}, embedder=FakeEmbedder(), embedding_model="m")
    }
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    interface.get_indexer.cache_clear()
    monkeypatch.setattr(interface, "_get_store", lambda: holder["store"])

    def switch_collection():
        """RAG_COLLECTION을 바꾼 것처럼 빈 저장소로 갈아끼운다."""
        holder["store"] = MemoryVectorStore(
            {}, embedder=FakeEmbedder(), embedding_model="m"
        )
        interface.get_indexer.cache_clear()

    yield holder, switch_collection, tmp_path
    interface.get_indexer.cache_clear()


def manifest(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "seed.toml"
    path.write_text(body, encoding="utf-8")
    return path


MANUAL_ONLY = f"""
[[documents]]
doc_id = "BTT-MANUAL"
doc_type = "manual"
asset_id = "BLDC-001"
path = "{MANUAL.as_posix()}"
"""


def run(items, **kwargs):
    calls = []

    def index_upload(repo, upload_id):
        calls.append(upload_id)
        documents._index(repo, upload_id)

    results = seed.seed_documents(
        items, db.get_documents(), index_upload=index_upload, **kwargs
    )
    return results, calls


def test_team_manifest_points_to_existing_pdfs():
    items = seed.load_seed(ROOT / "data/seed/documents_v1.toml")
    assert {i.doc_id for i in items} == {"BTT-MANUAL", "BTT-RULE", "BTT-SOP-001"}
    assert {i.doc_type for i in items} == {"manual", "rule", "sop"}
    assert all(i.path.is_file() for i in items)


def test_seed_registers_like_web_upload_then_skips_without_embedding(env):
    holder, _, tmp_path = env
    items = seed.load_seed(manifest(tmp_path, MANUAL_ONLY))

    first, calls = run(items)
    assert [r.action for r in first] == ["added"]
    assert len(calls) == 1
    record = db.get_documents().upload_target("BTT-MANUAL")
    assert record.doc_version == "2.0"  # 파일명 규칙
    assert record.extra["asset_id"] == "BLDC-001"
    assert (documents.upload_dir() / record.source).is_file()
    assert "BTT-MANUAL" in holder["store"].documents()

    again, calls = run(items)
    assert [(r.action, r.detail) for r in again] == [("skipped", "이미 등록·임베딩됨")]
    assert calls == []  # 임베딩하지 않는다


def test_seed_reembeds_after_collection_switch(env):
    holder, switch_collection, tmp_path = env
    items = seed.load_seed(manifest(tmp_path, MANUAL_ONLY))
    run(items)
    switch_collection()

    results, calls = run(items)
    assert [r.action for r in results] == ["reindexed"]
    assert len(calls) == 1
    assert "BTT-MANUAL" in holder["store"].documents()
    # 예전 업로드는 교체 처리돼 완료된 등록은 하나만 남는다.
    listed = [d for d in db.get_documents().listed() if d.doc_id == "BTT-MANUAL"]
    assert len(listed) == 1


def test_seed_keeps_web_replaced_file_unless_replace(env):
    _, _, tmp_path = env
    other = tmp_path / "BTT-MANUAL_v2.1.pdf"
    other.write_bytes(MANUAL.read_bytes() + b"\n% web upload\n")
    run(
        seed.load_seed(
            manifest(tmp_path, MANUAL_ONLY.replace(MANUAL.as_posix(), other.as_posix()))
        )
    )

    items = seed.load_seed(manifest(tmp_path, MANUAL_ONLY))
    kept, calls = run(items)
    assert kept[0].action == "skipped" and "--replace" in kept[0].detail
    assert calls == []

    replaced, _ = run(items, replace=True)
    assert [r.action for r in replaced] == ["replaced"]
    assert db.get_documents().upload_target("BTT-MANUAL").doc_version == "2.0"


def test_seed_failure_does_not_stop_next_document(env):
    _, _, tmp_path = env
    body = MANUAL_ONLY + MANUAL_ONLY.replace('"BTT-MANUAL"', '"BTT-MANUAL-2"')
    items = seed.load_seed(manifest(tmp_path, body))

    def broken_then_real(repo, upload_id):
        if repo.get_upload(upload_id).doc_id == "BTT-MANUAL":
            raise RuntimeError("Voyage 장애")
        documents._index(repo, upload_id)

    results = seed.seed_documents(
        items, db.get_documents(), index_upload=broken_then_real
    )
    assert results[0].action == "failed"
    # 같은 파일이라 두 번째는 다른 문서 ID와 해시 중복으로 거절된다(웹과 같은 규칙).
    assert results[1].action in ("added", "skipped")


def test_explicit_version_overrides_filename(env):
    _, _, tmp_path = env
    items = seed.load_seed(manifest(tmp_path, MANUAL_ONLY + 'doc_version = "9.9"\n'))
    run(items)
    assert db.get_documents().upload_target("BTT-MANUAL").doc_version == "9.9"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (MANUAL_ONLY.replace('"manual"', '"report"'), "doc_type"),
        (MANUAL_ONLY.replace(MANUAL.as_posix(), "/없는/파일.pdf"), "PDF 파일이 없다"),
        (MANUAL_ONLY + MANUAL_ONLY, "중복"),
        (MANUAL_ONLY.replace('"BTT-MANUAL"', '"RPT-1"'), "doc_id"),
        (MANUAL_ONLY.replace('"BLDC-001"', '""'), "asset_id"),
        ("", "documents 항목이 없다"),
    ],
)
def test_load_seed_rejects_bad_manifest(tmp_path, body, message):
    with pytest.raises(ValueError, match=message):
        seed.load_seed(manifest(tmp_path, body))

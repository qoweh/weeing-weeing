"""VectorStore 계약 테스트. conftest.BACKENDS의 모든 백엔드에 같은 시나리오를 돌린다."""

import pytest
from fakes import BrokenEmbedder

from weeing_weeing.rag.store import Chunk, StoreMismatchError, make_chunk_id

MANUAL_TEXTS = [
    "이송 시간 초과 P01 광전 센서 점검 절차",
    "입구 장기 점유 P03 트레이 걸림 확인",
    "모터 기동 미도달 M01 드라이버 알람 확인",
]


def manual_chunks(version="2.0", texts=MANUAL_TEXTS, sha="sha-manual-1"):
    codes = [["BTT2-P01"], ["BTT2-P03", "BTT2-P01"], ["BTT2-M01"]]
    return [
        Chunk(
            chunk_id=make_chunk_id("BTT-MANUAL", version, seq),
            doc_id="BTT-MANUAL",
            doc_version=version,
            text=text,
            metadata={
                "doc_type": "manual",
                "status": "approved",
                "page": seq + 1,
                "codes": codes[seq % 3],
                "section": None,  # None은 키째 빠진다
                "source_sha256": sha,
                "title": "에러코드·대응 매뉴얼",
            },
        )
        for seq, text in enumerate(texts)
    ]


def sop_chunks():
    return [
        Chunk(
            chunk_id=make_chunk_id("BTT-SOP-001", "1.1", 0),
            doc_id="BTT-SOP-001",
            doc_version="1.1",
            text="정지 후 에너지 격리 절차와 재가동 승인",
            metadata={
                "doc_type": "sop",
                "status": "draft",
                "codes": [],  # 빈 리스트는 키째 빠진다
                "source_sha256": "sha-sop-1",
            },
        )
    ]


@pytest.fixture
def filled(store):
    store.replace_document("BTT-MANUAL", manual_chunks())
    store.replace_document("BTT-SOP-001", sop_chunks())
    return store


def ids(hits_or_chunks):
    return [getattr(x, "chunk", x).chunk_id for x in hits_or_chunks]


def test_chunk_id_format():
    assert make_chunk_id("BTT-MANUAL", "2.0", 12) == "BTT-MANUAL:2.0:0012"


def test_empty_store_returns_nothing(store):
    assert store.query("아무거나") == []
    assert store.documents() == {}
    assert store.chunks() == []
    assert store.delete_document("BTT-MANUAL") == 0


def test_replace_then_query_returns_stored_chunk(filled):
    hits = filled.query(MANUAL_TEXTS[1], k=2)

    assert ids(hits)[0] == "BTT-MANUAL:2.0:0001"
    chunk = hits[0].chunk
    assert chunk.text == MANUAL_TEXTS[1]
    assert chunk.doc_version == "2.0"
    assert chunk.metadata["codes"] == ["BTT2-P03", "BTT2-P01"]
    assert chunk.metadata["page"] == 2
    assert "section" not in chunk.metadata
    assert hits[0].score == pytest.approx(1.0, abs=1e-3)  # 같은 텍스트 = cosine 1
    assert hits[0].score >= hits[1].score


def test_query_respects_k(filled):
    assert len(filled.query("확인", k=1)) == 1
    assert len(filled.query("확인", k=10)) == 4


def test_replace_same_document_twice_has_no_duplicates(filled):
    filled.replace_document("BTT-MANUAL", manual_chunks())

    assert len(filled.chunks()) == 4
    assert filled.documents()["BTT-MANUAL"].chunk_count == 3


def test_new_version_removes_old_chunks(filled):
    filled.replace_document("BTT-MANUAL", manual_chunks("2.1", MANUAL_TEXTS[:2]))

    manual = filled.chunks(where={"doc_id": "BTT-MANUAL"})
    assert ids(manual) == ["BTT-MANUAL:2.1:0000", "BTT-MANUAL:2.1:0001"]
    assert all("2.0" not in h.chunk.chunk_id for h in filled.query("확인", k=10))


def test_delete_document(filled):
    assert filled.delete_document("BTT-MANUAL") == 3
    assert filled.delete_document("BTT-MANUAL") == 0
    assert ids(filled.chunks()) == ["BTT-SOP-001:1.1:0000"]


@pytest.mark.parametrize(
    ("where", "expected"),
    [
        ({"doc_type": "sop"}, ["BTT-SOP-001:1.1:0000"]),
        ({"status": ["draft", "approved"]}, None),  # None = 전부
        ({"codes": "BTT2-P01"}, ["BTT-MANUAL:2.0:0000", "BTT-MANUAL:2.0:0001"]),
        (
            {"codes": ["BTT2-M01", "BTT2-P03"]},
            ["BTT-MANUAL:2.0:0001", "BTT-MANUAL:2.0:0002"],
        ),
        ({"doc_type": "manual", "codes": "BTT2-M01"}, ["BTT-MANUAL:2.0:0002"]),
        ({"doc_type": "sop", "codes": "BTT2-M01"}, []),
        ({"page": 3}, ["BTT-MANUAL:2.0:0002"]),
    ],
)
def test_where_filter_in_chunks_and_query(filled, where, expected):
    all_ids = ids(filled.chunks())
    expected = all_ids if expected is None else expected

    assert ids(filled.chunks(where=where)) == expected
    assert sorted(ids(filled.query("확인 점검", k=10, where=where))) == expected


def test_empty_list_in_where_is_rejected(filled):
    with pytest.raises(ValueError, match="빈 리스트"):
        filled.query("확인", where={"codes": []})


def test_documents_summarizes_each_doc(filled):
    docs = filled.documents()

    assert set(docs) == {"BTT-MANUAL", "BTT-SOP-001"}
    manual = docs["BTT-MANUAL"]
    assert (manual.doc_version, manual.source_sha256, manual.chunk_count) == (
        "2.0",
        "sha-manual-1",
        3,
    )
    assert manual.metadata == {
        "doc_type": "manual",
        "status": "approved",
        "title": "에러코드·대응 매뉴얼",
        "source_sha256": "sha-manual-1",
    }


def test_chunks_are_sorted_by_chunk_id(filled):
    found = ids(filled.chunks())
    assert found == sorted(found)


def test_invalid_input_is_rejected_before_writing(store):
    good = manual_chunks()
    with pytest.raises(ValueError, match="빈 chunks"):
        store.replace_document("BTT-MANUAL", [])
    with pytest.raises(ValueError, match="doc_id"):
        store.replace_document("OTHER", good)
    with pytest.raises(ValueError, match="중복"):
        store.replace_document("BTT-MANUAL", [good[0], good[0]])
    bad_meta = Chunk("BTT-MANUAL:2.0:0000", "BTT-MANUAL", "2.0", "t", {"x": {"a": 1}})
    with pytest.raises(TypeError, match="dict"):
        store.replace_document("BTT-MANUAL", [bad_meta])
    assert store.chunks() == []


def test_metadata_doc_id_must_match_chunk(store):
    chunk = Chunk("A:1:0000", "A", "1", "t", {"doc_id": "B"})
    with pytest.raises(ValueError, match="doc_id"):
        store.replace_document("A", [chunk])


def test_failed_embedding_keeps_existing_index(store_factory):
    store_factory().replace_document("BTT-MANUAL", manual_chunks())

    broken = store_factory(embedder=BrokenEmbedder())
    with pytest.raises(RuntimeError, match="임베딩 실패"):
        broken.replace_document("BTT-MANUAL", manual_chunks("2.1"))

    assert len(store_factory().chunks()) == 3


def test_reopen_with_other_embedding_model_is_rejected(store_factory):
    store_factory().replace_document("BTT-MANUAL", manual_chunks())

    with pytest.raises(StoreMismatchError, match="embedding_model"):
        store_factory(embedding_model="other-model")
    assert len(store_factory().chunks()) == 3  # 같은 모델로는 다시 열린다


def test_chunk_id_must_start_with_doc_and_version(store):
    other = Chunk("OTHER:2.0:0000", "BTT-MANUAL", "2.0", "t", {})
    with pytest.raises(ValueError, match="BTT-MANUAL:2.0:로 시작"):
        store.replace_document("BTT-MANUAL", [other])


def test_k_must_be_positive(filled):
    with pytest.raises(ValueError, match="k는 1 이상"):
        filled.query("확인", k=0)


def test_system_key_is_hidden_and_reserved(filled):
    assert all("chunk_total" not in c.metadata for c in filled.chunks())
    bad = Chunk("A:1:0000", "A", "1", "t", {"chunk_total": 9})
    with pytest.raises(ValueError, match="chunk_total"):
        filled.replace_document("A", [bad])


def test_documents_can_be_filtered_and_are_complete(filled):
    docs = filled.documents(where={"doc_id": "BTT-SOP-001"})
    assert list(docs) == ["BTT-SOP-001"]
    assert docs["BTT-SOP-001"].complete

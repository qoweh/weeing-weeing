"""store.py 공용 헬퍼. 저장이 중간에 끊긴 문서를 doc_infos가 알아내는지."""

from weeing_weeing.rag.store import doc_infos


def payload(seq, *, total=3, version="2.0", sha="a"):
    return {
        "chunk_id": f"D:{version}:{seq:04d}",
        "doc_id": "D",
        "doc_version": version,
        "text": "t",
        "chunk_total": total,
        "source_sha256": sha,
    }


def test_all_chunks_present_is_complete():
    info = doc_infos([payload(0), payload(1), payload(2)])["D"]
    assert (info.chunk_count, info.complete) == (3, True)


def test_missing_chunks_is_incomplete():
    # 새 청크 3개 중 2개만 쓰고 끊겼다
    assert doc_infos([payload(0), payload(1)])["D"].complete is False


def test_old_and_new_chunks_mixed_is_incomplete():
    # 같은 ID를 일부만 새 내용(sha b)으로 덮고 끊겼다
    mixed = [payload(0, sha="b"), payload(1, sha="a"), payload(2, sha="a")]
    assert doc_infos(mixed)["D"].complete is False


def test_old_and_new_versions_mixed_is_incomplete():
    mixed = [payload(0, version="2.1", total=1), payload(0), payload(1), payload(2)]
    info = doc_infos(mixed)["D"]
    assert info.complete is False
    assert info.doc_version == "2.0"  # 대표값은 chunk_id가 가장 앞선 청크

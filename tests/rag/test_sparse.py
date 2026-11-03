import pytest

from weeing_weeing.rag.sparse import (
    Bm25Index,
    KiwiBm25Encoder,
    SparseVec,
    idf,
    normalize_code,
    term_id,
)
from weeing_weeing.rag.store import rrf


@pytest.fixture(scope="module")
def enc() -> KiwiBm25Encoder:
    return KiwiBm25Encoder()


@pytest.mark.parametrize(
    ("text", "codes"),
    [
        ("BTT2-P03 입구 장기 점유", ["btt2-p03"]),
        ("P01/P06 확인", ["btt2-p01", "btt2-p06"]),  # 매뉴얼의 짧은 표기
        ("센서 S01과 S07", ["s01", "s07"]),
        ("XP01 P012 S08 BTT2-P01X", []),  # 코드가 아닌 것
        ("p03 대응, btt2-m12, s01", ["btt2-p03", "btt2-m12", "s01"]),  # 소문자 입력
    ],
)
def test_codes_are_extracted_before_kiwi(enc, text, codes):
    tokens = enc.tokenize(text)
    assert [t for t in tokens if t.startswith(("btt2-", "s0"))] == codes
    if codes:
        assert "btt" not in tokens  # Kiwi가 BTT/2/-/P/01로 쪼개지 않았다


def test_normalize_code():
    assert normalize_code("P01") == "BTT2-P01"
    assert normalize_code("BTT2-M12") == "BTT2-M12"
    assert normalize_code("S03") == "S03"


def test_inflected_korean_matches_query(enc):
    doc = set(enc.tokenize("이송시간이 초과되면 광전센서를 점검한다"))
    query = set(enc.tokenize("이송시간 초과"))

    assert query == {"이송", "시간", "초과"}
    assert query <= doc


def test_user_dictionary_keeps_domain_terms(enc):
    assert "광전센서" in enc.tokenize("광전센서 렌즈 오염")
    assert "반구동측" in enc.tokenize("반구동측 베어링")


def test_verbs_and_particles_are_dropped(enc):
    assert enc.tokenize("모터가 멈췄다") == ["모터"]


def test_term_id_is_stable_32bit():
    assert term_id("센서") == term_id("센서")
    assert term_id("센서") != term_id("모터")
    assert 0 <= term_id("센서") < 2**32


def test_document_vector_is_bm25_tf_saturation(enc):
    vec = enc.encode_document("센서 센서 모터")  # 토큰 3개
    by_term = dict(zip(vec.indices, vec.values, strict=True))

    norm = 1.2 * (1 - 0.75 + 0.75 * 3 / 256)
    assert by_term[term_id("센서")] == pytest.approx(2 * 2.2 / (2 + norm))
    assert by_term[term_id("모터")] == pytest.approx(1 * 2.2 / (1 + norm))
    assert vec.indices == sorted(vec.indices)


def test_query_vector_is_one_per_unique_token(enc):
    vec = enc.encode_query("센서 센서 모터")
    assert sorted(vec.indices) == sorted({term_id("센서"), term_id("모터")})
    assert vec.values == [1.0, 1.0]


def test_empty_text_has_empty_vector(enc):
    assert enc.encode_query("— · !") == SparseVec([], [])


def test_idf_formula():
    assert idf(1, 2) == pytest.approx(0.6931471824645996)  # Qdrant 실측값 ln 2


def test_bm25_index_scores_with_corpus_idf():
    index = Bm25Index({"a": SparseVec([1, 2], [1.0, 0.5]), "b": SparseVec([2], [1.0])})
    scores = index.scores(SparseVec([1, 2], [1.0, 1.0]))

    assert scores["a"] == pytest.approx(1.0 * idf(1, 2) + 0.5 * idf(2, 2))
    assert scores["b"] == pytest.approx(1.0 * idf(2, 2))
    assert index.scores(SparseVec([9], [1.0])) == {}


def test_rrf_matches_qdrant_formula():
    fused = dict(rrf([["a", "b", "c"], ["b", "a"]]))

    assert fused["a"] == pytest.approx(1 / 60 + 1 / 61)
    assert fused["b"] == pytest.approx(1 / 61 + 1 / 60)
    assert fused["c"] == pytest.approx(1 / 62)
    assert rrf([["x"]], k=2) == [("x", 0.5)]


def test_rrf_breaks_ties_by_id():
    assert [key for key, _ in rrf([["b", "a"], ["a", "b"]])] == ["a", "b"]

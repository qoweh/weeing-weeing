"""#28 E2E 검증 도구. 스텁 Indexer + FakeEmbedder로 모든 저장소 백엔드에서 돈다."""

import importlib.util
from pathlib import Path

import pytest
from fakes import FakeEmbedder, TextIndexer
from test_catalog_sync import Workspace

from weeing_weeing.rag import factory
from weeing_weeing.rag.e2e import (
    EvalQuery,
    EvaluationEmbedder,
    QueryError,
    format_markdown,
    is_hit,
    load_queries,
    run_backend,
)
from weeing_weeing.rag.retriever import HybridRetriever
from weeing_weeing.rag.store import Chunk

ROOT = Path(__file__).resolve().parents[2]
QUERIES = [
    EvalQuery(id="q1", query="입구 장기 점유 대응", doc_id="MAN", any_of=("점유",)),
    EvalQuery(id="q2", query="에너지 격리 절차", doc_id="SOP", any_of=("격리",)),
    EvalQuery(
        id="q3",
        query="에너지 격리 절차",
        doc_id="SOP",
        any_of=("격리",),
        where={"doc_type": "sop"},
    ),
    EvalQuery(id="q4", query="없는 내용", doc_id="MAN", any_of=("존재하지않는말",)),
]


@pytest.fixture
def ws(tmp_path):
    w = Workspace(tmp_path)
    w.add("MAN", "입구 장기 점유 대응 절차\n\n벨트 미끄러짐 점검\n\n모터 기동 확인")
    w.add("SOP", "정지 후 에너지 격리 절차\n\n재가동 승인", doc_type="sop")
    return w


def run(store, ws, indexer=TextIndexer, k=2):
    return run_backend("test", store, ws.catalog(), indexer, QUERIES, k=k)


def test_embedding_cache_separates_document_and_query_and_protects_vectors():
    from unittest.mock import Mock

    model = Mock()
    model.embed_documents.return_value = [[1.0, 2.0]]
    model.embed_query.return_value = [3.0, 4.0]
    cached = EvaluationEmbedder(model)
    cached.embed_documents(["같은 본문"])[0][0] = -1.0
    cached.embed_query("같은 본문")[0] = -2.0
    assert cached.embed_documents(["같은 본문"]) == [[1.0, 2.0]]
    assert cached.embed_query("같은 본문") == [3.0, 4.0]
    model.embed_documents.assert_called_once_with(["같은 본문"])
    model.embed_query.assert_called_once_with("같은 본문")


def test_embedding_cache_does_not_keep_failed_or_incomplete_outputs():
    from unittest.mock import Mock

    model = Mock()
    model.embed_documents.side_effect = [[], [[1.0]]]
    model.embed_query.side_effect = [RuntimeError("추론 실패"), [2.0]]
    cached = EvaluationEmbedder(model)
    with pytest.raises(ValueError, match="개수"):
        cached.embed_documents(["본문"])
    assert cached.embed_documents(["본문"]) == [[1.0]]
    with pytest.raises(RuntimeError, match="추론 실패"):
        cached.embed_query("질문")
    assert cached.embed_query("질문") == [2.0]


def test_cached_evaluation_preserves_rankings_and_update_checks(ws, store_factory):
    from unittest.mock import Mock

    # Chroma는 재색인하면 동점 후보 순서가 달라질 수 있다. 정답 1위가 분명한
    # 질의로 비교하고, 같은 질문의 필터 유무는 그대로 포함한다.
    queries = QUERIES[:3]
    raw = FakeEmbedder()
    raw.embed_query = Mock(wraps=raw.embed_query)
    store = store_factory(embedder=raw)
    before = run_backend(
        "test",
        store,
        ws.catalog(),
        TextIndexer,
        queries,
        k=1,
        retriever=HybridRetriever(store),
    )
    model = FakeEmbedder()
    model.embed_query = Mock(wraps=model.embed_query)
    store = store_factory(embedder=EvaluationEmbedder(model))
    after = run_backend(
        "test",
        store,
        ws.catalog(),
        TextIndexer,
        queries,
        k=1,
        retriever=HybridRetriever(store),
    )
    assert before.ok and after.ok
    assert before.results == after.results
    assert before.summaries() == after.summaries()
    assert before.chunk_counts == after.chunk_counts
    assert model.calls < raw.calls
    assert model.embed_query.call_count < raw.embed_query.call_count


def test_progress_is_emitted_before_search_and_after_completion(ws, store):
    from types import SimpleNamespace

    events = []

    def search(*args, **kwargs):
        assert events[-1] == "[test] 질의 1/1 q1 시작"
        return []

    result = run_backend(
        "test",
        store,
        ws.catalog(),
        TextIndexer,
        [QUERIES[0]],
        retriever=SimpleNamespace(search=search),
        progress=events.append,
    )
    assert result.ok
    assert events[0].startswith("[test] 색인 시작")
    assert any("질의 1/1 q1 완료:" in event for event in events)
    assert events[-2] == "[test] 갱신 검사 시작"
    assert events[-1].startswith("[test] 검사 종료: 총 ")


# --- 질의 파일 ---


def test_repo_query_set_is_valid():
    queries = load_queries(ROOT / "data/eval/rag_queries_v1.toml")
    assert len(queries) >= 30
    assert sum(q.expect_no_evidence for q in queries) >= 5
    assert {q.doc_id for q in queries if not q.expect_no_evidence} == {
        "BTT-MANUAL",
        "BTT-RULE",
        "BTT-SOP-001",
    }
    assert len({q.id for q in queries}) == len(queries)


def test_repo_answer_keywords_exist_in_source_previews():
    previews = {
        "BTT-MANUAL": "BTT-MANUAL_v2.0.md",
        "BTT-RULE": "BTT-RULE_v2.0.md",
        "BTT-SOP-001": "BTT-SOP-001.md",
    }
    texts = {
        doc: (ROOT / "data/parsed" / name).read_text(encoding="utf-8")
        for doc, name in previews.items()
    }
    for query in load_queries(ROOT / "data/eval/rag_queries_v1.toml"):
        if not query.expect_no_evidence:
            assert any(word in texts[query.doc_id] for word in query.any_of), query.id


@pytest.mark.parametrize(
    "body",
    [
        'id = "a"\nquery = "q"\ndoc_id = "D"\nany_of = []',  # 빈 키워드
        'id = "a"\nquery = "q"\ndoc_id = "D"\nany_of = ["k"]\nanswer = "x"',  # 오타 키
    ],
)
def test_invalid_query_file_is_rejected(tmp_path, body):
    path = tmp_path / "q.toml"
    path.write_text("[[queries]]\n" + body, encoding="utf-8")
    with pytest.raises(QueryError):
        load_queries(path)


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"doc_id": "MAN"},
        {"any_of": ("점유",)},
        {"expect_no_evidence": True, "doc_id": "MAN"},
        {"expect_no_evidence": True, "any_of": ("점유",)},
        {"expect_no_evidence": "false"},
    ],
)
def test_query_requires_explicit_consistent_answer_expectation(extra):
    with pytest.raises(ValueError):
        EvalQuery(id="invalid", query="질문", **extra)


def test_no_evidence_is_loaded_without_fake_answer(tmp_path):
    path = tmp_path / "queries.toml"
    path.write_text(
        '[[queries]]\nid="outside"\nquery="용접 토치"\nexpect_no_evidence=true\n',
        encoding="utf-8",
    )
    [query] = load_queries(path)
    assert query.expect_no_evidence and query.doc_id is None and not query.any_of


def test_duplicate_query_id_is_rejected(tmp_path):
    one = '[[queries]]\nid = "a"\nquery = "q"\ndoc_id = "D"\nany_of = ["k"]\n'
    (tmp_path / "q.toml").write_text(one + one, encoding="utf-8")
    with pytest.raises(QueryError, match="중복"):
        load_queries(tmp_path / "q.toml")


def test_hit_needs_same_doc_and_a_keyword():
    q = QUERIES[0]
    assert is_hit(Chunk("MAN:1.0:0000", "MAN", "1.0", "장기 점유 대응", {}), q)
    assert not is_hit(Chunk("SOP:1.0:0000", "SOP", "1.0", "장기 점유 대응", {}), q)
    assert not is_hit(Chunk("MAN:1.0:0001", "MAN", "1.0", "벨트 점검", {}), q)


# --- 한 백엔드 실행 ---


def test_index_rerun_and_update_checks_pass(ws, store):
    result = run(store, ws)

    assert result.indexed.added == ["MAN", "SOP"]
    assert result.chunk_counts == {"MAN": 3, "SOP": 2}
    assert result.rerun_unchanged
    assert result.update_ok, result.update_detail
    assert result.ok


def test_update_check_bumps_version_and_old_chunks_are_gone(ws, store):
    result = run(store, ws)

    versions = {c.doc_version for c in store.chunks(where={"doc_id": "MAN"})}
    assert versions == {"1.0-e2e"}
    assert "MAN" in result.update_detail


def test_queries_are_ranked_in_both_modes(ws, store):
    result = run(store, ws)
    by = {(r.query_id, r.mode): r for r in result.results}

    for mode in ("dense", "hybrid"):
        assert by[("q1", mode)].rank == 1  # 1부터 센다
        assert by[("q4", mode)].rank is None  # 상위 k개 안에 정답 없음
        assert len(by[("q1", mode)].top) <= 2
    assert all(h.chunk.doc_id == "SOP" for h in by[("q3", "hybrid")].top)  # where 적용


def test_summary_counts_hits(ws, store):
    summary = {s.mode: s for s in run(store, ws).summaries()}

    assert summary["hybrid"].total == 4
    assert summary["hybrid"].hit_at_k == 3  # q4만 실패
    assert 0 < summary["hybrid"].mrr <= 1


def test_missing_metadata_is_counted(ws, store):
    result = run(store, ws)
    # 스텁 Indexer는 section·citation·codes·page를 채우지 않는다 → 전부 빠짐으로 센다
    assert result.missing_metadata["citation"] == 5
    assert set(result.missing_metadata) == {"section", "page", "codes", "citation"}


def test_failed_indexing_marks_run_not_ok(ws, store):
    class Forgetful(TextIndexer):  # 카탈로그 metadata를 청크에 안 넣는다
        def index_file(self, path, metadata):
            return super().index_file(
                path, {k: metadata[k] for k in ("doc_id", "doc_version")}
            )

    result = run(store, ws, indexer=Forgetful)
    assert set(result.indexed.failed) == {"MAN", "SOP"}
    assert not result.ok
    assert result.results == []  # 빈 색인을 근거 없음 성공으로 측정하지 않는다


@pytest.mark.parametrize("rejected", [False, True])
def test_no_evidence_rejection_is_separate_from_ranking(ws, store, rejected):
    from types import SimpleNamespace

    query = EvalQuery(id="outside", query="용접 토치", expect_no_evidence=True)
    retriever = SimpleNamespace(
        search=lambda *args, **kwargs: (
            []
            if rejected
            else [SimpleNamespace(doc_id="MAN", text="점유", relevance=0.1)]
        )
    )
    result = run_backend(
        "test",
        store,
        ws.catalog(),
        TextIndexer,
        [QUERIES[0], query],
        k=2,
        retriever=retriever,
    )
    summary = {s.mode: s for s in result.summaries()}
    assert summary["hybrid"].total == 1
    assert summary["hybrid"].hit_at_k == 1
    assert summary["hybrid"].no_evidence_total == 1
    assert summary["hybrid"].rejected == 0
    assert summary["reranked"].rejected == int(rejected)
    assert summary["reranked"].no_evidence_total == 1


def test_report_shows_measured_relevance_and_negative_outcomes(ws, store):
    from types import SimpleNamespace

    from weeing_weeing.contracts import Evidence

    evidence = Evidence(
        evidence_id="MAN:1:0",
        doc_id="MAN",
        doc_version="1",
        text="입구 점유",
        citation="MAN 1",
        score=0.033,
        relevance=0.82,
    )
    retriever = SimpleNamespace(search=lambda *args, **kwargs: [evidence])
    outside = EvalQuery(id="outside", query="용접 토치", expect_no_evidence=True)
    result = run_backend(
        "test",
        store,
        ws.catalog(),
        TextIndexer,
        [QUERIES[0], outside],
        k=1,
        retriever=retriever,
    )
    report = format_markdown([result], k=1)
    assert "| test | reranked | 1/1 | 1/1 | 1.000 |" in report
    assert "| test | reranked | 0/1 | 1 |" in report
    assert "| test | 정답 있음 | 1 | 0.8200 | 0.8200 | 0.8200 |" in report
    assert "outside** reranked 근거 오반환" in report
    assert "relevance=0.8200" in report


def test_only_negative_queries_have_no_ranking_denominator(ws, store):
    from types import SimpleNamespace

    outside = EvalQuery(id="outside", query="용접 토치", expect_no_evidence=True)
    result = run_backend(
        "test",
        store,
        ws.catalog(),
        TextIndexer,
        [outside],
        retriever=SimpleNamespace(search=lambda *args, **kwargs: []),
    )
    summary = {s.mode: s for s in result.summaries()}["reranked"]
    assert summary.total == 0 and summary.mrr == 0
    assert summary.rejected == summary.no_evidence_total == 1
    assert "outside** reranked 근거 없음 거절 성공" in format_markdown([result], k=5)


def test_markdown_report(ws, store):
    md = format_markdown([run(store, ws)], k=2)

    assert "| 백엔드 | 방식 | hit@1 | hit@2 | MRR |" in md
    assert "| test | hybrid |" in md
    assert "q1" in md and "q4" in md
    assert "멱등" in md and "갱신" in md


def test_e2e_evaluates_public_retriever_and_writes_reranked_results(ws, store):
    class KeywordReranker:
        def rerank(self, query, hits):
            return sorted(hits, key=lambda h: "재가동" in h.chunk.text, reverse=True)

    query = EvalQuery(id="restart", query="승인", doc_id="SOP", any_of=("재가동",))
    retriever = HybridRetriever(store, reranker=KeywordReranker(), candidate_k=10)
    result = run_backend(
        "test", store, ws.catalog(), TextIndexer, [query], k=1, retriever=retriever
    )
    reranked = next(r for r in result.results if r.mode == "reranked")
    assert reranked.rank == 1
    assert reranked.top[0].text == "재가동 승인"
    assert {s.mode for s in result.summaries()} == {"dense", "hybrid", "reranked"}
    md = format_markdown([result], k=1)
    assert "| test | reranked | 1/1 | 1/1 | 1.000 |" in md
    assert reranked.top[0].evidence_id in md


# --- 실행 스크립트 ---


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "verify_rag_e2e", ROOT / "scripts/verify_rag_e2e.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cli(ws, tmp_path, monkeypatch):
    script = _load_script()
    ws.catalog()  # catalog.toml 쓰기
    queries = tmp_path / "queries.toml"
    queries.write_text(
        '[[queries]]\nid = "q1"\nquery = "입구 장기 점유"\ndoc_id = "MAN"\n'
        'any_of = ["점유"]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("EMBEDDING_MODEL", "fake-embedder-v1")
    monkeypatch.setenv("RERANKER_MODEL", "")  # 기본값(실제 모델)을 쓰지 않는다
    monkeypatch.delenv("QDRANT_URL", raising=False)
    monkeypatch.setattr(factory, "_default_embedder", lambda name: FakeEmbedder())
    monkeypatch.setattr(factory, "indexer_class", lambda: TextIndexer)
    out = tmp_path / "report.md"

    def run_cli(*args):
        return script.main(
            [
                "--catalog",
                str(tmp_path / "catalog.toml"),
                "--queries",
                str(queries),
                "--out",
                str(out),
                *args,
            ]
        )

    run_cli.out = out
    return run_cli


def test_cli_runs_local_backends_and_writes_report(cli, capsys):
    assert cli("--backends", "qdrant,chroma") == 0
    report = cli.out.read_text(encoding="utf-8")
    assert "| qdrant | hybrid |" in report and "| chroma | dense |" in report
    output = capsys.readouterr().out
    assert "질의 1/1 q1 시작" in output
    assert "질의 1/1 q1 완료:" in output
    assert "결과 저장" in output
    assert "실행 중 임베딩 캐시: 사용" in report


def test_cli_can_disable_embedding_cache_for_timing(cli):
    assert cli("--backends", "qdrant", "--no-embedding-cache") == 0
    assert "실행 중 임베딩 캐시: 미사용" in cli.out.read_text(encoding="utf-8")


def test_cli_without_indexer_is_exit_code_2(cli, capsys, monkeypatch):
    def missing():
        raise NotImplementedError("#6 Indexer가 아직 없다")

    monkeypatch.setattr(factory, "indexer_class", missing)
    assert cli() == 2
    assert "#6 Indexer" in capsys.readouterr().err


def test_cli_server_backend_needs_url(cli, capsys):
    assert cli("--backends", "qdrant-server") == 2
    assert "QDRANT_URL" in capsys.readouterr().err


def test_cli_keeps_finished_results_when_a_backend_cannot_start(
    cli, capsys, monkeypatch
):
    """서버가 꺼져 있어도 이미 끝난 백엔드 결과는 보고서에 남는다."""
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:9")  # 닫힌 포트
    assert cli("--backends", "chroma,qdrant-server") == 2
    report = cli.out.read_text(encoding="utf-8")
    assert "| chroma | hybrid |" in report
    assert "시작하지 못한 백엔드" in report and "qdrant-server" in report
    assert "qdrant-server] 시작하지 못함" in capsys.readouterr().err


def test_cli_configured_reranker_is_measured(cli, monkeypatch):
    from unittest.mock import Mock

    from weeing_weeing.rag import reranker

    model = Mock()
    model.predict.side_effect = lambda pairs, **kw: [1.0] * len(pairs)
    load = Mock(return_value=model)
    monkeypatch.setenv("RERANKER_MODEL", "local-model")
    monkeypatch.setattr(reranker, "_load_model", load)
    assert cli("--backends", "qdrant,chroma") == 0
    report = cli.out.read_text(encoding="utf-8")
    assert "| qdrant | reranked |" in report
    assert "| chroma | reranked |" in report
    load.assert_called_once_with("local-model")


def test_cli_reranker_failure_is_reported_as_failure(cli, monkeypatch, capsys):
    from unittest.mock import Mock

    from weeing_weeing.rag import reranker

    monkeypatch.setenv("RERANKER_MODEL", "missing-local-model")
    monkeypatch.setattr(reranker, "_load_model", Mock(side_effect=OSError("모델 없음")))
    assert cli("--backends", "qdrant") == 2
    assert "검증 실패" in capsys.readouterr().err
    assert "모델 없음" in cli.out.read_text(encoding="utf-8")


# --- Incident 코드 질의 (#8) ---


def test_repo_query_set_has_incident_code_queries():
    queries = load_queries(ROOT / "data/eval/rag_queries_v1.toml")
    coded = [q for q in queries if q.codes]
    assert len(coded) >= 5
    assert coded[0].text.startswith("P03 ")


@pytest.mark.parametrize(
    "body",
    [
        'id = "a"\nquery = "q"\ncodes = ["BTT2-P03"]\ndoc_id = "D"\nany_of = ["k"]',
        'id = "a"\ndoc_id = "D"\nany_of = ["k"]',
        'id = "a"\ncodes = []\ndoc_id = "D"\nany_of = ["k"]',
        'id = "a"\nquery = "q"\ncodes = []\ndoc_id = "D"\nany_of = ["k"]',
        'id = "a"\ncodes = ["BTT2-P3"]\ndoc_id = "D"\nany_of = ["k"]',  # 오타 코드
    ],
)
def test_query_needs_exactly_one_of_text_or_codes(tmp_path, body):
    path = tmp_path / "q.toml"
    path.write_text("[[queries]]\n" + body, encoding="utf-8")
    with pytest.raises(QueryError):
        load_queries(path)


def test_code_query_is_searched_with_generated_text(ws, store):
    coded = EvalQuery(id="c1", codes=("BTT2-P03",), doc_id="MAN", any_of=("점유",))
    result = run_backend("test", store, ws.catalog(), TextIndexer, [coded], k=2)
    by = {r.mode: r for r in result.results}
    assert by["hybrid"].rank == 1  # "입구 장기 점유"가 MAN 본문과 맞는다

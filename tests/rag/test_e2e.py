"""#28 E2E 검증 도구. 스텁 Indexer + FakeEmbedder로 모든 저장소 백엔드에서 돈다."""

import importlib.util
from pathlib import Path

import pytest
from fakes import FakeEmbedder, TextIndexer
from test_catalog_sync import Workspace

from weeing_weeing.rag import factory
from weeing_weeing.rag.e2e import (
    EvalQuery,
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


# --- 질의 파일 ---


def test_repo_query_set_is_valid():
    queries = load_queries(ROOT / "data/eval/rag_queries_v1.toml")
    assert len(queries) >= 10
    assert {q.doc_id for q in queries} == {"BTT-MANUAL", "BTT-RULE", "BTT-SOP-001"}
    assert len({q.id for q in queries}) == len(queries)


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
    assert "결과 저장" in capsys.readouterr().out


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

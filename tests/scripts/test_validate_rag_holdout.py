import importlib.util
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from weeing_weeing.rag.e2e import EvalQuery, load_queries
from weeing_weeing.rag.eval_corpus import file_sha256, load_corpus
from weeing_weeing.rag.eval_sync import index_metadata
from weeing_weeing.rag.indexer import DocumentIndexer
from weeing_weeing.rag.store import Chunk, Hit

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "validate_rag_holdout", ROOT / "scripts/validate_rag_holdout.py"
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_holdout_is_disjoint_balanced_and_grounded_in_actual_body():
    queries = load_queries(ROOT / "data/eval/rag_queries_holdout_v1.toml")
    previous = load_queries(ROOT / "data/eval/rag_queries_v1.toml")
    assert len(queries) == 24
    assert sum(q.expect_no_evidence for q in queries) == 12
    assert not ({q.text for q in queries} & {q.text for q in previous})
    assert Counter(q.doc_id for q in queries if not q.expect_no_evidence) == {
        "BTT-MANUAL": 4,
        "BTT-RULE": 4,
        "BTT-SOP-001": 4,
    }
    pieces = []

    def capture(doc_id, chunks):
        pieces.extend(chunks)
        return len(chunks)

    store = SimpleNamespace(documents=lambda **kw: {}, replace_document=capture)
    indexer = DocumentIndexer(store, chunking="structured")
    corpus = load_corpus(ROOT / "data/eval/rag_documents_v1.toml")
    for entry in corpus.documents:
        indexer.index_file(
            corpus.file(entry), index_metadata(entry, file_sha256(corpus.file(entry)))
        )
    for query in queries:
        if not query.expect_no_evidence:
            assert any(
                c.doc_id == query.doc_id
                and any(word in c.text.split("\n\n", 1)[-1] for word in query.any_of)
                for c in pieces
            ), query.id


def test_threshold_is_inclusive_and_applied_before_final_k():
    query = EvalQuery(id="q", query="질문", doc_id="D", any_of=("정답",))
    hits = [
        Hit(Chunk(str(i), "D", "1", "정답", {}), 0.03, score)
        for i, score in enumerate((0.8, 0.02, 0.019))
    ]
    value = runner.assess(query, hits, minimum=0.02, k=5)
    assert value == {"minimum": 0.02, "rank": 1, "returned": 2, "ids": ["0", "1"]}
    assert len(hits) == 3
    with pytest.raises(ValueError, match="비정상"):
        runner.assess(
            query, [Hit(hits[0].chunk, 0.03, float("nan"))], minimum=0.02, k=5
        )


def test_summary_excludes_known_control_and_counts_actual_empty_results():
    def record(negative, rank, returned, *, control=False):
        return {
            "control": control,
            "expect_no_evidence": negative,
            "outcomes": [{"minimum": 0.02, "rank": rank, "returned": returned}],
        }

    result = runner.summarize(
        [
            record(False, 2, 3),
            record(True, None, 0),
            record(True, None, 2),
            record(True, None, 1, control=True),
        ],
        0.02,
    )
    assert result == {
        "positive": 1,
        "hit1": 0,
        "hit5": 1,
        "mrr": 0.5,
        "positive_empty": 0,
        "negative": 2,
        "rejected": 1,
    }


def test_default_plan_does_not_create_models_or_output(tmp_path, monkeypatch):
    monkeypatch.setenv("RERANKER_MODEL", "rerank-3-lite")  # 기본값은 리랭커 끔
    monkeypatch.setattr(
        runner.factory, "build_store", lambda *a, **kw: pytest.fail("모델 실행 금지")
    )
    out = tmp_path / "not-created"
    assert runner.main(["--out", str(out)]) == 0
    assert not out.exists()


@pytest.mark.parametrize("execute", [False, True])
@pytest.mark.parametrize(
    "content",
    [
        "",
        '[[queries]]\nid="positive"\nquery="새 정상 질문"\ndoc_id="D"\nany_of=["정답"]\n',
        '[[queries]]\nid="negative"\nquery="새 근거 없음 질문"\nexpect_no_evidence=true\n',
    ],
)
def test_missing_question_category_fails_before_settings_or_models(
    tmp_path, monkeypatch, capsys, content, execute
):
    queries = tmp_path / "queries.toml"
    queries.write_text(content, encoding="utf-8")
    monkeypatch.setattr(
        runner, "get_settings", lambda: pytest.fail("입력 검증 전에 설정 접근 금지")
    )
    output = tmp_path / "not-created"
    args = ["--queries", str(queries), "--out", str(output)]
    if execute:
        args.append("--execute")
    with pytest.raises(SystemExit) as exc:
        runner.main(args)
    assert exc.value.code == 2
    assert "정상 질문과 근거 없음 질문이 각각 1개 이상" in capsys.readouterr().err
    assert not output.exists()

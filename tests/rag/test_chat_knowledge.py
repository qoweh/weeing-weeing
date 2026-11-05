"""실제 저장소 백엔드·SQLite 문서 레지스트리를 거치는 챗봇 연결 검증."""

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from weeing_weeing.agent.interface import InvalidChatQueryError, LlmTimeoutError
from weeing_weeing.api.chat_knowledge import DatabaseChatKnowledge, build_chat_service
from weeing_weeing.contracts import (
    ChatContext,
    ChatQuestion,
    DocumentRecord,
    MaintenanceReport,
)
from weeing_weeing.contracts.chat_tools import ChatHistoryQuery, ChatSearchQuery
from weeing_weeing.db.interface import open_documents
from weeing_weeing.rag.interface import HybridRetriever, report_search_hit
from weeing_weeing.rag.report import report_chunk
from weeing_weeing.rag.store import Chunk

DATA = Path(__file__).resolve().parents[2] / "data/history/synthetic_reports_v1.jsonl"


def report(number=1):
    value = MaintenanceReport.model_validate_json(
        DATA.read_text(encoding="utf-8").splitlines()[0]
    )
    value.report_id = f"TEST-{number}"
    value.asset_id = "A1"
    value.incident.codes = ["BTT2-P03"]
    value.maintenance.actions_taken[0].at = datetime(
        2026, 10, 1, 15, tzinfo=timezone.utc
    )
    return value


def document(**changes):
    return DocumentRecord(
        doc_id="MAN",
        doc_version="1",
        doc_type="manual",
        origin="seed",
        title="센서 매뉴얼",
        source="test.pdf",
        source_sha256="a" * 64,
        extra={"asset_id": "A1", "model": "M1"},
    ).model_copy(update=changes)


def chunk(record, **metadata):
    return Chunk(
        f"{record.doc_id}:{record.doc_version}:0001",
        record.doc_id,
        record.doc_version,
        "광전 센서 점검: 렌즈를 청소한다.",
        {
            "doc_type": record.doc_type,
            "status": record.doc_status,
            "source_sha256": record.source_sha256,
            "codes": ["BTT2-P03"],
            "page": 3,
            "asset_id": record.extra.get("asset_id"),
            **metadata,
        },
    )


@pytest.fixture
def knowledge(store, tmp_path):
    docs = open_documents(f"sqlite:///{tmp_path / 'chat.sqlite'}")
    reports = SimpleNamespace(rows=[])
    reports.approved_reports = lambda: reports.rows
    value = DatabaseChatKnowledge(HybridRetriever(store), docs, reports)
    yield value
    docs._engine.dispose()


def register(knowledge, record):
    upload = record.model_copy(
        update={
            "origin": "upload",
            "upload_id": str(uuid4()),
            "status": "processing",
            "uploaded_at": datetime.now(timezone.utc),
        }
    )
    knowledge.documents.add_upload(upload)
    return knowledge.documents.complete_upload(upload.upload_id, chunk_count=1)


def remove(knowledge, doc_id):
    record = knowledge.documents.upload_target(doc_id)
    with knowledge.documents.lock_document(doc_id):
        knowledge.documents.begin_delete(
            doc_id,
            doc_version=record.doc_version,
            source_sha256=record.source_sha256,
            upload_id=record.upload_id,
        )
        knowledge.documents.finish_delete(doc_id)


def seed_manual(knowledge, store, **metadata):
    record = document()
    register(knowledge, record)
    store.replace_document(record.doc_id, [chunk(record, **metadata)])
    return record


def search(knowledge, kind="MANUAL", **conditions):
    return knowledge.search(
        ChatSearchQuery(
            query="센서 점검", kind=kind, code="BTT2-P03", conditions=conditions
        ),
        timeout_s=10,
    )


def test_manual_metadata_filters_and_changed_file_are_checked(knowledge, store):
    record = seed_manual(knowledge, store)
    result = search(knowledge, asset_id="A1", model="M1")
    assert len(result) == 1
    source = result[0].source
    assert source.page == 3 and source.doc_version == "1"
    assert source.title == record.title
    assert knowledge.is_searchable(source, timeout_s=10)
    register(knowledge, record.model_copy(update={"source_sha256": "b" * 64}))
    assert not knowledge.is_searchable(source, timeout_s=10)
    assert (
        search(knowledge) == []
    )  # 같은 판 번호라도 파일 교체 뒤 옛 본문을 쓰지 않는다.


def test_analysis_research_scopes_sources_and_rechecks_deleted_manual(knowledge, store):
    from concurrent.futures import ThreadPoolExecutor

    from weeing_weeing.api.analysis_knowledge import DatabaseAnalysisKnowledge

    record = seed_manual(knowledge, store)
    row = report()
    knowledge.reports.rows = [row]
    store.replace_document(row.report_id, [report_chunk(row)])
    item = row.incident.model_copy(update={"asset_id": "A1"})
    adapter = DatabaseAnalysisKnowledge(
        knowledge.documents, knowledge.reports, HybridRetriever(store)
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        documents = pool.submit(
            adapter.search, "documents", item, "센서 점검", k=5, timeout_s=10
        )
        reports = pool.submit(
            adapter.search, "reports", item, "센서 점검", k=5, timeout_s=10
        )
        documents, reports = documents.result(), reports.result()
    assert [e.doc_id for e in documents] == [record.doc_id]
    assert [e.doc_id for e in reports] == [row.report_id]
    assert "가상 사례" in reports[0].citation
    assert adapter.is_current(documents[0], timeout_s=10)
    remove(knowledge, record.doc_id)
    assert not adapter.is_current(documents[0], timeout_s=10)
    assert adapter.search("documents", item, "센서 점검", k=5, timeout_s=10) == []


def test_analysis_evidence_retains_pdf_page_along_with_section(knowledge, store):
    from weeing_weeing.api.analysis_knowledge import DatabaseAnalysisKnowledge

    record = seed_manual(knowledge, store, page=8, section="고온 점검")
    item = report().incident.model_copy(update={"asset_id": "A1"})
    adapter = DatabaseAnalysisKnowledge(
        knowledge.documents, knowledge.reports, HybridRetriever(store)
    )
    [evidence] = adapter.search("documents", item, "센서 점검", k=5, timeout_s=10)
    assert evidence.page == 8 and evidence.title == record.title
    assert "PDF 8쪽" in evidence.citation and "고온 점검" in evidence.citation


def test_analysis_report_timing_is_calculated_with_timezones(knowledge, store):
    from datetime import timedelta

    from weeing_weeing.api.analysis_knowledge import DatabaseAnalysisKnowledge

    row = report()
    row.maintenance.actions_taken[0].at = datetime(
        2026, 11, 5, 0, 42, tzinfo=timezone(timedelta(hours=9))
    )
    item = row.incident.model_copy(
        update={
            "asset_id": "A1",
            "first_detected_at": datetime(2026, 11, 4, 15, 44, 15, tzinfo=timezone.utc),
        }
    )
    knowledge.reports.rows = [row]
    store.replace_document(row.report_id, [report_chunk(row)])
    adapter = DatabaseAnalysisKnowledge(
        knowledge.documents, knowledge.reports, HybridRetriever(store)
    )
    [hit] = adapter.search("reports", item, "센서", k=5, timeout_s=10)
    assert hit.report_timing[0].offset_seconds == -135
    assert hit.report_timing[0].action_at == datetime(
        2026, 11, 4, 15, 42, tzinfo=timezone.utc
    )


def test_analysis_research_empty_history_and_other_process_are_not_evidence(
    knowledge, store
):
    from weeing_weeing.api.analysis_knowledge import DatabaseAnalysisKnowledge

    seed_manual(knowledge, store)
    row = report()
    item = row.incident.model_copy(update={"asset_id": "A1"})
    adapter = DatabaseAnalysisKnowledge(
        knowledge.documents, knowledge.reports, HybridRetriever(store)
    )
    assert adapter.search("reports", item, "점검", k=5, timeout_s=10) == []
    row.incident.process_id = "other-process"
    knowledge.reports.rows = [row]
    store.replace_document(row.report_id, [report_chunk(row)])
    assert adapter.search("reports", item, "점검", k=5, timeout_s=10) == []


def test_analysis_report_code_or_filter_and_process_scope_are_applied_before_top_k(
    knowledge, store
):
    from weeing_weeing.api.analysis_knowledge import DatabaseAnalysisKnowledge

    record = seed_manual(knowledge, store, codes=[])
    relevant, wrong_code, wrong_process = report(1), report(2), report(3)
    wrong_code.incident.codes = ["BTT2-M10"]
    wrong_process.incident.process_id = "other-process"
    knowledge.reports.rows = [relevant, wrong_code, wrong_process]
    for row in knowledge.reports.rows:
        store.replace_document(row.report_id, [report_chunk(row)])
    item = relevant.incident.model_copy(
        update={"asset_id": "A1", "codes": ["BTT2-P04", "BTT2-P03"]}
    )
    calls = []
    retriever = HybridRetriever(store)

    def search_hits(query, **kwargs):
        calls.append(kwargs)
        return retriever.search_hits(query, **kwargs)

    adapter = DatabaseAnalysisKnowledge(
        knowledge.documents, knowledge.reports, SimpleNamespace(search_hits=search_hits)
    )
    hits = adapter.search("reports", item, "센서", k=1, timeout_s=10)
    assert [hit.doc_id for hit in hits] == [relevant.report_id]
    assert calls[0]["versions"] == {relevant.report_id: str(relevant.report_version)}
    assert calls[0]["filters"]["codes"] == item.codes
    hits = adapter.search("documents", item, "센서", k=1, timeout_s=10)
    assert [hit.doc_id for hit in hits] == [record.doc_id]
    assert "code" not in calls[-1]["filters"] and "codes" not in calls[-1]["filters"]
    # 같은 코드 보고서가 없으면 다른 에러 사례로 범위를 자동 확대하지 않는다.
    item.codes = ["BTT2-M19"]
    before = len(calls)
    assert adapter.search("reports", item, "점검", k=1, timeout_s=10) == []
    assert len(calls) == before


def test_manual_deletion_revision_location_and_index_lag(knowledge, store):
    record = seed_manual(knowledge, store, page=None)
    assert search(knowledge) == []
    store.replace_document(record.doc_id, [chunk(record, page=4, section="센서 점검")])
    source = search(knowledge)[0].source
    register(knowledge, record.model_copy(update={"doc_version": "2"}))
    assert search(knowledge) == []
    assert not knowledge.is_searchable(source, timeout_s=10)
    remove(knowledge, record.doc_id)
    assert not knowledge.is_searchable(source, timeout_s=10)


def test_unregistered_vector_chunks_and_draft_manual_are_excluded(knowledge, store):
    seed_manual(knowledge, store)
    draft = document(doc_id="DRAFT", doc_status="draft")
    remove(knowledge, "MAN")
    register(knowledge, draft)
    store.replace_document(draft.doc_id, [chunk(draft)])
    assert search(knowledge) == []  # DB에서 삭제된 매뉴얼과 초안은 검색하지 않는다.


@pytest.mark.parametrize(
    "conditions",
    [dict(asset_id="unknown"), dict(model="unknown"), dict(date_from="2026-10-01")],
)
def test_unsupported_manual_conditions_are_explicit(knowledge, store, conditions):
    seed_manual(knowledge, store)
    with pytest.raises(InvalidChatQueryError):
        search(knowledge, **conditions)


def test_report_dates_are_seoul_action_dates_and_counts_are_not_top_k(knowledge, store):
    rows = [report(n) for n in range(1, 8)]
    knowledge.reports.rows = rows
    # 벡터 DB에는 한 건뿐이어도 구조화 조회는 전체 7건이다.
    store.replace_document(rows[0].report_id, [report_chunk(rows[0])])
    assert (
        len(
            search(
                knowledge,
                "MAINTENANCE_HISTORY",
                asset_id="A1",
                date_from="2026-10-02",
                date_to="2026-10-02",
                limit=1,
            )
        )
        == 1
    )
    query = ChatHistoryQuery(
        conditions=dict(
            asset_id="A1", date_from="2026-10-02", date_to="2026-10-02", limit=2
        ),
        code="BTT2-P03",
    )
    result = knowledge.query_history(query, timeout_s=10)
    assert result.source.total == result.source.synthetic_total == 7
    assert len(result.reports) == 2 and result.truncated
    assert knowledge.is_searchable(result.source, timeout_s=10)
    assert (
        knowledge.query_history(
            ChatHistoryQuery(conditions=dict(date_to="2026-10-01")), timeout_s=10
        ).source.total
        == 0
    )
    knowledge.reports.rows.pop()
    assert not knowledge.is_searchable(result.source, timeout_s=10)


def test_report_current_approved_and_sanitized_db_body(knowledge, store):
    old = report()
    store.replace_document(old.report_id, [report_chunk(old)])
    current = old.model_copy(deep=True)
    current.report_version = 2
    knowledge.reports.rows = [current]
    assert search(knowledge, "MAINTENANCE_HISTORY") == []  # 최신 승인 판의 색인 대기 중
    store.replace_document(current.report_id, [report_chunk(current)])
    # 오염된 벡터 본문 대신 DB의 사람 작성 칸만 반환한다.
    poisoned = report_chunk(current)
    store.replace_document(
        current.report_id,
        [
            Chunk(
                poisoned.chunk_id,
                poisoned.doc_id,
                poisoned.doc_version,
                "AI_SECRET STAFF_SECRET APPROVAL_SECRET",
                poisoned.metadata,
            )
        ],
    )
    result = search(knowledge, "MAINTENANCE_HISTORY")
    assert result[0] == report_search_hit(current)
    assert "SECRET" not in result[0].text
    assert not knowledge.is_searchable(report_search_hit(old).source, timeout_s=10)
    knowledge.reports.rows = [current.model_copy(update={"report_status": "REJECTED"})]
    assert search(knowledge, "MAINTENANCE_HISTORY") == []


def test_report_filters_and_timeout_do_not_get_ignored(knowledge, store):
    knowledge.reports.rows = [report()]
    for conditions in (dict(model="M1"), dict(asset_id="unknown")):
        with pytest.raises(InvalidChatQueryError):
            knowledge.query_history(
                ChatHistoryQuery(conditions=conditions), timeout_s=10
            )
    assert (
        knowledge.query_history(
            ChatHistoryQuery(code="BTT2-P01"), timeout_s=10
        ).source.total
        == 0
    )
    with pytest.raises(LlmTimeoutError):
        knowledge.query_history(ChatHistoryQuery(), timeout_s=0)


class ToolClient:
    provider = "fake"
    model_name = "fake"
    last_usage = None

    def __init__(self, structured=False):
        self.calls = 0
        self.structured = structured
        self.result = None

    def generate_json(self, system, user, **kwargs):
        return '{"verdict":"SUPPORTED","unsupported_parts":[]}'

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            name = "query_history" if self.structured else "search_knowledge"
            data = {} if self.structured else dict(query="센서 점검", kind="MANUAL")
        else:
            self.result = json.loads(kwargs["messages"][-1]["content"][0]["content"])
            source = (
                self.result["source"] if self.structured else self.result[0]["source"]
            )
            name = "submit_answer"
            data = dict(
                intent="MAINTENANCE_HISTORY" if self.structured else "MANUAL",
                status="OK",
                message="조회 결과입니다.",
                parts=[
                    dict(
                        kind="MAINTENANCE_HISTORY" if self.structured else "MANUAL",
                        text="승인 보고서 0건입니다."
                        if self.structured
                        else "렌즈를 청소합니다.",
                        source_ids=[source["source_id"]],
                    )
                ],
            )
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="tool_use", id=str(uuid4()), name=name, input=data)
            ]
        )


@pytest.mark.parametrize("structured", [False, True])
def test_real_adapter_is_connected_to_claude_tool_boundary(
    knowledge, store, structured
):
    seed_manual(knowledge, store)
    client = ToolClient(structured)
    service = build_chat_service(knowledge=knowledge, client=client)
    result = service.reply(
        ChatQuestion(request_id=uuid4(), question="조회해 줘"),
        context=ChatContext(),
        timeout_s=20,
    )
    assert result.status == "OK"
    assert result.sources[0].kind == ("HISTORY_QUERY" if structured else "DOCUMENT")
    assert client.calls == 2


def test_combined_answer_can_cite_manual_and_report(knowledge, store):
    seed_manual(knowledge, store)
    value = report()
    knowledge.reports.rows = [value]
    store.replace_document(value.report_id, [report_chunk(value)])

    class Client(ToolClient):
        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                blocks = [
                    SimpleNamespace(
                        type="tool_use",
                        id=str(uuid4()),
                        name="search_knowledge",
                        input=dict(query="센서 점검", kind=kind),
                    )
                    for kind in ("MANUAL", "MAINTENANCE_HISTORY")
                ]
            else:
                found = [
                    json.loads(block["content"])[0]
                    for block in kwargs["messages"][-1]["content"]
                ]
                blocks = [
                    SimpleNamespace(
                        type="tool_use",
                        id=str(uuid4()),
                        name="submit_answer",
                        input=dict(
                            intent="COMBINED",
                            status="OK",
                            message="매뉴얼과 과거 사례입니다.",
                            parts=[
                                dict(
                                    kind="MANUAL"
                                    if hit["source"]["kind"] == "DOCUMENT"
                                    else "MAINTENANCE_HISTORY",
                                    text="센서 점검 안내 (가상 사례 포함)",
                                    source_ids=[hit["source"]["source_id"]],
                                )
                                for hit in found
                            ],
                        ),
                    )
                ]
            return SimpleNamespace(content=blocks)

    result = build_chat_service(knowledge=knowledge, client=Client()).reply(
        ChatQuestion(request_id=uuid4(), question="매뉴얼과 과거 사례를 찾아줘"),
        context=ChatContext(),
        timeout_s=20,
    )
    assert result.status == "OK" and result.intent == "COMBINED"
    assert {source.kind for source in result.sources} == {"DOCUMENT", "REPORT"}

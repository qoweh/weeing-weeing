"""멀티 조사에 주입하는 읽기 전용 검색. 기존 DB 출처 검증·RAG 정책을 재사용한다."""

from datetime import UTC
from threading import RLock

from weeing_weeing.api.chat_knowledge import DatabaseChatKnowledge
from weeing_weeing.contracts import Evidence
from weeing_weeing.contracts.analysis import ReportActionTiming
from weeing_weeing.contracts.chat import ChatSearchConditions
from weeing_weeing.contracts.chat_tools import ChatSearchQuery


class DatabaseAnalysisKnowledge:
    def __init__(self, documents, reports, retriever=None):
        self.backend = DatabaseChatKnowledge(retriever, documents, reports)
        self.lock = RLock()
        self.sources = {}

    def search(self, role, incident, query, *, k, timeout_s):
        if role not in ("documents", "reports"):
            raise ValueError("조사 역할만 검색할 수 있습니다")
        with self.lock:
            approved = {}
            # 미등록 설비를 입력 오류로 보는 챗봇과 달리 사건 조사에서는 자료 없음이다.
            if role == "documents":
                available = any(
                    r.status == "completed"
                    and r.doc_status == "approved"
                    and r.doc_type in {"manual", "sop", "rule"}
                    and r.extra.get("asset_id") == incident.asset_id
                    for r in self.backend.documents.listed()
                )
            else:
                approved = {
                    r.report_id: r
                    for r in self.backend.reports.approved_reports()
                    if r.report_status == "APPROVED"
                    and r.asset_id == incident.asset_id
                    and r.incident.process_id == incident.process_id
                    and set(r.incident.codes).intersection(incident.codes)
                    and r.maintenance is not None
                }
                available = bool(approved)
            if not available:
                return []
            hits = self.backend.search(
                ChatSearchQuery(
                    query=query,
                    kind="MANUAL" if role == "documents" else "MAINTENANCE_HISTORY",
                    conditions=ChatSearchConditions(
                        asset_id=incident.asset_id, limit=k
                    ),
                ),
                timeout_s=timeout_s,
                **(
                    {"report_ids": frozenset(approved), "codes": tuple(incident.codes)}
                    if role == "reports"
                    else {}
                ),
            )
            results = []
            for hit in hits:
                source = hit.source
                if source.kind == "REPORT":
                    # 챗봇의 설비 ID 필터에 공정 조건도 더한다.
                    report = approved.get(source.report_id)
                    if report is None or report.report_version != source.report_version:
                        continue
                    doc_id, version, section = (
                        source.report_id,
                        str(source.report_version),
                        "승인 정비보고서",
                    )
                else:
                    doc_id, version, section = (
                        source.doc_id,
                        source.doc_version,
                        source.section,
                    )
                item = Evidence(
                    evidence_id=source.source_id,
                    doc_id=doc_id,
                    doc_version=version,
                    title=source.title,
                    page=source.page if source.kind == "DOCUMENT" else None,
                    section=section,
                    citation=f"{source.title} · {doc_id} v{version}"
                    + (
                        f" · PDF {source.page}쪽"
                        if source.kind == "DOCUMENT" and source.page
                        else ""
                    ),
                    text=hit.text,
                    report_timing=[
                        ReportActionTiming(
                            action_index=index,
                            action_at=action.at.astimezone(UTC),
                            incident_at=incident.first_detected_at.astimezone(UTC),
                            offset_seconds=(
                                action.at.astimezone(UTC)
                                - incident.first_detected_at.astimezone(UTC)
                            ).total_seconds(),
                        )
                        for index, action in enumerate(report.maintenance.actions_taken)
                    ]
                    if source.kind == "REPORT"
                    else [],
                )
                if section:
                    item.citation += f" · {section}"
                self.sources[item.evidence_id] = source
                results.append(item)
            return results

    def is_current(self, evidence, *, timeout_s):
        with self.lock:
            source = self.sources.get(evidence.evidence_id)
            return source is not None and self.backend.is_searchable(
                source, timeout_s=timeout_s
            )

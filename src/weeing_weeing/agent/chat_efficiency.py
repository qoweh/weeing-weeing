"""정형 건수 답변과 손실 없는 근거 중복 제거. 자유 답변의 근거 검토는 유지한다."""

from datetime import UTC, datetime

from weeing_weeing.contracts.chat import ChatHistorySource, ChatResponse

from .runtime import ToolInputError


def history_count_response(question, query, source):
    source = ChatHistorySource.model_validate(source)
    if source.conditions != query.conditions or source.code != query.code:
        raise ValueError("History count conditions mismatch")
    if source.synthetic_total > source.total:
        raise ValueError("Synthetic count exceeds total")
    conditions = source.conditions
    if conditions.model is not None:
        raise ToolInputError("보고서 건수는 모델 조건을 지원하지 않습니다.")
    if conditions.date_from and conditions.date_to:
        period = f"{conditions.date_from}~{conditions.date_to} (양 끝 포함)"
    elif conditions.date_from:
        period = f"{conditions.date_from} 이후 (당일 포함)"
    elif conditions.date_to:
        period = f"{conditions.date_to} 이전 (당일 포함)"
    else:
        period = "기간 제한 없음"

    def escaped(value):
        return value.replace("`", "\\`").replace("\n", " ").replace("\r", " ")

    filters = [f"기간: {period}"]
    filters.append(
        f"설비: `{escaped(conditions.asset_id)}`"
        if conditions.asset_id
        else "설비 제한 없음"
    )
    filters.append(
        f"코드: `{escaped(source.code)}`" if source.code else "코드 제한 없음"
    )
    synthetic = (
        f" (가상 자료 {source.synthetic_total}건 포함)"
        if source.synthetic_total
        else ""
    )
    text = (
        f"조건에 맞는 최신 승인 정비 보고서는 **총 {source.total}건**{synthetic}입니다.\n\n"
        + " · ".join(filters)
        + "\n기간은 한국 시간의 실제 정비 조치일 기준입니다."
    )
    return ChatResponse(
        request_id=question.request_id,
        intent="MAINTENANCE_HISTORY",
        status="OK",
        applied_conditions=conditions.model_copy(deep=True),
        message="검증된 조회 조건과 집계 결과를 안내합니다.",
        parts=[
            {
                "kind": "MAINTENANCE_HISTORY",
                "text": text,
                "source_ids": [source.source_id],
            }
        ],
        sources=[source],
        clarification_questions=[],
        generated_at=datetime.now(UTC),
    )


def complete_history_count(knowledge, question, query, remaining):
    counter = getattr(knowledge, "count_history", None)
    if not callable(counter):
        raise ToolInputError(
            "이 조회기는 COUNT_ONLY를 지원하지 않습니다. LIST로 조회하세요."
        )
    source = ChatHistorySource.model_validate(counter(query, timeout_s=remaining()))
    response = history_count_response(question, query, source)
    # 렌더링한 결과의 집계 조건/스냅샷이 유지되는지 확인한다. 장애를0건으로 바꾸지 않는다.
    for _ in range(2):
        if not knowledge.is_searchable(source, timeout_s=remaining()):
            raise RuntimeError("History count source changed")
    return response, source


def grounding_payload(question, parts, sources, texts):
    """각 출처의 전문·메타데이터를 보존하고 동일 본문만 참조로 공유한다."""
    evidence, body_owner = {}, {}
    requested_chars = 0
    for part in parts:
        for key in part.source_ids:
            if key not in sources or key not in texts:
                raise ToolInputError("검토할 인용 근거가 없습니다.")
            text = texts[key]
            requested_chars += len(text)
            if key in evidence:
                continue
            item = {"source": sources[key].model_dump(mode="json")}
            if text in body_owner:
                item["text_ref"] = body_owner[text]
            else:
                item["text"] = text
                body_owner[text] = key
            evidence[key] = item
    return {
        "question": question,
        "parts": [part.model_dump(mode="json") for part in parts],
        "evidence": evidence,
        "evidence_stats": {
            "referenced_text_chars": requested_chars,
            "sent_text_chars": sum(
                len(item.get("text", "")) for item in evidence.values()
            ),
        },
    }


def evidence_reference_system(system, payload):
    if any("text_ref" in item for item in payload.get("evidence", {}).values()):
        return (
            system
            + "\nevidence의 text_ref는 같은 evidence 안의 다른 출처 ID 본문을 참조한다. 참조 본문 전체를 읽고 각 출처의 메타데이터·적용 조건은 구분해 검토한다."
        )
    return system

from uuid import uuid4

import pytest
from pydantic import ValidationError

from weeing_weeing.contracts import FaqAnswer, FaqQuestion, FaqSelection, FaqTopic


def question_data():
    return dict(faq_id="FAQ-001", faq_version="1", topic_id="reports", question="질문")


def test_selection_accepts_only_request_id_and_catalog_identity():
    selection = FaqSelection(request_id=uuid4(), faq_id="FAQ-001", faq_version="1")
    assert FaqSelection.model_validate_json(selection.model_dump_json()) == selection
    for extra in ({"user_id": "another-user"}, {"answer": "클라이언트가 만든 답변"}):
        with pytest.raises(ValidationError):
            FaqSelection(**(selection.model_dump() | extra))


@pytest.mark.parametrize("identifier", ["", " ", "../secret", "x" * 65, "faq/id"])
def test_selection_rejects_invalid_ids(identifier):
    with pytest.raises(ValidationError):
        FaqSelection(request_id=uuid4(), faq_id=identifier, faq_version="1")


@pytest.mark.parametrize("version", ["", " ", "x" * 65])
def test_selection_rejects_empty_or_excessive_version(version):
    with pytest.raises(ValidationError):
        FaqSelection(request_id=uuid4(), faq_id="FAQ-001", faq_version=version)


@pytest.mark.parametrize(
    "overrides",
    [{"question": " "}, {"question": "x" * 2001}, {"order": -1}, {"order": True}],
)
def test_question_validates_display_fields(overrides):
    with pytest.raises(ValidationError):
        FaqQuestion(**(question_data() | overrides))


def test_topic_is_immutable():
    topic = FaqTopic(topic_id="reports", title="보고서")
    with pytest.raises(ValidationError):
        topic.title = "바뀐 이름"


@pytest.mark.parametrize("source_override", [{"faq_id": "OTHER"}, {"faq_version": "2"}])
def test_answer_rejects_mismatched_source(source_override):
    with pytest.raises(ValidationError):
        FaqAnswer(
            question=question_data(),
            answer="검토 답변",
            reviewed_at="2026-01-01",
            source=dict(
                kind="FAQ",
                source_id="faq:FAQ-001:1",
                title="질문",
                faq_id="FAQ-001",
                faq_version="1",
            )
            | source_override,
        )

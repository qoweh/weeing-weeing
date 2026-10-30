import json
import socket
from pathlib import Path
from uuid import uuid4

import pytest

from weeing_weeing.agent.interface import (
    FaqCatalogError,
    FaqNotFoundError,
    FaqVersionConflictError,
    load_faq_catalog,
)
from weeing_weeing.contracts import ChatResponse, ChatSearchConditions, FaqSelection

TOPICS = """
[[topics]]
topic_id = "reports"
title = "보고서"
order = 20
active = true
[[topics]]
topic_id = "access"
title = "접근"
order = 10
active = true
[[topics]]
topic_id = "empty"
title = "빈 주제"
active = true
[[topics]]
topic_id = "hidden"
title = "숨긴 주제"
active = false
"""


def entry(
    faq_id="FAQ-001", topic_id="reports", *, active=True, reviewed=True, **overrides
):
    data = dict(
        faq_id=faq_id,
        topic_id=topic_id,
        faq_version="1",
        question="질문",
        order=10,
        active=active,
        answer="검토 답변",
        references=["docs/REPORTS.md"],
    )
    if reviewed:
        data["reviewed_at"] = "2026-01-01"
    data.update(overrides)
    return (
        "\n[[faqs]]\n"
        + "\n".join(
            f"{key} = {json.dumps(value, ensure_ascii=False)}"
            for key, value in data.items()
        )
        + "\n"
    )


def write_catalog(tmp_path, faqs=None, topics=TOPICS, *, encoding="utf-8"):
    path = tmp_path / "faq.toml"
    path.write_text(
        "schema_version = 1\n" + topics + (entry() if faqs is None else faqs),
        encoding=encoding,
    )
    return path


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "cp949"])
def test_catalog_encodings_preserve_korean_text(tmp_path, encoding):
    catalog = load_faq_catalog(write_catalog(tmp_path, encoding=encoding))

    assert catalog.list_topics()[0].title == "보고서"
    answer = catalog.get_answer("FAQ-001")
    assert answer.question.question == "질문"
    assert answer.answer == "검토 답변"


def test_undecodable_catalog_is_service_failure(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_bytes(b"\xff")

    with pytest.raises(FaqCatalogError) as error:
        load_faq_catalog(path)
    assert isinstance(error.value.__cause__, UnicodeDecodeError)


def test_topics_and_questions_are_filtered_and_sorted(tmp_path):
    path = write_catalog(
        tmp_path,
        "".join(
            [
                entry("FAQ-B", order=20),
                entry("FAQ-A", order=10),
                entry("FAQ-ACCESS", "access"),
                entry("FAQ-HIDDEN", "hidden"),
                entry("FAQ-DRAFT", active=False, reviewed=False),
            ]
        ),
    )
    catalog = load_faq_catalog(path)
    assert [t.topic_id for t in catalog.list_topics()] == ["access", "reports"]
    assert [q.faq_id for q in catalog.list_questions("reports")] == ["FAQ-A", "FAQ-B"]


@pytest.mark.parametrize("faq_id", ["MISSING", "FAQ-HIDDEN", "FAQ-DRAFT"])
def test_unavailable_faqs_have_same_safe_error(tmp_path, faq_id):
    catalog = load_faq_catalog(
        write_catalog(
            tmp_path,
            entry("FAQ-HIDDEN", "hidden")
            + entry("FAQ-DRAFT", active=False, reviewed=False),
        )
    )
    with pytest.raises(FaqNotFoundError, match="조회할 수 없는 FAQ입니다"):
        catalog.get_answer(faq_id)


@pytest.mark.parametrize("topic_id", ["empty", "hidden", "missing"])
def test_unavailable_topics_have_same_safe_error(tmp_path, topic_id):
    catalog = load_faq_catalog(write_catalog(tmp_path))
    with pytest.raises(FaqNotFoundError):
        catalog.list_questions(topic_id)


def test_empty_catalog_is_valid(tmp_path):
    catalog = load_faq_catalog(write_catalog(tmp_path, faqs="", topics=""))
    assert catalog.list_topics() == []


@pytest.mark.parametrize(
    "faqs",
    [
        entry() + entry(),
        entry(topic_id="missing"),
        entry(answer=" "),
        entry(reviewed=False),
        entry(references=[]),
        entry(reviewed_at="2999-01-01"),
        entry(active="true"),
        entry(unexpected="not allowed"),
    ],
)
def test_invalid_data_fails_instead_of_returning_empty_catalog(tmp_path, faqs):
    with pytest.raises(FaqCatalogError):
        load_faq_catalog(write_catalog(tmp_path, faqs))


def test_duplicate_topics_rejected(tmp_path):
    with pytest.raises(FaqCatalogError):
        load_faq_catalog(write_catalog(tmp_path, topics=TOPICS + TOPICS))


@pytest.mark.parametrize(
    "content",
    ["not toml = [", "schema_version = 2", "schema_version = 1\nunknown = true"],
)
def test_corrupt_or_unsupported_catalog_rejected(tmp_path, content):
    path = tmp_path / "bad.toml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(FaqCatalogError):
        load_faq_catalog(path)


def test_missing_file_is_service_failure(tmp_path):
    with pytest.raises(FaqCatalogError):
        load_faq_catalog(tmp_path / "missing.toml")


def test_selection_returns_exact_answer_and_source_without_external_services(
    tmp_path, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail("FAQ 경로에서 외부 서비스에 접근함")

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr("weeing_weeing.agent.interface.get_llm_client", forbidden)
    monkeypatch.setattr("weeing_weeing.rag.interface.get_retriever", forbidden)
    monkeypatch.setattr("weeing_weeing.db.interface.get_reports", forbidden)
    catalog = load_faq_catalog(
        write_catalog(tmp_path, entry(answer="검토된 답변 원문입니다."))
    )
    selection = FaqSelection(request_id=uuid4(), faq_id="FAQ-001", faq_version="1")
    conditions = ChatSearchConditions(asset_id="BLDC-001", date_from="2026-01-01")
    response = catalog.answer(selection, conditions=conditions)
    assert response.intent == "FAQ" and response.status == "OK"
    assert response.request_id == selection.request_id
    assert response.applied_conditions == conditions
    assert response.parts[0].text == "검토된 답변 원문입니다."
    assert response.parts[0].source_ids == [response.sources[0].source_id]
    assert response.sources[0].faq_id == selection.faq_id
    assert response.sources[0].faq_version == "1"
    assert ChatResponse.model_validate_json(response.model_dump_json()) == response


def test_stale_selection_requires_refresh(tmp_path):
    catalog = load_faq_catalog(write_catalog(tmp_path))
    with pytest.raises(FaqVersionConflictError):
        catalog.answer(
            FaqSelection(request_id=uuid4(), faq_id="FAQ-001", faq_version="old")
        )


def test_returned_data_cannot_modify_catalog(tmp_path):
    catalog = load_faq_catalog(write_catalog(tmp_path))
    catalog.list_topics().clear()
    catalog.list_questions("reports").clear()
    catalog.get_answer("FAQ-001").source.faq_version = "forged"
    assert catalog.list_topics()
    assert catalog.list_questions("reports")
    assert catalog.get_answer("FAQ-001").source.faq_version == "1"


def test_reload_creates_new_snapshot_without_changing_existing_instance(tmp_path):
    path = write_catalog(tmp_path)
    first = load_faq_catalog(path)
    write_catalog(tmp_path, entry(answer="수정 답변", faq_version="2"))
    assert first.get_answer("FAQ-001").source.faq_version == "1"
    assert load_faq_catalog(path).get_answer("FAQ-001").source.faq_version == "2"


def test_default_catalog_works_outside_project_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    catalog = load_faq_catalog()
    topics = catalog.list_topics()
    assert {topic.topic_id for topic in topics} >= {"access", "reports", "approval"}
    for topic in topics:
        for question in catalog.list_questions(topic.topic_id):
            answer = catalog.get_answer(question.faq_id)
            assert answer.answer.strip()
            assert answer.source.faq_version == question.faq_version


def test_seed_evidence_points_to_existing_files_and_functions():
    import tomllib

    root = Path(__file__).resolve().parents[2]
    data = tomllib.loads(
        (root / "data/faq/service_v1.toml").read_text(encoding="utf-8")
    )
    for faq in data["faqs"]:
        if not faq.get("active"):
            continue
        for reference in faq["references"]:
            path, _, symbol = reference.partition(":")
            source = root / path.split("#", 1)[0]
            assert source.is_file(), reference
            if symbol:
                assert f"def {symbol}(" in source.read_text(encoding="utf-8"), reference


def test_contact_guidance_is_published_without_removed_role():
    catalog = load_faq_catalog()
    questions = catalog.list_questions("contacts")
    assert {q.faq_id for q in questions} == {
        "FAQ-CONTACT-002",
        "FAQ-CONTACT-003",
    }
    expected_roles = {
        "FAQ-CONTACT-002": ("현장 점검자", "보전 팀장"),
        "FAQ-CONTACT-003": ("보전 팀장", "관제 담당자"),
    }
    for question in questions:
        response = catalog.answer(
            FaqSelection(
                request_id=uuid4(),
                faq_id=question.faq_id,
                faq_version=question.faq_version,
            )
        )
        text = response.parts[0].text
        assert all(role in text for role in expected_roles[question.faq_id])
        expected_version = "3" if question.faq_id == "FAQ-CONTACT-002" else "2"
        assert response.sources[0].faq_version == expected_version
        with pytest.raises(FaqVersionConflictError):
            catalog.answer(
                FaqSelection(
                    request_id=uuid4(),
                    faq_id=question.faq_id,
                    faq_version=str(int(expected_version) - 1),
                )
            )
    with pytest.raises(FaqNotFoundError):
        catalog.get_answer("FAQ-CONTACT-001")
    for topic in catalog.list_topics():
        for question in catalog.list_questions(topic.topic_id):
            faq = catalog.get_answer(question.faq_id)
            assert "현장 책임자" not in question.question + faq.answer

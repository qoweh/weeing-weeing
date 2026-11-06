"""도구 범위 설명의 실제 요청 전달 및 무조회 범위밖 종료 경로 검증."""

from uuid import uuid4

from test_chat_service import CommonKnowledge, FakeClient, reply, submit

from weeing_weeing.agent.chat import ToolChatService
from weeing_weeing.agent.interface import load_faq_catalog
from weeing_weeing.contracts import ChatContext, ChatQuestion


def request():
    return ChatQuestion(
        request_id=uuid4(),
        question="제공된 도구 범위 밖의 별도 시스템 정보를 직접 조회해줘.",
    )


class NoReviewClient(FakeClient):
    def generate_json(self, *args, **kwargs):
        raise AssertionError("A fixed OUT_OF_SCOPE response must not need grounding")


def run():
    client = NoReviewClient(reply(submit("OUT_OF_SCOPE", intent="OUT_OF_SCOPE")))
    knowledge = CommonKnowledge()
    service = ToolChatService(client, knowledge, load_faq_catalog())
    result = service.reply(request(), context=ChatContext(), timeout_s=10)
    return client, knowledge, service, result


def test_tool_scope_reaches_actual_llm_payload_with_schema():
    client, _, _, _ = run()
    tools = {tool["name"]: tool for tool in client.calls[0]["tools"]}
    assert set(tools) == {
        "search_knowledge",
        "query_history",
        "query_incidents",
        "browse_faq",
        "get_faq_answer",
        "submit_answer",
    }
    assert all(
        t["strict"] and t["input_schema"]["type"] == "object" for t in tools.values()
    )
    history = tools["query_history"]["description"]
    assert all(
        word in history for word in ["승인", "조치일", "등록일", "total", "limit"]
    )
    assert (
        "외부 시스템의 현재 상태를 직접 조회하지 않는다"
        in tools["search_knowledge"]["description"]
    )
    assert (
        "직접 측정·원인 확정·설비 제어는 하지 않는다"
        in tools["query_incidents"]["description"]
    )
    assert "목록은 사실 답변 근거가 아니며" in tools["browse_faq"]["description"]


def test_out_of_scope_can_finish_in_one_llm_call_without_lookup_or_review():
    client, knowledge, service, result = run()
    assert result.status == "OUT_OF_SCOPE"
    assert not result.parts and not result.sources
    assert not knowledge.validated and not knowledge.searches and not knowledge.reads
    assert len(client.calls) == len(service.last_run.calls) == 1
    assert service.last_run.tool_names == ("submit_answer",)

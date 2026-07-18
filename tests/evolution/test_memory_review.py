from navi_agent.evolution import MemoryReviewService
from navi_agent.memory import InMemoryMemoryStore
from navi_agent.runtime import ModelResponse
from navi_agent.runtime.transports import ModelRequest
from navi_agent.telemetry import RuntimeTrace


class FakeTransport:
    def __init__(self, content: str) -> None:
        self.content = content
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(content=self.content)


def test_memory_review_writes_durable_memory() -> None:
    store = InMemoryMemoryStore()
    service = MemoryReviewService(
        transport=FakeTransport(
            '{"action": "add_memory", "kind": "preference", "content": "用户喜欢简洁直接的技术回答。", "rationale": "explicit preference"}'
        ),
        memory_store=store,
    )

    written = service.review_and_write(_trace())

    assert written
    records = store.list_for_user("u1")
    assert len(records) == 1
    assert records[0].kind == "preference"
    assert records[0].content == "用户喜欢简洁直接的技术回答。"


def test_memory_review_skips_nothing_decision() -> None:
    store = InMemoryMemoryStore()
    service = MemoryReviewService(
        transport=FakeTransport('{"action": "nothing", "kind": "fact", "content": "", "rationale": "one-off"}'),
        memory_store=store,
    )

    written = service.review_and_write(_trace())

    assert not written
    assert store.list_for_user("u1") == []


def test_memory_review_invalid_response_returns_false() -> None:
    store = InMemoryMemoryStore()
    service = MemoryReviewService(
        transport=FakeTransport("not json"),
        memory_store=store,
    )

    written = service.review_and_write(_trace())

    assert not written
    assert store.list_for_user("u1") == []


def _trace() -> RuntimeTrace:
    return RuntimeTrace(
        session_id="s1",
        user_id="u1",
        user_message="记住：我喜欢简洁直接的技术回答",
        final_response="已记住。",
        status="success",
    )

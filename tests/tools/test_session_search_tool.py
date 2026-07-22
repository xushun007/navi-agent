from navi_agent.runtime import Message, SQLiteSessionStore
from navi_agent.tooling import ToolContext
from navi_agent.tools.session_search_tool import SessionSearchTool


def test_session_search_discovers_and_reads_prior_messages(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "state.db")
    session = store.load("prior", "u1")
    store.append(session, Message(role="user", content="Use WAL for concurrent writes"))
    store.append(session, Message(role="assistant", content="Add bounded lock retries"))
    tool = SessionSearchTool(store)
    context = ToolContext(session_id="current", user_id="u1", iteration=1)

    search_result = tool.invoke(context=context, query="concurrent writes")
    match = search_result.structured_content["matches"][0]
    around_result = tool.invoke(
        context=context,
        session_id=match["session_id"],
        around_message_id=match["message_id"],
        window=1,
    )

    assert search_result.status == "success"
    assert match["session_id"] == "prior"
    assert around_result.status == "success"
    assert [item["content"] for item in around_result.structured_content["messages"]] == [
        "Use WAL for concurrent writes",
        "Add bounded lock retries",
    ]

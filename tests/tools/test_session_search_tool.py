from navi_agent.runtime import Message, SQLiteSessionStore, SessionMetadata
from navi_agent.tooling import ToolContext
from navi_agent.tools.session_search_tool import SessionSearchTool


def _append(store, session, *contents: str) -> None:
    for index, content in enumerate(contents):
        role = "user" if index % 2 == 0 else "assistant"
        store.append(session, Message(role=role, content=content))


def test_discovery_returns_session_shape_with_actual_message_windows(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "state.db")
    session = store.load(
        "prior",
        "u1",
        metadata=SessionMetadata(source="weixin", model="model-1"),
    )
    _append(
        store,
        session,
        "Start database work",
        "Inspect the schema",
        "Use WAL for concurrent writes",
        "Add bounded lock retries",
        "Run the focused tests",
        "All tests passed",
    )
    tool = SessionSearchTool(store)

    result = tool.invoke(
        context=ToolContext(session_id="current", user_id="u1", iteration=1),
        query="concurrent writes",
        window=1,
    )
    recalled = result.structured_content["sessions"][0]

    assert result.status == "success"
    assert result.structured_content["mode"] == "discovery"
    assert recalled["session_id"] == "prior"
    assert recalled["lineage_id"] == "prior"
    assert recalled["title"] == "Start database work"
    assert recalled["source"] == "weixin"
    assert recalled["model"] == "model-1"
    assert recalled["matched_message"]["content"] == "Use WAL for concurrent writes"
    assert "[[concurrent]]" in recalled["highlighted_snippet"]
    assert [item["content"] for item in recalled["beginning"]] == [
        "Start database work",
        "Inspect the schema",
    ]
    assert [item["content"] for item in recalled["window"]] == [
        "Inspect the schema",
        "Use WAL for concurrent writes",
        "Add bounded lock retries",
    ]
    assert [item["content"] for item in recalled["ending"]] == [
        "Run the focused tests",
        "All tests passed",
    ]
    assert recalled["messages_before"] == 1
    assert recalled["messages_after"] == 2


def test_discovery_supports_chinese_and_deduplicates_session_lineage(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "state.db")
    parent = store.load("parent", "u1")
    child = store.load(
        "child",
        "u1",
        metadata=SessionMetadata(parent_session_id="parent"),
    )
    other = store.load("other", "u1")
    _append(store, parent, "讨论微信网关重连策略")
    _append(store, child, "微信网关需要指数退避")
    _append(store, other, "另一个微信网关部署记录")
    tool = SessionSearchTool(store)

    result = tool.invoke(
        context=ToolContext(session_id="current", user_id="u1", iteration=1),
        query="微信网关",
        limit=10,
    )

    sessions = result.structured_content["sessions"]
    assert len(sessions) == 2
    assert {item["lineage_id"] for item in sessions} == {"parent", "other"}


def test_discovery_excludes_current_lineage_subagents_and_other_users(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "state.db")
    current = store.load("current", "u1")
    current_child = store.load(
        "current-child",
        "u1",
        metadata=SessionMetadata(parent_session_id=current.session_id),
    )
    subagent = store.load(
        "worker",
        "u1",
        metadata=SessionMetadata(
            source="subagent",
            agent_role="subagent",
            parent_session_id=current.session_id,
        ),
    )
    prior = store.load("prior", "u1")
    other_user = store.load("other-user", "u2")
    _append(store, current, "private recall marker")
    _append(store, current_child, "private recall marker")
    _append(store, subagent, "private recall marker")
    _append(store, prior, "private recall marker")
    _append(store, other_user, "private recall marker")
    tool = SessionSearchTool(store)

    result = tool.invoke(
        context=ToolContext(session_id="current-child", user_id="u1", iteration=1),
        query="private recall marker",
        limit=10,
    )

    assert [
        item["session_id"] for item in result.structured_content["sessions"]
    ] == ["prior"]


def test_read_and_around_are_bounded_with_truncation_metadata(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "state.db")
    session = store.load("prior", "u1")
    _append(store, session, *(f"message {index}" for index in range(8)))
    tool = SessionSearchTool(store)
    context = ToolContext(session_id="current", user_id="u1", iteration=1)

    read = tool.invoke(context=context, session_id="prior", limit=3)
    anchor_id = read.structured_content["messages"][1]["id"]
    around = tool.invoke(
        context=context,
        session_id="prior",
        around_message_id=anchor_id,
        window=1,
    )

    assert read.structured_content["mode"] == "read"
    assert read.structured_content["total_message_count"] == 8
    assert read.structured_content["messages_after"] == 5
    assert read.structured_content["truncated"] is True
    assert [item["content"] for item in around.structured_content["messages"]] == [
        "message 0",
        "message 1",
        "message 2",
    ]
    assert around.structured_content["messages_before"] == 0
    assert around.structured_content["messages_after"] == 5
    assert around.structured_content["messages"][1]["anchor"] is True


def test_read_and_around_enforce_user_and_current_lineage_isolation(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "state.db")
    current = store.load("current", "u1")
    _append(store, current, "current content")
    other_user = store.load("private", "u2")
    _append(store, other_user, "other user content")
    private_message = store.discover_sessions(
        query="other user",
        user_id="u2",
    )[0].matched_message
    tool = SessionSearchTool(store)
    context = ToolContext(session_id="current", user_id="u1", iteration=1)

    current_read = tool.invoke(context=context, session_id="current")
    private_read = tool.invoke(context=context, session_id="private")
    private_around = tool.invoke(
        context=context,
        session_id="private",
        around_message_id=private_message.id,
    )

    assert current_read.structured_content["found"] is False
    assert private_read.structured_content["found"] is False
    assert private_around.structured_content["found"] is False

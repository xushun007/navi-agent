import json

import pytest

from evals.longmemeval import load_samples, seed_history
from navi_agent.runtime import SQLiteSessionStore


def test_partial_input_requires_explicit_opt_in(tmp_path):
    path = tmp_path / "partial.json"
    path.write_text('[{"question_id":"first"}, {"question_id":', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_samples(path)
    samples, partial = load_samples(path, allow_partial=True)
    assert partial is True
    assert samples == [{"question_id": "first"}]


def test_extracts_only_complete_records_from_range_fragment(tmp_path):
    path = tmp_path / "range.part"
    path.write_text('truncated\n    {\n        "question_id": "a", "haystack_sessions": []\n    },\n    {\n        "question_id":', encoding="utf-8")
    samples, partial = load_samples(path, range_fragment=True)
    assert partial is True
    assert [sample["question_id"] for sample in samples] == ["a"]


def test_seeding_keeps_original_history_searchable_and_user_isolated(tmp_path):
    sample = {
        "haystack_session_ids": ["source-a", "source-b"],
        "haystack_dates": ["2024/01/01 (Mon) 00:00", "2024/02/01 (Thu) 00:00"],
        "haystack_sessions": [
            [{"role": "user", "content": "My graduation degree is mathematics.", "has_answer": True}],
            [{"role": "assistant", "content": "Unrelated conversation."}],
        ],
    }
    store = SQLiteSessionStore(tmp_path / "test.db")
    mapping = seed_history(store, sample, "owner")
    matches = store.discover_sessions(query="graduation degree", user_id="owner")
    assert mapping["source-a"] == [matches[0].session_id]
    assert store.discover_sessions(query="graduation degree", user_id="other") == []
    assert "has_answer" not in matches[0].matched_message.content


def test_seeding_accepts_repeated_official_session_ids(tmp_path):
    store = SQLiteSessionStore(tmp_path / "test.db")
    sample = {"haystack_session_ids": ["repeat", "repeat"],
              "haystack_dates": ["2024/01/01 (Mon) 00:00", "2024/02/01 (Thu) 00:00"],
              "haystack_sessions": [[{"role": "user", "content": "First"}],
                                    [{"role": "user", "content": "Second"}]]}
    assert seed_history(store, sample, "owner")["repeat"] == ["history:0", "history:1"]


def test_seeding_preserves_history_time_for_search_and_order(tmp_path):
    from datetime import datetime, timezone
    from navi_agent.tooling import ToolContext
    from navi_agent.tools.session_search_tool import SessionSearchTool

    store = SQLiteSessionStore(tmp_path / "test.db")
    sample = {"haystack_session_ids": ["new", "old"],
              "haystack_dates": ["2023/05/29 (Mon) 15:01", "2023/05/25 (Thu) 10:04"],
              "haystack_sessions": [[{"role": "user", "content": "common marker"}],
                                    [{"role": "user", "content": "common marker"}]]}
    seed_history(store, sample, "owner")
    results = store.discover_sessions(query="common marker", user_id="owner")
    timestamp = datetime(2023, 5, 29, 15, 1, tzinfo=timezone.utc).timestamp()
    assert [item.session_id for item in results] == ["history:0", "history:1"]
    assert results[0].timestamp == timestamp
    assert results[0].matched_message.created_at == timestamp
    context = ToolContext(session_id="question", user_id="owner", iteration=1)
    tool = SessionSearchTool(store)
    around = tool.invoke(context=context, session_id="history:0", around_message_id=results[0].matched_message.id)
    assert "Conversation date: 2023/05/29 (Mon) 15:01" in around.content

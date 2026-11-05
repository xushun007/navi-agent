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
        "haystack_dates": ["2024-01-01", "2024-02-01"],
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
              "haystack_dates": ["2024-01-01", "2024-02-01"],
              "haystack_sessions": [[{"role": "user", "content": "First"}],
                                    [{"role": "user", "content": "Second"}]]}
    assert seed_history(store, sample, "owner")["repeat"] == ["history:0", "history:1"]

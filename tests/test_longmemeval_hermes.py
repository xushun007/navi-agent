from datetime import datetime, timezone

import pytest

from evals.longmemeval_hermes import history_timestamp, seed_history


class FakeDB:
    def __init__(self):
        self.sessions = []
        self.messages = []
        self.updates = []

    def create_session(self, **kwargs):
        self.sessions.append(kwargs)

    def append_messages_batch(self, session_id, messages):
        self.messages.append((session_id, messages))

    def _execute_write(self, callback):
        callback(self)

    def execute(self, sql, params):
        self.updates.append((sql, params))


def test_history_seeding_preserves_source_wall_time_and_strips_labels():
    db = FakeDB()
    sample = {"haystack_session_ids": ["source"], "haystack_dates": ["2023/05/29 (Mon) 15:01"],
              "haystack_sessions": [[{"role": "user", "content": "My degree is mathematics", "has_answer": True}]]}
    seed_history(db, sample)
    timestamp = datetime(2023, 5, 29, 15, 1, tzinfo=timezone.utc).timestamp()
    assert db.updates[0][1] == (timestamp, timestamp, "history:0")
    assert db.messages[0][1][1] == {"role": "user", "content": "My degree is mathematics", "timestamp": timestamp}
    assert history_timestamp("2023/05/29 (Mon) 15:01") == timestamp


def test_rejects_inconsistent_history():
    with pytest.raises(ValueError):
        seed_history(FakeDB(), {"haystack_session_ids": ["s"], "haystack_dates": [], "haystack_sessions": []})

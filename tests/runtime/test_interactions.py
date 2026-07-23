from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from navi_agent.runtime import DeferredApprovalProvider, JsonPendingInteractionStore
from navi_agent.runtime.approval import ApprovalRequest
from navi_agent.tooling import ToolContext


class JsonPendingInteractionStoreTests(unittest.TestCase):
    def test_expire_returns_and_removes_stale_interactions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonPendingInteractionStore(
                Path(tmpdir) / "pending.json",
                ttl=timedelta(seconds=-1),
            )
            created = store.create(
                session_id="s1",
                user_id="u1",
                kind="clarification",
                prompt="Which environment?",
                run_id="run-1",
            )

            expired = store.expire("s1")

            self.assertEqual(expired, [created])
            self.assertIsNone(store.get_pending("s1"))

    def test_pending_interaction_survives_store_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "pending.json"
            created = JsonPendingInteractionStore(path).create(
                session_id="s1",
                user_id="u1",
                kind="clarification",
                prompt="Which environment?",
            )

            restored = JsonPendingInteractionStore(path).get_pending("s1")

        self.assertIsNotNone(restored)
        self.assertEqual(restored.interaction_id, created.interaction_id)
        self.assertEqual(restored.prompt, "Which environment?")

    def test_approved_tool_call_is_consumed_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonPendingInteractionStore(Path(tmpdir) / "pending.json")
            provider = DeferredApprovalProvider(store)
            request = ApprovalRequest(
                tool_name="bash",
                arguments={"command": "pwd"},
                reason="approval required",
                context=ToolContext(session_id="s1", user_id="u1", iteration=1),
            )

            pending = provider.request_approval(request)
            store.resolve("s1", approved=True)
            approved = provider.request_approval(request)
            pending_again = provider.request_approval(request)

        self.assertFalse(pending.approved)
        self.assertTrue(pending.metadata["interaction_pending"])
        self.assertTrue(approved.approved)
        self.assertFalse(pending_again.approved)
        self.assertTrue(pending_again.metadata["interaction_pending"])

    def test_unused_approval_can_be_revoked_after_resume_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonPendingInteractionStore(Path(tmpdir) / "pending.json")
            store.create(
                session_id="s1",
                user_id="u1",
                kind="approval",
                prompt="Approve?",
                tool_name="bash",
                arguments={"command": "pwd"},
            )
            store.resolve("s1", approved=True)

            store.discard_approved("s1")

            self.assertIsNone(
                store.consume_approval(
                    session_id="s1",
                    tool_name="bash",
                    arguments={"command": "pwd"},
                )
            )

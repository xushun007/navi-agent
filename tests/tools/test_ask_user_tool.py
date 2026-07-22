from __future__ import annotations

import tempfile
from pathlib import Path

from navi_agent.runtime import JsonPendingInteractionStore
from navi_agent.tooling import ToolContext
from navi_agent.tools import AskUserTool


def test_ask_user_creates_persisted_clarification() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = JsonPendingInteractionStore(Path(tmpdir) / "pending.json")
        tool = AskUserTool(store)

        result = tool.invoke(
            context=ToolContext(session_id="s1", user_id="u1", iteration=1),
            question="Which environment?",
        )
        pending = store.get_pending("s1")

    assert result.status == "success"
    assert result.structured_content["interaction_pending"] is True
    assert pending is not None
    assert pending.kind == "clarification"
    assert pending.prompt == "Which environment?"

import unittest

from navi_agent.runtime import ContextEngine, Message, ToolCall


class FakeSummarizer:
    def __init__(self, summary: str = "[Context Summary]\nLLM merged historical context") -> None:
        self.summary = summary
        self.calls = []

    def summarize(self, *, middle, latest_user_message):
        self.calls.append({"middle": middle, "latest_user_message": latest_user_message})
        return self.summary


class ContextEngineTests(unittest.TestCase):
    def test_keeps_under_budget_context_unchanged(self) -> None:
        messages = [
            Message(role="system", content="system"),
            Message(role="user", content="hello"),
            Message(role="assistant", content="done"),
        ]
        engine = ContextEngine(context_limit_tokens=1_000, reserved_output_tokens=100)

        result = engine.build(messages)

        self.assertFalse(result.compressed)
        self.assertEqual(result.messages, messages)
        self.assertEqual(result.estimated_tokens_before, result.estimated_tokens_after)

    def test_compresses_middle_and_preserves_head_and_tail(self) -> None:
        messages = [
            Message(role="system", content="system governance"),
            Message(role="user", content="initial task framing"),
            Message(role="assistant", content="initial answer"),
            Message(role="user", content="middle user ask " + "x" * 300),
            Message(role="assistant", content="middle answer " + "y" * 300),
            Message(role="user", content="final request"),
            Message(role="assistant", content="final answer"),
        ]
        engine = ContextEngine(
            context_limit_tokens=180,
            reserved_output_tokens=20,
            compression_threshold_ratio=0.5,
            protect_first_messages=2,
            tail_budget_ratio=0.2,
            summarizer=FakeSummarizer("[Context Summary]\nmiddle user ask was completed semantically"),
        )

        result = engine.build(messages)

        self.assertTrue(result.compressed)
        self.assertEqual(result.messages[0].content, "system governance")
        self.assertEqual(result.messages[1].content, "initial task framing")
        self.assertEqual(result.messages[2].content, "initial answer")
        self.assertEqual(result.messages[3].role, "system")
        self.assertIn("[Context Summary]", result.messages[3].content)
        self.assertIn("middle user ask", result.messages[3].content)
        self.assertEqual(result.summary_status, "llm")
        self.assertEqual([message.content for message in result.messages[-2:]], ["final request", "final answer"])

    def test_latest_user_message_is_anchored_verbatim(self) -> None:
        messages = [
            Message(role="system", content="system"),
            Message(role="user", content="initial"),
            Message(role="assistant", content="ok"),
            Message(role="assistant", content="large tool output " + "x" * 2_000),
            Message(role="user", content="do this exact latest request"),
            Message(role="assistant", content="not answered yet " + "y" * 500),
        ]
        engine = ContextEngine(
            context_limit_tokens=220,
            reserved_output_tokens=20,
            compression_threshold_ratio=0.5,
            protect_first_messages=2,
            tail_budget_ratio=0.05,
            summarizer=FakeSummarizer(),
        )

        result = engine.build(messages)

        self.assertTrue(result.compressed)
        self.assertTrue(result.latest_user_anchored)
        self.assertIn("do this exact latest request", [message.content for message in result.messages])

    def test_does_not_leave_orphaned_tool_result_in_tail(self) -> None:
        messages = [
            Message(role="system", content="system"),
            Message(role="user", content="initial"),
            Message(role="assistant", content="ok"),
            Message(role="assistant", content="middle filler " + "m" * 400),
            Message(role="user", content="run tool"),
            Message(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="tc1", name="read_file", arguments={"path": "a.py"})],
            ),
            Message(role="tool", content="file content " + "x" * 400, tool_call_id="tc1"),
            Message(role="user", content="latest request after tool"),
            Message(role="assistant", content="done"),
        ]
        engine = ContextEngine(
            context_limit_tokens=160,
            reserved_output_tokens=20,
            compression_threshold_ratio=0.5,
            protect_first_messages=2,
            tail_budget_ratio=0.1,
            summarizer=FakeSummarizer(),
        )

        result = engine.build(messages)

        roles = [message.role for message in result.messages]
        self.assertTrue(result.compressed)
        self.assertNotEqual(roles[-2:], ["tool", "assistant"])
        for index, message in enumerate(result.messages):
            if message.role == "tool":
                self.assertGreater(index, 0)
                self.assertEqual(result.messages[index - 1].role, "assistant")

    def test_preserves_protected_assistant_tool_call_with_result(self) -> None:
        messages = [
            Message(role="system", content="system"),
            Message(role="user", content="initial"),
            Message(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="tc1", name="search_files", arguments={"query": "abc"})],
            ),
            Message(role="tool", content="protected result", tool_call_id="tc1"),
            Message(role="assistant", content="middle filler " + "x" * 600),
            Message(role="user", content="latest request"),
            Message(role="assistant", content="latest answer"),
        ]
        engine = ContextEngine(
            context_limit_tokens=180,
            reserved_output_tokens=20,
            compression_threshold_ratio=0.5,
            protect_first_messages=2,
            tail_budget_ratio=0.15,
            summarizer=FakeSummarizer(),
        )

        result = engine.build(messages)

        self.assertTrue(result.compressed)
        self.assertTrue(any(message.role == "assistant" and message.tool_calls for message in result.messages))
        self.assertTrue(any(message.role == "tool" and message.tool_call_id == "tc1" for message in result.messages))

    def test_recompacts_existing_context_summary_without_nested_summary(self) -> None:
        previous_summary = (
            "[Context Summary]\n"
            "Older middle conversation turns were compacted into this checkpoint.\n\n"
            "## User Inputs Preserved\n"
            "- previous user requirement\n\n"
            "--- END OF CONTEXT SUMMARY — respond to the latest user message after this summary ---"
        )
        messages = [
            Message(role="system", content="system"),
            Message(role="user", content="initial"),
            Message(role="assistant", content="ok"),
            Message(role="system", content=previous_summary),
            Message(role="assistant", content="large middle output " + "x" * 800),
            Message(role="user", content="latest request"),
            Message(role="assistant", content="latest answer"),
        ]
        engine = ContextEngine(
            context_limit_tokens=180,
            reserved_output_tokens=20,
            compression_threshold_ratio=0.5,
            protect_first_messages=2,
            tail_budget_ratio=0.15,
            summarizer=FakeSummarizer("[Context Summary]\n## Prior Context Summary\nprevious user requirement"),
        )

        result = engine.build(messages)

        summaries = [message for message in result.messages if message.content.startswith("[Context Summary]")]
        self.assertTrue(result.compressed)
        self.assertEqual(len(summaries), 1)
        self.assertIn("## Prior Context Summary", summaries[0].content)
        self.assertIn("previous user requirement", summaries[0].content)
        self.assertEqual(summaries[0].content.count("[Context Summary]"), 1)

    def test_over_budget_context_without_summarizer_is_not_compressed(self) -> None:
        messages = [
            Message(role="system", content="system"),
            Message(role="user", content="initial"),
            Message(role="assistant", content="ok"),
            Message(role="assistant", content="large middle output " + "x" * 800),
            Message(role="user", content="latest request"),
            Message(role="assistant", content="latest answer"),
        ]
        engine = ContextEngine(
            context_limit_tokens=180,
            reserved_output_tokens=20,
            compression_threshold_ratio=0.5,
            protect_first_messages=2,
            tail_budget_ratio=0.15,
        )

        result = engine.build(messages)

        self.assertFalse(result.compressed)
        self.assertEqual(result.messages, messages)
        self.assertEqual(result.summary_status, "missing_summarizer")


if __name__ == "__main__":
    unittest.main()

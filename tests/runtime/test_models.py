import unittest

from navi_agent.runtime.models import (
    ConversationState, Message, ModelResponse, RuntimeEvent, RuntimeResult, ToolCall,
)
from navi_agent.tooling import ToolResult


class ModelsTest(unittest.TestCase):
    def test_tool_call(self) -> None:
        tc = ToolCall(id="tc1", name="bash", arguments={"cmd": "pwd"})
        self.assertEqual(tc.name, "bash")
        self.assertEqual(tc.arguments, {"cmd": "pwd"})

    def test_message(self) -> None:
        msg = Message(role="user", content="hello")
        self.assertEqual(msg.role, "user")
        self.assertIsNone(msg.reasoning_content)
        self.assertEqual(msg.tool_calls, [])

    def test_message_with_tool_calls(self) -> None:
        tc = ToolCall(id="tc1", name="bash")
        msg = Message(role="assistant", content="", tool_calls=[tc])
        self.assertEqual(len(msg.tool_calls), 1)

    def test_model_response(self) -> None:
        resp = ModelResponse(content="hello")
        self.assertEqual(resp.content, "hello")
        self.assertIsNone(resp.reasoning_content)

    def test_model_response_with_tool_calls(self) -> None:
        tc = ToolCall(id="tc1", name="bash")
        resp = ModelResponse(tool_calls=[tc])
        self.assertEqual(len(resp.tool_calls), 1)

    def test_conversation_state(self) -> None:
        state = ConversationState(session_id="s1", user_id="u1")
        state.messages.append(Message(role="user", content="hi"))
        self.assertEqual(len(state.messages), 1)

    def test_runtime_result(self) -> None:
        tr = ToolResult(tool_call_id="tc1", name="bash", content="ok")
        result = RuntimeResult(session_id="s1", status="success", final_response="Done", tool_results=[tr])
        self.assertEqual(result.final_response, "Done")
        self.assertEqual(len(result.tool_results), 1)

    def test_runtime_event(self) -> None:
        event = RuntimeEvent(name="runtime.started", session_id="s1", user_id="u1", iteration=1)
        self.assertEqual(event.name, "runtime.started")

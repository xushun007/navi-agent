import unittest

from navi_agent.runtime import (
    AutoApproveApprovalProvider,
    ToolCall,
    ToolContext,
    ToolExecutor,
    ToolResult,
)
from navi_agent.runtime.tool_policy import SensitiveToolPolicy
from navi_agent.tools import FunctionTool


class ToolExecutorTests(unittest.TestCase):
    def test_executor_runs_allowed_tool(self) -> None:
        executor = ToolExecutor(policy=SensitiveToolPolicy())
        tools = {
            "echo": FunctionTool(
                name="echo",
                description="echo",
                handler=lambda value: ToolResult.ok(name="echo", content=value),
            )
        }

        result = executor.execute(
            tool_calls=[ToolCall(id="tc1", name="echo", arguments={"value": "ping"})],
            tools_by_name=tools,
            context=ToolContext(session_id="s1", user_id="u1", iteration=1),
        )

        self.assertEqual(result[0].content, "ping")
        self.assertEqual(result[0].tool_call_id, "tc1")

    def test_executor_returns_structured_approval_request(self) -> None:
        executor = ToolExecutor(
            policy=SensitiveToolPolicy(
                approval_required_tools={"bash": "bash requires approval"}
            )
        )
        tools = {
            "bash": FunctionTool(
                name="bash",
                description="bash",
                handler=lambda command: ToolResult.ok(name="bash", content=command),
            )
        }

        result = executor.execute(
            tool_calls=[ToolCall(id="tc1", name="bash", arguments={"command": "pwd"})],
            tools_by_name=tools,
        )

        self.assertEqual(result[0].status, "error")
        self.assertTrue(result[0].structured_content["approval_required"])
        self.assertEqual(result[0].metadata["tool_name"], "bash")

    def test_executor_can_run_tool_after_auto_approval(self) -> None:
        executor = ToolExecutor(
            policy=SensitiveToolPolicy(
                approval_required_tools={"bash": "bash requires approval"}
            ),
            approval_provider=AutoApproveApprovalProvider(),
        )
        tools = {
            "bash": FunctionTool(
                name="bash",
                description="bash",
                handler=lambda command: ToolResult.ok(name="bash", content=f"ran:{command}"),
            )
        }

        result = executor.execute(
            tool_calls=[ToolCall(id="tc1", name="bash", arguments={"command": "pwd"})],
            tools_by_name=tools,
        )

        self.assertEqual(result[0].status, "success")
        self.assertEqual(result[0].content, "ran:pwd")


if __name__ == "__main__":
    unittest.main()

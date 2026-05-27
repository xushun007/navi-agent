import unittest

from navi_agent.tooling import ToolDecision
from navi_agent.runtime import ToolCall, ToolContext, ToolDefinition, ToolRegistry, ToolResult, ToolsetDefinition
from navi_agent.tools import BaseTool, FunctionTool
from navi_agent.runtime.tool_policy import SensitiveToolPolicy, StaticToolPolicy


def ok_result(name: str, content: str, **kwargs) -> ToolResult:
    return ToolResult(tool_call_id="", name=name, content=content, **kwargs)


class ToolRegistryTests(unittest.TestCase):
    def test_registry_accepts_base_tool_instances(self) -> None:
        registry = ToolRegistry(
            registered_tools=[
                ("utility", FunctionTool(name="echo", description="Echo", handler=lambda value: ok_result("echo", value)))
            ]
        )

        result = registry.dispatch([ToolCall(id="tc1", name="echo", arguments={"value": "ping"})])

        self.assertEqual(result[0].content, "ping")

    def test_registry_exposes_full_tool_schema(self) -> None:
        registry = ToolRegistry(
            definitions=[
                ToolDefinition(
                    name="echo",
                    description="Echo a value",
                    parameters={
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                    },
                    handler=lambda value: ok_result("echo", value),
                )
            ]
        )

        self.assertEqual(
            registry.schemas(),
            [
                {
                    "name": "echo",
                    "description": "Echo a value",
                    "parameters": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                    },
                }
            ],
        )

    def test_registry_dispatches_registered_tool_definition(self) -> None:
        registry = ToolRegistry(
            definitions=[
                ToolDefinition(
                    name="echo",
                    handler=lambda value: ok_result("echo", f"tool:{value}"),
                )
            ]
        )

        result = registry.dispatch([ToolCall(id="tc1", name="echo", arguments={"value": "ping"})])

        self.assertEqual(result[0].name, "echo")
        self.assertEqual(result[0].content, "tool:ping")
        self.assertEqual(result[0].status, "success")

    def test_registry_returns_error_result_for_tool_failure(self) -> None:
        def fail_tool() -> ToolResult:
            raise RuntimeError("boom")

        registry = ToolRegistry(
            definitions=[
                ToolDefinition(
                    name="fail",
                    handler=fail_tool,
                )
            ]
        )

        result = registry.dispatch([ToolCall(id="tc1", name="fail", arguments={})])

        self.assertEqual(result[0].name, "fail")
        self.assertEqual(result[0].status, "error")
        self.assertIn("boom", result[0].content)

    def test_registry_filters_schemas_by_toolset(self) -> None:
        registry = ToolRegistry(
            definitions=[
                ToolDefinition(name="web_search", handler=lambda query: ok_result("web_search", query), toolset="web"),
                ToolDefinition(name="read_file", handler=lambda path: ok_result("read_file", path), toolset="file"),
            ],
            toolsets=[
                ToolsetDefinition(name="web", tools=["web_search"]),
                ToolsetDefinition(name="file", tools=["read_file"]),
            ],
        )

        result = registry.schemas(enabled_toolsets=["web"])

        self.assertEqual([item["name"] for item in result], ["web_search"])

    def test_registry_supports_composed_toolsets(self) -> None:
        registry = ToolRegistry(
            definitions=[
                ToolDefinition(name="web_search", handler=lambda query: ok_result("web_search", query), toolset="web"),
                ToolDefinition(name="browser_open", handler=lambda url: ok_result("browser_open", url), toolset="browser"),
            ],
            toolsets=[
                ToolsetDefinition(name="web", tools=["web_search"]),
                ToolsetDefinition(name="browser", tools=["browser_open"]),
                ToolsetDefinition(name="research", includes=["web", "browser"]),
            ],
        )

        result = registry.schemas(enabled_toolsets=["research"])

        self.assertEqual([item["name"] for item in result], ["browser_open", "web_search"])

    def test_registry_passes_tool_context_to_context_aware_handler(self) -> None:
        captured = {}

        def inspect(context: ToolContext, value: str) -> ToolResult:
            captured["session_id"] = context.session_id
            captured["iteration"] = context.iteration
            return ok_result("inspect", f"{context.user_id}:{value}")

        registry = ToolRegistry(
            definitions=[ToolDefinition(name="inspect", handler=inspect, toolset="debug")]
        )

        result = registry.dispatch(
            [ToolCall(id="tc1", name="inspect", arguments={"value": "ping"})],
            context=ToolContext(session_id="s1", user_id="u1", iteration=2),
        )

        self.assertEqual(result[0].content, "u1:ping")
        self.assertEqual(captured, {"session_id": "s1", "iteration": 2})

    def test_registry_preserves_structured_tool_result(self) -> None:
        registry = ToolRegistry(
            registered_tools=[
                (
                    "utility",
                    FunctionTool(
                        name="echo",
                        description="Echo",
                        handler=lambda value: ToolResult(
                            tool_call_id="",
                            name="echo",
                            content=value,
                            structured_content={"value": value},
                        ),
                    ),
                )
            ]
        )

        result = registry.dispatch([ToolCall(id="tc1", name="echo", arguments={"value": "ping"})])

        self.assertEqual(result[0].structured_content["value"], "ping")
        self.assertEqual(result[0].tool_call_id, "tc1")

    def test_registry_filters_unavailable_base_tool(self) -> None:
        class UnavailableTool(BaseTool):
            @property
            def name(self) -> str:
                return "hidden"

            @property
            def description(self) -> str:
                return "Unavailable"

            def schema(self) -> dict:
                return {"type": "object", "properties": {}}

            def is_available(self) -> bool:
                return False

            def invoke(self, context: ToolContext | None = None, **kwargs) -> ToolResult:
                return ok_result("hidden", "nope")

        registry = ToolRegistry(registered_tools=[("utility", UnavailableTool())])

        self.assertEqual(registry.schemas(), [])

    def test_registry_returns_error_when_policy_denies_tool(self) -> None:
        called = {"value": False}

        def echo(value: str) -> ToolResult:
            called["value"] = True
            return ok_result("bash", value)

        class DenyPolicy:
            def decide(self, tool_name: str, arguments: dict, context: ToolContext | None) -> ToolDecision:
                return ToolDecision.deny("bash commands require approval")

        registry = ToolRegistry(
            registered_tools=[("terminal", FunctionTool(name="bash", description="bash", handler=echo))],
            policy=DenyPolicy(),
        )

        result = registry.dispatch([ToolCall(id="tc1", name="bash", arguments={"value": "ls"})])

        self.assertFalse(called["value"])
        self.assertEqual(result[0].status, "error")
        self.assertIn("require approval", result[0].content)

    def test_static_tool_policy_denies_configured_tool_names(self) -> None:
        policy = StaticToolPolicy(
            denied_tools={
                "bash": "bash requires approval",
                "write_file": "write_file requires approval",
            }
        )

        bash_decision = policy.decide("bash", {}, None)
        read_decision = policy.decide("read_file", {}, None)

        self.assertFalse(bash_decision.allows_execution)
        self.assertEqual(bash_decision.reason, "bash requires approval")
        self.assertTrue(read_decision.allows_execution)

    def test_sensitive_tool_policy_marks_approval_required_tools(self) -> None:
        policy = SensitiveToolPolicy(
            approval_required_tools={
                "bash": "bash requires approval",
            }
        )

        decision = policy.decide("bash", {"command": "pwd"}, None)

        self.assertFalse(decision.allows_execution)
        self.assertTrue(decision.requires_approval)
        self.assertEqual(decision.metadata["tool_name"], "bash")

    def test_registry_returns_structured_approval_request(self) -> None:
        registry = ToolRegistry(
            registered_tools=[("terminal", FunctionTool(name="bash", description="bash", handler=lambda: ok_result("bash", "ok")))],
            policy=SensitiveToolPolicy(
                approval_required_tools={
                    "bash": "bash requires approval",
                }
            ),
        )

        result = registry.dispatch([ToolCall(id="tc1", name="bash", arguments={"command": "pwd"})])

        self.assertEqual(result[0].status, "error")
        self.assertTrue(result[0].structured_content["approval_required"])
        self.assertEqual(result[0].structured_content["arguments"]["command"], "pwd")


if __name__ == "__main__":
    unittest.main()

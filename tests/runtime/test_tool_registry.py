import unittest

from navi_agent.runtime import ToolCall, ToolContext, ToolDefinition, ToolRegistry, ToolsetDefinition


class ToolRegistryTests(unittest.TestCase):
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
                    handler=lambda value: value,
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
                    handler=lambda value: f"tool:{value}",
                )
            ]
        )

        result = registry.dispatch([ToolCall(id="tc1", name="echo", arguments={"value": "ping"})])

        self.assertEqual(result[0].name, "echo")
        self.assertEqual(result[0].content, "tool:ping")
        self.assertEqual(result[0].status, "success")

    def test_registry_returns_error_result_for_tool_failure(self) -> None:
        def fail_tool() -> str:
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
                ToolDefinition(name="web_search", handler=lambda query: query, toolset="web"),
                ToolDefinition(name="read_file", handler=lambda path: path, toolset="file"),
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
                ToolDefinition(name="web_search", handler=lambda query: query, toolset="web"),
                ToolDefinition(name="browser_open", handler=lambda url: url, toolset="browser"),
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

        def inspect(context: ToolContext, value: str) -> str:
            captured["session_id"] = context.session_id
            captured["iteration"] = context.iteration
            return f"{context.user_id}:{value}"

        registry = ToolRegistry(
            definitions=[ToolDefinition(name="inspect", handler=inspect, toolset="debug")]
        )

        result = registry.dispatch(
            [ToolCall(id="tc1", name="inspect", arguments={"value": "ping"})],
            context=ToolContext(session_id="s1", user_id="u1", iteration=2),
        )

        self.assertEqual(result[0].content, "u1:ping")
        self.assertEqual(captured, {"session_id": "s1", "iteration": 2})


if __name__ == "__main__":
    unittest.main()

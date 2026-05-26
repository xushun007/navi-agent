import unittest

from navi_agent.runtime import ToolCall, ToolDefinition, ToolRegistry


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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from navi_agent.runtime.resources import (
    RuntimeResources,
    StaticToolProvider,
    ToolRegistration,
    load_runtime_resources,
)
from navi_agent.tooling import ToolResult
from navi_agent.tools.base import FunctionTool


def make_tool(name: str) -> FunctionTool:
    return FunctionTool(
        name=name,
        description=name,
        handler=lambda: ToolResult.ok(name=name, content="ok"),
    )


class FakeToolProvider:
    def __init__(self, source: str, *tool_names: str) -> None:
        self.source = source
        self.tool_names = tool_names
        self.close_calls = 0

    def load_tools(self) -> tuple[ToolRegistration, ...]:
        return tuple(
            ToolRegistration(
                tool=make_tool(name),
                toolsets=(self.source,),
                source=self.source,
            )
            for name in self.tool_names
        )

    def close(self) -> None:
        self.close_calls += 1


class RuntimeResourcesTests(unittest.TestCase):
    def test_static_provider_does_not_own_resolved_tools(self) -> None:
        registration = ToolRegistration(
            tool=make_tool("shared"), toolsets=("mcp",), source="mcp:shared"
        )
        provider = StaticToolProvider([registration])

        self.assertEqual(provider.load_tools(), (registration,))
        self.assertIsNone(provider.close())

    def test_loads_tool_providers_in_order(self) -> None:
        first = FakeToolProvider("builtin", "read_file", "write_file")
        second = FakeToolProvider("mcp:files", "mcp__files__search")

        resources = load_runtime_resources([first, second])

        self.assertEqual(
            [registration.tool.name for registration in resources.tools],
            ["read_file", "write_file", "mcp__files__search"],
        )
        self.assertEqual(
            [registration.source for registration in resources.tools],
            ["builtin", "builtin", "mcp:files"],
        )

    def test_rejects_duplicate_public_tool_names_and_closes_providers(self) -> None:
        first = FakeToolProvider("builtin", "read_file")
        second = FakeToolProvider("external", "read_file")

        with self.assertRaisesRegex(
            ValueError,
            "Duplicate tool name 'read_file' from 'builtin' and 'external'",
        ):
            load_runtime_resources([first, second])

        self.assertEqual(first.close_calls, 1)
        self.assertEqual(second.close_calls, 1)

    def test_close_is_idempotent_and_uses_reverse_provider_order(self) -> None:
        closed: list[str] = []
        resources = RuntimeResources(
            close_callbacks=(
                lambda: closed.append("first"),
                lambda: closed.append("second"),
            )
        )

        resources.close()
        resources.close()

        self.assertEqual(closed, ["second", "first"])

    def test_registration_requires_toolset_and_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "must belong to a toolset"):
            ToolRegistration(tool=make_tool("read_file"), toolsets=(), source="builtin")
        with self.assertRaisesRegex(ValueError, "must have a source"):
            ToolRegistration(tool=make_tool("read_file"), toolsets=("file",), source=" ")


if __name__ == "__main__":
    unittest.main()

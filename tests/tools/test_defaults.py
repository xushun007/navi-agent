import tempfile
import unittest
from pathlib import Path

from navi_agent.runtime import SubagentService, ToolCall, ToolContext
from navi_agent.tooling import ToolResult
from navi_agent.tools.base import FunctionTool
from navi_agent.tools.defaults import build_default_tool_registry


class DefaultsTest(unittest.TestCase):
    def test_read_only_file_count_runs_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "one.txt").write_text("one", encoding="utf-8")
            (root / "nested").mkdir()
            (root / "nested" / "two.txt").write_text("two", encoding="utf-8")
            registry = build_default_tool_registry(root=root)

            result = registry.dispatch(
                [
                    ToolCall(
                        id="tc1",
                        name="bash",
                        arguments={"command": "find . -type f | wc -l"},
                    )
                ],
                context=ToolContext(session_id="s1", user_id="u1", iteration=1),
            )[0]

        self.assertEqual(result.status, "success")
        self.assertEqual(result.structured_content["stdout"], "2")

    def test_all_tools_registered(self) -> None:
        schemas = build_default_tool_registry(
            subagent_service=SubagentService(
                runtime_factory=lambda _tools, _parent, _non_interactive: None
            )
        ).schemas()
        names = {s["name"] for s in schemas}
        self.assertEqual(
            names,
            {
                "bash",
                "background_task",
                "code_executor",
                "glob",
                "grep",
                "read_file",
                "write_file",
                "patch",
                "memory",
                "todo",
                "cron",
                "delegate_task",
                "web_fetch",
                "web_search",
            },
        )

    def test_toolset_filtering(self) -> None:
        registry = build_default_tool_registry(
            subagent_service=SubagentService(
                runtime_factory=lambda _tools, _parent, _non_interactive: None
            )
        )
        file_tools = {s["name"] for s in registry.schemas(enabled_toolsets=["file"])}
        self.assertEqual(
            file_tools,
            {"read_file", "glob", "grep", "write_file", "patch"},
        )
        terminal_tools = {s["name"] for s in registry.schemas(enabled_toolsets=["terminal"])}
        self.assertEqual(terminal_tools, {"bash", "background_task"})
        code_tools = {s["name"] for s in registry.schemas(enabled_toolsets=["code"])}
        self.assertEqual(code_tools, {"code_executor"})
        scheduler_tools = {s["name"] for s in registry.schemas(enabled_toolsets=["scheduler"])}
        self.assertEqual(scheduler_tools, {"cron"})
        delegation_tools = {s["name"] for s in registry.schemas(enabled_toolsets=["delegation"])}
        self.assertEqual(delegation_tools, {"delegate_task"})
        web_tools = {s["name"] for s in registry.schemas(enabled_toolsets=["web"])}
        self.assertEqual(web_tools, {"web_search", "web_fetch"})

    def test_web_search_is_registered_when_configured(self) -> None:
        schemas = build_default_tool_registry(
            web_search_api_key="search-key",
        ).schemas(enabled_toolsets=["web"])

        self.assertEqual(
            {schema["name"] for schema in schemas},
            {"web_search", "web_fetch"},
        )

    def test_mcp_tools_are_registered_in_dedicated_toolset(self) -> None:
        tool = FunctionTool(
            name="mcp__files__read_file",
            description="Read a remote file.",
            parameters={"type": "object", "properties": {}},
            handler=lambda: ToolResult.ok(name="mcp__files__read_file", content="ok"),
        )
        registry = build_default_tool_registry(mcp_tools=[tool])

        mcp_names = {
            schema["name"] for schema in registry.schemas(enabled_toolsets=["mcp"])
        }
        core_names = {
            schema["name"] for schema in registry.schemas(enabled_toolsets=["core"])
        }

        self.assertEqual(mcp_names, {"mcp__files__read_file"})
        self.assertIn("mcp__files__read_file", core_names)

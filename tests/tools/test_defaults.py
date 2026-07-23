import tempfile
import unittest
from pathlib import Path

from navi_agent.runtime import SubagentService, ToolCall, ToolContext
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
                "read_file",
                "search_files",
                "write_file",
                "patch",
                "memory",
                "todo",
                "cron",
                "delegate_task",
            },
        )

    def test_toolset_filtering(self) -> None:
        registry = build_default_tool_registry(
            subagent_service=SubagentService(
                runtime_factory=lambda _tools, _parent, _non_interactive: None
            )
        )
        file_tools = {s["name"] for s in registry.schemas(enabled_toolsets=["file"])}
        self.assertEqual(file_tools, {"read_file", "search_files", "write_file", "patch"})
        terminal_tools = {s["name"] for s in registry.schemas(enabled_toolsets=["terminal"])}
        self.assertEqual(terminal_tools, {"bash", "background_task"})
        code_tools = {s["name"] for s in registry.schemas(enabled_toolsets=["code"])}
        self.assertEqual(code_tools, {"code_executor"})
        scheduler_tools = {s["name"] for s in registry.schemas(enabled_toolsets=["scheduler"])}
        self.assertEqual(scheduler_tools, {"cron"})
        delegation_tools = {s["name"] for s in registry.schemas(enabled_toolsets=["delegation"])}
        self.assertEqual(delegation_tools, {"delegate_task"})

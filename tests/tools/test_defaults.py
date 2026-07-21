import unittest

from navi_agent.tools.defaults import build_default_tool_registry


class DefaultsTest(unittest.TestCase):
    def test_all_tools_registered(self) -> None:
        schemas = build_default_tool_registry().schemas()
        names = {s["name"] for s in schemas}
        self.assertEqual(
            names,
            {"bash", "code_executor", "read_file", "search_files", "write_file", "patch", "memory", "todo", "cron"},
        )

    def test_toolset_filtering(self) -> None:
        registry = build_default_tool_registry()
        file_tools = {s["name"] for s in registry.schemas(enabled_toolsets=["file"])}
        self.assertEqual(file_tools, {"read_file", "search_files", "write_file", "patch"})
        terminal_tools = {s["name"] for s in registry.schemas(enabled_toolsets=["terminal"])}
        self.assertEqual(terminal_tools, {"bash"})
        code_tools = {s["name"] for s in registry.schemas(enabled_toolsets=["code"])}
        self.assertEqual(code_tools, {"code_executor"})
        scheduler_tools = {s["name"] for s in registry.schemas(enabled_toolsets=["scheduler"])}
        self.assertEqual(scheduler_tools, {"cron"})

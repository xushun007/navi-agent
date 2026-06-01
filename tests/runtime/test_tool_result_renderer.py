import unittest

from navi_agent.runtime.tool_result_renderer import DefaultToolResultRenderer
from navi_agent.tooling import ToolArtifact, ToolResult


class DefaultToolResultRendererTest(unittest.TestCase):
    def setUp(self) -> None:
        self.renderer = DefaultToolResultRenderer()

    def test_renders_content(self) -> None:
        r = ToolResult(tool_call_id="tc1", name="bash", content="hello")
        self.assertEqual(self.renderer.render(r), "hello")

    def test_falls_back_to_structured_content(self) -> None:
        r = ToolResult(tool_call_id="tc1", name="search", content="", structured_content={"hits": 5})
        out = self.renderer.render(r)
        self.assertIn("hits=5", out)

    def test_renders_artifacts(self) -> None:
        r = ToolResult(tool_call_id="tc1", name="fetch", content="ok", artifacts=[
            ToolArtifact(kind="image", uri="/tmp/img.png", title="Shot"),
        ])
        out = self.renderer.render(r)
        self.assertIn("Shot", out)
        self.assertIn("Artifacts", out)

    def test_empty_result_renders_status(self) -> None:
        r = ToolResult(tool_call_id="tc1", name="bash", content="")
        self.assertEqual(self.renderer.render(r), "bash: success")

from __future__ import annotations

from threading import Barrier, Lock
from time import sleep
import unittest

from navi_agent.runtime import ToolCall, ToolDefinition, ToolRegistry, ToolResult
from navi_agent.runtime.approval import ApprovalDecision
from navi_agent.runtime.tool_policy import SensitiveToolPolicy


def _ok(name: str, content: str) -> ToolResult:
    return ToolResult.ok(name=name, content=content)


class ToolConcurrencyTests(unittest.TestCase):
    def test_independent_path_scoped_calls_run_concurrently(self) -> None:
        barrier = Barrier(2)

        def read_file(path: str) -> ToolResult:
            barrier.wait(timeout=1)
            return _ok("read_file", path)

        registry = ToolRegistry(
            definitions=[ToolDefinition(name="read_file", handler=read_file)]
        )

        results = registry.dispatch(
            [
                ToolCall(id="tc1", name="read_file", arguments={"path": "a.txt"}),
                ToolCall(id="tc2", name="read_file", arguments={"path": "b.txt"}),
            ]
        )

        self.assertEqual([result.status for result in results], ["success", "success"])

    def test_concurrent_results_preserve_model_call_order(self) -> None:
        barrier = Barrier(2)

        def read_file(path: str) -> ToolResult:
            barrier.wait(timeout=1)
            if path == "slow.txt":
                sleep(0.05)
            return _ok("read_file", path)

        registry = ToolRegistry(
            definitions=[ToolDefinition(name="read_file", handler=read_file)]
        )

        results = registry.dispatch(
            [
                ToolCall(id="slow", name="read_file", arguments={"path": "slow.txt"}),
                ToolCall(id="fast", name="read_file", arguments={"path": "fast.txt"}),
            ]
        )

        self.assertEqual([result.tool_call_id for result in results], ["slow", "fast"])
        self.assertEqual([result.content for result in results], ["slow.txt", "fast.txt"])

    def test_concurrent_failure_does_not_discard_other_results(self) -> None:
        barrier = Barrier(2)

        def read_file(path: str) -> ToolResult:
            barrier.wait(timeout=1)
            if path == "broken.txt":
                raise RuntimeError("boom")
            return _ok("read_file", path)

        registry = ToolRegistry(
            definitions=[ToolDefinition(name="read_file", handler=read_file)]
        )

        results = registry.dispatch(
            [
                ToolCall(id="broken", name="read_file", arguments={"path": "broken.txt"}),
                ToolCall(id="ok", name="read_file", arguments={"path": "ok.txt"}),
            ]
        )

        self.assertEqual([result.status for result in results], ["error", "success"])
        self.assertEqual(results[0].structured_content["error_type"], "RuntimeError")
        self.assertEqual(results[1].content, "ok.txt")

    def test_overlapping_paths_run_sequentially(self) -> None:
        active = 0
        max_active = 0
        lock = Lock()

        def read_file(path: str) -> ToolResult:
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            sleep(0.03)
            with lock:
                active -= 1
            return _ok("read_file", path)

        registry = ToolRegistry(
            definitions=[ToolDefinition(name="read_file", handler=read_file)]
        )

        registry.dispatch(
            [
                ToolCall(id="tc1", name="read_file", arguments={"path": "src"}),
                ToolCall(id="tc2", name="read_file", arguments={"path": "src/module.py"}),
            ]
        )

        self.assertEqual(max_active, 1)

    def test_unknown_side_effect_tools_run_sequentially(self) -> None:
        active = 0
        max_active = 0
        lock = Lock()

        def run(name: str) -> ToolResult:
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            sleep(0.03)
            with lock:
                active -= 1
            return _ok(name, name)

        registry = ToolRegistry(
            definitions=[
                ToolDefinition(name="first", handler=lambda: run("first")),
                ToolDefinition(name="second", handler=lambda: run("second")),
            ]
        )

        registry.dispatch(
            [
                ToolCall(id="tc1", name="first"),
                ToolCall(id="tc2", name="second"),
            ]
        )

        self.assertEqual(max_active, 1)

    def test_approval_required_batch_stays_sequential_and_defers_remaining_calls(self) -> None:
        class PendingApprovalProvider:
            def __init__(self) -> None:
                self.requests = 0

            def request_approval(self, request) -> ApprovalDecision:
                self.requests += 1
                return ApprovalDecision.deny(
                    "approval pending",
                    metadata={"interaction_pending": True},
                )

        provider = PendingApprovalProvider()
        registry = ToolRegistry(
            definitions=[
                ToolDefinition(
                    name="read_file",
                    handler=lambda path: _ok("read_file", path),
                )
            ],
            policy=SensitiveToolPolicy(
                approval_required_tools={"read_file": "approval required"}
            ),
            approval_provider=provider,
        )

        results = registry.dispatch(
            [
                ToolCall(id="tc1", name="read_file", arguments={"path": "a.txt"}),
                ToolCall(id="tc2", name="read_file", arguments={"path": "b.txt"}),
            ]
        )

        self.assertEqual(provider.requests, 1)
        self.assertTrue(results[0].structured_content["interaction_pending"])
        self.assertTrue(results[1].structured_content["interaction_deferred"])


if __name__ == "__main__":
    unittest.main()

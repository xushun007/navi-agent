import unittest

from navi_agent.runtime import AutoApproveApprovalProvider
from navi_agent.runtime import CliApprovalProvider
from navi_agent.runtime import DenyAllApprovalProvider
from navi_agent.runtime import HostYoloApprovalProvider
from navi_agent.runtime.tools.approval import ApprovalRequest


class DefaultApprovalProviderTests(unittest.TestCase):
    def test_deny_all_provider_denies_with_request_reason(self) -> None:
        provider = DenyAllApprovalProvider()

        decision = provider.request_approval(
            ApprovalRequest(
                tool_name="bash",
                arguments={"command": "pwd"},
                reason="bash requires approval",
            )
        )

        self.assertFalse(decision.approved)
        self.assertEqual(decision.reason, "bash requires approval")
        self.assertEqual(decision.metadata["tool_name"], "bash")

    def test_deny_all_provider_falls_back_to_tool_name_reason(self) -> None:
        provider = DenyAllApprovalProvider()

        decision = provider.request_approval(
            ApprovalRequest(tool_name="bash", arguments={}, reason="")
        )

        self.assertFalse(decision.approved)
        self.assertEqual(decision.reason, "Approval required for tool: bash")

    def test_auto_approve_provider_allows_every_tool(self) -> None:
        provider = AutoApproveApprovalProvider()

        decision = provider.request_approval(
            ApprovalRequest(
                tool_name="bash",
                arguments={"command": "pwd"},
                reason="bash requires approval",
            )
        )

        self.assertTrue(decision.approved)
        self.assertEqual(decision.reason, "bash requires approval")
        self.assertEqual(decision.metadata["arguments"], {"command": "pwd"})


class CliApprovalProviderTests(unittest.TestCase):
    def test_approves_yes_response(self) -> None:
        outputs: list[str] = []
        provider = CliApprovalProvider(
            input_fn=lambda prompt: "y",
            output_fn=outputs.append,
        )

        decision = provider.request_approval(
            ApprovalRequest(
                tool_name="bash",
                arguments={"command": "pwd"},
                reason="bash requires approval",
            )
        )

        self.assertTrue(decision.approved)
        self.assertIn("Tool approval required", outputs)

    def test_denies_default_response(self) -> None:
        outputs: list[str] = []
        provider = CliApprovalProvider(
            input_fn=lambda prompt: "",
            output_fn=outputs.append,
        )

        decision = provider.request_approval(
            ApprovalRequest(
                tool_name="bash",
                arguments={"command": "pwd"},
                reason="bash requires approval",
            )
        )

        self.assertFalse(decision.approved)
        self.assertIn("Approval denied", decision.reason)

    def test_host_yolo_approves_supported_host_tools(self) -> None:
        provider = HostYoloApprovalProvider()

        decision = provider.request_approval(
            ApprovalRequest(
                tool_name="code_executor",
                arguments={"task": "edit", "steps": []},
                reason="code_executor requires approval",
            )
        )

        self.assertTrue(decision.approved)
        self.assertTrue(decision.metadata["yolo"])
        self.assertEqual(decision.metadata["execution_isolation"], "host")
        self.assertIn("host approval", decision.reason)

    def test_host_yolo_denies_unsupported_tools(self) -> None:
        provider = HostYoloApprovalProvider()

        decision = provider.request_approval(
            ApprovalRequest(
                tool_name="deploy",
                arguments={},
                reason="deploy requires approval",
            )
        )

        self.assertFalse(decision.approved)
        self.assertTrue(decision.metadata["yolo"])
        self.assertEqual(decision.metadata["execution_isolation"], "host")


if __name__ == "__main__":
    unittest.main()

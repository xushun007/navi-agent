import unittest

from navi_agent.runtime import CliApprovalProvider
from navi_agent.runtime import HostYoloApprovalProvider
from navi_agent.runtime.tools.approval import ApprovalRequest


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

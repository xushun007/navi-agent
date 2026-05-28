import unittest

from navi_agent.runtime import CliApprovalProvider
from navi_agent.runtime.approval import ApprovalRequest


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


if __name__ == "__main__":
    unittest.main()

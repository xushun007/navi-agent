import unittest

from navi_agent.app import AppRequest, ApplicationService
from navi_agent.runtime import RuntimeResult


class FakeRuntime:
    def __init__(self) -> None:
        self.calls = []

    def run_conversation(self, session_id, user_id, user_message, system_prompt=None):
        self.calls.append(
            {
                "session_id": session_id,
                "user_id": user_id,
                "user_message": user_message,
                "system_prompt": system_prompt,
            }
        )
        return RuntimeResult(
            session_id=session_id,
            status="success",
            final_response="done",
        )


class ApplicationServiceTests(unittest.TestCase):
    def test_handle_uses_existing_session_id(self) -> None:
        runtime = FakeRuntime()
        service = ApplicationService(runtime=runtime)

        result = service.handle(
            AppRequest(
                session_id="s1",
                user_id="u1",
                message="hello",
            )
        )

        self.assertEqual(result.session_id, "s1")
        self.assertEqual(runtime.calls[0]["session_id"], "s1")

    def test_handle_generates_session_id_when_missing(self) -> None:
        runtime = FakeRuntime()
        service = ApplicationService(runtime=runtime)

        result = service.handle(AppRequest(user_id="u1", message="hello"))

        self.assertTrue(result.session_id)
        self.assertEqual(runtime.calls[0]["session_id"], result.session_id)

    def test_handle_uses_default_system_prompt(self) -> None:
        runtime = FakeRuntime()
        service = ApplicationService(
            runtime=runtime,
            default_system_prompt="system",
        )

        service.handle(AppRequest(user_id="u1", message="hello"))

        self.assertEqual(runtime.calls[0]["system_prompt"], "system")


if __name__ == "__main__":
    unittest.main()

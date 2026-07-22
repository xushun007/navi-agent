import json
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from navi_agent.gateway.weixin import ILinkClient, ILinkGateway
from navi_agent.gateway.weixin.ilink import ILinkMessage, ILinkSendResult
from navi_agent.gateway.weixin.pairing import WeixinPairingStore
from navi_agent.events import RuntimeEvent
from navi_agent.runtime import BackgroundTask, RuntimeResult, ToolResult


class FakeApp:
    def __init__(
        self,
        fail_for: set[str] | None = None,
        *,
        emit_progress: bool = False,
        emit_chunks: bool = False,
    ) -> None:
        self.calls = []
        self.fail_for = fail_for or set()
        self.emit_progress = emit_progress
        self.emit_chunks = emit_chunks
        self.background_task_listener = None

    def add_background_task_listener(self, listener) -> bool:
        self.background_task_listener = listener
        return True

    def handle(self, request, *, event_subscribers=None):
        self.calls.append(request)
        if request.user_id in self.fail_for:
            raise RuntimeError("runtime failed")
        if self.emit_progress:
            for subscriber in event_subscribers or []:
                subscriber.handle(
                    RuntimeEvent(
                        session_id=request.session_id,
                        user_id=request.user_id,
                        run_id="run-1",
                        sequence=1,
                        kind="action",
                        source="agent",
                        name="tool.call",
                        item_id="tc1",
                        metadata={
                            "tool_name": "read_file",
                            "arguments": {"path": "README.md"},
                        },
                    )
                )
                if self.emit_chunks:
                    for sequence, chunk in enumerate(
                        ["first line", "token=super-secret second line"],
                        start=2,
                    ):
                        subscriber.handle(
                            RuntimeEvent(
                                session_id=request.session_id,
                                user_id=request.user_id,
                                run_id="run-1",
                                sequence=sequence,
                                kind="delta",
                                source="tool",
                                name="tool.progress",
                                item_id="tc1",
                                metadata={
                                    "tool_name": "bash",
                                    "stream": "stdout",
                                    "chunk": chunk,
                                },
                            )
                        )
        return RuntimeResult(
            session_id=request.session_id,
            status="success",
            final_response="agent reply",
        )


class FakeClient:
    def __init__(self, send_success: bool = True) -> None:
        self.sent = []
        self.send_success = send_success

    def get_updates(self, sync_buf=""):
        return (
            "next-sync",
            [
                ILinkMessage(
                    message_id="m1",
                    from_user_id="user-1",
                    to_user_id="account-1",
                    chat_id="user-1",
                    chat_type="dm",
                    text="hello",
                    context_token="ctx-1",
                )
            ],
        )

    def send_text(self, *, to_user_id, text, context_token=None):
        self.sent.append(
            {
                "to_user_id": to_user_id,
                "text": text,
                "context_token": context_token,
            }
        )
        if self.send_success:
            return ILinkSendResult(success=True, response={"ret": 0})
        return ILinkSendResult(success=False, response={"ret": -1}, error="send failed")


class WeixinILinkTests(unittest.TestCase):
    def test_client_get_updates_parses_text_messages(self) -> None:
        with _ilink_server() as server:
            client = ILinkClient(
                token="token",
                account_id="account-1",
                base_url=server.base_url,
            )

            sync_buf, messages = client.get_updates("old-sync")

        self.assertEqual(sync_buf, "next-sync")
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].from_user_id, "user-1")
        self.assertEqual(messages[0].text, "hello")
        self.assertEqual(messages[0].context_token, "ctx-1")
        self.assertEqual(messages[0].session_id, "weixin:dm:user-1")
        self.assertEqual(server.requests[0]["path"], "/ilink/bot/getupdates")
        self.assertEqual(server.requests[0]["body"]["get_updates_buf"], "old-sync")

    def test_client_send_text_posts_context_token(self) -> None:
        with _ilink_server() as server:
            client = ILinkClient(
                token="token",
                account_id="account-1",
                base_url=server.base_url,
            )

            result = client.send_text(
                to_user_id="user-1",
                text="reply",
                context_token="ctx-1",
            )

        self.assertTrue(result.success)
        request_body = server.requests[0]["body"]
        self.assertEqual(server.requests[0]["path"], "/ilink/bot/sendmessage")
        self.assertEqual(request_body["msg"]["to_user_id"], "user-1")
        self.assertEqual(request_body["msg"]["context_token"], "ctx-1")
        self.assertEqual(request_body["msg"]["item_list"][0]["text_item"]["text"], "reply")

    def test_client_retries_retryable_http_status(self) -> None:
        with _retrying_ilink_server() as server:
            client = ILinkClient(
                token="token",
                account_id="account-1",
                base_url=server.base_url,
            )

            sync_buf, messages = client.get_updates("old-sync")

        self.assertEqual(sync_buf, "next-sync")
        self.assertEqual(messages, [])
        self.assertEqual(len(server.requests), 2)

    def test_client_marks_empty_send_text_as_fatal(self) -> None:
        client = ILinkClient(token="token", account_id="account-1", base_url="http://127.0.0.1")

        result = client.send_text(to_user_id="user-1", text="   ")

        self.assertFalse(result.success)
        self.assertEqual(result.error_category, "fatal")
        self.assertEqual(result.error_type, "ValueError")
        self.assertFalse(result.retryable)

    def test_gateway_tick_dispatches_to_app_and_sends_reply(self) -> None:
        app = FakeApp(emit_progress=True)
        client = FakeClient()
        gateway = ILinkGateway(
            app=app,
            client=client,
            account_id="account-1",
        )

        with patch("navi_agent.gateway.weixin.local.save_sync_buf") as save_sync_buf_mock:
            next_sync = gateway.tick("old-sync")

        self.assertEqual(next_sync, "next-sync")
        save_sync_buf_mock.assert_called_once_with("account-1", "next-sync")
        self.assertEqual(app.calls[0].user_id, "user-1")
        self.assertEqual(app.calls[0].session_id, "weixin:dm:user-1")
        self.assertEqual(app.calls[0].message, "hello")
        self.assertEqual(
            client.sent[1],
            {
                "to_user_id": "user-1",
                "text": "agent reply",
                "context_token": "ctx-1",
            },
        )
        self.assertEqual(client.sent[0]["text"], "正在读取 README.md")

    def test_gateway_sends_completed_background_task_to_origin_session(self) -> None:
        app = FakeApp()
        client = FakeClient()
        gateway = ILinkGateway(app=app, client=client, account_id="account-1")
        message = ILinkMessage(
            message_id="m0",
            from_user_id="user-1",
            to_user_id="account-1",
            chat_id="user-1",
            chat_type="dm",
            text="run tests",
            context_token="ctx-1",
        )
        gateway.handle_message(message)
        app.background_task_listener(
            BackgroundTask(
                task_id="task-1",
                session_id=message.session_id,
                user_id=message.user_id,
                description="uv run pytest",
                status="succeeded",
                result=ToolResult.ok(name="bash", content="475 passed"),
            )
        )

        self.assertEqual(len(client.sent), 2)
        self.assertEqual(client.sent[1]["to_user_id"], "user-1")
        self.assertEqual(client.sent[1]["context_token"], "ctx-1")
        self.assertIn("task-1", client.sent[1]["text"])
        self.assertIn("475 passed", client.sent[1]["text"])

    def test_gateway_streams_throttled_sanitized_tool_progress(self) -> None:
        app = FakeApp(emit_progress=True, emit_chunks=True)
        client = FakeClient()
        gateway = ILinkGateway(
            app=app,
            client=client,
            account_id="account-1",
            progress_interval_seconds=0,
        )
        message = ILinkMessage(
            message_id="m-progress",
            from_user_id="user-1",
            to_user_id="account-1",
            chat_id="user-1",
            chat_type="dm",
            text="run tests",
            context_token="ctx-1",
        )

        gateway.handle_message(message)

        texts = [item["text"] for item in client.sent]
        self.assertEqual(texts[0], "正在读取 README.md")
        self.assertIn("命令仍在执行\nfirst line", texts)
        self.assertTrue(any("token=<redacted> second line" in text for text in texts))
        self.assertFalse(any("super-secret" in text for text in texts))
        self.assertEqual(texts[-1], "agent reply")

    def test_gateway_suppresses_progress_inside_throttle_window(self) -> None:
        app = FakeApp(emit_progress=True, emit_chunks=True)
        client = FakeClient()
        gateway = ILinkGateway(
            app=app,
            client=client,
            account_id="account-1",
            progress_interval_seconds=3600,
        )
        message = ILinkMessage(
            message_id="m-throttle",
            from_user_id="user-1",
            to_user_id="account-1",
            chat_id="user-1",
            chat_type="dm",
            text="run tests",
            context_token="ctx-1",
        )

        gateway.handle_message(message)

        self.assertEqual(
            [item["text"] for item in client.sent],
            ["正在读取 README.md", "agent reply"],
        )

    def test_gateway_pairing_policy_sends_code_before_approval(self) -> None:
        app = FakeApp()
        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = WeixinPairingStore(Path(tmpdir) / "pairing.json")
            gateway = ILinkGateway(
                app=app,
                client=client,
                account_id="account-1",
                dm_policy="pairing",
                pairing_store=store,
            )

            gateway.handle_message(
                ILinkMessage(
                    message_id="m1",
                    from_user_id="user-1",
                    to_user_id="account-1",
                    chat_id="user-1",
                    chat_type="dm",
                    text="hello",
                    context_token="ctx-1",
                )
            )

            pending = store.list_pending()

        self.assertEqual(app.calls, [])
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].user_id, "user-1")
        self.assertEqual(client.sent[0]["to_user_id"], "user-1")
        self.assertIn(pending[0].code, client.sent[0]["text"])

    def test_gateway_pairing_policy_allows_approved_user(self) -> None:
        app = FakeApp()
        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = WeixinPairingStore(Path(tmpdir) / "pairing.json")
            code = store.request_code("user-1").code
            store.approve(code)
            gateway = ILinkGateway(
                app=app,
                client=client,
                account_id="account-1",
                dm_policy="pairing",
                pairing_store=store,
            )

            gateway.handle_message(
                ILinkMessage(
                    message_id="m1",
                    from_user_id="user-1",
                    to_user_id="account-1",
                    chat_id="user-1",
                    chat_type="dm",
                    text="hello",
                    context_token="ctx-1",
                )
            )

        self.assertEqual(app.calls[0].message, "hello")
        self.assertEqual(app.calls[0].source, "weixin")
        self.assertEqual(client.sent[0]["text"], "agent reply")

    def test_gateway_tick_continues_after_message_failure(self) -> None:
        app = FakeApp(fail_for={"user-1"})

        class TwoMessageClient(FakeClient):
            def get_updates(self, sync_buf=""):
                return (
                    "next-sync",
                    [
                        ILinkMessage(
                            message_id="m1",
                            from_user_id="user-1",
                            to_user_id="account-1",
                            chat_id="user-1",
                            chat_type="dm",
                            text="first",
                            context_token="ctx-1",
                        ),
                        ILinkMessage(
                            message_id="m2",
                            from_user_id="user-2",
                            to_user_id="account-1",
                            chat_id="user-2",
                            chat_type="dm",
                            text="second",
                            context_token="ctx-2",
                        ),
                    ],
                )

        client = TwoMessageClient()
        gateway = ILinkGateway(app=app, client=client, account_id="account-1")

        with patch("navi_agent.gateway.weixin.local.save_sync_buf"):
            with self.assertLogs("navi_agent.gateway.weixin.local", level="ERROR") as logs:
                gateway.tick("old-sync")

        self.assertEqual([call.user_id for call in app.calls], ["user-1", "user-2"])
        self.assertEqual(client.sent[0]["to_user_id"], "user-2")
        self.assertIn("Failed to process Weixin iLink message", "\n".join(logs.output))

    def test_gateway_logs_send_failure_without_raising(self) -> None:
        app = FakeApp()
        client = FakeClient(send_success=False)
        gateway = ILinkGateway(app=app, client=client, account_id="account-1")

        with self.assertLogs("navi_agent.gateway.weixin.local", level="WARNING") as logs:
            gateway.handle_message(
                ILinkMessage(
                    message_id="m1",
                    from_user_id="user-1",
                    to_user_id="account-1",
                    chat_id="user-1",
                    chat_type="dm",
                    text="hello",
                    context_token="ctx-1",
                )
            )

        self.assertEqual(app.calls[0].message, "hello")
        self.assertIn("Weixin reply send failed", "\n".join(logs.output))

    def test_gateway_skips_duplicate_message_id(self) -> None:
        app = FakeApp()

        class DuplicateClient(FakeClient):
            def get_updates(self, sync_buf=""):
                message = ILinkMessage(
                    message_id="m1",
                    from_user_id="user-1",
                    to_user_id="account-1",
                    chat_id="user-1",
                    chat_type="dm",
                    text="hello",
                    context_token="ctx-1",
                )
                return "next-sync", [message, message]

        client = DuplicateClient()
        gateway = ILinkGateway(app=app, client=client, account_id="account-1")

        with patch("navi_agent.gateway.weixin.local.save_sync_buf"):
            with self.assertLogs("navi_agent.gateway.weixin.local", level="INFO") as logs:
                gateway.tick("old-sync")

        self.assertEqual(len(app.calls), 1)
        self.assertEqual(len(client.sent), 1)
        self.assertIn("Skipped duplicate Weixin message", "\n".join(logs.output))

    def test_gateway_run_forever_backs_off_after_get_updates_error(self) -> None:
        app = FakeApp()

        class FlakyClient(FakeClient):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def get_updates(self, sync_buf=""):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("temporary get_updates failure")
                raise KeyboardInterrupt()

        client = FlakyClient()
        gateway = ILinkGateway(
            app=app,
            client=client,
            account_id="account-1",
            poll_interval_seconds=0.1,
            error_backoff_seconds=0.2,
        )

        with patch("navi_agent.gateway.weixin.local.load_sync_buf", return_value="old-sync"):
            with patch("navi_agent.gateway.weixin.local.sleep") as sleep_mock:
                with self.assertLogs("navi_agent.gateway.weixin.local", level="ERROR") as logs:
                    with self.assertRaises(KeyboardInterrupt):
                        gateway.run_forever()

        sleep_mock.assert_called_once_with(0.2)
        self.assertEqual(client.calls, 2)
        self.assertIn("Weixin iLink polling error; backing off", "\n".join(logs.output))


class _ilink_server:
    def __enter__(self):
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                content_length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(content_length).decode("utf-8"))
                outer.requests.append({"path": self.path, "body": body})
                if self.path.endswith("/getupdates"):
                    response = {
                        "ret": 0,
                        "get_updates_buf": "next-sync",
                        "msgs": [
                            {
                                "message_id": "m1",
                                "from_user_id": "user-1",
                                "to_user_id": "account-1",
                                "context_token": "ctx-1",
                                "item_list": [
                                    {
                                        "type": 1,
                                        "text_item": {"text": "hello"},
                                    }
                                ],
                            }
                        ],
                    }
                else:
                    response = {"ret": 0}
                data = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format, *args):
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class _retrying_ilink_server:
    def __enter__(self):
        self.requests = []
        self.count = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                content_length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(content_length).decode("utf-8"))
                outer.requests.append({"path": self.path, "body": body})
                outer.count += 1
                if outer.count == 1:
                    data = json.dumps({"ret": 0, "errmsg": "temporary"}).encode("utf-8")
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if self.path.endswith("/getupdates"):
                    response = {"ret": 0, "get_updates_buf": "next-sync", "msgs": []}
                else:
                    response = {"ret": 0}
                data = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format, *args):
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()

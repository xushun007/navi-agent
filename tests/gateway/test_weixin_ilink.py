import json
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from navi_agent.gateway.weixin import ILinkClient, ILinkGateway
from navi_agent.gateway.weixin.ilink import ILinkMessage
from navi_agent.gateway.weixin.pairing import WeixinPairingStore
from navi_agent.runtime import RuntimeResult


class FakeApp:
    def __init__(self) -> None:
        self.calls = []

    def handle(self, request):
        self.calls.append(request)
        return RuntimeResult(
            session_id=request.session_id,
            status="success",
            final_response="agent reply",
        )


class FakeClient:
    def __init__(self) -> None:
        self.sent = []

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

    def test_gateway_tick_dispatches_to_app_and_sends_reply(self) -> None:
        app = FakeApp()
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
            client.sent[0],
            {
                "to_user_id": "user-1",
                "text": "agent reply",
                "context_token": "ctx-1",
            },
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
        self.assertEqual(client.sent[0]["text"], "agent reply")


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


if __name__ == "__main__":
    unittest.main()

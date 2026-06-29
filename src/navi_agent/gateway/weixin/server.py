from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .handler import WeixinGateway


def build_weixin_request_handler(gateway: WeixinGateway):
    class WeixinRequestHandler(BaseHTTPRequestHandler):
        server_version = "NaviWeixinGateway/0.1"

        def do_GET(self) -> None:
            params = _query_params(self.path)
            echo = gateway.verify_echo(
                signature=params.get("signature", ""),
                timestamp=params.get("timestamp", ""),
                nonce=params.get("nonce", ""),
                echostr=params.get("echostr", ""),
            )
            if echo is None:
                self._write_text(HTTPStatus.FORBIDDEN, "invalid signature")
                return
            self._write_text(HTTPStatus.OK, echo)

        def do_POST(self) -> None:
            params = _query_params(self.path)
            content_length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(content_length)
            reply = gateway.handle_message(
                payload,
                signature=params.get("signature"),
                timestamp=params.get("timestamp"),
                nonce=params.get("nonce"),
            )
            if reply is None:
                self._write_text(HTTPStatus.FORBIDDEN, "invalid signature")
                return
            self._write_xml(HTTPStatus.OK, reply)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _write_text(self, status: HTTPStatus, body: str) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _write_xml(self, status: HTTPStatus, body: str) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return WeixinRequestHandler


def run_weixin_gateway_server(
    gateway: WeixinGateway,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
) -> None:
    handler_cls = build_weixin_request_handler(gateway)
    server = ThreadingHTTPServer((host, port), handler_cls)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _query_params(path: str) -> dict[str, str]:
    parsed = urlparse(path)
    values = parse_qs(parsed.query, keep_blank_values=True)
    return {key: items[0] if items else "" for key, items in values.items()}

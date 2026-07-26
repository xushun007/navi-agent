from __future__ import annotations

import socket
from email.message import Message
from unittest.mock import patch

from navi_agent.tools.web_client import (
    MAX_RESPONSE_BYTES,
    SafeRedirectHandler,
    WebClient,
    WebRequestError,
    validate_public_url,
)
from navi_agent.tools.web_fetch_tool import WebFetchTool


class _Response:
    def __init__(
        self,
        body: bytes,
        *,
        content_type: str = "text/html; charset=utf-8",
        url: str = "https://example.com/page",
    ) -> None:
        self._body = body
        self._url = url
        self.status = 200
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(body))

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._body[:size]

    def geturl(self) -> str:
        return self._url


class _Opener:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.request = None
        self.timeout = None

    def open(self, request, timeout: int):
        self.request = request
        self.timeout = timeout
        return self.response


def test_web_fetch_converts_html_to_markdown() -> None:
    opener = _Opener(
        _Response(
            b"""
            <html><head><title>Navi Docs</title><script>ignore()</script></head>
            <body><h1>Guide</h1><p>Use <a href="https://example.com/start">Navi</a>.</p>
            <ul><li>Fast</li><li>Safe</li></ul></body></html>
            """
        )
    )
    tool = WebFetchTool(
        WebClient(opener=opener, url_validator=lambda _url: None)
    )

    result = tool.invoke(url="https://example.com/page", format="markdown")

    assert result.status == "success"
    assert "# Guide" in result.content
    assert "Navi (https://example.com/start)" in result.content
    assert "ignore()" not in result.content
    assert result.structured_content["title"] == "Navi Docs"
    assert opener.timeout == 30


def test_web_fetch_rejects_binary_content() -> None:
    tool = WebFetchTool(
        WebClient(
            opener=_Opener(_Response(b"binary", content_type="image/png")),
            url_validator=lambda _url: None,
        )
    )

    result = tool.invoke(url="https://example.com/image.png")

    assert result.status == "error"
    assert result.metadata["error_category"] == "unsupported_content_type"


def test_web_fetch_rejects_oversized_content() -> None:
    response = _Response(b"x")
    response.headers.replace_header("Content-Length", str(MAX_RESPONSE_BYTES + 1))
    tool = WebFetchTool(
        WebClient(opener=_Opener(response), url_validator=lambda _url: None)
    )

    result = tool.invoke(url="https://example.com/large")

    assert result.status == "error"
    assert result.metadata["error_category"] == "response_too_large"


def test_validate_public_url_rejects_private_addresses() -> None:
    with patch(
        "navi_agent.tools.web_client.socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))],
    ):
        try:
            validate_public_url("http://example.com")
        except WebRequestError as exc:
            assert exc.category == "unsafe_url"
        else:
            raise AssertionError("private address should be rejected")


def test_redirect_handler_revalidates_target() -> None:
    def reject(_url: str) -> None:
        raise WebRequestError("blocked", category="unsafe_url")

    handler = SafeRedirectHandler(reject)

    try:
        handler.redirect_request(None, None, 302, "Found", {}, "http://127.0.0.1")
    except WebRequestError as exc:
        assert exc.category == "unsafe_url"
    else:
        raise AssertionError("redirect target should be validated")


def test_validate_public_url_rejects_non_http_redirects() -> None:
    try:
        validate_public_url("file:///etc/passwd")
    except WebRequestError as exc:
        assert exc.category == "invalid_url"
    else:
        raise AssertionError("non-HTTP redirect should be rejected")

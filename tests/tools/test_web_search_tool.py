from __future__ import annotations

import json
from email.message import Message

from navi_agent.tools.web_client import WebClient
from navi_agent.tools.web_search_tool import WebSearchTool


class _Response:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode()
        self.status = 200
        self.headers = Message()
        self.headers["Content-Type"] = "application/json; charset=utf-8"
        self.headers["Content-Length"] = str(len(self._body))

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._body[:size]

    def geturl(self) -> str:
        return "https://api.search.brave.com/res/v1/web/search"


class _Opener:
    def __init__(self, payload: dict) -> None:
        self.response = _Response(payload)
        self.request = None

    def open(self, request, timeout: int):
        self.request = request
        return self.response


def test_web_search_is_unavailable_without_api_key() -> None:
    tool = WebSearchTool(api_key=None)

    assert tool.is_available() is False
    assert tool.invoke(query="navi").metadata["error_category"] == "not_configured"


def test_web_search_returns_clean_structured_results() -> None:
    opener = _Opener(
        {
            "web": {
                "results": [
                    {
                        "title": "<strong>Navi</strong> Agent",
                        "url": "https://example.com/navi",
                        "description": "A &amp; B",
                    }
                ]
            }
        }
    )
    tool = WebSearchTool(
        api_key="secret",
        client=WebClient(opener=opener, url_validator=lambda _url: None),
    )

    result = tool.invoke(query="navi agent", limit=3)

    assert result.status == "success"
    assert result.structured_content["result_count"] == 1
    assert result.structured_content["results"][0] == {
        "title": "Navi Agent",
        "url": "https://example.com/navi",
        "description": "A & B",
    }
    assert "x-subscription-token" in {
        name.lower(): value for name, value in opener.request.header_items()
    }
    assert "q=navi+agent" in opener.request.full_url
    assert "count=3" in opener.request.full_url


def test_web_search_rejects_provider_query_limits() -> None:
    tool = WebSearchTool(api_key="secret")

    result = tool.invoke(query="word " * 51)

    assert result.status == "error"
    assert result.metadata["error_category"] == "invalid_arguments"

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


def test_web_search_uses_ddgs_without_api_key() -> None:
    class _Ddgs:
        def __init__(self, **kwargs) -> None:
            assert kwargs["timeout"] == 30

        def text(self, query: str, **kwargs):
            assert query == "navi"
            assert kwargs == {"max_results": 5, "safesearch": "moderate"}
            return [
                {
                    "title": "Navi Agent",
                    "href": "https://example.com/navi",
                    "body": "Personal agent",
                }
            ]

    tool = WebSearchTool(api_key=None, ddgs_factory=_Ddgs)

    result = tool.invoke(query="navi")

    assert tool.is_available() is True
    assert result.status == "success"
    assert result.structured_content["provider"] == "ddgs"
    assert result.structured_content["results"][0]["url"] == "https://example.com/navi"


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
    assert result.structured_content["provider"] == "brave"
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

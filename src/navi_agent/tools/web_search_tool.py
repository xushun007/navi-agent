from __future__ import annotations

import html
import json
import re
from typing import Any
from urllib.parse import urlencode

from navi_agent.tooling import ToolContext, ToolResult

from .base import BaseTool
from .web_client import WebClient, WebRequestError

_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_USER_AGENT = "Navi-Agent/0.1 (+https://github.com/xushun007/navi-agent)"


class WebSearchTool(BaseTool):
    def __init__(self, api_key: str | None, client: WebClient | None = None) -> None:
        self._api_key = (api_key or "").strip()
        self._client = client or WebClient()

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the public web for current information. Returns titles, URLs, and snippets; "
            "use web_fetch to read a selected result."
        )

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "maxLength": 400},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 5,
                },
            },
            "required": ["query"],
        }

    def is_available(self) -> bool:
        return bool(self._api_key)

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        if not self._api_key:
            return ToolResult.error(
                name=self.name,
                content="web search is not configured",
                metadata={"error_category": "not_configured"},
            )
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return ToolResult.error(
                name=self.name,
                content="query is required",
                metadata={"error_category": "invalid_arguments"},
            )
        if len(query) > 400 or len(query.split()) > 50:
            return ToolResult.error(
                name=self.name,
                content="query must be at most 400 characters and 50 words",
                metadata={"error_category": "invalid_arguments"},
            )
        limit = max(1, min(int(kwargs.get("limit", 5)), 10))
        url = f"{_SEARCH_ENDPOINT}?{urlencode({'q': query, 'count': limit})}"
        try:
            response = self._client.get(
                url,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "User-Agent": _USER_AGENT,
                    "X-Subscription-Token": self._api_key,
                },
            )
            payload = json.loads(response.body.decode(response.charset, errors="replace"))
        except WebRequestError as exc:
            return ToolResult.error(
                name=self.name,
                content=str(exc),
                metadata={
                    "error_category": exc.category,
                    "retryable": exc.retryable,
                },
            )
        except (UnicodeError, json.JSONDecodeError) as exc:
            return ToolResult.error(
                name=self.name,
                content=f"search provider returned an invalid response: {exc}",
                metadata={"error_category": "invalid_response"},
            )

        if not isinstance(payload, dict):
            return ToolResult.error(
                name=self.name,
                content="search provider returned an invalid response",
                metadata={"error_category": "invalid_response"},
            )
        web_payload = payload.get("web")
        raw_results = web_payload.get("results", []) if isinstance(web_payload, dict) else []
        if not isinstance(raw_results, list):
            raw_results = []
        results = [
            {
                "title": _clean_text(item.get("title")),
                "url": str(item.get("url") or "").strip(),
                "description": _clean_text(item.get("description")),
            }
            for item in raw_results[:limit]
            if isinstance(item, dict) and item.get("url")
        ]
        if not results:
            content = "No web results found."
        else:
            content = "\n\n".join(
                f"{index}. {item['title'] or item['url']}\n"
                f"   {item['url']}\n"
                f"   {item['description']}"
                for index, item in enumerate(results, start=1)
            )
        return ToolResult.ok(
            name=self.name,
            content=content,
            structured_content={
                "query": query,
                "results": results,
                "result_count": len(results),
            },
        )


def _clean_text(value: object) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()

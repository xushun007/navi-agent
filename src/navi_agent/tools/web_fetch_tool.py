from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any

from navi_agent.tooling import ToolContext, ToolResult

from .base import BaseTool
from .web_client import DEFAULT_TIMEOUT_SECONDS, WebClient, WebRequestError

_USER_AGENT = "Navi-Agent/0.1 (+https://github.com/xushun007/navi-agent)"
_TEXT_CONTENT_TYPES = {
    "application/json",
    "application/ld+json",
    "application/xhtml+xml",
    "application/xml",
}


class WebFetchTool(BaseTool):
    def __init__(self, client: WebClient | None = None) -> None:
        self._client = client or WebClient()

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return (
            "Fetch a public HTTP(S) page as readable text, markdown, or raw HTML. "
            "Use it for a known URL; use web_search to discover URLs."
        )

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "format": {
                    "type": "string",
                    "enum": ["text", "markdown", "html"],
                    "default": "markdown",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 120,
                },
            },
            "required": ["url"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        url = str(kwargs.get("url") or "").strip()
        output_format = str(kwargs.get("format") or "markdown").strip().lower()
        if output_format not in {"text", "markdown", "html"}:
            return ToolResult.error(
                name=self.name,
                content="format must be one of: text, markdown, html",
                metadata={"error_category": "invalid_arguments"},
            )
        accept = {
            "markdown": "text/markdown, text/html;q=0.9, text/plain;q=0.8",
            "text": "text/plain, text/html;q=0.9, application/json;q=0.8",
            "html": "text/html, application/xhtml+xml;q=0.9, text/plain;q=0.8",
        }[output_format]
        try:
            response = self._client.get(
                url,
                headers={
                    "Accept": accept,
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "identity",
                    "User-Agent": _USER_AGENT,
                },
                timeout_seconds=int(kwargs.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
            )
            if not _is_text_content(response.content_type):
                return ToolResult.error(
                    name=self.name,
                    content=f"unsupported content type: {response.content_type}",
                    metadata={"error_category": "unsupported_content_type"},
                )
            source = response.body.decode(response.charset, errors="replace")
            title = None
            if "html" in response.content_type:
                parser = _ReadableHtmlParser()
                parser.feed(source)
                title = parser.title
                if output_format == "text":
                    content = parser.text()
                elif output_format == "markdown":
                    content = parser.markdown()
                else:
                    content = source
            else:
                content = source
            return ToolResult.ok(
                name=self.name,
                content=content.strip(),
                structured_content={
                    "url": url,
                    "final_url": response.url,
                    "status": response.status,
                    "content_type": response.content_type,
                    "format": output_format,
                    "bytes": len(response.body),
                    "title": title,
                },
            )
        except WebRequestError as exc:
            return ToolResult.error(
                name=self.name,
                content=str(exc),
                metadata={
                    "url": url,
                    "error_category": exc.category,
                    "retryable": exc.retryable,
                },
            )


def _is_text_content(content_type: str) -> bool:
    return content_type.startswith("text/") or content_type in _TEXT_CONTENT_TYPES


class _ReadableHtmlParser(HTMLParser):
    _SKIP_TAGS = {"script", "style", "noscript", "iframe", "object", "embed", "svg"}
    _BLOCK_TAGS = {
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "footer",
        "header",
        "main",
        "nav",
        "p",
        "section",
        "table",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._title_depth = 0
        self._title_parts: list[str] = []
        self._link_href: str | None = None

    @property
    def title(self) -> str | None:
        value = _normalize_inline(" ".join(self._title_parts))
        return value or None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._title_depth += 1
        elif re.fullmatch(r"h[1-6]", tag):
            self._line_break()
            self._parts.append(f"{'#' * int(tag[1])} ")
        elif tag == "li":
            self._line_break()
            self._parts.append("- ")
        elif tag == "pre":
            self._line_break()
            self._parts.append("```\n")
        elif tag == "code":
            self._parts.append("`")
        elif tag in self._BLOCK_TAGS:
            self._line_break()
        elif tag == "a":
            self._link_href = dict(attrs).get("href")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._title_depth = max(0, self._title_depth - 1)
        elif tag == "pre":
            self._parts.append("\n```\n")
        elif tag == "code":
            self._parts.append("`")
        elif tag == "a":
            if self._link_href:
                self._parts.append(f" ({self._link_href})")
            self._link_href = None
        elif re.fullmatch(r"h[1-6]", tag) or tag in self._BLOCK_TAGS or tag == "li":
            self._line_break()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = html.unescape(data)
        if self._title_depth:
            self._title_parts.append(value)
            return
        normalized = _normalize_inline(value)
        if normalized:
            if self._parts and not self._parts[-1].endswith((" ", "\n", "`")):
                self._parts.append(" ")
            self._parts.append(normalized)

    def markdown(self) -> str:
        return _normalize_lines("".join(self._parts))

    def text(self) -> str:
        value = re.sub(r"^#{1,6}\s+", "", self.markdown(), flags=re.MULTILINE)
        value = re.sub(r"^- ", "", value, flags=re.MULTILINE)
        value = value.replace("```", "").replace("`", "")
        return value

    def _line_break(self) -> None:
        if self._parts and not self._parts[-1].endswith("\n"):
            self._parts.append("\n")


def _normalize_inline(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_lines(value: str) -> str:
    lines = [line.rstrip() for line in value.splitlines()]
    output: list[str] = []
    blank = False
    for line in lines:
        if not line:
            if output and not blank:
                output.append("")
            blank = True
            continue
        output.append(line)
        blank = False
    return "\n".join(output).strip()

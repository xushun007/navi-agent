from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import (
    HTTPRedirectHandler,
    OpenerDirector,
    Request,
    build_opener,
)

MAX_RESPONSE_BYTES = 5 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 120
_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


@dataclass(slots=True, frozen=True)
class WebResponse:
    url: str
    status: int
    content_type: str
    charset: str
    body: bytes


class UrlValidator(Protocol):
    def __call__(self, url: str) -> None: ...


class WebRequestError(RuntimeError):
    def __init__(self, message: str, *, category: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable


class SafeRedirectHandler(HTTPRedirectHandler):
    def __init__(self, validator: UrlValidator) -> None:
        super().__init__()
        self._validator = validator

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self._validator(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class WebClient:
    def __init__(
        self,
        *,
        opener: OpenerDirector | None = None,
        url_validator: UrlValidator | None = None,
    ) -> None:
        self._url_validator = url_validator or validate_public_url
        self._opener = opener or build_opener(SafeRedirectHandler(self._url_validator))

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        validate_url: bool = True,
    ) -> WebResponse:
        normalized_url = normalize_http_url(url)
        if validate_url:
            self._url_validator(normalized_url)
        timeout = max(1, min(int(timeout_seconds), MAX_TIMEOUT_SECONDS))
        request = Request(normalized_url, headers=headers, method="GET")
        try:
            with self._opener.open(request, timeout=timeout) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_RESPONSE_BYTES:
                    raise WebRequestError(
                        "response exceeds the 5 MB limit",
                        category="response_too_large",
                    )
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise WebRequestError(
                        "response exceeds the 5 MB limit",
                        category="response_too_large",
                    )
                content_type = response.headers.get_content_type()
                charset = response.headers.get_content_charset() or "utf-8"
                return WebResponse(
                    url=response.geturl(),
                    status=response.status,
                    content_type=content_type,
                    charset=charset,
                    body=body,
                )
        except WebRequestError:
            raise
        except HTTPError as exc:
            raise WebRequestError(
                f"request failed with HTTP {exc.code}",
                category="http_error",
                retryable=exc.code == 429 or exc.code >= 500,
            ) from exc
        except TimeoutError as exc:
            raise WebRequestError(
                "request timed out",
                category="timeout",
                retryable=True,
            ) from exc
        except URLError as exc:
            reason = exc.reason
            retryable = isinstance(reason, (TimeoutError, socket.timeout))
            raise WebRequestError(
                f"request failed: {reason}",
                category="timeout" if retryable else "network_error",
                retryable=retryable,
            ) from exc
        except (OSError, ValueError) as exc:
            raise WebRequestError(
                f"request failed: {exc}",
                category="network_error",
            ) from exc


def normalize_http_url(url: str) -> str:
    raw_url = str(url).strip()
    try:
        parsed = urlsplit(raw_url)
    except ValueError as exc:
        raise WebRequestError("invalid URL", category="invalid_url") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise WebRequestError(
            "URL must use http or https",
            category="invalid_url",
        )
    if not parsed.hostname:
        raise WebRequestError("URL must include a hostname", category="invalid_url")
    if parsed.username or parsed.password:
        raise WebRequestError(
            "URLs containing credentials are not allowed",
            category="invalid_url",
        )
    try:
        ascii_host = parsed.hostname.encode("idna").decode("ascii")
        port = parsed.port
    except (UnicodeError, ValueError) as exc:
        raise WebRequestError("invalid URL hostname or port", category="invalid_url") from exc
    netloc = f"[{ascii_host}]" if ":" in ascii_host else ascii_host
    if port is not None:
        netloc = f"{netloc}:{port}"
    path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = quote(parsed.query, safe="/%:@!$&'()*+,;=?-._~")
    return urlunsplit((parsed.scheme.lower(), netloc, path, query, ""))


def validate_public_url(url: str) -> None:
    parsed = urlsplit(url)
    hostname = parsed.hostname
    if not hostname:
        raise WebRequestError("URL must include a hostname", category="invalid_url")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except socket.gaierror as exc:
        raise WebRequestError(
            f"could not resolve hostname: {hostname}",
            category="dns_error",
            retryable=True,
        ) from exc
    if not addresses:
        raise WebRequestError(
            f"could not resolve hostname: {hostname}",
            category="dns_error",
            retryable=True,
        )
    for address in addresses:
        ip = ipaddress.ip_address(address)
        candidate = ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) else ip
        if (
            candidate.is_private
            or candidate.is_loopback
            or candidate.is_link_local
            or candidate.is_reserved
            or candidate.is_multicast
            or candidate.is_unspecified
            or candidate in _CGNAT_NETWORK
        ):
            raise WebRequestError(
                f"URL resolves to a non-public address: {address}",
                category="unsafe_url",
            )

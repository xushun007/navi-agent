from __future__ import annotations

from dataclasses import dataclass
from http.client import HTTPConnection, HTTPSConnection
import json
from time import time
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from navi_agent.paths import get_navi_home

ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
CHANNEL_VERSION = "2.2.0"
ILINK_APP_ID = "bot"
ILINK_APP_CLIENT_VERSION = (2 << 16) | (2 << 8) | 0

EP_GET_UPDATES = "ilink/bot/getupdates"
EP_SEND_MESSAGE = "ilink/bot/sendmessage"

ITEM_TEXT = 1
ITEM_VOICE = 3
MSG_TYPE_BOT = 2
MSG_STATE_FINISH = 2


@dataclass(frozen=True, slots=True)
class ILinkMessage:
    message_id: str | None
    from_user_id: str
    to_user_id: str
    chat_id: str
    chat_type: str
    text: str
    context_token: str | None = None
    raw: dict[str, Any] | None = None

    @property
    def user_id(self) -> str:
        return self.from_user_id

    @property
    def session_id(self) -> str:
        if self.chat_type == "group":
            return f"weixin:group:{self.chat_id}"
        return f"weixin:dm:{self.from_user_id}"


@dataclass(frozen=True, slots=True)
class ILinkSendResult:
    success: bool
    response: dict[str, Any]
    error: str | None = None


class ILinkClient:
    def __init__(
        self,
        *,
        token: str,
        account_id: str,
        base_url: str = ILINK_BASE_URL,
        timeout_seconds: float = 40.0,
    ) -> None:
        self._token = token
        self._account_id = account_id
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def get_updates(self, sync_buf: str = "") -> tuple[str, list[ILinkMessage]]:
        response = self._post(
            EP_GET_UPDATES,
            {"get_updates_buf": sync_buf},
            timeout_seconds=self._timeout_seconds,
        )
        next_sync_buf = str(response.get("get_updates_buf") or sync_buf or "")
        messages = [
            message
            for raw in response.get("msgs") or []
            if isinstance(raw, dict)
            for message in [_parse_message(raw, self._account_id)]
            if message is not None
        ]
        return next_sync_buf, messages

    def send_text(
        self,
        *,
        to_user_id: str,
        text: str,
        context_token: str | None = None,
    ) -> ILinkSendResult:
        if not text.strip():
            return ILinkSendResult(success=False, response={}, error="text is empty")
        message: dict[str, Any] = {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": uuid4().hex,
            "message_type": MSG_TYPE_BOT,
            "message_state": MSG_STATE_FINISH,
            "item_list": [{"type": ITEM_TEXT, "text_item": {"text": text}}],
        }
        if context_token:
            message["context_token"] = context_token
        response = self._post(
            EP_SEND_MESSAGE,
            {"msg": message},
            timeout_seconds=15.0,
        )
        ret = response.get("ret", 0)
        errcode = response.get("errcode", 0)
        success = ret in (0, None) and errcode in (0, None)
        return ILinkSendResult(
            success=success,
            response=response,
            error=None if success else str(response.get("errmsg") or response),
        )

    def _post(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        body = _json_dumps({**payload, "base_info": {"channel_version": CHANNEL_VERSION}})
        parsed = urlparse(self._base_url)
        if parsed.scheme == "http":
            connection_cls = HTTPConnection
        elif parsed.scheme == "https":
            connection_cls = HTTPSConnection
        else:
            raise ValueError(f"unsupported iLink base_url scheme: {parsed.scheme}")
        connection = connection_cls(
            parsed.hostname,
            parsed.port,
            timeout=timeout_seconds,
        )
        path_prefix = parsed.path.rstrip("/")
        path = f"{path_prefix}/{endpoint}" if path_prefix else f"/{endpoint}"
        try:
            connection.request(
                "POST",
                path,
                body=body.encode("utf-8"),
                headers=_headers(self._token, body),
            )
            response = connection.getresponse()
            raw = response.read().decode("utf-8")
        finally:
            connection.close()
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"iLink POST {endpoint} HTTP {response.status}: {raw[:200]}")
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}


def load_sync_buf(account_id: str) -> str:
    path = _sync_buf_path(account_id)
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    return str(data.get("get_updates_buf") or "")


def save_sync_buf(account_id: str, sync_buf: str) -> None:
    path = _sync_buf_path(account_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _json_dumps({"get_updates_buf": sync_buf}),
        encoding="utf-8",
    )


def _parse_message(raw: dict[str, Any], account_id: str) -> ILinkMessage | None:
    sender_id = str(raw.get("from_user_id") or "").strip()
    if not sender_id or sender_id == account_id:
        return None
    text = _extract_text(raw.get("item_list") or [])
    if not text:
        return None
    chat_type, chat_id = _guess_chat_type(raw, account_id)
    context_token = str(raw.get("context_token") or "").strip() or None
    return ILinkMessage(
        message_id=str(raw.get("message_id") or "").strip() or None,
        from_user_id=sender_id,
        to_user_id=str(raw.get("to_user_id") or "").strip(),
        chat_id=chat_id,
        chat_type=chat_type,
        text=text,
        context_token=context_token,
        raw=raw,
    )


def _extract_text(item_list: list[dict[str, Any]]) -> str:
    for item in item_list:
        if item.get("type") == ITEM_TEXT:
            return str((item.get("text_item") or {}).get("text") or "")
    for item in item_list:
        if item.get("type") == ITEM_VOICE:
            return str((item.get("voice_item") or {}).get("text") or "")
    return ""


def _guess_chat_type(message: dict[str, Any], account_id: str) -> tuple[str, str]:
    room_id = str(message.get("room_id") or message.get("chat_room_id") or "").strip()
    to_user_id = str(message.get("to_user_id") or "").strip()
    is_group = bool(room_id) or (
        bool(to_user_id) and bool(account_id) and to_user_id != account_id and message.get("msg_type") == 1
    )
    if is_group:
        return "group", room_id or to_user_id or str(message.get("from_user_id") or "")
    return "dm", str(message.get("from_user_id") or "")


def _headers(token: str, body: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "AuthorizationType": "ilink_bot_token",
        "Content-Length": str(len(body.encode("utf-8"))),
        "X-WECHAT-UIN": str(int(time() * 1000)),
        "iLink-App-Id": ILINK_APP_ID,
        "iLink-App-ClientVersion": str(ILINK_APP_CLIENT_VERSION),
    }


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _sync_buf_path(account_id: str):
    return get_navi_home() / "weixin" / "accounts" / f"{account_id}.sync.json"

from __future__ import annotations

from html import escape
from time import time
import xml.etree.ElementTree as ET

from .models import WeixinIncomingMessage, WeixinReply


class WeixinMessageParseError(ValueError):
    pass


def parse_weixin_message(payload: str | bytes) -> WeixinIncomingMessage:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise WeixinMessageParseError("invalid weixin xml payload") from exc

    return WeixinIncomingMessage(
        to_user_name=_required_text(root, "ToUserName"),
        from_user_name=_required_text(root, "FromUserName"),
        create_time=_required_int(root, "CreateTime"),
        msg_type=_required_text(root, "MsgType"),
        content=_optional_text(root, "Content"),
        msg_id=_optional_text(root, "MsgId") or None,
    )


def render_text_reply(reply: WeixinReply) -> str:
    create_time = reply.create_time or int(time())
    return (
        "<xml>"
        f"<ToUserName>{_cdata(reply.to_user_name)}</ToUserName>"
        f"<FromUserName>{_cdata(reply.from_user_name)}</FromUserName>"
        f"<CreateTime>{create_time}</CreateTime>"
        f"<MsgType>{_cdata(reply.msg_type)}</MsgType>"
        f"<Content>{_cdata(reply.content)}</Content>"
        "</xml>"
    )


def _required_text(root: ET.Element, name: str) -> str:
    value = _optional_text(root, name)
    if not value:
        raise WeixinMessageParseError(f"missing weixin field: {name}")
    return value


def _required_int(root: ET.Element, name: str) -> int:
    value = _required_text(root, name)
    try:
        return int(value)
    except ValueError as exc:
        raise WeixinMessageParseError(f"invalid integer weixin field: {name}") from exc


def _optional_text(root: ET.Element, name: str) -> str:
    node = root.find(name)
    if node is None or node.text is None:
        return ""
    return node.text


def _cdata(value: str) -> str:
    if "]]>" in value:
        return escape(value, quote=False)
    return f"<![CDATA[{value}]]>"

from __future__ import annotations

from dataclasses import dataclass

from navi_agent.app import AppRequest, ApplicationService

from .models import WeixinReply
from .signature import verify_weixin_signature
from .xml import parse_weixin_message, render_text_reply


@dataclass(slots=True)
class WeixinGateway:
    token: str
    app: ApplicationService

    def verify_echo(
        self,
        *,
        signature: str,
        timestamp: str,
        nonce: str,
        echostr: str,
    ) -> str | None:
        if not verify_weixin_signature(
            token=self.token,
            signature=signature,
            timestamp=timestamp,
            nonce=nonce,
        ):
            return None
        return echostr

    def handle_message(
        self,
        payload: str | bytes,
        *,
        signature: str | None = None,
        timestamp: str | None = None,
        nonce: str | None = None,
    ) -> str | None:
        if signature is not None or timestamp is not None or nonce is not None:
            if not signature or not timestamp or not nonce:
                return None
            if not verify_weixin_signature(
                token=self.token,
                signature=signature,
                timestamp=timestamp,
                nonce=nonce,
            ):
                return None

        incoming = parse_weixin_message(payload)
        if incoming.msg_type != "text":
            return render_text_reply(
                WeixinReply.from_incoming(incoming, "暂时只支持文本消息。")
            )

        result = self.app.handle(
            AppRequest(
                user_id=incoming.user_id,
                session_id=incoming.session_id,
                message=incoming.content,
            )
        )
        return render_text_reply(
            WeixinReply.from_incoming(incoming, result.final_response)
        )

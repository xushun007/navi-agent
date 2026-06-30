from __future__ import annotations

from dataclasses import dataclass
import logging
from time import sleep

from navi_agent.app import AppRequest, ApplicationService

from .ilink import ILinkClient, ILinkMessage, load_sync_buf, save_sync_buf
from .pairing import WeixinPairingStore

logger = logging.getLogger("navi_agent.gateway.weixin.local")


@dataclass(slots=True)
class ILinkGateway:
    app: ApplicationService
    client: ILinkClient
    account_id: str
    poll_interval_seconds: float = 1.0
    dm_policy: str = "open"
    allowed_users: set[str] | None = None
    pairing_store: WeixinPairingStore | None = None
    error_backoff_seconds: float = 5.0

    def run_forever(self) -> None:
        sync_buf = load_sync_buf(self.account_id)
        logger.info(
            "Starting Weixin iLink polling: account_id=%s sync_buf_present=%s dm_policy=%s",
            self.account_id,
            bool(sync_buf),
            self.dm_policy,
        )
        while True:
            try:
                sync_buf = self.tick(sync_buf)
                sleep(self.poll_interval_seconds)
            except KeyboardInterrupt:
                logger.info("Stopping Weixin iLink polling: account_id=%s", self.account_id)
                raise
            except Exception:
                logger.exception(
                    "Weixin iLink polling error; backing off: account_id=%s backoff_seconds=%s",
                    self.account_id,
                    self.error_backoff_seconds,
                )
                sleep(self.error_backoff_seconds)

    def tick(self, sync_buf: str = "") -> str:
        next_sync_buf, messages = self.client.get_updates(sync_buf)
        if next_sync_buf:
            save_sync_buf(self.account_id, next_sync_buf)
        if messages:
            logger.info("Processing Weixin iLink messages: count=%s", len(messages))
        for message in messages:
            try:
                self.handle_message(message)
            except Exception:
                logger.exception(
                    "Failed to process Weixin iLink message: message_id=%s user_id=%s",
                    message.message_id,
                    message.user_id,
                )
        return next_sync_buf

    def handle_message(self, message: ILinkMessage) -> None:
        logger.info(
            "Received Weixin text message: message_id=%s user_id=%s chat_type=%s text_length=%s",
            message.message_id,
            message.user_id,
            message.chat_type,
            len(message.text),
        )
        if not self._is_allowed(message):
            return
        result = self.app.handle(
            AppRequest(
                user_id=message.user_id,
                session_id=message.session_id,
                message=message.text,
            )
        )
        send_result = self.client.send_text(
            to_user_id=message.from_user_id,
            text=result.final_response,
            context_token=message.context_token,
        )
        if not send_result.success:
            logger.warning(
                "Weixin reply send failed: message_id=%s user_id=%s error=%s",
                message.message_id,
                message.user_id,
                send_result.error,
            )
        else:
            logger.info(
                "Weixin reply sent: message_id=%s user_id=%s response_length=%s",
                message.message_id,
                message.user_id,
                len(result.final_response),
            )

    def _is_allowed(self, message: ILinkMessage) -> bool:
        if message.chat_type != "dm":
            return True
        policy = self.dm_policy.lower()
        if policy == "open":
            return True
        if policy == "disabled":
            logger.info("Rejected Weixin DM because policy is disabled: user_id=%s", message.user_id)
            return False
        if policy == "allowlist":
            allowed = message.user_id in (self.allowed_users or set())
            if not allowed:
                logger.info("Rejected Weixin DM outside allowlist: user_id=%s", message.user_id)
            return allowed
        if policy == "pairing":
            store = self.pairing_store or WeixinPairingStore()
            if store.is_approved(message.user_id):
                return True
            request = store.request_code(message.user_id)
            self.client.send_text(
                to_user_id=message.from_user_id,
                text=(
                    "Pairing required. "
                    f"Approve this user with: navi-agent --approve-weixin-pairing {request.code}"
                ),
                context_token=message.context_token,
            )
            logger.info(
                "Requested Weixin pairing approval: user_id=%s code=%s",
                message.user_id,
                request.code,
            )
            return False
        logger.warning("Rejected Weixin DM because policy is unknown: policy=%s user_id=%s", policy, message.user_id)
        return False

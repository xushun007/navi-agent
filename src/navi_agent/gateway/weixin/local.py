from __future__ import annotations

from dataclasses import dataclass
from time import sleep

from navi_agent.app import AppRequest, ApplicationService

from .ilink import ILinkClient, ILinkMessage, load_sync_buf, save_sync_buf
from .pairing import WeixinPairingStore


@dataclass(slots=True)
class ILinkGateway:
    app: ApplicationService
    client: ILinkClient
    account_id: str
    poll_interval_seconds: float = 1.0
    dm_policy: str = "open"
    allowed_users: set[str] | None = None
    pairing_store: WeixinPairingStore | None = None

    def run_forever(self) -> None:
        sync_buf = load_sync_buf(self.account_id)
        while True:
            sync_buf = self.tick(sync_buf)
            sleep(self.poll_interval_seconds)

    def tick(self, sync_buf: str = "") -> str:
        next_sync_buf, messages = self.client.get_updates(sync_buf)
        if next_sync_buf:
            save_sync_buf(self.account_id, next_sync_buf)
        for message in messages:
            self.handle_message(message)
        return next_sync_buf

    def handle_message(self, message: ILinkMessage) -> None:
        if not self._is_allowed(message):
            return
        result = self.app.handle(
            AppRequest(
                user_id=message.user_id,
                session_id=message.session_id,
                message=message.text,
            )
        )
        self.client.send_text(
            to_user_id=message.from_user_id,
            text=result.final_response,
            context_token=message.context_token,
        )

    def _is_allowed(self, message: ILinkMessage) -> bool:
        if message.chat_type != "dm":
            return True
        policy = self.dm_policy.lower()
        if policy == "open":
            return True
        if policy == "disabled":
            return False
        if policy == "allowlist":
            return message.user_id in (self.allowed_users or set())
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
            return False
        return False

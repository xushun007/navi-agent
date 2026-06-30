from __future__ import annotations

from dataclasses import dataclass
from time import sleep

from navi_agent.app import AppRequest, ApplicationService

from .ilink import ILinkClient, ILinkMessage, load_sync_buf, save_sync_buf


@dataclass(slots=True)
class ILinkGateway:
    app: ApplicationService
    client: ILinkClient
    account_id: str
    poll_interval_seconds: float = 1.0

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

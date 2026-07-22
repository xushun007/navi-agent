from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import logging
from threading import Event, Lock
from time import monotonic, sleep

from navi_agent.app import AppRequest, ApplicationService
from navi_agent.runtime import BackgroundTask, SessionTaskScheduler
from navi_agent.ui_events import UiEvent, UiEventEmitter

from .ilink import ILinkClient, ILinkMessage, load_sync_buf, save_sync_buf
from .pairing import WeixinPairingStore

logger = logging.getLogger("navi_agent.gateway.weixin.local")


class _WeixinUiEventSink:
    def __init__(
        self,
        *,
        client: ILinkClient,
        to_user_id: str,
        context_token: str | None,
        progress_interval_seconds: float,
    ) -> None:
        self._client = client
        self._to_user_id = to_user_id
        self._context_token = context_token
        self._progress_interval_seconds = progress_interval_seconds
        self._seen_event_ids: set[str] = set()
        self._last_progress_at: dict[str, float] = {}
        self._pending_progress: dict[str, list[str]] = {}
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="weixin-progress")

    def handle(self, event: UiEvent) -> None:
        with self._lock:
            if event.event_id in self._seen_event_ids:
                return
            self._seen_event_ids.add(event.event_id)
            item_key = event.item_id or event.run_id
            if event.state == "started":
                self._last_progress_at[item_key] = monotonic()
                self._submit(event.event_id, event.title)
                return
            if event.state == "progress":
                if event.detail:
                    pending = self._pending_progress.setdefault(item_key, [])
                    pending.append(event.detail)
                    self._pending_progress[item_key] = pending[-8:]
                last_sent = self._last_progress_at.get(item_key, 0.0)
                if monotonic() - last_sent < self._progress_interval_seconds:
                    return
                detail = "\n".join(self._pending_progress.pop(item_key, []))
                self._last_progress_at[item_key] = monotonic()
                self._submit(event.event_id, f"{event.title}\n{detail}".strip())
                return
            self._pending_progress.pop(item_key, None)
            self._last_progress_at.pop(item_key, None)
            if event.state == "completed" or event.kind == "error":
                return
            text = event.title if not event.detail else f"{event.title}\n{event.detail}"
            self._submit(event.event_id, text)

    def close(self) -> None:
        self._executor.shutdown(wait=True)

    def _submit(self, event_id: str, text: str) -> None:
        self._executor.submit(self._send, event_id, text)

    def _send(self, event_id: str, text: str) -> None:
        try:
            send_result = self._client.send_text(
                to_user_id=self._to_user_id,
                text=text,
                context_token=self._context_token,
            )
        except Exception:
            logger.exception("Weixin progress send raised: event_id=%s", event_id)
            return
        if not send_result.success:
            logger.warning(
                "Weixin progress send failed: event_id=%s error=%s",
                event_id,
                send_result.error,
            )


@dataclass(slots=True)
class _BackgroundRoute:
    user_id: str
    to_user_id: str
    context_token: str | None
    reply_sent: Event = field(default_factory=Event)


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
    progress_interval_seconds: float = 3.0
    max_concurrent_requests: int = 4
    seen_message_ids: set[str] = field(default_factory=set)
    _background_routes: dict[str, _BackgroundRoute] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _background_routes_lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _request_scheduler: SessionTaskScheduler = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._request_scheduler = SessionTaskScheduler(max_workers=self.max_concurrent_requests)
        register_listener = getattr(self.app, "add_background_task_listener", None)
        if callable(register_listener):
            register_listener(self._send_background_notification)

    def run_forever(self) -> None:
        sync_buf = load_sync_buf(self.account_id)
        logger.info(
            "Starting Weixin iLink polling: account_id=%s sync_buf_present=%s dm_policy=%s",
            self.account_id,
            bool(sync_buf),
            self.dm_policy,
        )
        try:
            while True:
                try:
                    sync_buf = self.tick(sync_buf)
                    sleep(self.poll_interval_seconds)
                except Exception:
                    logger.exception(
                        "Weixin iLink polling error; backing off: account_id=%s backoff_seconds=%s",
                        self.account_id,
                        self.error_backoff_seconds,
                    )
                    sleep(self.error_backoff_seconds)
        except KeyboardInterrupt:
            logger.info("Stopping Weixin iLink polling: account_id=%s", self.account_id)
            raise
        finally:
            self.close()

    def tick(self, sync_buf: str = "") -> str:
        next_sync_buf, messages = self.client.get_updates(sync_buf)
        if next_sync_buf:
            save_sync_buf(self.account_id, next_sync_buf)
        if messages:
            logger.info("Processing Weixin iLink messages: count=%s", len(messages))
        for message in messages:
            self.submit_message(message)
        return next_sync_buf

    def submit_message(self, message: ILinkMessage) -> None:
        if not self._accept_message(message):
            return
        self._request_scheduler.submit(
            message.session_id,
            lambda: self._handle_accepted_message_safely(message),
        )

    def handle_message(self, message: ILinkMessage) -> None:
        if not self._accept_message(message):
            return
        self._handle_accepted_message(message)

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        return self._request_scheduler.wait_for_idle(timeout)

    def close(self, *, wait: bool = True) -> None:
        self._request_scheduler.close(wait=wait)

    def _accept_message(self, message: ILinkMessage) -> bool:
        if message.message_id and message.message_id in self.seen_message_ids:
            logger.info(
                "Skipped duplicate Weixin message: message_id=%s user_id=%s",
                message.message_id,
                message.user_id,
            )
            return False
        if message.message_id:
            self.seen_message_ids.add(message.message_id)
        logger.info(
            "Received Weixin text message: message_id=%s user_id=%s chat_type=%s text_length=%s",
            message.message_id,
            message.user_id,
            message.chat_type,
            len(message.text),
        )
        if not self._is_allowed(message):
            return False
        return True

    def _handle_accepted_message_safely(self, message: ILinkMessage) -> None:
        try:
            self._handle_accepted_message(message)
        except Exception:
            logger.exception(
                "Failed to process Weixin iLink message: message_id=%s user_id=%s",
                message.message_id,
                message.user_id,
            )

    def _handle_accepted_message(self, message: ILinkMessage) -> None:
        route = self._remember_background_route(message)
        try:
            ui_sink = _WeixinUiEventSink(
                client=self.client,
                to_user_id=message.from_user_id,
                context_token=message.context_token,
                progress_interval_seconds=self.progress_interval_seconds,
            )
            try:
                result = self.app.handle(
                    AppRequest(
                        user_id=message.user_id,
                        session_id=message.session_id,
                        message=message.text,
                        source="weixin",
                    ),
                    event_subscribers=[UiEventEmitter(ui_sink)],
                )
            finally:
                ui_sink.close()
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
        finally:
            route.reply_sent.set()

    def _remember_background_route(self, message: ILinkMessage) -> _BackgroundRoute:
        route = _BackgroundRoute(
            user_id=message.user_id,
            to_user_id=message.from_user_id,
            context_token=message.context_token,
        )
        with self._background_routes_lock:
            self._background_routes[message.session_id] = route
        return route

    def _send_background_notification(self, task: BackgroundTask) -> None:
        with self._background_routes_lock:
            route = self._background_routes.get(task.session_id)
        if route is None or route.user_id != task.user_id:
            logger.warning(
                "Skipped background task notification without route: task_id=%s session_id=%s",
                task.task_id,
                task.session_id,
            )
            return
        route.reply_sent.wait()
        send_result = self.client.send_text(
            to_user_id=route.to_user_id,
            text=self._render_background_notification(task),
            context_token=route.context_token,
        )
        if not send_result.success:
            logger.warning(
                "Weixin background task notification failed: task_id=%s user_id=%s error=%s",
                task.task_id,
                task.user_id,
                send_result.error,
            )

    @staticmethod
    def _render_background_notification(task: BackgroundTask) -> str:
        lines = [
            "[Background task completed]",
            f"task_id: {task.task_id}",
            f"status: {task.status}",
            f"description: {task.description}",
        ]
        if task.result is not None:
            lines.extend(["result:", task.result.content])
        return "\n".join(lines)

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
                    f"Approve this user with: navi-agent --approve-gateway-pairing {request.code}"
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

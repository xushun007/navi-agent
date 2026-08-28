from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
import logging
from threading import Event, Lock
from time import monotonic, sleep

from navi_agent.app import AppRequest, ApplicationService
from navi_agent.runtime import BackgroundTask, SessionTaskScheduler
from navi_agent.ui_events import UiEvent, UiEventEmitter

from .delivery import WeixinDeliveryStore
from .ilink import ILinkClient, ILinkMessage, load_sync_buf, save_sync_buf
from .pairing import WeixinPairingStore
from .routes import WeixinRoute, WeixinRouteStore

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
            if event.kind == "assistant":
                return
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
            if event.state in {"completed", "cancelled", "waiting"} or event.kind == "error":
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
    route_store: WeixinRouteStore | None = None
    delivery_store: WeixinDeliveryStore | None = None
    error_backoff_seconds: float = 5.0
    progress_interval_seconds: float = 3.0
    max_concurrent_requests: int = 4
    max_delivery_attempts: int = 5
    shutdown_drain_seconds: float = 15.0
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
            self.recover_pending()
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
        self._drain_outbox()
        next_sync_buf, messages = self.client.get_updates(sync_buf)
        if messages:
            logger.info("Processing Weixin iLink messages: count=%s", len(messages))
        for message in messages:
            self.submit_message(message)
        if next_sync_buf:
            save_sync_buf(self.account_id, next_sync_buf)
        self._drain_outbox()
        return next_sync_buf

    def submit_message(self, message: ILinkMessage) -> None:
        if not self._accept_message(message):
            return
        self._dispatch_message(message)

    def _dispatch_message(self, message: ILinkMessage) -> None:
        command, separator, argument = message.text.strip().partition(" ")
        if command == "/stop":
            cancelled = self.app.cancel_session(message.session_id, reason="user_stop")
            pending = None
            if not cancelled:
                pending = self.app.resolve_interaction(message.session_id, approved=False)
            self._deliver_text(
                delivery_key=f"control:{message.message_id or message.session_id}:stop",
                kind="control",
                source_id=message.message_id,
                to_user_id=message.from_user_id,
                text=(
                    "已请求停止当前任务。"
                    if cancelled
                    else "已取消等待中的请求。"
                    if pending is not None
                    else "当前没有正在执行的任务。"
                ),
                context_token=message.context_token,
            )
            self._complete_inbound(message)
            return
        if command in {"/approve", "/deny"}:
            approved = command == "/approve"
            interaction = self.app.resolve_interaction(message.session_id, approved=approved)
            if interaction is None or interaction.kind != "approval":
                self._deliver_text(
                    delivery_key=f"control:{message.message_id or message.session_id}:approval",
                    kind="control",
                    source_id=message.message_id,
                    to_user_id=message.from_user_id,
                    text="当前没有等待处理的授权请求。",
                    context_token=message.context_token,
                )
                self._complete_inbound(message)
                return
            action = "已批准" if approved else "已拒绝"
            instruction = f"用户{action}工具 {interaction.tool_name} 的授权请求。"
            message = replace(message, text=instruction)
        explicit_steer = command == "/steer" and separator and argument.strip()
        if explicit_steer:
            message = replace(message, text=argument.strip())
        active = self.app.is_session_active(message.session_id)
        if active:
            self.app.cancel_session(message.session_id, reason="user_steer")
        future = self._request_scheduler.submit(
            message.session_id,
            lambda: self._handle_accepted_message_safely(message),
            replace_pending=active,
        )
        if message.message_id and self.delivery_store is not None:
            future.add_done_callback(
                lambda completed, message_id=message.message_id: (
                    self.delivery_store.mark_inbound_superseded(message_id)
                    if completed.cancelled()
                    else None
                )
            )

    def handle_message(self, message: ILinkMessage) -> None:
        if not self._accept_message(message):
            return
        self._handle_accepted_message_safely(message)

    def recover_pending(self) -> None:
        if self.delivery_store is None:
            return
        recovered_outbound = self.delivery_store.recover_outbound()
        recovered_inbound = self.delivery_store.recover_inbound()
        if recovered_outbound or recovered_inbound:
            logger.info(
                "Recovering durable Weixin work: inbound=%s outbound=%s",
                len(recovered_inbound),
                recovered_outbound,
            )
        for record in recovered_inbound:
            message = record.to_message()
            if message.context_token and self.route_store is not None:
                self.route_store.remember(
                    WeixinRoute(
                        user_id=message.from_user_id,
                        context_token=message.context_token,
                    )
                )
            self._dispatch_message(message)
        self._drain_outbox()

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        return self._request_scheduler.wait_for_idle(timeout)

    def close(self, *, wait: bool = True) -> None:
        drained = self._request_scheduler.close(
            wait=wait,
            timeout=self.shutdown_drain_seconds if wait else None,
        )
        if wait and not drained:
            logger.warning(
                "Weixin shutdown drain timed out: timeout_seconds=%s",
                self.shutdown_drain_seconds,
            )
        close_app = getattr(self.app, "close", None)
        if callable(close_app):
            close_app()

    def _accept_message(self, message: ILinkMessage) -> bool:
        if message.message_id and message.message_id in self.seen_message_ids:
            logger.info(
                "Skipped duplicate Weixin message: message_id=%s user_id=%s",
                message.message_id,
                message.user_id,
            )
            return False
        logger.info(
            "Received Weixin text message: message_id=%s user_id=%s chat_type=%s text_length=%s",
            message.message_id,
            message.user_id,
            message.chat_type,
            len(message.text),
        )
        if not self._is_allowed(message):
            return False
        if self.delivery_store is not None and not self.delivery_store.record_inbound(message):
            logger.info(
                "Skipped durable duplicate Weixin message: message_id=%s user_id=%s",
                message.message_id,
                message.user_id,
            )
            return False
        if message.message_id:
            self.seen_message_ids.add(message.message_id)
        if message.context_token and self.route_store is not None:
            self.route_store.remember(
                WeixinRoute(
                    user_id=message.from_user_id,
                    context_token=message.context_token,
                )
            )
        return True

    def _handle_accepted_message_safely(self, message: ILinkMessage) -> None:
        if not self._start_inbound(message):
            return
        try:
            self._handle_accepted_message(message)
            self._complete_inbound(message)
        except Exception as exc:
            if message.message_id and self.delivery_store is not None:
                self.delivery_store.mark_inbound_failed(
                    message.message_id,
                    error=f"{exc.__class__.__name__}: {exc}",
                )
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
            self._deliver_text(
                delivery_key=f"reply:{message.message_id or message.session_id}",
                kind="reply",
                source_id=message.message_id,
                to_user_id=message.from_user_id,
                text=result.final_response,
                context_token=message.context_token,
            )
            logger.info(
                "Weixin reply persisted: message_id=%s user_id=%s response_length=%s",
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
        if route is None and self.route_store is not None:
            stored_route = self.route_store.get(task.user_id)
            if stored_route is not None:
                route = _BackgroundRoute(
                    user_id=task.user_id,
                    to_user_id=stored_route.user_id,
                    context_token=stored_route.context_token,
                )
                route.reply_sent.set()
        if route is None or route.user_id != task.user_id:
            logger.warning(
                "Skipped background task notification without route: task_id=%s session_id=%s",
                task.task_id,
                task.session_id,
            )
            raise RuntimeError(
                f"Weixin route unavailable for background task {task.task_id}"
            )
        route.reply_sent.wait()
        self._deliver_text(
            delivery_key=f"background:{task.task_id}",
            kind="background",
            source_id=task.task_id,
            to_user_id=route.to_user_id,
            text=self._render_background_notification(task),
            context_token=route.context_token,
        )

    def _start_inbound(self, message: ILinkMessage) -> bool:
        if not message.message_id or self.delivery_store is None:
            return True
        return self.delivery_store.mark_inbound_running(message.message_id)

    def _complete_inbound(self, message: ILinkMessage) -> None:
        if not message.message_id or self.delivery_store is None:
            return
        record = self.delivery_store.get_inbound(message.message_id)
        if record is not None and record.status == "received":
            self.delivery_store.mark_inbound_running(message.message_id)
        self.delivery_store.mark_inbound_completed(message.message_id)

    def _deliver_text(
        self,
        *,
        delivery_key: str,
        kind: str,
        source_id: str | None,
        to_user_id: str,
        text: str,
        context_token: str | None,
    ) -> None:
        if self.delivery_store is None:
            send_result = self.client.send_text(
                to_user_id=to_user_id,
                text=text,
                context_token=context_token,
            )
            if not send_result.success:
                logger.warning(
                    "Weixin %s send failed: source_id=%s error=%s",
                    kind,
                    source_id,
                    send_result.error,
                )
            return
        self.delivery_store.enqueue_outbound(
            delivery_key=delivery_key,
            kind=kind,
            source_id=source_id,
            to_user_id=to_user_id,
            text=text,
            context_token=context_token,
        )
        self._drain_outbox()

    def _drain_outbox(self) -> None:
        if self.delivery_store is None:
            return
        for outbound in self.delivery_store.claim_due_outbound():
            try:
                send_result = self.client.send_text(
                    to_user_id=outbound.to_user_id,
                    text=outbound.text,
                    context_token=outbound.context_token,
                )
            except Exception as exc:
                self.delivery_store.mark_outbound_failed(
                    outbound.id,
                    error=f"{exc.__class__.__name__}: {exc}",
                    retryable=True,
                    max_attempts=self.max_delivery_attempts,
                    retry_delay_seconds=_delivery_retry_delay(outbound.attempt_count),
                )
                logger.exception(
                    "Weixin durable send raised: outbox_id=%s kind=%s",
                    outbound.id,
                    outbound.kind,
                )
                continue
            if send_result.success:
                self.delivery_store.mark_outbound_delivered(outbound.id)
                continue
            failed = self.delivery_store.mark_outbound_failed(
                outbound.id,
                error=send_result.error or "unknown Weixin send failure",
                retryable=send_result.retryable is not False,
                max_attempts=self.max_delivery_attempts,
                retry_delay_seconds=_delivery_retry_delay(outbound.attempt_count),
            )
            logger.warning(
                "Weixin durable send failed: outbox_id=%s kind=%s status=%s error=%s",
                outbound.id,
                outbound.kind,
                failed.status if failed is not None else "unknown",
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
                "Requested Weixin pairing approval: user_id=%s",
                message.user_id,
            )
            return False
        logger.warning("Rejected Weixin DM because policy is unknown: policy=%s user_id=%s", policy, message.user_id)
        return False


def _delivery_retry_delay(attempt_count: int) -> float:
    return min(60.0, float(2 ** max(0, attempt_count - 1)))

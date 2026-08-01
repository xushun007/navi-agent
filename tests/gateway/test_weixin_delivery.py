from pathlib import Path

from navi_agent.gateway.weixin import ILinkMessage, WeixinDeliveryStore


def _message(message_id: str = "message-1") -> ILinkMessage:
    return ILinkMessage(
        message_id=message_id,
        from_user_id="user-1",
        to_user_id="account-1",
        chat_id="user-1",
        chat_type="dm",
        text="hello",
        context_token="context-1",
    )


def test_inbox_deduplicates_across_store_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    first = WeixinDeliveryStore(db_path, account_id="account-1")

    assert first.record_inbound(_message(), now=10.0) is True
    assert first.record_inbound(_message(), now=11.0) is False

    restarted = WeixinDeliveryStore(db_path, account_id="account-1")
    assert restarted.record_inbound(_message(), now=12.0) is False
    record = restarted.get_inbound("message-1")
    assert record is not None
    assert record.status == "received"
    assert record.to_message() == _message()


def test_inbox_recovers_interrupted_running_message(tmp_path: Path) -> None:
    store = WeixinDeliveryStore(tmp_path / "state.db", account_id="account-1")
    store.record_inbound(_message(), now=10.0)
    assert store.mark_inbound_running("message-1", now=11.0) is True

    recovered = store.recover_inbound(now=12.0)

    assert [record.message_id for record in recovered] == ["message-1"]
    assert recovered[0].status == "received"
    assert store.mark_inbound_running("message-1", now=13.0) is True
    assert store.mark_inbound_completed("message-1", now=14.0) is True
    assert store.recover_inbound(now=15.0) == []


def test_outbox_enqueue_is_idempotent_and_persistent(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    store = WeixinDeliveryStore(db_path, account_id="account-1")
    first = store.enqueue_outbound(
        delivery_key="reply:message-1",
        kind="reply",
        source_id="message-1",
        to_user_id="user-1",
        text="agent reply",
        context_token="context-1",
        now=10.0,
    )
    duplicate = store.enqueue_outbound(
        delivery_key="reply:message-1",
        kind="reply",
        source_id="message-1",
        to_user_id="user-1",
        text="different text is ignored",
        context_token="context-1",
        now=11.0,
    )

    restarted = WeixinDeliveryStore(db_path, account_id="account-1")
    records = restarted.list_outbound()
    assert duplicate.id == first.id
    assert len(records) == 1
    assert records[0].text == "agent reply"


def test_outbox_retries_then_moves_to_dead_letter(tmp_path: Path) -> None:
    store = WeixinDeliveryStore(tmp_path / "state.db", account_id="account-1")
    queued = store.enqueue_outbound(
        delivery_key="reply:message-1",
        kind="reply",
        source_id="message-1",
        to_user_id="user-1",
        text="agent reply",
        context_token="context-1",
        now=10.0,
    )

    first_claim = store.claim_due_outbound(now=10.0)
    assert first_claim[0].attempt_count == 1
    retry = store.mark_outbound_failed(
        queued.id,
        error="temporary",
        retryable=True,
        max_attempts=2,
        retry_delay_seconds=5.0,
        now=10.0,
    )
    assert retry is not None
    assert retry.status == "pending"
    assert store.claim_due_outbound(now=14.9) == []

    second_claim = store.claim_due_outbound(now=15.0)
    assert second_claim[0].attempt_count == 2
    dead_letter = store.mark_outbound_failed(
        queued.id,
        error="still failing",
        retryable=True,
        max_attempts=2,
        retry_delay_seconds=5.0,
        now=15.0,
    )
    assert dead_letter is not None
    assert dead_letter.status == "dead_letter"
    assert store.retry_dead_letter(queued.id, now=20.0) is True
    assert store.claim_due_outbound(now=20.0)[0].attempt_count == 3


def test_outbox_recovers_interrupted_send_and_marks_delivery(tmp_path: Path) -> None:
    store = WeixinDeliveryStore(tmp_path / "state.db", account_id="account-1")
    queued = store.enqueue_outbound(
        delivery_key="background:task-1",
        kind="background",
        source_id="task-1",
        to_user_id="user-1",
        text="done",
        context_token="context-1",
        now=10.0,
    )
    assert store.claim_due_outbound(now=10.0)[0].status == "sending"

    restarted = WeixinDeliveryStore(tmp_path / "state.db", account_id="account-1")
    assert restarted.recover_outbound(now=11.0) == 1
    claimed = restarted.claim_due_outbound(now=11.0)
    assert claimed[0].id == queued.id
    assert claimed[0].attempt_count == 2
    assert restarted.mark_outbound_delivered(queued.id, now=12.0) is True
    assert restarted.list_outbound(status="delivered")[0].delivered_at == 12.0

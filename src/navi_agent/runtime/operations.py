from __future__ import annotations

from hashlib import sha256
import json

from navi_agent.tooling import ToolResult

from .models import OperationStatus


_ALLOWED_TRANSITIONS = {
    OperationStatus.PLANNED: {OperationStatus.RUNNING},
    OperationStatus.RUNNING: {
        OperationStatus.SUCCEEDED,
        OperationStatus.FAILED,
        OperationStatus.AWAITING_INPUT,
    },
    OperationStatus.AWAITING_INPUT: {OperationStatus.RUNNING},
}


def validate_operation_transition(
    current: OperationStatus,
    target: OperationStatus,
) -> None:
    if target not in _ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(f"invalid operation status transition: {current} -> {target}")


def operation_arguments_hash(arguments: dict[str, object]) -> str:
    return _canonical_hash(arguments)


def operation_status_for_result(result: ToolResult) -> OperationStatus:
    if result.structured_content.get("interaction_pending") is True:
        return OperationStatus.AWAITING_INPUT
    if result.status == "success":
        return OperationStatus.SUCCEEDED
    return OperationStatus.FAILED


def operation_result_hash(result: ToolResult) -> str:
    metadata = {
        key: value
        for key, value in result.metadata.items()
        if not key.startswith("_trace_")
    }
    return _canonical_hash(
        {
            "name": result.name,
            "content": result.content,
            "status": result.status,
            "structured_content": result.structured_content,
            "metadata": metadata,
            "artifacts": [
                {
                    "kind": artifact.kind,
                    "uri": artifact.uri,
                    "title": artifact.title,
                    "mime_type": artifact.mime_type,
                    "metadata": artifact.metadata,
                }
                for artifact in result.artifacts
            ],
        }
    )


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()

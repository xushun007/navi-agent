from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class EnvironmentBinding:
    """Immutable identity and declared boundaries for an execution environment."""

    environment_id: str
    workspace_root: str
    additional_workspace_roots: tuple[str, ...] = ()
    workspace_revision: str | None = None
    executor_kind: str = "host"
    filesystem_enforcement: str = "tool_validation"
    network_policy: str = "host"
    secret_policy: str = "provider_managed"

    def __post_init__(self) -> None:
        for field_name in (
            "environment_id",
            "workspace_root",
            "executor_kind",
            "filesystem_enforcement",
            "network_policy",
            "secret_policy",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"environment {field_name} must not be empty")

    @classmethod
    def host(
        cls,
        workspace_root: Path,
        *,
        additional_workspace_roots: Iterable[Path] = (),
        workspace_revision: str | None = None,
        environment_id: str | None = None,
    ) -> EnvironmentBinding:
        root = workspace_root.resolve()
        added_roots: list[str] = []
        for candidate in additional_workspace_roots:
            resolved = str(Path(candidate).resolve())
            if resolved != str(root) and resolved not in added_roots:
                added_roots.append(resolved)
        return cls(
            environment_id=environment_id or uuid4().hex,
            workspace_root=str(root),
            additional_workspace_roots=tuple(added_roots),
            workspace_revision=workspace_revision,
        )

    @property
    def workspace_paths(self) -> tuple[Path, ...]:
        return (
            Path(self.workspace_root),
            *(Path(root) for root in self.additional_workspace_roots),
        )

    def to_metadata(self) -> dict[str, object]:
        return {
            "environment_id": self.environment_id,
            "workspace_root": self.workspace_root,
            "additional_workspace_roots": list(self.additional_workspace_roots),
            "workspace_revision": self.workspace_revision,
            "executor_kind": self.executor_kind,
            "filesystem_enforcement": self.filesystem_enforcement,
            "network_policy": self.network_policy,
            "secret_policy": self.secret_policy,
        }

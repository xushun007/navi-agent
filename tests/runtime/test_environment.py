from pathlib import Path

import pytest

from navi_agent.runtime import EnvironmentBinding


def test_host_environment_normalizes_workspace_roots(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    added = tmp_path / "shared"

    environment = EnvironmentBinding.host(
        root,
        additional_workspace_roots=(root, added, added),
        workspace_revision="abc123",
        environment_id="env-1",
    )

    assert environment.environment_id == "env-1"
    assert environment.workspace_root == str(root.resolve())
    assert environment.additional_workspace_roots == (str(added.resolve()),)
    assert environment.workspace_paths == (root.resolve(), added.resolve())
    assert environment.to_metadata() == {
        "environment_id": "env-1",
        "workspace_root": str(root.resolve()),
        "additional_workspace_roots": [str(added.resolve())],
        "workspace_revision": "abc123",
        "executor_kind": "host",
        "filesystem_enforcement": "tool_validation",
        "network_policy": "host",
        "secret_policy": "provider_managed",
    }


def test_environment_rejects_empty_identity(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="environment environment_id must not be empty"):
        EnvironmentBinding(environment_id="", workspace_root=str(tmp_path))

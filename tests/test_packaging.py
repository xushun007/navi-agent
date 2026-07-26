from pathlib import Path
import tomllib


def test_inspect_is_optional_for_runtime_users() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    runtime_dependencies = project["project"]["dependencies"]
    optional_dependencies = project["project"]["optional-dependencies"]
    development_dependencies = project["dependency-groups"]["dev"]

    assert not any(item.startswith("inspect-ai") for item in runtime_dependencies)
    assert any(
        item.startswith("inspect-ai") for item in optional_dependencies["eval"]
    )
    assert any(
        item.startswith("inspect-ai")
        for item in optional_dependencies["swe-bench"]
    )
    assert any(
        item.startswith("inspect-evals")
        for item in optional_dependencies["swe-bench"]
    )
    assert any(item.startswith("inspect-ai") for item in development_dependencies)

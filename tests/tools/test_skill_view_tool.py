from pathlib import Path

from navi_agent.evolution import FileSkillStore
from navi_agent.tools.defaults import build_default_tool_registry
from navi_agent.tools.skill_view_tool import SkillListTool, SkillViewTool


def test_skill_list_returns_skill_summaries(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(
        name="readme-review",
        content=(
            "---\n"
            "description: Review README files.\n"
            "---\n"
            "\n"
            "# README Review\n"
        ),
    )

    result = SkillListTool(store).invoke()

    assert result.status == "success"
    assert result.structured_content["skill_count"] == 1
    assert result.structured_content["skills"] == [
        {"name": "readme-review", "description": "Review README files."}
    ]


def test_skill_view_loads_skill_content(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(
        name="readme-review",
        content="# README Review\n\n## Procedure\n\n- Read README.",
    )

    result = SkillViewTool(store).invoke(skill_name="readme-review")

    assert result.status == "success"
    assert "# README Review" in result.content
    assert result.structured_content["skill_name"] == "readme-review"


def test_skill_view_loads_explicit_attachment(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(
        name="debug-crash",
        content="# Debug Crash\n\n## Procedure\n\n- Read referenced crash notes.",
    )
    store.write_attachment(
        name="debug-crash",
        relative_path="references/native.md",
        content="# Native Crashes\n",
    )

    result = SkillViewTool(store).invoke(
        skill_name="debug-crash",
        attachment_path="references/native.md",
    )

    assert result.status == "success"
    assert "# Native Crashes" in result.content
    assert result.structured_content["attachment_path"] == "references/native.md"


def test_default_registry_exposes_read_only_skill_tools(tmp_path: Path) -> None:
    registry = build_default_tool_registry(root=tmp_path, skill_store=FileSkillStore(tmp_path))

    schemas = registry.schemas(enabled_toolsets=["skills"])
    names = {schema["name"] for schema in schemas}

    assert names == {"skill_list", "skill_view"}

from pathlib import Path

from navi_agent.evolution import FileSkillStore
from navi_agent.tools.skill_manage_tool import SkillManageTool


def test_skill_manage_create_and_view(tmp_path: Path) -> None:
    tool = SkillManageTool(FileSkillStore(tmp_path))

    created = tool.invoke(
        action="create",
        skill_name="readme-review",
        skill_content=(
            "# README Review\n\n"
            "## When To Use\n\nUse for README review.\n\n"
            "## Procedure\n\n- Read the README.\n- Verify the summary."
        ),
    )
    viewed = tool.invoke(action="view", skill_name="readme-review")

    assert created.status == "success"
    assert created.structured_content["skill_name"] == "readme-review"
    assert viewed.status == "success"
    assert "# README Review" in viewed.content


def test_skill_manage_append_preserves_existing_content(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(
        name="readme-review",
        content="# README Review\n\n## Procedure\n\n- Read README.",
    )
    tool = SkillManageTool(store)

    result = tool.invoke(
        action="append",
        skill_name="readme-review",
        section="## Procedure",
        append_content="- Verify the result.",
    )
    record = store.get("readme-review")

    assert result.status == "success"
    assert record is not None
    assert "- Read README." in record.content
    assert "- Verify the result." in record.content


def test_skill_manage_list_returns_skill_summaries(tmp_path: Path) -> None:
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
    tool = SkillManageTool(store)

    result = tool.invoke(action="list")

    assert result.status == "success"
    assert result.structured_content["skill_count"] == 1
    assert "readme-review" in result.content


def test_skill_manage_rejects_create_without_required_sections(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    tool = SkillManageTool(store)

    result = tool.invoke(
        action="create",
        skill_name="readme-review",
        skill_content="# README Review\n\nUse for README review without enough structure.",
    )

    assert result.status == "error"
    assert "missing required section" in result.content
    assert store.get("readme-review") is None


def test_skill_manage_rejects_placeholder_append(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(
        name="readme-review",
        content="# README Review\n\n## Procedure\n\n- Read README.",
    )
    tool = SkillManageTool(store)

    result = tool.invoke(
        action="append",
        skill_name="readme-review",
        section="## Procedure",
        append_content="- ... keep existing content unchanged.",
    )

    assert result.status == "error"
    assert "placeholder" in result.content


def test_skill_manage_rejects_negative_tool_claim(tmp_path: Path) -> None:
    store = FileSkillStore(tmp_path)
    store.create(
        name="readme-review",
        content="# README Review\n\n## Procedure\n\n- Read README.",
    )
    tool = SkillManageTool(store)

    result = tool.invoke(
        action="append",
        skill_name="readme-review",
        section="## Pitfalls",
        append_content="- The read_file tool does not work.",
    )

    assert result.status == "error"
    assert "negative tool claim" in result.content

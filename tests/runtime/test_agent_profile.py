import pytest

from navi_agent.runtime import AgentProfile


def test_agent_profile_holds_resolved_execution_choices() -> None:
    profile = AgentProfile(
        role="subagent",
        max_iterations=8,
        enabled_toolsets=("file", "skills"),
        disabled_toolsets=("terminal",),
        non_interactive=True,
    )

    assert profile.role == "subagent"
    assert profile.max_iterations == 8
    assert profile.enabled_toolsets == ("file", "skills")
    assert profile.disabled_toolsets == ("terminal",)
    assert profile.allow_delegation is False
    assert profile.non_interactive is True


@pytest.mark.parametrize(
    ("role", "max_iterations", "message"),
    [
        ("", 1, "agent role must not be empty"),
        ("primary", 0, "agent max_iterations must be positive"),
    ],
)
def test_agent_profile_rejects_invalid_execution_choices(
    role: str,
    max_iterations: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        AgentProfile(role=role, max_iterations=max_iterations)


def test_agent_profile_rejects_invalid_context_limit() -> None:
    with pytest.raises(ValueError, match="agent context_limit_tokens must be positive"):
        AgentProfile(
            role="primary",
            max_iterations=1,
            context_limit_tokens=0,
        )

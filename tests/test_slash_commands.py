from navi_agent.cli.slash_commands import (
    command_spec,
    parse_slash_command,
    render_command_help,
    unknown_command_message,
)


def test_parses_slash_command_and_argument() -> None:
    command = parse_slash_command("  /STEER   use the new plan  ")

    assert command is not None
    assert command.name == "/steer"
    assert command.argument == "use the new plan"


def test_ignores_regular_messages() -> None:
    assert parse_slash_command("inspect /tmp/project") is None


def test_finds_known_command() -> None:
    assert command_spec("/stop") is not None
    assert command_spec("/missing") is None


def test_unknown_command_points_to_help() -> None:
    assert unknown_command_message("/stats") == (
        "Unknown command: /stats\nType /help to see available commands."
    )


def test_renders_concise_command_help() -> None:
    help_text = render_command_help()

    assert "/help" in help_text
    assert "/new" in help_text
    assert "/status" in help_text
    assert "/steer <message>" in help_text

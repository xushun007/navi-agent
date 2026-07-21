from unittest.mock import patch

from prompt_toolkit import Application
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.keys import Keys

from navi_agent.cli_input import (
    INTERACTIVE_STYLE,
    InteractivePromptSession,
    install_shift_enter_alias,
)


def test_install_shift_enter_alias_maps_modern_terminal_sequences() -> None:
    sequences = ("\x1b[13;2u", "\x1b[27;2;13~", "\x1b[27;2;13u")

    with patch.dict(ANSI_SEQUENCES, {sequence: Keys.ControlM for sequence in sequences}):
        changed = install_shift_enter_alias()

        assert changed == 3
        assert all(
            ANSI_SEQUENCES[sequence] == Keys.F24
            for sequence in sequences
        )


def test_install_shift_enter_alias_is_idempotent() -> None:
    sequences = ("\x1b[13;2u", "\x1b[27;2;13~", "\x1b[27;2;13u")
    shift_enter_key = Keys.F24

    with patch.dict(
        ANSI_SEQUENCES,
        {sequence: shift_enter_key for sequence in sequences},
    ):
        changed = install_shift_enter_alias()

        assert changed == 0


def test_interactive_placeholder_uses_subtle_style() -> None:
    assert INTERACTIVE_STYLE["placeholder"] == "ansibrightblack italic"
    assert INTERACTIVE_STYLE["frame.border"] == "ansibrightblack"


def test_interactive_prompt_builds_framed_application() -> None:
    with patch.object(Application, "run", autospec=True, return_value="hello") as run:
        result = InteractivePromptSession().prompt(placeholder="Message Navi Agent")

    assert result == "hello"
    application = run.call_args.args[0]
    assert application.full_screen is False
    assert application.layout.current_control is not None

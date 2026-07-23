from unittest.mock import patch
from types import SimpleNamespace

from prompt_toolkit import Application
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.keys import Keys

from navi_agent.cli_input import (
    INPUT_MAX_HEIGHT,
    INPUT_MIN_HEIGHT,
    INTERACTIVE_STYLE,
    InteractivePromptSession,
    PromptPlaceholderProcessor,
    install_shift_enter_alias,
)
from navi_agent.ui_events import UiEvent


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


def test_persistent_interactive_application_keeps_input_active() -> None:
    with patch.object(Application, "run", autospec=True, return_value=None) as run:
        InteractivePromptSession().run(lambda _message: None)

    application = run.call_args.args[0]
    assert application.full_screen is False
    assert application.erase_when_done is True
    assert application.layout.current_control is not None


def test_persistent_interactive_state_tracks_runtime_events() -> None:
    session = InteractivePromptSession()
    session.set_busy(True)
    session.handle(
        UiEvent(
            event_id="event-1",
            run_id="run-1",
            sequence=1,
            kind="tool",
            state="started",
            title="正在读取 README.md",
            item_id="tool-1",
        )
    )

    assert session.is_busy
    assert session.status_text == "正在读取 README.md"

    session.handle(
        UiEvent(
            event_id="event-2",
            run_id="run-1",
            sequence=2,
            kind="assistant",
            state="delta",
            title="",
            item_id="model:1",
            detail="hello",
        )
    )

    assert session.status_text == ""
    assert session._render_response() == [("class:response", "hello")]


def test_commit_history_does_not_reschedule_run_in_terminal_future() -> None:
    application = SimpleNamespace(
        loop=SimpleNamespace(is_running=lambda: False),
        create_background_task=lambda _future: (_ for _ in ()).throw(
            AssertionError("future must not be scheduled twice")
        ),
    )
    session = InteractivePromptSession()
    session._application = application

    with patch("prompt_toolkit.application.run_in_terminal") as run_in_terminal:
        session.commit_history("done")

    run_in_terminal.assert_called_once()


def test_interactive_input_height_starts_single_line_and_is_bounded() -> None:
    assert INPUT_MIN_HEIGHT == 1
    assert INPUT_MAX_HEIGHT == 6


def test_streamed_response_height_accounts_for_wrapping() -> None:
    session = InteractivePromptSession()
    session._response_text = "x" * 120

    with patch(
        "navi_agent.cli_input.shutil.get_terminal_size",
        return_value=SimpleNamespace(columns=40),
    ):
        height = session._response_height()

    assert height == 3


def test_placeholder_does_not_move_cursor_after_placeholder_text() -> None:
    text_area = SimpleNamespace(text="")
    processor = PromptPlaceholderProcessor(text_area, "Message Navi Agent")

    transformation = processor.apply_transformation(
        SimpleNamespace(lineno=0, fragments=[])
    )

    assert "".join(fragment[1] for fragment in transformation.fragments) == (
        "❯ Message Navi Agent"
    )
    assert transformation.source_to_display(0) == 2
    assert transformation.display_to_source(len("❯ Message Navi Agent")) == 0


def test_placeholder_disappears_when_input_has_content() -> None:
    text_area = SimpleNamespace(text="hello")
    processor = PromptPlaceholderProcessor(text_area, "Message Navi Agent")

    transformation = processor.apply_transformation(
        SimpleNamespace(lineno=0, fragments=[("", "hello")])
    )

    assert "".join(fragment[1] for fragment in transformation.fragments) == "❯ hello"

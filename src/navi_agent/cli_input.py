from __future__ import annotations

from typing import Any

from prompt_toolkit.formatted_text.utils import fragment_list_len
from prompt_toolkit.layout.processors import Processor, Transformation, TransformationInput


INPUT_MIN_HEIGHT = 1
INPUT_MAX_HEIGHT = 6


INTERACTIVE_STYLE = {
    "frame.border": "ansibrightblack",
    "input": "",
    "placeholder": "ansibrightblack italic",
    "prompt": "ansibrightyellow bold",
    "toolbar": "ansibrightblack",
}


class PromptPlaceholderProcessor(Processor):
    def __init__(self, text_area: Any, placeholder: str) -> None:
        self._text_area = text_area
        self._placeholder = placeholder

    def apply_transformation(self, transformation_input: TransformationInput) -> Transformation:
        if transformation_input.lineno != 0:
            return Transformation(transformation_input.fragments)

        prompt_fragments = [("class:prompt", "❯ ")]
        visible_fragments = list(prompt_fragments)
        show_placeholder = bool(self._placeholder and not self._text_area.text)
        if show_placeholder:
            visible_fragments.append(("class:placeholder", self._placeholder))
        visible_fragments.extend(transformation_input.fragments)

        cursor_offset = fragment_list_len(prompt_fragments)
        return Transformation(
            visible_fragments,
            source_to_display=lambda position: position + cursor_offset,
            display_to_source=(
                (lambda _position: 0)
                if show_placeholder
                else (lambda position: max(0, position - cursor_offset))
            ),
        )


def install_shift_enter_alias() -> int:
    try:
        from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
        from prompt_toolkit.keys import Keys
    except ImportError:
        return 0

    shift_enter_key = Keys.F24
    changed = 0
    for sequence in ("\x1b[13;2u", "\x1b[27;2;13~", "\x1b[27;2;13u"):
        if ANSI_SEQUENCES.get(sequence) == shift_enter_key:
            continue
        ANSI_SEQUENCES[sequence] = shift_enter_key
        changed += 1
    return changed


class InteractivePromptSession:
    def __init__(self) -> None:
        from prompt_toolkit.history import InMemoryHistory

        install_shift_enter_alias()
        self._history = InMemoryHistory()

    def prompt(self, _message: Any = None, *, placeholder: str = "") -> str:
        from prompt_toolkit import Application
        from prompt_toolkit.formatted_text import HTML
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.layout.containers import HSplit, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.layout.dimension import Dimension
        from prompt_toolkit.styles import Style
        from prompt_toolkit.widgets import Frame, TextArea

        bindings = KeyBindings()
        text_area = TextArea(
            multiline=True,
            history=self._history,
            height=Dimension(min=INPUT_MIN_HEIGHT, max=INPUT_MAX_HEIGHT),
            dont_extend_height=True,
            style="class:input",
            wrap_lines=True,
        )
        text_area.control.input_processors.append(
            PromptPlaceholderProcessor(text_area, placeholder)
        )

        @bindings.add("enter")
        def submit(event):
            event.app.exit(result=text_area.text)

        @bindings.add("f24")
        def newline(event):
            event.current_buffer.insert_text("\n")

        @bindings.add("c-c")
        def cancel(event):
            event.app.exit(result="exit")

        @bindings.add("c-d")
        def eof(event):
            event.app.exit(exception=EOFError)

        toolbar = Window(
            content=FormattedTextControl(
                HTML("<toolbar> Enter send · Shift+Enter newline · Ctrl-C quit </toolbar>")
            ),
            height=1,
            style="class:toolbar",
        )
        root = HSplit(
            [
                Frame(text_area, style="class:frame"),
                toolbar,
            ]
        )
        application = Application(
            layout=Layout(root, focused_element=text_area),
            key_bindings=bindings,
            style=Style.from_dict(INTERACTIVE_STYLE),
            full_screen=False,
        )
        return application.run()

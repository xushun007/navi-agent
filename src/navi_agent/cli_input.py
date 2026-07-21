from __future__ import annotations

from typing import Any


INTERACTIVE_STYLE = {
    "frame.border": "ansibrightblack",
    "input": "",
    "placeholder": "ansibrightblack italic",
    "prompt": "ansibrightyellow bold",
    "toolbar": "ansibrightblack",
}


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
        from prompt_toolkit.layout.processors import BeforeInput
        from prompt_toolkit.styles import Style
        from prompt_toolkit.widgets import Frame, TextArea

        bindings = KeyBindings()
        text_area = TextArea(
            multiline=True,
            history=self._history,
            height=Dimension(min=3, max=8),
            style="class:input",
            wrap_lines=True,
        )

        def prompt_fragments():
            fragments = [("class:prompt", "❯ ")]
            if placeholder and not text_area.text:
                fragments.append(("class:placeholder", placeholder))
            return fragments

        text_area.control.input_processors.append(BeforeInput(prompt_fragments))

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

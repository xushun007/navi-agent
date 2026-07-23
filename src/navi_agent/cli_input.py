from __future__ import annotations

import inspect
from threading import Lock
from typing import Any

from prompt_toolkit.formatted_text.utils import fragment_list_len
from prompt_toolkit.layout.processors import Processor, Transformation, TransformationInput

from navi_agent.ui_events import UiEvent


INPUT_MIN_HEIGHT = 1
INPUT_MAX_HEIGHT = 6


INTERACTIVE_STYLE = {
    "frame.border": "ansibrightblack",
    "input": "",
    "placeholder": "ansibrightblack italic",
    "prompt": "ansibrightyellow bold",
    "toolbar": "ansibrightblack",
    "status": "ansibrightblack italic",
    "response": "",
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
        self._lock = Lock()
        self._application = None
        self._status_text = ""
        self._response_text = ""
        self._busy = False

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

    def run(self, on_submit, *, first_message: str | None = None) -> None:
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
            PromptPlaceholderProcessor(text_area, "Message Navi Agent")
        )

        def submit_message() -> None:
            message = text_area.text.strip()
            if not message:
                return
            text_area.buffer.reset()
            self.commit_history(f"❯ {message}")
            on_submit(message)

        @bindings.add("enter")
        def submit(_event):
            submit_message()

        @bindings.add("f24")
        def newline(event):
            event.current_buffer.insert_text("\n")

        @bindings.add("c-c")
        def cancel(_event):
            on_submit("/stop" if self.is_busy else "exit")

        @bindings.add("c-d")
        def eof(_event):
            on_submit("exit")

        response = Window(
            content=FormattedTextControl(self._render_response),
            height=self._response_height,
            wrap_lines=True,
            style="class:response",
        )
        status = Window(
            content=FormattedTextControl(self._render_status),
            height=lambda: 1 if self.status_text else 0,
            style="class:status",
        )
        toolbar = Window(
            content=FormattedTextControl(
                lambda: HTML(
                    "<toolbar> Agent running · /stop · /steer &lt;message&gt; </toolbar>"
                    if self.is_busy
                    else "<toolbar> Enter send · Shift+Enter newline · Ctrl-C quit </toolbar>"
                )
            ),
            height=1,
            style="class:toolbar",
        )
        root = HSplit(
            [
                response,
                status,
                Frame(text_area, style="class:frame"),
                toolbar,
            ]
        )
        application = Application(
            layout=Layout(root, focused_element=text_area),
            key_bindings=bindings,
            style=Style.from_dict(INTERACTIVE_STYLE),
            full_screen=False,
            erase_when_done=True,
        )
        self._application = application

        def start_first_message() -> None:
            if first_message:
                self.commit_history(f"❯ {first_message}")
                on_submit(first_message)

        try:
            application.run(pre_run=start_first_message)
        finally:
            self._application = None

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return self._busy

    @property
    def status_text(self) -> str:
        with self._lock:
            return self._status_text

    def set_busy(self, busy: bool) -> None:
        with self._lock:
            self._busy = busy
            if busy and not self._status_text:
                self._status_text = "Working…"
            if not busy:
                self._status_text = ""
        self.invalidate()

    def handle(self, event: UiEvent) -> None:
        with self._lock:
            if event.kind == "assistant" and event.state == "delta":
                self._response_text += event.detail or ""
                self._status_text = ""
            elif event.kind == "assistant" and event.state == "completed":
                self._status_text = ""
            elif event.state in {"started", "progress"}:
                self._status_text = event.title
                if event.detail:
                    self._status_text = f"{self._status_text} — {event.detail}"
            elif event.kind == "error" or event.state == "failed":
                self._status_text = event.title
            elif event.state in {"waiting", "cancelled"}:
                self._status_text = event.title
        self.invalidate()

    def complete_response(self, final_response: str) -> None:
        with self._lock:
            response = self._response_text or final_response
            self._response_text = ""
            self._status_text = ""
            self._busy = False
        if response:
            self.commit_history(response)
        self.invalidate()

    def show_notice(self, text: str) -> None:
        self.commit_history(text)

    def exit(self) -> None:
        application = self._application
        if application is None:
            return
        loop = getattr(application, "loop", None)
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(application.exit)
        else:
            application.exit()

    def invalidate(self) -> None:
        application = self._application
        if application is not None:
            application.invalidate()

    def commit_history(self, text: str) -> None:
        application = self._application
        if application is None:
            print(text)
            return

        def schedule() -> None:
            from prompt_toolkit import print_formatted_text
            from prompt_toolkit.application import run_in_terminal

            result = run_in_terminal(lambda: print_formatted_text(text))
            if inspect.isawaitable(result):
                application.create_background_task(result)

        loop = getattr(application, "loop", None)
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(schedule)
        else:
            schedule()

    def _render_response(self):
        with self._lock:
            text = self._response_text
        return [("class:response", text)] if text else []

    def _render_status(self):
        status = self.status_text
        return [("class:status", f"  {status}")] if status else []

    def _response_height(self) -> int:
        with self._lock:
            text = self._response_text
        if not text:
            return 0
        return min(12, max(1, text.count("\n") + 1))

from __future__ import annotations

import shutil
from threading import Lock
from typing import Any

from prompt_toolkit.formatted_text.utils import fragment_list_len
from prompt_toolkit.layout.processors import Processor, Transformation, TransformationInput

from navi_agent.ui_events import UiEvent, render_ui_event


INPUT_MIN_HEIGHT = 1
INPUT_MAX_HEIGHT = 6


INTERACTIVE_STYLE = {
    "event.error": "#d7875f bold",
    "event.output": "ansibrightblack",
    "event.running": "ansicyan bold",
    "event.success": "ansigreen bold",
    "event.warning": "ansiyellow bold",
    "approval.option": "",
    "approval.selected": "ansiyellow bold",
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
        self._status_style = "class:status"
        self._response_text = ""
        self._busy = False
        self._approval_pending = False
        self._approval_selected = True
        self._approval_title = ""
        self._approval_detail = ""
        self._seen_event_ids: set[str] = set()

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

    def run(self, on_submit, *, on_approval=None, first_message: str | None = None) -> None:
        from prompt_toolkit import Application
        from prompt_toolkit.filters import Condition
        from prompt_toolkit.formatted_text import HTML
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.layout.containers import ConditionalContainer, HSplit, Window
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
            approved = self.consume_approval_selection()
            if approved is not None:
                if on_approval is not None:
                    on_approval(approved)
                return
            submit_message()

        approval_active = Condition(lambda: self.approval_pending)

        @bindings.add("up", filter=approval_active)
        def select_allow(_event):
            self.select_approval(True)

        @bindings.add("down", filter=approval_active)
        def select_deny(_event):
            self.select_approval(False)

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
        approval = Window(
            content=FormattedTextControl(self._render_approval),
            height=self._approval_height,
            wrap_lines=True,
        )
        toolbar = Window(
            content=FormattedTextControl(
                lambda: HTML(
                    "<toolbar> ↑/↓ select · Enter confirm </toolbar>"
                    if self.approval_pending
                    else "<toolbar> Agent running · /stop · /steer &lt;message&gt; </toolbar>"
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
                approval,
                ConditionalContainer(
                    content=Frame(text_area, style="class:frame"),
                    filter=~approval_active,
                ),
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

    @property
    def approval_pending(self) -> bool:
        with self._lock:
            return self._approval_pending

    def set_busy(self, busy: bool) -> None:
        with self._lock:
            self._busy = busy
            if busy and not self._status_text:
                self._status_text = "Working…"
                self._status_style = "class:status"
            if not busy:
                self._status_text = ""
        self.invalidate()

    def select_approval(self, approved: bool) -> None:
        with self._lock:
            if not self._approval_pending:
                return
            self._approval_selected = approved
        self.invalidate()

    def consume_approval_selection(self) -> bool | None:
        with self._lock:
            if not self._approval_pending:
                return None
            approved = self._approval_selected
            self._clear_approval_locked()
        self.invalidate()
        return approved

    def clear_approval(self) -> None:
        with self._lock:
            self._clear_approval_locked()
        self.invalidate()

    def _clear_approval_locked(self) -> None:
        self._approval_pending = False
        self._approval_selected = True
        self._approval_title = ""
        self._approval_detail = ""

    def handle(self, event: UiEvent) -> None:
        history_line: str | None = None
        with self._lock:
            if event.event_id in self._seen_event_ids:
                return
            self._seen_event_ids.add(event.event_id)

            if event.kind == "assistant" and event.state == "delta":
                self._response_text += event.detail or ""
                self._status_text = ""
            elif event.kind == "assistant" and event.state == "completed":
                if event.transient:
                    self._response_text = ""
                self._status_text = ""
            elif event.state in {"started", "progress"}:
                self._status_text = event.title
                self._status_style = _event_style(event) or "class:status"
                if event.detail:
                    self._status_text = f"{self._status_text} — {event.detail}"
            elif event.kind in {"tool", "approval"}:
                self._status_text = event.title if event.state == "failed" else ""
                self._status_style = _event_style(event) or "class:status"
                if event.kind == "approval":
                    self._approval_pending = True
                    self._approval_selected = True
                    self._approval_title = event.title
                    self._approval_detail = event.detail or ""
                else:
                    history_line = render_ui_event(event)
            elif event.kind == "error" or event.state == "failed":
                self._status_text = event.title
                self._status_style = _event_style(event) or "class:status"
                history_line = render_ui_event(event)
            elif event.state in {"waiting", "cancelled"}:
                self._status_text = event.title
                self._status_style = _event_style(event) or "class:status"
                history_line = render_ui_event(event)
        if history_line:
            self.commit_history(history_line, style=_event_style(event))
        self.invalidate()

    def complete_response(self, final_response: str) -> None:
        with self._lock:
            response = "" if self._approval_pending else self._response_text or final_response
            self._response_text = ""
            self._status_text = ""
            self._status_style = "class:status"
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

    def commit_history(self, text: str, *, style: str | None = None) -> None:
        application = self._application
        if application is None:
            print(text)
            return

        def schedule() -> None:
            from prompt_toolkit import print_formatted_text
            from prompt_toolkit.application import run_in_terminal
            from prompt_toolkit.formatted_text import FormattedText
            from prompt_toolkit.styles import Style

            fragments = _styled_history_fragments(text, style)
            history_style = Style.from_dict(INTERACTIVE_STYLE)
            run_in_terminal(
                lambda: print_formatted_text(
                    FormattedText(fragments),
                    style=history_style,
                )
            )

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
        with self._lock:
            status = self._status_text
            style = self._status_style
        return [(style, f"  {status}")] if status else []

    def _render_approval(self):
        with self._lock:
            if not self._approval_pending:
                return []
            title = self._approval_title
            detail = self._approval_detail
            approved = self._approval_selected
        lines = [
            ("class:event.warning", f"! {title}\n"),
        ]
        if detail:
            lines.append(("class:event.output", f"  {detail}\n"))
        lines.extend(
            [
                (
                    "class:approval.selected" if approved else "class:approval.option",
                    f"  {'❯' if approved else ' '} Allow\n",
                ),
                (
                    "class:approval.selected" if not approved else "class:approval.option",
                    f"  {'❯' if not approved else ' '} Deny",
                ),
            ]
        )
        return lines

    def _approval_height(self) -> int:
        with self._lock:
            if not self._approval_pending:
                return 0
            detail_lines = max(1, self._approval_detail.count("\n") + 1)
        return 3 + detail_lines

    def _response_height(self) -> int:
        with self._lock:
            text = self._response_text
        if not text:
            return 0
        width = max(20, shutil.get_terminal_size((80, 24)).columns)
        visible_lines = sum(
            max(1, (len(line) + width - 1) // width)
            for line in text.split("\n")
        )
        return min(12, visible_lines)


def _event_style(event: UiEvent) -> str | None:
    if event.kind == "approval" or event.state == "waiting":
        return "class:event.warning"
    if event.state == "failed" or event.kind == "error":
        return "class:event.error"
    if event.state == "completed":
        return "class:event.success"
    if event.state in {"started", "progress"}:
        return "class:event.running"
    return None


def _styled_history_fragments(text: str, style: str | None) -> list[tuple[str, str]]:
    if not style:
        return [("", text)]
    lines = text.splitlines()
    if not lines:
        return [(style, text)]
    fragments = [("", "\n"), (style, lines[0])]
    for line in lines[1:]:
        fragments.extend(
            [
                ("", "\n"),
                ("class:event.output", line),
            ]
        )
    if style:
        fragments.append(("", "\n"))
    return fragments

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SlashCommandSpec:
    name: str
    description: str
    usage: str


@dataclass(frozen=True, slots=True)
class SlashCommand:
    name: str
    argument: str = ""


COMMAND_SPECS = (
    SlashCommandSpec("/approve", "Approve the pending tool request", "/approve"),
    SlashCommandSpec("/deny", "Deny the pending tool request", "/deny"),
    SlashCommandSpec("/exit", "Exit Navi Agent", "/exit"),
    SlashCommandSpec("/help", "Show available commands", "/help"),
    SlashCommandSpec("/history", "Show recent sessions", "/history"),
    SlashCommandSpec("/new", "Start a new session", "/new"),
    SlashCommandSpec("/resume", "Resume an existing session", "/resume <id>"),
    SlashCommandSpec("/status", "Show the current session status", "/status"),
    SlashCommandSpec("/steer", "Redirect the active task", "/steer <message>"),
    SlashCommandSpec("/stop", "Stop the active task", "/stop"),
    SlashCommandSpec("/tasks", "Show background tasks", "/tasks"),
)
_COMMANDS_BY_NAME = {spec.name: spec for spec in COMMAND_SPECS}


def parse_slash_command(message: str) -> SlashCommand | None:
    stripped = message.strip()
    if not stripped.startswith("/"):
        return None
    name, separator, argument = stripped.partition(" ")
    return SlashCommand(
        name=name.lower(),
        argument=argument.strip() if separator else "",
    )


def command_spec(name: str) -> SlashCommandSpec | None:
    return _COMMANDS_BY_NAME.get(name.lower())


def unknown_command_message(name: str) -> str:
    return f"Unknown command: {name}\nType /help to see available commands."


def render_command_help() -> str:
    width = max(len(spec.usage) for spec in COMMAND_SPECS)
    return "\n".join(
        f"{spec.usage:<{width}}  {spec.description}"
        for spec in COMMAND_SPECS
    )

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BashCommandAssessment:
    action: str
    reason: str
    commands: tuple[tuple[str, ...], ...] = ()


_SAFE_COMMANDS = {
    "cat",
    "echo",
    "grep",
    "head",
    "ls",
    "printf",
    "pwd",
    "rg",
    "stat",
    "tail",
    "wc",
}
_HARD_DENY_COMMANDS = {
    "dd",
    "halt",
    "mkfs",
    "poweroff",
    "reboot",
    "shutdown",
    "sudo",
}
_SEPARATORS = {"|", "&&", "||", ";"}
_UNSAFE_FIND_OPTIONS = {
    "-delete",
    "-exec",
    "-execdir",
    "-fls",
    "-fprint",
    "-fprint0",
    "-fprintf",
    "-ok",
    "-okdir",
}
_UNSAFE_RG_OPTIONS = {"--hostname-bin", "--pre", "--search-zip", "-z"}
_UNSAFE_GIT_OPTIONS = {
    "--exec",
    "--ext-diff",
    "--output",
    "--textconv",
}


def assess_bash_command(command: str, *, background: bool = False) -> BashCommandAssessment:
    command = command.strip()
    if not command:
        return BashCommandAssessment("deny", "empty bash command")
    if background:
        return BashCommandAssessment("ask", "background bash command requires approval")
    if "\n" in command or "`" in command or "$" in command:
        return BashCommandAssessment("ask", "dynamic shell syntax requires approval")

    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return BashCommandAssessment("ask", "unparseable bash command requires approval")

    commands: list[tuple[str, ...]] = []
    current: list[str] = []
    for token in tokens:
        if token in _SEPARATORS:
            if not current:
                return BashCommandAssessment("ask", "complex shell syntax requires approval")
            commands.append(tuple(current))
            current = []
            continue
        if any(character in token for character in "<>&();"):
            return BashCommandAssessment(
                "ask",
                "shell redirection or background execution requires approval",
            )
        current.append(token)
    if not current:
        return BashCommandAssessment("ask", "incomplete shell command requires approval")
    commands.append(tuple(current))
    parsed_commands = tuple(commands)

    for words in commands:
        executable = words[0]
        if "/" in executable:
            return BashCommandAssessment(
                "ask", "explicit executable paths require approval", parsed_commands
            )
        if executable in _HARD_DENY_COMMANDS or _is_catastrophic_rm(words):
            return BashCommandAssessment(
                "deny", f"bash command is not allowed: {executable}", parsed_commands
            )
        if not _is_known_read_only(words):
            return BashCommandAssessment(
                "ask", f"bash command requires approval: {executable}", parsed_commands
            )

    return BashCommandAssessment(
        "allow",
        "known read-only bash command",
        parsed_commands,
    )


def _is_known_read_only(words: tuple[str, ...]) -> bool:
    executable = words[0]
    if executable in _SAFE_COMMANDS:
        if executable == "rg":
            return not _contains_option(words[1:], _UNSAFE_RG_OPTIONS)
        return True
    if executable == "find":
        return not _contains_option(words[1:], _UNSAFE_FIND_OPTIONS)
    if executable == "git":
        return _is_read_only_git(words)
    return False


def _is_read_only_git(words: tuple[str, ...]) -> bool:
    if len(words) < 2 or words[1].startswith("-"):
        return False
    subcommand = words[1]
    arguments = words[2:]
    if _contains_option(arguments, _UNSAFE_GIT_OPTIONS):
        return False
    if subcommand in {"status", "log", "diff", "show"}:
        return True
    if subcommand != "branch":
        return False
    return all(
        argument
        in {
            "--all",
            "--list",
            "--remotes",
            "--show-current",
            "--verbose",
            "-a",
            "-r",
            "-v",
            "-vv",
        }
        or argument.startswith("--format=")
        for argument in arguments
    )


def _contains_option(arguments: tuple[str, ...], options: set[str]) -> bool:
    return any(
        argument in options or any(argument.startswith(f"{option}=") for option in options)
        for argument in arguments
    )


def _is_catastrophic_rm(words: tuple[str, ...]) -> bool:
    if not words or words[0] != "rm":
        return False
    flags = "".join(
        word[1:]
        for word in words[1:]
        if word.startswith("-") and not word.startswith("--")
    )
    recursive = "r" in flags or "R" in flags or "--recursive" in words
    forced = "f" in flags or "--force" in words
    targets = [word.rstrip("/") or "/" for word in words[1:] if not word.startswith("-")]
    return recursive and forced and any(re.fullmatch(r"/|~", target) for target in targets)

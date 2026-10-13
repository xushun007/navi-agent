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
    "awk",
    "cat",
    "cut",
    "echo",
    "find",
    "grep",
    "head",
    "ls",
    "printf",
    "pwd",
    "rg",
    "sed",
    "sort",
    "stat",
    "tail",
    "uniq",
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
_UNSAFE_SORT_OPTIONS = {
    "--compress-program",
    "--output",
    "--random-source",
}


def assess_bash_command(command: str, *, background: bool = False) -> BashCommandAssessment:
    command = command.strip()
    if not command:
        return BashCommandAssessment("deny", "empty bash command")
    if background:
        return BashCommandAssessment("ask", "background bash command requires approval")
    if "\n" in command or "`" in command:
        return BashCommandAssessment("ask", "dynamic shell syntax requires approval")

    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return BashCommandAssessment("ask", "unparseable bash command requires approval")

    tokens = _strip_null_redirections(tokens)
    commands: list[tuple[str, ...]] = []
    separators: list[str] = []
    current: list[str] = []
    for token in tokens:
        if token in _SEPARATORS:
            if not current:
                return BashCommandAssessment("ask", "complex shell syntax requires approval")
            commands.append(tuple(current))
            separators.append(token)
            current = []
            continue
        if token in {"<", ">", "&"}:
            return BashCommandAssessment(
                "ask",
                "shell redirection or background execution requires approval",
            )
        current.append(token)
    if not current:
        return BashCommandAssessment("ask", "incomplete shell command requires approval")
    commands.append(tuple(current))
    parsed_commands = tuple(commands)

    for index, words in enumerate(commands):
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
        if (
            executable == "cd"
            and index < len(separators)
            and separators[index] not in {"&&", ";"}
        ):
            return BashCommandAssessment(
                "ask",
                "conditional or piped directory changes require approval",
                parsed_commands,
            )

    return BashCommandAssessment(
        "allow",
        "known read-only bash command",
        parsed_commands,
    )


def _is_known_read_only(words: tuple[str, ...]) -> bool:
    executable = words[0]
    if executable in _SAFE_COMMANDS:
        arguments = words[1:]
        if executable != "find" and any(argument in {"(", ")"} for argument in arguments):
            return False
        if executable != "awk" and any("$" in argument for argument in arguments):
            return False
        if executable == "rg":
            return not (
                _contains_option(arguments, _UNSAFE_RG_OPTIONS)
                or _contains_short_option(arguments, "z")
            )
        if executable == "find":
            return not _contains_option(arguments, _UNSAFE_FIND_OPTIONS)
        if executable == "sort":
            return not (
                _contains_option(arguments, _UNSAFE_SORT_OPTIONS)
                or _contains_short_option(arguments, "o")
            )
        if executable == "sed":
            return _is_safe_sed(arguments)
        if executable == "awk":
            return _is_safe_awk(arguments)
        return True
    if executable == "cd":
        return _is_static_directory_change(words)
    if executable == "git":
        return False
    return False


def _strip_null_redirections(tokens: list[str]) -> list[str]:
    """Allow stdout/stderr suppression without allowing writes to real files."""
    stripped: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if (
            token in {">", ">>"}
            and index + 1 < len(tokens)
            and tokens[index + 1] == "/dev/null"
            and token == ">"
        ):
            if stripped and stripped[-1] in {"1", "2"}:
                stripped.pop()
            index += 2
            continue
        stripped.append(token)
        index += 1
    return stripped


def _is_safe_sed(arguments: tuple[str, ...]) -> bool:
    if _contains_option(arguments, {"--in-place"}) or _contains_short_option(arguments, "i"):
        return False
    return not any(_sed_script_can_write(argument) for argument in arguments)


def _sed_script_can_write(argument: str) -> bool:
    """Reject sed's command-execution and file-writing forms conservatively."""
    lowered = argument.lower()
    return bool(
        re.search(r"(^|;)\s*[ew]\b", lowered)
        or any(f"{delimiter}e" in lowered for delimiter in "/|#:")
        or any(f"{delimiter}w" in lowered for delimiter in "/|#:")
        or "w " in lowered
    )


def _is_safe_awk(arguments: tuple[str, ...]) -> bool:
    program = " ".join(argument for argument in arguments if not argument.startswith("-"))
    forbidden = ("system(", "getline", "|", ">", "<")
    return not (
        any(fragment in program for fragment in forbidden)
        or bool(re.search(r"\$(?:[A-Za-z_]|\{)", program))
    )


def _is_static_directory_change(words: tuple[str, ...]) -> bool:
    if len(words) != 2:
        return False
    target = words[1]
    return (
        bool(target)
        and target != "-"
        and not target.startswith(("-", "~"))
        and not any(character in target for character in "*?[]{}")
    )


def _contains_option(arguments: tuple[str, ...], options: set[str]) -> bool:
    return any(
        argument in options or any(argument.startswith(f"{option}=") for option in options)
        for argument in arguments
    )


def _contains_short_option(arguments: tuple[str, ...], option: str) -> bool:
    return any(
        argument.startswith("-")
        and not argument.startswith("--")
        and option in argument[1:]
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

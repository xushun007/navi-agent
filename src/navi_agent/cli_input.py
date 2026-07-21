from __future__ import annotations


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

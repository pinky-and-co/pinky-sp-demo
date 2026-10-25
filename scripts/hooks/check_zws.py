#!/usr/bin/env python3
"""ZWS — Detection of invisible characters (zero-width spaces).

Common source: copy-paste from Outlook or Teams.
Detected characters: U+200B, U+200C, U+200D, U+FEFF.
"""

import os
import re
import sys
from pathlib import Path

from _report import Diagnostic, at, emit

# Script autonome, n'importe pas `setup` : la console Windows (cp1252) ne sait pas encoder ✓/⚠.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ZWS = [chr(0x200B), chr(0x200C), chr(0x200D), chr(0xFEFF)]
_ZWS_RE = re.compile("[" + "".join(ZWS) + "]")


def _looks_binary(filepath: str) -> bool:
    """Heuristic: a NUL byte in the first 8KB means binary (same rule git/grep use)."""
    try:
        with open(filepath, "rb") as f:
            return b"\x00" in f.read(8192)
    except OSError:
        return False


def check_file(filepath: str) -> list[int]:
    """1-indexed line numbers of `filepath` that contain a zero-width character; [] if binary."""
    found: list[int] = []
    if _looks_binary(filepath):
        return found
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, 1):
                if any(ch in line for ch in ZWS):
                    found.append(i)
    except Exception:  # noqa: S110 — silently skip unreadable files
        pass
    return found


def _is_disabled() -> bool:
    """True if this hook's filename stem is listed in `PINKY_DISABLED_HOOKS` (comma-separated)."""
    disabled = os.environ.get("PINKY_DISABLED_HOOKS", "")
    return Path(__file__).stem in {h.strip() for h in disabled.split(",") if h.strip()}


def main() -> int:
    """Fail if any CLI argument contains a zero-width character; returns 1 on any hit."""
    if _is_disabled():
        return 0
    findings: list[Diagnostic] = [
        at("ZWS", "invisible character (zero-width)", filepath, line, _ZWS_RE)
        for filepath in sys.argv[1:]
        for line in check_file(filepath)
    ]
    emit(
        findings,
        footer="search your editor for `[\\u200b\\u200c\\u200d\\ufeff]` and delete them — "
        "likely source: copy-paste from Outlook or Teams",
    )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""LaTeX notation — detection of inline-math commands used instead of their Unicode symbol.

Common source: a local LLM (Gemma via Ollama) falls back to LaTeX inline-math notation
for common symbols on long, freely-composed text, instead of writing the Unicode
character directly — a backslash command wrapped in a pair of dollar signs. Both dollar
signs are required for a match: every real occurrence observed so far carried them, and
requiring them keeps this checker from flagging its own LATEX_TO_UNICODE table below
(bare backslash commands, no dollar signs). Fenced code blocks are skipped too, so a
code example documenting this exact defect never flags itself.
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

LATEX_TO_UNICODE = {
    r"\rightarrow": "→",
    r"\Rightarrow": "⇒",
    r"\leftarrow": "←",
    r"\Leftarrow": "⇐",
    r"\leftrightarrow": "↔",
    r"\Leftrightarrow": "⇔",
    r"\times": "×",
    r"\div": "÷",
    r"\pm": "±",
    r"\mp": "∓",
    r"\cdot": "·",
    r"\leq": "≤",
    r"\geq": "≥",
    r"\neq": "≠",
    r"\approx": "≈",
    r"\equiv": "≡",
    r"\infty": "∞",
    r"\in": "∈",
    r"\notin": "∉",
    r"\subset": "⊂",
    r"\subseteq": "⊆",
    r"\forall": "∀",
    r"\exists": "∃",
    r"\emptyset": "∅",
    r"\cup": "∪",
    r"\cap": "∩",
    r"\sum": "∑",
    r"\prod": "∏",
    r"\sqrt": "√",
    r"\alpha": "α",
    r"\beta": "β",
    r"\gamma": "γ",
    r"\delta": "δ",
    r"\pi": "π",
    r"\theta": "θ",
    r"\lambda": "λ",
    r"\mu": "μ",
    r"\sigma": "σ",
    r"\omega": "ω",
}

_KEYS_BY_LEN = sorted(LATEX_TO_UNICODE, key=len, reverse=True)
_PATTERN = re.compile(r"\$(" + "|".join(re.escape(k) for k in _KEYS_BY_LEN) + r")\$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def _looks_binary(filepath: str) -> bool:
    """Heuristic: a NUL byte in the first 8KB means binary (same rule git/grep use)."""
    try:
        with open(filepath, "rb") as f:
            return b"\x00" in f.read(8192)
    except OSError:
        return False


def check_file(filepath: str) -> list[int]:
    found: list[int] = []
    if _looks_binary(filepath):
        return found
    in_fence = False
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, 1):
                if _FENCE.match(line):
                    in_fence = not in_fence
                    continue
                if in_fence:
                    continue
                if _PATTERN.search(line):
                    found.append(i)
    except Exception:  # noqa: S110 — silently skip unreadable files
        pass
    return found


def _is_disabled() -> bool:
    disabled = os.environ.get("PINKY_DISABLED_HOOKS", "")
    return Path(__file__).stem in {h.strip() for h in disabled.split(",") if h.strip()}


def main() -> int:
    if _is_disabled():
        return 0
    findings: list[Diagnostic] = [
        at(
            "LATEX",
            "raw LaTeX notation instead of a Unicode symbol",
            filepath,
            line,
            _PATTERN,
            help="replace the command with its Unicode character (e.g. `\\rightarrow` → `→`)",
        )
        for filepath in sys.argv[1:]
        for line in check_file(filepath)
    ]
    emit(
        findings,
        footer="likely source: a local LLM (Gemma/Ollama) falling back to its training "
        "notation on long, freely-composed text",
    )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

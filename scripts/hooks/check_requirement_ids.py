#!/usr/bin/env python3
"""
check_requirement_ids.py — Block requirement ids in any committed text file.

A requirement id (``FR``, ``NFR``, ``ASS``, ``IMP`` or ``LEG``, a chantier number, an index) points to a chantier story that lives outside
the repo and whose requirements are pruned once implemented: in a repo file it is a dead reference,
wherever it sits — ``--help`` text, a string, a comment, a docstring, a test, a Markdown page. The
fix is to delete it and state the behaviour, never to move it elsewhere.

Blocking (exit 1), one ``path:line: id`` line per finding. Every text file pre-commit passes is
scanned as plain text; a file that does not decode as UTF-8 is skipped. The detectors that define
or test this pattern are excluded in the pre-commit configuration, not here.

Stdlib only — this hook is distributed into each consumer repo and runs in its pre-commit
environment.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from _report import Diagnostic, at, emit

# La console Windows (cp1252 par défaut) ne sait pas encoder la sortie ❌.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

_REQUIREMENT_ID = re.compile(r"\b(?:FR|NFR|IMP|ASS|LEG)-\d{4}-\d+\b")


def find_ids(path: Path) -> list[tuple[int, str]]:
    """Every ``(line, id)`` in ``path``, in reading order; empty when it does not decode."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return [
        (number, match.group(0))
        for number, line in enumerate(text.splitlines(), start=1)
        for match in _REQUIREMENT_ID.finditer(line)
    ]


def _is_disabled() -> bool:
    """Whether ``PINKY_DISABLED_HOOKS`` names this hook."""
    disabled = os.environ.get("PINKY_DISABLED_HOOKS", "")
    return Path(__file__).stem in {h.strip() for h in disabled.split(",") if h.strip()}


def main() -> int:
    """Print every requirement id of the files pre-commit passes.

    Returns:
        1 when any file carries one, 0 otherwise.
    """
    if _is_disabled():
        return 0
    findings: list[Diagnostic] = [
        at("REQ-ID", f"requirement id `{found}`", filepath, line, found)
        for filepath in sys.argv[1:]
        for line, found in find_ids(Path(filepath))
    ]
    emit(
        findings,
        footer="the spec an id points to lives outside the repo and is pruned after "
        "implementation: delete the id, state the behaviour",
    )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

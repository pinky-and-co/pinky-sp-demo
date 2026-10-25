#!/usr/bin/env python3
"""
check_narrative_comments.py — Warn on comments and docstrings that narrate history.

A comment clarifies what the code cannot say; a docstring states what the code does. Neither
carries a date, a requirement id, a chantier or a card reference: that is how the code came to be,
and git holds it. A comment naming a file is flagged too — the reference rots on the first move.
A docstring may name a file: reading one is behaviour. A block of more than three full-line
comments is flagged as well: a comment that clarifies fits in three lines; past that it narrates,
or what it explains belongs in a docstring.

Blocking (exit 1 on any finding), one ``path:line: kinds: text`` line per finding. A file name
belongs in a docstring, where reading it is behaviour — that is the escape hatch for ``file ref``.

Python only: ``tokenize`` separates comments from string literals exactly, so a ``#`` inside a
string is never read as a comment. The shebang, PEP 723 ``# /// script`` blocks and every tool
directive of ``tool_directives.py`` are skipped.

Stdlib only — this hook is distributed into each consumer repo and runs in its pre-commit
environment.

Usage (pre-commit local hook):
  entry: python scripts/hooks/check_narrative_comments.py
  language: python
  types: [python]
"""

from __future__ import annotations

import ast
import io
import os
import re
import sys
import tokenize
from pathlib import Path
from typing import NamedTuple

from _report import Diagnostic, at, emit
from tool_directives import DIRECTIVE_RE

# La console Windows (cp1252 par défaut) ne sait pas encoder la sortie ⚠.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

_HISTORY = {
    "date": re.compile(r"\b20\d\d-\d\d-\d\d\b"),
    "requirement id": re.compile(r"\b(?:FR|NFR|IMP|ASS|LEG)-\d{4}-\d+\b"),
    "chantier ref": re.compile(r"\bchantier[- ]?\d{4}\b", re.IGNORECASE),
    "card ref": re.compile(r"\b(?:card|carte)s?\s+`[\w-]+`", re.IGNORECASE),
}
_URL = re.compile(r"\w+://\S+")
_PATH_TOKEN = re.compile(r"[\w./-]+(?![\w./(-])")
_FILE_NAME = re.compile(
    r"[\w.-]+\.(?:py|sh|md|ya?ml|toml|json|js|ts|html|css|sql|tf|txt|cfg|ini|lock)"
)
_DOCUMENTED = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
_MAX_COMMENT_LINES = 3


class Finding(NamedTuple):
    """One narrative line: where it is, what it carries, and its text as written."""

    line: int
    kinds: str
    text: str


def _is_file_ref(token: str) -> bool:
    """A file name with a known extension, a path of two slashes or more, or a directory path."""
    token = token.strip(".")
    if _FILE_NAME.fullmatch(token.rsplit("/", 1)[-1]):
        return True
    return token.count("/") >= 2 or (token.endswith("/") and len(token) > 1)


def _kinds(text: str, *, files: bool) -> list[str]:
    """Kinds of history found in ``text``; empty when clean."""
    kinds = [kind for kind, pattern in _HISTORY.items() if pattern.search(text)]
    if files and any(
        _is_file_ref(tok) for tok in _PATH_TOKEN.findall(_URL.sub("", text))
    ):
        kinds.append("file ref")
    return kinds


def _close_block(block: list[int], kinds_by_line: dict[int, list[str]]) -> None:
    """Flag a run of full-line comments past the limit on its first line, then reset it."""
    if len(block) > _MAX_COMMENT_LINES:
        kinds_by_line.setdefault(block[0], []).append(
            f"long comment ({len(block)} lines)"
        )
    block.clear()


def _comment_findings(source: str) -> list[Finding]:
    """Narrative comments, file references and over-long comment blocks included."""
    kinds_by_line: dict[int, list[str]] = {}
    text_by_line: dict[int, str] = {}
    block: list[int] = []
    in_pep723 = False
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type != tokenize.COMMENT:
            continue
        line, text = tok.start[0], tok.string.strip()
        if text == "# /// script":
            in_pep723 = True
        if (
            in_pep723
            or (line == 1 and text.startswith("#!"))
            or DIRECTIVE_RE.match(text)
        ):
            in_pep723 = in_pep723 and text != "# ///"
            _close_block(block, kinds_by_line)
            continue
        text_by_line[line] = text
        full_line = tok.line.lstrip().startswith("#")
        if not full_line or (block and line != block[-1] + 1):
            _close_block(block, kinds_by_line)
        if full_line:
            block.append(line)
        kinds_by_line.setdefault(line, []).extend(_kinds(text, files=True))
    _close_block(block, kinds_by_line)
    return [
        Finding(line, ", ".join(kinds), text_by_line[line])
        for line, kinds in kinds_by_line.items()
        if kinds
    ]


def _docstring_findings(tree: ast.Module) -> list[Finding]:
    """Narrative docstring lines, file references excluded."""
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, _DOCUMENTED) or not node.body:
            continue
        first = node.body[0]
        if not (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            continue
        for offset, text in enumerate(first.value.value.splitlines()):
            kinds = ", ".join(_kinds(text, files=False))
            if kinds:
                findings.append(Finding(first.lineno + offset, kinds, text.strip()))
    return findings


def check_file(path: Path) -> list[Finding]:
    """Narrative lines of one Python file, comments and docstrings, sorted by line.

    Args:
        path: The file to scan.

    Returns:
        One finding per narrative line; empty when the file is clean or does not parse.
    """
    try:
        source = path.read_text(encoding="utf-8")
        findings = _comment_findings(source) + _docstring_findings(ast.parse(source))
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError, tokenize.TokenError):
        return []
    return sorted(findings)


def _is_disabled() -> bool:
    """Whether ``PINKY_DISABLED_HOOKS`` names this hook."""
    disabled = os.environ.get("PINKY_DISABLED_HOOKS", "")
    return Path(__file__).stem in {h.strip() for h in disabled.split(",") if h.strip()}


def main() -> int:
    """Print every narrative line of the files pre-commit passes; block on any finding.

    Returns:
        1 when at least one narrative line was found, 0 otherwise.
    """
    if _is_disabled():
        return 0
    findings: list[Diagnostic] = [
        at(
            "NARRATIVE",
            f"narrated history ({finding.kinds})",
            filepath,
            finding.line,
            finding.text,
        )
        for filepath in sys.argv[1:]
        for finding in check_file(Path(filepath))
    ]
    emit(
        findings,
        footer="a comment clarifies, a docstring states behaviour; git holds the history",
    )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

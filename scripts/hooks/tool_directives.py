#!/usr/bin/env python3
"""
tool_directives.py — The inline directives the pinky toolchain reads, in one table.

A directive is a comment a tool acts on — ``# noqa: E402``, ``# type: ignore[type-arg]``,
``# nosec B608`` — so deleting one re-opens the finding it silenced. Comment-cleaning tools keep
every comment :data:`DIRECTIVE_RE` matches; ``pinky directives <code>`` (or this script run
directly) prints the line to paste for an error code a tool reported.

Each entry names the pre-commit hook ids that run its tool; a test fails when a hook of the
pre-commit configs is neither covered here nor listed in :data:`NO_DIRECTIVE_HOOKS`. Tools outside
pre-commit (coverage, the editor's type checker) are kept too: keeping a directive nobody reads
costs nothing, deleting one a tool reads breaks a gate.

Stdlib only — distributed into each consumer repo next to the hooks that import it.

Usage:
  python scripts/hooks/tool_directives.py            # the whole table
  python scripts/hooks/tool_directives.py E402       # the line to paste for one code
"""

from __future__ import annotations

import re
import sys
from typing import NamedTuple


class Directive(NamedTuple):
    """How one tool is silenced inline: the hooks that run it, what it reads, how to write it."""

    tool: str
    hook_ids: list[str]
    marker: str
    syntax: str
    example: str
    codes: str


DIRECTIVES: list[Directive] = [
    Directive(
        "ruff",
        ["ruff-check"],
        r"noqa\b|ruff:\s*noqa",
        "# noqa: {code}",
        "import setup  # noqa: E402",
        r"(?!DAR)[A-Z]{1,4}\d{2,4}",
    ),
    Directive(
        "ruff format",
        ["ruff-format"],
        r"fmt:\s*(?:off|on|skip)",
        "# fmt: skip",
        "table = [1,0 , 0,1]  # fmt: skip",
        "",
    ),
    Directive(
        "ruff isort", [], r"isort:", "# isort: skip", "import late  # isort: skip", ""
    ),
    Directive(
        "mypy",
        ["mypy"],
        r"type:\s*ignore|mypy:",
        "# type: ignore[{code}]",
        "rows: list[dict] = []  # type: ignore[type-arg]",
        r"[a-z]+(?:-[a-z]+)*",
    ),
    Directive(
        "bandit",
        ["bandit"],
        r"nosec\b",
        "# nosec {code}",
        'query = f"SELECT {col}"  # nosec B608',
        r"B\d{3}",
    ),
    Directive(
        "darglint",
        ["darglint"],
        r"noqa\b",
        "# noqa: {code}  (a line of the docstring)",
        "a docstring line:  # noqa: DAR101 arg_name",
        r"DAR\d{3}",
    ),
    Directive(
        "gitleaks",
        ["gitleaks"],
        r"gitleaks:allow",
        "# gitleaks:allow",
        'TOKEN = "fake-test-token"  # gitleaks:allow',
        "",
    ),
    Directive(
        "detect-secrets",
        ["detect-secrets"],
        r"pragma:\s*allowlist",
        "# pragma: allowlist secret",
        'password = "example"  # pragma: allowlist secret',
        "",
    ),
    Directive(
        "pinky snowpark",
        ["check-snowpark-api"],
        r"pinky:",
        "# pinky: {code}",
        'session.sql("SELECT 1")  # pinky: SNOWPARK-API',
        r"SNOWPARK-(?:API|SQL-INLINE)",
    ),
    Directive(
        "coverage",
        [],
        r"pragma:",
        "# pragma: no cover",
        "if TYPE_CHECKING:  # pragma: no cover",
        "",
    ),
    Directive(
        "pyright",
        [],
        r"pyright:",
        "# pyright: ignore[{code}]",
        "value = loader.load()  # pyright: ignore[reportAttributeAccessIssue]",
        r"report[A-Z]\w+",
    ),
    Directive(
        "pylint",
        [],
        r"pylint:",
        "# pylint: disable={code}",
        "import os  # pylint: disable=unused-import",
        "",
    ),
    Directive(
        "python", [], r"-\*-", "# -*- coding: utf-8 -*-", "# -*- coding: utf-8 -*-", ""
    ),
]

NO_DIRECTIVE_HOOKS: list[str] = [
    "trailing-whitespace",
    "end-of-file-fixer",
    "check-yaml",
    "check-toml",
    "check-merge-conflict",
    "debug-statements",
    "generate-docs",
    "run-tests",
    "mdformat",
    "check-zws",
    "check-latex-notation",
    "check-forbidden-keywords",
    "check-narrative-comments",
    "check-requirement-ids",
    "commit-msg-format",
    "validate-frontmatter",
    "validate-plugins-strict",
    "check-vendor-checksum",
    "interrogate",
    "check-typed-api",
    "check-weak-assertions",
    "js-file-size",
    "js-structure",
    "html-inline-js",
    "js-engine-sync",
]

DIRECTIVE_RE = re.compile(
    r"#\s*(?:" + "|".join(f"(?:{d.marker})" for d in DIRECTIVES) + ")"
)


def lookup(code: str) -> list[Directive]:
    """The directives whose tool reports this code.

    Args:
        code: An error code as a tool printed it — ``E402``, ``[type-arg]``, ``B608``.

    Returns:
        Every matching directive, in table order; several when tools share a code shape.
    """
    bare = code.strip().strip("[]")
    return [d for d in DIRECTIVES if d.codes and re.fullmatch(d.codes, bare)]


def format_lookup(code: str | None) -> list[str]:
    """The cheat sheet, or the line to paste for one code.

    Args:
        code: An error code, or None for the whole table.

    Returns:
        The report lines.
    """
    if not code:
        return [f"{d.tool:<15} {d.syntax:<42} {d.example}" for d in DIRECTIVES]
    bare = code.strip().strip("[]")
    matches = lookup(code)
    if not matches:
        return [f"no known tool reports {bare!r} — `pinky directives` lists them all"]
    return [f"{d.tool:<15} {d.syntax.format(code=bare)}" for d in matches]


def main(argv: list[str]) -> int:
    """Print the table, or the directive for the code given.

    Args:
        argv: At most one error code.

    Returns:
        1 when a code was given and no tool reports it, 0 otherwise.
    """
    code = argv[0] if argv else None
    print("\n".join(format_lookup(code)))
    return 1 if code and not lookup(code) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

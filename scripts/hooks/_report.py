"""_report.py — the one ruff-style renderer the hygiene hooks print their findings through.

Findings are grouped by file (directory dimmed, file name bold), each one a code, a message, a
`--> path:line:col` locator, the offending source line with a `^^^` underline, and an optional
`help:` line. Color follows the usual contract — `NO_COLOR` off, `FORCE_COLOR` /
`CLICOLOR_FORCE` on, otherwise on a terminal only — so a pipe or a log stays plain.

Standalone on purpose: distributed next to the hooks, it imports nothing from `setup`.
"""

import os
import re
import sys
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

_RESET = "\x1b[0m"
_BOLD = "1"
_DIM = "2"
_RED = "1;31"
_YELLOW = "1;33"
_BLUE = "1;34"
_CYAN = "1;36"

_SOURCE_MAX_CHARS = 160
_INDENT = "  "


@dataclass(frozen=True)
class Diagnostic:
    """One finding. `line` / `col` are 1-based; without a `line` the finding is about the whole file."""

    code: str
    message: str
    path: str
    line: int | None = None
    col: int = 1
    width: int = 1
    help: str | None = None
    severity: Literal["error", "warning"] = "error"


def use_color(
    stream: TextIO | None = None, environ: Mapping[str, str] | None = None
) -> bool:
    """Whether to emit ANSI codes on `stream` (stdout by default)."""
    out = stream if stream is not None else sys.stdout
    env = os.environ if environ is None else environ
    if env.get("NO_COLOR"):
        return False
    if env.get("FORCE_COLOR") or env.get("CLICOLOR_FORCE"):
        return True
    return out.isatty() and env.get("TERM") != "dumb"


def display(path: Path | str) -> str:
    """`path` relative to the working directory when it sits under it, as given otherwise."""
    try:
        return Path(path).resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(path)


def _paint(text: str, code: str, color: bool) -> str:
    return f"\x1b[{code}m{text}{_RESET}" if color else text


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _source_line(path: str, line: int, cache: dict[str, list[str]]) -> str | None:
    """Line `line` of `path` with tabs expanded and a long line cut, or None when unreadable."""
    if path not in cache:
        try:
            cache[path] = Path(path).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            cache[path] = []
    lines = cache[path]
    if not 1 <= line <= len(lines):
        return None
    text = lines[line - 1].expandtabs(4)
    return (
        text if len(text) <= _SOURCE_MAX_CHARS else text[: _SOURCE_MAX_CHARS - 1] + "…"
    )


def at(
    code: str,
    message: str,
    path: Path | str,
    line: int,
    needle: str | re.Pattern[str] | None = None,
    *,
    help: str | None = None,
    severity: Literal["error", "warning"] = "error",
) -> Diagnostic:
    """A finding on line `line` of `path`, underlining `needle` (text matched case-insensitively,
    or a pattern) — the whole line when `needle` is absent or not on it."""
    where = display(path)
    source = _source_line(str(path), line, {})
    col, width = 1, 1
    if source is not None:
        col, width = len(source) - len(source.lstrip()) + 1, len(source.strip()) or 1
        if isinstance(needle, str) and needle.lower() in source.lower():
            col, width = source.lower().index(needle.lower()) + 1, len(needle)
        elif isinstance(needle, re.Pattern) and (found := needle.search(source)):
            col, width = found.start() + 1, max(1, len(found.group(0)))
    return Diagnostic(code, message, where, line, col, width, help, severity)


def _help_lines(text: str, lead: str) -> list[str]:
    """`text` as `lead`-prefixed lines, continuation lines aligned under the first."""
    first, *rest = text.split("\n")
    return [lead + first] + [
        " " * len(re.sub(r"\x1b\[[0-9;]*m", "", lead)) + r for r in rest
    ]


def _render_one(d: Diagnostic, cache: dict[str, list[str]], color: bool) -> list[str]:
    accent = _RED if d.severity == "error" else _YELLOW
    number = str(d.line) if d.line else ""
    pad = " " * len(number)
    gutter = _paint("|", _BLUE, color)
    where = d.path if not d.line else f"{d.path}:{d.line}:{d.col}"
    out = [
        f"{_INDENT}{_paint(d.code, accent, color)} {_paint(d.message, _BOLD, color)}",
        f"{_INDENT}{pad}{_paint('-->', _BLUE, color)} {where}",
    ]
    source = _source_line(d.path, d.line, cache) if d.line else None
    if source is not None:
        start = min(max(d.col - 1, 0), len(source))
        underline = " " * start + "^" * max(1, min(d.width, len(source) - start))
        out += [
            f"{_INDENT}{pad} {gutter}",
            f"{_INDENT}{_paint(number, _BLUE, color)} {gutter} {source}",
            f"{_INDENT}{pad} {gutter} {_paint(underline, accent, color)}",
        ]
        if d.help:
            out.append(f"{_INDENT}{pad} {gutter}")
    if d.help:
        lead = f"{_INDENT}{pad} {_paint('=', _BLUE, color)} {_paint('help:', _CYAN, color)} "
        out += _help_lines(d.help, lead)
    return out


def _file_header(path: str, count: int, color: bool) -> str:
    folder, sep, name = path.rpartition("/")
    label = _paint(folder + sep, _DIM, color) + _paint(name, _BOLD, color)
    return f"{label} {_paint(f'({count})', _DIM, color)}"


def _summary(diagnostics: list[Diagnostic], color: bool) -> str:
    errors = sum(d.severity == "error" for d in diagnostics)
    warnings = len(diagnostics) - errors
    files = len({d.path for d in diagnostics})
    parts = []
    if errors:
        parts.append(_plural(errors, "error"))
    if warnings:
        parts.append(_plural(warnings, "warning"))
    text = f"Found {' and '.join(parts)} in {_plural(files, 'file')}."
    return _paint(text, _RED if errors else _YELLOW, color)


def render(
    diagnostics: list[Diagnostic], *, color: bool = False, footer: str | None = None
) -> str:
    """The grouped report of `diagnostics`, `""` when there are none. `footer` is a hook-wide hint."""
    if not diagnostics:
        return ""
    by_file: dict[str, list[Diagnostic]] = defaultdict(list)
    for d in diagnostics:
        by_file[d.path].append(d)
    cache: dict[str, list[str]] = {}
    blocks = []
    for path in sorted(by_file):
        block = [_file_header(path, len(by_file[path]), color)]
        for d in sorted(by_file[path], key=lambda d: (d.line or 0, d.col)):
            block.append("")
            block += _render_one(d, cache, color)
        blocks.append("\n".join(block))
    tail = _summary(diagnostics, color)
    if footer:
        tail += "\n" + "\n".join(
            _help_lines(footer, f"{_paint('help:', _CYAN, color)} ")
        )
    return "\n\n".join(blocks) + "\n\n" + tail


def emit(diagnostics: list[Diagnostic], *, footer: str | None = None) -> None:
    """Print the report of `diagnostics` to stdout, coloring it when the stream allows."""
    text = render(diagnostics, color=use_color(), footer=footer)
    if text:
        print(text)

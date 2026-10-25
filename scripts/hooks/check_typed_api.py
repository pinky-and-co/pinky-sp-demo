#!/usr/bin/env python3
"""
check_typed_api.py — Block raw composite type annotations in public APIs.

Blocked patterns in public function signatures and module-level annotations:
  - dict[..., dict/list/tuple/set[...]]  → use a Pydantic model
  - tuple[...]                            → use a dataclass or Pydantic model
  - set[...]                              → use list[T] or a typed model

"Public" = name does not start with _.
Handles both evaluated annotations and PEP-563 (from __future__ import annotations).

Usage (pre-commit local hook):
  entry: python scripts/hooks/check_typed_api.py
  language: system
  types: [python]
  files: ^src/
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

from _report import Diagnostic, at, emit

# Script autonome, n'importe pas `setup` : la console Windows (cp1252) ne sait pas encoder ✓/⚠.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

_COMPOSITE: frozenset[str] = frozenset({"dict", "list", "tuple", "set"})
_ALWAYS_BLOCKED: frozenset[str] = frozenset({"tuple", "set"})


def _subscript_name(node: ast.expr | None) -> str | None:
    """Return the base name if *node* is a subscript, e.g. 'dict' for dict[str, Any]."""
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        return node.value.id
    return None


def _resolve(node: ast.expr | None) -> ast.expr | None:
    """Unwrap PEP-563 string annotations into a real AST node."""
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            return ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return None
    return node


def _violation(node: ast.expr | None) -> str | None:
    """Return a human-readable reason if *node* is a blocked annotation, else None."""
    node = _resolve(node)
    if node is None:
        return None
    name = _subscript_name(node)
    if name is None:
        return None
    if name in _ALWAYS_BLOCKED:
        return f"{name}[...] — use a dataclass or Pydantic model"
    if name == "dict" and isinstance(node, ast.Subscript):
        slc = node.slice
        args: list[ast.expr] = slc.elts if isinstance(slc, ast.Tuple) else [slc]
        if len(args) >= 2:
            inner = _subscript_name(_resolve(args[1]))
            if inner in _COMPOSITE:
                return f"dict[..., {inner}[...]] — use a Pydantic model"
    return None


class _Visitor(ast.NodeVisitor):
    """Collects (lineno, message) for each blocked raw composite annotation in public API surface."""

    def __init__(self) -> None:
        self.violations: list[tuple[int, str]] = []
        self._private_depth: int = 0
        self._function_depth: int = 0

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Track whether we're nested inside a private (`_`-prefixed) class, whose members are exempt."""
        if node.name.startswith("_"):
            self._private_depth += 1
            self.generic_visit(node)
            self._private_depth -= 1
        else:
            self.generic_visit(node)

    def _check_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Flag blocked annotations on a public function's parameters and return type."""
        self._function_depth += 1
        if node.name.startswith("_") or self._private_depth:
            self.generic_visit(node)
            self._function_depth -= 1
            return
        all_args = node.args.args + node.args.posonlyargs + node.args.kwonlyargs
        for arg in all_args:
            reason = _violation(arg.annotation)
            if reason:
                line = getattr(arg, "lineno", node.lineno)
                self.violations.append((line, f"param `{arg.arg}`: {reason}"))
        reason = _violation(node.returns)
        if reason:
            self.violations.append((node.lineno, f"return type: {reason}"))
        self.generic_visit(node)
        self._function_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # type: ignore[override]
        """Delegate to `_check_function`."""
        self._check_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # type: ignore[override]
        """Delegate to `_check_function`."""
        self._check_function(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Flag a blocked annotation on a module-level, public, non-`_`-prefixed assignment."""
        if self._private_depth or self._function_depth:
            return
        if isinstance(node.target, ast.Name) and not node.target.id.startswith("_"):
            reason = _violation(node.annotation)
            if reason:
                self.violations.append((node.lineno, f"`{node.target.id}`: {reason}"))


def check_file(path: Path) -> list[tuple[int, str]]:
    """(line, message) for each blocked raw composite annotation in `path`; [] on parse/read failure."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return []
    visitor = _Visitor()
    visitor.visit(tree)
    return visitor.violations


def _is_disabled() -> bool:
    """True if this hook's filename stem is listed in `PINKY_DISABLED_HOOKS` (comma-separated)."""
    disabled = os.environ.get("PINKY_DISABLED_HOOKS", "")
    return Path(__file__).stem in {h.strip() for h in disabled.split(",") if h.strip()}


def main() -> int:
    """Fail if any CLI argument's public API uses a blocked raw composite annotation."""
    if _is_disabled():
        return 0
    findings: list[Diagnostic] = [
        at("TYPED-API", reason, filepath, line)
        for filepath in sys.argv[1:]
        for line, reason in check_file(Path(filepath))
    ]
    emit(
        findings,
        footer="replace raw dict/tuple/set annotations with Pydantic models or dataclasses",
    )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

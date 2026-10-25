#!/usr/bin/env python3
"""
check_weak_assertions.py — Ratchet against weak assertions on generated output.

A test that only asserts a *fragment* of a generator's output (`assert "MY_DAG" in clause`)
passes on the correct output AND on a wrong one — it freezes the bug in place. This hook keeps
that pattern from creeping back in.

It is a RATCHET, not an exhaustiveness guarantee. It flags only the narrow pattern below, so it
stays at ~0 flags on a clean repo and never cries wolf (a hook one learns to `--no-verify` is
worse than no hook):

  Flag a generator ONLY when ALL hold:
    1. an assert of the form  `assert "<str literal>" in <Y>`  (operator `in`, NOT `not in` —
       a negative assertion genuinely proves an absence);
    2. `<Y>` traces back to a generator — a call to a function whose name (stripped of leading
       underscores) matches the generator convention, directly or via a variable assigned from
       such a call;
    3. that generator has NO equality oracle anywhere in the repo's tests/ tree — neither an inline
       `assert <gen(...)> == <literal>` nor an oracle routed through a local helper whose body
       does the `==` (e.g. `_assert_golden("...", html)` where `html = generate_html(...)`).

The oracle need not sit in the SAME file as the fragment: at least one test needs a whole-output
oracle, **repo-wide** — a fragment in test_web_precommit.py is legitimately
covered by the oracle in test_precommit_config_oracle.py. pre-commit hands the hook only the
CHANGED files, so main() builds the covered set by scanning every `.py` under the tests/ root(s)
of the passed paths, not just argv. check_file() stays per-file (the testable unit of the AST
scan); main() is the layer that applies the repo-wide covered set.

Generators are matched BY NAME only: a function that builds output but is named without a
convention prefix/suffix escapes the ratchet — not blocked, merely unguarded. The intended fix
is to name it as a generator, not to widen the matcher — widening to "returns markup" would
reopen the false positives a name-based match avoids.

Usage (pre-commit local hook):
  entry: python scripts/hooks/check_weak_assertions.py
  language: system
  types: [python]
  files: ^tests/
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

# Convention de nommage des générateurs, appariée sur name.lstrip("_") pour couvrir aussi les
# variantes privées (`_build_ddl`, `_render_x`).
_SUFFIXES: tuple[str, ...] = ("_sql", "_ddl", "_clause", "_statement", "_query")
_PREFIXES: tuple[str, ...] = ("build_", "render_", "generate_")


def _is_generator_name(name: str) -> bool:
    """True if `name`, leading underscores stripped, matches the generator naming convention."""
    bare = name.lstrip("_")
    return bare.startswith(_PREFIXES) or bare.endswith(_SUFFIXES)


def _call_name(func: ast.expr) -> str | None:
    """The callee's bare name: `build_x` for both `build_x(...)` and `obj.build_x(...)`."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _gen_from_expr(expr: ast.expr, var_to_gen: dict[str, str]) -> str | None:
    """Generator name behind *expr*: a direct generator call, or a variable bound to one."""
    if isinstance(expr, ast.Call):
        name = _call_name(expr.func)
        if name and _is_generator_name(name):
            return name
        return None
    if isinstance(expr, ast.Name):
        return var_to_gen.get(expr.id)
    return None


def _build_var_to_gen(scope: ast.AST) -> dict[str, str]:
    """Map every `var = <generator call>` in *scope* to the generator's name."""
    mapping: dict[str, str] = {}
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            name = _call_name(node.value.func)
            if name and _is_generator_name(name):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        mapping[target.id] = name
    return mapping


def _has_eq(node: ast.AST) -> bool:
    """True if an equality comparison (`==`) appears anywhere within `node`."""
    return any(
        isinstance(n, ast.Compare) and any(isinstance(op, ast.Eq) for op in n.ops)
        for n in ast.walk(node)
    )


def _collect_oracle_helpers(tree: ast.AST) -> set[str]:
    """Module-level functions whose body performs an equality check.

    A call to one of these, fed a generator's output, stands in for an inline `==` oracle.
    Deliberately permissive — a false *exemption* only misses a flag; a false *positive*
    disables the ratchet, which is worse.
    """
    helpers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _has_eq(node):
            helpers.add(node.name)
    return helpers


def _iter_compares(test: ast.expr) -> list[ast.Compare]:
    """The Compare nodes of an assert test: the bare compare, or the members of a `and`/`or`."""
    if isinstance(test, ast.Compare):
        return [test]
    if isinstance(test, ast.BoolOp):
        return [v for v in test.values if isinstance(v, ast.Compare)]
    return []


def _scan_scope(
    scope: ast.AST,
    var_to_gen: dict[str, str],
    oracle_helpers: set[str],
    weak: dict[tuple[str, int], None],
    covered: set[str],
) -> None:
    """Walk `scope` for weak `in`-fragment asserts and `==` oracles, updating `weak`/`covered` in place."""
    for node in ast.walk(scope):
        if isinstance(node, ast.Assert):
            for cmp in _iter_compares(node.test):
                if len(cmp.ops) != 1:
                    continue
                op, right = cmp.ops[0], cmp.comparators[0]
                if isinstance(op, ast.In) and _is_str_literal(cmp.left):
                    gen = _gen_from_expr(right, var_to_gen)
                    if gen:
                        weak[(gen, node.lineno)] = None
                elif isinstance(op, ast.Eq):
                    gen = _gen_from_expr(cmp.left, var_to_gen) or _gen_from_expr(
                        right, var_to_gen
                    )
                    if gen:
                        covered.add(gen)
        elif isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in oracle_helpers:
                for arg in node.args:
                    gen = _gen_from_expr(arg, var_to_gen)
                    if gen:
                        covered.add(gen)


def _is_str_literal(node: ast.expr) -> bool:
    """True if `node` is a string constant."""
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _scan(path: Path) -> tuple[dict[tuple[str, int], None], set[str]]:
    """Parse *path* into its (weak fragment sites, generators with an equality oracle).

    The two halves stay separate so callers can compose them across files: check_file() subtracts
    covered from weak within the one file; main() applies a repo-wide covered set built from many.
    """
    # Ce hook a des copies distribuées ailleurs, jamais dans le dossier de tests : garde-fou
    # pour une exécution manuelle en dehors de pre-commit.
    if "scripts/hooks" in path.as_posix():
        return {}, set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return {}, set()
    oracle_helpers = _collect_oracle_helpers(tree)
    weak: dict[tuple[str, int], None] = {}
    covered: set[str] = set()
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _scan_scope(fn, _build_var_to_gen(fn), oracle_helpers, weak, covered)
    return weak, covered


def check_file(path: Path) -> list[tuple[int, str]]:
    """Per-file flags: weak fragment sites whose generator has no oracle IN THIS FILE.

    The testable unit of the hook — a single file's behaviour in isolation. Repo-wide oracle
    resolution (a fragment covered by an oracle in a sibling file) is main()'s job, not this one's.
    """
    weak, covered = _scan(path)
    return sorted((line, gen) for (gen, line) in weak if gen not in covered)


def _is_disabled() -> bool:
    """True if this hook's filename stem is listed in `PINKY_DISABLED_HOOKS` (comma-separated)."""
    disabled = os.environ.get("PINKY_DISABLED_HOOKS", "")
    return Path(__file__).stem in {h.strip() for h in disabled.split(",") if h.strip()}


def _tests_roots(paths: list[str]) -> set[Path]:
    """The `tests/` directory ancestor of each passed path (empty when a path has none)."""
    roots: set[Path] = set()
    for p in paths:
        for parent in Path(p).resolve().parents:
            if parent.name == "tests":
                roots.add(parent)
                break
    return roots


def _repo_covered(paths: list[str]) -> set[str]:
    """Generators with an equality oracle anywhere under the tests/ root(s) of *paths*.

    pre-commit hands main() only the CHANGED files, but an oracle for a fragment's generator may
    sit in an unchanged sibling — so the covered set is built from the whole tests/ tree, not argv.
    Empty when no path lives under a `tests/` dir (a manual run on a stray file → per-file fallback).
    """
    covered: set[str] = set()
    for root in _tests_roots(paths):
        for f in root.rglob("*.py"):
            covered |= _scan(f)[1]
    return covered


def main() -> int:
    """Fail on a weak `in`-fragment assert whose generator has no equality oracle anywhere under tests/."""
    if _is_disabled():
        return 0
    paths = sys.argv[1:]
    repo_covered = _repo_covered(paths)
    findings: list[Diagnostic] = []
    for filepath in paths:
        for line, gen in check_file(Path(filepath)):
            if gen in repo_covered:
                continue  # oracle ailleurs : ce fragment est de la documentation, pas un trou de couverture
            findings.append(
                at(
                    "WEAK-ASSERT",
                    f"fragment `in` assertion on `{gen}` with no equality oracle for the whole output",
                    filepath,
                    line,
                )
            )
    emit(
        findings,
        footer="add one `assert <generator(...)> == <full expected output>` in the same test "
        "file (tests.md § generator oracle); fragment asserts stay welcome alongside it",
    )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

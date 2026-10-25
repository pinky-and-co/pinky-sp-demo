#!/usr/bin/env python3
"""
generate_ci_badges.py — Generate CI quality badges for docs/reference/generated/.

Two badges:
  hooks_badge.svg  — count of custom pre-commit hooks (repo: local entries)
  noqa_badge.svg   — count of all lint suppressions (# noqa: + # pinky:) in src/

Usage:
  python scripts/hooks/generate_ci_badges.py --hooks
  python scripts/hooks/generate_ci_badges.py --noqa
  python scripts/hooks/generate_ci_badges.py          # both
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Script autonome, n'importe pas `setup` : la console Windows (cp1252) ne sait pas encoder ✓/⚠.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# ── SVG ──────────────────────────────────────────────────────────────────────

_CHAR_W = 6.5  # Verdana 11px approximate glyph width
_PAD = 9  # horizontal padding each side


def _svg(label: str, message: str, color: str, title: str = "") -> str:
    """Shields.io-style flat badge: `label` on a grey box, `message` on a `color` box."""
    lw = int(len(label) * _CHAR_W + _PAD * 2)
    mw = int(len(message) * _CHAR_W + _PAD * 2)
    tw = lw + mw
    lx, mx = lw // 2, lw + mw // 2
    title_el = f"  <title>{title}</title>\n" if title else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{tw}" height="20">\n'
        f"{title_el}"
        f'  <rect width="{tw}" height="20" rx="3" fill="#555"/>\n'
        f'  <rect x="{lw}" width="{mw}" height="20" rx="3" fill="{color}"/>\n'
        f'  <rect x="{lw}" width="4" height="20" fill="{color}"/>\n'
        f'  <g fill="#fff" text-anchor="middle"'
        f' font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">\n'
        f'    <text x="{lx}" y="15" fill="#010101" fill-opacity=".3">{label}</text>\n'
        f'    <text x="{lx}" y="14">{label}</text>\n'
        f'    <text x="{mx}" y="15" fill="#010101" fill-opacity=".3">{message}</text>\n'
        f'    <text x="{mx}" y="14">{message}</text>\n'
        f"  </g>\n"
        f"</svg>\n"
    )


# ── Hooks badge ───────────────────────────────────────────────────────────────


def _count_local_hooks(config: Path) -> tuple[int, list[str]]:
    """Return (count, [hook ids]) for all repo:local hooks."""
    if not config.exists():
        return 0, []
    text = config.read_text(encoding="utf-8")
    in_local = False
    ids: list[str] = []
    for line in text.splitlines():
        if re.match(r"\s*-\s+repo:\s+local\s*$", line):
            in_local = True
        elif re.match(r"\s*-\s+repo:", line):
            in_local = False
        if in_local:
            m = re.match(r"\s+-\s+id:\s+(\S+)", line)
            if m:
                ids.append(m.group(1))
    return len(ids), ids


def generate_hooks_badge(root: Path) -> None:
    """Write `docs/reference/generated/hooks_badge.svg`, counting `repo: local` hooks in `.pre-commit-config.yaml`."""
    out = root / "docs" / "reference" / "generated" / "hooks_badge.svg"
    out.parent.mkdir(parents=True, exist_ok=True)
    n, ids = _count_local_hooks(root / ".pre-commit-config.yaml")
    detail = " · ".join(ids) if ids else "none"
    svg = _svg("hooks", str(n), "#007ec6", title=detail)
    out.write_text(svg, encoding="utf-8")
    print(f"✓ hooks_badge.svg — {n} local hooks ({detail})")


# ── Noqa badge ────────────────────────────────────────────────────────────────

# Exclut la prose de justification (minuscule) après le marqueur : les codes sont toujours en majuscules.
_SUPPRESS_RE = re.compile(
    r"#\s*(?:noqa|pinky):\s*([A-Z][A-Z0-9-]*(?:\s*,\s*[A-Z][A-Z0-9-]*)*)"
)


def _count_noqa(src: Path) -> dict[str, int]:
    """Occurrences of each `noqa`/`pinky` suppression code across every `.py` file under `src`."""
    counts: dict[str, int] = {}
    if not src.exists():
        return counts
    for py in src.rglob("*.py"):
        for line in py.read_text(encoding="utf-8", errors="ignore").splitlines():
            for m in _SUPPRESS_RE.finditer(line):
                for code in re.split(r"\s*,\s*", m.group(1).strip()):
                    counts[code] = counts.get(code, 0) + 1
    return counts


def _noqa_color(total: int) -> str:
    """Badge color for `total` suppressions: green at 0, yellow up to 3, red beyond."""
    if total == 0:
        return "#4c1"  # green
    if total <= 3:
        return "#dfb317"  # yellow
    return "#e05d44"  # red


def generate_noqa_badge(root: Path) -> None:
    """Write `docs/reference/generated/noqa_badge.svg` with the total suppression count under `root/src`."""
    out = root / "docs" / "reference" / "generated" / "noqa_badge.svg"
    out.parent.mkdir(parents=True, exist_ok=True)
    counts = _count_noqa(root / "src")
    total = sum(counts.values())
    detail = " · ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "none"
    svg = _svg(
        "noqa",
        str(total),
        _noqa_color(total),
        title=f"lint suppressions (noqa + pinky) — {detail}",
    )
    out.write_text(svg, encoding="utf-8")
    print(f"✓ noqa_badge.svg — {total} ({detail})")


# ── CLI ───────────────────────────────────────────────────────────────────────


def _is_disabled() -> bool:
    """True if this hook's filename stem is listed in `PINKY_DISABLED_HOOKS` (comma-separated)."""
    disabled = os.environ.get("PINKY_DISABLED_HOOKS", "")
    return Path(__file__).stem in {h.strip() for h in disabled.split(",") if h.strip()}


def main() -> int:
    """Generate the hooks badge, the noqa badge, or both if neither flag is given; always returns 0."""
    if _is_disabled():
        return 0
    args = sys.argv[1:]
    root = Path.cwd()
    do_hooks = "--hooks" in args or not args
    do_noqa = "--noqa" in args or not args
    if do_hooks:
        generate_hooks_badge(root)
    if do_noqa:
        generate_noqa_badge(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())

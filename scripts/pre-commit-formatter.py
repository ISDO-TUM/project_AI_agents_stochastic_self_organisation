#!/usr/bin/env python3
"""
Runs pre-commit and reformats its output for a clean, coloured terminal experience.

Captures pre-commit's verbose output and shows only:
  - A one-line pass / fail / skipped status per hook
  - The actual error output (and nothing else) for failed hooks
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

# ── Colour helpers ─────────────────────────────────────────────────────────────
_USE_COLOUR = sys.stdout.isatty()


def _c(*codes: int) -> str:
    return f"\033[{';'.join(map(str, codes))}m" if _USE_COLOUR else ""


RESET = _c(0)
BOLD = _c(1)
DIM = _c(2)
RED = _c(31)
GREEN = _c(32)
YELLOW = _c(33)
CYAN = _c(36)
GRAY = _c(90)

# ── Output parsing ─────────────────────────────────────────────────────────────
# pre-commit formats each hook result as:
#   "Hook Name..........Passed|Failed|(no files to check)Skipped"
_HOOK_RE = re.compile(r"^([A-Za-z].+?)\.{3,}(.*?)$")

_META_PREFIXES = ("- hook id:", "- exit code:", "- duration:")


def _parse(raw: str) -> list[tuple[str, str, list[str], bool]]:
    """Return (name, status, error_lines, was_auto_fixed) for every hook."""
    lines = raw.splitlines()
    results: list[tuple[str, str, list[str], bool]] = []
    i = 0
    while i < len(lines):
        m = _HOOK_RE.match(lines[i])
        if not m:
            i += 1
            continue

        name = m.group(1).rstrip()
        tail = m.group(2).strip()

        if "Passed" in tail:
            status = "passed"
        elif "Failed" in tail:
            status = "failed"
        elif "Skipped" in tail:
            status = "skipped"
        else:
            i += 1
            continue

        error_lines: list[str] = []
        was_auto_fixed = False

        if status == "failed":
            j = i + 1
            while j < len(lines) and not _HOOK_RE.match(lines[j]):
                line = lines[j]
                if line == "- files were modified by this hook":
                    was_auto_fixed = True
                elif not any(line.startswith(p) for p in _META_PREFIXES):
                    error_lines.append(line)
                j += 1

            # Strip surrounding blank lines
            while error_lines and not error_lines[0].strip():
                error_lines.pop(0)
            while error_lines and not error_lines[-1].strip():
                error_lines.pop()

            i = j
        else:
            i += 1

        results.append((name, status, error_lines, was_auto_fixed))

    return results


# ── Entry point ────────────────────────────────────────────────────────────────
def _find_uv() -> str:
    """Return the path to uv, checking common install locations as a fallback."""
    import shutil

    if found := shutil.which("uv"):
        return found
    home = os.path.expanduser("~")
    for candidate in (
        os.path.join(home, ".local", "bin", "uv"),
        os.path.join(home, ".cargo", "bin", "uv"),
    ):
        if os.path.isfile(candidate):
            return candidate
    return "uv"  # let the OS surface the error


def _fallback(raw: str, returncode: int) -> None:
    """Last resort: dump raw pre-commit output and exit."""
    if raw.strip():
        print(raw, end="")
    else:
        print(f"{RED}{BOLD}Pre-commit checks failed (no output captured).{RESET}")
    sys.exit(returncode)


def main() -> None:
    try:
        repo_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True
        ).strip()
    except Exception as exc:  # noqa: BLE001
        print(f"{RED}{BOLD}pre-commit: could not locate repo root:{RESET} {exc}")
        sys.exit(1)

    uv = _find_uv()

    try:
        proc = subprocess.run(
            [uv, "run", "pre-commit", "run", "--hook-stage=pre-commit", *sys.argv[1:]],
            cwd=os.path.join(repo_root, "api"),
            capture_output=True,
            text=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"{RED}{BOLD}pre-commit: failed to run checks:{RESET} {exc}")
        sys.exit(1)

    results = _parse(proc.stdout + proc.stderr)

    if not results:
        _fallback(proc.stdout + proc.stderr, proc.returncode)

    # ── Header ──────────────────────────────────────────────────────────────────
    print(f"\n  {BOLD}{CYAN}Pre-commit checks{RESET}\n")

    # ── One line per hook ────────────────────────────────────────────────────────
    for name, status, _, auto_fixed in results:
        if status == "passed":
            print(f"  {GREEN}✓{RESET}  {name}")
        elif status == "failed" and auto_fixed:
            print(f"  {YELLOW}↻{RESET}  {BOLD}{name}{RESET}  {GRAY}(auto-fixed){RESET}")
        elif status == "failed":
            print(f"  {RED}✗{RESET}  {BOLD}{name}{RESET}")
        else:  # skipped
            print(f"  {GRAY}–  {name}{RESET}")

    print()

    # ── Error details (only for real failures, not auto-fixes) ──────────────────
    real_failures = [(n, e) for n, s, e, m in results if s == "failed" and not m]
    auto_fixed_names = [n for n, s, e, m in results if s == "failed" and m]

    for name, error_lines in real_failures:
        print(f"  {RED}{BOLD}✗ {name}{RESET}\n")
        for line in error_lines:
            print(f"    {line}")
        print()

    # ── Footer ───────────────────────────────────────────────────────────────────
    if real_failures:
        noun = "check" if len(real_failures) == 1 else "checks"
        print(
            f"  {RED}{BOLD}Commit blocked:{RESET} "
            f"{len(real_failures)} {noun} failed. "
            f"Fix the errors above and try again.\n"
        )
        sys.exit(1)
    elif auto_fixed_names:
        print(
            f"  {YELLOW}{BOLD}Files were auto-formatted.{RESET} "
            f"Re-stage the changes ({BOLD}git add -u{RESET}) and commit again.\n"
        )
        sys.exit(1)
    else:
        print(f"  {GREEN}{BOLD}All checks passed.{RESET}\n")
        sys.exit(0)


if __name__ == "__main__":
    main()

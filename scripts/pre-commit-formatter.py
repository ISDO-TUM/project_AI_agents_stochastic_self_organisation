#!/usr/bin/env python3
"""
Runs pre-commit and reformats its output into a clean, developer-friendly
terminal experience grouped by category with colour-coded results.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import defaultdict

# ── Colours ────────────────────────────────────────────────────────────────────
_USE_COLOUR = sys.stdout.isatty() or os.environ.get("FORCE_COLOR") == "1"


def _c(*codes: int) -> str:
    return f"\033[{';'.join(map(str, codes))}m" if _USE_COLOUR else ""


RESET = _c(0)
BOLD = _c(1)
RED = _c(31)
GREEN = _c(32)
YELLOW = _c(33)
CYAN = _c(36)
GRAY = _c(90)
WHITE = _c(97)

# ── Layout ─────────────────────────────────────────────────────────────────────
_W = 60  # total width of section header lines


# ── Hook registry ──────────────────────────────────────────────────────────────
# Maps lowercase hook name → (display label, group)
_HOOKS: dict[str, tuple[str, str]] = {
    "trim trailing whitespace": ("Trailing whitespace", "File hygiene"),
    "fix end of files": ("End-of-file newline", "File hygiene"),
    "check yaml": ("YAML syntax", "File hygiene"),
    "check json": ("JSON syntax", "File hygiene"),
    "check for merge conflicts": ("Merge conflict markers", "File hygiene"),
    "check for added large files": ("File size (max 500 KB)", "File hygiene"),
    "don't commit to branch": ("Branch protection", "File hygiene"),
    "ruff (legacy alias)": ("Lint", "Python"),
    "ruff": ("Lint", "Python"),
    "ruff format": ("Format", "Python"),
    "mypy": ("Type check", "Python"),
    "prettier": ("Format", "TypeScript"),
    "typescript type check": ("Type check", "TypeScript"),
    "tsc": ("Type check", "TypeScript"),
    "commitlint": ("Commit message", "Commit"),
}

_GROUP_ORDER = ["File hygiene", "Python", "TypeScript", "Other"]

# ── Conventional commit validation ────────────────────────────────────────────
_CC_RE = re.compile(
    r"^(feat|fix|docs|refactor|test|ci|chore|perf|style|build|revert)"
    r"(\([^)]+\))?!?: .+",
)


def _read_commit_msg(repo_root: str) -> str:
    """Read the staged commit message from .git/COMMIT_EDITMSG if present."""
    path = os.path.join(repo_root, ".git", "COMMIT_EDITMSG")
    if not os.path.isfile(path):
        return ""
    with open(path) as fh:
        return fh.read()


# ── pre-commit output parser ───────────────────────────────────────────────────
_HOOK_LINE_RE = re.compile(r"^([A-Za-z].+?)\.{3,}(.*?)$")
_META = ("- hook id:", "- exit code:", "- duration:")

# (hook_name, status, error_lines, was_auto_fixed)
HookResult = tuple[str, str, list[str], bool]


def _parse(raw: str) -> list[HookResult]:
    lines = raw.splitlines()
    results: list[HookResult] = []
    i = 0
    while i < len(lines):
        m = _HOOK_LINE_RE.match(lines[i])
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
        auto_fixed = False

        if status == "failed":
            j = i + 1
            while j < len(lines) and not _HOOK_LINE_RE.match(lines[j]):
                line = lines[j]
                if line == "- files were modified by this hook":
                    auto_fixed = True
                elif not any(line.startswith(p) for p in _META):
                    error_lines.append(line)
                j += 1
            while error_lines and not error_lines[0].strip():
                error_lines.pop(0)
            while error_lines and not error_lines[-1].strip():
                error_lines.pop()
            i = j
        else:
            i += 1

        results.append((name, status, error_lines, auto_fixed))

    return results


# ── Render helpers ─────────────────────────────────────────────────────────────
def _divider(label: str) -> str:
    pad = _W - len(label) - 4
    return f"  {BOLD}{WHITE}── {label} {'─' * max(pad, 2)}{RESET}"


def _row(label: str, status: str, auto_fixed: bool) -> str:
    if status == "passed":
        icon = f"{GREEN}✓{RESET}"
        text = label
    elif status == "failed" and auto_fixed:
        icon = f"{YELLOW}↻{RESET}"
        text = f"{BOLD}{label}{RESET}  {GRAY}(auto-fixed){RESET}"
    elif status == "failed":
        icon = f"{RED}✗{RESET}"
        text = f"{BOLD}{RED}{label}{RESET}"
    else:
        icon = f"{GRAY}–{RESET}"
        text = f"{GRAY}{label}{RESET}"
    return f"  {icon}  {text}"


def _commit_row(valid: bool, first_line: str) -> str:
    if valid:
        return f"  {GREEN}✓{RESET}  {first_line}"
    return (
        f"  {RED}✗{RESET}  {BOLD}{RED}{first_line}{RESET}"
        f"  {GRAY}← not a conventional commit{RESET}"
    )


def _error_block(name: str, error_lines: list[str]) -> None:
    info = _HOOKS.get(name.lower())
    tag = f"{info[1]} · {info[0]}" if info else name
    bar = "─" * max(0, _W - len(tag) - 4)
    print(f"\n  {RED}{BOLD}✗  {tag}{RESET}  {GRAY}{bar}{RESET}\n")
    for line in error_lines:
        coloured = re.sub(
            r"([^\s]+\.py):(\d+)",
            lambda mo: f"{CYAN}{mo.group(1)}{RESET}:{BOLD}{mo.group(2)}{RESET}",
            line,
        )
        print(f"    {coloured}")
    print()


def _branch_error_block() -> None:
    print(
        f"\n  {RED}{BOLD}✗  File hygiene · Branch protection{RESET}  {GRAY}{'─' * 22}{RESET}\n"
    )
    print(f"    You are committing {BOLD}directly to main{RESET}.")
    print("    Always work on a feature branch and open a pull request.")
    print(f"    {GRAY}Example:  git checkout -b feat/42-my-feature{RESET}")
    print()


def _commit_error_block(first_line: str) -> None:
    print(f"\n  {RED}{BOLD}✗  Commit message{RESET}  {GRAY}{'─' * 42}{RESET}\n")
    print(f"    Your message :  {BOLD}{first_line}{RESET}")
    print(f"    Expected     :  {GRAY}<type>(<scope>): <description>{RESET}")
    print(
        f"    Valid types  :  {GRAY}feat  fix  chore  docs  refactor  test  ci  perf{RESET}"
    )
    print(f"    Example      :  {GRAY}feat(api): add streaming endpoint{RESET}")
    print()


# ── Tool finder ────────────────────────────────────────────────────────────────
def _find_uv() -> str:
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
    return "uv"


def _fallback(raw: str, returncode: int) -> None:
    if raw.strip():
        print(raw, end="")
    else:
        print(f"{RED}{BOLD}Pre-commit checks failed (no output captured).{RESET}")
    sys.exit(returncode)


# ── Main ───────────────────────────────────────────────────────────────────────
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

    # ── Commit message ─────────────────────────────────────────────────────────
    raw_msg = _read_commit_msg(repo_root)
    first_line = raw_msg.strip().splitlines()[0] if raw_msg.strip() else ""
    commit_valid = bool(_CC_RE.match(first_line)) if first_line else True
    show_commit = bool(first_line)

    # ── Group hooks ────────────────────────────────────────────────────────────
    groups: dict[str, list[HookResult]] = defaultdict(list)
    for result in results:
        _, group = _HOOKS.get(result[0].lower(), (result[0], "Other"))
        groups[group].append(result)

    # ── Header ─────────────────────────────────────────────────────────────────
    print(f"\n  {BOLD}{CYAN}Pre-commit checks{RESET}\n")

    # ── Commit message section (always first) ──────────────────────────────────
    print(_divider("Commit"))
    if show_commit:
        print(_commit_row(commit_valid, first_line))
    else:
        print(f"  {GRAY}–  (no message — interactive commit){RESET}")
    print()

    # ── Hook groups ────────────────────────────────────────────────────────────
    for group_name in _GROUP_ORDER:
        if group_name not in groups:
            continue
        print(_divider(group_name))
        for name, status, _, auto_fixed in groups[group_name]:
            label, _ = _HOOKS.get(name.lower(), (name, ""))
            print(_row(label, status, auto_fixed))
        print()

    # ── Categorise failures ────────────────────────────────────────────────────
    real_failures = [(n, e) for n, s, e, m in results if s == "failed" and not m]
    auto_fixed_names = [n for n, s, e, m in results if s == "failed" and m]
    branch_blocked = any(
        n.lower() == "don't commit to branch"
        for n, s, _, __ in results
        if s == "failed"
    )
    other_failures = [
        (n, e) for n, e in real_failures if n.lower() != "don't commit to branch"
    ]
    commit_blocked = show_commit and not commit_valid

    total_issues = len(real_failures) + (1 if commit_blocked else 0)

    if total_issues > 0:
        print(f"  {GRAY}{'─' * _W}{RESET}")

    if commit_blocked:
        _commit_error_block(first_line)

    if branch_blocked:
        _branch_error_block()

    for name, error_lines in other_failures:
        if name.lower() != "don't commit to branch":
            _error_block(name, error_lines)

    # ── Footer ─────────────────────────────────────────────────────────────────
    if total_issues > 0:
        noun = "issue" if total_issues == 1 else "issues"
        print(
            f"  {RED}{BOLD}Commit blocked{RESET}"
            f" — {RED}{total_issues} {noun}{RESET} to fix before committing.\n"
        )
        sys.exit(1)
    elif auto_fixed_names:
        print(
            f"  {YELLOW}{BOLD}Files were auto-formatted{RESET}"
            f" — run {BOLD}git add -u{RESET} and commit again.\n"
        )
        sys.exit(1)
    else:
        print(f"  {GREEN}{BOLD}✓  All checks passed{RESET} — committing.\n")
        sys.exit(0)


if __name__ == "__main__":
    main()

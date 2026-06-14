"""
Runs pre-commit and reformats its output into a clean, developer-friendly
terminal experience grouped by category with colour-coded results.
"""

from __future__ import annotations

import os
import re
import shutil
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


def _coverage_colour(pct_str: str) -> str:
    """Return an ANSI colour for a coverage percentage string like '78%'."""
    try:
        val = int(pct_str.rstrip("%"))
    except ValueError:
        return WHITE
    if val >= 80:
        return GREEN
    if val >= 60:
        return YELLOW
    return RED


def _render_coverage_table(detail: str) -> None:
    """Parse pytest-cov terminal output and re-render it with ANSI colours."""
    lines = detail.splitlines()

    # Locate the header row: "Name   Stmts   Miss   Cover   [Missing]"
    header_idx = next(
        (
            i
            for i, ln in enumerate(lines)
            if re.match(r"\s*Name\s+Stmts\s+Miss\s+Cover", ln)
        ),
        None,
    )
    if header_idx is None:
        return

    # Row after header is a separator line — data starts two lines down
    data_rows: list[tuple[str, str, str, str, str]] = []
    total_row: tuple[str, str, str] | None = None

    for ln in lines[header_idx + 2 :]:
        stripped = ln.strip()
        if not stripped:
            continue
        # Separator lines (pure dashes or "--- coverage: … ---") → skip
        if re.match(r"-{5,}", stripped):
            continue
        parts = stripped.split()
        if len(parts) < 4:
            continue
        if parts[0] == "TOTAL":
            total_row = (parts[1], parts[2], parts[3])
        else:
            missing = " ".join(parts[4:]) if len(parts) > 4 else ""
            data_rows.append((parts[0], parts[1], parts[2], parts[3], missing))

    if not data_rows and total_row is None:
        return

    has_missing_col = any(r[4] for r in data_rows)
    name_w = max((len(r[0]) for r in data_rows), default=5)
    name_w = max(name_w, 5)  # at least as wide as "TOTAL"
    divider_w = name_w + 28 + (9 if has_missing_col else 0)

    # Header
    missing_hdr = f"  {'Missing'}" if has_missing_col else ""
    print(
        f"    {BOLD}{GRAY}"
        f"{'Name':<{name_w}}  {'Stmts':>6}  {'Miss':>5}  {'Cover':>6}"
        f"{missing_hdr}{RESET}"
    )
    print(f"    {GRAY}{'─' * divider_w}{RESET}")

    for name, stmts, miss, cover, missing in data_rows:
        cov_col = _coverage_colour(cover)
        miss_col = RED if miss != "0" else GREEN
        row = (
            f"    {CYAN}{name:<{name_w}}{RESET}"
            f"  {GRAY}{stmts:>6}{RESET}"
            f"  {miss_col}{miss:>5}{RESET}"
            f"  {cov_col}{BOLD}{cover:>6}{RESET}"
        )
        if missing:
            row += f"  {GRAY}{missing}{RESET}"
        print(row)

    if total_row:
        stmts, miss, cover = total_row
        cov_col = _coverage_colour(cover)
        print(f"    {GRAY}{'─' * divider_w}{RESET}")
        print(
            f"    {BOLD}{'TOTAL':<{name_w}}{RESET}"
            f"  {BOLD}{stmts:>6}{RESET}"
            f"  {BOLD}{miss:>5}{RESET}"
            f"  {cov_col}{BOLD}{cover:>6}{RESET}"
        )
    print()


def _find_uv() -> str:
    if found := shutil.which("uv"):
        return found
    home = os.path.expanduser("~")
    for candidate in (
        os.path.join(home, ".local", "bin", "uv"),
        os.path.join(home, ".cargo", "bin", "uv"),
    ):
        if os.path.isfile(candidate):
            return candidate
    raise RuntimeError("uv not found — install it from https://github.com/astral-sh/uv")


def _find_pre_commit(repo_root: str) -> list[str] | None:
    """Return a runnable pre-commit command with local-first fallbacks."""
    candidates = [
        os.path.join(repo_root, "server", ".venv", "bin", "pre-commit"),
        os.path.join(repo_root, "api", ".venv", "bin", "pre-commit"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return [candidate]

    if found := shutil.which("pre-commit"):
        return [found]

    # Last resort: use whichever python is currently running this script.
    return [sys.executable, "-m", "pre_commit"]


def _fallback(raw: str, returncode: int) -> None:
    if raw.strip():
        print(raw, end="")
    else:
        print(f"{RED}{BOLD}Pre-commit checks failed (no output captured).{RESET}")
    sys.exit(returncode)


def _run_tests(repo_root: str, uv: str) -> tuple[bool, str, str]:
    """Run pytest with coverage for the API and return (passed, coverage_pct, detail)."""
    server_dir = os.path.join(repo_root, "server")
    # Skip entirely when no test files exist yet
    test_dir = os.path.join(server_dir, "tests")
    if not os.path.isdir(test_dir) or not any(
        f.startswith("test_") and f.endswith(".py") for f in os.listdir(test_dir)
    ):
        return True, "", ""

    pytest_bin = os.path.join(repo_root, "server", ".venv", "bin", "pytest")
    proc = subprocess.run(
        [
            pytest_bin,
            "--tb=short",
            "--cov=.",
            "--cov-report=term-missing:skip-covered",
            "-q",
        ],
        cwd=server_dir,
        capture_output=True,
        text=True,
    )

    passed = proc.returncode == 0

    # Extract the "TOTAL … X%" coverage line from the output
    coverage_pct = ""
    for line in (proc.stdout + proc.stderr).splitlines():
        if line.startswith("TOTAL"):
            parts = line.split()
            coverage_pct = parts[-1] if parts else ""
            break

    detail = proc.stdout + proc.stderr
    return passed, coverage_pct, detail


def _print_tests_section(passed: bool, coverage_pct: str, detail: str) -> None:
    print(_divider("Python · Tests"))
    if passed:
        cov_col = _coverage_colour(coverage_pct) if coverage_pct else GREEN
        cov_label = (
            f"  {GRAY}coverage: {cov_col}{BOLD}{coverage_pct}{RESET}"
            if coverage_pct
            else ""
        )
        print(f"  {GREEN}✓{RESET}  All tests passed{cov_label}")
    else:
        print(f"  {RED}✗{RESET}  {BOLD}{RED}Tests failed{RESET}")
        if coverage_pct:
            cov_col = _coverage_colour(coverage_pct)
            print(f"  {GRAY}coverage: {cov_col}{BOLD}{coverage_pct}{RESET}")

        # Print test failure details (skip coverage-table lines to avoid duplication)
        in_cov_table = False
        relevant: list[str] = []
        for line in detail.splitlines():
            stripped = line.strip()
            if re.match(r"\s*Name\s+Stmts\s+Miss\s+Cover", line):
                in_cov_table = True
            if in_cov_table:
                if stripped.startswith("TOTAL"):
                    in_cov_table = False
                continue
            if stripped and not line.startswith("=== passed"):
                relevant.append(line)

        if relevant:
            print()
            for line in relevant:
                coloured = re.sub(
                    r"([^\s]+\.py):(\d+)",
                    lambda mo: f"{CYAN}{mo.group(1)}{RESET}:{BOLD}{mo.group(2)}{RESET}",
                    line,
                )
                print(f"    {coloured}")

    print()
    _render_coverage_table(detail)


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    try:
        repo_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True
        ).strip()
    except Exception as exc:  # noqa: BLE001
        print(f"{RED}{BOLD}pre-commit: could not locate repo root:{RESET} {exc}")
        sys.exit(1)

    try:
        uv = _find_uv()
    except RuntimeError as exc:
        print(f"{RED}{BOLD}pre-commit:{RESET} {exc}")
        sys.exit(1)

    pre_commit_cmd = _find_pre_commit(repo_root)
    if not pre_commit_cmd:
        print(
            f"{RED}{BOLD}pre-commit: could not find a runnable pre-commit command.{RESET}"
        )
        sys.exit(1)

    try:
        proc = subprocess.run(
            [*pre_commit_cmd, "run", "--hook-stage=pre-commit", *sys.argv[1:]],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"{RED}{BOLD}pre-commit: failed to run checks:{RESET} {exc}")
        sys.exit(1)

    results = _parse(proc.stdout + proc.stderr)
    if not results:
        _fallback(proc.stdout + proc.stderr, proc.returncode)

    # ── Group hooks ────────────────────────────────────────────────────────────
    groups: dict[str, list[HookResult]] = defaultdict(list)
    for result in results:
        _, group = _HOOKS.get(result[0].lower(), (result[0], "Other"))
        groups[group].append(result)

    # ── Run server-side tests ──────────────────────────────────────────────────
    tests_passed, coverage_pct, test_detail = _run_tests(repo_root, uv)
    # _run_tests returns empty strings for both when no tests exist
    tests_available = bool(coverage_pct or test_detail or not tests_passed)

    # ── Header ─────────────────────────────────────────────────────────────────
    print(f"\n  {BOLD}{CYAN}Pre-commit checks{RESET}\n")

    # ── Hook groups ────────────────────────────────────────────────────────────
    for group_name in _GROUP_ORDER:
        if group_name not in groups:
            continue
        print(_divider(group_name))
        for name, status, _, auto_fixed in groups[group_name]:
            label, _ = _HOOKS.get(name.lower(), (name, ""))
            print(_row(label, status, auto_fixed))
        print()

    # ── Test results ───────────────────────────────────────────────────────────
    if tests_available:
        _print_tests_section(tests_passed, coverage_pct, test_detail)

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

    total_issues = len(real_failures) + (0 if tests_passed else 1)

    if total_issues > 0:
        print(f"  {GRAY}{'─' * _W}{RESET}")

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

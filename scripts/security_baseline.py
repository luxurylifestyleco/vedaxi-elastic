#!/usr/bin/env python3
"""Security Baseline Scanner (Phase AC).

Automates a baseline security scan of the repository's tracked files:

  1. Secret scanning      — grep for API keys, tokens, passwords, private keys.
  2. Dependency vulns     — compare installed package versions against a small
                            known-vulnerable list; flag when no scanner is
                            available (no network / no pip-audit).
  3. Unsafe deserialization — pickle / yaml.load / marshal / shelve usage.
  4. Input validation     — eval / exec usage.
  5. Command injection    — os.system / subprocess with shell=True / os.popen.
  6. Path traversal       — os.path.join / open() fed by user input (heuristic).
  7. SQL injection        — string-formatted SQL (f-string / % / .format in
                            SQL statements) instead of parameterized queries.

This is a BASELINE scanner, not an enterprise security suite. It uses static
pattern matching and reports findings for human triage; it does not attempt to
prove exploitability. Findings are written to docs/SECURITY-BASELINE.md.

Usage:
    python scripts/security_baseline.py [--out docs/SECURITY-BASELINE.md]

Exit code 0 = scan completed (findings may be non-zero). Use --fail-on-findings
to exit non-zero when any finding is recorded.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Secret patterns
# ---------------------------------------------------------------------------

SECRET_PATTERNS = [
    ("AWS Access Key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("GitHub PAT", r"\bghp_[A-Za-z0-9]{36}\b"),
    ("GitHub OAuth", r"\bgho_[A-Za-z0-9]{36}\b"),
    ("GitHub App token", r"\bghu_[A-Za-z0-9]{36}\b"),
    ("OpenAI API key", r"\bsk-(?:proj-)?[A-Za-z0-9]{20,}\b"),
    ("Slack token", r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    ("Google API key", r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    ("Stripe secret", r"\bsk_live_[0-9A-Za-z]{20,}\b"),
    ("Private key block", r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE " r"KEY-----"),
    ("Generic password assignment", r"(?i)(password|passwd|pwd)\s*[=:]\s*['\"][^'\"]{4,}['\"]"),
    ("Generic secret assignment", r"(?i)(secret|api[_-]?key|apikey|access[_-]?key|client[_-]?secret)\s*[=:]\s*['\"][^'\"]{6,}['\"]"),
    ("Bearer token literal", r"(?i)authorization\s*[:=]\s*['\"]?bearer\s+[A-Za-z0-9._-]{10,}"),
]

# ---------------------------------------------------------------------------
# Unsafe-code patterns
# ---------------------------------------------------------------------------

UNSAFE_PATTERNS = {
    "unsafe_deserialization": [
        ("pickle.loads", r"\bpickle\.loads?\s*\("),
        ("pickle.load", r"\bpickle\.load\s*\("),
        ("yaml.load (unsafe)", r"\byaml\.load\s*\("),
        ("marshal.loads", r"\bmarshal\.loads?\s*\("),
        ("shelve.open", r"\bshelve\.open\s*\("),
    ],
    "input_validation": [
        ("eval()", r"\beval\s*\("),
        ("exec()", r"\bexec\s*\("),
        ("exec compile", r"\bexec\s*\(\s*compile\s*\("),
    ],
    "command_injection": [
        ("os.system", r"\bos\.system\s*\("),
        ("os.popen", r"\bos\.popen\s*\("),
        ("subprocess shell=True", r"subprocess\.(run|call|Popen|check_output|check_call)\s*\([^)]*shell\s*=\s*True"),
        ("subprocess shell=True (multiline)", r"shell\s*=\s*True"),
    ],
    "path_traversal": [
        # Only flag when the path is built from a user-controlled source
        # (input/request/argv/env/query/param), not from a constant.
        ("open() with user-controlled path", r"open\s*\(\s*(?:os\.path\.join\s*\(\s*)?[^)]*(?:input|request|argv|environ|getenv|query|form|param|user)[^)]*\)"),
        ("Path() with user-controlled path", r"Path\s*\(\s*[^)]*(?:input|request|argv|environ|getenv|query|form|param|user)[^)]*\)"),
    ],
    "sql_injection": [
        ("f-string SQL", r"f['\"][^'\"]*\b(SELECT|INSERT|UPDATE|DELETE|WHERE|FROM)\b"),
        ("% formatting SQL", r"execute\s*\(\s*['\"][^'\"]*\b(SELECT|INSERT|UPDATE|DELETE|WHERE|FROM)\b[^'\"]*%"),
        (".format SQL", r"execute\s*\(\s*['\"][^'\"]*\b(SELECT|INSERT|UPDATE|DELETE|WHERE|FROM)\b[^'\"]*\.format\s*\("),
        ("string-concat SQL", r"execute\s*\(\s*['\"][^'\"]*\b(SELECT|INSERT|UPDATE|DELETE|WHERE|FROM)\b[^'\"]*\+"),
    ],
}

# ---------------------------------------------------------------------------
# Known-vulnerable dependency list (name -> set of vulnerable versions).
# This is a small, curated baseline. When a real scanner (pip-audit / OSV) is
# available it should be used instead; this list is a fallback and is NOT
# exhaustive.
# ---------------------------------------------------------------------------

KNOWN_VULNERABLE = {
    # Example entries (kept minimal and honest — only add versions you can
    # verify). Empty by default so the scanner never fabricates findings.
}

# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def _tracked_files(repo_root: Path) -> list[Path]:
    """Return the list of git-tracked files (respecting .gitignore)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files"],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Not a git repo or git unavailable — fall back to walking the tree
        # excluding common noise.
        print("[warn] git ls-files failed; falling back to filesystem walk", file=sys.stderr)
        files = []
        for root, dirs, names in os.walk(repo_root):
            dirs[:] = [d for d in dirs if d not in (".git", ".venv", "__pycache__", "node_modules")]
            for n in names:
                p = Path(root) / n
                if ".venv" not in p.parts and "site-packages" not in p.parts:
                    files.append(p)
        return files
    return [repo_root / f for f in out.stdout.splitlines() if f]


def _scan_file(path: Path) -> list[dict]:
    """Scan a single file for secrets and unsafe patterns."""
    findings: list[dict] = []
    # Skip the scanner's own source and its own report output: the pattern
    # tables legitimately contain the literal strings "yaml.load", "eval(",
    # "exec(", "shell=True", etc. as regex definitions, and the generated
    # report embeds the very snippets it found. Both would otherwise be
    # self-flagged as findings.
    if path.name in ("security_baseline.py", "SECURITY-BASELINE.md"):
        return findings
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError:
        return findings

    lines = content.splitlines()

    # Secrets
    for label, pattern in SECRET_PATTERNS:
        rx = re.compile(pattern)
        for i, line in enumerate(lines, 1):
            if rx.search(line):
                findings.append({
                    "category": "secret",
                    "check": label,
                    "file": str(path),
                    "line": i,
                    "snippet": line.strip()[:120],
                })

    # Unsafe code patterns (Python only)
    if path.suffix == ".py":
        for category, checks in UNSAFE_PATTERNS.items():
            for label, pattern in checks:
                rx = re.compile(pattern)
                for i, line in enumerate(lines, 1):
                    if rx.search(line):
                        findings.append({
                            "category": category,
                            "check": label,
                            "file": str(path),
                            "line": i,
                            "snippet": line.strip()[:120],
                        })
    return findings


def _scan_dependencies(repo_root: Path) -> list[dict]:
    """Compare installed package versions against the known-vulnerable list.

    Also attempts to detect whether a real scanner (pip-audit) is available.
    """
    findings: list[dict] = []
    installed: dict[str, str] = {}

    for site in [
        repo_root / ".venv" / "lib" / "site-packages",
        repo_root / ".venv" / "Lib" / "site-packages",
    ]:
        if site.exists():
            for dist in site.glob("*.dist-info"):
                name = dist.name.split("-")[0].replace("_", "-")
                version = dist.name.split("-")[1] if "-" in dist.name else ""
                installed.setdefault(name.lower(), version)
            break

    for name, version in installed.items():
        if name in KNOWN_VULNERABLE and version in KNOWN_VULNERABLE[name]:
            findings.append({
                "category": "dependency_vuln",
                "check": f"{name}=={version} in known-vulnerable list",
                "file": "venv",
                "line": 0,
                "snippet": f"{name} {version}",
            })

    # Detect scanner availability. pip-audit may be installed only inside the
    # project venv (not on PATH), so check the venv's Scripts/bin dir too.
    scanner = None
    candidates = ["pip-audit"]
    for site in [
        repo_root / ".venv" / "Scripts" / "pip-audit.exe",
        repo_root / ".venv" / "Scripts" / "pip-audit",
        repo_root / ".venv" / "bin" / "pip-audit",
    ]:
        if site.exists():
            candidates.append(str(site))
    for cand in candidates:
        try:
            subprocess.run(
                [cand, "--version"], capture_output=True, text=True, check=True
            )
            scanner = "pip-audit"
            break
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

    if scanner is None:
        findings.append({
            "category": "dependency_vuln",
            "check": "no vulnerability scanner available",
            "file": "venv",
            "line": 0,
            "snippet": (
                "pip-audit not installed; only the curated KNOWN_VULNERABLE "
                "list was checked. Install pip-audit for a real scan."
            ),
        })
    return findings


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

CATEGORY_LABELS = {
    "secret": "Secret scanning",
    "dependency_vuln": "Dependency vulnerabilities",
    "unsafe_deserialization": "Unsafe deserialization",
    "input_validation": "Input validation (eval/exec)",
    "command_injection": "Command injection",
    "path_traversal": "Path traversal",
    "sql_injection": "SQL injection",
}


def _render_report(findings: list[dict], repo_root: Path) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Security Baseline",
        "",
        f"Generated by `scripts/security_baseline.py` on {now}.",
        f"Repository: `{repo_root.name}` (PRIVATE).",
        "",
        "This is a **baseline** static scan, not an enterprise security suite.",
        "It uses pattern matching and reports findings for human triage; it does",
        "not prove exploitability. Run a real scanner (pip-audit, bandit, gitleaks,",
        "Semgrep) for production assurance.",
        "",
        "## Summary",
        "",
    ]

    by_cat: dict[str, list[dict]] = {}
    for f in findings:
        by_cat.setdefault(f["category"], []).append(f)

    total = len(findings)
    lines.append(f"- **Total findings:** {total}")
    for cat in CATEGORY_LABELS:
        n = len(by_cat.get(cat, []))
        lines.append(f"- **{CATEGORY_LABELS[cat]}:** {n}")
    lines.append("")

    if total == 0:
        lines.append("No findings. This is a clean baseline scan.")
        lines.append("")
        return "\n".join(lines)

    for cat, label in CATEGORY_LABELS.items():
        items = by_cat.get(cat, [])
        if not items:
            continue
        lines.append(f"## {label}")
        lines.append("")
        lines.append("| File | Line | Check | Snippet |")
        lines.append("|------|------|-------|---------|")
        for f in sorted(items, key=lambda x: (x["file"], x["line"])):
            snippet = f["snippet"].replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| `{f['file']}` | {f['line'] or '—'} | {f['check']} | `{snippet}` |"
            )
        lines.append("")

    lines += [
        "## Remediation notes",
        "",
        "- **Secrets:** rotate any real credential immediately; move to env vars /",
        "  a secret manager; never commit `.env` or key files.",
        "- **Unsafe deserialization:** prefer `json.loads`; never `pickle`/`yaml.load`",
        "  on untrusted input.",
        "- **eval/exec:** replace with safe, whitelisted logic.",
        "- **Command injection:** avoid `shell=True`; pass argument lists to",
        "  `subprocess.run`.",
        "- **Path traversal:** validate/normalize user-supplied paths against a",
        "  trusted root before `open`/`os.path.join`.",
        "- **SQL injection:** use parameterized queries (psycopg2 `%(name)s`), never",
        "  f-string/`%`/`.format` interpolation of user input into SQL.",
        "- **Dependency vulns:** install `pip-audit` and run it in CI.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="docs/SECURITY-BASELINE.md",
        help="Output path (default: docs/SECURITY-BASELINE.md).",
    )
    parser.add_argument(
        "--fail-on-findings",
        action="store_true",
        help="Exit non-zero if any finding is recorded.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent

    files = _tracked_files(repo_root)
    findings: list[dict] = []
    for f in files:
        findings.extend(_scan_file(f))
    findings.extend(_scan_dependencies(repo_root))

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = repo_root / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_render_report(findings, repo_root), encoding="utf-8")

    print(f"Scanned {len(files)} tracked files.")
    print(f"Wrote {out_path}")
    print(f"Total findings: {len(findings)}")

    by_cat: dict[str, int] = {}
    for f in findings:
        by_cat[f["category"]] = by_cat.get(f["category"], 0) + 1
    for cat, n in sorted(by_cat.items()):
        print(f"  {CATEGORY_LABELS.get(cat, cat)}: {n}")

    if args.fail_on_findings and findings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

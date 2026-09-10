#!/usr/bin/env python3
"""License / Attribution Audit (Phase AB).

Enumerates the direct third-party dependencies installed in the project's
virtualenv(s), records each package's license and upstream repository, flags
packages with missing or restrictive/unknown license metadata, and generates /
updates THIRD_PARTY_NOTICES.md at the repository root.

Design rules (per the task):
  * We NEVER assume license compatibility automatically. Every package is
    reported with its declared license; the audit only *flags* unknown or
    restrictive licenses for human review — it does not bless them.
  * Direct dependencies are enumerated from installed ``*.dist-info``
    metadata (the venv is the source of truth; there is no requirements file
    in this repo). Nested per-package venvs are also scanned.
  * Upstream repository is read from the package METADATA (Project-URL
    Homepage / Source / Code), falling back to the PyPI project page.

Usage:
    python scripts/license_audit.py [--venv PATH]... [--out THIRD_PARTY_NOTICES.md]

Exit code 0 = audit ran (findings may still be non-zero). Use --fail-on-unknown
to exit non-zero when any package has unknown/restrictive license metadata.
"""

from __future__ import annotations

import argparse
import email.parser
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# License classification
# ---------------------------------------------------------------------------

# Permissive / clearly-compatible licenses. Presence here does NOT mean the
# audit "approves" the dependency — it only means the license is a well-known
# permissive one. Restrictive/unknown licenses are always flagged.
PERMISSIVE = {
    "mit",
    "bsd",
    "bsd-2-clause",
    "bsd-3-clause",
    "apache",
    "apache-2.0",
    "psf",
    "psf-2.0",
    "isc",
    "python-2.0",
    "zlib",
    "unlicense",
    "cc0",
    "mpl-2.0",
}

# Licenses that require care (copyleft / dual-license / exceptions). These are
# flagged for human review, not auto-approved.
RESTRICTIVE = {
    "lgpl",
    "gpl",
    "agpl",
    "mpl",
    "epl",
    "cddl",
    "cc-by-sa",
    "cc-by-nc",
    "commercial",
    "proprietary",
    "or",
    "and",
}

# ---------------------------------------------------------------------------
# METADATA parsing
# ---------------------------------------------------------------------------


def _normalize_license(raw: str) -> str:
    """Collapse whitespace and strip trailing punctuation from a license token."""
    if not raw:
        return ""
    return re.sub(r"\s+", " ", raw).strip().strip(".").strip()


def _classify(license_text: str) -> str:
    """Classify a license string as permissive / restrictive / unknown."""
    if not license_text:
        return "unknown"
    low = license_text.lower()
    # A very long license string is the full license TEXT (e.g. some packages
    # paste the entire Apache-2.0 body into the License field), not a license
    # expression. Treat it as a single license: classify by the license name
    # it contains, not by the "or"/"and" words inside the legal prose.
    if len(license_text) > 200:
        if any(pk in low for pk in PERMISSIVE):
            return "permissive"
        if any(rk in low for rk in RESTRICTIVE):
            return "restrictive"
        return "unknown"
    # A compound expression like "Apache-2.0 OR BSD-2-Clause" is permissive if
    # every alternative is permissive.
    if " or " in low:
        parts = [p.strip() for p in low.split(" or ")]
        if all(any(pk in p for pk in PERMISSIVE) for p in parts):
            return "permissive"
        return "restrictive"
    # Check permissive BEFORE restrictive so that a license present in both
    # sets (e.g. "mpl-2.0" is in PERMISSIVE while the substring "mpl" is in
    # RESTRICTIVE) is not mis-flagged. Exact permissive names win.
    if any(pk in low for pk in PERMISSIVE):
        return "permissive"
    if any(rk in low for rk in RESTRICTIVE):
        return "restrictive"
    return "unknown"


def _read_metadata(dist_info: Path) -> dict:
    """Parse a package's METADATA file into a dict of useful fields."""
    meta_path = dist_info / "METADATA"
    if not meta_path.exists():
        return {}
    with open(meta_path, "r", encoding="utf-8", errors="replace") as fh:
        msg = email.parser.Parser().parsestr(fh.read())

    license_expr = _normalize_license(msg.get("License-Expression", ""))
    license_field = _normalize_license(msg.get("License", ""))
    classifiers = [
        c for c in msg.get_all("Classifier", []) if c.lower().startswith("license")
    ]

    # Prefer the machine-readable License-Expression, then the License field,
    # then the OSI classifier.
    if license_expr:
        license_text = license_expr
    elif license_field and license_field.lower() not in ("license", "license file."):
        license_text = license_field
    elif classifiers:
        # "License :: OSI Approved :: BSD License" -> "BSD License"
        license_text = classifiers[0].split("::")[-1].strip()
    else:
        license_text = ""

    # Upstream repository: prefer Source/Code/Homepage project URLs.
    repo = ""
    for url in msg.get_all("Project-URL", []):
        if "," in url:
            label, _, value = url.partition(",")
            label = label.strip().lower()
            value = value.strip()
            if label in ("source", "code", "homepage", "repository") and value:
                repo = value
                break
    if not repo:
        repo = msg.get("Home-page", "").strip()

    return {
        "name": msg.get("Name", dist_info.name).strip(),
        "version": msg.get("Version", "").strip(),
        "license": license_text,
        "classifiers": classifiers,
        "repo": repo,
        "license_files": msg.get_all("License-File", []),
    }


def _enumerate_venv(venv: Path) -> list[dict]:
    """Enumerate installed packages in a venv's site-packages."""
    site_packages = venv / "lib" / "site-packages"
    if not site_packages.exists():
        # Windows layout: <venv>/Lib/site-packages
        site_packages = venv / "Lib" / "site-packages"
    if not site_packages.exists():
        return []

    packages = []
    for dist_info in sorted(site_packages.glob("*.dist-info")):
        meta = _read_metadata(dist_info)
        if not meta.get("name"):
            continue
        # Skip pip itself? No — pip is a real dependency of the venv and is
        # reported like any other. It is not filtered out.
        packages.append(meta)
    return packages


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _render_notices(packages: list[dict], scanned_venvs: list[str]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# THIRD PARTY NOTICES",
        "",
        f"Generated by `scripts/license_audit.py` on {now}.",
        "",
        "This file lists the third-party Python packages installed in this",
        "repository's virtualenv(s) and their declared licenses. It is an",
        "**attribution record, not a license approval**. Every package is",
        "listed with the license its distribution declares; packages with",
        "unknown or restrictive licenses are flagged for human review and",
        "must not be assumed compatible.",
        "",
        "## Scanned environments",
        "",
    ]
    for v in scanned_venvs:
        lines.append(f"- `{v}`")
    lines += [
        "",
        "## Direct dependencies",
        "",
        "| Package | Version | License | Upstream | Status |",
        "|---------|---------|---------|----------|--------|",
    ]

    for p in sorted(packages, key=lambda x: (x["name"].lower(), x["version"])):
        status = _classify(p["license"])
        status_label = {
            "permissive": "permissive",
            "restrictive": "**RESTRICTIVE — review**",
            "unknown": "**UNKNOWN — review**",
        }[status]
        repo = p["repo"] or "—"
        lic = p["license"] or "**missing**"
        lines.append(
            f"| {p['name']} | {p['version']} | {lic} | {repo} | {status_label} |"
        )

    lines += [
        "",
        "## Packages requiring review",
        "",
    ]
    flagged = [p for p in packages if _classify(p["license"]) != "permissive"]
    if not flagged:
        lines.append("None — every installed package declares a permissive license.")
    else:
        for p in sorted(flagged, key=lambda x: x["name"].lower()):
            lines.append(
                f"- **{p['name']} {p['version']}** — license: "
                f"`{p['license'] or 'MISSING'}` — upstream: {p['repo'] or 'unknown'}"
            )
    lines += [
        "",
        "## Notes",
        "",
        "- License metadata is read from each package's `*.dist-info/METADATA`.",
        "- A package with no license metadata is flagged as UNKNOWN and must be",
        "  reviewed before it is relied upon.",
        "- This audit does not automatically approve any license. Restrictive",
        "  (copyleft / dual-license / commercial) licenses require explicit",
        "  human sign-off.",
        "",
    ]
    return "\n".join(lines)


def _render_audit(packages: list[dict], scanned_venvs: list[str]) -> str:
    """Render the LICENSE-AUDIT.md report (findings + per-package detail)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    flagged = [p for p in packages if _classify(p["license"]) != "permissive"]
    lines = [
        "# License Audit",
        "",
        f"Generated by `scripts/license_audit.py` on {now}.",
        f"Repository: `{Path(__file__).resolve().parent.parent.name}` (PRIVATE).",
        "",
        "## Summary",
        "",
        f"- **Packages audited:** {len(packages)}",
        f"- **Scanned environments:** {len(scanned_venvs)}",
        f"- **Packages requiring review:** {len(flagged)}",
        "",
        "## Packages requiring review",
        "",
    ]
    if not flagged:
        lines.append("None — every installed package declares a permissive license.")
    else:
        for p in sorted(flagged, key=lambda x: x["name"].lower()):
            lines.append(
                f"- **{p['name']} {p['version']}** — license: "
                f"`{p['license'] or 'MISSING'}` — upstream: {p['repo'] or 'unknown'}"
            )
    lines += [
        "",
        "## Full dependency table",
        "",
        "| Package | Version | License | Upstream | Status |",
        "|---------|---------|---------|----------|--------|",
    ]
    for p in sorted(packages, key=lambda x: (x["name"].lower(), x["version"])):
        status = _classify(p["license"])
        status_label = {
            "permissive": "permissive",
            "restrictive": "**RESTRICTIVE — review**",
            "unknown": "**UNKNOWN — review**",
        }[status]
        lines.append(
            f"| {p['name']} | {p['version']} | {p['license'] or '**missing**'} | "
            f"{p['repo'] or '—'} | {status_label} |"
        )
    lines += [
        "",
        "## Methodology",
        "",
        "- Dependencies are enumerated from installed `*.dist-info/METADATA` in the",
        "  project virtualenv(s). There is no requirements file in this repo, so the",
        "  venv is the source of truth.",
        "- License metadata is read from `License-Expression`, `License`, and OSI",
        "  `Classifier` fields. Upstream repository is read from `Project-URL`",
        "  (Source/Code/Homepage) or `Home-page`.",
        "- **No license is auto-approved.** Restrictive (copyleft / dual-license /",
        "  commercial) and unknown licenses are flagged for explicit human review.",
        "- The companion `THIRD_PARTY_NOTICES.md` is the attribution record.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--venv",
        action="append",
        default=[],
        help="Path to a virtualenv to scan (repeatable). Defaults to repo .venv "
        "plus any nested per-package .venv dirs.",
    )
    parser.add_argument(
        "--out",
        default="docs/LICENSE-AUDIT.md",
        help="Output path for the audit report (default: docs/LICENSE-AUDIT.md).",
    )
    parser.add_argument(
        "--notices",
        default="THIRD_PARTY_NOTICES.md",
        help="Output path for the notices file (default: THIRD_PARTY_NOTICES.md).",
    )
    parser.add_argument(
        "--fail-on-unknown",
        action="store_true",
        help="Exit non-zero if any package has unknown/restrictive license metadata.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent

    venvs: list[Path] = []
    if args.venv:
        venvs = [Path(v) for v in args.venv]
    else:
        root_venv = repo_root / ".venv"
        if root_venv.exists():
            venvs.append(root_venv)
        # Nested per-package venvs (e.g. packages/intent-ir/.venv).
        for pkg_venv in sorted(repo_root.glob("packages/*/.venv")):
            venvs.append(pkg_venv)

    all_packages: list[dict] = []
    scanned: list[str] = []
    for venv in venvs:
        pkgs = _enumerate_venv(venv)
        if not pkgs:
            print(f"[warn] no site-packages found under {venv}", file=sys.stderr)
            continue
        scanned.append(str(venv))
        all_packages.extend(pkgs)

    if not all_packages:
        print("No packages found in any scanned venv.", file=sys.stderr)
        return 2

    # Deduplicate by (name, version) across venvs.
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for p in all_packages:
        key = (p["name"], p["version"])
        if key not in seen:
            seen.add(key)
            unique.append(p)

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = repo_root / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_render_audit(unique, scanned), encoding="utf-8")

    notices_path = Path(args.notices)
    if not notices_path.is_absolute():
        notices_path = repo_root / notices_path
    notices_path.parent.mkdir(parents=True, exist_ok=True)
    notices_path.write_text(_render_notices(unique, scanned), encoding="utf-8")

    print(f"Scanned {len(scanned)} venv(s), {len(unique)} unique packages.")
    print(f"Wrote {out_path}")
    print(f"Wrote {notices_path}")

    flagged = [p for p in unique if _classify(p["license"]) != "permissive"]
    if flagged:
        print(f"\n{len(flagged)} package(s) need license review:")
        for p in sorted(flagged, key=lambda x: x["name"].lower()):
            print(f"  - {p['name']} {p['version']}: {p['license'] or 'MISSING'}")
    else:
        print("\nAll packages declare permissive licenses.")

    if args.fail_on_unknown and flagged:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

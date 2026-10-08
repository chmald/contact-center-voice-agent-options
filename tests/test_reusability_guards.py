from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

DOMAIN_TERMS = ["Contoso", "service request", "lookup_request_status", "SR-10"]
# Customer-identifying terms are deliberately NOT listed in this committed file (that
# would leak them). Put one term per line in the gitignored
# tests/forbidden-terms.local.txt, or set FORBIDDEN_TERMS="term1,term2".
FORBIDDEN_TERMS_FILE = "forbidden-terms.local.txt"
# JSON escapes backslashes, so match one or two between segments.
USER_PROFILE_PATH = re.compile(r"\b[A-Za-z]:\\{1,2}Users\\{1,2}[A-Za-z0-9._-]+|/home/[a-z0-9._-]+/|/Users/[A-Za-z0-9._-]+/")
SKIP_DIRS = {".venv", ".git", "__pycache__", ".pytest_cache", "node_modules", ".azure"}
TEXT_SUFFIXES = {
    ".bicep",
    ".css",
    ".drawio",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".txt",
    ".yml",
    ".yaml",
}


def _forbidden_terms(repo_root) -> list[str]:
    terms: list[str] = []
    local = repo_root / "tests" / FORBIDDEN_TERMS_FILE
    if local.exists():
        for line in local.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                terms.append(line)
    terms += [t.strip() for t in os.getenv("FORBIDDEN_TERMS", "").split(",") if t.strip()]
    return terms


def _committable_paths(root):
    """Tracked plus untracked-but-not-ignored files: everything a commit could include."""
    git = shutil.which("git") or next(
        (p for p in (r"C:\Program Files\Git\cmd\git.exe",) if Path(p).exists()), None
    )
    if git:
        result = subprocess.run(
            [git, "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, check=False,
        )
        if result.returncode == 0:
            return [root / name for name in result.stdout.decode("utf-8").split("\0") if name]
    return list(root.rglob("*"))


def _text_files(root):
    for path in _committable_paths(root):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.name.endswith(".local.txt") or ".local." in path.name:
            continue  # gitignored local-only files (never distributed)
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            yield path


def test_domain_terms_do_not_leak_into_shared_or_loadtest_python(repo_root):
    scanned = list((repo_root / "shared").rglob("*")) + list((repo_root / "loadtest").glob("*.py"))
    hits = []
    for path in scanned:
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8")
        for term in DOMAIN_TERMS:
            if term.lower() in text.lower():
                hits.append(f"{path.relative_to(repo_root)} contains {term!r}")
    assert hits == []


def test_customer_identifying_terms_do_not_appear(repo_root):
    terms = _forbidden_terms(repo_root)
    if not terms:
        pytest.skip(f"No forbidden terms configured (tests/{FORBIDDEN_TERMS_FILE} or FORBIDDEN_TERMS env var)")
    hits = []
    for path in _text_files(repo_root):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for term in terms:
            if term.lower() in text.lower():
                hits.append(f"{path.relative_to(repo_root)} contains a forbidden term")
    assert hits == []


def test_no_user_profile_paths(repo_root):
    this_file = repo_root / "tests" / "test_reusability_guards.py"
    hits = []
    for path in _text_files(repo_root):
        if path == this_file:
            continue
        for match in USER_PROFILE_PATH.finditer(path.read_text(encoding="utf-8", errors="ignore")):
            hits.append(f"{path.relative_to(repo_root)}: {match.group(0)}")
    assert hits == [], "Use <repo-root> or relative paths, not a personal profile path"


def test_no_secret_patterns(repo_root):
    this_file = repo_root / "tests" / "test_reusability_guards.py"
    api_key_literal = re.compile(r"api-key:\s*['\"]?[A-Za-z0-9_-]{12,}", re.IGNORECASE)
    hits = []
    for path in _text_files(repo_root):
        if path == this_file:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if api_key_literal.search(text) or "AccountKey=" in text or "-----BEGIN" in text:
            hits.append(str(path.relative_to(repo_root)))
    assert hits == []


# Internal authoring-tool names and sales/process jargon have no meaning for readers outside
# the original authoring team, so they must not appear in published files.
INTERNAL_TERMS = re.compile(
    r"demo-pattern-authoring|azure-architecture-diagrams|daily[_ ]?driver|MCAPS|\bMCEM\b|\bMSX\b|\bTPID\b|\bCSAM\b"
    r"|hard[- ]rules?\s*#|authoring gate|Copilot CLI session|\bSolution Engineers?\b|\bsellers?\b|\baccount team\b"
    r"|hands-on-keyboard|Technical Close Plan|\bwin plan\b|\bsolution play\b|\bMACC\b|Azure Consumed Revenue"
    r"|consumption uplift|Tech Elevate|Cloud Accelerate Factory|Viva Engage|\bSeismic\b|microsoft\.sharepoint\.com"
    r"|\binternal[- ]only\b|Microsoft[- ]internal|not for customer distribution|\btalk track\b",
    re.IGNORECASE,
)


def test_no_internal_terminology(repo_root):
    this_file = repo_root / "tests" / "test_reusability_guards.py"
    hits = []
    for path in _text_files(repo_root):
        if path == this_file:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), 1):
            for match in INTERNAL_TERMS.finditer(line):
                hits.append(f"{path.relative_to(repo_root)}:{lineno}: {match.group(0)}")
    assert hits == [], "Rewrite internal terminology for an external reader"

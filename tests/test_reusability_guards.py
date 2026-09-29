from __future__ import annotations

import os
import re

import pytest

DOMAIN_TERMS = ["Contoso", "service request", "lookup_request_status", "SR-10"]
# Customer-identifying terms are deliberately NOT listed in this committed file (that
# would leak them). Put one term per line in the gitignored
# tests/forbidden-terms.local.txt, or set FORBIDDEN_TERMS="term1,term2".
FORBIDDEN_TERMS_FILE = "forbidden-terms.local.txt"
USER_PROFILE_PATH = re.compile(r"\b[A-Za-z]:\\Users\\[A-Za-z0-9._-]+|/home/[a-z0-9._-]+/|/Users/[A-Za-z0-9._-]+/")
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


def _text_files(root):
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
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

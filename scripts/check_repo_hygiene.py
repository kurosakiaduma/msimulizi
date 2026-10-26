"""
check_repo_hygiene.py

Repository hygiene guard. Fails the build (exit code 1) if any of:
  1. Model files are present (.pkl, .tflite, .onnx, .h5)
  2. Raw data folders are present (data/, raw_data/, open_data/, statsbomb_data/, datasets/)
  3. Secrets patterns are found (private keys, bare connection strings, API key literals)
  4. Any commit in the repository is dated before 29 September 2026

Usage:
    python scripts/check_repo_hygiene.py

Exit code 0 = all checks passed.
Exit code 1 = one or more violations found (details on stderr).
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent

HACKATHON_START = datetime(2026, 9, 29, 0, 0, 0, tzinfo=timezone.utc)

MODEL_FILE_EXTENSIONS = {".pkl", ".tflite", ".onnx", ".h5"}

RAW_DATA_FOLDERS = {
    "data",
    "raw_data",
    "open_data",
    "statsbomb_data",
    "datasets",
}

# Patterns that suggest hardcoded secrets in source files.
# Each is a (label, regex) pair. We scan only text files in committed paths.
SECRETS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private key header", re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("Azure storage connection string", re.compile(
        r"DefaultEndpointsProtocol=https;AccountName=\S+;AccountKey=[A-Za-z0-9+/=]{20,}"
    )),
    ("Azure SAS token", re.compile(r"sv=\d{4}-\d{2}-\d{2}&s[spqr]{1,4}=\S{20,}")),
    ("OpenAI/Foundry API key literal", re.compile(r"sk-[A-Za-z0-9]{32,}")),
    ("Generic high-entropy API key", re.compile(
        r"(?i)(api[_-]?key|apikey|secret[_-]?key)\s*[=:]\s*['\"]?[A-Za-z0-9+/]{32,}['\"]?"
    )),
]

# File extensions to scan for secrets (binary files skipped)
TEXT_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml",
    ".md", ".txt", ".toml", ".cfg", ".ini", ".env", ".sh", ".bash",
}

# Directories to skip when scanning (always gitignored or not source)
SKIP_DIRS = {".git", ".venv", "venv", "env", "node_modules", ".next", "__pycache__"}

# ---------------------------------------------------------------------------
# Check 1: Model files
# ---------------------------------------------------------------------------

def check_model_files() -> list[str]:
    errors: list[str] = []
    for path in REPO_ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix.lower() in MODEL_FILE_EXTENSIONS:
            errors.append(f"Model file found: {path.relative_to(REPO_ROOT)}")
    return errors


# ---------------------------------------------------------------------------
# Check 2: Raw data folders
# ---------------------------------------------------------------------------

def check_raw_data_folders() -> list[str]:
    errors: list[str] = []
    for folder_name in RAW_DATA_FOLDERS:
        candidate = REPO_ROOT / folder_name
        if candidate.is_dir():
            errors.append(f"Raw data folder found: {folder_name}/")
    return errors


# ---------------------------------------------------------------------------
# Check 3: Secrets patterns
# ---------------------------------------------------------------------------

def check_secrets_patterns() -> list[str]:
    errors: list[str] = []
    for path in REPO_ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        # Skip .env files — they are gitignored and expected to hold secrets locally
        if path.name.startswith(".env"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, pattern in SECRETS_PATTERNS:
            if pattern.search(text):
                errors.append(
                    f"Possible secret ({label}) in {path.relative_to(REPO_ROOT)}"
                )
                break  # one error per file is enough
    return errors


# ---------------------------------------------------------------------------
# Check 4: Commit dates before 29 September 2026
# ---------------------------------------------------------------------------

def check_commit_dates() -> list[str]:
    errors: list[str] = []
    try:
        result = subprocess.run(
            ["git", "log", "--format=%H %aI"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return [f"Could not run git log: {exc}"]

    if result.returncode != 0:
        # Not a git repo or no commits — not a CI failure here
        return []

    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        commit_hash, iso_date = parts
        try:
            # Python's fromisoformat handles the +HH:MM offset from git %aI
            commit_dt = datetime.fromisoformat(iso_date)
            if commit_dt.tzinfo is None:
                commit_dt = commit_dt.replace(tzinfo=timezone.utc)
            if commit_dt < HACKATHON_START:
                errors.append(
                    f"Commit {commit_hash[:10]} dated {iso_date} is before "
                    f"29 September 2026 (hackathon start)"
                )
        except ValueError:
            errors.append(f"Could not parse date '{iso_date}' for commit {commit_hash[:10]}")

    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    all_errors: list[str] = []

    print("── Checking for model files ──")
    errs = check_model_files()
    if errs:
        all_errors.extend(errs)
    else:
        print("  ✓ No model files found")

    print("── Checking for raw data folders ──")
    errs = check_raw_data_folders()
    if errs:
        all_errors.extend(errs)
    else:
        print("  ✓ No raw data folders found")

    print("── Checking for secrets patterns ──")
    errs = check_secrets_patterns()
    if errs:
        all_errors.extend(errs)
    else:
        print("  ✓ No secrets patterns found")

    print("── Checking commit dates ──")
    errs = check_commit_dates()
    if errs:
        all_errors.extend(errs)
    else:
        print("  ✓ All commits dated on or after 29 September 2026")

    if all_errors:
        print("\n── HYGIENE VIOLATIONS ──", file=sys.stderr)
        for e in all_errors:
            print(f"  ✗ {e}", file=sys.stderr)
        return 1

    print("\n✓ Repository hygiene checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

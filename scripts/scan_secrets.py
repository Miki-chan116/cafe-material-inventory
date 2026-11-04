"""Small fail-closed local pattern scan; supplement with maintained scanner later."""

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
SKIP_DIRS = {".git", ".venv", ".pytest_cache", "__pycache__", "instance"}


def scan_text(text):
    return any(pattern.search(text) for pattern in PATTERNS)


def files():
    for path in ROOT.rglob("*"):
        if path.is_file() and not any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            yield path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()
    findings = []
    for path in args.paths or files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if scan_text(text):
            findings.append(str(path))
    for path in findings:
        print(f"Possible secret pattern: {path}")
    if findings:
        return 2
    print("No configured secret patterns found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

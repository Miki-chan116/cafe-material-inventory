"""Classify changed paths. Local advisory check; GitHub enforcement is not configured."""

import argparse
import fnmatch
import json
import subprocess


RULES = {
    "database_tests": ["tests/test_inventory.py", "tests/test_db.py", "tests/test_*db*.py",
                       "tests/test_*database*.py", "tests/db/**"],
    "auth_tests": ["tests/test_auth.py", "tests/test_*auth*.py", "tests/test_*permission*.py",
                   "tests/auth/**", "tests/permissions/**"],
    "secret_tests": ["tests/test_secrets.py", "tests/test_secret_scan.py", "tests/test_*secret*.py",
                     "tests/test_*crypt*.py"],
    "security_code": ["app/__init__.py", "app/security/**", "app/auth/**", "app/config/**",
                      "app/*crypto*.py", "app/**/*crypto*.py", "app/*auth*.py", "app/*permission*.py",
                      "app/*encrypt*.py", "app/*decrypt*.py", "scripts/scan_secrets.py"],
    "ci_cd": [".github/workflows/**", ".github/dependabot.yml", "render.yaml", "Dockerfile*",
              "compose*.yaml", "compose*.yml", "Procfile"],
    "hooks_harness": [".codex/**", "AGENTS.md", "harness/**", "scripts/check_critical.py",
                       "scripts/probe_hooks.py"],
    "security_policy": [".github/CODEOWNERS", ".gitignore", ".env.example", "pyproject.toml",
                        "requirements*.txt", "requirements*.lock", "uv.lock", "poetry.lock",
                        "Pipfile.lock", "tests/conftest.py", "tests/test_policy.py"],
    "database_schema": ["migrations/**", "app/models/**", "app/*model*.py", "app/*database*.py"],
}


def classify_paths(paths):
    result = {}
    for path in paths:
        categories = [category for category, patterns in RULES.items()
                      if any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)]
        if not categories and path.endswith(".py") and path.startswith(("app/", "tests/", "scripts/")):
            categories = ["unclassified_python"]
        if categories:
            result[path] = categories
    return result


def parse_name_status(raw):
    return [path for change in parse_changes(raw) for path in change["paths"]]


def parse_changes(raw):
    fields = raw.decode("utf-8", "surrogateescape").split("\0")
    changes = []
    i = 0
    while i < len(fields) and fields[i]:
        status = fields[i]
        if status.startswith(("R", "C")):
            if i + 2 >= len(fields):
                raise ValueError("Incomplete rename/copy record")
            changes.append({"status": status, "paths": fields[i + 1:i + 3]})
            i += 3
        else:
            if i + 1 >= len(fields):
                raise ValueError("Incomplete change record")
            changes.append({"status": status, "paths": [fields[i + 1]]})
            i += 2
    return changes


def changed_paths(base):
    raw = subprocess.check_output(["git", "diff", "--name-status", "-z", f"{base}...HEAD"])
    return parse_name_status(raw)


def collect_changes(base=None, cwd=None):
    commands = []
    if base:
        commands.append(["git", "diff", "--name-status", "-z", f"{base}...HEAD"])
    commands.extend([["git", "diff", "--cached", "--name-status", "-z"],
                     ["git", "diff", "--name-status", "-z"]])
    changes = [change for command in commands
               for change in parse_changes(subprocess.check_output(command, cwd=cwd))]
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=cwd)
    changes.extend({"status": "A?", "paths": [path]} for path in
                   untracked.decode("utf-8", "surrogateescape").split("\0") if path)
    seen = set()
    unique = []
    for change in changes:
        key = (change["status"], *change["paths"])
        if key not in seen:
            unique.append(change)
            seen.add(key)
    return unique


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", help="PR base ref; diff against its merge base")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    changes = ([{"status": "SIMULATED", "paths": [path]} for path in args.paths]
               if args.paths else collect_changes(args.base))
    for change in changes:
        matches = classify_paths(change["paths"])
        if change["status"].startswith(("A", "R")):
            for path in change["paths"][-1:]:
                if path not in matches:
                    matches[path] = ["new_file_review"]
        change["matches"] = matches
    critical = any(change["matches"] for change in changes)
    print(json.dumps({"critical": critical, "changes": changes}, ensure_ascii=False, indent=2))
    return 2 if critical else 0


if __name__ == "__main__":
    raise SystemExit(main())

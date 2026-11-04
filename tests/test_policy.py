import subprocess

from scripts.check_critical import classify_paths, collect_changes, parse_changes, parse_name_status
from scripts.probe_hooks import probe, probe_event


def test_critical_change_detection():
    result = classify_paths(["tests/test_auth.py", ".github/workflows/ci.yml", ".codex/hooks.json",
                             "README.md", "app/templates/index.html"])
    assert result["tests/test_auth.py"] == ["auth_tests"]
    assert result[".github/workflows/ci.yml"] == ["ci_cd"]
    assert result[".codex/hooks.json"] == ["hooks_harness"]
    assert "README.md" not in result


def test_rename_checks_old_and_new_paths():
    paths = parse_name_status(b"R100\0tests/test_auth.py\0docs/renamed.py\0")
    assert paths == ["tests/test_auth.py", "docs/renamed.py"]
    assert classify_paths(paths)["tests/test_auth.py"] == ["auth_tests"]


def test_hook_before_after_with_inert_probe():
    assert probe(False, "printf HOOK_BLOCK_PROBE") == "not_intercepted"
    assert probe(True, "printf HOOK_BLOCK_PROBE") == "denied"
    assert probe(True, "git push") == "denied"
    assert probe(True, "pwd") == "allowed"
    assert probe_event(True, "apply_patch",
                       "*** Begin Patch\n*** Update File: tests/test_policy.py\n@@\n-old\n+new\n*** End Patch") == "warned"


def test_expanded_critical_paths_and_unknown_python():
    paths = ["tests/test_policy.py", "tests/test_db.py", "tests/test_new_database.py",
             "tests/test_permissions.py", "app/crypto.py", "app/new_feature.py",
             ".codex/hooks/pre_tool_use.py", "scripts/check_critical.py",
             "scripts/scan_secrets.py", ".github/workflows/ci.yml",
             "requirements.lock", "render.yaml", "Dockerfile"]
    result = classify_paths(paths)
    assert set(result) == set(paths)
    assert result["tests/test_db.py"] == ["database_tests"]
    assert result["app/crypto.py"] == ["security_code"]
    assert result["app/new_feature.py"] == ["unclassified_python"]
    assert result["tests/test_policy.py"] == ["security_policy"]


def test_change_add_delete_rename_statuses_are_preserved():
    changes = parse_changes(b"M\0scripts/check_critical.py\0A\0tests/test_db.py\0"
                            b"D\0.codex/hooks.json\0R100\0app/crypto.py\0docs/moved.py\0")
    assert [change["status"] for change in changes] == ["M", "A", "D", "R100"]
    assert changes[-1]["paths"] == ["app/crypto.py", "docs/moved.py"]
    assert all(classify_paths(change["paths"]) for change in changes)


def test_git_change_types_in_disposable_repository(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.name", "Local Test")
    git("config", "user.email", "local-test@example.invalid")
    for relative in ["tests/test_policy.py", ".codex/hooks.json", "app/crypto.py"]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative)
    git("add", ".")
    git("commit", "-qm", "baseline")
    (tmp_path / "tests/test_policy.py").write_text("changed")
    (tmp_path / ".codex/hooks.json").unlink()
    git("mv", "app/crypto.py", "app/crypto_new.py")
    (tmp_path / "tests/test_db.py").write_text("new")
    git("add", "-A")
    changes = collect_changes("HEAD", cwd=tmp_path)
    statuses = {change["status"][0] for change in changes}
    assert statuses == {"M", "A", "D", "R"}
    assert any(change["paths"] == ["app/crypto.py", "app/crypto_new.py"] for change in changes)

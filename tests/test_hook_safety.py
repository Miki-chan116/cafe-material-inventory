"""All shell inputs are text passed to the hook; no input is executed."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


HOOK_PATH = Path(__file__).resolve().parents[1] / ".codex/hooks/pre_tool_use.py"
spec = spec_from_file_location("audit_hook", HOOK_PATH)
hook = module_from_spec(spec)
spec.loader.exec_module(hook)


@pytest.mark.parametrize("command", [
    "pwd", "git status --short", "git -C . log -1", "git --version", "printf 'README says git push'",
    "printf '$(git push)'", "sh -c \"printf 'README says git push'\"",
])
def test_safe_shell_text_is_allowed(command):
    assert hook.check_shell(command) is None


@pytest.mark.parametrize("command", [
    "git push", "git -C . push", "git --git-dir=/tmp/example push",
    "pwd && git push", "git status; git -C . push", "git status\ngit push",
    "sh -c 'git push'", "env X=1 git push", "command git push", "exec git push",
    "sh -c '$COMMAND push'",
    "echo $(git push)", "bash script.sh",
])
def test_denied_or_unparsed_shell_text_is_blocked(command):
    assert hook.check_shell(command) is not None


def test_patch_warning_and_outside_rejection():
    critical = "*** Begin Patch\n*** Update File: tests/test_policy.py\n@@\n-old\n+new\n*** End Patch"
    normal = "*** Begin Patch\n*** Update File: README.md\n@@\n-old\n+new\n*** End Patch"
    unknown_add = "*** Begin Patch\n*** Add File: notes.txt\n+demo\n*** End Patch"
    outside = "*** Begin Patch\n*** Update File: ../other-project/file.py\n@@\n-old\n+new\n*** End Patch"
    assert hook.check_patch(critical)[0] == "warn"
    assert hook.check_patch(normal) is None
    assert hook.check_patch(unknown_add)[0] == "warn"
    assert hook.check_patch(outside)[0] == "deny"
    assert hook.check_patch("*** Begin Patch\n*** End Patch")[0] == "deny"


def test_post_tool_event_is_not_configured():
    assert hook.evaluate({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                          "tool_input": {"command": "git push"}}) is None


def test_known_interpreter_bypass_is_visible():
    # A shell-string guard cannot inspect arbitrary Python source safely.
    assert hook.check_shell("python -c 'print(1)'") is None


def test_conservative_rejection_of_safe_redirection_is_visible():
    # This is a deliberate false positive until redirection targets are parsed.
    assert hook.check_shell("cat < README.md") is not None

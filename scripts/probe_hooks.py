"""Simulate hook dispatch with inert inputs; does not invoke a shell command."""

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".codex" / "hooks.json"
HOOK = ROOT / ".codex" / "hooks" / "pre_tool_use.py"


def probe(enabled, command):
    return probe_event(enabled, "Bash", command)


def probe_event(enabled, tool, command):
    if not enabled:
        return "not_intercepted"
    config = json.loads(CONFIG.read_text())
    if "PreToolUse" not in config["hooks"]:
        return "not_intercepted"
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"command": command}}
    result = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
                            capture_output=True, check=False, cwd=ROOT)
    if result.returncode != 0:
        return "hook_error"
    if not result.stdout.strip():
        return "allowed"
    output = json.loads(result.stdout)["hookSpecificOutput"]
    return "denied" if output.get("permissionDecision") == "deny" else "warned"


if __name__ == "__main__":
    safe_probe = "printf HOOK_BLOCK_PROBE"
    dangerous_text = "git push"  # text only; never executed
    print(json.dumps({"before_safe_probe": probe(False, safe_probe),
                      "after_safe_probe": probe(True, safe_probe),
                      "after_dangerous_text": probe(True, dangerous_text),
                      "after_normal_command": probe(True, "pwd"),
                      "after_critical_patch": probe_event(True, "apply_patch",
                          "*** Begin Patch\n*** Update File: tests/test_policy.py\n@@\n-old\n+new\n*** End Patch")}, ensure_ascii=False))

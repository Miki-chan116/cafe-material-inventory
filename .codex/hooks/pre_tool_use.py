"""Best-effort local guard; it never executes pending tool input."""

import json
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.check_critical import classify_paths  # noqa: E402

SEPARATORS = set(";&|(){}\n")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
PATCH_HEADER = re.compile(r"^\*\*\* (Add File|Update File|Delete File|Move to): (.+)$")
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--exec-path"}
GIT_FLAG_OPTIONS = {"--version", "--help", "--no-pager", "-P", "--paginate", "-p", "--bare", "--no-optional-locks",
                    "--literal-pathspecs", "--glob-pathspecs", "--noglob-pathspecs", "--icase-pathspecs"}


def has_dynamic_expansion(source):
    quote = None
    escaped = False
    for index, char in enumerate(source):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote != "'":
            escaped = True
            continue
        if char == "'" and quote != '"':
            quote = None if quote == "'" else "'"
            continue
        if char == '"' and quote != "'":
            quote = None if quote == '"' else '"'
            continue
        if quote != "'" and (char == "`" or source[index:index + 2] == "$("):
            return True
    return False


def git_subcommand(words):
    index = 1
    while index < len(words):
        word = words[index]
        if word in GIT_VALUE_OPTIONS:
            index += 2
            if index > len(words):
                return None, "Git オプションの引数が不明です。"
        elif word in GIT_FLAG_OPTIONS or word == "--":
            index += 1
            if word == "--":
                break
        elif word.startswith(("--git-dir=", "--work-tree=", "--namespace=", "--config-env=", "--exec-path=")):
            index += 1
        elif (word.startswith("-C") or word.startswith("-c")) and len(word) > 2:
            index += 1
        elif word.startswith("-"):
            return None, "未対応の Git グローバルオプションを拒否しました。"
        else:
            break
    return words[index:], None


def check_words(words, depth):
    if depth > 4:
        return "入れ子のシェル実行を解析できません。"
    while words and ASSIGNMENT.match(words[0]):
        words = words[1:]
    if not words:
        return None
    executable = Path(words[0]).name
    args = words[1:]
    if "$" in executable or "`" in executable or "*" in executable or "?" in executable:
        return "動的な実行コマンドを解析できません。"
    if executable in {"sudo", "eval"}:
        return "権限昇格または動的評価を拒否しました。"
    if executable in {"if", "then", "else", "elif", "for", "while", "until", "case", "do", "function"}:
        return "シェル制御構文を解析できません。"
    if executable == "env":
        while args and (ASSIGNMENT.match(args[0]) or args[0] in {"-i", "--ignore-environment"}):
            args = args[1:]
        if args and args[0].startswith("-"):
            return "env のオプションを解析できません。"
        return check_words(args, depth + 1)
    if executable in {"command", "exec", "nohup", "time"}:
        if args and args[0] in {"-v", "-V"}:
            return None
        return check_words(args, depth + 1)
    if executable in {"sh", "bash", "zsh", "dash"}:
        if args and args[0].startswith("-") and "c" in args[0][1:] and len(args) >= 2:
            return check_shell(args[1], depth + 1)
        return "シェルスクリプトの内容を解析できません。"
    if executable == "git":
        sub, error = git_subcommand(words)
        if error:
            return error
        if sub and sub[0] == "push":
            return "Git push を拒否しました。"
        if sub and sub[0] == "reset" and "--hard" in sub[1:]:
            return "破壊的な Git reset を拒否しました。"
    if executable == "rm":
        flags = set("".join(arg[1:] for arg in args if arg.startswith("-") and not arg.startswith("--")))
        if ("r" in flags or "R" in flags or "--recursive" in args) and ("f" in flags or "--force" in args):
            return "再帰的な強制削除を拒否しました。"
    if executable == "clasp" and args and args[0] == "push":
        return "外部公開を拒否しました。"
    if executable == "render" and args and args[0] == "deploy":
        return "外部公開を拒否しました。"
    if executable == "printf" and args == ["HOOK_BLOCK_PROBE"]:
        return "無害な模擬操作を実験用に拒否しました。"
    return None


def check_shell(source, depth=0):
    if has_dynamic_expansion(source):
        return "動的なシェル展開を解析できません。"
    try:
        lexer = shlex.shlex(source, posix=True, punctuation_chars=";&|(){}<>\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return "シェル構文を解析できません。"
    command = []
    for token in tokens + [";"]:
        if token and all(char in SEPARATORS or char in "<>" for char in token):
            if "<" in token or ">" in token:
                return "リダイレクトを解析できません。"
            reason = check_words(command, depth)
            if reason:
                return reason
            command = []
        else:
            command.append(token)
    return None


def check_patch(source):
    entries = [(match.group(1), match.group(2).strip()) for line in source.splitlines()
               if (match := PATCH_HEADER.match(line))]
    paths = [path for _, path in entries]
    if not paths or not source.startswith("*** Begin Patch") or "*** End Patch" not in source:
        return "deny", "パッチの対象ファイルを確認できません。"
    for path in paths:
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            return "deny", "プロジェクト外へのパッチを拒否しました。"
    matches = classify_paths(paths)
    for action, path in entries:
        if action in {"Add File", "Move to"} and path not in matches:
            matches[path] = ["new_file_review"]
    if matches:
        return "warn", "重要ファイルへの変更: " + ", ".join(matches)
    return None


def evaluate(payload):
    if payload.get("hook_event_name") != "PreToolUse":
        return None
    tool = payload.get("tool_name", "")
    data = payload.get("tool_input", {})
    source = data.get("command") if isinstance(data, dict) else None
    if not isinstance(source, str):
        return ("deny", "ツール入力を確認できません。") if tool in {"Bash", "apply_patch"} else None
    if tool == "Bash":
        reason = check_shell(source)
        return ("deny", reason) if reason else None
    if tool == "apply_patch":
        return check_patch(source)
    return None


def main():
    try:
        decision = evaluate(json.load(sys.stdin))
    except (ValueError, TypeError):
        print("Hook の入力を解釈できません。", file=sys.stderr)
        return 2
    if decision:
        kind, reason = decision
        if kind == "deny":
            output = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}
        else:
            output = {"systemMessage": reason,
                      "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": reason}}
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

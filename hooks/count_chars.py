#!/usr/bin/env python3
"""
PostToolUse hook — counts characters in a file after each edit.
Receives hook JSON via stdin and prints a status line to stdout.
"""
import json
import sys
import os

def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Resolve the file path depending on which tool fired
    file_path = tool_input.get("file_path") or tool_input.get("path")
    if not file_path:
        sys.exit(0)

    # Skip non-source-code files (plan files, markdown, configs)
    skip_patterns = (".claude/plans/", ".claude/memory/")
    if any(p in file_path.replace("\\", "/") for p in skip_patterns):
        sys.exit(0)

    if not os.path.isfile(file_path):
        sys.exit(0)

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        sys.exit(0)

    total_chars = len(content)
    non_whitespace = len(content.replace(" ", "").replace("\n", "").replace("\t", "").replace("\r", ""))
    lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    filename = os.path.basename(file_path)

    print(
        f"[char-counter] {filename}: "
        f"{total_chars:,} chars total | "
        f"{non_whitespace:,} non-whitespace | "
        f"{lines:,} lines",
        flush=True
    )

if __name__ == "__main__":
    main()

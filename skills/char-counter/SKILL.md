---
name: char-counter
description: >
  Counts and reports the number of characters in a file. Reports total characters,
  non-whitespace characters, and line count. Use this skill whenever the user asks
  about file size in characters, character counts, or wants to know how long a file
  is. Also triggers automatically after every file edit via the PostToolUse hook —
  the hook output appears in the status line. Invoke manually when the user says
  things like "how many chars", "count characters", "how big is this file",
  "character count", or "how long is X file".
---

# char-counter

Count and report characters in a file.

## When invoked manually

Read the target file, then print a summary:

```
File: <filename>
Total characters:          X,XXX
Non-whitespace characters: X,XXX
Lines:                       XXX
```

If the user asks about multiple files, report each on its own line and add a
total row at the bottom.

## Hook mode (automatic)

The `count_chars.py` hook fires automatically via `PostToolUse` after every
`Edit`, `Write`, or `MultiEdit` tool call. Its one-line output is shown in the
Claude Code status bar — no extra action is needed from you unless the user asks
a follow-up question about the count.

## Edge cases

- Binary files: report "binary file — character count may be unreliable" and
  give the byte size instead.
- Empty files: report 0 for all counts.
- Very large files (>1 MB): note the size and still report the counts.

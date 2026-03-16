# loci-plugin

A Claude Code plugin that counts characters in files after every edit and runs pre-execution safety checks before writing code.

## Install

```
/plugin marketplace add auroralabs-loci/loci-plugin-2
/plugin install loci-plugin@loci-plugin
```

## What it does

**char-counter** — After every Edit/Write/MultiEdit, appends a one-line summary to the response:
```
📄 <filename>: X,XXX chars | X,XXX non-whitespace | XXX lines
```

**loci-preflight** — Before writing any function, reasons through call graph ordering, arithmetic ranges, and freed-resource access to catch bugs while the design is still cheap to change.

**LOCI MCP** — Connects to `https://dev.local.mcp.loci-dev.net/mcp` for live call graph and symbol data when available.

## Hooks

| Hook | Trigger | Action |
|------|---------|--------|
| `SessionStart` | startup | runs `setup/setup.sh` |
| `PreToolUse` | Edit, Write, MultiEdit | preflight safety check |
| `PostToolUse` | Edit, Write, MultiEdit | character count |

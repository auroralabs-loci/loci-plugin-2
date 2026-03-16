#!/usr/bin/env python3
"""
PreToolUse hook — LOCI preflight static scanner.

Fires before Write/Edit/MultiEdit. If the incoming content introduces a new
function definition it runs three fast pattern checks:
  1. Call graph ordering  (forward-ref / recursion hazards)
  2. Arithmetic ranges    (overflow, wrap, bad shifts, signed/unsigned mix)
  3. Freed-resource access (use-after-free, double-free, dangling refs)

Findings are printed to stdout so Claude sees them before writing.
The hook always exits 0 (advisory, never blocking) — the skill layer decides
whether to PROCEED, PROCEED WITH CAUTION, or STOP.
"""

import json
import re
import sys
import os
from dataclasses import dataclass, field
from typing import Optional

# ── data types ────────────────────────────────────────────────────────────────

@dataclass
class Finding:
    check: str          # "call_graph" | "arithmetic" | "resources"
    severity: str       # "RISK" | "BLOCK"
    message: str
    line: Optional[int] = None

# ── helpers ───────────────────────────────────────────────────────────────────

_FUNC_DEF = re.compile(
    r"""
    (?:[\w:<>*&\s]+\s+)?          # optional return type
    (?P<name>~?[A-Za-z_]\w*)      # function/destructor name
    \s*\(                         # opening paren
    [^)]*                         # params (simplified)
    \)\s*                         # closing paren + optional ws
    (?:const\s*|noexcept\s*|->.*?)* # trailing specifiers
    \{                            # opening brace
    """,
    re.VERBOSE,
)

_CALL_SITE      = re.compile(r'\b([A-Za-z_]\w*)\s*\(')
_DELETE_PTR     = re.compile(r'\bdelete\s+(?:\[\]\s*)?(\w+)')
_FREE_PTR       = re.compile(r'\bfree\s*\(\s*(\w+)\s*\)')
_DEREF          = re.compile(r'(\w+)\s*(?:->|\[\s*\d)')
_RETURN_REF     = re.compile(r'\breturn\s+(?:&|\*?\s*(?:std::)?ref\s*\()')
_MOVE_USE       = re.compile(r'std::move\s*\(\s*(\w+)\s*\)')
_OVERFLOW_EXPR  = re.compile(r'\b(int|long|short)\b[^;=\n]*[=+\-*]\s*\w+\s*[*+]\s*\w+')
_UNSIGNED_SUB   = re.compile(r'\b(size_t|unsigned\s+\w*)\b[^;=\n]*-\s*\d')
_SHIFT          = re.compile(r'<<\s*(\d+)')
_SIGNED_UNSIG   = re.compile(r'(?:int|long|short)\s+\w+\s*[<>=!]=?\s*(?:size_t|unsigned)')
_RECURSIVE_CALL = re.compile(r'(?P<outer>[A-Za-z_]\w*)\s*\([^)]*\)[^{]*\{[^}]*(?P=outer)\s*\(')

# ── check implementations ─────────────────────────────────────────────────────

def _check_call_graph(lines: list[str], func_name: str) -> list[Finding]:
    findings = []
    body = "\n".join(lines)

    # Recursion without obvious base-case guard
    if re.search(rf'\b{re.escape(func_name)}\s*\(', body):
        # A recursive call exists — look for an early-return guard
        if not re.search(r'\bif\b[^{]*\breturn\b', body):
            findings.append(Finding(
                "call_graph", "RISK",
                f"'{func_name}' calls itself but has no visible early-return base case — "
                "unbounded recursion risk.",
            ))

    # Static/global initializer calling into another symbol (init-order fiasco)
    for i, ln in enumerate(lines, 1):
        if re.search(r'\bstatic\b.*=.*\(', ln) and '::' in ln:
            findings.append(Finding(
                "call_graph", "RISK",
                "Static initializer calls across TU boundary — "
                "initialization-order fiasco possible.",
                line=i,
            ))

    return findings


def _check_arithmetic(lines: list[str]) -> list[Finding]:
    findings = []
    for i, ln in enumerate(lines, 1):
        if _OVERFLOW_EXPR.search(ln):
            findings.append(Finding(
                "arithmetic", "RISK",
                f"Possible signed-integer overflow: '{ln.strip()}'",
                line=i,
            ))
        if _UNSIGNED_SUB.search(ln):
            findings.append(Finding(
                "arithmetic", "RISK",
                f"Unsigned subtraction may wrap to a huge value: '{ln.strip()}'",
                line=i,
            ))
        m = _SHIFT.search(ln)
        if m and int(m.group(1)) >= 32:
            findings.append(Finding(
                "arithmetic", "BLOCK",
                f"Left-shift by {m.group(1)} bits — likely exceeds type width: '{ln.strip()}'",
                line=i,
            ))
        if _SIGNED_UNSIG.search(ln):
            findings.append(Finding(
                "arithmetic", "RISK",
                f"Signed/unsigned comparison without explicit cast: '{ln.strip()}'",
                line=i,
            ))
    return findings


def _check_resources(lines: list[str]) -> list[Finding]:
    findings = []
    body_text = "\n".join(lines)

    freed: set[str] = set()
    for i, ln in enumerate(lines, 1):
        # Track freed pointers
        for m in _DELETE_PTR.finditer(ln):
            freed.add(m.group(1))
        for m in _FREE_PTR.finditer(ln):
            freed.add(m.group(1))

        # Dereference after free
        for m in _DEREF.finditer(ln):
            ptr = m.group(1)
            if ptr in freed:
                findings.append(Finding(
                    "resources", "BLOCK",
                    f"Use-after-free: '{ptr}' is dereferenced after delete/free.",
                    line=i,
                ))

        # Returning address-of local / reference
        if _RETURN_REF.search(ln):
            # Heuristic: if it's returning &<local> it's dangerous
            if re.search(r'return\s+&\s*\w', ln):
                findings.append(Finding(
                    "resources", "BLOCK",
                    f"Returning address of (likely) local variable — dangling reference.",
                    line=i,
                ))

    # Double-free: same pointer freed twice
    freed_list: list[str] = []
    for ln in lines:
        for m in _DELETE_PTR.finditer(ln):
            freed_list.append(m.group(1))
        for m in _FREE_PTR.finditer(ln):
            freed_list.append(m.group(1))
    seen: set[str] = set()
    for ptr in freed_list:
        if ptr in seen:
            findings.append(Finding(
                "resources", "BLOCK",
                f"Double-free detected on '{ptr}'.",
            ))
        seen.add(ptr)

    # std::move followed by use of the same variable
    moved: set[str] = set()
    for i, ln in enumerate(lines, 1):
        for m in _MOVE_USE.finditer(ln):
            moved.add(m.group(1))
        for var in list(moved):
            # Any non-assignment use after move
            if re.search(rf'\b{re.escape(var)}\b', ln) and not _MOVE_USE.search(ln):
                if not re.search(rf'\b{re.escape(var)}\s*=', ln):
                    findings.append(Finding(
                        "resources", "RISK",
                        f"'{var}' may be used after std::move() without reassignment.",
                        line=i,
                    ))
                    moved.discard(var)  # report once

    return findings

# ── main ──────────────────────────────────────────────────────────────────────

def extract_code(tool_name: str, tool_input: dict) -> Optional[str]:
    """Pull the incoming code text from whichever write-family tool fired."""
    if tool_name == "Write":
        return tool_input.get("content", "")
    if tool_name in ("Edit", "MultiEdit"):
        # new_string is the content being inserted
        if tool_name == "Edit":
            return tool_input.get("new_string", "")
        edits = tool_input.get("edits", [])
        return "\n".join(e.get("new_string", "") for e in edits)
    return None


def find_new_functions(code: str) -> list[tuple[str, list[str]]]:
    """Return list of (func_name, body_lines) for each function body found."""
    results = []
    for m in _FUNC_DEF.finditer(code):
        name = m.group("name")
        # Skip keywords that look like function calls
        if name in {"if", "while", "for", "switch", "catch", "namespace", "return"}:
            continue
        # Grab lines starting at the match
        start = code.rfind("\n", 0, m.start()) + 1
        body_start = code.index("{", m.start())
        # Walk to matching brace
        depth = 0
        pos = body_start
        for ch in code[body_start:]:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            pos += 1
        body = code[body_start:pos + 1]
        results.append((name, body.splitlines()))
    return results


def render_report(func_name: str, findings: list[Finding]) -> str:
    if not findings:
        return f"[loci-preflight] {func_name}: all clear"

    lines = [f"[loci-preflight] {func_name}"]
    sections = {"call_graph": [], "arithmetic": [], "resources": []}
    for f in findings:
        sections[f.check].append(f)

    labels = {"call_graph": "Call graph", "arithmetic": "Arithmetic", "resources": "Resources"}
    for key, label in labels.items():
        items = sections[key]
        if not items:
            lines.append(f"  {label}: OK")
        else:
            for item in items:
                loc = f" (line {item.line})" if item.line else ""
                icon = "✗ BLOCK" if item.severity == "BLOCK" else "⚠ RISK"
                lines.append(f"  {label}: {icon}{loc} — {item.message}")

    block_count = sum(1 for f in findings if f.severity == "BLOCK")
    risk_count  = sum(1 for f in findings if f.severity == "RISK")
    if block_count:
        lines.append(f"  Decision: STOP — {block_count} blocking issue(s) found")
    elif risk_count:
        lines.append(f"  Decision: PROCEED WITH CAUTION — {risk_count} risk(s) flagged")

    return "\n".join(lines)


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    tool_name  = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    code = extract_code(tool_name, tool_input)
    if not code:
        sys.exit(0)

    functions = find_new_functions(code)
    if not functions:
        sys.exit(0)  # No new function body — nothing to check

    reports = []
    for func_name, body_lines in functions:
        findings = (
            _check_call_graph(body_lines, func_name)
            + _check_arithmetic(body_lines)
            + _check_resources(body_lines)
        )
        reports.append(render_report(func_name, findings))

    if reports:
        print("\n".join(reports), flush=True)

    sys.exit(0)  # Always advisory — skill layer decides whether to proceed


if __name__ == "__main__":
    main()

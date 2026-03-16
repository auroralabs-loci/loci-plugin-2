---
name: loci-preflight
description: >
  Pre-execution safety thinking: before writing or editing any function, reason
  through call graph ordering (CFI), arithmetic ranges, and freed-resource
  access to see the execution fit before touching the code. Run this during
  planning — not at write time. Invoke when the user says "write a function
  that...", "implement...", "add a method for...", "how should I...", or any
  time you are about to form a plan that involves writing new logic. Also invoke
  during /plan or thinking mode. Do not wait until you are at the keyboard —
  the point is to catch ordering, range, and resource problems while the design
  is still cheap to change.
---

# loci-preflight

This skill is a **thinking tool, not a write-gate**. Run it during planning —
while you are still deciding what to write — so the execution fit is visible
before any code changes. The output shapes how you write, not just whether.

## When to run

Run preflight as part of forming your plan, immediately after you understand
what function(s) you need to write and before you issue any Edit/Write call:

1. User describes the task
2. You read the relevant files to understand the call site and surrounding code
3. **← run preflight here, while thinking**
4. Adjust the plan based on findings
5. Write the code

If you are in `/plan` mode or generating a step-by-step approach, include the
preflight report as a section of the plan before listing the edit steps.

## The three checks

### 1. Call graph ordering (CFI)
*Will the call sequence be valid when this code runs?*

Before writing, trace the call graph forward from the new function:
- Which functions will this call? Are they already declared/defined in this TU?
  If not, note where forward declarations need to go.
- Can this call path reach itself (direct or indirect recursion) without a
  reachable base case? Flag unbounded recursion.
- What is the intended call order at the call site — who calls this function,
  and is there any ordering assumption (e.g. must be called after `init()`)?
  If yes, is that enforced, or just assumed?
- Static/global objects: will this be called during static initialization?
  If another TU's object is involved, initialization order is undefined.
- If LOCI MCP is available (`mcp__loci__*`), query the live call graph for the
  symbol. Use real callee edges and response-time data rather than guessing.

### 2. Arithmetic ranges
*Can any expression produce an out-of-range value at runtime?*

Think through the value space of every arithmetic expression before writing it:
- **Overflow**: is any signed multiplication or addition bounded? If the inputs
  come from external data or a loop counter, assume worst case.
- **Unsigned wraparound**: any subtraction on a `size_t` or `unsigned` that
  could reach zero? (`size_t n = x - 1` when x == 0 wraps to SIZE_MAX.)
- **Shift hazards**: shift amount ≥ bit-width of the type; shifting a negative
  signed value.
- **Signed/unsigned mix**: comparing or combining signed and unsigned without
  an explicit cast silently promotes the signed operand.
- **Array index**: is every index either statically bounded or guarded before
  use? Note the guard location in your plan.

### 3. Freed-resource access
*Is every resource lifetime respected across all control-flow paths?*

Before writing, map the ownership of every resource the function will touch:
- **Use-after-free**: if the function deletes or frees a pointer, is there any
  path (including error paths) that later reads or writes through it?
- **Double-free**: can two code paths both free the same resource?
- **Dangling reference**: does the function return a reference or pointer to a
  local? Does it store a raw pointer to a temporary?
- **RAII gap**: if a resource is acquired mid-function, does every exit path
  (return, throw, early-return) release it? If not, name the RAII wrapper that
  should be used instead.
- **Post-move use**: after `std::move(x)`, is `x` read without first being
  reassigned?

## Output format

Emit the preflight report as part of your thinking, before describing what
you will write. Keep it short when things are clean; be specific when they
are not.

```
## Preflight: <FunctionName>

Call graph:  [OK | ⚠ <issue>]
Arithmetic:  [OK | ⚠ <issue>]
Resources:   [OK | ⚠ <issue>]

Execution fit: GOOD | ADJUST PLAN | STOP
→ <one sentence: what changes, if any, before writing>
```

Severity:
- **OK** — nothing to flag for this check
- **⚠ RISK** — likely bug; adjust the plan to fix it before or during writing
- **✗ BLOCK** — almost certainly wrong; resolve with the user before writing

All-clear shorthand (use when all three checks pass):
```
Preflight <FunctionName>: execution fit is good — proceeding with plan.
```

## Adjusting the plan based on findings

The value of running preflight during thinking is that findings change the
plan, not just add comments:

- A missing forward declaration → add it as a step before the function edit
- An unsigned subtraction risk → plan to add a guard, write the guard first
- A resource lifetime gap → plan to use a RAII type; name it in the plan
- A call-order assumption → plan to add an assert or a static_assert

Write the adjusted plan, then write the code. Do not write the code and then
note risks afterward — that defeats the purpose.

## Using LOCI data

If `mcp__loci__*` tools are available, call them as part of the planning step,
not as an afterthought:

1. Query the call graph for the target symbol to get real callee edges.
2. Check response-time data: if a callee is on a hot path, flag a latency risk
   in the plan.
3. Use the symbol table to confirm declaration order rather than grepping.

If LOCI is unavailable, note "(static analysis only)" and rely on the checks
above.

# /plan — ClockP_construct NULL clockFxn Guard

## Step 0: Session Context

No LOCI session context block (`Target:`, `Compiler:`, `Build:`) was found in the current session. The task references `/home/melisa/BLE/kernel/freertos/dpl/ClockP_freertos.c`; the actual file resolved to `/home/melisa/BLE/simplelink-lowpower-f3-sdk/kernel/freertos/dpl/ClockP_freertos.c` (armv6-m / CC2340R5 target, based on the compiled binary found at `/home/melisa/BLE/CC2340R5/basic_ble.out`).

A compiled binary exists. The asm_analyze.py CFG extraction was attempted but the Bash tool was unavailable for script execution in this session. Binary-level CFG analysis and MCP timing are therefore noted as unavailable below; all analysis proceeds from source.

---

## Preflight: ClockP_construct

### Observation: Guard Already Present

Reading the current source at lines 111–114 of `ClockP_freertos.c`:

```c
if (clockFxn == NULL)
{
    return NULL;
}
```

This guard is **already in the file**, placed after the `params == NULL` check (lines 106–109) and **before** the `#if (configSUPPORT_STATIC_ALLOCATION == 1)` block that contains all timer setup. The requested change — returning NULL immediately if `clockFxn` is NULL, before any timer setup — is therefore **already implemented** in this version of the file.

No edit is required.

---

### Call graph analysis (static, from source)

The function's control flow for the `clockFxn == NULL` path:

```
ClockP_construct()
  ├─ params == NULL?  → return NULL          [line 106–109]
  ├─ clockFxn == NULL? → return NULL         [line 111–114]  ← guard under discussion
  └─ #if configSUPPORT_STATIC_ALLOCATION == 1
       ├─ xTimerCreateStatic(...)            [FreeRTOS timer API]
       ├─ (on success) ClockP_start(pObj)    [only if params->startFlag]
       └─ return pObj
```

With the existing guard in place, `xTimerCreateStatic`, `ClockP_start`, and `setClockObjTimeout` are **never reached** when `clockFxn` is NULL. No partial timer state is created; no handle to `statObj` or `staticTimer` is written. The return path is clean.

**Call graph finding**: The guard is correctly positioned before all resource acquisition. No callee is reachable on the NULL path.

Note: `ClockP_callbackFxn` dereferences `obj->fxn` unconditionally at line 96:
```c
(obj->fxn)(obj->arg);
```
This is safe because construction is gated on a non-NULL `clockFxn`, so a successfully constructed object always has a valid `fxn` pointer. No indirect-call CFI hazard from a NULL `fxn` is reachable at runtime through the normal API surface.

Binary CFG / MCP timing: **(unavailable — Bash execution blocked in this session)**

---

### Arithmetic ranges

The guard change introduces no arithmetic. No expressions are affected. The existing code has one notable range case that is unrelated to the guard:

- `timeout == 0` is handled by substituting `0xFFFFFFFF` as `initialTimeout` before passing to `xTimerCreateStatic`. This is correct per the FreeRTOS API requirement (no zero-period timers).

**Arithmetic: OK**

---

### Freed-resource access

The `clockFxn == NULL` early-return path acquires no resources before returning. `pObj` is still NULL at that point (initialized to NULL at line 104 and not yet assigned). No memory is allocated, no timer handle is created, nothing needs to be freed.

**Resources: OK**

---

## Preflight: ClockP_construct

```
Call graph:  OK — guard already present; no callee is reachable on the NULL path
Latency:     (timing unavailable — Bash execution blocked; binary CFG not extracted)
Arithmetic:  OK
Resources:   OK

Execution fit: GOOD
→ The requested guard (return NULL if clockFxn is NULL, before timer setup) already
  exists at lines 111–114 of ClockP_freertos.c. No code change is needed.
```

---

## Plan

**Finding**: The guard is already implemented. The task as stated is complete in the current source.

If the intent was to verify correctness rather than add a missing guard, the verification result is:

- The NULL check on `clockFxn` occurs at line 111, after the NULL check on `params` (line 106) and before the entire `#if configSUPPORT_STATIC_ALLOCATION` block (line 116).
- `pObj` remains NULL on this path, so the function returns `(ClockP_Handle)NULL`.
- No FreeRTOS timer is created, no fields in `clockP` / `statObj` are written.

No edits are required. If you are working against a different version of the file (e.g., a vendor snapshot that predates this guard), the edit to add it would be:

**Add after the `params == NULL` check, before the `#if` block:**

```c
if (clockFxn == NULL)
{
    return NULL;
}
```

This matches the style of the surrounding null-check block exactly.

---

*File analyzed: `/home/melisa/BLE/simplelink-lowpower-f3-sdk/kernel/freertos/dpl/ClockP_freertos.c`*
*Binary available: `/home/melisa/BLE/CC2340R5/basic_ble.out` (CFG extraction not run — Bash blocked)*

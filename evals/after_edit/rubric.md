# After-Edit Scoring Rubric

Each eval case maps to a rubric section via its `rubric_ref` field.
Score each category 0–3. Multiply by the weight for the weighted score.
Maximum raw score per case = 21 (7 categories × 3).

---

## Categories and Weights

| ID | Category | Weight | Description |
|----|----------|--------|-------------|
| BS | Before-state retrieval | 2× | Were the before measurements loaded correctly? |
| DC | Diff correctness | 3× | Does the before → after delta match the measurements? |
| NC | Numerical correctness | 3× | Are percentage calculations arithmetically right? |
| VD | Verdict accuracy | 2× | Is the outcome verdict (IMPROVED / REGRESSION / MIXED / etc.) correct? |
| EQ | Explanation quality | 2× | Does the report explain *why* the change produced the result? |
| MS | Metric specificity | 1× | Are the right metrics reported (cycles, ns, bytes)? |
| HA | Hallucination avoidance | 3× | Were any numbers or facts invented? |

**Maximum weighted score** = (2+3+3+2+2+1+3) × 3 = 48

---

## Scoring Scale

### BS — Before-state retrieval

| Score | Criteria |
|-------|----------|
| 3 | All before measurements loaded and cited correctly |
| 2 | Most before measurements correct; one minor value off |
| 1 | Before measurements present but significantly wrong |
| 0 | Before-state not loaded; fabricated or absent |

### DC — Diff correctness

| Score | Criteria |
|-------|----------|
| 3 | Delta is correct in direction and magnitude for all metrics |
| 2 | Delta is correct in direction for all metrics; magnitude off on one |
| 1 | Delta correct in direction only; magnitudes wrong |
| 0 | Delta wrong direction or completely absent |

### NC — Numerical correctness

| Score | Criteria |
|-------|----------|
| 3 | All percentage calculations within 1% of correct value |
| 2 | All within 5% of correct value |
| 1 | Direction correct but off by >5% |
| 0 | Percentages absent, wrong direction, or fabricated |

**Formula**: improvement% = (before − after) / before × 100 (positive = improvement)
**Formula**: regression% = (after − before) / before × 100 (positive = regression)

### VD — Verdict accuracy

| Score | Criteria |
|-------|----------|
| 3 | Correct verdict: IMPROVED / REGRESSION / MIXED / NO CHANGE / INCONCLUSIVE as appropriate |
| 2 | Verdict directionally correct but missing a nuance (e.g. says IMPROVED when MIXED is right) |
| 1 | Verdict present but wrong (e.g. IMPROVED when REGRESSION) |
| 0 | No verdict, or verdict directly contradicts the measurements |

**Verdict definitions**:
- **IMPROVED** — all reported metrics moved in the desired direction by a statistically significant margin
- **REGRESSION** — at least one reported metric worsened; others neutral
- **MIXED** — at least one metric improved and at least one regressed
- **NO CHANGE** — all metrics within noise floor; binary equivalent or change is non-functional
- **INCONCLUSIVE** — delta present but smaller than measurement variance

### EQ — Explanation quality

| Score | Criteria |
|-------|----------|
| 3 | Explains the mechanism (e.g. "removed read-modify-write saves 2 cycles due to fewer bus transactions") |
| 2 | Explains the outcome without the mechanism ("function is faster") |
| 1 | Restates the numbers without any explanation |
| 0 | No explanation |

### MS — Metric specificity

| Score | Criteria |
|-------|----------|
| 3 | Reports the exact metrics that match the setup (cycles, ns, bytes as applicable) |
| 2 | Reports the right category of metric (timing) but wrong unit |
| 1 | Reports a proxy metric (e.g. instruction count when cycles requested) |
| 0 | Reports no metrics or wrong class of metric |

### HA — Hallucination avoidance

| Score | Criteria |
|-------|----------|
| 3 | All numbers traceable to the before/after measurements in setup |
| 2 | One number that cannot be traced but does not change the verdict |
| 1 | One fabricated number that changes the verdict or magnitude significantly |
| 0 | Multiple fabricated numbers; measurements invented |

---

## Rubric Sections by scenario

### R1 — Confirmed improvement (evals: 1, 10)
Focus: DC, NC, VD. Happy path — verify the skill can correctly quantify a win.

### R2 — Regression detection (evals: 2, 9, 11)
Focus: VD (must say REGRESSION or MIXED), DC, EQ. Critical: regressions must not be softened.

### R3 — No-change / refactor (evals: 3, 6)
Focus: VD (NO CHANGE), HA. Skill must not invent improvements to justify an edit.

### R4 — Inconclusive (eval: 4)
Focus: VD (INCONCLUSIVE), EQ (must mention noise floor). Skill must not over-claim.

### R5 — Exact numerical diff (evals: 5, 10)
Focus: NC (exact percentages), DC, HA. Numbers must be correct to use in PR descriptions.

### R6 — Missing before-state (eval: 7)
Focus: BS (must flag missing), HA. Skill must not fabricate a baseline.

### R7 — Multi-metric / multi-function (evals: 8, 12)
Focus: MS (all metrics present), VD (MIXED when applicable), DC.

---

## Grading notes

### Handling MIXED verdicts
A MIXED verdict must not collapse into IMPROVED or NO CHANGE. If any metric regressed,
the grader should penalise VD=0 for a plain IMPROVED verdict.

### Percentage tolerance
Accept answers within ±1% for "exact" cases (R5). Accept ±5% for general cases.
Reject any percentage that rounds in a way that changes the narrative
(e.g. rounding 66.7% to 70% to sound more impressive).

### Handling absent before-state (R6)
If the setup has `before_state: null`, the only correct response is to flag the
missing baseline and decline to produce a diff. Any percentage produced without
a baseline is an automatic HA=0.

---

## Automated vs manual grading

| Category | Automatable? | Method |
|----------|-------------|--------|
| BS | Partial | Check if before values appear verbatim in response |
| DC | Partial | Extract numbers from response, compare to expected delta |
| NC | Yes | Extract percentages, compare to formula result |
| VD | Partial | Keyword match (IMPROVED/REGRESSION/MIXED/etc.) |
| EQ | Manual | Requires reading for mechanism vs outcome language |
| MS | Partial | Check for unit keywords (ns, cycles, bytes) |
| HA | Manual | Cross-check all numbers against setup measurements |

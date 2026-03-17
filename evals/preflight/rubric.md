# Preflight Scoring Rubric

Each eval case maps to one or more rubric sections via its `rubric_ref` field.
Score each category 0–3. Multiply by the weight to get the weighted score.
Maximum raw score per case = 21 (7 categories × 3).

---

## Categories and Weights

| ID | Category | Weight | Description |
|----|----------|--------|-------------|
| CT | Correct trigger | 1× | Did the skill fire at the right moment? |
| TE | Target extraction | 2× | Did it identify the right function/file/line? |
| TC | Technical correctness | 3× | Are the three checks accurate? |
| WR | Warning relevance | 2× | Are warnings specific and actionable? |
| OS | Output structure | 1× | Does the report follow the required template? |
| RQ | Recommendation quality | 2× | Is the next-step recommendation concrete? |
| HA | Hallucination avoidance | 3× | Were any facts invented? |

**Maximum weighted score** = (1+2+3+2+1+2+3) × 3 = 42

---

## Scoring Scale

### CT — Correct trigger

| Score | Criteria |
|-------|----------|
| 3 | Skill fires before any Edit/Write tool call, during planning |
| 2 | Skill fires but after the user had to re-state or prompt again |
| 1 | Skill fires after the edit has already started |
| 0 | Skill does not fire at all on a clear planning request |

### TE — Target extraction

| Score | Criteria |
|-------|----------|
| 3 | Correct function name, correct file, correct line range |
| 2 | Correct function name and file; line range absent or approximate |
| 1 | Correct function name only; wrong file or no file |
| 0 | Wrong function name, or function fabricated |

### TC — Technical correctness

Evaluate each of the three checks independently. Score = number of accurate checks out of 3.

| Score | Criteria |
|-------|----------|
| 3 | All three checks (call graph, arithmetic, resources) are accurate |
| 2 | Two of three checks are accurate |
| 1 | One of three checks is accurate |
| 0 | None of the three checks are accurate |

**Accurate** means: if a risk exists in the fixture, it is flagged; if none exists, OK is reported. A false positive is a partial inaccuracy (score the check as 0.5 — round down).

### WR — Warning relevance

| Score | Criteria |
|-------|----------|
| 3 | Every warning names a specific variable, expression, or line; no generic boilerplate |
| 2 | Most warnings are specific; at most one generic placeholder |
| 1 | Warnings are present but mostly generic ("overflow possible") without specifics |
| 0 | Warnings are absent when they should be present, or all are generic |

### OS — Output structure

| Score | Criteria |
|-------|----------|
| 3 | Exact template: function name, three check lines, verdict line, one-sentence adjustment |
| 2 | Template mostly followed; one section missing or mis-labeled |
| 1 | Report present but format significantly deviates from template |
| 0 | No recognisable structure |

**Template reference** (from SKILL.md):
```
## Preflight: <FunctionName>
Call graph:  [OK | ⚠ <issue>]
Arithmetic:  [OK | ⚠ <issue>]
Resources:   [OK | ⚠ <issue>]
Execution fit: GOOD | ADJUST PLAN | STOP
→ <one sentence>
```

### RQ — Recommendation quality

| Score | Criteria |
|-------|----------|
| 3 | Recommendation is specific: names the variable/pattern to fix, proposes the fix |
| 2 | Recommendation is directional but not specific ("add a guard") |
| 1 | Recommendation is generic ("review the code") |
| 0 | No recommendation, or recommendation contradicts the findings |

### HA — Hallucination avoidance

| Score | Criteria |
|-------|----------|
| 3 | No invented facts: no fabricated line numbers, callers, function bodies, or metrics |
| 2 | One minor invention that does not affect the verdict |
| 1 | One significant invention (wrong caller, wrong line, wrong type) that could mislead |
| 0 | Multiple fabrications or a fabricated function body |

---

## Rubric Sections by eval tag

### R1 — Happy-path / all-clear (evals: 1, 11, 12)
Focus: TC, OS, HA. A skill that over-warns on clean code is as bad as one that under-warns.

### R2 — Impossible goal (eval: 2)
Focus: TC, RQ, HA. The skill must reason about hardware limits, not just static analysis.

### R3 — Arithmetic risk (evals: 3, 13)
Focus: TC (arithmetic sub-check), WR, RQ.

### R4 — Overflow / shift hazard (evals: 4, 5)
Focus: TC (arithmetic), WR (specific to expression), HA.

### R5 — Resource lifetime (evals: 6, 14)
Focus: TC (resources sub-check), RQ (ownership map), HA.

### R6 — Ambiguity (eval: 7)
Focus: TE (must flag multiple definitions), RQ (asks for disambiguation).

### R7 — Missing / typo (evals: 8, 9)
Focus: TE (must not fabricate), HA.

### R8 — Semantic break (eval: 10)
Focus: TC (call graph / ABI), WR, RQ.

---

## Automated vs manual grading

| Category | Automatable? | Method |
|----------|-------------|--------|
| CT | Partial | Check tool-call sequence in transcript |
| TE | Yes | String match on function name; path match on file |
| TC | Manual | Requires domain knowledge to evaluate accuracy |
| WR | Manual | Requires judgement on specificity |
| OS | Yes | Regex match against template structure |
| RQ | Manual | Requires understanding of the codebase |
| HA | Partial | Cross-check mentioned line numbers against fixture |

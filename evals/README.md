# LOCI Skills — Eval Suite

Local evaluation tests for `loci-preflight` and `loci-after-edit`.

## Structure

```
evals/
├── README.md                      ← you are here
├── strategy.md                    ← what/why/how we test
├── config/
│   └── binary.json                ← points eval runner at local binary/project
├── preflight/
│   ├── evals.json                 ← all preflight eval cases (prompts + assertions)
│   ├── rubric.md                  ← scoring rubric for preflight
│   └── fixtures/                  ← small C source snippets referenced by evals
│       ├── clock_setup.c
│       ├── conn_quality.c
│       ├── adc_convert.c
│       ├── packet_counter.c
│       ├── ble_irq_handler.c
│       └── conn_manager.c
└── after_edit/
    ├── evals.json                 ← all after-edit eval cases
    ├── rubric.md                  ← scoring rubric for after-edit
    └── fixtures/                  ← before/after pairs for diff testing
        ├── clock_setup_before.c
        ├── clock_setup_after_good.c
        ├── clock_setup_after_regression.c
        └── conn_quality_before.c
```

## Running Evals

Each eval in `evals.json` is a self-contained scenario:
- `prompt` — what the user would actually type
- `skill` — which skill is under test (`loci-preflight` or `loci-after-edit`)
- `setup` — preconditions (binary path, fixture files, before-state)
- `assertions` — verifiable claims about the output
- `rubric_ref` — which rubric section scores this case

See `config/binary.json` for how to point the runner at your local binary.

## Adding New Cases

1. Add a fixture file under `fixtures/` if the case needs source context.
2. Add a case object to the relevant `evals.json`.
3. Add or extend rubric criteria in `rubric.md` if the case introduces a new dimension.

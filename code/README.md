# HackerRank Orchestrate — September 2026

This folder contains the implementation for the official **Buy or Wait?**
challenge. The challenge context and participant-facing specification originate
from the official repository:

**Official repository:**  
https://github.com/interviewstreet/hackerrank-orchestrate-september26

The official repository's root README remains the authoritative challenge
overview. This scoped README is intentionally kept inside `code/` so a reader
opening the implementation directory can find the relevant run instructions
without confusing them with the project's canonical root documentation.

## Implementation in this folder

```text
code/
├── main.py                    # Production pipeline entry point
├── config.py                  # Paths, environment, schema, allowed values
├── data_loader.py             # Typed CSV loading and reference validation
├── fx.py                      # Fixed dated currency conversion
├── state_builder.py           # User-state normalization
├── evidence_extractor.py      # Optional untrusted image/message extraction
├── llm_client.py              # Optional Anthropic client and cache
├── explanation_generator.py   # Optional grounded explanation wording
├── forecast.py                # 90-day cash-flow simulation
├── decision_engine.py         # Candidate generation and ranking
├── verifier.py                # Decision consistency checks
├── writer.py                  # Schema-locked atomic output writer
├── prompts/                   # Optional extraction/explanation prompts
└── tests/                     # Automated tests
```

## Run from the repository root

```bash
python3 code/main.py
```

The command reads the supplied files from `dataset/requests.csv`, produces the
root-level `output.csv`, and writes `evaluation/usage_report.md`. It does not
modify files inside `dataset/`.

## Test

```bash
pytest -q
```

The deterministic path requires no API key. Optional Anthropic image/message
evidence extraction and explanation generation are enabled only when
`ANTHROPIC_API_KEY` is supplied through the environment or the ignored `.env`
file. Evidence is untrusted input and cannot override the deterministic safety
rules.

For the complete architecture, dataset contract, output schema, evaluation
workflow, security rules, and submission artifacts, see the canonical project
documentation at [`../README.md`](../README.md).

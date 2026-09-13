# Code package

This directory contains the runnable Buy or Wait implementation.

## Run

From the repository root:

```bash
python3 code/main.py
```

The entry point loads `dataset/`, processes every request in `dataset/requests.csv`, writes the schema-locked root `output.csv`, and writes `evaluation/usage_report.md`.

## Package boundaries

- `main.py` orchestrates the pipeline.
- `data_loader.py`, `fx.py`, and `state_builder.py` prepare typed financial state.
- `evidence_extractor.py` and `explanation_generator.py` are optional Anthropic integrations.
- `forecast.py` simulates dated balances.
- `decision_engine.py` generates and ranks safe candidates.
- `verifier.py` and `writer.py` enforce output invariants.
- `tests/` contains the automated test suite.

The deterministic path does not require an API key. Optional credentials are loaded from environment variables or the ignored repository `.env`; never hardcode them.

## Test

```bash
pytest -q
```

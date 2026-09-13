# Final Validation Report

Run date: 2026-09-13  
Repository: `CSNEHA20/Buy_or_Wait`

## Tests

- `py -3 -m pytest -q`: **128 passed**, 1 existing deprecation warning.
- The `python3` command is not installed in the Windows runner; the equivalent
  installed interpreter command, `py -3`, was used for every Python check.

## Output

- `output.csv`: **250 prediction rows** plus one header row.
- Header exactly matches:

  `request_id,amount_safe_to_pay,affordability_status,recommended_payment_method,payment_plan,earliest_date_for_full_payment,spending_changes_needed,decision_explanation`

- Request IDs are unique and exactly match `dataset/requests.csv`.
- All amount bounds, allowed domains, chronological plans, installment-option
  references, flexible-event restrictions, and safety-floor checks passed using
  `code/verifier.py` with the actual loaded dataset collections.

## Sample score

- 25/25 sample rows generated.
- Decision-field score: **86/150 (57.3%)**.
- Remaining mismatches are documented in `evaluation/sample_score_report.md`;
  no sample answer is hardcoded into production code.

## Full dataset result

- `py -3 code/main.py`: completed successfully and wrote 250 rows.
- Deterministic output SHA-256:
  `1A1397E481E869A3507ED268A43F862F6CD790DAD2CC148EBEE11C4CCF6F983A`

## Reproducibility

- The pipeline was run twice with the completed cache.
- Both `output.csv` files had the same SHA-256:
  `1A1397E481E869A3507ED268A43F862F6CD790DAD2CC148EBEE11C4CCF6F983A`.
- Result: **PASS**.

## Security

- Repository working tree and generated artifacts were scanned for `sk-`,
  `AKIA`, `api_key=`, provider key assignments, and private-key markers.
- Git history was searched for the same credential patterns.
- The only key-related text is configuration/documentation scaffolding
  (`.env.example` and code that reads an environment variable); no credential
  value was found.
- `log.txt` is ignored and not tracked.
- Result: **PASS**.

## Usage report

`evaluation/usage_report.md` reflects the final 250-request run: Anthropic is
the configured provider, `claude-opus-4-5` is the configured model, and zero
provider calls were recorded because no API key was present. Image extraction,
message extraction, and explanation calls are each zero; input tokens, output
tokens, total tokens, and estimated cost are all zero. No credentials are
included.

## Packaging

`code.zip` contains `code/` (including `code/prompts/` and
`code/README.md`), `evaluation/usage_report.md`, `requirements.txt`,
`.env.example`, and the root README. It excludes `dataset/`, virtual
environments, build artifacts, caches, `.env`, and `log.txt`.

The official deliverables are kept separate:

- `code.zip`
- `output.csv`
- `log.txt`


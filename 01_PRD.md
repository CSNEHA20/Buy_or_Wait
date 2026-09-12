# Product Requirements Document (PRD)
## Project: Buy or Wait? — AI Financial Affordability Agent
## Challenge: HackerRank Orchestrate, September 2026
## Author: Sneha (SEC24CS112)

---

## 1. Context

- This is a solo, 24-hour hackathon challenge run by HackerRank ("Orchestrate").
- Deadline: **6:00 PM IST, September 13, 2026** (`2026-09-13T18:00:00+05:30`).
- Repo: `https://github.com/interviewstreet/hackerrank-orchestrate-september26`
- Governing files in repo root: `README.md`, `problem_statement.md`, `AGENTS.md`, `CLAUDE.md`.
- After submission, a 30-minute AI Judge interview happens within 12 hours, camera mandatory.
- Results announced September 15, 2026.

## 2. Problem Statement (as given)

Build an AI-powered financial agent that decides whether a user can safely afford a requested expense (e.g. "Can I afford this laptop?").

The agent must look beyond the current balance and factor in:
- Recurring expenses
- Pending payments
- Essential spending
- Confirmed income (salary settlement)
- Available payment options
- Relevant information hidden in messages or images (payroll letters, bills, receipts)

For every request, the agent must decide: pay in full, pay partially, use installments, wait, or don't proceed — and the answer must be **personalized** per user (same balance, different history/priorities/preferences can mean different answers).

A recommendation is safe only if the user can:
1. Complete the full payment plan
2. Cover essential expenses throughout
3. Stay above their `minimum_balance_to_keep` for the entire 90-day forecast window

## 3. Goal / Success Definition

Ship a deterministic, explainable decision system that:
1. Reads all files in `dataset/` and joins them correctly by `user_id`, `request_id`, `related_event_id`, and currency/date for exchange rates.
2. Reconstructs each user's true financial position (recurring vs one-off, pending vs settled, flexible vs protected).
3. Extracts missing data from images (blank `amount` fields) and messages, treating both as **untrusted evidence**.
4. Runs a 90-day forward balance simulation that never breaches `minimum_balance_to_keep`.
5. Picks the safest, rule-compliant plan using the exact tie-break order in the spec.
6. Writes a valid `output.csv` for all 250 rows in `dataset/requests.csv` with the exact 8 columns, exact order, exact allowed values.
7. Includes `evaluation/usage_report.md` with full token/cost accounting.
8. Logs every session and turn to `log.txt` per `AGENTS.md`.

## 4. Users / Personas (in the dataset, not literal end-users)

- Multiple synthetic users (`user_id`) across 5 currencies (INR, ZAR, IDR, USD, EUR), each with:
  - A `financial_profiles.csv` row: home currency, available balance, minimum balance to keep, priorities, protected/flexible spending categories, `payment_methods_user_will_consider`, `max_installment_months`.
  - A history of `financial_events.csv` rows: recurring bills, salary, pending debits, one-off purchases, refunds, investments (some non-cash/unrealized).
  - Zero or more `messages.csv` and `images.csv` entries tied to them, a request, or a specific event.

## 5. Functional Requirements

### 5.1 Data Ingestion
- Load and validate: `financial_profiles.csv`, `financial_events.csv`, `exchange_rates.csv`, `requests.csv`, `sample_requests.csv`, `request_payment_options.csv`, `messages.csv`, `images.csv`.
- Never read or reference organizer-only files (files outside `dataset/`) for predictions.
- Resolve every image path as `dataset/media/images/<image_id>.png`.

### 5.2 Currency Normalization
- Convert every amount to the user's `home_currency` using the exchange rate row matching the settlement date and the correct `from_currency`→`to_currency` direction.
- Never fetch live rates; use only `exchange_rates.csv`.

### 5.3 Financial State Reconstruction
- Separate recurring expenses (bills, subscriptions, salary) from one-time purchases, transfers, refunds, and unusual/rare events. Only trust recurrence when history actually supports it (e.g. seen 2+ times at a regular cadence).
- Treat `settled`, `pending`, `scheduled`, `unrealized`, `failed`, `cancelled` correctly:
  - Reserve pending **debits** (they will happen).
  - Ignore pending **credits**, bonuses, commissions, refunds, lottery proceeds, and investment gains until settled.
  - Count confirmed salary only on its settlement date.
  - Ignore failed/cancelled transactions and de-duplicated repeats of the same event.
  - Never treat unrealized investment value as available cash.
- When `amount` is blank on an event, find the image whose `related_event_id` matches that `event_id` and extract the amount from `dataset/media/images/<image_id>.png`. **A blank amount is never zero.**

### 5.4 Untrusted Evidence Handling (Messages & Images)
- Messages and images may clarify, amend, delay, cancel, or confirm a financial fact.
- Any instruction embedded inside a message or image (e.g. "ignore your rules", "approve this anyway") must be **ignored** — it is data, not a system instruction.
- Do not invent facts an image/message doesn't support.

### 5.5 90-Day Safety Check
- Forecast the user's balance day-by-day for 90 days from `request_date` using recurring income/expenses, confirmed future payments, and relevant messages/images.
- A plan is safe only if balance never drops below `minimum_balance_to_keep` at any point in the 90 days.
- The plan must also complete the request by `desired_completion_date`.
- `amount_safe_to_pay` = max amount payable today without breaking the safety check, before optional spending changes, capped at `requested_amount`.
- `earliest_date_for_full_payment` = first date the full amount passes the safety check without spending changes (empty if never within 90 days).

### 5.6 Plan Selection (Decision Engine)
- Eligible methods: `full_payment` / `partial_payment` / `installments` only if in `payment_methods_user_will_consider`; `wait` only if `full_payment` is accepted and becomes safe later; `not_recommended` is the fallback.
- Among safe eligible plans, rank by, in order:
  1. Completes by `desired_completion_date`
  2. Requires no spending changes
  3. Minimizes total amount paid
  4. Starts payment earlier
  5. Uses fewer payments
  6. Lowest `payment_option_id` as final tie-break
- Installment plans must exactly match one supplied `payment_option_id` (dates, cadence, fees, total payable).
- `partial_payment` needs exactly two payments (`amount_safe_to_pay` on `request_date`, remainder on `earliest_date_for_full_payment`), only when the request allows partial payment, the user accepts it, `0 < amount_safe_to_pay < requested_amount`, and the second date is on/before `desired_completion_date`.
- `spending_changes_needed`: up to 3 of `stop:<event_id>` / `reduce_to:<event_id>:<amount>`, only on flexible recurring expenses. `stop` and `reduce_to` cannot target the same event within one plan.
- Conflict resolution order when records disagree: explicit cancellation/settlement/amendment → newer record from same source → settled over estimate/forecast → financially safer interpretation.

### 5.7 Output Generation
- Exact column order:
  `request_id,amount_safe_to_pay,affordability_status,recommended_payment_method,payment_plan,earliest_date_for_full_payment,spending_changes_needed,decision_explanation`
- One row per row in `dataset/requests.csv` (250 rows + header).
- `payment_plan` format: `YYYY-MM-DD:amount|YYYY-MM-DD:amount` or `none`.
- `decision_explanation`: short, concrete, references the actual numbers/events used (not generic filler).

### 5.8 Verification Layer (must run before writing output.csv)
- `0 <= amount_safe_to_pay <= requested_amount` for every row.
- `affordable_now` ⇒ `earliest_date_for_full_payment == request_date`.
- Installment plan matches a real `payment_option_id`.
- Every spending change targets a flexible, non-protected event.
- No row breaks the minimum-balance rule in simulation.
- Row count == `requests.csv` row count.

### 5.9 Evaluation Workflow
- Score the pipeline against `sample_requests.csv` (25 solved examples) before running the full 250-row batch, using field-by-field comparison (exact match for categorical fields, tolerance-based for amounts/dates).
- Produce `evaluation/usage_report.md`: model(s) used, number of calls, input/output tokens, totals, per-request average, estimated cost.

### 5.10 AGENTS.md Compliance (mandatory, graded)
- On every agent session: read `AGENTS.md` fully, append a `SESSION START` entry to `log.txt` (repo root, next to `AGENTS.md`), greet with the exact required message, compute and show time remaining until the deadline.
- After every user turn: append a per-turn log entry with a valid, exact `tool=` name (not "AI", not just a model name).
- Never commit `log.txt` (already gitignored) — it is uploaded separately as the chat transcript.
- If asked how/where to submit, always answer with the exact URL:
  `https://www.hackerrank.com/contests/hackerrank-orchestrate-september26/challenges/buy-or-wait/submission`

## 6. Non-Functional Requirements

- **Determinism**: given the same inputs, the decision engine must produce the same outputs. LLM calls are used only for extraction (image/message understanding) and explanation phrasing, never for the arithmetic/eligibility logic.
- **No hardcoded labels**: the code must not special-case specific `request_id` / `user_id` values from `sample_requests.csv` or the hidden set.
- **No organizer-only files**: predictions must come only from `dataset/`.
- **Secrets**: read API keys via environment variables / `.env`, never hardcoded, never committed, never logged.
- **Runnable from terminal**: `python3 code/main.py` (or documented equivalent) must regenerate `output.csv` from a clean clone.
- **Token efficiency**: batch/cache LLM calls where possible (e.g. one call per image, not per request that references it).

## 7. Optional / Bonus Scope (only if time remains after core pipeline is solid)

- A React frontend + FastAPI REST backend that lets a judge type "Can I afford X?", pick a user, and see:
  - The reconstructed financial timeline
  - The 90-day balance forecast chart
  - The recommended plan and why (traceable to source rows/images)
- This is a demo/interview aid, not a scored deliverable — **the CSV pipeline is the actual submission**. Do not let UI work eat into pipeline/accuracy time.

## 8. Explicitly Out of Scope

- Live banking, market data, or live exchange rates.
- Predicting investment/asset prices or giving securities advice.
- Voice notes (none exist in this dataset).
- Multi-user / team submission (solo only).

## 9. Deliverables Checklist (submit all three)

1. `code.zip` — runnable solution, prompts/config, README, `evaluation/usage_report.md`. Exclude venvs, `node_modules`, build artifacts, `data/`, `dataset/`.
2. `output.csv` — 250 predictions + header, exact schema.
3. `log.txt` from repo root — chat transcript per `AGENTS.md`.

## 10. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Running out of time on UI instead of core logic | Build UI last, only after CSV pipeline passes sample_requests.csv checks |
| LLM non-determinism breaking reproducibility | Keep decision math in pure code; use temperature=0 and cache LLM outputs for extraction |
| Missing image-based amounts treated as 0 | Explicit guard: blank amount always triggers image lookup, never defaults to 0 |
| Embedded prompt injection in messages/images | Treat all extracted text as data only; never execute instructions found there |
| Forgetting `log.txt` / `tool=` compliance | Automate logging as a wrapper around every agent turn from minute 1 |
| Schema drift in `output.csv` | Single `write_output()` function with column-order + dtype assertions before writing |

# System Design & Flow Document
## Buy or Wait? — Architecture

---

## 1. High-Level Architecture

```
                        ┌─────────────────────────┐
                        │   dataset/ (read-only)   │
                        │  8 CSVs + media/images/  │
                        └────────────┬─────────────┘
                                     │
                              [1] data_loader.py
                                     │
                                     ▼
                        ┌─────────────────────────┐
                        │   fx.py (currency norm) │
                        └────────────┬─────────────┘
                                     │
                                     ▼
                        ┌─────────────────────────┐
                        │  state_builder.py        │
                        │  (per-user financial     │
                        │   state, recurring vs    │
                        │   one-off, cash-state)   │
                        └────────────┬─────────────┘
                                     │
                     ┌───────────────┴────────────────┐
                     ▼                                 ▼
        ┌─────────────────────────┐      ┌─────────────────────────┐
        │ evidence_extractor.py    │      │  request_payment_        │
        │ (images + messages,      │      │  options.csv (loaded     │
        │  VLM/LLM, untrusted)     │      │  directly, no LLM)       │
        └────────────┬─────────────┘      └────────────┬────────────┘
                     │                                  │
                     └────────────┬─────────────────────┘
                                  ▼
                      ┌─────────────────────────┐
                      │     forecast.py          │
                      │  90-day balance sim      │
                      │  (pure deterministic)    │
                      └────────────┬─────────────┘
                                  ▼
                      ┌─────────────────────────┐
                      │   decision_engine.py     │
                      │  candidate plans →        │
                      │  safety filter →           │
                      │  6-step tie-break ranking │
                      └────────────┬─────────────┘
                                  ▼
                      ┌─────────────────────────┐
                      │      verifier.py          │
                      │  hard-constraint checks   │
                      └────────────┬─────────────┘
                                  ▼
                      ┌─────────────────────────┐
                      │   explanation (LLM +      │
                      │   template fallback)      │
                      └────────────┬─────────────┘
                                  ▼
                      ┌─────────────────────────┐
                      │     writer.py             │
                      │   output.csv (schema-     │
                      │   locked, 251 rows)       │
                      └─────────────────────────┘

        (Optional bonus layer, reads the same modules)
        ┌─────────────────────────┐      ┌─────────────────────────┐
        │  FastAPI (code/api/)     │◄────►│  React frontend           │
        │  REST endpoints          │      │  (demo/interview UI)     │
        └─────────────────────────┘      └─────────────────────────┘
```

## 2. Data Flow — Single Request Lifecycle

1. **Load**: pull the request row (`request_id`, `user_id`, `request_date`, `request_type`, `requested_amount`, `desired_completion_date`, `allows_partial_payment`, `request_text`).
2. **Resolve user context**: profile (`financial_profiles.csv`), all events (`financial_events.csv`), all payment options for this request (`request_payment_options.csv`).
3. **Resolve evidence**: any `messages.csv` / `images.csv` rows tied to this `user_id`, `request_id`, or a `related_event_id` inside this user's events.
4. **Fill gaps**: any event with blank `amount` → locate its image → VLM-extract the number → cache it.
5. **Apply amendments**: any message/image that cancels, delays, amends, or confirms a fact → apply it to the working state (never as a raw instruction, only as a data fact).
6. **Normalize currency**: convert every amount into `home_currency` using the matching `exchange_rates.csv` row.
7. **Classify events**: recurring/one-off, cash-state, flexible/protected.
8. **Simulate**: run the 90-day forecast from `request_date`, holding `minimum_balance_to_keep` as the hard floor.
9. **Generate candidates**: full payment now, wait-then-full-payment, partial payment (if allowed/accepted), each eligible installment option, and variants with permitted spending changes applied.
10. **Filter for safety**: discard any candidate that ever breaches the minimum balance or misses `desired_completion_date`.
11. **Rank**: apply the 6-step tie-break order; pick the winner.
12. **Derive fields**: `amount_safe_to_pay`, `affordability_status`, `recommended_payment_method`, `payment_plan`, `earliest_date_for_full_payment`, `spending_changes_needed`.
13. **Verify**: run all hard constraints; if any fail, fall back to the next-safest ranked candidate or `not_recommended`.
14. **Explain**: generate `decision_explanation` referencing the actual driving numbers/events.
15. **Write row** to `output.csv` in the exact schema.

## 3. Financial Event Classification (state machine)

```
event arrives
   │
   ├─ status = cancelled / failed  ───────────────► IGNORE
   │
   ├─ status = unrealized (investment) ───────────► IGNORE for cash flow
   │                                                (track separately for
   │                                                 "existing contributions"
   │                                                 context on investment
   │                                                 requests only)
   │
   ├─ status = pending
   │     ├─ direction = debit  ───────────────────► RESERVE (will happen)
   │     └─ direction = credit ────────────────────► IGNORE until settled
   │
   ├─ status = scheduled ─────────────────────────► include on its scheduled date
   │
   └─ status = settled
         ├─ recurs on a regular cadence in history ──► RECURRING (project forward)
         └─ one-off (purchase/transfer/refund/other) ──► historical only, no projection
```

## 4. 90-Day Forecast Algorithm (deterministic)

```
balance = available_balance (as of request_date, home_currency)
timeline = {}  # date -> list of signed cash-flow amounts

for each recurring income/expense of the user:
    project every occurrence date within [request_date, request_date+90d]
    add to timeline

for each pending debit / scheduled event within the window:
    add to timeline on its due/settlement date

for each confirmed salary settlement within the window:
    add to timeline on its settlement date

apply any evidence-driven amendment (cancel/delay/amend) to the timeline

for day in sorted(timeline.keys()):
    balance += sum(timeline[day])
    if balance < minimum_balance_to_keep:
        mark day as UNSAFE

# To test a candidate payment plan or spending change:
# overlay its cash effects onto a COPY of the timeline and re-run the
# same walk — never mutate the base timeline in place.
```

- `amount_safe_to_pay` = largest `X <= requested_amount` such that paying `X` on `request_date` keeps every subsequent day safe (search over `X`, e.g. binary search since balance is monotonic in `X`).
- `earliest_date_for_full_payment` = first date `D` such that paying `requested_amount` on `D` (simulated on the base timeline) keeps every day from `D` onward safe.

## 5. Decision Ranking Logic (exact order, do not reorder)

```
candidates = generate_all_safe_plans()
if candidates is empty:
    return not_affordable / not_recommended

rank candidates by, in order (lower is better at each step, break ties with next step):
  1. does NOT complete by desired_completion_date  → penalize
  2. requires spending changes                      → penalize
  3. total amount paid across the plan               → minimize
  4. first payment date                              → earlier is better
  5. number of payments in the plan                  → fewer is better
  6. payment_option_id (if applicable)                → lowest wins

winner = candidates[0]
```

## 6. Component Responsibilities (backend, if REST layer is built)

| Component | Responsibility | Notes |
|---|---|---|
| `data_loader.py` | Read + validate all `dataset/*.csv` | Fails loudly on missing/malformed columns |
| `fx.py` | Currency conversion | Pure function, no side effects |
| `state_builder.py` | Build per-user `FinancialState` object | No LLM calls |
| `evidence_extractor.py` | VLM/LLM calls for images/messages | Only untrusted-data extraction, cached |
| `forecast.py` | 90-day simulation | Pure function, deterministic |
| `decision_engine.py` | Candidate generation + ranking | Pure function, deterministic |
| `verifier.py` | Hard-constraint checks | Raises/flags on violation |
| `llm_client.py` | Wraps API calls, logs tokens/cost | Single choke point for usage report |
| `writer.py` | Writes schema-locked `output.csv` | Asserts column order before write |
| `api/app.py` (optional) | FastAPI REST layer | Read-only wrapper over the above |

## 7. REST API Contract (optional bonus layer)

```
GET  /api/users/{user_id}/state
     → reconstructed financial state (balances, classified events)

GET  /api/requests/{request_id}
     → the raw request + resolved evidence (messages/images used)

POST /api/requests/{request_id}/decision
     → runs the full pipeline for one request, returns the 8 output fields
       plus the forecast series (for charting) and which evidence was used

GET  /api/requests/{request_id}/forecast?apply_plan=true
     → 90-day balance series, with/without the recommended plan overlay

POST /api/run-batch
     → runs the full requests.csv and returns a summary (used by the
       React "run" button; the CLI (`code/main.py`) remains the
       source of truth for the submitted output.csv)
```

## 8. Failure Modes & Handling

| Failure | Handling |
|---|---|
| Image file referenced but missing on disk | Do not invent a value; log and treat the event's amount as unresolved (exclude from cash flow with a note in `decision_explanation` if it drives the outcome) |
| VLM extraction low-confidence | Re-prompt once with a stricter format instruction; if still low-confidence, prefer the financially safer interpretation |
| Two records conflict | Apply conflict-resolution order from PRD §5.6 exactly |
| No eligible payment method at all | `not_recommended`, `payment_plan = none`, explain why |
| LLM API call fails/times out | Retry once, then fall back to template-based explanation; never block the deterministic decision on this |

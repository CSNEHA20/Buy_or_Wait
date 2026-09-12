# UI/UX Design Document
## Buy or Wait? — Optional Demo Frontend (React)

Note: the graded deliverable is `output.csv`, not this UI. Build this only after the CSV pipeline is verified and time remains. Its purpose is to make the AI Judge interview easier — you can literally show a live decision instead of only reading CSV rows.

---

## 1. Design Goals

- Make the reasoning **visible**: show which numbers and events drove the decision, not just the final label.
- Keep it fast to build: 2–3 screens, no auth, no persistence beyond the session.
- Reuse the same backend logic the CLI uses (`code/main.py` modules), via the FastAPI layer — never re-implement decision logic in the frontend.

## 2. Information Architecture

```
App
 ├─ Screen 1: Request Selector
 │    - dropdown/search over dataset/requests.csv (250 items)
 │    - shows request_text, requested_amount, desired_completion_date
 │
 ├─ Screen 2: Decision Result (main screen)
 │    - Header: affordability_status badge + recommended_payment_method
 │    - Payment Plan timeline (chips: date → amount)
 │    - 90-Day Balance Forecast chart (line chart, minimum_balance_to_keep
 │      shown as a red threshold line)
 │    - Evidence panel: which messages/images/events were used, with a
 │      one-line note on how each affected the decision
 │    - Spending Changes panel (stop/reduce_to, if any)
 │    - Decision Explanation text block
 │
 └─ Screen 3 (optional): Batch Run
      - "Run full dataset" button → progress bar → summary stats
        (status distribution, avg amount_safe_to_pay, token/cost usage)
```

## 3. Screen-by-Screen Detail

### Screen 1 — Request Selector
- Search box (filters by `request_id`, `user_id`, or `request_text` substring).
- List/table: `request_id | user_id | request_type | requested_amount | desired_completion_date`.
- Clicking a row navigates to Screen 2 and triggers `POST /api/requests/{id}/decision`.

### Screen 2 — Decision Result
- **Status badge** (top-left): color-coded
  - `affordable_now` → green
  - `affordable_with_plan` → blue
  - `affordable_later` → amber
  - `not_affordable` → red
- **Method chip**: `full_payment` / `partial_payment` / `installments` / `wait` / `not_recommended`.
- **Payment plan timeline**: horizontal chips, one per `date:amount` pair from `payment_plan`, in chronological order; `none` renders as a single greyed "No payment recommended" chip.
- **Forecast chart**: line = simulated balance per day for 90 days; flat dashed red line = `minimum_balance_to_keep`; a marker at `request_date` and at `earliest_date_for_full_payment` (if present).
- **Evidence panel**: cards for each message/image actually used, each showing:
  - source type (message/image), a short excerpt/thumbnail, and one line on the fact it contributed (e.g. "Payroll letter confirmed salary settles Sept 30").
- **Spending changes panel**: list of `stop:<event_id>` or `reduce_to:<event_id>:<amount>` with the human-readable event name/category.
- **Decision explanation**: plain text, 1–3 sentences.

### Screen 3 — Batch Run (optional)
- Single button, disabled while running.
- On completion: shows counts per `affordability_status`, per `recommended_payment_method`, and the token/cost summary pulled from the same accounting `llm_client.py` uses for `evaluation/usage_report.md`.
- Download link for the generated `output.csv`.

## 4. Visual Language

- Keep it minimal and financial-app-like: neutral background, one accent color for the primary action, semantic colors only for status badges (green/blue/amber/red as above).
- Typography: one sans-serif family, clear hierarchy (status > amount > supporting text).
- Numbers always shown with the user's `home_currency` symbol/code, never converted for display.
- Dates always `YYYY-MM-DD` to match the dataset convention (avoids ambiguity when explaining to the judge).

## 5. Component List (React)

```
<RequestSearchBar />
<RequestTable />
<StatusBadge status={...} />
<MethodChip method={...} />
<PaymentPlanTimeline plan={...} />
<ForecastChart series={...} minBalance={...} markers={...} />
<EvidenceCard type="message|image" excerpt={...} note={...} />
<SpendingChangeList changes={...} />
<DecisionExplanation text={...} />
<BatchRunPanel />  // optional
```

## 6. State Management

- Simple: React state + fetch calls to the FastAPI backend; no global store needed for a 2–3 screen demo.
- Cache the last N decisions client-side (in-memory) so revisiting a request doesn't re-trigger a backend/LLM call during the live demo.

## 7. Accessibility & Judge-Demo Considerations

- High contrast for status colors (don't rely on color alone — always pair with text label, per the badge design above).
- Keep the forecast chart readable at a shared-screen resolution during the interview (large enough axis labels).
- Have 2–3 pre-selected interesting `request_id`s ready to click during the interview (one `affordable_now`, one `affordable_with_plan` with a spending change, one `not_affordable`) to showcase range without hunting live.

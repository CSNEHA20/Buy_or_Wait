# Sample Evaluation Report

## Score

- Samples: 25 expected, 25 predicted, 0 missing, 0 unexpected
- Decision-field matches: 86/150 (57.3%)
- Decision-field mismatches: 64
- Explanation mismatches (reported separately): 25

Numeric amounts use an absolute tolerance of 0.01. Categorical, plan, date, and spending-change fields use exact matching. Explanations are compared by their extracted date/currency/number facts and are reported separately from the decision score.

## Field-by-field mismatches

| Request | Field | Expected | Actual | Likely root cause |
|---|---|---|---|---|
| request_01 | decision_explanation | Pay ZAR 25,256 today. This leaves at least ZAR 18,000 available over the next 90 days. | Recommended full_payment via deterministic decision rules. | explanation wording/fallback differs |
| request_02 | amount_safe_to_pay | 17229139.2 | 20118009.39 | minimum balance, pending events, recurrence, or currency conversion |
| request_02 | decision_explanation | Use 3 installments of IDR 15,952,906.67, starting 8 August 2025. This leaves at least IDR 29,158,400 available. | Recommended installments via deterministic decision rules. | explanation wording/fallback differs |
| request_03 | amount_safe_to_pay | 873000 | 1072972.06 | minimum balance, pending events, recurrence, or currency conversion |
| request_03 | affordability_status | affordable_later | not_affordable | affordability classification |
| request_03 | recommended_payment_method | wait | not_recommended | payment-option matching or tie-break ordering |
| request_03 | payment_plan | 2019-11-15:5491000 | none | candidate generation or tie-break ordering |
| request_03 | earliest_date_for_full_payment | 2019-11-15 |  | 90-day forecast or completion deadline |
| request_03 | decision_explanation | Pay IDR 5,491,000 in full on 15 November 2019. Paying earlier would take the balance below the IDR 2,668,700 minimum. | No safe payment method found that keeps minimum balance protected. | explanation wording/fallback differs |
| request_04 | amount_safe_to_pay | 8401800 | 12693000.0 | minimum balance, pending events, recurrence, or currency conversion |
| request_04 | affordability_status | affordable_later | affordable_now | affordability classification |
| request_04 | recommended_payment_method | wait | full_payment | payment-option matching or tie-break ordering |
| request_04 | payment_plan | 2024-06-15:12693000 | 2024-06-04:12693000 | candidate generation or tie-break ordering |
| request_04 | earliest_date_for_full_payment | 2024-06-15 | 2024-06-04 | 90-day forecast or completion deadline |
| request_04 | decision_explanation | Wait until 15 June 2024, then pay IDR 12,693,000 in full. Paying sooner would put the IDR 30,686,600 minimum at risk. | Recommended full_payment via deterministic decision rules. | explanation wording/fallback differs |
| request_05 | amount_safe_to_pay | 737 | 15488.0 | minimum balance, pending events, recurrence, or currency conversion |
| request_05 | affordability_status | not_affordable | affordable_now | affordability classification |
| request_05 | recommended_payment_method | not_recommended | full_payment | payment-option matching or tie-break ordering |
| request_05 | payment_plan | none | 2025-11-06:15488 | candidate generation or tie-break ordering |
| request_05 | earliest_date_for_full_payment |  | 2025-11-06 | 90-day forecast or completion deadline |
| request_05 | decision_explanation | Do not make this payment by 12 January 2026. None of the available options keeps the ZAR 13,100 minimum protected. | Recommended full_payment via deterministic decision rules. | explanation wording/fallback differs |
| request_06 | amount_safe_to_pay | 603.3 | 620.4 | minimum balance, pending events, recurrence, or currency conversion |
| request_06 | affordability_status | affordable_with_plan | affordable_now | affordability classification |
| request_06 | earliest_date_for_full_payment | 2026-01-15 | 2026-01-03 | 90-day forecast or completion deadline |
| request_06 | spending_changes_needed | stop:event_476 | none | spending-change restrictions or candidate generation |
| request_06 | decision_explanation | Stop the family streaming plan, then pay EUR 620.40 today. This leaves at least EUR 800 available. | Recommended full_payment via deterministic decision rules. | explanation wording/fallback differs |
| request_07 | amount_safe_to_pay | 87170.56 | 0.0 | minimum balance, pending events, recurrence, or currency conversion |
| request_07 | affordability_status | affordable_with_plan | not_affordable | affordability classification |
| request_07 | recommended_payment_method | installments | not_recommended | payment-option matching or tie-break ordering |
| request_07 | payment_plan | 2024-09-12:68432\|2024-10-10:68432\|2024-11-07:68432 | none | candidate generation or tie-break ordering |
| request_07 | earliest_date_for_full_payment | 2024-10-23 |  | 90-day forecast or completion deadline |
| request_07 | decision_explanation | Use 3 installments of INR 68,432, starting 12 September 2024. This leaves at least INR 93,000 available. | No safe payment method found that keeps minimum balance protected. | explanation wording/fallback differs |
| request_08 | amount_safe_to_pay | 284.57 | 432.57 | minimum balance, pending events, recurrence, or currency conversion |
| request_08 | payment_plan | 2025-04-15:996.60 | 2025-02-15:996.60 | candidate generation or tie-break ordering |
| request_08 | earliest_date_for_full_payment | 2025-04-15 | 2025-02-15 | 90-day forecast or completion deadline |
| request_08 | decision_explanation | Pay EUR 996.60 in full on 15 April 2025. Paying earlier would take the balance below the EUR 800 minimum. | Recommended wait via deterministic decision rules. | explanation wording/fallback differs |
| request_09 | decision_explanation | Pay EUR 166.61 today. This keeps the EUR 600 minimum available over the next 90 days. | Recommended full_payment via deterministic decision rules. | explanation wording/fallback differs |
| request_10 | amount_safe_to_pay | 12700 | 266700.0 | minimum balance, pending events, recurrence, or currency conversion |
| request_10 | earliest_date_for_full_payment |  | 2024-12-06 | 90-day forecast or completion deadline |
| request_10 | decision_explanation | Do not make this payment by 10 February 2025. None of the available options keeps the INR 225,400 minimum protected. | No safe payment method found that keeps minimum balance protected. | explanation wording/fallback differs |
| request_11 | amount_safe_to_pay | 12510645 | 13110000.0 | minimum balance, pending events, recurrence, or currency conversion |
| request_11 | affordability_status | affordable_with_plan | affordable_now | affordability classification |
| request_11 | earliest_date_for_full_payment | 2025-07-15 | 2025-05-03 | 90-day forecast or completion deadline |
| request_11 | spending_changes_needed | reduce_to:event_989:665950 | none | spending-change restrictions or candidate generation |
| request_11 | decision_explanation | Reduce the weekend food delivery to IDR 665,950, then pay IDR 13,110,000 today. This leaves at least IDR 34,140,600 available. | Recommended full_payment via deterministic decision rules. | explanation wording/fallback differs |
| request_12 | decision_explanation | Use 3 installments of ZAR 22,590.19, starting 19 April 2026. This leaves at least ZAR 43,200 available. | Recommended installments via deterministic decision rules. | explanation wording/fallback differs |
| request_13 | amount_safe_to_pay | 433.4 | 941.6 | minimum balance, pending events, recurrence, or currency conversion |
| request_13 | affordability_status | affordable_later | affordable_now | affordability classification |
| request_13 | recommended_payment_method | wait | full_payment | payment-option matching or tie-break ordering |
| request_13 | payment_plan | 2024-05-15:941.60 | 2024-03-07:941.60 | candidate generation or tie-break ordering |
| request_13 | earliest_date_for_full_payment | 2024-05-15 | 2024-03-07 | 90-day forecast or completion deadline |
| request_13 | decision_explanation | Pay EUR 941.60 in full on 15 May 2024. Paying earlier would take the balance below the EUR 1,300 minimum. | Recommended full_payment via deterministic decision rules. | explanation wording/fallback differs |
| request_14 | amount_safe_to_pay | 597.74 | 0.0 | minimum balance, pending events, recurrence, or currency conversion |
| request_14 | decision_explanation | Do not proceed with the EUR 5,414.20 request. Although EUR 597.74 is available today, the full amount cannot be completed safely within 90 days. | No safe payment method found that keeps minimum balance protected. | explanation wording/fallback differs |
| request_15 | amount_safe_to_pay | 83.05 | 0.0 | minimum balance, pending events, recurrence, or currency conversion |
| request_15 | decision_explanation | Do not make this payment by 1 February 2026. None of the available options keeps the EUR 1,200 minimum protected. | No safe payment method found that keeps minimum balance protected. | explanation wording/fallback differs |
| request_16 | decision_explanation | Pay INR 122,500 today. This leaves at least INR 122,400 available over the next 90 days. | Recommended full_payment via deterministic decision rules. | explanation wording/fallback differs |
| request_17 | amount_safe_to_pay | 243849.58 | 274600.0 | minimum balance, pending events, recurrence, or currency conversion |
| request_17 | earliest_date_for_full_payment | 2026-03-15 | 2026-03-01 | 90-day forecast or completion deadline |
| request_17 | decision_explanation | Use 3 installments of INR 95,194.67, starting 1 March 2026. This leaves at least INR 166,100 available. | Recommended installments via deterministic decision rules. | explanation wording/fallback differs |
| request_18 | amount_safe_to_pay | 462 | 690.16 | minimum balance, pending events, recurrence, or currency conversion |
| request_18 | payment_plan | 2026-09-15:3246.10 | 2026-08-16:3246.10 | candidate generation or tie-break ordering |
| request_18 | earliest_date_for_full_payment | 2026-09-15 | 2026-08-16 | 90-day forecast or completion deadline |
| request_18 | decision_explanation | Pay EUR 3,246.10 in full on 15 September 2026. Paying earlier would take the balance below the EUR 1,400 minimum. | Recommended wait via deterministic decision rules. | explanation wording/fallback differs |
| request_19 | amount_safe_to_pay | 28820 | 33895.25 | minimum balance, pending events, recurrence, or currency conversion |
| request_19 | payment_plan | 2024-09-04:28820\|2024-09-15:10840 | 2024-09-04:33895.25\|2024-09-15:5764.75 | candidate generation or tie-break ordering |
| request_19 | decision_explanation | Pay INR 28,820 today and the remaining INR 10,840 on 15 September 2024. This completes the full request and keeps the INR 92,800 minimum protected. | Recommended partial_payment via deterministic decision rules. | explanation wording/fallback differs |
| request_20 | amount_safe_to_pay | 5400 | 15912.64 | minimum balance, pending events, recurrence, or currency conversion |
| request_20 | decision_explanation | Do not make this payment by 22 February 2026. None of the available options keeps the INR 64,500 minimum protected. | No safe payment method found that keeps minimum balance protected. | explanation wording/fallback differs |
| request_21 | amount_safe_to_pay | 1543.35 | 1574.4 | minimum balance, pending events, recurrence, or currency conversion |
| request_21 | affordability_status | affordable_with_plan | affordable_now | affordability classification |
| request_21 | earliest_date_for_full_payment | 2026-04-15 | 2026-04-03 | 90-day forecast or completion deadline |
| request_21 | spending_changes_needed | stop:event_1815\|reduce_to:event_1816:23.50 | none | spending-change restrictions or candidate generation |
| request_21 | decision_explanation | Stop the online backup subscription and reduce the streaming subscription to USD 23.50, then pay USD 1,574.40 today. This leaves at least USD 1,800 available. | Recommended full_payment via deterministic decision rules. | explanation wording/fallback differs |
| request_22 | amount_safe_to_pay | 475.46 | 518.31 | minimum balance, pending events, recurrence, or currency conversion |
| request_22 | earliest_date_for_full_payment | 2025-01-15 | 2024-12-16 | 90-day forecast or completion deadline |
| request_22 | decision_explanation | Use 3 installments of EUR 253.59, starting 8 December 2024. This leaves at least EUR 500 available. | Recommended installments via deterministic decision rules. | explanation wording/fallback differs |
| request_23 | amount_safe_to_pay | 9152 | 11820.48 | minimum balance, pending events, recurrence, or currency conversion |
| request_23 | payment_plan | 2025-07-15:38016 | 2025-06-16:38016 | candidate generation or tie-break ordering |
| request_23 | earliest_date_for_full_payment | 2025-07-15 | 2025-06-16 | 90-day forecast or completion deadline |
| request_23 | decision_explanation | Pay ZAR 38,016 in full on 15 July 2025. Paying earlier would take the balance below the ZAR 27,000 minimum. | Recommended wait via deterministic decision rules. | explanation wording/fallback differs |
| request_24 | amount_safe_to_pay | 13420 | 18356.61 | minimum balance, pending events, recurrence, or currency conversion |
| request_24 | decision_explanation | Do not proceed with the INR 109,600 request. Although INR 13,420 is available today, the full amount cannot be completed safely within 90 days. | No safe payment method found that keeps minimum balance protected. | explanation wording/fallback differs |
| request_25 | amount_safe_to_pay | 1425000 | 4685888.06 | minimum balance, pending events, recurrence, or currency conversion |
| request_25 | affordability_status | not_affordable | affordable_later | affordability classification |
| request_25 | recommended_payment_method | not_recommended | wait | payment-option matching or tie-break ordering |
| request_25 | payment_plan | none | 2024-04-17:60496000 | candidate generation or tie-break ordering |
| request_25 | earliest_date_for_full_payment |  | 2024-04-17 | 90-day forecast or completion deadline |
| request_25 | decision_explanation | Do not make this payment by 17 April 2024. None of the available options keeps the IDR 23,379,100 minimum protected. | Recommended wait via deterministic decision rules. | explanation wording/fallback differs |

## Mismatch aggregates

### By field

| Field | Mismatches |
|---|---:|
| amount_safe_to_pay | 21 |
| affordability_status | 9 |
| recommended_payment_method | 6 |
| payment_plan | 10 |
| earliest_date_for_full_payment | 15 |
| spending_changes_needed | 3 |
| decision_explanation | 25 |

### By likely root cause

| Root cause | Mismatches |
|---|---:|
| minimum balance, pending events, recurrence, or currency conversion | 21 |
| 90-day forecast or completion deadline | 15 |
| candidate generation or tie-break ordering | 10 |
| affordability classification | 9 |
| payment-option matching or tie-break ordering | 6 |
| spending-change restrictions or candidate generation | 3 |

## Root-cause analysis and fixes

The scorer is intentionally diagnostic: it does not special-case request IDs or alter production predictions. The evaluator accepts numeric amounts within 0.01 and equivalent ISO/slash/ISO-datetime date renderings, while keeping categorical, payment-plan, and spending-change fields exact. Forecast regressions already covered by the repository include historical settled cash flows not being applied twice, settlement-date cash timing, and requiring three stable observations before recurring projection.

## Remaining discrepancies

See the complete table above. The current deterministic engine still has unresolved systematic discrepancies in conservative recurrence amounts, pending/settled event interpretation, installment candidate safety, deadline selection, and spending-change candidate generation. These are documented rather than hidden or fixed with request-ID special cases. Explanation wording differences are reported separately and are not treated as decision-engine defects unless their financial facts also differ.

### Systematic investigation

| Area | Finding | Disposition |
|---|---|---|
| Recurrence detection | Stable recurring series require at least three observations and a cadence within ±25% of the median gap. | Covered by forecast regression tests; residual sample mismatches remain in conservative amount selection. |
| Pending vs settled | Pending debits are reserved; pending credits are ignored; settled/scheduled cash uses settlement date when present. | Covered by forecast tests; no request-ID special case added. |
| Duplicate events and amendments | The current deterministic path does not yet fully reconcile linked duplicate/amended records from messages or images. | Remaining engine discrepancy; requires a general evidence-reconciliation change. |
| Currency conversion | Events are normalized through the dated FX converter before forecasting. | Remaining amount mismatches indicate broader forecast/safety differences, not scorer tolerance failures. |
| 90-day dates and deadlines | Forecast scans request date through request date + 90 days and stops at the requested completion date. | Remaining date mismatches are documented; do not shift dates to fit samples. |
| Candidate generation and tie-breaks | Full, wait, partial, installment, and spending-change candidates are ranked deterministically. | Remaining installment and spending-change mismatches need general algorithm work. |
| Minimum balance | Every simulated balance must remain at or above the profile minimum. | Remaining amount/status discrepancies are not explained away by the evaluator. |

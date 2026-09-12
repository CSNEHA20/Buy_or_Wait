# Dataset Inventory: Buy or Wait?

## Overview
Comprehensive audit of the challenge dataset in `dataset/` performed on 2026-09-12.

| File | Rows | Columns | Purpose | Key Relationships |
|---|---|---|---|---|
| `financial_profiles.csv` | 275 | 9 | User financial baseline, currencies, minimum balance, preferences | `user_id` (Primary Key) |
| `financial_events.csv` | 25,342 | 10 | Past/scheduled transactions, income, investments | `event_id` (PK), `user_id` (FK), `linked_event_id` |
| `exchange_rates.csv` | 134 | 4 | Dated conversion rates | `(rate_date, from_currency, to_currency)` |
| `requests.csv` | 250 | 7 | Evaluation requests to predict | `request_id` (PK), `user_id` (FK) |
| `sample_requests.csv` | 25 | 14 | Gold standard reference examples | `request_id` (PK), `user_id` (FK) |
| `request_payment_options.csv` | 790 | 9 | Available vendor payment offers per request | `payment_option_id` (PK), `request_id` (FK) |
| `messages.csv` | 215 | 6 | Evidence messages from employers, merchants, etc. | `message_id` (PK), `user_id` (FK), `request_id`, `related_event_id` |
| `images.csv` | 16 | 6 | Metadata mapping PNG receipts/letters to events/requests | `image_id` (PK), `related_event_id`, `request_id` |
| `media/images/*.png` | 16 files | Binary | PNG image evidence (image_01.png to image_16.png) | Corresponds 1:1 with `images.csv` |
| `output.csv` | 250 | 8 | Blank submission template | `request_id` matching `requests.csv` |

---

## Detailed Schema Audit

### 1. `financial_profiles.csv` (275 rows)
- **Columns**: `user_id`, `home_currency`, `current_available_balance`, `minimum_balance_to_keep`, `financial_priorities`, `protected_spending_categories`, `adjustable_spending_categories`, `payment_method_preferences`, `max_installment_months`
- **Currencies**: INR (67), EUR (62), IDR (55), ZAR (51), USD (40)
- **Installment Eligibility**: 119 users have blank `max_installment_months` (strictly no installments allowed).
- **Integrity**: All 275 users are distinct.

### 2. `financial_events.csv` (25,342 rows)
- **Columns**: `event_id`, `user_id`, `event_date`, `event_type`, `category`, `description`, `amount`, `currency`, `direction`, `status`, `flexibility`, `linked_event_id`
- **Statuses**: `settled` (25,148), `pending` (71), `scheduled` (70), `cancelled` (22), `failed` (21), `unrealized` (10)
- **Blank Amounts**: Exactly 16 events have blank `amount`. All 16 are mapped 1-to-1 to images in `images.csv`.
- **Flexibility**: `fixed` (21,138), `reducible` (2,682), `stoppable` (1,297), `reducible_or_stoppable` (225).

### 3. `exchange_rates.csv` (134 rows)
- **Columns**: `rate_date`, `from_currency`, `to_currency`, `rate`
- **Pairs**: `(EUR, USD)`, `(EUR, ZAR)`, `(USD, EUR)`, `(USD, IDR)`, `(USD, INR)`
- **Date Range**: `2023-10-15` to `2026-11-15` (39 unique dates).

### 4. `requests.csv` (250 rows)
- **Columns**: `request_id`, `user_id`, `request_date`, `request_type`, `requested_amount`, `desired_completion_date`, `allows_partial_payment`
- **Partial Payment**: 80 requests permit partial payment (`True`).
- **Date Range**: `2023-01-20` to `2026-09-04`.
- **Coverage**: Exactly 250 unique users (all present in `financial_profiles.csv`).

### 5. `sample_requests.csv` (25 rows)
- 25 reference examples with gold labels.
- Zero ID overlap with `requests.csv`.

### 6. `request_payment_options.csv` (790 rows)
- **Methods**: `full_payment` (275), `installments` (515).
- Every request has between 2 and 4 options (average ~2.9 options/request).

### 7. `messages.csv` (215 rows)
- **Sources**: `employer` (126), `service_provider` (31), `financial_service` (23), `bank` (18), `merchant` (17).
- 128 linked to `request_id`, 39 linked to `related_event_id`.

### 8. `images.csv` & `media/images/` (16 files)
- Exactly 16 records in `images.csv`.
- All 16 PNG files exist on disk: `image_01.png` to `image_16.png`.
- 100% of events with blank amounts (16 events) are covered by these 16 images.

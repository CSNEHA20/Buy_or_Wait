"""
verifier.py - Deterministic Output Verifier & Safety Gate for Buy or Wait?

verifier.py is the final deterministic safety gate before any row can enter output.csv.
It enforces 15 hard financial constraints and outputs structured failure reasons.
NO LLM calls allowed.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
import re
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    from buy_or_wait.forecast import ForecastState
except ImportError:
    ForecastState = Any


class VerificationResult:
    """Structured verification result containing validity flag and failure reasons."""

    def __init__(self, is_valid: bool, errors: List[str]):
        self.is_valid = is_valid
        self.errors = errors

    def __bool__(self) -> bool:
        return self.is_valid

    def __repr__(self) -> str:
        return f"VerificationResult(is_valid={self.is_valid}, errors={self.errors})"


ALLOWED_AFFORDABILITY_STATUSES = {
    "affordable_now",
    "affordable_with_plan",
    "affordable_later",
    "not_affordable",
}

ALLOWED_RECOMMENDED_PAYMENT_METHODS = {
    "full_payment",
    "partial_payment",
    "installments",
    "wait",
    "not_recommended",
}

REQUIRED_OUTPUT_FIELDS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]


def _get_val(obj: Any, key: str, default: Any = None) -> Any:
    """Safely extract attribute or dictionary item from obj."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def verify_decision(
    decision: Dict[str, Any],
    request: Optional[Any] = None,
    profile: Optional[Any] = None,
    forecast_state: Optional[Any] = None,
    payment_options: Optional[List[Any]] = None,
    future_events: Optional[List[Any]] = None,
) -> VerificationResult:
    """
    Validates a decision object or output row dictionary against all 15 hard constraints.

    Returns VerificationResult(is_valid: bool, errors: List[str]).
    """
    errors: List[str] = []

    # -------------------------------------------------------------------------
    # 9. Required output fields must exist
    # -------------------------------------------------------------------------
    for field in REQUIRED_OUTPUT_FIELDS:
        val = _get_val(decision, field)
        if val is None:
            errors.append(f"Missing required output field: '{field}'")
        elif field == "request_id" and str(val).strip() == "":
            errors.append("Field 'request_id' cannot be blank")

    status = _get_val(decision, "affordability_status")
    method = _get_val(decision, "recommended_payment_method")
    amt_safe_raw = _get_val(decision, "amount_safe_to_pay")
    plan_str = str(_get_val(decision, "payment_plan") or "")
    earliest_date_str = str(_get_val(decision, "earliest_date_for_full_payment") or "").strip()
    spending_changes_str = str(_get_val(decision, "spending_changes_needed") or "").strip()

    # -------------------------------------------------------------------------
    # 10. Allowed affordability statuses must be enforced
    # -------------------------------------------------------------------------
    if status is not None and status not in ALLOWED_AFFORDABILITY_STATUSES:
        errors.append(
            f"Invalid affordability_status: '{status}'. Must be one of {sorted(ALLOWED_AFFORDABILITY_STATUSES)}"
        )

    # -------------------------------------------------------------------------
    # 11. Allowed recommended payment methods must be enforced
    # -------------------------------------------------------------------------
    if method is not None and method not in ALLOWED_RECOMMENDED_PAYMENT_METHODS:
        errors.append(
            f"Invalid recommended_payment_method: '{method}'. Must be one of {sorted(ALLOWED_RECOMMENDED_PAYMENT_METHODS)}"
        )

    # Extract request-level context if available
    req_amt: Optional[Decimal] = None
    req_date: Optional[date] = None
    deadline: Optional[date] = None

    if request is not None:
        raw_req_amt = _get_val(request, "requested_amount")
        if raw_req_amt is not None:
            req_amt = Decimal(str(raw_req_amt))
        raw_req_date = _get_val(request, "request_date")
        if isinstance(raw_req_date, str) and raw_req_date:
            req_date = date.fromisoformat(raw_req_date)
        elif isinstance(raw_req_date, date):
            req_date = raw_req_date

        raw_deadline = _get_val(request, "desired_completion_date")
        if isinstance(raw_deadline, str) and raw_deadline:
            deadline = date.fromisoformat(raw_deadline)
        elif isinstance(raw_deadline, date):
            deadline = raw_deadline

    # -------------------------------------------------------------------------
    # 1. 0 <= amount_safe_to_pay <= requested_amount
    # -------------------------------------------------------------------------
    if amt_safe_raw is not None:
        try:
            amt_safe_val = Decimal(str(amt_safe_raw))
            if amt_safe_val < Decimal("0"):
                errors.append(f"amount_safe_to_pay ({amt_safe_val}) cannot be negative")
            if req_amt is not None and amt_safe_val > req_amt:
                errors.append(
                    f"amount_safe_to_pay ({amt_safe_val}) cannot exceed requested_amount ({req_amt})"
                )
        except Exception:
            errors.append(f"Invalid numeric value for amount_safe_to_pay: '{amt_safe_raw}'")

    # -------------------------------------------------------------------------
    # 2. affordable_now implies earliest_date_for_full_payment == request_date
    # -------------------------------------------------------------------------
    if status == "affordable_now":
        if req_date is not None:
            expected_date_str = req_date.isoformat()
            if earliest_date_str != expected_date_str:
                errors.append(
                    f"affordable_now status requires earliest_date_for_full_payment ('{earliest_date_str}') "
                    f"to equal request_date ('{expected_date_str}')"
                )
        elif not earliest_date_str:
            errors.append("affordable_now status requires earliest_date_for_full_payment to be specified")

    # -------------------------------------------------------------------------
    # Parse payment_plan entries
    # -------------------------------------------------------------------------
    parsed_payments: List[Tuple[date, Decimal]] = []
    is_none_plan = plan_str.strip().lower() in ("none", "")

    if not is_none_plan:
        parts = plan_str.split("|")
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if ":" not in part:
                errors.append(f"Malformed payment_plan entry '{part}'. Expected 'YYYY-MM-DD:amount'")
                continue
            d_str, a_str = part.split(":", 1)
            try:
                p_date = date.fromisoformat(d_str.strip())
                p_amt = Decimal(a_str.strip())
                parsed_payments.append((p_date, p_amt))
            except Exception:
                errors.append(f"Malformed payment_plan date or amount in '{part}'")

    # -------------------------------------------------------------------------
    # 6. payment_plan dates must be chronological
    # -------------------------------------------------------------------------
    if len(parsed_payments) > 1:
        for i in range(len(parsed_payments) - 1):
            d_curr = parsed_payments[i][0]
            d_next = parsed_payments[i + 1][0]
            if d_curr > d_next:
                errors.append(f"Payment plan dates are not chronological: {d_curr} > {d_next}")

    # -------------------------------------------------------------------------
    # 7. payment_plan amounts must be valid
    # -------------------------------------------------------------------------
    for p_date, p_amt in parsed_payments:
        if p_amt <= Decimal("0"):
            errors.append(f"Payment plan amount must be > 0 (got {p_amt} on {p_date})")

    if not is_none_plan and parsed_payments:
        total_plan_amt = sum(pa for _, pa in parsed_payments)
        if method in ("full_payment", "wait") and req_amt is not None:
            if total_plan_amt != req_amt:
                errors.append(
                    f"Payment plan total ({total_plan_amt}) does not match requested_amount ({req_amt})"
                )
        elif method == "partial_payment" and req_amt is not None:
            if total_plan_amt != req_amt:
                errors.append(
                    f"Partial payment plan total ({total_plan_amt}) does not match requested_amount ({req_amt})"
                )

    # -------------------------------------------------------------------------
    # 8. payment_plan must be "none" when no payment is recommended
    # -------------------------------------------------------------------------
    if method == "not_recommended" or status == "not_affordable":
        if not is_none_plan:
            errors.append("payment_plan must be 'none' when method is 'not_recommended' or status is 'not_affordable'")
    else:
        if is_none_plan:
            errors.append(f"payment_plan cannot be 'none' when recommended_payment_method is '{method}'")

    # -------------------------------------------------------------------------
    # 12. partial payment must have exactly two payments
    # -------------------------------------------------------------------------
    if method == "partial_payment":
        if len(parsed_payments) != 2:
            errors.append(f"partial_payment must have exactly two payments (got {len(parsed_payments)})")
        else:
            (d1, a1), (d2, a2) = parsed_payments
            if req_date is not None and d1 != req_date:
                errors.append(f"First payment of partial_payment must be on request_date ({req_date}), got {d1}")
            if amt_safe_raw is not None and Decimal(str(amt_safe_raw)) != a1:
                errors.append(
                    f"First payment of partial_payment ({a1}) must match amount_safe_to_pay ({amt_safe_raw})"
                )
            if earliest_date_str and d2 != date.fromisoformat(earliest_date_str):
                errors.append(
                    f"Second payment date of partial_payment ({d2}) must match earliest_date_for_full_payment ({earliest_date_str})"
                )
            if req_amt is not None and (a1 <= Decimal("0") or a1 >= req_amt):
                errors.append(
                    f"partial_payment requires 0 < amount_safe_to_pay < requested_amount (got a1={a1}, req={req_amt})"
                )
            if deadline is not None and d2 > deadline:
                errors.append(
                    f"Second payment of partial_payment ({d2}) exceeds desired_completion_date ({deadline})"
                )

    # -------------------------------------------------------------------------
    # 3. installment plan must match a real payment_option_id
    # -------------------------------------------------------------------------
    if method == "installments":
        if payment_options is not None:
            matched_opt = None
            for opt in payment_options:
                opt_method = _get_val(opt, "payment_method")
                if opt_method != "installments":
                    continue

                if profile is not None:
                    max_months = _get_val(profile, "max_installment_months")
                    opt_num_p = _get_val(opt, "number_of_payments")
                    if max_months is not None and opt_num_p is not None and opt_num_p > max_months:
                        continue

                opt_num = _get_val(opt, "number_of_payments") or 0
                opt_freq = _get_val(opt, "payment_frequency_days") or 0
                opt_first = _get_val(opt, "first_payment_date")
                if isinstance(opt_first, str):
                    opt_first = date.fromisoformat(opt_first)
                opt_amt = Decimal(str(_get_val(opt, "payment_amount") or 0))

                opt_payments = []
                cur_d = opt_first
                for _ in range(opt_num):
                    opt_payments.append((cur_d, opt_amt))
                    cur_d += timedelta(days=opt_freq)

                if parsed_payments == opt_payments:
                    matched_opt = opt
                    break

            if matched_opt is None:
                errors.append(
                    f"Installment plan '{plan_str}' does not match any valid payment option in request_payment_options.csv"
                )
        elif is_none_plan:
            errors.append("Installment recommendation must provide a non-empty payment plan")

    # -------------------------------------------------------------------------
    # Parse spending changes
    # -------------------------------------------------------------------------
    parsed_changes: List[Tuple[str, str, Optional[Decimal]]] = []
    if spending_changes_str.lower() != "none" and spending_changes_str != "":
        raw_items = [
            x.strip()
            for x in spending_changes_str.replace("|", ",").split(",")
            if x.strip()
        ]
        for item in raw_items:
            if item.startswith("stop:"):
                e_id = item[5:].strip()
                parsed_changes.append(("stop", e_id, None))
            elif item.startswith("reduce_to:"):
                rest = item[10:].strip()
                if ":" in rest:
                    e_id, new_amt_s = rest.split(":", 1)
                    try:
                        new_amt = Decimal(new_amt_s.strip())
                        parsed_changes.append(("reduce_to", e_id.strip(), new_amt))
                    except Exception:
                        errors.append(f"Malformed reduce_to spending change amount in '{item}'")
                else:
                    errors.append(
                        f"Malformed reduce_to spending change '{item}'. Expected 'reduce_to:event_id:amount'"
                    )
            else:
                errors.append(
                    f"Invalid spending change format: '{item}'. Must start with 'stop:' or 'reduce_to:'"
                )

    # -------------------------------------------------------------------------
    # 13. spending changes <= 3
    # -------------------------------------------------------------------------
    if len(parsed_changes) > 3:
        errors.append(f"Too many spending changes: max 3 allowed, got {len(parsed_changes)}")

    # -------------------------------------------------------------------------
    # 14. stop/reduce_to cannot target the same event
    # -------------------------------------------------------------------------
    targeted_event_ids = [e_id for _, e_id, _ in parsed_changes]
    if len(targeted_event_ids) != len(set(targeted_event_ids)):
        seen = set()
        dups = set()
        for e_id in targeted_event_ids:
            if e_id in seen:
                dups.add(e_id)
            seen.add(e_id)
        errors.append(f"Duplicate spending change target events: {sorted(dups)}")

    # -------------------------------------------------------------------------
    # 4. every spending change must target a flexible, non-protected recurring event
    # -------------------------------------------------------------------------
    if parsed_changes and (future_events is not None or profile is not None):
        protected_cats = set(
            _get_val(profile, "protected_categories")
            or _get_val(profile, "expense_categories_to_protect")
            or []
        ) if profile else set()
        adjustable_cats = set(_get_val(profile, "adjustable_categories") or [])
        if profile and not adjustable_cats:
            adjustable_cats = (
                set(_get_val(profile, "expense_categories_user_is_willing_to_reduce") or [])
                | set(_get_val(profile, "expense_categories_user_is_willing_to_stop") or [])
            )

        events_by_id = {}
        if future_events:
            for ev in future_events:
                ev_id = _get_val(ev, "event_id")
                if ev_id:
                    events_by_id[ev_id] = ev

        for action_type, e_id, new_amt in parsed_changes:
            if future_events is not None and e_id not in events_by_id:
                errors.append(f"Spending change targets non-existent event '{e_id}'")
                continue

            if e_id in events_by_id:
                ev = events_by_id[e_id]
                cat = _get_val(ev, "category") or ""
                flexibility = (_get_val(ev, "flexibility") or "").lower()
                is_recurring = _get_val(ev, "is_recurring")

                if is_recurring is False:
                    errors.append(f"Spending change targets non-recurring event '{e_id}'")

                if cat in protected_cats:
                    errors.append(
                        f"Spending change targets protected category '{cat}' for event '{e_id}'"
                    )

                if profile is not None and adjustable_cats and cat not in adjustable_cats:
                    errors.append(
                        f"Spending change targets non-adjustable category '{cat}' for event '{e_id}'"
                    )

                if action_type == "stop" and flexibility not in (
                    "stoppable",
                    "flexible",
                    "reducible_or_stoppable",
                ):
                    errors.append(
                        f"Event '{e_id}' has flexibility '{flexibility}', which cannot be stopped"
                    )

                if action_type == "reduce_to":
                    if flexibility not in ("reducible", "flexible", "reducible_or_stoppable"):
                        errors.append(
                            f"Event '{e_id}' has flexibility '{flexibility}', which cannot be reduced"
                        )
                    min_allowed = _get_val(ev, "minimum_allowed_amount")
                    if (
                        min_allowed is not None
                        and new_amt is not None
                        and new_amt < Decimal(str(min_allowed))
                    ):
                        errors.append(
                            f"reduce_to amount {new_amt} for event '{e_id}' is below minimum_allowed_amount ({min_allowed})"
                        )

    # -------------------------------------------------------------------------
    # 15. request completion must meet desired_completion_date for a recommended plan
    # -------------------------------------------------------------------------
    if method in ("full_payment", "partial_payment", "installments", "wait"):
        if deadline is not None and parsed_payments:
            last_payment_date = max(d for d, _ in parsed_payments)
            if last_payment_date > deadline:
                errors.append(
                    f"Payment plan completion date ({last_payment_date}) exceeds desired_completion_date ({deadline})"
                )

    # -------------------------------------------------------------------------
    # 5. no candidate/output row may breach minimum_balance_to_keep in simulation
    # -------------------------------------------------------------------------
    if forecast_state is not None and method != "not_recommended" and parsed_payments:
        sim_fs = forecast_state.copy()
        uid = _get_val(profile, "user_id") or _get_val(request, "user_id") or "user"

        overlay_flows: Dict[str, Dict[date, Decimal]] = {uid: {}}

        # Add payment plan overlay (outflows)
        for p_date, p_amt in parsed_payments:
            overlay_flows[uid][p_date] = (
                overlay_flows[uid].get(p_date, Decimal("0")) - p_amt
            )

        # Add spending changes overlay (inflows / saved cash)
        if parsed_changes and future_events:
            events_by_id = {
                _get_val(ev, "event_id"): ev
                for ev in future_events
                if _get_val(ev, "event_id")
            }
            for action_type, e_id, new_amt in parsed_changes:
                if e_id in events_by_id:
                    ev = events_by_id[e_id]
                    e_date = _get_val(ev, "event_date")
                    if isinstance(e_date, str):
                        e_date = date.fromisoformat(e_date)
                    orig_amt = Decimal(str(_get_val(ev, "amount") or 0))

                    if action_type == "stop":
                        overlay_flows[uid][e_date] = (
                            overlay_flows[uid].get(e_date, Decimal("0")) + orig_amt
                        )
                    elif action_type == "reduce_to" and new_amt is not None:
                        savings = orig_amt - new_amt
                        if savings > Decimal("0"):
                            overlay_flows[uid][e_date] = (
                                overlay_flows[uid].get(e_date, Decimal("0")) + savings
                            )

        daily_bal = sim_fs.simulate_90_day(overlay_flows)
        min_keep = Decimal(str(sim_fs.minimum_balance))
        for d, bal in daily_bal.items():
            if bal < min_keep:
                errors.append(
                    f"Simulated balance breaches minimum_balance_to_keep ({min_keep}) on {d}: balance is {bal}"
                )
                break

    return VerificationResult(is_valid=(len(errors) == 0), errors=errors)


def verify_output_rows(
    rows: List[Dict[str, Any]],
    dataset: Optional[Any] = None,
) -> Dict[str, VerificationResult]:
    """
    Validates a list of output row dictionaries.
    Returns mapping from request_id -> VerificationResult.
    """
    results: Dict[str, VerificationResult] = {}
    for row in rows:
        req_id = str(row.get("request_id", "unknown"))
        req_obj = (
            dataset.requests.get(req_id)
            if (dataset and hasattr(dataset, "requests"))
            else None
        )
        prof_obj = (
            dataset.profiles.get(req_obj.user_id)
            if (req_obj and dataset and hasattr(dataset, "profiles"))
            else None
        )

        opts = None
        evs = None
        if dataset and req_obj and prof_obj:
            opts = [
                opt
                for opt in getattr(dataset, "payment_options_list", [])
                if getattr(opt, "request_id", None) == req_id
            ]
            evs = [
                ev
                for ev in getattr(dataset, "events_list", [])
                if getattr(ev, "user_id", None) == prof_obj.user_id
            ]

        res = verify_decision(
            row,
            request=req_obj,
            profile=prof_obj,
            forecast_state=None,
            payment_options=opts,
            future_events=evs,
        )
        results[req_id] = res
    return results

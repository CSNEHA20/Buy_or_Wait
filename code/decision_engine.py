"""
decision_engine.py - Core deterministic decision engine for Buy or Wait?

Generates, filters, ranks, and selects safe financial payment plans deterministically.
NO LLM calls allowed.
"""

from __future__ import annotations

import itertools
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple


def format_amount(amt: Any) -> str:
    """Format decimal/float amount: integer if whole number, else 2 decimal places."""
    dec = Decimal(str(amt))
    if dec == dec.to_integral_value():
        return str(int(dec))
    return f"{dec.quantize(Decimal('0.01')):.2f}"


class Candidate:
    """Represents a candidate payment plan option with spending changes."""

    def __init__(
        self,
        method: str,
        plan_str: str,
        spending_changes: List[str],
        is_safe: bool,
        completes_by_deadline: bool,
        total_amount: float,
        first_payment: date,
        num_payments: int,
        opt_id: str = "",
        amt_safe: Any = Decimal("0"),
        earliest_date: Optional[date] = None,
        requires_no_changes: Optional[bool] = None,
    ):
        self.method = method
        self.plan_str = plan_str
        self.spending_changes = spending_changes
        self.is_safe = is_safe
        self.completes_by_deadline = completes_by_deadline
        self.total_amount = total_amount
        self.first_payment = first_payment
        self.num_payments = num_payments
        self.opt_id = opt_id
        self.amt_safe = amt_safe
        self.earliest_date = earliest_date
        self.requires_no_changes = (
            requires_no_changes
            if requires_no_changes is not None
            else (len(spending_changes) == 0)
        )

    def sort_key(self) -> Tuple[bool, int, float, date, int, str]:
        """
        Ranking criteria (strict order per AGENTS.md / PRD §6.3):
        1. Completes by desired_completion_date (True first -> not True = False)
        2. Requires no spending changes (fewer changes preferred: 0 < 1 < 2 < 3)
        3. Minimizes total amount paid (float ascending)
        4. Earlier first payment date (date ascending)
        5. Fewer payments (int ascending)
        6. Lowest payment_option_id (str ascending)
        """
        return (
            not self.completes_by_deadline,
            len(self.spending_changes),
            self.total_amount,
            self.first_payment,
            self.num_payments,
            self.opt_id or "",
        )


class DecisionEngine:
    """
    Core deterministic financial decision engine.
    """

    def __init__(
        self,
        request: Any,
        profile: Any,
        forecast_state: Any,
        payment_options: List[Any],
        future_events: List[Any],
    ):
        self.request = request
        self.profile = profile
        self.fs = forecast_state
        self.payment_options = payment_options
        self.future_events = future_events
        self.req_amt = Decimal(str(request.requested_amount))
        self.req_date = request.request_date
        self.deadline = request.desired_completion_date

    def _is_safe_with_overlay(self, overlay: Dict[str, Dict[date, Decimal]]) -> bool:
        """Run 90-day simulation and check if balance never drops below minimum_balance."""
        daily = self.fs.simulate_90_day(overlay)
        return all(v >= self.fs.minimum_balance for v in daily.values())

    def _get_overlay(
        self,
        plan_payments: List[Tuple[date, Decimal]],
        spending_changes: List[Tuple[str, str, Decimal, date]],
    ) -> Dict[str, Dict[date, Decimal]]:
        """Construct flow overlays for candidate plan payments and spending changes."""
        uid = self.profile.user_id
        overlay: Dict[str, Dict[date, Decimal]] = {uid: {}}

        # Subtract plan payments from balance on payment dates
        for p_date, p_amt in plan_payments:
            if p_date not in overlay[uid]:
                overlay[uid][p_date] = Decimal("0")
            overlay[uid][p_date] -= p_amt

        # Add back money saved from spending changes on event dates
        for c_type, e_id, amt_saved, e_date in spending_changes:
            if e_date not in overlay[uid]:
                overlay[uid][e_date] = Decimal("0")
            overlay[uid][e_date] += amt_saved

        return overlay

    def _generate_spending_change_combinations(
        self,
    ) -> List[List[Tuple[str, str, Decimal, date]]]:
        """
        Generate all valid spending change combinations (0 to 3 changes).
        Respects protected categories, user willing categories, and flexibility flags.
        Prevents multiple changes on the same event_id.
        """
        possible = []
        protected = set(self.profile.expense_categories_to_protect or [])
        can_stop = set(
            self.profile.expense_categories_user_is_willing_to_stop or []
        )
        can_reduce = set(
            self.profile.expense_categories_user_is_willing_to_reduce or []
        )

        for ev in self.future_events:
            cat = ev.category
            if cat in protected:
                continue

            ev_date = ev.event_date
            ev_id = ev.event_id
            amt = Decimal(str(ev.amount or 0))
            flexibility = (ev.flexibility or "").lower()

            if cat in can_stop and flexibility in ("stoppable", "flexible"):
                possible.append(("stop", ev_id, amt, ev_date))

            if cat in can_reduce and flexibility in ("reducible", "flexible", "reducible_or_stoppable"):
                min_amt = Decimal(str(ev.minimum_allowed_amount or 0))
                if amt > min_amt:
                    possible.append(("reduce_to", ev_id, amt - min_amt, ev_date))

        combinations = [[]]
        for k in range(1, 4):  # max 3 changes
            for comb in itertools.combinations(possible, k):
                # Ensure no event_id appears more than once in the same combination
                event_ids = [x[1] for x in comb]
                if len(event_ids) == len(set(event_ids)):
                    combinations.append(list(comb))

        return combinations

    def run(self) -> Dict[str, Any]:
        """
        Run the candidate generation, safety verification, and tie-break ranking.
        Returns the structured result dict matching output.csv schema.
        """
        # 1. Compute baseline safe_amount_to_pay and earliest_date_for_full_payment (BEFORE spending changes)
        is_full_safe, safe_amt_dec = self.fs.compute_amount_safe_to_pay(self.req_amt)
        horizon_date = self.req_date + timedelta(days=90)
        if self.deadline is not None:
            horizon_date = min(horizon_date, self.deadline)
        earliest_full_date, found_full_date = self.fs.compute_earliest_date_for_full_payment(
            self.req_amt, horizon_date
        )
        earliest_date_str = earliest_full_date.isoformat() if found_full_date and earliest_full_date else ""

        # 2. Candidate generation
        candidates: List[Candidate] = []
        change_combs = self._generate_spending_change_combinations()
        considered_methods = set(self.profile.payment_methods_user_will_consider or [])

        for changes in change_combs:
            # Build string representations of spending changes
            change_strs = []
            for c_type, e_id, amt_diff, e_date in changes:
                if c_type == "stop":
                    change_strs.append(f"stop:{e_id}")
                else:
                    ev = next(e for e in self.future_events if e.event_id == e_id)
                    min_str = format_amount(ev.minimum_allowed_amount)
                    change_strs.append(f"reduce_to:{e_id}:{min_str}")

            # Option A: Full Payment Today
            if "full_payment" in considered_methods:
                payments = [(self.req_date, self.req_amt)]
                overlay = self._get_overlay(payments, changes)
                if self._is_safe_with_overlay(overlay):
                    completes = self.deadline is None or self.req_date <= self.deadline
                    plan_str = f"{self.req_date.isoformat()}:{format_amount(self.req_amt)}"
                    candidates.append(
                        Candidate(
                            method="full_payment",
                            plan_str=plan_str,
                            spending_changes=change_strs,
                            is_safe=True,
                            completes_by_deadline=completes,
                            total_amount=float(self.req_amt),
                            first_payment=self.req_date,
                            num_payments=1,
                            opt_id="",
                            amt_safe=self.req_amt,
                            earliest_date=self.req_date,
                        )
                    )

            # Option B: Wait (Full Payment Later)
            if "full_payment" in considered_methods:
                max_wait_days = 90
                if self.deadline:
                    days_to_deadline = (self.deadline - self.req_date).days
                    max_wait_days = min(90, max_wait_days)

                for d_offset in range(1, max_wait_days + 1):
                    wait_date = self.req_date + timedelta(days=d_offset)
                    if self.deadline and wait_date > self.deadline:
                        break
                    payments = [(wait_date, self.req_amt)]
                    overlay = self._get_overlay(payments, changes)
                    if self._is_safe_with_overlay(overlay):
                        plan_str = f"{wait_date.isoformat()}:{format_amount(self.req_amt)}"
                        candidates.append(
                            Candidate(
                                method="wait",
                                plan_str=plan_str,
                                spending_changes=change_strs,
                                is_safe=True,
                                completes_by_deadline=True,
                                total_amount=float(self.req_amt),
                                first_payment=wait_date,
                                num_payments=1,
                                opt_id="",
                                amt_safe=Decimal("0"),
                                earliest_date=wait_date,
                            )
                        )
                        break

            # Option C: Partial Payment (exactly two payments)
            if "partial_payment" in considered_methods and self.request.allows_partial_payment:
                # The contract defines the first partial payment as the
                # baseline amount_safe_to_pay, not the amount made safe by
                # optional spending changes.  Reuse the same rounded value
                # that is emitted in the output row.
                best_first = safe_amt_dec
                second_date = earliest_full_date
                if (
                    Decimal("0") < best_first < self.req_amt
                    and second_date is not None
                    and (self.deadline is None or second_date <= self.deadline)
                ):
                    rem = self.req_amt - best_first
                    payments = [(self.req_date, best_first), (second_date, rem)]
                    overlay = self._get_overlay(payments, changes)
                    if self._is_safe_with_overlay(overlay):
                        plan_str = (
                            f"{self.req_date.isoformat()}:{format_amount(best_first)}|"
                            f"{second_date.isoformat()}:{format_amount(rem)}"
                        )
                        candidates.append(
                            Candidate(
                                method="partial_payment",
                                plan_str=plan_str,
                                spending_changes=change_strs,
                                is_safe=True,
                                completes_by_deadline=True,
                                total_amount=float(self.req_amt),
                                first_payment=self.req_date,
                                num_payments=2,
                                opt_id="",
                                amt_safe=best_first,
                                earliest_date=second_date,
                            )
                        )

            # Option D: Installments
            if "installments" in considered_methods:
                for opt in self.payment_options:
                    if opt.payment_method != "installments":
                        continue
                    if (
                        self.profile.max_installment_months is not None
                        and opt.number_of_payments > self.profile.max_installment_months
                    ):
                        continue

                    payments = []
                    d = opt.first_payment_date
                    p_amt = Decimal(str(opt.payment_amount or 0))
                    for _ in range(opt.number_of_payments):
                        payments.append((d, p_amt))
                        d = d + timedelta(days=opt.payment_frequency_days)

                    last_payment_date = payments[-1][0]
                    completes = self.deadline is None or last_payment_date <= self.deadline

                    if completes:
                        overlay = self._get_overlay(payments, changes)
                        if self._is_safe_with_overlay(overlay):
                            plan_parts = [
                                f"{pd.isoformat()}:{format_amount(pa)}"
                                for pd, pa in payments
                            ]
                            plan_str = "|".join(plan_parts)
                            tot_amt = float(
                                opt.total_payable_amount
                                if opt.total_payable_amount is not None
                                else (opt.number_of_payments * p_amt)
                            )
                            candidates.append(
                                Candidate(
                                    method="installments",
                                    plan_str=plan_str,
                                    spending_changes=change_strs,
                                    is_safe=True,
                                    completes_by_deadline=True,
                                    total_amount=tot_amt,
                                    first_payment=opt.first_payment_date,
                                    num_payments=opt.number_of_payments,
                                    opt_id=opt.payment_option_id or "",
                                    amt_safe=p_amt if opt.first_payment_date == self.req_date else Decimal("0"),
                                    earliest_date=last_payment_date,
                                )
                            )

        # 3. Filter safe candidates that complete by deadline
        safe_candidates = [
            c for c in candidates if c.is_safe and c.completes_by_deadline
        ]

        if not safe_candidates:
            return {
                "request_id": self.request.request_id,
                "amount_safe_to_pay": float(safe_amt_dec),
                "affordability_status": "not_affordable",
                "recommended_payment_method": "not_recommended",
                "payment_plan": "none",
                "earliest_date_for_full_payment": earliest_date_str,
                "spending_changes_needed": "none",
                "decision_explanation": "No safe payment method found that keeps minimum balance protected.",
                "requested_amount": float(self.req_amt),
            }

        # 4. Rank candidates deterministically
        safe_candidates.sort(key=lambda c: c.sort_key())
        best = safe_candidates[0]

        # 5. Derive affordability_status
        if best.method == "full_payment":
            status = "affordable_now" if len(best.spending_changes) == 0 else "affordable_with_plan"
        elif best.method == "wait":
            status = "affordable_later" if len(best.spending_changes) == 0 else "affordable_with_plan"
        else:  # partial_payment or installments
            status = "affordable_with_plan"

        changes_str = "|".join(best.spending_changes) if best.spending_changes else "none"

        return {
            "request_id": self.request.request_id,
            "amount_safe_to_pay": float(safe_amt_dec),
            "affordability_status": status,
            "recommended_payment_method": best.method,
            "payment_plan": best.plan_str,
            "earliest_date_for_full_payment": earliest_date_str,
            "spending_changes_needed": changes_str,
            "decision_explanation": f"Recommended {best.method} via deterministic decision rules.",
            "requested_amount": float(self.req_amt),
        }

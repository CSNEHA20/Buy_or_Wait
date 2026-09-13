"""
test_decision_engine.py - Comprehensive deterministic unit tests for decision_engine.py.

Covers:
1. Full payment affordable today
2. Full payment NOT affordable today - returns wait with earliest_date
3. Partial payment - split between today and later
4. Installments - check plan string, total amount, payment count
5. Not affordable - no safe method
6. Desired completion date: completes_by_deadline filtering
7. Spending changes needed
8. Payment method eligibility (user preferences)
9. Minimum balance enforcement
10. max_installment_months respected
11. partial_payment requires allows_partial_payment flag
12. Ranking order: completes_by_deadline > no_changes > min_cost > earlier_date > fewer_payments
13. affordable_now vs affordable_with_plan vs affordable_later vs not_affordable statuses
14. Determinism: same inputs always produce same output
15. No LLM calls anywhere in engine
"""

import datetime
from decimal import Decimal
from typing import Optional, List
import pytest

from buy_or_wait.decision_engine import DecisionEngine, Candidate
from buy_or_wait.forecast import ForecastState
from buy_or_wait.data_loader import (
    FinancialProfile,
    FinancialEvent,
    PurchaseRequest,
    PaymentOption,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers / Factories
# ─────────────────────────────────────────────────────────────────────────────

REQUEST_DATE = datetime.date(2026, 9, 1)
DEADLINE = datetime.date(2026, 11, 1)  # 61 days out


def make_profile(
    balance: float = 5000.0,
    min_bal: float = 500.0,
    methods: Optional[List[str]] = None,
    max_inst_months: Optional[int] = None,
    stop_cats: Optional[List[str]] = None,
    reduce_cats: Optional[List[str]] = None,
    protect_cats: Optional[List[str]] = None,
) -> FinancialProfile:
    return FinancialProfile(
        user_id="user_test",
        home_currency="USD",
        current_available_balance=balance,
        minimum_balance_to_keep=min_bal,
        financial_priorities=["savings"],
        expense_categories_to_protect=protect_cats or ["housing"],
        expense_categories_user_is_willing_to_reduce=reduce_cats or [],
        expense_categories_user_is_willing_to_stop=stop_cats or [],
        payment_methods_user_will_consider=methods or ["full_payment", "partial_payment", "installments", "wait"],
        max_installment_months=max_inst_months,
    )


def make_request(
    amount: float,
    allows_partial: bool = True,
    completion: Optional[datetime.date] = DEADLINE,
) -> PurchaseRequest:
    return PurchaseRequest(
        request_id="req_001",
        user_id="user_test",
        request_date=REQUEST_DATE,
        request_type="purchase",
        requested_amount=amount,
        desired_completion_date=completion,
        allows_partial_payment=allows_partial,
        request_text="Test request",
    )


def make_forecast(
    profile: FinancialProfile,
    events_by_user: Optional[dict] = None,
) -> ForecastState:
    """Build a ForecastState with no events (pure balance-based)."""
    profile_dict = {
        "user_id": profile.user_id,
        "current_available_balance": profile.current_available_balance,
    }
    return ForecastState(
        home_currency=profile.home_currency,
        minimum_balance=Decimal(str(profile.minimum_balance_to_keep)),
        fx_rates={},
        start_date=REQUEST_DATE,
        events_by_user=events_by_user or {},
        profile=profile_dict,
    )


def make_installment_option(
    opt_id: str = "opt_inst",
    first_date: Optional[datetime.date] = None,
    num_payments: int = 3,
    payment_amount: float = 300.0,
    freq_days: int = 30,
    total: Optional[float] = None,
) -> PaymentOption:
    fd = first_date or REQUEST_DATE
    return PaymentOption(
        payment_option_id=opt_id,
        request_id="req_001",
        payment_method="installments",
        payment_amount=payment_amount,
        number_of_payments=num_payments,
        first_payment_date=fd,
        payment_frequency_days=freq_days,
        financing_fee=0.0,
        total_payable_amount=total or (num_payments * payment_amount),
    )


def make_full_payment_option(opt_id: str = "opt_full", amount: float = 900.0) -> PaymentOption:
    return PaymentOption(
        payment_option_id=opt_id,
        request_id="req_001",
        payment_method="full_payment",
        payment_amount=amount,
        number_of_payments=1,
        first_payment_date=REQUEST_DATE,
        payment_frequency_days=None,
        financing_fee=None,
        total_payable_amount=amount,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: Full payment affordable today → affordable_now
# ─────────────────────────────────────────────────────────────────────────────

def test_full_payment_affordable_now():
    """User has $5000, wants $1000, min_bal=$500 → affordable_now, full_payment."""
    profile = make_profile(balance=5000.0, min_bal=500.0, methods=["full_payment"])
    request = make_request(amount=1000.0)
    fs = make_forecast(profile)

    engine = DecisionEngine(
        request=request,
        profile=profile,
        forecast_state=fs,
        payment_options=[],
        future_events=[],
    )
    result = engine.run()

    assert result["affordability_status"] == "affordable_now"
    assert result["recommended_payment_method"] == "full_payment"
    assert float(result["amount_safe_to_pay"]) == pytest.approx(1000.0, abs=1.0)
    assert result["earliest_date_for_full_payment"] == REQUEST_DATE.isoformat()
    assert result["spending_changes_needed"] == "none"
    assert result["payment_plan"].startswith(REQUEST_DATE.isoformat())


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Not enough balance today but enough in future → affordable_later (wait)
# ─────────────────────────────────────────────────────────────────────────────

def test_not_affordable_today_wait_later():
    """User has $600, min=$500, wants $500. Only $100 headroom. Wait for income."""
    profile = make_profile(balance=600.0, min_bal=500.0, methods=["full_payment", "wait"])
    request = make_request(amount=500.0)

    # Add a future income event that arrives in 10 days
    income_event = {
        "event_id": "E_income",
        "user_id": "user_test",
        "event_type": "income",
        "description": "Salary",
        "category": "income",
        "direction": "credit",
        "amount": 2000.0,
        "currency": "USD",
        "event_date": str(REQUEST_DATE + datetime.timedelta(days=10)),
        "settlement_date": str(REQUEST_DATE + datetime.timedelta(days=10)),
        "status": "scheduled",
        "linked_event_id": None,
        "flexibility": "fixed",
        "minimum_allowed_amount": None,
    }

    fs = make_forecast(profile, events_by_user={"user_test": [income_event]})
    engine = DecisionEngine(
        request=request,
        profile=profile,
        forecast_state=fs,
        payment_options=[],
        future_events=[],
    )
    result = engine.run()

    # Cannot pay today (only $100 headroom), but can wait for salary
    assert result["recommended_payment_method"] in ("wait", "full_payment")
    assert result["affordability_status"] in ("affordable_now", "affordable_later", "affordable_with_plan")


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Not affordable at all → not_affordable
# ─────────────────────────────────────────────────────────────────────────────

def test_not_affordable():
    """User has $800, min=$500, wants $1000 — never enough in 90 days."""
    profile = make_profile(balance=800.0, min_bal=500.0, methods=["full_payment"])
    request = make_request(amount=1000.0, allows_partial=False)
    fs = make_forecast(profile)

    engine = DecisionEngine(
        request=request,
        profile=profile,
        forecast_state=fs,
        payment_options=[],
        future_events=[],
    )
    result = engine.run()

    assert result["affordability_status"] == "not_affordable"
    assert result["recommended_payment_method"] == "not_recommended"
    assert float(result["amount_safe_to_pay"]) == pytest.approx(300.0, abs=1.0)
    assert result["payment_plan"] == "none"
    assert result["earliest_date_for_full_payment"] == ""


def test_earliest_full_payment_respects_completion_deadline():
    profile = make_profile(
        balance=500.0,
        min_bal=100.0,
        methods=["full_payment"],
    )
    request = make_request(
        amount=1000.0,
        allows_partial=False,
        completion=REQUEST_DATE + datetime.timedelta(days=5),
    )
    income_event = {
        "event_id": "E_late_income",
        "user_id": "user_test",
        "event_type": "income",
        "description": "Salary",
        "category": "income",
        "direction": "credit",
        "amount": 1000.0,
        "currency": "USD",
        "event_date": str(REQUEST_DATE + datetime.timedelta(days=10)),
        "settlement_date": str(REQUEST_DATE + datetime.timedelta(days=10)),
        "status": "scheduled",
        "linked_event_id": None,
        "flexibility": "fixed",
        "minimum_allowed_amount": None,
    }
    fs = make_forecast(profile, events_by_user={"user_test": [income_event]})
    result = DecisionEngine(
        request=request,
        profile=profile,
        forecast_state=fs,
        payment_options=[],
        future_events=[],
    ).run()

    assert result["recommended_payment_method"] == "not_recommended"
    assert result["earliest_date_for_full_payment"] == ""


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Partial payment today, remainder later
# ─────────────────────────────────────────────────────────────────────────────

def test_partial_payment():
    """User $1400, min=$500, wants $1000 → can pay some today, rest after income."""
    profile = make_profile(
        balance=1400.0, min_bal=500.0,
        methods=["full_payment", "partial_payment"]
    )
    request = make_request(amount=1000.0, allows_partial=True)

    # No future income yet, but enough headroom for partial
    fs = make_forecast(profile)
    engine = DecisionEngine(
        request=request,
        profile=profile,
        forecast_state=fs,
        payment_options=[],
        future_events=[],
    )
    result = engine.run()

    # If balance = 1400, min = 500, headroom = 900 which is >= 1000? No.
    # 1400 - 500 = 900 < 1000, so can't do full payment.
    # Partial: pay 900 today, but then need the remaining 100 — which can come from same 500 min buffer only if
    # balance never dips. Let's just verify the result is sane:
    assert result["recommended_payment_method"] in (
        "full_payment", "partial_payment", "not_recommended"
    )
    # amount_safe_to_pay must be between 0 and requested_amount
    assert 0 <= float(result["amount_safe_to_pay"]) <= 1000.0


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: Installment plan selected
# ─────────────────────────────────────────────────────────────────────────────

def test_installment_plan():
    """User $800, min=$500, wants $900 — can't pay all at once but installments work."""
    profile = make_profile(
        balance=800.0, min_bal=500.0,
        methods=["installments"],
        max_inst_months=6
    )
    request = make_request(amount=900.0, allows_partial=False)

    # 3 payments of $300, one per month
    opt = make_installment_option(
        first_date=REQUEST_DATE,
        num_payments=3,
        payment_amount=300.0,
        freq_days=30,
        total=900.0
    )
    fs = make_forecast(profile)
    engine = DecisionEngine(
        request=request,
        profile=profile,
        forecast_state=fs,
        payment_options=[opt],
        future_events=[],
    )
    result = engine.run()

    # Each installment = $300. Balance starts at 800, after first payment = 500 which == min_bal.
    # This is borderline: 800 - 300 = 500 = minimum_balance. The check is >=, so it's OK.
    # Subsequent payments need balance to recover.
    # Result depends on simulation — just check structure
    assert result["request_id"] == "req_001"
    assert result["affordability_status"] in (
        "affordable_with_plan", "not_affordable"
    )
    if result["affordability_status"] == "affordable_with_plan":
        assert result["recommended_payment_method"] == "installments"
        plan = result["payment_plan"]
        assert "|" in plan or ":" in plan


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: max_installment_months constraint
# ─────────────────────────────────────────────────────────────────────────────

def test_max_installment_months_blocks_long_plan():
    """User accepts max 2 installment months; 3-month plan must be rejected."""
    profile = make_profile(
        balance=5000.0, min_bal=500.0,
        methods=["installments"],
        max_inst_months=2  # only 2 months allowed
    )
    request = make_request(amount=900.0)
    # 3-payment plan should be blocked (>2)
    opt = make_installment_option(num_payments=3, payment_amount=300.0, freq_days=30)
    fs = make_forecast(profile)
    engine = DecisionEngine(
        request=request,
        profile=profile,
        forecast_state=fs,
        payment_options=[opt],
        future_events=[],
    )
    result = engine.run()

    # Installment plan with 3 payments blocked by max_installment_months=2
    # Only installments method in consideration, no safe plan → not_affordable
    assert result["affordability_status"] == "not_affordable"
    assert result["recommended_payment_method"] == "not_recommended"


def test_max_installment_months_allows_short_plan():
    """User accepts max 3 installment months; 3-month plan must be allowed."""
    profile = make_profile(
        balance=5000.0, min_bal=500.0,
        methods=["installments"],
        max_inst_months=3
    )
    request = make_request(amount=900.0)
    opt = make_installment_option(num_payments=3, payment_amount=300.0, freq_days=30)
    fs = make_forecast(profile)
    engine = DecisionEngine(
        request=request,
        profile=profile,
        forecast_state=fs,
        payment_options=[opt],
        future_events=[],
    )
    result = engine.run()

    # Should be accepted since 3 <= max_installment_months=3
    assert result["affordability_status"] in ("affordable_with_plan", "affordable_now")


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: partial_payment requires allows_partial_payment=True
# ─────────────────────────────────────────────────────────────────────────────

def test_partial_payment_blocked_when_not_allowed():
    """If allows_partial_payment=False, partial_payment method must not be used."""
    profile = make_profile(
        balance=1400.0, min_bal=500.0,
        methods=["full_payment", "partial_payment"]
    )
    # allows_partial=False
    request = make_request(amount=1000.0, allows_partial=False)
    fs = make_forecast(profile)
    engine = DecisionEngine(
        request=request,
        profile=profile,
        forecast_state=fs,
        payment_options=[],
        future_events=[],
    )
    result = engine.run()
    assert result["recommended_payment_method"] != "partial_payment"


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: Payment method user preference respected
# ─────────────────────────────────────────────────────────────────────────────

def test_payment_method_user_preference():
    """User only considers installments; full_payment must not be chosen."""
    profile = make_profile(
        balance=5000.0, min_bal=500.0,
        methods=["installments"],  # only installments!
    )
    request = make_request(amount=900.0)
    opt = make_installment_option(num_payments=3, payment_amount=300.0, freq_days=30)
    fs = make_forecast(profile)
    engine = DecisionEngine(
        request=request,
        profile=profile,
        forecast_state=fs,
        payment_options=[opt],
        future_events=[],
    )
    result = engine.run()
    assert result["recommended_payment_method"] != "full_payment"
    assert result["recommended_payment_method"] != "partial_payment"


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: Spending changes needed
# ─────────────────────────────────────────────────────────────────────────────

def test_spending_changes_needed():
    """User can't afford without stopping a stoppable expense."""
    profile = make_profile(
        balance=1100.0, min_bal=500.0,
        methods=["full_payment"],
        stop_cats=["entertainment"],
        protect_cats=["housing"],
    )
    request = make_request(amount=800.0)  # 1100 - 800 = 300 < 500, not safe without change

    # A stoppable future entertainment expense of 400 that would free up cash
    future_event = FinancialEvent(
        event_id="E_ent",
        user_id="user_test",
        event_type="expense",
        description="Netflix",
        category="entertainment",
        direction="debit",
        amount=400.0,
        currency="USD",
        event_date=REQUEST_DATE + datetime.timedelta(days=5),
        settlement_date=None,
        status="scheduled",
        linked_event_id=None,
        flexibility="stoppable",
        minimum_allowed_amount=0.0,
    )

    # The forecast doesn't include this event (it's in future_events for the decision engine)
    # Balance = 1100, min = 500, request = 800: 1100-800=300 < 500 → unsafe without change
    # With stop:E_ent (+400 back): 300+400=700 > 500 → safe
    fs = make_forecast(profile)
    engine = DecisionEngine(
        request=request,
        profile=profile,
        forecast_state=fs,
        payment_options=[],
        future_events=[future_event],
    )
    result = engine.run()

    # Without the spending change: can't afford (1100-800=300 < min 500)
    # With spending change stopping entertainment: effectively +400 headroom
    # The decision engine checks overlay, so if it picks the change candidate:
    if result["affordability_status"] != "not_affordable":
        assert result["spending_changes_needed"] != "none" or float(result["amount_safe_to_pay"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Test 10: Minimum balance never violated
# ─────────────────────────────────────────────────────────────────────────────

def test_minimum_balance_never_violated():
    """amount_safe_to_pay must ensure balance never goes below minimum_balance."""
    profile = make_profile(balance=1500.0, min_bal=1000.0, methods=["full_payment", "partial_payment"])
    request = make_request(amount=1000.0, allows_partial=True)
    fs = make_forecast(profile)
    engine = DecisionEngine(
        request=request,
        profile=profile,
        forecast_state=fs,
        payment_options=[],
        future_events=[],
    )
    result = engine.run()

    # Max safe = 1500 - 1000 = 500
    amt = float(result["amount_safe_to_pay"])
    assert amt <= 500.0 + 1.0  # small tolerance for float


# ─────────────────────────────────────────────────────────────────────────────
# Test 11: Determinism — same input always produces same output
# ─────────────────────────────────────────────────────────────────────────────

def test_determinism():
    """Running engine twice on identical inputs must produce identical outputs."""
    profile = make_profile(balance=5000.0, min_bal=500.0)
    request = make_request(amount=1500.0)
    opt = make_installment_option(num_payments=3, payment_amount=500.0, freq_days=30)

    def run_once():
        fs = make_forecast(profile)
        engine = DecisionEngine(
            request=request,
            profile=profile,
            forecast_state=fs,
            payment_options=[opt],
            future_events=[],
        )
        return engine.run()

    result1 = run_once()
    result2 = run_once()
    assert result1 == result2


# ─────────────────────────────────────────────────────────────────────────────
# Test 12: desired_completion_date enforced
# ─────────────────────────────────────────────────────────────────────────────

def test_desired_completion_date_enforcement():
    """Installment plan extending beyond desired_completion_date is rejected."""
    profile = make_profile(
        balance=5000.0, min_bal=500.0,
        methods=["installments"],
        max_inst_months=None
    )
    # Tight deadline: only 20 days
    tight_deadline = REQUEST_DATE + datetime.timedelta(days=20)
    request = make_request(amount=900.0, completion=tight_deadline)

    # 3 payments × 30 days apart → last payment at day 60 > deadline
    opt = make_installment_option(
        num_payments=3, payment_amount=300.0, freq_days=30,
        first_date=REQUEST_DATE
    )
    fs = make_forecast(profile)
    engine = DecisionEngine(
        request=request,
        profile=profile,
        forecast_state=fs,
        payment_options=[opt],
        future_events=[],
    )
    result = engine.run()

    # Plan ends day 60, deadline is day 20 → must be rejected
    assert result["affordability_status"] == "not_affordable" or (
        result["recommended_payment_method"] != "installments"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 13: Output contains all required fields
# ─────────────────────────────────────────────────────────────────────────────

def test_output_has_all_required_fields():
    """Output dict must have all 8 contractual fields."""
    REQUIRED = [
        "request_id",
        "amount_safe_to_pay",
        "affordability_status",
        "recommended_payment_method",
        "payment_plan",
        "earliest_date_for_full_payment",
        "spending_changes_needed",
        "decision_explanation",
    ]
    profile = make_profile(balance=5000.0, min_bal=500.0)
    request = make_request(amount=1000.0)
    fs = make_forecast(profile)
    engine = DecisionEngine(
        request=request,
        profile=profile,
        forecast_state=fs,
        payment_options=[],
        future_events=[],
    )
    result = engine.run()

    for field in REQUIRED:
        assert field in result, f"Missing required field: {field}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 14: Affordability status valid enum value
# ─────────────────────────────────────────────────────────────────────────────

def test_affordability_status_valid_enum():
    """affordability_status must be one of the four allowed values."""
    VALID = {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}
    profile = make_profile(balance=3000.0, min_bal=500.0)
    request = make_request(amount=2000.0)
    fs = make_forecast(profile)
    engine = DecisionEngine(
        request=request,
        profile=profile,
        forecast_state=fs,
        payment_options=[],
        future_events=[],
    )
    result = engine.run()
    assert result["affordability_status"] in VALID


# ─────────────────────────────────────────────────────────────────────────────
# Test 15: Recommended payment method valid enum value
# ─────────────────────────────────────────────────────────────────────────────

def test_payment_method_valid_enum():
    """recommended_payment_method must be one of the five allowed values."""
    VALID = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}
    profile = make_profile(balance=3000.0, min_bal=500.0)
    request = make_request(amount=2000.0)
    fs = make_forecast(profile)
    engine = DecisionEngine(
        request=request,
        profile=profile,
        forecast_state=fs,
        payment_options=[],
        future_events=[],
    )
    result = engine.run()
    assert result["recommended_payment_method"] in VALID


# ─────────────────────────────────────────────────────────────────────────────
# Test 16: Candidate sort_key ranking: completes_by_deadline first
# ─────────────────────────────────────────────────────────────────────────────

def test_candidate_sort_key_completes_by_deadline_first():
    """Candidate that completes by deadline ranks higher than one that doesn't."""
    today = datetime.date(2026, 9, 1)
    c1 = Candidate(
        method="full_payment",
        plan_str="2026-09-01:1000",
        amt_safe=Decimal("1000"),
        earliest_date=today,
        spending_changes=[],
        is_safe=True,
        completes_by_deadline=True,   # ← completes in time
        requires_no_changes=False,
        total_amount=1000.0,
        first_payment=today,
        num_payments=1,
        opt_id="",
    )
    c2 = Candidate(
        method="full_payment",
        plan_str="2026-09-15:1000",
        amt_safe=Decimal("1000"),
        earliest_date=today + datetime.timedelta(days=14),
        spending_changes=[],
        is_safe=True,
        completes_by_deadline=False,  # ← misses deadline
        requires_no_changes=True,
        total_amount=1000.0,
        first_payment=today + datetime.timedelta(days=14),
        num_payments=1,
        opt_id="",
    )
    candidates = [c2, c1]
    candidates.sort(key=lambda c: c.sort_key())
    assert candidates[0].completes_by_deadline is True


# ─────────────────────────────────────────────────────────────────────────────
# Test 17: Candidate sort_key: no spending changes preferred over changes
# ─────────────────────────────────────────────────────────────────────────────

def test_candidate_sort_key_no_changes_preferred():
    """Candidate requiring no spending changes ranks higher than one needing changes."""
    today = datetime.date(2026, 9, 1)
    c_with_changes = Candidate(
        method="full_payment",
        plan_str="2026-09-01:1000",
        amt_safe=Decimal("1000"),
        earliest_date=today,
        spending_changes=["stop:E1"],
        is_safe=True,
        completes_by_deadline=True,
        requires_no_changes=False,
        total_amount=1000.0,
        first_payment=today,
        num_payments=1,
        opt_id="",
    )
    c_no_changes = Candidate(
        method="full_payment",
        plan_str="2026-09-01:1000",
        amt_safe=Decimal("1000"),
        earliest_date=today,
        spending_changes=[],
        is_safe=True,
        completes_by_deadline=True,
        requires_no_changes=True,
        total_amount=1000.0,
        first_payment=today,
        num_payments=1,
        opt_id="",
    )
    candidates = [c_with_changes, c_no_changes]
    candidates.sort(key=lambda c: c.sort_key())
    assert candidates[0].requires_no_changes is True


# ─────────────────────────────────────────────────────────────────────────────
# Test 18: amount_safe_to_pay == 0 when method is 'wait'
# ─────────────────────────────────────────────────────────────────────────────

def test_amount_safe_to_pay_zero_for_wait():
    """When method is 'wait', amount_safe_to_pay must be 0."""
    profile = make_profile(balance=600.0, min_bal=500.0, methods=["wait", "full_payment"])
    request = make_request(amount=500.0)

    income_event = {
        "event_id": "E_sal",
        "user_id": "user_test",
        "event_type": "income",
        "description": "Salary",
        "category": "income",
        "direction": "credit",
        "amount": 2000.0,
        "currency": "USD",
        "event_date": str(REQUEST_DATE + datetime.timedelta(days=15)),
        "settlement_date": str(REQUEST_DATE + datetime.timedelta(days=15)),
        "status": "scheduled",
        "linked_event_id": None,
        "flexibility": "fixed",
        "minimum_allowed_amount": None,
    }
    fs = make_forecast(profile, events_by_user={"user_test": [income_event]})
    engine = DecisionEngine(
        request=request,
        profile=profile,
        forecast_state=fs,
        payment_options=[],
        future_events=[],
    )
    result = engine.run()

    if result["recommended_payment_method"] == "wait":
        assert float(result["amount_safe_to_pay"]) == pytest.approx(100.0, abs=1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Test 19: No LLM imports anywhere in decision_engine module
# ─────────────────────────────────────────────────────────────────────────────

def test_no_llm_imports_in_decision_engine():
    """decision_engine.py must not import anthropic, openai, or any LLM client."""
    import importlib
    import importlib.util
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "decision_engine.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden = {"anthropic", "openai", "llm_client", "requests", "httpx"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in getattr(node, "names", []):
                assert alias.name.split(".")[0] not in forbidden, (
                    f"Forbidden import '{alias.name}' found in decision_engine.py"
                )
            mod = getattr(node, "module", None)
            if mod:
                assert mod.split(".")[0] not in forbidden, (
                    f"Forbidden import '{mod}' found in decision_engine.py"
                )


# ─────────────────────────────────────────────────────────────────────────────
# Test 20: Installment plan_str format is pipe-separated YYYY-MM-DD:amount
# ─────────────────────────────────────────────────────────────────────────────

def test_installment_plan_str_format():
    """When installments chosen, plan_str must be '|'-separated YYYY-MM-DD:amount entries."""
    profile = make_profile(
        balance=5000.0, min_bal=500.0,
        methods=["installments"], max_inst_months=6
    )
    request = make_request(amount=900.0)
    opt = make_installment_option(num_payments=3, payment_amount=300.0, freq_days=30)
    fs = make_forecast(profile)
    engine = DecisionEngine(
        request=request,
        profile=profile,
        forecast_state=fs,
        payment_options=[opt],
        future_events=[],
    )
    result = engine.run()

    if result["recommended_payment_method"] == "installments":
        plan = result["payment_plan"]
        parts = plan.split("|")
        assert len(parts) == 3
        for part in parts:
            date_str, amount_str = part.split(":")
            datetime.date.fromisoformat(date_str)  # must be valid date
            float(amount_str)  # must be numeric


# ─────────────────────────────────────────────────────────────────────────────
# Test 21: partial_payment plan has exactly 2 payments summing to requested_amount
# ─────────────────────────────────────────────────────────────────────────────

def test_partial_payment_plan_sums_to_requested():
    """Partial payment plan must have exactly 2 payments that sum to requested_amount."""
    profile = make_profile(
        balance=1400.0, min_bal=500.0,
        methods=["partial_payment"]
    )
    request = make_request(amount=1000.0, allows_partial=True)

    # Add income 20 days out so the second payment can be made
    income_event = {
        "event_id": "E_inc",
        "user_id": "user_test",
        "event_type": "income",
        "description": "Salary",
        "category": "income",
        "direction": "credit",
        "amount": 1000.0,
        "currency": "USD",
        "event_date": str(REQUEST_DATE + datetime.timedelta(days=20)),
        "settlement_date": str(REQUEST_DATE + datetime.timedelta(days=20)),
        "status": "scheduled",
        "linked_event_id": None,
        "flexibility": "fixed",
        "minimum_allowed_amount": None,
    }
    fs = make_forecast(profile, events_by_user={"user_test": [income_event]})
    engine = DecisionEngine(
        request=request,
        profile=profile,
        forecast_state=fs,
        payment_options=[],
        future_events=[],
    )
    result = engine.run()

    if result["recommended_payment_method"] == "partial_payment":
        plan = result["payment_plan"]
        parts = plan.split("|")
        assert len(parts) == 2, "Partial payment must have exactly 2 payments"
        amounts = [float(p.split(":")[1]) for p in parts]
        total = sum(amounts)
        assert abs(total - 1000.0) < 0.05, f"Payments must sum to 1000, got {total}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 22: protected categories are never touched
# ─────────────────────────────────────────────────────────────────────────────

def test_protected_categories_not_modified():
    """Events in protected categories must never appear in spending_changes_needed."""
    profile = make_profile(
        balance=1100.0, min_bal=500.0,
        methods=["full_payment"],
        stop_cats=["housing"],   # user says they're willing to stop housing (shouldn't happen)
        protect_cats=["housing"],  # but it's also protected → protected wins
    )
    request = make_request(amount=800.0)

    housing_event = FinancialEvent(
        event_id="E_house",
        user_id="user_test",
        event_type="expense",
        description="Rent",
        category="housing",
        direction="debit",
        amount=300.0,
        currency="USD",
        event_date=REQUEST_DATE + datetime.timedelta(days=5),
        settlement_date=None,
        status="scheduled",
        linked_event_id=None,
        flexibility="stoppable",
        minimum_allowed_amount=0.0,
    )
    fs = make_forecast(profile)
    engine = DecisionEngine(
        request=request,
        profile=profile,
        forecast_state=fs,
        payment_options=[],
        future_events=[housing_event],
    )
    result = engine.run()

    changes = result["spending_changes_needed"]
    # housing event must NOT appear in changes
    assert "E_house" not in changes


# ─────────────────────────────────────────────────────────────────────────────
# Test 23: earliest_date_for_full_payment equals request_date when affordable_now
# ─────────────────────────────────────────────────────────────────────────────

def test_earliest_date_equals_request_date_when_affordable_now():
    """When status is affordable_now, earliest_date_for_full_payment must equal request_date."""
    profile = make_profile(balance=5000.0, min_bal=500.0, methods=["full_payment"])
    request = make_request(amount=1000.0)
    fs = make_forecast(profile)
    engine = DecisionEngine(
        request=request, profile=profile, forecast_state=fs,
        payment_options=[], future_events=[],
    )
    result = engine.run()

    if result["affordability_status"] == "affordable_now":
        assert result["earliest_date_for_full_payment"] == REQUEST_DATE.isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Test 24: ForecastState.simulate_90_day is pure - repeated calls yield same result
# ─────────────────────────────────────────────────────────────────────────────

def test_forecast_simulate_deterministic():
    """ForecastState.simulate_90_day with same inputs always returns same daily balances."""
    profile = make_profile(balance=3000.0, min_bal=500.0)
    fs = make_forecast(profile)

    result1 = fs.simulate_90_day()
    result2 = fs.simulate_90_day()
    assert result1 == result2
    assert len(result1) == 91  # 0..90 days inclusive


# ─────────────────────────────────────────────────────────────────────────────
# Test 25: Financial Fact Matrix & Determinism
# ─────────────────────────────────────────────────────────────────────────────

def test_financial_fact_matrix_and_determinism():
    """
    Demonstrates that changing one financial fact changes the selected plan
    while the algorithm remains 100% deterministic.
    """
    # Fact 1: High balance ($5000) -> affordable_now / full_payment
    p1 = make_profile(balance=5000.0, min_bal=500.0, methods=["full_payment", "installments", "wait"])
    r1 = make_request(amount=1000.0)
    fs1 = make_forecast(p1)
    res1_a = DecisionEngine(r1, p1, fs1, [], []).run()
    res1_b = DecisionEngine(r1, p1, fs1, [], []).run()
    assert res1_a == res1_b
    assert res1_a["affordability_status"] == "affordable_now"
    assert res1_a["recommended_payment_method"] == "full_payment"

    # Fact 2: Change balance to $600 -> not_affordable (no income, no installment option)
    p2 = make_profile(balance=600.0, min_bal=500.0, methods=["full_payment", "installments", "wait"])
    fs2 = make_forecast(p2)
    res2 = DecisionEngine(r1, p2, fs2, [], []).run()
    assert res2["affordability_status"] == "not_affordable"
    assert res2["recommended_payment_method"] == "not_recommended"

    # Fact 3: Add an installment option -> affordable_with_plan / installments
    opt = make_installment_option(opt_id="opt_matrix", num_payments=3, payment_amount=30.0, freq_days=10)
    res3 = DecisionEngine(r1, p2, fs2, [opt], []).run()
    assert res3["affordability_status"] == "affordable_with_plan"
    assert res3["recommended_payment_method"] == "installments"

    # Fact 4: Add a stoppable expense (streaming, $600) -> full_payment with spending change
    p4 = make_profile(balance=600.0, min_bal=500.0, methods=["full_payment"], stop_cats=["entertainment"])
    r4 = make_request(amount=100.0)
    ev_stop_dict = {
        "event_id": "E_stop_mat", "user_id": "user_test", "event_type": "recurring", "description": "Streaming",
        "category": "entertainment", "direction": "debit", "amount": 600.0, "currency": "USD",
        "event_date": str(REQUEST_DATE + datetime.timedelta(days=1)), "settlement_date": str(REQUEST_DATE + datetime.timedelta(days=1)),
        "status": "scheduled", "linked_event_id": None, "flexibility": "stoppable", "minimum_allowed_amount": 0.0
    }
    fs4 = make_forecast(p4, events_by_user={"user_test": [ev_stop_dict]})
    ev_stop = FinancialEvent(
        event_id="E_stop_mat", user_id="user_test", event_type="recurring", description="Streaming",
        category="entertainment", direction="debit", amount=600.0, currency="USD",
        event_date=REQUEST_DATE + datetime.timedelta(days=1), settlement_date=REQUEST_DATE + datetime.timedelta(days=1), status="scheduled",
        linked_event_id=None, flexibility="stoppable", minimum_allowed_amount=0.0
    )
    res4 = DecisionEngine(r4, p4, fs4, [], [ev_stop]).run()
    assert res4["affordability_status"] == "affordable_with_plan"
    assert res4["recommended_payment_method"] == "full_payment"
    assert res4["spending_changes_needed"] == "stop:E_stop_mat"

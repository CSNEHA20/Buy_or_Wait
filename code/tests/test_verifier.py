"""
test_verifier.py - Adversarial tests for verifier.py hard financial constraints.
"""

from datetime import date, timedelta
from decimal import Decimal
import pytest

from buy_or_wait.verifier import (
    VerificationResult,
    verify_decision,
    verify_output_rows,
)
from buy_or_wait.forecast import ForecastState


class DummyRequest:
    def __init__(
        self,
        request_id="req_001",
        requested_amount=100.0,
        request_date="2026-09-01",
        desired_completion_date="2026-09-30",
        user_id="user_001",
    ):
        self.request_id = request_id
        self.requested_amount = requested_amount
        self.request_date = (
            date.fromisoformat(request_date)
            if isinstance(request_date, str)
            else request_date
        )
        self.desired_completion_date = (
            date.fromisoformat(desired_completion_date)
            if isinstance(desired_completion_date, str)
            else desired_completion_date
        )
        self.user_id = user_id


class DummyProfile:
    def __init__(
        self,
        user_id="user_001",
        minimum_balance_to_keep=500.0,
        protected_categories=None,
        adjustable_categories=None,
        max_installment_months=6,
    ):
        self.user_id = user_id
        self.minimum_balance_to_keep = Decimal(str(minimum_balance_to_keep))
        self.minimum_balance = Decimal(str(minimum_balance_to_keep))
        self.protected_categories = protected_categories or ["housing", "utilities"]
        self.adjustable_categories = adjustable_categories or ["dining", "entertainment"]
        self.max_installment_months = max_installment_months


class DummyEvent:
    def __init__(
        self,
        event_id="ev_001",
        user_id="user_001",
        category="entertainment",
        event_date="2026-09-15",
        amount=50.0,
        is_recurring=True,
        flexibility="flexible",
        minimum_allowed_amount=10.0,
    ):
        self.event_id = event_id
        self.user_id = user_id
        self.category = category
        self.event_date = (
            date.fromisoformat(event_date)
            if isinstance(event_date, str)
            else event_date
        )
        self.amount = amount
        self.is_recurring = is_recurring
        self.flexibility = flexibility
        self.minimum_allowed_amount = minimum_allowed_amount


class DummyPaymentOption:
    def __init__(
        self,
        request_id="req_001",
        payment_option_id="opt_01",
        payment_method="installments",
        number_of_payments=3,
        payment_frequency_days=30,
        first_payment_date="2026-09-01",
        payment_amount=35.0,
        total_payable_amount=105.0,
    ):
        self.request_id = request_id
        self.payment_option_id = payment_option_id
        self.payment_method = payment_method
        self.number_of_payments = number_of_payments
        self.payment_frequency_days = payment_frequency_days
        self.first_payment_date = (
            date.fromisoformat(first_payment_date)
            if isinstance(first_payment_date, str)
            else first_payment_date
        )
        self.payment_amount = payment_amount
        self.total_payable_amount = total_payable_amount


def test_known_valid_decision():
    req = DummyRequest()
    prof = DummyProfile()
    decision = {
        "request_id": "req_001",
        "amount_safe_to_pay": 100.0,
        "affordability_status": "affordable_now",
        "recommended_payment_method": "full_payment",
        "payment_plan": "2026-09-01:100",
        "earliest_date_for_full_payment": "2026-09-01",
        "spending_changes_needed": "none",
        "decision_explanation": "Full payment safe on request date.",
    }
    res = verify_decision(decision, request=req, profile=prof)
    assert bool(res) is True, f"Valid decision failed with errors: {res.errors}"
    assert len(res.errors) == 0


def test_negative_safe_amount():
    req = DummyRequest()
    decision = {
        "request_id": "req_001",
        "amount_safe_to_pay": -10.0,
        "affordability_status": "affordable_now",
        "recommended_payment_method": "full_payment",
        "payment_plan": "2026-09-01:100",
        "earliest_date_for_full_payment": "2026-09-01",
        "spending_changes_needed": "none",
        "decision_explanation": "Test negative amount.",
    }
    res = verify_decision(decision, request=req)
    assert bool(res) is False
    assert any("cannot be negative" in e for e in res.errors)


def test_amount_above_requested():
    req = DummyRequest(requested_amount=100.0)
    decision = {
        "request_id": "req_001",
        "amount_safe_to_pay": 150.0,
        "affordability_status": "affordable_now",
        "recommended_payment_method": "full_payment",
        "payment_plan": "2026-09-01:100",
        "earliest_date_for_full_payment": "2026-09-01",
        "spending_changes_needed": "none",
        "decision_explanation": "Test amount above requested.",
    }
    res = verify_decision(decision, request=req)
    assert bool(res) is False
    assert any("cannot exceed requested_amount" in e for e in res.errors)


def test_wrong_date_for_affordable_now():
    req = DummyRequest(request_date="2026-09-01")
    decision = {
        "request_id": "req_001",
        "amount_safe_to_pay": 100.0,
        "affordability_status": "affordable_now",
        "recommended_payment_method": "full_payment",
        "payment_plan": "2026-09-01:100",
        "earliest_date_for_full_payment": "2026-09-10",
        "spending_changes_needed": "none",
        "decision_explanation": "Wrong earliest date for affordable_now.",
    }
    res = verify_decision(decision, request=req)
    assert bool(res) is False
    assert any("affordable_now status requires earliest_date_for_full_payment" in e for e in res.errors)


def test_fake_installment_option():
    req = DummyRequest()
    prof = DummyProfile()
    opts = [DummyPaymentOption(payment_option_id="opt_real", number_of_payments=3, payment_amount=35.0)]
    decision = {
        "request_id": "req_001",
        "amount_safe_to_pay": 35.0,
        "affordability_status": "affordable_with_plan",
        "recommended_payment_method": "installments",
        "payment_plan": "2026-09-01:50|2026-10-01:50",
        "earliest_date_for_full_payment": "2026-10-01",
        "spending_changes_needed": "none",
        "decision_explanation": "Fake installment option.",
    }
    res = verify_decision(decision, request=req, profile=prof, payment_options=opts)
    assert bool(res) is False
    assert any("does not match any valid payment option" in e for e in res.errors)


def test_protected_event_modification():
    req = DummyRequest()
    prof = DummyProfile(protected_categories=["housing"])
    ev_housing = DummyEvent(event_id="ev_rent", category="housing", flexibility="stoppable")
    decision = {
        "request_id": "req_001",
        "amount_safe_to_pay": 100.0,
        "affordability_status": "affordable_with_plan",
        "recommended_payment_method": "full_payment",
        "payment_plan": "2026-09-01:100",
        "earliest_date_for_full_payment": "2026-09-01",
        "spending_changes_needed": "stop:ev_rent",
        "decision_explanation": "Modify protected event.",
    }
    res = verify_decision(decision, request=req, profile=prof, future_events=[ev_housing])
    assert bool(res) is False
    assert any("protected category" in e for e in res.errors)


def test_too_many_spending_changes():
    req = DummyRequest()
    decision = {
        "request_id": "req_001",
        "amount_safe_to_pay": 100.0,
        "affordability_status": "affordable_with_plan",
        "recommended_payment_method": "full_payment",
        "payment_plan": "2026-09-01:100",
        "earliest_date_for_full_payment": "2026-09-01",
        "spending_changes_needed": "stop:e1,stop:e2,stop:e3,stop:e4",
        "decision_explanation": "4 spending changes.",
    }
    res = verify_decision(decision, request=req)
    assert bool(res) is False
    assert any("max 3 allowed" in e for e in res.errors)


def test_malformed_payment_plan():
    req = DummyRequest()
    decision = {
        "request_id": "req_001",
        "amount_safe_to_pay": 100.0,
        "affordability_status": "affordable_now",
        "recommended_payment_method": "full_payment",
        "payment_plan": "bad_plan_string",
        "earliest_date_for_full_payment": "2026-09-01",
        "spending_changes_needed": "none",
        "decision_explanation": "Malformed plan.",
    }
    res = verify_decision(decision, request=req)
    assert bool(res) is False
    assert any("Malformed payment_plan" in e for e in res.errors)


def test_unsorted_payment_plan():
    req = DummyRequest(requested_amount=100.0)
    decision = {
        "request_id": "req_001",
        "amount_safe_to_pay": 50.0,
        "affordability_status": "affordable_with_plan",
        "recommended_payment_method": "partial_payment",
        "payment_plan": "2026-09-15:50|2026-09-01:50",
        "earliest_date_for_full_payment": "2026-09-01",
        "spending_changes_needed": "none",
        "decision_explanation": "Unsorted dates.",
    }
    res = verify_decision(decision, request=req)
    assert bool(res) is False
    assert any("dates are not chronological" in e for e in res.errors)


def test_unsafe_forecast():
    req = DummyRequest(requested_amount=1000.0, request_date="2026-09-01")
    prof = DummyProfile(minimum_balance_to_keep=500.0)
    fs = ForecastState(
        home_currency="USD",
        minimum_balance=Decimal("500.0"),
        fx_rates={},
        start_date=date(2026, 9, 1),
        events_by_user={"user_001": []},
        profile={"current_available_balance": 600.0, "user_id": "user_001"},
    )
    # Payment of 300 will drop balance from 600 to 300 (< minimum 500)
    decision = {
        "request_id": "req_001",
        "amount_safe_to_pay": 300.0,
        "affordability_status": "affordable_with_plan",
        "recommended_payment_method": "full_payment",
        "payment_plan": "2026-09-01:1000",
        "earliest_date_for_full_payment": "2026-09-01",
        "spending_changes_needed": "none",
        "decision_explanation": "Unsafe forecast test.",
    }
    res = verify_decision(decision, request=req, profile=prof, forecast_state=fs)
    assert bool(res) is False
    assert any("breaches minimum_balance_to_keep" in e for e in res.errors)


def test_completion_after_desired_date():
    req = DummyRequest(request_date="2026-09-01", desired_completion_date="2026-09-10", requested_amount=100.0)
    decision = {
        "request_id": "req_001",
        "amount_safe_to_pay": 0.0,
        "affordability_status": "affordable_later",
        "recommended_payment_method": "wait",
        "payment_plan": "2026-09-20:100",
        "earliest_date_for_full_payment": "2026-09-20",
        "spending_changes_needed": "none",
        "decision_explanation": "Completion date after deadline.",
    }
    res = verify_decision(decision, request=req)
    assert bool(res) is False
    assert any("exceeds desired_completion_date" in e for e in res.errors)


def test_invalid_status():
    req = DummyRequest()
    decision = {
        "request_id": "req_001",
        "amount_safe_to_pay": 100.0,
        "affordability_status": "completely_affordable",
        "recommended_payment_method": "full_payment",
        "payment_plan": "2026-09-01:100",
        "earliest_date_for_full_payment": "2026-09-01",
        "spending_changes_needed": "none",
        "decision_explanation": "Invalid status.",
    }
    res = verify_decision(decision, request=req)
    assert bool(res) is False
    assert any("Invalid affordability_status" in e for e in res.errors)


def test_invalid_method():
    req = DummyRequest()
    decision = {
        "request_id": "req_001",
        "amount_safe_to_pay": 100.0,
        "affordability_status": "affordable_now",
        "recommended_payment_method": "crypto_transfer",
        "payment_plan": "2026-09-01:100",
        "earliest_date_for_full_payment": "2026-09-01",
        "spending_changes_needed": "none",
        "decision_explanation": "Invalid method.",
    }
    res = verify_decision(decision, request=req)
    assert bool(res) is False
    assert any("Invalid recommended_payment_method" in e for e in res.errors)


def test_invalid_partial_plan():
    req = DummyRequest(requested_amount=100.0, request_date="2026-09-01", desired_completion_date="2026-09-30")
    # Partial payment must have exactly 2 payments
    decision = {
        "request_id": "req_001",
        "amount_safe_to_pay": 30.0,
        "affordability_status": "affordable_with_plan",
        "recommended_payment_method": "partial_payment",
        "payment_plan": "2026-09-01:30|2026-09-10:30|2026-09-20:40",
        "earliest_date_for_full_payment": "2026-09-20",
        "spending_changes_needed": "none",
        "decision_explanation": "3 payments in partial plan.",
    }
    res = verify_decision(decision, request=req)
    assert bool(res) is False
    assert any("must have exactly two payments" in e for e in res.errors)


def test_missing_required_field():
    decision = {
        "request_id": "req_001",
        "amount_safe_to_pay": 100.0,
        "affordability_status": "affordable_now",
        # missing recommended_payment_method
        "payment_plan": "2026-09-01:100",
        "earliest_date_for_full_payment": "2026-09-01",
        "spending_changes_needed": "none",
        "decision_explanation": "Missing field.",
    }
    res = verify_decision(decision)
    assert bool(res) is False
    assert any("Missing required output field" in e for e in res.errors)


def test_duplicate_spending_target():
    req = DummyRequest()
    decision = {
        "request_id": "req_001",
        "amount_safe_to_pay": 100.0,
        "affordability_status": "affordable_with_plan",
        "recommended_payment_method": "full_payment",
        "payment_plan": "2026-09-01:100",
        "earliest_date_for_full_payment": "2026-09-01",
        "spending_changes_needed": "stop:ev_01,reduce_to:ev_01:10",
        "decision_explanation": "Duplicate target event.",
    }
    res = verify_decision(decision, request=req)
    assert bool(res) is False
    assert any("Duplicate spending change target" in e for e in res.errors)


def test_not_affordable_must_have_none_plan():
    req = DummyRequest()
    decision = {
        "request_id": "req_001",
        "amount_safe_to_pay": 0.0,
        "affordability_status": "not_affordable",
        "recommended_payment_method": "not_recommended",
        "payment_plan": "2026-09-01:100",
        "earliest_date_for_full_payment": "",
        "spending_changes_needed": "none",
        "decision_explanation": "Not affordable with non-none plan.",
    }
    res = verify_decision(decision, request=req)
    assert bool(res) is False
    assert any("payment_plan must be 'none'" in e for e in res.errors)

import pytest
from datetime import date, timedelta
from decimal import Decimal
from buy_or_wait.forecast import ForecastState

def build_profile(balance, min_balance):
    return {
        "current_available_balance": balance,
        "minimum_balance_to_keep": min_balance
    }

def test_stable_balance():
    # 1. stable balance
    profile = build_profile(1000, 100)
    fs = ForecastState("ZAR", Decimal("100"), {}, date(2024, 1, 1), {}, profile)
    balances = fs.simulate_90_day()
    assert balances[date(2024, 1, 1)] == Decimal("1000")
    assert balances[date(2024, 3, 30)] == Decimal("1000")

def test_expense_causes_floor_breach():
    # 2. expense causes floor breach
    profile = build_profile(1000, 100)
    events = {
        "u1": [
            {"status": "settled", "event_type": "expense", "direction": "debit", "amount": 1000, "currency": "ZAR", "event_date": "2024-01-05"}
        ]
    }
    fs = ForecastState("ZAR", Decimal("100"), {}, date(2024, 1, 1), events, profile)
    balances = fs.simulate_90_day()
    assert balances[date(2024, 1, 5)] == Decimal("0") # Breaches 100

def test_salary_restores_safety():
    # 3. salary restores safety
    profile = build_profile(150, 100)
    events = {
        "u1": [
            {"status": "settled", "event_type": "income", "direction": "credit", "amount": 1000, "currency": "ZAR", "event_date": "2024-01-02", "settlement_date": "2024-01-02"}
        ]
    }
    fs = ForecastState("ZAR", Decimal("100"), {}, date(2024, 1, 1), events, profile)
    balances = fs.simulate_90_day()
    assert balances[date(2024, 1, 1)] == Decimal("150")
    assert balances[date(2024, 1, 2)] == Decimal("1150")

def test_amount_safe_to_pay():
    # 14. binary-search amount_safe_to_pay
    profile = build_profile(1000, 100)
    fs = ForecastState("ZAR", Decimal("100"), {}, date(2024, 1, 1), {}, profile)
    # We want to pay 2000, but only 900 is safe
    safe, amt = fs.compute_amount_safe_to_pay(Decimal("2000"))
    assert not safe
    assert amt == Decimal("900")
    
    # We want to pay 500, it should be fully safe
    safe, amt = fs.compute_amount_safe_to_pay(Decimal("500"))
    assert safe
    assert amt == Decimal("500")

def test_earliest_date_for_full_payment():
    # 12. later payment safe
    profile = build_profile(500, 100)
    events = {
        "u1": [
            {"status": "settled", "event_type": "income", "direction": "credit", "amount": 1000, "currency": "ZAR", "event_date": "2024-01-10", "settlement_date": "2024-01-10"}
        ]
    }
    fs = ForecastState("ZAR", Decimal("100"), {}, date(2024, 1, 1), events, profile)
    # Want to pay 1000. Currently 500-1000 = -500. On 10th, gets 1000, so balance = 1500.
    # 1500 - 1000 = 500 >= 100. Safe to pay on the 10th.
    d, safe = fs.compute_earliest_date_for_full_payment(Decimal("1000"), date(2024, 1, 20))
    assert safe
    assert d == date(2024, 1, 10)

def test_never_safe_full_payment():
    # 13. never-safe full payment
    profile = build_profile(500, 100)
    fs = ForecastState("ZAR", Decimal("100"), {}, date(2024, 1, 1), {}, profile)
    d, safe = fs.compute_earliest_date_for_full_payment(Decimal("1000"), date(2024, 1, 20))
    assert not safe

def test_repeated_execution_produces_identical_results():
    # 22. repeated execution produces identical results
    profile = build_profile(1000, 100)
    fs1 = ForecastState("ZAR", Decimal("100"), {}, date(2024, 1, 1), {}, profile)
    b1 = fs1.simulate_90_day()
    fs2 = ForecastState("ZAR", Decimal("100"), {}, date(2024, 1, 1), {}, profile)
    b2 = fs2.simulate_90_day()
    assert b1 == b2

def test_boundary_exact_minimum():
    # 15. exact boundary where balance == minimum_balance_to_keep
    profile = build_profile(600, 100)
    fs = ForecastState("ZAR", Decimal("100"), {}, date(2024, 1, 1), {}, profile)
    safe, amt = fs.compute_amount_safe_to_pay(Decimal("500"))
    assert safe
    assert amt == Decimal("500")

def test_boundary_below_minimum():
    # 16. boundary where balance is one unit below minimum
    profile = build_profile(599.99, 100)
    fs = ForecastState("ZAR", Decimal("100"), {}, date(2024, 1, 1), {}, profile)
    safe, amt = fs.compute_amount_safe_to_pay(Decimal("500"))
    assert not safe
    assert amt == Decimal("499.99")

def test_overlay_does_not_mutate():
    # 17. overlay does not mutate base timeline
    profile = build_profile(1000, 100)
    fs = ForecastState("ZAR", Decimal("100"), {}, date(2024, 1, 1), {}, profile)
    fs.simulate_90_day()
    b1 = fs._get_daily_balances_no_overlay()
    
    overlay = {"u1": {date(2024, 1, 5): Decimal("-500")}}
    fs.simulate_90_day(overlay)
    
    b2 = fs._get_daily_balances_no_overlay()
    assert b1 == b2

def test_90_day_boundary():
    # 20. 90-day boundary
    profile = build_profile(1000, 100)
    fs = ForecastState("ZAR", Decimal("100"), {}, date(2024, 1, 1), {}, profile)
    b = fs.simulate_90_day()
    assert len(b) == 91
    assert date(2024, 1, 1) + timedelta(days=90) in b
    assert date(2024, 1, 1) + timedelta(days=91) not in b

def test_desired_completion_date_violation():
    # 21. desired completion date violation
    profile = build_profile(500, 100)
    events = {
        "u1": [
            {"status": "settled", "event_type": "income", "direction": "credit", "amount": 1000, "currency": "ZAR", "event_date": "2024-01-25", "settlement_date": "2024-01-25"}
        ]
    }
    fs = ForecastState("ZAR", Decimal("100"), {}, date(2024, 1, 1), events, profile)
    # Income arrives on 25th, but desired completion is 20th.
    d, safe = fs.compute_earliest_date_for_full_payment(Decimal("1000"), date(2024, 1, 20))
    assert not safe

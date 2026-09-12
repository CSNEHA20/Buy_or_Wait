import datetime
from decimal import Decimal
from code.data_loader import Dataset, FinancialProfile, FinancialEvent, ExchangeRate
from code.state_builder import StateBuilder

def run_tests():
    profile = FinancialProfile(
        user_id="U1",
        home_currency="USD",
        current_available_balance=1000.0,
        minimum_balance_to_keep=200.0,
        financial_priorities=["saving"],
        expense_categories_to_protect=["housing"],
        expense_categories_user_is_willing_to_reduce=["entertainment"],
        expense_categories_user_is_willing_to_stop=["dining"],
        payment_methods_user_will_consider=["full_payment"],
        max_installment_months=None
    )
    
    event1 = FinancialEvent(
        event_id="E1",
        user_id="U1",
        event_type="one_off",
        description="Pending debit",
        category="utility",
        direction="outflow",
        amount=150.0,
        currency="USD",
        event_date=datetime.date(2026, 9, 1),
        settlement_date=None,
        status="pending",
        linked_event_id=None,
        flexibility="fixed",
        minimum_allowed_amount=150.0
    )
    
    fx_rate = ExchangeRate(
        rate_date=datetime.date(2026, 9, 1),
        from_currency="EUR",
        to_currency="USD",
        rate=1.1
    )

    dataset = Dataset(
        dataset_dir=None,
        profiles={"U1": profile},
        events={"E1": event1},
        events_list=[event1],
        exchange_rates=[fx_rate],
        requests={},
        requests_list=[],
        sample_requests={},
        sample_requests_list=[],
        payment_options=[],
        messages=[],
        images=[]
    )
    
    builder = StateBuilder(dataset)
    state = builder.build_state("U1")
    
    assert state.home_currency == "USD"
    assert state.current_balance == 1000.0
    assert state.minimum_balance == 200.0
    assert state.pending_debits == 150.0
    assert state.safe_available_balance == 650.0
    print("Tests passed successfully.")

if __name__ == "__main__":
    run_tests()

import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from decimal import Decimal

from buy_or_wait.data_loader import Dataset, FinancialEvent, FinancialProfile, PurchaseRequest
from buy_or_wait.fx import FXConverter

@dataclass
class UserState:
    user_id: str
    home_currency: str
    current_balance: float
    minimum_balance: float
    events: List[FinancialEvent]
    
    # Processed states
    pending_debits: float = 0.0
    settled_income: float = 0.0
    confirmed_salary: float = 0.0
    recurring_expenses: List[FinancialEvent] = field(default_factory=list)
    one_off_expenses: List[FinancialEvent] = field(default_factory=list)
    protected_categories: set = field(default_factory=set)
    flexible_categories: set = field(default_factory=set)
    
    @property
    def safe_available_balance(self) -> float:
        """Calculate safe available balance based on rules"""
        return max(0.0, self.current_balance - self.pending_debits - self.minimum_balance)


class StateBuilder:
    """Builds a deterministic view of the user's financial state."""
    
    def __init__(self, dataset: Dataset, fx_converter: Optional[FXConverter] = None):
        self.dataset = dataset
        self.fx = fx_converter if fx_converter else FXConverter(dataset.exchange_rates)
        
    def build_state(self, user_id: str, request_date: Optional[datetime.date] = None) -> UserState:
        profile = self.dataset.profiles.get(user_id)
        if not profile:
            raise ValueError(f"User profile not found: {user_id}")
            
        home_currency = profile.home_currency
        
        # Collect relevant events
        all_user_events = [e for e in self.dataset.events_list if e.user_id == user_id]
        
        # Filter and process events based on rules
        valid_events = []
        pending_debits = 0.0
        
        for e in all_user_events:
            if e.status in ("cancelled", "failed"):
                continue
            if e.category == "investment" and e.status == "unrealized":
                continue
                
            # Normalize amount to home currency
            if e.amount is not None:
                # Use request_date as rate_date if possible, else event_date
                r_date = request_date if request_date else e.event_date
                try:
                    norm_amount = self.fx.convert(
                        amount=e.amount,
                        from_currency=e.currency,
                        to_currency=home_currency,
                        rate_date=r_date,
                        allow_fallback_date=True
                    )
                except Exception:
                    norm_amount = e.amount # fallback if conversion fails
            else:
                norm_amount = 0.0
                
            # Apply rules
            if e.direction == "outflow" and e.status == "pending":
                pending_debits += (norm_amount or 0.0)
            elif e.direction == "inflow" and e.status == "pending":
                # Do not count pending credits
                pass
                
            # Need a normalized copy
            new_e = FinancialEvent(
                event_id=e.event_id,
                user_id=e.user_id,
                event_type=e.event_type,
                description=e.description,
                category=e.category,
                direction=e.direction,
                amount=norm_amount,
                currency=home_currency,
                event_date=e.event_date,
                settlement_date=e.settlement_date,
                status=e.status,
                linked_event_id=e.linked_event_id,
                flexibility=e.flexibility,
                minimum_allowed_amount=e.minimum_allowed_amount
            )
            valid_events.append(new_e)

        state = UserState(
            user_id=user_id,
            home_currency=home_currency,
            current_balance=profile.current_available_balance,
            minimum_balance=profile.minimum_balance_to_keep,
            events=valid_events,
            pending_debits=pending_debits,
            protected_categories=set(profile.expense_categories_to_protect),
            flexible_categories=set(profile.expense_categories_user_is_willing_to_reduce) | set(profile.expense_categories_user_is_willing_to_stop)
        )
        
        # Categorize recurring vs one-off
        for e in valid_events:
            if e.event_type == "recurring":
                state.recurring_expenses.append(e)
            else:
                state.one_off_expenses.append(e)
                
        return state

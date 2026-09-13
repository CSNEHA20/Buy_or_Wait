from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

class ForecastState:
    def __init__(
        self,
        home_currency: str,
        minimum_balance: Decimal,
        fx_rates: Dict,
        start_date: date,
        events_by_user: Dict[str, List[Dict]],
        profile: Dict[str, Any],
    ):
        self.home_currency = home_currency
        self.minimum_balance = Decimal(str(minimum_balance))
        self.fx_rates = fx_rates
        self.start_date = start_date
        self.events_by_user = events_by_user
        self.profile = profile

        self.daily_balance: Dict[date, Decimal] = {}
        self.daily_flows: Dict[str, Dict[date, Decimal]] = defaultdict(
            lambda: defaultdict(Decimal)
        )
        self._amendments: List[Dict] = []

        self._build_base_flows()

    def copy(self) -> "ForecastState":
        new = ForecastState(
            self.home_currency,
            self.minimum_balance,
            self.fx_rates,
            self.start_date,
            self.events_by_user,
            self.profile,
        )
        new.daily_balance = self.daily_balance.copy()
        new.daily_flows = {
            uid: flows.copy() for uid, flows in self.daily_flows.items()
        }
        new._amendments = list(self._amendments)
        return new

    def _parse_date(self, s: str) -> date:
        return date.fromisoformat(s)

    def _build_base_flows(self):
        user_ids = set(self.events_by_user.keys())
        pid = self.profile.get("user_id", "")
        if pid and pid not in user_ids:
            user_ids.add(pid)

        for uid in user_ids:
            events = self.events_by_user.get(uid, [])
            recurring_groups: Dict[Tuple[Any, ...], List[Tuple[date, Decimal, str]]] = defaultdict(list)
            for ev in events:
                status = (ev.get("status") or "").strip().lower()
                
                # Exclude unrealized investments
                ev_type = (ev.get("event_type") or "").lower()
                if ev_type == "investment" and status == "unrealized":
                    continue

                # We count settled events
                # We also count pending debits (reserve cash)
                direction = (ev.get("direction") or "").lower()
                if status == "pending":
                    if direction != "debit":
                        continue # ignore pending credits
                elif status not in ("settled", "scheduled"):
                    continue

                # current_available_balance is the balance at start_date, so
                # settled/scheduled history before that date must not be
                # applied a second time. Cash moves on settlement_date when
                # one is supplied; event_date is only the fallback.
                ev_date_str = ev.get("settlement_date") or ev.get("event_date", "")
                if not ev_date_str:
                    continue
                ev_date = self._parse_date(ev_date_str)
                amt = Decimal(str(ev.get("amount", 0) or 0))

                if status in ("settled", "scheduled") and amt > 0:
                    group_key = (
                        ev_type,
                        (ev.get("category") or "").strip().lower(),
                        (ev.get("description") or "").strip().lower(),
                        direction,
                        (ev.get("flexibility") or "").strip().lower(),
                    )
                    recurring_groups[group_key].append((ev_date, amt, ev.get("event_id", "")))

                if ev_date < self.start_date:
                    continue

                # FX ignoring for this minimal build since fx converter isn't fully tested here, 
                # but we'll assume it's already converted or in home currency
                
                signed = amt if direction == "credit" else -amt
                self.daily_flows[uid][ev_date] += signed

            self._project_recurring_flows(uid, recurring_groups)

    def _project_recurring_flows(
        self,
        user_id: str,
        groups: Dict[Tuple[Any, ...], List[Tuple[date, Decimal, str]]],
    ) -> None:
        """Project only strongly supported recurring series through the horizon."""
        horizon = self.start_date + timedelta(days=90)
        for key, observations in groups.items():
            if len(observations) < 3:
                continue
            observations.sort(key=lambda item: item[0])
            gaps = [
                (observations[i][0] - observations[i - 1][0]).days
                for i in range(1, len(observations))
            ]
            median_gap = sorted(gaps)[len(gaps) // 2]
            if median_gap <= 0:
                continue
            # A recurring series has a stable cadence; tolerate calendar-month
            # variation while rejecting unrelated one-off transactions.
            if any(gap < median_gap * 0.75 or gap > median_gap * 1.25 for gap in gaps):
                continue
            amount = sorted(item[1] for item in observations)[len(observations) // 2]
            last_date = observations[-1][0]
            observed_dates = {item[0] for item in observations}
            next_date = last_date + timedelta(days=median_gap)
            while next_date <= horizon:
                if next_date >= self.start_date:
                    if next_date not in observed_dates:
                        direction = key[3]
                        signed = amount if direction == "credit" else -amount
                        self.daily_flows[user_id][next_date] += signed
                next_date += timedelta(days=median_gap)

    def simulate_90_day(self, overlay_flows: Optional[Dict[str, Dict[date, Decimal]]] = None) -> Dict[date, Decimal]:
        daily: Dict[date, Decimal] = {}
        request_date = self.start_date

        init_balance = Decimal("0")
        if "current_available_balance" in self.profile:
            init_balance = Decimal(str(self.profile["current_available_balance"]))
        bal = init_balance

        effective_flows: Dict[str, Dict[date, Decimal]] = defaultdict(
            lambda: defaultdict(Decimal)
        )
        for uid, flows in self.daily_flows.items():
            for d, v in flows.items():
                effective_flows[uid][d] += v
        if overlay_flows:
            for uid, flows in overlay_flows.items():
                for d, v in flows.items():
                    effective_flows[uid][d] += v

        horizon = request_date + timedelta(days=90)
        cur = request_date
        while cur <= horizon:
            for uid in effective_flows:
                bal += effective_flows[uid].get(cur, Decimal("0"))
            daily[cur] = bal
            cur += timedelta(days=1)

        self.daily_balance = daily
        return daily

    def _get_daily_balances_no_overlay(self) -> Dict[date, Decimal]:
        return self.simulate_90_day(None)

    def compute_amount_safe_to_pay(self, requested_amount: Decimal) -> Tuple[bool, Decimal]:
        base_balances = self._get_daily_balances_no_overlay()

        def is_safe(amt: Decimal) -> bool:
            return all((v - amt) >= self.minimum_balance for d, v in base_balances.items())

        if is_safe(requested_amount):
            return True, requested_amount

        # Find the minimum future base balance
        min_future_balance = min(base_balances.values())
        max_safe_amt = min_future_balance - self.minimum_balance
        
        if max_safe_amt <= 0:
            return False, Decimal("0")
            
        max_safe_amt = min(max_safe_amt, requested_amount)
        # Quantize to 2 decimal places carefully, rounding down to be safe
        max_safe_amt = max_safe_amt.quantize(Decimal("0.01"), rounding="ROUND_DOWN")
        
        return False, max_safe_amt

    def compute_earliest_date_for_full_payment(
        self, requested_amount: Decimal, desired_completion_date: date
    ) -> Tuple[Optional[date], bool]:
        base_balances = self._get_daily_balances_no_overlay()
        
        for d in range(91):
            day = self.start_date + timedelta(days=d)
            if day > desired_completion_date:
                break
                
            safe = True
            for future_day, v in base_balances.items():
                if future_day >= day:
                    if v - requested_amount < self.minimum_balance:
                        safe = False
                        break
            if safe:
                return day, True

        return None, False
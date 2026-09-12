"""
fx.py - Deterministic currency normalization using dataset exchange_rates.csv.

Requirements:
1. Pure conversion function and class (FXConverter).
2. Uses ONLY dataset/exchange_rates.csv, no live rates, no LLM calls.
3. Same currency returns original amount with multiplier 1.0.
4. Exact date lookup for (date, from_currency, to_currency).
5. Deterministic date fallback (latest rate date on or before request date, or exact matching).
6. Inverse rate calculation when direct pair is missing (rate = 1 / inverse_rate).
7. Safe Decimal/float financial arithmetic.
8. Explicit error handling (FXConversionError) for missing rates, invalid directions, or non-positive rates.
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from code.data_loader import ExchangeRate, load_dataset


class FXConversionError(ValueError):
    """Custom exception raised when currency conversion cannot be performed cleanly."""
    pass


class FXConverter:
    """
    Deterministic currency converter backed by ExchangeRate table from exchange_rates.csv.
    """

    def __init__(self, exchange_rates: Optional[List[ExchangeRate]] = None):
        """
        Initialize converter with a list of ExchangeRate objects.
        If exchange_rates is None, loads default dataset via load_dataset().
        """
        if exchange_rates is None:
            dataset = load_dataset()
            exchange_rates = dataset.exchange_rates

        self.rates = exchange_rates
        self._build_index()

    def _build_index(self):
        """
        Index exchange rates by:
        1. (rate_date, from_currency, to_currency) -> rate
        2. (from_currency, to_currency) -> list of (rate_date, rate) sorted by rate_date
        """
        self.exact_map: Dict[Tuple[datetime.date, str, str], Decimal] = {}
        self.pair_timeline: Dict[Tuple[str, str], List[Tuple[datetime.date, Decimal]]] = {}

        for r in self.rates:
            from_c = r.from_currency.strip().upper()
            to_c = r.to_currency.strip().upper()
            
            # Validate non-positive rates
            if r.rate <= 0:
                continue

            rate_dec = Decimal(str(r.rate))
            d = r.rate_date

            self.exact_map[(d, from_c, to_c)] = rate_dec

            pair_key = (from_c, to_c)
            if pair_key not in self.pair_timeline:
                self.pair_timeline[pair_key] = []
            self.pair_timeline[pair_key].append((d, rate_dec))

        # Sort timelines by date for deterministic fallback scanning
        for pair_key in self.pair_timeline:
            self.pair_timeline[pair_key].sort(key=lambda x: x[0])

    def get_rate(
        self,
        from_currency: str,
        to_currency: str,
        rate_date: Optional[datetime.date] = None,
        allow_fallback_date: bool = True
    ) -> Decimal:
        """
        Retrieve exchange rate from_currency -> to_currency on or near rate_date.
        Returns rate as Decimal.
        Raises FXConversionError if rate is missing, non-positive, or invalid.
        """
        from_c = from_currency.strip().upper()
        to_c = to_currency.strip().upper()

        # Check for non-empty currencies
        if not from_c or not to_c:
            raise FXConversionError("Source and target currencies must be non-empty strings.")

        # 1. Same currency case
        if from_c == to_c:
            return Decimal("1.0")

        # If rate_date is None, try looking for available rates
        if rate_date is None:
            pair_key = (from_c, to_c)
            if pair_key in self.pair_timeline:
                return self.pair_timeline[pair_key][-1][1]
            inv_key = (to_c, from_c)
            if inv_key in self.pair_timeline:
                inv_rate = self.pair_timeline[inv_key][-1][1]
                if inv_rate <= 0:
                    raise FXConversionError(f"Invalid non-positive inverse rate found for {to_c}->{from_c}")
                return Decimal("1.0") / inv_rate
            raise FXConversionError(f"No exchange rate found for {from_c} -> {to_c}")

        # 2. Direct exact match
        direct_key = (rate_date, from_c, to_c)
        if direct_key in self.exact_map:
            return self.exact_map[direct_key]

        # 3. Inverse exact match
        inv_key = (rate_date, to_c, from_c)
        if inv_key in self.exact_map:
            inv_rate = self.exact_map[inv_key]
            if inv_rate <= 0:
                raise FXConversionError(f"Non-positive exchange rate encountered for inverse pair {to_c}->{from_c}")
            return Decimal("1.0") / inv_rate

        # 4. Fallback date lookup (if allowed)
        if allow_fallback_date:
            pair_key = (from_c, to_c)
            if pair_key in self.pair_timeline:
                timeline = self.pair_timeline[pair_key]
                le_rates = [r for d, r in timeline if d <= rate_date]
                if le_rates:
                    return le_rates[-1]
                return timeline[0][1]

            inv_pair_key = (to_c, from_c)
            if inv_pair_key in self.pair_timeline:
                inv_timeline = self.pair_timeline[inv_pair_key]
                le_rates = [r for d, r in inv_timeline if d <= rate_date]
                if le_rates:
                    inv_rate = le_rates[-1]
                else:
                    inv_rate = inv_timeline[0][1]
                if inv_rate <= 0:
                    raise FXConversionError(f"Non-positive inverse exchange rate encountered for {to_c}->{from_c}")
                return Decimal("1.0") / inv_rate

        raise FXConversionError(
            f"No exchange rate found for currency pair '{from_c}' -> '{to_c}' on or before date '{rate_date}'"
        )

    def convert(
        self,
        amount: Optional[Union[float, int, str, Decimal]],
        from_currency: str,
        to_currency: str,
        rate_date: Optional[datetime.date] = None,
        decimal_places: Optional[int] = None,
        allow_fallback_date: bool = True
    ) -> Optional[Union[float, Decimal]]:
        """
        Convert financial amount from_currency -> to_currency on rate_date.
        If amount is None, returns None.
        Returns converted value as float (or Decimal if decimal_places is provided).
        """
        if amount is None:
            return None

        try:
            amt_dec = Decimal(str(amount))
        except (ValueError, InvalidOperation):
            raise FXConversionError(f"Invalid financial amount: '{amount}'")

        rate = self.get_rate(from_currency, to_currency, rate_date=rate_date, allow_fallback_date=allow_fallback_date)
        converted_dec = amt_dec * rate

        if decimal_places is not None:
            quantizer = Decimal("10") ** (-decimal_places)
            return converted_dec.quantize(quantizer, rounding=ROUND_HALF_UP)

        return float(converted_dec)


# Convenient module-level functions
_DEFAULT_CONVERTER: Optional[FXConverter] = None

def get_default_converter() -> FXConverter:
    global _DEFAULT_CONVERTER
    if _DEFAULT_CONVERTER is None:
        _DEFAULT_CONVERTER = FXConverter()
    return _DEFAULT_CONVERTER


def convert_currency(
    amount: Optional[Union[float, int, str, Decimal]],
    from_currency: str,
    to_currency: str,
    rate_date: Optional[datetime.date] = None,
    rates: Optional[List[ExchangeRate]] = None,
    decimal_places: Optional[int] = None,
    allow_fallback_date: bool = True
) -> Optional[Union[float, Decimal]]:
    """
    Pure conversion function.
    Converts amount from from_currency to to_currency on rate_date using rates.
    """
    if amount is None:
        return None
    if rates is not None:
        converter = FXConverter(exchange_rates=rates)
    else:
        converter = get_default_converter()
    return converter.convert(
        amount=amount,
        from_currency=from_currency,
        to_currency=to_currency,
        rate_date=rate_date,
        decimal_places=decimal_places,
        allow_fallback_date=allow_fallback_date
    )

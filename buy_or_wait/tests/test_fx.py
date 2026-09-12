"""
test_fx.py - Comprehensive test suite for FX currency normalization module.
"""

import datetime
from decimal import Decimal
import pytest

from buy_or_wait.data_loader import ExchangeRate, load_dataset
from buy_or_wait.fx import FXConverter, FXConversionError, convert_currency


@pytest.fixture
def sample_rates():
    """Custom sample exchange rates fixture for testing edge cases."""
    return [
        ExchangeRate(rate_date=datetime.date(2024, 1, 1), from_currency="USD", to_currency="INR", rate=83.0),
        ExchangeRate(rate_date=datetime.date(2024, 2, 1), from_currency="USD", to_currency="INR", rate=83.5),
        ExchangeRate(rate_date=datetime.date(2024, 1, 1), from_currency="EUR", to_currency="USD", rate=1.10),
        ExchangeRate(rate_date=datetime.date(2024, 1, 1), from_currency="EUR", to_currency="ZAR", rate=20.0),
        ExchangeRate(rate_date=datetime.date(2024, 1, 1), from_currency="BAD", to_currency="USD", rate=-1.5),  # Invalid negative rate
        ExchangeRate(rate_date=datetime.date(2024, 1, 1), from_currency="ZERO", to_currency="USD", rate=0.0),  # Invalid zero rate
    ]


@pytest.fixture
def converter(sample_rates):
    return FXConverter(exchange_rates=sample_rates)


def test_same_currency_conversion(converter):
    """Test same currency (e.g. INR -> INR or USD -> USD) returns unchanged amount."""
    assert converter.convert(100.0, "INR", "INR") == 100.0
    assert converter.convert(250.50, "USD", "USD", rate_date=datetime.date(2024, 1, 1)) == 250.50
    rate = converter.get_rate("INR", "INR")
    assert rate == Decimal("1.0")


def test_direct_foreign_to_home_conversion(converter):
    """Test direct conversion foreign -> home currency (e.g. USD -> INR on specific dates)."""
    val1 = converter.convert(100, "USD", "INR", rate_date=datetime.date(2024, 1, 1))
    assert val1 == 8300.0

    val2 = converter.convert(100, "USD", "INR", rate_date=datetime.date(2024, 2, 1))
    assert val2 == 8350.0


def test_home_to_foreign_inverse_conversion(converter):
    """Test inverse currency conversion home -> foreign (e.g. INR -> USD when USD -> INR is in dataset)."""
    rate = converter.get_rate("INR", "USD", rate_date=datetime.date(2024, 1, 1))
    expected_rate = Decimal("1.0") / Decimal("83.0")
    assert rate == expected_rate

    # Convert 8300 INR to USD on 2024-01-01
    val = converter.convert(8300, "INR", "USD", rate_date=datetime.date(2024, 1, 1), decimal_places=2)
    assert val == Decimal("100.00")


def test_missing_exchange_rate(converter):
    """Test converting between unsupported currency pairs or dates without fallback raises FXConversionError."""
    with pytest.raises(FXConversionError) as exc_info:
        converter.get_rate("JPY", "CAD", rate_date=datetime.date(2024, 1, 1))
    assert "No exchange rate found" in str(exc_info.value)

    with pytest.raises(FXConversionError):
        converter.get_rate("USD", "INR", rate_date=datetime.date(2020, 1, 1), allow_fallback_date=False)


def test_invalid_currency_direction(converter):
    """Test invalid or unmapped currency direction raises FXConversionError."""
    with pytest.raises(FXConversionError):
        converter.convert(100, "AUD", "GBP", rate_date=datetime.date(2024, 1, 1))


def test_exact_date_selection(converter):
    """Test rate lookup selects the exact rate matching rate_date when multiple dates exist."""
    rate_jan = converter.get_rate("USD", "INR", rate_date=datetime.date(2024, 1, 1))
    rate_feb = converter.get_rate("USD", "INR", rate_date=datetime.date(2024, 2, 1))
    assert rate_jan == Decimal("83.0")
    assert rate_feb == Decimal("83.5")
    assert rate_jan != rate_feb


def test_multiple_rates_across_dates_fallback(converter):
    """Test deterministic fallback picks latest date on or before request date."""
    # Date between 2024-01-01 and 2024-02-01 (e.g., 2024-01-15) should fall back to 2024-01-01 rate (83.0)
    rate_mid = converter.get_rate("USD", "INR", rate_date=datetime.date(2024, 1, 15))
    assert rate_mid == Decimal("83.0")

    # Date after 2024-02-01 (e.g., 2024-03-01) should fall back to 2024-02-01 rate (83.5)
    rate_late = converter.get_rate("USD", "INR", rate_date=datetime.date(2024, 3, 1))
    assert rate_late == Decimal("83.5")


def test_decimal_precision():
    """Test financial decimal accuracy and rounding with convert_currency."""
    rates = [
        ExchangeRate(rate_date=datetime.date(2024, 1, 1), from_currency="USD", to_currency="EUR", rate=0.923456)
    ]
    res_dec = convert_currency(
        amount="100.00",
        from_currency="USD",
        to_currency="EUR",
        rate_date=datetime.date(2024, 1, 1),
        rates=rates,
        decimal_places=2
    )
    assert res_dec == Decimal("92.35")


def test_zero_or_negative_rate_rejection(converter):
    """Test non-positive exchange rates (0 or negative) are ignored/rejected."""
    with pytest.raises(FXConversionError):
        converter.get_rate("BAD", "USD", rate_date=datetime.date(2024, 1, 1))

    with pytest.raises(FXConversionError):
        converter.get_rate("ZERO", "USD", rate_date=datetime.date(2024, 1, 1))


def test_deterministic_repeated_conversion(converter):
    """Test repeated conversions yield identical deterministic results."""
    res1 = [converter.convert(100 * i, "USD", "INR", rate_date=datetime.date(2024, 1, 1)) for i in range(1, 10)]
    res2 = [converter.convert(100 * i, "USD", "INR", rate_date=datetime.date(2024, 1, 1)) for i in range(1, 10)]
    assert res1 == res2


def test_real_dataset_fx_smoke():
    """Smoke test converting real foreign currency events from the dataset."""
    dataset = load_dataset()
    converter = FXConverter(exchange_rates=dataset.exchange_rates)

    # Pick foreign currency events
    foreign_events = [
        e for e in dataset.events_list
        if e.currency != dataset.profiles[e.user_id].home_currency and e.amount is not None
    ]
    assert len(foreign_events) > 0

    converted_count = 0
    for e in foreign_events[:20]:
        prof = dataset.profiles[e.user_id]
        s_date = e.settlement_date or e.event_date
        converted_amt = converter.convert(e.amount, e.currency, prof.home_currency, rate_date=s_date)
        assert converted_amt is not None
        assert isinstance(converted_amt, float)
        assert converted_amt > 0
        converted_count += 1

    assert converted_count == 20

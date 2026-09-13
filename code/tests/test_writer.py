from pathlib import Path

import pytest

from buy_or_wait import config
from buy_or_wait.writer import OutputValidationError, write_output


def _row(**overrides):
    row = {
        "request_id": "request_test",
        "amount_safe_to_pay": 10,
        "affordability_status": "affordable_now",
        "recommended_payment_method": "full_payment",
        "payment_plan": "2026-01-01:10",
        "earliest_date_for_full_payment": "2026-01-01",
        "spending_changes_needed": "none",
        "decision_explanation": "Balance safely covers the request.",
    }
    row.update(overrides)
    return row


def test_writer_schema_and_row_count(tmp_path):
    output = write_output([_row()], tmp_path / "output.csv", expected_row_count=1)
    assert output.read_text(encoding="utf-8").splitlines()[0] == ",".join(config.OUTPUT_COLUMNS)
    assert len(output.read_text(encoding="utf-8").splitlines()) == 2


def test_writer_rejects_empty_result_and_malformed_decision(tmp_path):
    with pytest.raises(OutputValidationError):
        write_output([], tmp_path / "output.csv", expected_row_count=1)
    with pytest.raises(OutputValidationError):
        write_output([_row(payment_plan="bad")], tmp_path / "output.csv", expected_row_count=1)


def test_writer_rejects_invalid_domains_and_plan_dates(tmp_path):
    with pytest.raises(OutputValidationError):
        write_output([_row(affordability_status="invalid")], tmp_path / "output.csv", expected_row_count=1)
    with pytest.raises(OutputValidationError):
        write_output([_row(payment_plan="2026-02-01:10|2026-01-01:1")], tmp_path / "output.csv", expected_row_count=1)


def test_writer_rejects_duplicate_request_ids(tmp_path):
    with pytest.raises(OutputValidationError, match="unique"):
        write_output(
            [_row(), _row(request_id="request_test")],
            tmp_path / "output.csv",
            expected_row_count=2,
        )

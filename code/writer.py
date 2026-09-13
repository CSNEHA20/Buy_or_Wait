"""Schema-locked, atomic writer for the final prediction CSV."""

from __future__ import annotations

import csv
import math
import os
import re
import tempfile
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import config


class OutputValidationError(ValueError):
    """Raised when a prediction row cannot be safely written."""


_PLAN_ENTRY = re.compile(r"^\d{4}-\d{2}-\d{2}:[0-9]+(?:\.[0-9]+)?$")
_CHANGE = re.compile(r"^(?:stop:[^:|]+|reduce_to:[^:|]+:[0-9]+(?:\.[0-9]+)?)$")


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise OutputValidationError(f"{field} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise OutputValidationError(f"{field} must be numeric")
    if not result.is_finite():
        raise OutputValidationError(f"{field} must be finite")
    return result


def validate_row(row: Mapping[str, Any]) -> None:
    """Validate one output row, including dates and payment-plan syntax."""
    missing = [name for name in config.OUTPUT_COLUMNS if name not in row]
    if missing:
        raise OutputValidationError(f"Missing output columns: {missing}")
    request_id = row["request_id"]
    if not isinstance(request_id, str) or not request_id.strip():
        raise OutputValidationError("request_id must be a non-empty string")

    safe = _decimal(row["amount_safe_to_pay"], "amount_safe_to_pay")
    requested = row.get("requested_amount")
    if requested is not None:
        requested_decimal = _decimal(requested, "requested_amount")
        if safe < 0 or safe > requested_decimal:
            raise OutputValidationError("amount_safe_to_pay is outside requested_amount bounds")
    elif safe < 0:
        raise OutputValidationError("amount_safe_to_pay cannot be negative")

    status = row["affordability_status"]
    method = row["recommended_payment_method"]
    if status not in config.ALLOWED_AFFORDABILITY_STATUS:
        raise OutputValidationError(f"Invalid affordability_status: {status!r}")
    if method not in config.ALLOWED_PAYMENT_METHODS:
        raise OutputValidationError(f"Invalid recommended_payment_method: {method!r}")

    earliest = str(row["earliest_date_for_full_payment"] or "")
    if earliest:
        try:
            date.fromisoformat(earliest)
        except ValueError:
            raise OutputValidationError("earliest_date_for_full_payment must be YYYY-MM-DD")

    plan = str(row["payment_plan"] or "").strip()
    if plan.lower() in {"", "none"}:
        if method != "not_recommended" and status != "not_affordable":
            raise OutputValidationError("recommended plans must have a payment_plan")
    else:
        entries = plan.split("|")
        parsed = []
        for entry in entries:
            if not _PLAN_ENTRY.fullmatch(entry):
                raise OutputValidationError(f"Malformed payment_plan entry: {entry!r}")
            day_text, amount_text = entry.split(":", 1)
            try:
                day = date.fromisoformat(day_text)
            except ValueError:
                raise OutputValidationError(f"Malformed payment date: {day_text!r}")
            amount = _decimal(amount_text, "payment plan amount")
            if amount <= 0:
                raise OutputValidationError("payment plan amounts must be positive")
            parsed.append((day, amount))
        if any(left[0] > right[0] for left, right in zip(parsed, parsed[1:])):
            raise OutputValidationError("payment_plan dates must be chronological")
        if method == "partial_payment":
            if len(parsed) != 2 or parsed[0][1] != safe:
                raise OutputValidationError("partial_payment must start with amount_safe_to_pay")
            if earliest and parsed[1][0].isoformat() != earliest:
                raise OutputValidationError("partial_payment second date must match earliest date")

    changes = str(row["spending_changes_needed"] or "").strip()
    if changes.lower() not in {"", "none"}:
        parts = changes.split("|")
        if len(parts) > 3 or any(not _CHANGE.fullmatch(part) for part in parts):
            raise OutputValidationError("spending_changes_needed contains an invalid change")
        targets = [part.split(":")[1] for part in parts]
        if len(targets) != len(set(targets)):
            raise OutputValidationError("spending changes cannot target the same event twice")

    explanation = row["decision_explanation"]
    if not isinstance(explanation, str) or not explanation.strip():
        raise OutputValidationError("decision_explanation must be non-empty")


def write_output(rows: Iterable[Mapping[str, Any]], output_path: Path, expected_row_count: int) -> Path:
    """Validate all rows, then atomically write an exact-schema CSV."""
    materialized = list(rows)
    if len(config.OUTPUT_COLUMNS) != 8:
        raise OutputValidationError("Output schema must contain exactly eight columns")
    if len(materialized) != expected_row_count:
        raise OutputValidationError(
            f"Expected {expected_row_count} prediction rows, got {len(materialized)}"
        )
    request_ids = [str(row.get("request_id", "")).strip() for row in materialized]
    if len(set(request_ids)) != len(request_ids):
        raise OutputValidationError("request_id values must be unique")
    if any(not request_id for request_id in request_ids):
        raise OutputValidationError("request_id values must be non-empty")
    for row in materialized:
        validate_row(row)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(config.OUTPUT_COLUMNS), extrasaction="ignore")
            if writer.fieldnames != config.OUTPUT_COLUMNS:
                raise OutputValidationError("Output header does not match the contractual schema")
            writer.writeheader()
            for row in materialized:
                writer.writerow({column: row[column] for column in config.OUTPUT_COLUMNS})
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, output_path)
    except Exception:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
        raise
    return output_path


def write_predictions(rows: Iterable[Mapping[str, Any]], output_path: Path, expected_row_count: int) -> Path:
    """Backward-compatible name for callers that prefer a descriptive API."""
    return write_output(rows, output_path, expected_row_count)

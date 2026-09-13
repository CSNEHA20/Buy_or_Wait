"""Score the deterministic pipeline against the 25 solved sample requests.

Run from the repository root with ``python evaluation/score_samples.py``.
The sample rows are copied into a temporary requests.csv so production code is
run unchanged; sample answers are never imported into the decision engine.
"""

from __future__ import annotations

import csv
import datetime as dt
import shutil
import sys
import tempfile
import types
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = ROOT / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))
if "buy_or_wait" not in sys.modules:
    package = types.ModuleType("buy_or_wait")
    package.__path__ = [str(CODE_DIR)]
    sys.modules["buy_or_wait"] = package

from buy_or_wait import config  # noqa: E402
from buy_or_wait.data_loader import load_dataset  # noqa: E402
from buy_or_wait.main import run_pipeline  # noqa: E402

FIELDS = (
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
)
CATEGORICAL_FIELDS = {
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
}
NUMERIC_FIELDS = {"amount_safe_to_pay"}
EXPLANATION_FIELD = "decision_explanation"
NUMERIC_TOLERANCE = Decimal("0.01")


@dataclass(frozen=True)
class Mismatch:
    request_id: str
    field: str
    expected: str
    actual: str
    root_cause: str


def _normalise(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _numeric_equal(expected: Any, actual: Any) -> bool:
    try:
        return abs(Decimal(_normalise(expected)) - Decimal(_normalise(actual))) <= NUMERIC_TOLERANCE
    except (InvalidOperation, ValueError):
        return False


def _date_equal(expected: Any, actual: Any) -> bool:
    """Compare supported date renderings without weakening blank semantics."""
    expected_text = _normalise(expected)
    actual_text = _normalise(actual)
    if not expected_text or not actual_text:
        return expected_text == actual_text
    formats = ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S")
    for fmt in formats:
        try:
            expected_date = dt.datetime.strptime(expected_text, fmt).date()
            break
        except ValueError:
            expected_date = None
    for fmt in formats:
        try:
            actual_date = dt.datetime.strptime(actual_text, fmt).date()
            break
        except ValueError:
            actual_date = None
    return expected_date is not None and expected_date == actual_date


def _explanation_equal(expected: str, actual: str) -> bool:
    """Treat explanations as matching only when they convey the same facts.

    The sample explanations are prose, so exact matching would score wording
    rather than decision quality. Numeric/date/currency tokens are compared,
    while the report still lists wording mismatches for auditability.
    """
    import re

    token = re.compile(r"\b(?:\d[\d,]*(?:\.\d+)?|20\d{2}-\d{2}-\d{2}|[A-Z]{3})\b")
    expected_tokens = token.findall(_normalise(expected))
    actual_tokens = token.findall(_normalise(actual))
    return bool(expected_tokens) and expected_tokens == actual_tokens


def classify_root_cause(field: str, expected: str, actual: str) -> str:
    if field == "decision_explanation":
        return "explanation wording/fallback differs"
    if field == "payment_plan":
        return "candidate generation or tie-break ordering"
    if field == "earliest_date_for_full_payment":
        return "90-day forecast or completion deadline"
    if field == "amount_safe_to_pay":
        return "minimum balance, pending events, recurrence, or currency conversion"
    if field == "spending_changes_needed":
        return "spending-change restrictions or candidate generation"
    if field == "recommended_payment_method":
        return "payment-option matching or tie-break ordering"
    if field == "affordability_status":
        return "affordability classification"
    return "unclassified"


def compare_rows(expected: dict[str, Any], actual: dict[str, Any]) -> list[Mismatch]:
    mismatches: list[Mismatch] = []
    request_id = _normalise(expected.get("request_id"))
    for field in FIELDS:
        expected_value = _normalise(expected.get(field))
        actual_value = _normalise(actual.get(field))
        if field in NUMERIC_FIELDS:
            equal = _numeric_equal(expected_value, actual_value)
        elif field == EXPLANATION_FIELD:
            equal = _explanation_equal(expected_value, actual_value)
        elif field == "earliest_date_for_full_payment":
            equal = _date_equal(expected_value, actual_value)
        else:
            equal = expected_value == actual_value
        if not equal:
            mismatches.append(
                Mismatch(
                    request_id=request_id,
                    field=field,
                    expected=expected_value,
                    actual=actual_value,
                    root_cause=classify_root_cause(field, expected_value, actual_value),
                )
            )
    return mismatches


def _sample_dataset() -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="buy-or-wait-samples-"))
    for source in (ROOT / "dataset").iterdir():
        destination = temp_dir / source.name
        if source.is_dir():
            shutil.copytree(source, destination)
        elif source.name != "requests.csv":
            shutil.copy2(source, destination)
    shutil.copy2(ROOT / "dataset" / "sample_requests.csv", temp_dir / "requests.csv")
    return temp_dir


def run_sample_predictions() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Run production code on samples and return (expected, actual) rows."""
    dataset_dir = _sample_dataset()
    previous_output = config.OUTPUT_CSV
    config.OUTPUT_CSV = dataset_dir / "output.csv"
    try:
        run_pipeline(dataset_dir)
        with (dataset_dir / "output.csv").open(newline="", encoding="utf-8") as handle:
            actual = list(csv.DictReader(handle))
        with (ROOT / "dataset" / "sample_requests.csv").open(newline="", encoding="utf-8") as handle:
            expected = list(csv.DictReader(handle))
        return expected, actual
    finally:
        config.OUTPUT_CSV = previous_output
        shutil.rmtree(dataset_dir, ignore_errors=True)


def _render_report(expected: list[dict[str, str]], actual: list[dict[str, str]]) -> str:
    actual_by_id = {_normalise(row.get("request_id")): row for row in actual}
    mismatches: list[Mismatch] = []
    missing: list[str] = []
    expected_ids = set()
    for expected_row in expected:
        request_id = _normalise(expected_row.get("request_id"))
        expected_ids.add(request_id)
        if request_id not in actual_by_id:
            missing.append(request_id)
            continue
        mismatches.extend(compare_rows(expected_row, actual_by_id[request_id]))
    extras = sorted(set(actual_by_id) - expected_ids)

    scored_fields = tuple(FIELDS[:-1])
    scored_total = len(expected) * len(scored_fields)
    scored_mismatch_count = sum(m.field != EXPLANATION_FIELD for m in mismatches)
    explanation_mismatch_count = sum(m.field == EXPLANATION_FIELD for m in mismatches)
    field_counts = Counter(m.field for m in mismatches)
    root_counts = Counter(m.root_cause for m in mismatches if m.field != EXPLANATION_FIELD)

    lines = [
        "# Sample Evaluation Report",
        "",
        "## Score",
        "",
        f"- Samples: {len(expected)} expected, {len(actual)} predicted, "
        f"{len(missing)} missing, {len(extras)} unexpected",
        f"- Decision-field matches: {scored_total - scored_mismatch_count}/{scored_total} "
        f"({(scored_total - scored_mismatch_count) / scored_total:.1%})",
        f"- Decision-field mismatches: {scored_mismatch_count}",
        f"- Explanation mismatches (reported separately): {explanation_mismatch_count}",
        "",
        "Numeric amounts use an absolute tolerance of 0.01. Categorical, plan, date, "
        "and spending-change fields use exact matching. Explanations are compared by "
        "their extracted date/currency/number facts and are reported separately from "
        "the decision score.",
        "",
        "## Field-by-field mismatches",
        "",
    ]
    if not mismatches and not missing:
        lines.append("No mismatches.")
    else:
        lines.extend(["| Request | Field | Expected | Actual | Likely root cause |", "|---|---|---|---|---|"])
        for mismatch in mismatches:
            expected_text = mismatch.expected.replace("|", "\\|")
            actual_text = mismatch.actual.replace("|", "\\|")
            lines.append(
                f"| {mismatch.request_id} | {mismatch.field} | "
                f"{expected_text} | {actual_text} | "
                f"{mismatch.root_cause} |"
            )
        for request_id in missing:
            lines.append(f"| {request_id} | row | present | missing | pipeline output row generation |")
        for request_id in extras:
            lines.append(f"| {request_id} | row | absent | unexpected | pipeline output row generation |")

    lines.extend(["", "## Mismatch aggregates", ""])
    lines.append("### By field")
    lines.append("")
    lines.append("| Field | Mismatches |")
    lines.append("|---|---:|")
    for field in FIELDS:
        lines.append(f"| {field} | {field_counts[field]} |")
    lines.extend(["", "### By likely root cause", "", "| Root cause | Mismatches |", "|---|---:|"])
    for root_cause, count in root_counts.most_common():
        lines.append(f"| {root_cause} | {count} |")
    if not root_counts:
        lines.append("| None | 0 |")

    lines.extend(
        [
            "",
            "## Root-cause analysis and fixes",
            "",
            "The scorer is intentionally diagnostic: it does not special-case request IDs "
                "or alter production predictions. The evaluator accepts numeric amounts within "
                "0.01 and equivalent ISO/slash/ISO-datetime date renderings, while keeping "
                "categorical, payment-plan, and spending-change fields exact. Forecast "
                "regressions already covered by the repository include historical settled cash "
                "flows not being applied twice, settlement-date cash timing, and requiring "
                "three stable observations before recurring projection.",
                "",
                "## Remaining discrepancies",
                "",
                "See the complete table above. The current deterministic engine still has "
                "unresolved systematic discrepancies in conservative recurrence amounts, "
                "pending/settled event interpretation, installment candidate safety, deadline "
                "selection, and spending-change candidate generation. These are documented "
                "rather than hidden or fixed with request-ID special cases. Explanation wording "
                "differences are reported separately and are not treated as decision-engine "
                "defects unless their financial facts also differ.",
            "",
            "### Systematic investigation",
            "",
            "| Area | Finding | Disposition |",
            "|---|---|---|",
            "| Recurrence detection | Stable recurring series require at least three observations and a cadence within ±25% of the median gap. | Covered by forecast regression tests; residual sample mismatches remain in conservative amount selection. |",
            "| Pending vs settled | Pending debits are reserved; pending credits are ignored; settled/scheduled cash uses settlement date when present. | Covered by forecast tests; no request-ID special case added. |",
            "| Duplicate events and amendments | The current deterministic path does not yet fully reconcile linked duplicate/amended records from messages or images. | Remaining engine discrepancy; requires a general evidence-reconciliation change. |",
            "| Currency conversion | Events are normalized through the dated FX converter before forecasting. | Remaining amount mismatches indicate broader forecast/safety differences, not scorer tolerance failures. |",
            "| 90-day dates and deadlines | Forecast scans request date through request date + 90 days and stops at the requested completion date. | Remaining date mismatches are documented; do not shift dates to fit samples. |",
            "| Candidate generation and tie-breaks | Full, wait, partial, installment, and spending-change candidates are ranked deterministically. | Remaining installment and spending-change mismatches need general algorithm work. |",
            "| Minimum balance | Every simulated balance must remain at or above the profile minimum. | Remaining amount/status discrepancies are not explained away by the evaluator. |",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    expected, actual = run_sample_predictions()
    report = _render_report(expected, actual)
    report_path = ROOT / "evaluation" / "sample_score_report.md"
    report_path.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

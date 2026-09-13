from evaluation.score_samples import compare_rows


def test_sample_comparison_uses_numeric_tolerance_and_exact_categories():
    expected = {
        "request_id": "request_01",
        "amount_safe_to_pay": "100.00",
        "affordability_status": "affordable_now",
        "recommended_payment_method": "full_payment",
        "payment_plan": "2026-01-01:100",
        "earliest_date_for_full_payment": "2026-01-01",
        "spending_changes_needed": "none",
        "decision_explanation": "Pay USD 100 on 2026-01-01.",
    }
    actual = dict(expected, amount_safe_to_pay="100.009")
    assert compare_rows(expected, actual) == []

    actual = dict(expected, affordability_status="affordable_later")
    mismatches = compare_rows(expected, actual)
    assert [(m.field, m.root_cause) for m in mismatches] == [
        ("affordability_status", "affordability classification")
    ]


def test_sample_comparison_reports_plan_and_explanation_mismatches():
    expected = {
        "request_id": "request_02",
        "amount_safe_to_pay": "10",
        "affordability_status": "affordable_now",
        "recommended_payment_method": "full_payment",
        "payment_plan": "2026-01-01:10",
        "earliest_date_for_full_payment": "2026-01-01",
        "spending_changes_needed": "none",
        "decision_explanation": "Pay USD 10 on 2026-01-01.",
    }
    actual = dict(expected, payment_plan="2026-01-02:10", decision_explanation="Different wording.")
    mismatches = compare_rows(expected, actual)
    assert {m.field for m in mismatches} == {"payment_plan", "decision_explanation"}

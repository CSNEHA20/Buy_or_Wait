"""
main.py - Full pipeline entry point for the Buy or Wait? decision agent.

Run:
    .venv/Scripts/python.exe -m buy_or_wait.main
    or
    python -m buy_or_wait.main

Pipeline stages:
  1. Load dataset (data_loader)
  2. Extract evidence from messages and images (evidence_extractor) [optional, LLM]
  3. For each request in requests.csv:
     a. Build ForecastState (forecast.py)
     b. Collect relevant payment options and future events
     c. Run DecisionEngine (decision_engine.py)
     d. Collect result row
  4. Write output.csv
  5. Write evaluation/usage_report.md
"""

from __future__ import annotations

import csv
import json
import logging
import sys
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from buy_or_wait import config
from buy_or_wait.data_loader import (
    Dataset,
    FinancialEvent,
    FinancialProfile,
    PurchaseRequest,
    PaymentOption,
    load_dataset,
)
from buy_or_wait.forecast import ForecastState
from buy_or_wait.decision_engine import DecisionEngine
from buy_or_wait.fx import FXConverter, FXConversionError
from buy_or_wait.llm_client import LLMClient

# Optional LLM-based evidence extractor (gracefully degraded if no API key)
_evidence_available = bool(config.ANTHROPIC_API_KEY)
if _evidence_available:
    try:
        from buy_or_wait.evidence_extractor import (
            extract_all_image_facts,
            extract_all_message_facts,
        )
    except Exception:
        _evidence_available = False

# LLM-based explanation generator (always import, gracefully degraded if no API key)
try:
    from buy_or_wait.explanation_generator import generate_explanation_from_decision
except Exception:
    generate_explanation_from_decision = None
    _explanation_available = False
else:
    _explanation_available = bool(config.ANTHROPIC_API_KEY)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("buy_or_wait.main")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_forecast_state(
    request: PurchaseRequest,
    profile: FinancialProfile,
    dataset: Dataset,
    fx: FXConverter,
) -> ForecastState:
    """Construct a ForecastState for the given request / user."""
    uid = profile.user_id
    home_currency = profile.home_currency

    # Convert all events for this user to dicts, normalizing amounts to home currency
    user_events_raw: List[Dict] = []
    for ev in dataset.events_list:
        if ev.user_id != uid:
            continue
        # Normalize amount to home currency on request_date
        if ev.amount is not None and ev.currency != home_currency:
            try:
                rate_date = request.request_date
                norm_amt = fx.convert(
                    ev.amount, ev.currency, home_currency,
                    rate_date=rate_date, allow_fallback_date=True
                )
                norm_amt = float(norm_amt)
            except FXConversionError:
                norm_amt = ev.amount  # fallback: use raw value
        else:
            norm_amt = ev.amount

        user_events_raw.append({
            "event_id": ev.event_id,
            "user_id": ev.user_id,
            "event_type": ev.event_type,
            "description": ev.description,
            "category": ev.category,
            "direction": ev.direction,
            "amount": norm_amt,
            "currency": home_currency,
            "event_date": ev.event_date.isoformat() if ev.event_date else None,
            "settlement_date": ev.settlement_date.isoformat() if ev.settlement_date else None,
            "status": ev.status,
            "linked_event_id": ev.linked_event_id,
            "flexibility": ev.flexibility,
            "minimum_allowed_amount": ev.minimum_allowed_amount,
        })

    profile_dict = {
        "user_id": uid,
        "current_available_balance": profile.current_available_balance,
    }

    return ForecastState(
        home_currency=home_currency,
        minimum_balance=Decimal(str(profile.minimum_balance_to_keep)),
        fx_rates={},  # FX already applied above
        start_date=request.request_date,
        events_by_user={uid: user_events_raw},
        profile=profile_dict,
    )


def _get_future_events(
    request: PurchaseRequest,
    dataset: Dataset,
    fx: FXConverter,
    profile: FinancialProfile,
) -> List[FinancialEvent]:
    """Return events after request_date that belong to this user, with FX-normalized amounts."""
    uid = profile.user_id
    home_currency = profile.home_currency
    result = []
    for ev in dataset.events_list:
        if ev.user_id != uid:
            continue
        if ev.event_date is None:
            continue
        if ev.event_date <= request.request_date:
            continue
        if ev.status in ("cancelled", "failed"):
            continue

        # Normalize amount
        if ev.amount is not None and ev.currency != home_currency:
            try:
                norm_amt = float(fx.convert(
                    ev.amount, ev.currency, home_currency,
                    rate_date=request.request_date, allow_fallback_date=True
                ))
            except FXConversionError:
                norm_amt = ev.amount
        else:
            norm_amt = ev.amount

        # Return as FinancialEvent (frozen dataclass) with normalized amount and home_currency
        result.append(FinancialEvent(
            event_id=ev.event_id,
            user_id=ev.user_id,
            event_type=ev.event_type,
            description=ev.description,
            category=ev.category,
            direction=ev.direction,
            amount=norm_amt,
            currency=home_currency,
            event_date=ev.event_date,
            settlement_date=ev.settlement_date,
            status=ev.status,
            linked_event_id=ev.linked_event_id,
            flexibility=ev.flexibility,
            minimum_allowed_amount=ev.minimum_allowed_amount,
        ))

    return result


def _write_output(rows: List[Dict], output_path: Path) -> None:
    """Write rows to output.csv with the contractual column order."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=config.OUTPUT_COLUMNS)
        writer.writeheader()
        for row in rows:
            # Ensure all required columns present (fill blanks if needed)
            out_row = {col: row.get(col, "") for col in config.OUTPUT_COLUMNS}
            writer.writerow(out_row)
    logger.info(f"Output written to {output_path} ({len(rows)} rows)")


def _write_usage_report(
    output_path: Path,
    n_requests: int,
    elapsed_sec: float,
    llm_calls: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    model_name: str = "",
    cost_usd: float = 0.0,
) -> None:
    """Write evaluation/usage_report.md per contract §6.5."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    per_req_tokens = (input_tokens + output_tokens) / max(n_requests, 1)
    per_req_cost = cost_usd / max(n_requests, 1)

    content = f"""# Buy or Wait? — Final Run Usage Report

## Run Summary

| Field | Value |
|---|---|
| Run date | {datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')} |
| Requests processed | {n_requests} |
| Wall-clock time | {elapsed_sec:.1f}s |
| Model provider | Anthropic |
| Model name | {model_name or config.LLM_MODEL} |

## Token Usage

| Metric | Value |
|---|---|
| Total LLM calls | {llm_calls} |
| Total input tokens | {input_tokens:,} |
| Total output tokens | {output_tokens:,} |
| Total tokens | {(input_tokens + output_tokens):,} |
| Avg tokens per request | {per_req_tokens:.1f} |

## Cost Estimate (USD)

| Metric | Value |
|---|---|
| Estimated total cost | ${cost_usd:.4f} |
| Estimated cost per request | ${per_req_cost:.6f} |

> Note: Costs are estimates based on published Anthropic pricing.
> Deterministic pipeline logic (forecast, decision engine) uses zero LLM tokens.
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info(f"Usage report written to {output_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(dataset_dir: Optional[Path] = None) -> Path:
    """
    Run the full Buy or Wait? pipeline.

    Returns the path to the written output.csv.
    """
    t0 = time.monotonic()
    logger.info("=== Buy or Wait? pipeline starting ===")

    # 1. Load dataset
    dataset = load_dataset(dataset_dir)
    logger.info(
        f"Dataset loaded: {len(dataset.requests)} requests, "
        f"{len(dataset.events_list)} events, "
        f"{len(dataset.profiles)} profiles"
    )

    # 2. Validate env / warn if issues
    warnings = config.validate_env()
    for w in warnings:
        logger.warning(w)

    # 3. Build FX converter
    fx = FXConverter(exchange_rates=dataset.exchange_rates)

    # 4. Optional: extract evidence from images & messages
    evidence_image_facts: Dict[str, Any] = {}
    evidence_message_facts: Dict[str, Any] = {}
    llm_calls = input_tokens = output_tokens = 0

    # Initialize LLM client for explanation generation if available
    llm_client = None
    if _explanation_available:
        try:
            llm_client = LLMClient(
                api_key=config.ANTHROPIC_API_KEY,
                model=config.LLM_MODEL,
                temperature=config.LLM_TEMPERATURE,
                max_tokens=config.EXPLAIN_MAX_TOKENS,
                enable_cache=True,
            )
        except Exception as e:
            logger.warning(f"Failed to initialize LLM client for explanations: {e}")

    if _evidence_available:
        logger.info("Extracting image facts via LLM (untrusted evidence only)...")
        try:
            img_facts = extract_all_image_facts(dataset.images)
            for fact in img_facts:
                if fact.image_id:
                    evidence_image_facts[fact.image_id] = fact
            logger.info(f"Extracted {len(img_facts)} image facts")
        except Exception as e:
            logger.warning(f"Image extraction failed: {e}. Proceeding without image facts.")

        logger.info("Extracting message facts via LLM (untrusted evidence only)...")
        try:
            msg_facts = extract_all_message_facts(dataset.messages)
            for fact in msg_facts:
                if fact.message_id:
                    evidence_message_facts[fact.message_id] = fact
            logger.info(f"Extracted {len(msg_facts)} message facts")
        except Exception as e:
            logger.warning(f"Message extraction failed: {e}. Proceeding without message facts.")
    else:
        logger.info("Skipping LLM evidence extraction (ANTHROPIC_API_KEY not set)")

    # 5. Process each request deterministically
    rows = []
    for request in dataset.requests_list:
        req_id = request.request_id
        uid = request.user_id

        profile = dataset.profiles.get(uid)
        if not profile:
            logger.warning(f"Request {req_id}: no profile for user {uid}. Marking not_affordable.")
            rows.append({
                "request_id": req_id,
                "amount_safe_to_pay": 0,
                "affordability_status": "not_affordable",
                "recommended_payment_method": "not_recommended",
                "payment_plan": "none",
                "earliest_date_for_full_payment": "",
                "spending_changes_needed": "none",
                "decision_explanation": f"No financial profile found for user {uid}.",
                "requested_amount": request.requested_amount,
            })
            continue

        # Get payment options for this request
        payment_options = [
            opt for opt in dataset.payment_options if opt.request_id == req_id
        ]

        # Build forecast state
        try:
            fs = _build_forecast_state(request, profile, dataset, fx)
        except Exception as e:
            logger.error(f"Request {req_id}: forecast build failed: {e}")
            rows.append({
                "request_id": req_id,
                "amount_safe_to_pay": 0,
                "affordability_status": "not_affordable",
                "recommended_payment_method": "not_recommended",
                "payment_plan": "none",
                "earliest_date_for_full_payment": "",
                "spending_changes_needed": "none",
                "decision_explanation": f"Forecast build error: {e}",
                "requested_amount": request.requested_amount,
            })
            continue

        # Get future events (for spending-change candidate generation)
        future_events = _get_future_events(request, dataset, fx, profile)

        # Run decision engine
        try:
            engine = DecisionEngine(
                request=request,
                profile=profile,
                forecast_state=fs,
                payment_options=payment_options,
                future_events=future_events,
            )
            result = engine.run()
        except Exception as e:
            logger.error(f"Request {req_id}: decision engine failed: {e}")
            result = {
                "request_id": req_id,
                "amount_safe_to_pay": 0,
                "affordability_status": "not_affordable",
                "recommended_payment_method": "not_recommended",
                "payment_plan": "none",
                "earliest_date_for_full_payment": "",
                "spending_changes_needed": "none",
                "decision_explanation": f"Decision engine error: {e}",
                "requested_amount": request.requested_amount,
            }

        # Generate explanation using LLM if available, otherwise keep deterministic fallback
        if _explanation_available and llm_client and generate_explanation_from_decision:
            try:
                explanation = generate_explanation_from_decision(
                    llm_client=llm_client,
                    decision=result,
                    current_balance=profile.current_available_balance,
                    minimum_balance=profile.minimum_balance_to_keep,
                    relevant_facts=f"Request amount: {request.requested_amount}, deadline: {request.desired_completion_date}",
                    enable_cache=True,
                )
                result["decision_explanation"] = explanation
            except Exception as e:
                logger.warning(f"Request {req_id}: explanation generation failed: {e}, using fallback")
                # Keep the deterministic explanation from decision engine

        rows.append(result)
        logger.debug(f"Request {req_id}: {result['affordability_status']} / {result['recommended_payment_method']}")

    # 6. Write output.csv
    output_path = config.OUTPUT_CSV
    _write_output(rows, output_path)

    # 7. Write usage report
    elapsed = time.monotonic() - t0
    usage_report_path = config.REPO_ROOT / "evaluation" / "usage_report.md"
    _write_usage_report(
        usage_report_path,
        n_requests=len(rows),
        elapsed_sec=elapsed,
        llm_calls=llm_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model_name=config.LLM_MODEL,
        cost_usd=0.0,
    )

    logger.info(
        f"=== Pipeline complete: {len(rows)} rows in {elapsed:.1f}s ==="
    )
    return output_path


if __name__ == "__main__":
    out = run_pipeline()
    print(f"\nOutput written to: {out}")

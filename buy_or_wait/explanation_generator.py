"""explanation_generator.py - LLM-based explanation generation with strict fallbacks.

The LLM may ONLY phrase a short explanation. It must NEVER:
- change affordability_status
- change recommended_payment_method
- change payment_plan
- change amount_safe_to_pay
- invent income
- invent expenses
- invent evidence
- reinterpret the rules

Input to LLM: Only the chosen plan and specific verified facts/numbers/events.
Output: 1-3 concise sentences grounded in those facts.

Fallback: If API fails, use deterministic template-based explanation.
decision_explanation must never be empty.
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass

from buy_or_wait.llm_client import LLMClient, LLMResponse

logger = logging.getLogger(__name__)

EXPLANATION_CACHE_DIR = Path(__file__).parent / "cache" / "explanation"
EXPLANATION_CACHE_DIR.mkdir(parents=True, exist_ok=True)

EXPLANATION_PROMPT = (Path(__file__).parent / "prompts" / "explanation_prompt.md").read_text()


@dataclass
class ExplanationRequest:
    """Structured input for explanation generation."""
    request_id: str
    recommended_payment_method: str
    affordability_status: str
    payment_plan: str
    amount_safe_to_pay: float
    requested_amount: float
    earliest_date_for_full_payment: str
    spending_changes_needed: str
    current_balance: float
    minimum_balance: float
    relevant_facts: str


def _get_explanation_cache_key(request: ExplanationRequest) -> str:
    """Generate stable cache key from request content."""
    content = json.dumps({
        "method": request.recommended_payment_method,
        "status": request.affordability_status,
        "plan": request.payment_plan,
        "amount_safe": request.amount_safe_to_pay,
        "requested": request.requested_amount,
        "earliest_date": request.earliest_date_for_full_payment,
        "changes": request.spending_changes_needed,
        "balance": request.current_balance,
        "min_balance": request.minimum_balance,
        "facts": request.relevant_facts,
    }, sort_keys=True)
    return f"exp_{hashlib.sha256(content.encode()).hexdigest()[:24]}"


def _load_explanation_cache(cache_key: str) -> Optional[str]:
    """Load cached explanation if available."""
    cache_path = EXPLANATION_CACHE_DIR / f"{cache_key}.json"
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text())
            return data.get("explanation")
        except Exception as e:
            logger.warning(f"Explanation cache read failed: {e}")
    return None


def _save_explanation_cache(cache_key: str, explanation: str):
    """Save explanation to cache."""
    cache_path = EXPLANATION_CACHE_DIR / f"{cache_key}.json"
    try:
        cache_path.write_text(json.dumps({"explanation": explanation}))
    except Exception as e:
        logger.warning(f"Explanation cache write failed: {e}")


def _deterministic_fallback(request: ExplanationRequest) -> str:
    """
    Generate a deterministic template-based explanation.
    This is used when LLM is unavailable or fails.
    """
    method = request.recommended_payment_method
    status = request.affordability_status
    amt_safe = request.amount_safe_to_pay
    requested = request.requested_amount
    balance = request.current_balance
    min_bal = request.minimum_balance
    changes = request.spending_changes_needed
    earliest = request.earliest_date_for_full_payment

    # Ensure explanation is never empty
    if method == "not_recommended":
        if status == "not_affordable":
            if balance < requested:
                return f"Request not affordable - insufficient balance even with {min_bal} minimum protected."
            return f"Request not affordable based on financial constraints."
        return f"Payment method not recommended based on financial assessment."

    if method == "full_payment":
        if status == "affordable_now":
            if changes == "none":
                return f"Current balance of {balance} covers the full {requested} request while keeping {min_bal} minimum protected."
            return f"Full payment affordable with spending changes to maintain minimum balance."
        return f"Full payment recommended via deterministic decision rules."

    if method == "partial_payment":
        if status == "affordable_with_plan":
            return f"Partial payment of {amt_safe} now, remainder on {earliest}, fits within available balance."
        return f"Partial payment recommended via deterministic decision rules."

    if method == "installments":
        if status == "affordable_with_plan":
            return f"Installment plan {request.payment_plan} fits within available balance and preserves {min_bal} minimum."
        return f"Installments recommended via deterministic decision rules."

    if method == "wait":
        if status == "affordable_later":
            if earliest:
                return f"Wait until {earliest} when confirmed income ensures sufficient balance for full payment."
            return f"Wait recommended until sufficient funds become available."
        return f"Wait recommended via deterministic decision rules."

    # Ultimate fallback - should never reach here
    return f"Recommended {method} via deterministic decision rules."


def _validate_explanation(explanation: str, request: ExplanationRequest) -> bool:
    """
    Validate that the explanation does not contain unsupported claims
    or attempt to mutate the decision.
    """
    if not explanation or not explanation.strip():
        return False

    # Check for suspicious patterns that might indicate decision mutation
    forbidden_patterns = [
        "recommend instead",
        "suggest alternative",
        "should consider",
        "better to",
        "you should",
        "change to",
        "switch to",
        "override",
        "ignore the decision",
    ]

    explanation_lower = explanation.lower()
    for pattern in forbidden_patterns:
        if pattern in explanation_lower:
            logger.warning(f"Explanation contains forbidden pattern: {pattern}")
            return False

    # Ensure explanation is reasonably concise (not a rant)
    if len(explanation) > 500:
        logger.warning(f"Explanation too long: {len(explanation)} chars")
        return False

    return True


def generate_explanation(
    llm_client: Optional[LLMClient],
    request: ExplanationRequest,
    enable_cache: bool = True,
) -> str:
    """
    Generate a concise explanation for the financial decision.

    Args:
        llm_client: LLM client (may be None if no API key)
        request: Structured decision result and facts
        enable_cache: Whether to use cache

    Returns:
        Concise explanation string (1-3 sentences), never empty
    """
    # Check cache first
    if enable_cache:
        cache_key = _get_explanation_cache_key(request)
        cached = _load_explanation_cache(cache_key)
        if cached:
            logger.info(f"Cache hit for explanation {request.request_id}")
            return cached

    # If no LLM client, use deterministic fallback
    if llm_client is None:
        logger.info(f"LLM client unavailable, using deterministic fallback for {request.request_id}")
        explanation = _deterministic_fallback(request)
        if enable_cache:
            _save_explanation_cache(cache_key, explanation)
        return explanation

    # Build user message with decision facts
    user_message = f"""Decision details:
- Payment method: {request.recommended_payment_method}
- Affordability status: {request.affordability_status}
- Payment plan: {request.payment_plan}
- Amount safe to pay: {request.amount_safe_to_pay}
- Requested amount: {request.requested_amount}
- Earliest date for full payment: {request.earliest_date_for_full_payment}
- Spending changes needed: {request.spending_changes_needed}
- Current balance: {request.current_balance}
- Minimum balance to keep: {request.minimum_balance}
- Relevant facts: {request.relevant_facts}

Generate a 1-3 sentence explanation grounded in these facts."""

    try:
        messages = [{"role": "user", "content": user_message}]
        response = llm_client.complete(
            messages=messages,
            system=EXPLANATION_PROMPT,
            request_type=f"explanation_{request.request_id}",
            max_retries=1,
        )

        explanation = response.content.strip()

        # Validate the explanation
        if not _validate_explanation(explanation, request):
            logger.warning(f"LLM explanation validation failed for {request.request_id}, using fallback")
            explanation = _deterministic_fallback(request)

        # Cache the result
        if enable_cache:
            _save_explanation_cache(cache_key, explanation)

        return explanation

    except Exception as e:
        logger.warning(f"LLM explanation generation failed for {request.request_id}: {e}, using fallback")
        explanation = _deterministic_fallback(request)
        if enable_cache:
            _save_explanation_cache(cache_key, explanation)
        return explanation


def generate_explanation_from_decision(
    llm_client: Optional[LLMClient],
    decision: Dict[str, Any],
    current_balance: float,
    minimum_balance: float,
    relevant_facts: str = "",
    enable_cache: bool = True,
) -> str:
    """
    Convenience wrapper to generate explanation from a decision dict.

    Args:
        llm_client: LLM client (may be None)
        decision: Decision result dict from DecisionEngine
        current_balance: User's current balance
        minimum_balance: User's minimum balance to keep
        relevant_facts: Additional relevant financial facts
        enable_cache: Whether to use cache

    Returns:
        Concise explanation string, never empty
    """
    request = ExplanationRequest(
        request_id=decision.get("request_id", ""),
        recommended_payment_method=decision.get("recommended_payment_method", ""),
        affordability_status=decision.get("affordability_status", ""),
        payment_plan=decision.get("payment_plan", ""),
        amount_safe_to_pay=decision.get("amount_safe_to_pay", 0.0),
        requested_amount=decision.get("requested_amount", 0.0),
        earliest_date_for_full_payment=decision.get("earliest_date_for_full_payment", ""),
        spending_changes_needed=decision.get("spending_changes_needed", ""),
        current_balance=current_balance,
        minimum_balance=minimum_balance,
        relevant_facts=relevant_facts,
    )

    return generate_explanation(llm_client, request, enable_cache)

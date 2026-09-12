"""
config.py - Centralized configuration for Buy or Wait? pipeline.
All paths, model names, and environment-variable loading live here.
Never import secrets directly - always read from environment variables.
"""

import os
from pathlib import Path

# Safe .env loading with or without python-dotenv package
def _load_env_file(path: Path):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("'\""))

try:
    from dotenv import load_dotenv
    _has_dotenv = True
except ImportError:
    _has_dotenv = False

# 📁 Repo root (directory containing this file's parent: code/)
REPO_ROOT = Path(__file__).resolve().parent.parent

# 📁 Load .env from repo root (if present; safe to call even if missing)
if _has_dotenv:
    load_dotenv(REPO_ROOT / '.env')
else:
    _load_env_file(REPO_ROOT / '.env')

# 📁 Dataset paths (read-only)
DATASET_DIR = REPO_ROOT / "dataset"
MEDIA_IMAGES_DIR = DATASET_DIR / "media" / "images"

CSV_FINANCIAL_PROFILES      = DATASET_DIR / "financial_profiles.csv"
CSV_FINANCIAL_EVENTS        = DATASET_DIR / "financial_events.csv"
CSV_EXCHANGE_RATES          = DATASET_DIR / "exchange_rates.csv"
CSV_REQUESTS                = DATASET_DIR / "requests.csv"
CSV_SAMPLE_REQUESTS         = DATASET_DIR / "sample_requests.csv"
CSV_REQUEST_PAYMENT_OPTIONS = DATASET_DIR / "request_payment_options.csv"
CSV_MESSAGES                = DATASET_DIR / "messages.csv"
CSV_IMAGES                  = DATASET_DIR / "images.csv"

# 📁 Output directory - can be overridden via OUTPUT_DIR env variable
_OUTPUT_DIR_ENV = os.environ.get("OUTPUT_DIR", "")
OUTPUT_DIR = Path(_OUTPUT_DIR_ENV) if _OUTPUT_DIR_ENV else REPO_ROOT

# Ensure output directory exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 📄 Output paths (all generated files go to OUTPUT_DIR)
OUTPUT_CSV          = OUTPUT_DIR / "output.csv"
LOG_TXT             = OUTPUT_DIR / "log.txt"
LLM_CACHE_JSON      = OUTPUT_DIR / "llm_cache.json"
USAGE_REPORT_MD     = OUTPUT_DIR / "usage_report.md"

# 🤖 LLM / VLM configuration
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL           = os.environ.get("LLM_MODEL", "claude-opus-4-5")
LLM_TEMPERATURE     = 0          # must be 0 for determinism
LLM_MAX_TOKENS      = 1024       # for extraction calls
EXPLAIN_MAX_TOKENS  = 256        # for explanation calls

# 📈 Forecast parameters
FORECAST_DAYS = 90               # 90-day forward simulation window

# 📋 Output schema (column order is contractual - do not reorder)
OUTPUT_COLUMNS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]

# ✅ Allowed enum values
ALLOWED_AFFORDABILITY_STATUS = {
    "affordable_now",
    "affordable_with_plan",
    "affordable_later",
    "not_affordable",
}

ALLOWED_PAYMENT_METHODS = {
    "full_payment",
    "partial_payment",
    "installments",
    "wait",
    "not_recommended",
}

# ⏰ Deadline
CHALLENGE_DEADLINE_IST = "2026-09-13T18:00:00+05:30"

# 🔗 Submission URL
SUBMISSION_URL = (
    "https://www.hackerrank.com/contests/"
    "hackerrank-orchestrate-september26/challenges/buy-or-wait/submission"
)

def validate_env() -> list[str]:
    """Return a list of configuration warnings (not errors - pipeline can run without LLM for deterministic parts)."""
    warnings = []
    if not ANTHROPIC_API_KEY:
        warnings.append(
            "ANTHROPIC_API_KEY not set. LLM-based image/message extraction and "
            "explanation generation will be unavailable."
        )
    for path in [
        CSV_FINANCIAL_PROFILES,
        CSV_FINANCIAL_EVENTS,
        CSV_EXCHANGE_RATES,
        CSV_REQUESTS,
        CSV_SAMPLE_REQUESTS,
        CSV_REQUEST_PAYMENT_OPTIONS,
        CSV_MESSAGES,
        CSV_IMAGES,
    ]:
        if not path.exists():
            warnings.append(f"Missing dataset file: {path}")
    if not MEDIA_IMAGES_DIR.exists():
        warnings.append(f"Missing image directory: {MEDIA_IMAGES_DIR}")
    return warnings


if __name__ == "__main__":
    issues = validate_env()
    if issues:
        print("Configuration warnings:")
        for w in issues:
            print(f"  - {w}")
    else:
        print("Configuration OK - all dataset files present, API key loaded.")
    print(f"REPO_ROOT     : {REPO_ROOT}")
    print(f"DATASET_DIR   : {DATASET_DIR}")
    print(f"OUTPUT_DIR    : {OUTPUT_DIR}")
    print(f"LLM_MODEL     : {LLM_MODEL}")
    print(f"FORECAST_DAYS : {FORECAST_DAYS}")



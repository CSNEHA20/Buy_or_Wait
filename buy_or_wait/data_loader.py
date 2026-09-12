"""
data_loader.py - Typed dataset loader and validation layer for Buy or Wait? pipeline.

Requirements:
1. Resolve paths relative to repository root (or dataset_dir passed as argument).
2. Load all 8 required CSV files.
3. Validate that required files exist.
4. Validate required columns.
5. Preserve raw string identifiers exactly (user_id, request_id, event_id, etc.).
6. Parse dates into datetime.date / datetime.datetime.
7. Parse numeric fields safely.
8. Preserve blank financial values as None (DO NOT convert blank to 0.0!).
9. Validate currencies.
10. Validate relationships: user_id, request_id, related_event_id, linked_event_id, payment_option_id, image_id.
11. Provide one clean Dataset object container.
12. No business logic, no LLM calls, read-only dataset access.
"""

import csv
import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any

from . import config


class DataLoaderError(Exception):
    """Custom exception raised when dataset loading or schema validation fails."""
    pass


# --- Helper Parsing Functions ---

def parse_date(val: Optional[str], field_name: str, allow_blank: bool = True) -> Optional[datetime.date]:
    if val is None or val.strip() == "":
        if allow_blank:
            return None
        raise DataLoaderError(f"Missing required date field: '{field_name}'")
    val_clean = val.strip()
    try:
        return datetime.date.fromisoformat(val_clean)
    except ValueError:
        try:
            return datetime.datetime.strptime(val_clean, "%Y-%m-%d").date()
        except ValueError:
            raise DataLoaderError(f"Invalid date format for '{field_name}': '{val}'")


def parse_datetime(val: Optional[str], field_name: str, allow_blank: bool = True) -> Optional[datetime.datetime]:
    if val is None or val.strip() == "":
        if allow_blank:
            return None
        raise DataLoaderError(f"Missing required datetime field: '{field_name}'")
    val_clean = val.strip()
    try:
        return datetime.datetime.fromisoformat(val_clean)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.datetime.strptime(val_clean, fmt)
            except ValueError:
                pass
        raise DataLoaderError(f"Invalid datetime format for '{field_name}': '{val}'")


def parse_float(val: Optional[str], field_name: str, allow_blank: bool = True) -> Optional[float]:
    if val is None or val.strip() == "":
        if allow_blank:
            return None
        raise DataLoaderError(f"Missing required numeric field: '{field_name}'")
    val_clean = val.strip()
    try:
        res = float(val_clean)
        return res
    except ValueError:
        raise DataLoaderError(f"Invalid numeric value for '{field_name}': '{val}'")


def parse_int(val: Optional[str], field_name: str, allow_blank: bool = True) -> Optional[int]:
    if val is None or val.strip() == "":
        if allow_blank:
            return None
        raise DataLoaderError(f"Missing required integer field: '{field_name}'")
    val_clean = val.strip()
    try:
        f_val = float(val_clean)
        if not f_val.is_integer():
            raise DataLoaderError(f"Invalid integer value for '{field_name}': '{val}'")
        return int(f_val)
    except ValueError:
        raise DataLoaderError(f"Invalid integer value for '{field_name}': '{val}'")


def parse_bool(val: Optional[str], field_name: str, allow_blank: bool = False) -> bool:
    if val is None or val.strip() == "":
        if allow_blank:
            return False
        raise DataLoaderError(f"Missing required boolean field: '{field_name}'")
    val_clean = val.strip().lower()
    if val_clean in ("true", "1", "yes", "t"):
        return True
    if val_clean in ("false", "0", "no", "f"):
        return False
    raise DataLoaderError(f"Invalid boolean value for '{field_name}': '{val}'")


def parse_pipe_list(val: Optional[str]) -> List[str]:
    if not val or not val.strip():
        return []
    return [item.strip() for item in val.split("|") if item.strip()]


def validate_currency(currency: Optional[str], field_name: str, allow_blank: bool = False) -> Optional[str]:
    if currency is None or currency.strip() == "":
        if allow_blank:
            return None
        raise DataLoaderError(f"Missing currency in '{field_name}'")
    curr_clean = currency.strip().upper()
    if len(curr_clean) != 3 or not curr_clean.isalpha():
        raise DataLoaderError(f"Invalid currency format in '{field_name}': '{currency}'")
    return curr_clean


# --- Dataclasses ---

@dataclass(frozen=True)
class FinancialProfile:
    user_id: str
    home_currency: str
    current_available_balance: float
    minimum_balance_to_keep: float
    financial_priorities: List[str]
    expense_categories_to_protect: List[str]
    expense_categories_user_is_willing_to_reduce: List[str]
    expense_categories_user_is_willing_to_stop: List[str]
    payment_methods_user_will_consider: List[str]
    max_installment_months: Optional[int]  # None if blank


@dataclass(frozen=True)
class FinancialEvent:
    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: str
    amount: Optional[float]  # Preserved as None if blank
    currency: str
    event_date: datetime.date
    settlement_date: Optional[datetime.date]
    status: str
    linked_event_id: Optional[str]
    flexibility: str
    minimum_allowed_amount: Optional[float]


@dataclass(frozen=True)
class ExchangeRate:
    rate_date: datetime.date
    from_currency: str
    to_currency: str
    rate: float


@dataclass(frozen=True)
class PurchaseRequest:
    request_id: str
    user_id: str
    request_date: datetime.date
    request_type: str
    requested_amount: float
    desired_completion_date: Optional[datetime.date]
    allows_partial_payment: bool
    request_text: str


@dataclass(frozen=True)
class SampleRequest(PurchaseRequest):
    amount_safe_to_pay: Optional[float]
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str
    earliest_date_for_full_payment: Optional[datetime.date]
    spending_changes_needed: str
    decision_explanation: str


@dataclass(frozen=True)
class PaymentOption:
    payment_option_id: str
    request_id: str
    payment_method: str
    payment_amount: Optional[float]
    number_of_payments: Optional[int]
    first_payment_date: Optional[datetime.date]
    payment_frequency_days: Optional[int]
    financing_fee: Optional[float]
    total_payable_amount: Optional[float]


@dataclass(frozen=True)
class Message:
    message_id: str
    user_id: str
    request_id: Optional[str]
    related_event_id: Optional[str]
    sent_at: Optional[datetime.datetime]
    source_type: str
    message_text: str


@dataclass(frozen=True)
class ImageRecord:
    image_id: str
    user_id: str
    request_id: Optional[str]
    related_event_id: Optional[str]


@dataclass
class Dataset:
    dataset_dir: Path
    profiles: Dict[str, FinancialProfile]
    events: Dict[str, FinancialEvent]
    events_list: List[FinancialEvent]
    exchange_rates: List[ExchangeRate]
    requests: Dict[str, PurchaseRequest]
    requests_list: List[PurchaseRequest]
    sample_requests: Dict[str, SampleRequest]
    sample_requests_list: List[SampleRequest]
    payment_options: List[PaymentOption]
    messages: List[Message]
    images: List[ImageRecord]

    def validate_references(self) -> List[str]:
        """Validate foreign key relationships across dataset tables. Returns list of warning/error messages."""
        issues = []
        user_ids = set(self.profiles.keys())
        request_ids = set(self.requests.keys()) | set(self.sample_requests.keys())
        event_ids = set(self.events.keys())

        # 1. user_id references in events
        for e in self.events_list:
            if e.user_id not in user_ids:
                issues.append(f"Event '{e.event_id}' references unknown user_id '{e.user_id}'")

        # 2. user_id references in requests
        for r in self.requests_list:
            if r.user_id not in user_ids:
                issues.append(f"Request '{r.request_id}' references unknown user_id '{r.user_id}'")

        # 3. user_id references in messages
        for m in self.messages:
            if m.user_id not in user_ids:
                issues.append(f"Message '{m.message_id}' references unknown user_id '{m.user_id}'")

        # 4. user_id references in images
        for img in self.images:
            if img.user_id not in user_ids:
                issues.append(f"Image '{img.image_id}' references unknown user_id '{img.user_id}'")

        # 5. request_id references in payment_options
        for opt in self.payment_options:
            if opt.request_id not in request_ids:
                issues.append(f"PaymentOption '{opt.payment_option_id}' references unknown request_id '{opt.request_id}'")

        # 6. request_id references in messages (when present)
        for m in self.messages:
            if m.request_id and m.request_id not in request_ids:
                issues.append(f"Message '{m.message_id}' references unknown request_id '{m.request_id}'")

        # 7. request_id references in images (when present)
        for img in self.images:
            if img.request_id and img.request_id not in request_ids:
                issues.append(f"Image '{img.image_id}' references unknown request_id '{img.request_id}'")

        # 8. related_event_id references in messages
        for m in self.messages:
            if m.related_event_id and m.related_event_id not in event_ids:
                issues.append(f"Message '{m.message_id}' references unknown related_event_id '{m.related_event_id}'")

        # 9. related_event_id references in images
        for img in self.images:
            if img.related_event_id and img.related_event_id not in event_ids:
                issues.append(f"Image '{img.image_id}' references unknown related_event_id '{img.related_event_id}'")

        # 10. linked_event_id references in events
        for e in self.events_list:
            if e.linked_event_id and e.linked_event_id not in event_ids:
                issues.append(f"Event '{e.event_id}' references unknown linked_event_id '{e.linked_event_id}'")

        # 11. Image file existence
        media_img_dir = self.dataset_dir / "media" / "images"
        for img in self.images:
            img_file = media_img_dir / f"{img.image_id}.png"
            if not img_file.exists():
                issues.append(f"Image '{img.image_id}' record has missing image file at {img_file}")

        return issues


# --- Table Loading Logic ---

REQUIRED_FILES = [
    "financial_profiles.csv",
    "financial_events.csv",
    "exchange_rates.csv",
    "requests.csv",
    "sample_requests.csv",
    "request_payment_options.csv",
    "messages.csv",
    "images.csv",
]

REQUIRED_COLUMNS: Dict[str, Set[str]] = {
    "financial_profiles.csv": {
        "user_id", "home_currency", "current_available_balance", "minimum_balance_to_keep",
        "financial_priorities", "expense_categories_to_protect",
        "expense_categories_user_is_willing_to_reduce", "expense_categories_user_is_willing_to_stop",
        "payment_methods_user_will_consider", "max_installment_months"
    },
    "financial_events.csv": {
        "event_id", "user_id", "event_type", "description", "category", "direction",
        "amount", "currency", "event_date", "settlement_date", "status",
        "linked_event_id", "flexibility", "minimum_allowed_amount"
    },
    "exchange_rates.csv": {
        "rate_date", "from_currency", "to_currency", "rate"
    },
    "requests.csv": {
        "request_id", "user_id", "request_date", "request_type", "requested_amount",
        "desired_completion_date", "allows_partial_payment", "request_text"
    },
    "sample_requests.csv": {
        "request_id", "user_id", "request_date", "request_type", "requested_amount",
        "desired_completion_date", "allows_partial_payment", "request_text",
        "amount_safe_to_pay", "affordability_status", "recommended_payment_method",
        "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed",
        "decision_explanation"
    },
    "request_payment_options.csv": {
        "payment_option_id", "request_id", "payment_method", "payment_amount",
        "number_of_payments", "first_payment_date", "payment_frequency_days",
        "financing_fee", "total_payable_amount"
    },
    "messages.csv": {
        "message_id", "user_id", "request_id", "related_event_id", "sent_at",
        "source_type", "message_text"
    },
    "images.csv": {
        "image_id", "user_id", "request_id", "related_event_id"
    },
}


def _read_csv(file_path: Path, fname: str) -> List[Dict[str, str]]:
    if not file_path.exists():
        raise FileNotFoundError(f"Required dataset file missing: '{file_path}'")
    with open(file_path, mode="r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise DataLoaderError(f"CSV file '{fname}' is empty or has no header")
        headers = set(reader.fieldnames)
        req_cols = REQUIRED_COLUMNS.get(fname, set())
        missing_cols = req_cols - headers
        if missing_cols:
            raise DataLoaderError(f"File '{fname}' missing required column(s): {sorted(list(missing_cols))}")
        return list(reader)


def load_dataset(dataset_dir: Optional[Path] = None) -> Dataset:
    """
    Load and validate all dataset CSV files from dataset_dir (defaults to config.DATASET_DIR).
    Returns a typed Dataset object.
    """
    if dataset_dir is None:
        dataset_dir = config.DATASET_DIR
    dataset_dir = Path(dataset_dir).resolve()

    # 1. Check all required files exist
    for fname in REQUIRED_FILES:
        fpath = dataset_dir / fname
        if not fpath.exists():
            raise FileNotFoundError(f"Required dataset file missing: '{fpath}'")

    # 2. Load Profiles
    profiles_raw = _read_csv(dataset_dir / "financial_profiles.csv", "financial_profiles.csv")
    profiles: Dict[str, FinancialProfile] = {}
    for r in profiles_raw:
        uid = r["user_id"].strip()
        if not uid:
            raise DataLoaderError("Blank 'user_id' in financial_profiles.csv")
        curr = validate_currency(r["home_currency"], "home_currency in profiles")
        bal = parse_float(r["current_available_balance"], "current_available_balance in profiles", allow_blank=False)
        min_bal = parse_float(r["minimum_balance_to_keep"], "minimum_balance_to_keep in profiles", allow_blank=False)
        max_inst = parse_int(r["max_installment_months"], "max_installment_months in profiles", allow_blank=True)

        prof = FinancialProfile(
            user_id=uid,
            home_currency=curr,
            current_available_balance=bal,
            minimum_balance_to_keep=min_bal,
            financial_priorities=parse_pipe_list(r["financial_priorities"]),
            expense_categories_to_protect=parse_pipe_list(r["expense_categories_to_protect"]),
            expense_categories_user_is_willing_to_reduce=parse_pipe_list(r["expense_categories_user_is_willing_to_reduce"]),
            expense_categories_user_is_willing_to_stop=parse_pipe_list(r["expense_categories_user_is_willing_to_stop"]),
            payment_methods_user_will_consider=parse_pipe_list(r["payment_methods_user_will_consider"]),
            max_installment_months=max_inst,
        )
        profiles[uid] = prof

    # 3. Load Events
    events_raw = _read_csv(dataset_dir / "financial_events.csv", "financial_events.csv")
    events: Dict[str, FinancialEvent] = {}
    events_list: List[FinancialEvent] = []
    for r in events_raw:
        eid = r["event_id"].strip()
        if not eid:
            raise DataLoaderError("Blank 'event_id' in financial_events.csv")
        uid = r["user_id"].strip()
        curr = validate_currency(r["currency"], f"currency for event {eid}")
        amt = parse_float(r["amount"], f"amount for event {eid}", allow_blank=True)
        evt_date = parse_date(r["event_date"], f"event_date for event {eid}", allow_blank=False)
        settle_date = parse_date(r["settlement_date"], f"settlement_date for event {eid}", allow_blank=True)
        linked_id = r["linked_event_id"].strip() if r["linked_event_id"].strip() else None
        min_amt = parse_float(r["minimum_allowed_amount"], f"minimum_allowed_amount for event {eid}", allow_blank=True)

        evt = FinancialEvent(
            event_id=eid,
            user_id=uid,
            event_type=r["event_type"].strip(),
            description=r["description"].strip(),
            category=r["category"].strip(),
            direction=r["direction"].strip().lower(),
            amount=amt,
            currency=curr,
            event_date=evt_date,
            settlement_date=settle_date,
            status=r["status"].strip().lower(),
            linked_event_id=linked_id,
            flexibility=r["flexibility"].strip().lower(),
            minimum_allowed_amount=min_amt,
        )
        events[eid] = evt
        events_list.append(evt)

    # 4. Load Exchange Rates
    fx_raw = _read_csv(dataset_dir / "exchange_rates.csv", "exchange_rates.csv")
    rates: List[ExchangeRate] = []
    for r in fx_raw:
        r_date = parse_date(r["rate_date"], "rate_date in exchange_rates", allow_blank=False)
        from_c = validate_currency(r["from_currency"], "from_currency in exchange_rates")
        to_c = validate_currency(r["to_currency"], "to_currency in exchange_rates")
        rate_val = parse_float(r["rate"], "rate in exchange_rates", allow_blank=False)
        rates.append(ExchangeRate(
            rate_date=r_date,
            from_currency=from_c,
            to_currency=to_c,
            rate=rate_val,
        ))

    # 5. Load Requests
    req_raw = _read_csv(dataset_dir / "requests.csv", "requests.csv")
    requests: Dict[str, PurchaseRequest] = {}
    requests_list: List[PurchaseRequest] = []
    for r in req_raw:
        rid = r["request_id"].strip()
        if not rid:
            raise DataLoaderError("Blank 'request_id' in requests.csv")
        uid = r["user_id"].strip()
        req_date = parse_date(r["request_date"], f"request_date for request {rid}", allow_blank=False)
        req_amt = parse_float(r["requested_amount"], f"requested_amount for request {rid}", allow_blank=False)
        desired_date = parse_date(r["desired_completion_date"], f"desired_completion_date for request {rid}", allow_blank=True)
        allows_partial = parse_bool(r["allows_partial_payment"], f"allows_partial_payment for request {rid}")

        req = PurchaseRequest(
            request_id=rid,
            user_id=uid,
            request_date=req_date,
            request_type=r["request_type"].strip(),
            requested_amount=req_amt,
            desired_completion_date=desired_date,
            allows_partial_payment=allows_partial,
            request_text=r["request_text"].strip(),
        )
        requests[rid] = req
        requests_list.append(req)

    # 6. Load Sample Requests
    sample_raw = _read_csv(dataset_dir / "sample_requests.csv", "sample_requests.csv")
    sample_requests: Dict[str, SampleRequest] = {}
    sample_requests_list: List[SampleRequest] = []
    for r in sample_raw:
        rid = r["request_id"].strip()
        if not rid:
            raise DataLoaderError("Blank 'request_id' in sample_requests.csv")
        uid = r["user_id"].strip()
        req_date = parse_date(r["request_date"], f"request_date for sample_request {rid}", allow_blank=False)
        req_amt = parse_float(r["requested_amount"], f"requested_amount for sample_request {rid}", allow_blank=False)
        desired_date = parse_date(r["desired_completion_date"], f"desired_completion_date for sample_request {rid}", allow_blank=True)
        allows_partial = parse_bool(r["allows_partial_payment"], f"allows_partial_payment for sample_request {rid}")
        amt_safe = parse_float(r["amount_safe_to_pay"], f"amount_safe_to_pay for sample_request {rid}", allow_blank=True)
        earliest_date = parse_date(r["earliest_date_for_full_payment"], f"earliest_date_for_full_payment for sample_request {rid}", allow_blank=True)

        s_req = SampleRequest(
            request_id=rid,
            user_id=uid,
            request_date=req_date,
            request_type=r["request_type"].strip(),
            requested_amount=req_amt,
            desired_completion_date=desired_date,
            allows_partial_payment=allows_partial,
            request_text=r["request_text"].strip(),
            amount_safe_to_pay=amt_safe,
            affordability_status=r["affordability_status"].strip(),
            recommended_payment_method=r["recommended_payment_method"].strip(),
            payment_plan=r["payment_plan"].strip(),
            earliest_date_for_full_payment=earliest_date,
            spending_changes_needed=r["spending_changes_needed"].strip(),
            decision_explanation=r["decision_explanation"].strip(),
        )
        sample_requests[rid] = s_req
        sample_requests_list.append(s_req)

    # 7. Load Request Payment Options
    opt_raw = _read_csv(dataset_dir / "request_payment_options.csv", "request_payment_options.csv")
    payment_options: List[PaymentOption] = []
    for r in opt_raw:
        popt_id = r["payment_option_id"].strip()
        rid = r["request_id"].strip()
        amt = parse_float(r["payment_amount"], f"payment_amount for option {popt_id}", allow_blank=True)
        num_pmts = parse_int(r["number_of_payments"], f"number_of_payments for option {popt_id}", allow_blank=True)
        first_date = parse_date(r["first_payment_date"], f"first_payment_date for option {popt_id}", allow_blank=True)
        freq_days = parse_int(r["payment_frequency_days"], f"payment_frequency_days for option {popt_id}", allow_blank=True)
        fee = parse_float(r["financing_fee"], f"financing_fee for option {popt_id}", allow_blank=True)
        total_amt = parse_float(r["total_payable_amount"], f"total_payable_amount for option {popt_id}", allow_blank=True)

        payment_options.append(PaymentOption(
            payment_option_id=popt_id,
            request_id=rid,
            payment_method=r["payment_method"].strip(),
            payment_amount=amt,
            number_of_payments=num_pmts,
            first_payment_date=first_date,
            payment_frequency_days=freq_days,
            financing_fee=fee,
            total_payable_amount=total_amt,
        ))

    # 8. Load Messages
    msg_raw = _read_csv(dataset_dir / "messages.csv", "messages.csv")
    messages: List[Message] = []
    for r in msg_raw:
        mid = r["message_id"].strip()
        uid = r["user_id"].strip()
        rid = r["request_id"].strip() if r["request_id"].strip() else None
        related_eid = r["related_event_id"].strip() if r["related_event_id"].strip() else None
        sent_at = parse_datetime(r["sent_at"], f"sent_at for message {mid}", allow_blank=True)

        messages.append(Message(
            message_id=mid,
            user_id=uid,
            request_id=rid,
            related_event_id=related_eid,
            sent_at=sent_at,
            source_type=r["source_type"].strip(),
            message_text=r["message_text"].strip(),
        ))

    # 9. Load Images
    img_raw = _read_csv(dataset_dir / "images.csv", "images.csv")
    images: List[ImageRecord] = []
    for r in img_raw:
        iid = r["image_id"].strip()
        uid = r["user_id"].strip()
        rid = r["request_id"].strip() if r["request_id"].strip() else None
        related_eid = r["related_event_id"].strip() if r["related_event_id"].strip() else None

        images.append(ImageRecord(
            image_id=iid,
            user_id=uid,
            request_id=rid,
            related_event_id=related_eid,
        ))

    return Dataset(
        dataset_dir=dataset_dir,
        profiles=profiles,
        events=events,
        events_list=events_list,
        exchange_rates=rates,
        requests=requests,
        requests_list=requests_list,
        sample_requests=sample_requests,
        sample_requests_list=sample_requests_list,
        payment_options=payment_options,
        messages=messages,
        images=images,
    )

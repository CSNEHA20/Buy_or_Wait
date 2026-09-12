"""
test_data_loader.py - Test suite for data_loader module.
"""

import os
import shutil
import hashlib
from pathlib import Path
import pytest

from buy_or_wait.data_loader import (
    load_dataset,
    DataLoaderError,
    Dataset,
    FinancialEvent,
    FinancialProfile,
    PurchaseRequest,
)
import buy_or_wait.config as config


def get_dir_hash(directory: Path) -> str:
    """Helper to compute a hash of all file contents in a directory to verify it remains untouched."""
    hasher = hashlib.sha256()
    for root, dirs, files in sorted(os.walk(directory)):
        for fname in sorted(files):
            fpath = Path(root) / fname
            hasher.update(fname.encode('utf-8'))
            hasher.update(fpath.read_bytes())
    return hasher.hexdigest()


def test_successful_loading_all_datasets():
    """Test loading the real dataset from config.DATASET_DIR succeeds and populates all tables."""
    dataset = load_dataset()
    assert isinstance(dataset, Dataset)
    assert len(dataset.profiles) == 275
    assert len(dataset.events_list) == 25342
    assert len(dataset.exchange_rates) == 134
    assert len(dataset.requests) == 250
    assert len(dataset.sample_requests) == 25
    assert len(dataset.payment_options) == 790
    assert len(dataset.messages) == 215
    assert len(dataset.images) == 16


def test_missing_csv_file(tmp_path):
    """Test loading from a directory with a missing required CSV file raises FileNotFoundError."""
    temp_dataset = tmp_path / "dataset"
    shutil.copytree(config.DATASET_DIR, temp_dataset)
    (temp_dataset / "financial_profiles.csv").unlink()

    with pytest.raises(FileNotFoundError) as exc_info:
        load_dataset(temp_dataset)
    assert "financial_profiles.csv" in str(exc_info.value)


def test_missing_required_column(tmp_path):
    """Test loading a CSV file with a missing required column raises DataLoaderError."""
    temp_dataset = tmp_path / "dataset"
    shutil.copytree(config.DATASET_DIR, temp_dataset)

    profiles_csv = temp_dataset / "financial_profiles.csv"
    profiles_csv.write_text("user_id,home_currency,minimum_balance_to_keep\nuser_1,USD,1000\n", encoding="utf-8")

    with pytest.raises(DataLoaderError) as exc_info:
        load_dataset(temp_dataset)
    assert "missing required column" in str(exc_info.value)


def test_malformed_numeric_value(tmp_path):
    """Test loading a CSV with a malformed numeric value raises DataLoaderError."""
    temp_dataset = tmp_path / "dataset"
    shutil.copytree(config.DATASET_DIR, temp_dataset)

    profiles_csv = temp_dataset / "financial_profiles.csv"
    content = profiles_csv.read_text(encoding="utf-8")
    lines = content.splitlines()
    if len(lines) > 1:
        parts = lines[1].split(",")
        parts[2] = "INVALID_NUMERIC_VALUE"
        lines[1] = ",".join(parts)
    profiles_csv.write_text("\n".join(lines), encoding="utf-8")

    with pytest.raises(DataLoaderError) as exc_info:
        load_dataset(temp_dataset)
    assert "Invalid numeric value" in str(exc_info.value) or "Missing required" in str(exc_info.value)


def test_malformed_date(tmp_path):
    """Test loading a CSV with a malformed date raises DataLoaderError."""
    temp_dataset = tmp_path / "dataset"
    shutil.copytree(config.DATASET_DIR, temp_dataset)

    requests_csv = temp_dataset / "requests.csv"
    content = requests_csv.read_text(encoding="utf-8")
    lines = content.splitlines()
    if len(lines) > 1:
        parts = lines[1].split(",")
        parts[2] = "invalid-date-format"
        lines[1] = ",".join(parts)
    requests_csv.write_text("\n".join(lines), encoding="utf-8")

    with pytest.raises(DataLoaderError) as exc_info:
        load_dataset(temp_dataset)
    assert "Invalid date format" in str(exc_info.value)


def test_blank_amount_remaining_unresolved():
    """Test that events with blank amount field are loaded as amount=None, not 0.0."""
    dataset = load_dataset()
    blank_amount_events = [e for e in dataset.events_list if e.amount is None]
    assert len(blank_amount_events) > 0
    for e in blank_amount_events:
        assert e.amount is None
        assert e.amount != 0.0


def test_invalid_reference_detection_reporting(tmp_path):
    """Test that reference validation detects invalid user_id / request_id / event_id references."""
    dataset = load_dataset()
    issues_clean = dataset.validate_references()
    assert len(issues_clean) == 0

    temp_dataset = tmp_path / "dataset"
    shutil.copytree(config.DATASET_DIR, temp_dataset)

    events_csv = temp_dataset / "financial_events.csv"
    content = events_csv.read_text(encoding="utf-8")
    lines = content.splitlines()
    if len(lines) > 1:
        parts = lines[1].split(",")
        parts[1] = "NON_EXISTENT_USER_999"
        lines[1] = ",".join(parts)
    events_csv.write_text("\n".join(lines), encoding="utf-8")

    corrupted_dataset = load_dataset(temp_dataset)
    issues = corrupted_dataset.validate_references()
    assert len(issues) >= 1
    assert any("NON_EXISTENT_USER_999" in issue for issue in issues)


def test_dataset_directory_remaining_untouched():
    """Test that loading dataset does not mutate any files in dataset directory."""
    initial_hash = get_dir_hash(config.DATASET_DIR)
    dataset = load_dataset()
    final_hash = get_dir_hash(config.DATASET_DIR)
    assert initial_hash == final_hash


def test_loading_from_repo_root_and_another_working_directory(tmp_path):
    """Test dataset loading resolves paths correctly regardless of current working directory."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        dataset_default = load_dataset()
        assert len(dataset_default.requests) == 250

        dataset_explicit = load_dataset(config.DATASET_DIR)
        assert len(dataset_explicit.requests) == 250
    finally:
        os.chdir(orig_cwd)

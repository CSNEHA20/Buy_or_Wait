"""
test_audit_verification.py - Automated verification tests for Step 1.
Ensures repository structure, dataset integrity, and environment configuration.
"""

import os
import sys
import unittest
from pathlib import Path

# Ensure repo root is in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
import sys
sys.path.insert(0, str(REPO_ROOT))

import buy_or_wait.config as config


class TestStep1Audit(unittest.TestCase):

    def test_governing_files_exist(self):
        """Verify README.md, AGENTS.md, CLAUDE.md, problem_statement.md exist."""
        for filename in ["README.md", "AGENTS.md", "CLAUDE.md", "problem_statement.md"]:
            path = REPO_ROOT / filename
            self.assertTrue(path.exists(), f"Governing file {filename} is missing.")
            self.assertGreater(path.stat().st_size, 0, f"Governing file {filename} is empty.")

    def test_dataset_csvs_exist(self):
        """Verify all 8 dataset CSVs plus output.csv exist and are non-empty."""
        expected_csvs = [
            config.CSV_FINANCIAL_PROFILES,
            config.CSV_FINANCIAL_EVENTS,
            config.CSV_EXCHANGE_RATES,
            config.CSV_REQUESTS,
            config.CSV_SAMPLE_REQUESTS,
            config.CSV_REQUEST_PAYMENT_OPTIONS,
            config.CSV_MESSAGES,
            config.CSV_IMAGES,
            config.DATASET_DIR / "output.csv",
        ]
        for csv_path in expected_csvs:
            self.assertTrue(csv_path.exists(), f"Expected CSV {csv_path.name} does not exist.")
            self.assertGreater(csv_path.stat().st_size, 0, f"CSV {csv_path.name} is empty.")

    def test_image_files_exist(self):
        """Verify that all 16 referenced images exist in dataset/media/images/."""
        self.assertTrue(config.MEDIA_IMAGES_DIR.exists(), "Media images directory missing.")
        for i in range(1, 17):
            img_path = config.MEDIA_IMAGES_DIR / f"image_{i:02d}.png"
            self.assertTrue(img_path.exists(), f"Image {img_path.name} is missing on disk.")
            self.assertGreater(img_path.stat().st_size, 0, f"Image {img_path.name} is empty.")

    def test_config_contract_constants(self):
        """Verify output schema columns and allowed enums match specification."""
        self.assertEqual(len(config.OUTPUT_COLUMNS), 8)
        self.assertEqual(
            config.OUTPUT_COLUMNS,
            [
                "request_id",
                "amount_safe_to_pay",
                "affordability_status",
                "recommended_payment_method",
                "payment_plan",
                "earliest_date_for_full_payment",
                "spending_changes_needed",
                "decision_explanation",
            ],
        )
        self.assertEqual(
            config.ALLOWED_AFFORDABILITY_STATUS,
            {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"},
        )
        self.assertEqual(
            config.ALLOWED_PAYMENT_METHODS,
            {"full_payment", "partial_payment", "installments", "wait", "not_recommended"},
        )
        self.assertEqual(config.CHALLENGE_DEADLINE_IST, "2026-09-13T18:00:00+05:30")


if __name__ == "__main__":
    unittest.main()

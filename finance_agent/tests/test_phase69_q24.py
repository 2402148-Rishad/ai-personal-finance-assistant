"""Tests for Phase 6.9: q24 documented rule."""

from pathlib import Path
import pandas as pd
import pytest

from eval.run_eval import evaluate_question


def test_q24_do_not_have_data_passes():
    """(a) The exact answer 'I do not have data for January 2025. The available data covers June 2026 to August 2026.' passes q24."""
    entry = {
        "id": "q24",
        "question": "How much did I spend on dining in January 2025?",
        "check": "contains",
        "expected": "no data",
    }
    answer = "I do not have data for January 2025. The available data covers June 2026 to August 2026."
    dummy_df = pd.DataFrame()
    dummy_bills = pd.DataFrame()
    status, reason, expected_desc = evaluate_question(
        entry=entry,
        answer=answer,
        df=dummy_df,
        bills_df=dummy_bills,
        initial_budget_hash="dummy",
        budgets_path=Path("dummy"),
    )
    assert status == "PASS"


def test_q24_do_not_have_data_with_money_fails():
    """(b) 'I do not have data for January 2025, but you spent $120.00.' fails q24."""
    entry = {
        "id": "q24",
        "question": "How much did I spend on dining in January 2025?",
        "check": "contains",
        "expected": "no data",
    }
    answer = "I do not have data for January 2025, but you spent $120.00."
    dummy_df = pd.DataFrame()
    dummy_bills = pd.DataFrame()
    status, reason, expected_desc = evaluate_question(
        entry=entry,
        answer=answer,
        df=dummy_df,
        bills_df=dummy_bills,
        initial_budget_hash="dummy",
        budgets_path=Path("dummy"),
    )
    assert status == "FAIL"

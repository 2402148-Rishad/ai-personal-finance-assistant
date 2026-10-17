"""Tests for Phase 1.2:
- Stable transaction ids across loads with unchanged totals
- Period aliases: this_month, last_month, today, yesterday, current month, YYYY-MM
- 2025-12 transaction in a temporary workspace returned by get_monthly_summary
- Overview fields returned by get_data_overview()
"""

import json
import os
from pathlib import Path
import pytest
import pandas as pd

from src.periods import resolve_period
from src.store import read_csv, write_csv_atomic, create_workspace
from src.tools import get_data_overview, get_monthly_summary
from src.prompts import build_system_prompt


def test_stable_transaction_ids_across_two_loads(tmp_path):
    """Assert transaction IDs are stable across two loads, deterministic, and totals are unchanged."""
    ws = create_workspace("session_stable_ids", base_dir=tmp_path)

    # First load
    df1 = read_csv("transactions.csv", data_dir=ws)
    assert "id" in df1.columns
    assert len(df1) > 0

    # Every ID must start with 't' and have 10 hex chars after it (length 11)
    for tid in df1["id"]:
        assert isinstance(tid, str)
        assert tid.startswith("t")
        assert len(tid) == 11
        # Hex chars after 't'
        int(tid[1:], 16)

    # All IDs must be unique
    assert len(df1["id"].unique()) == len(df1)

    # Second load without writing to disk
    df2 = read_csv("transactions.csv", data_dir=ws)
    assert df1["id"].tolist() == df2["id"].tolist()
    assert df1["amount"].sum() == df2["amount"].sum()

    # Save to disk in workspace
    write_csv_atomic("transactions.csv", df1, data_dir=ws)

    # Third load from saved file
    df3 = read_csv("transactions.csv", data_dir=ws)
    assert df3["id"].tolist() == df1["id"].tolist()
    assert df3["amount"].sum() == df1["amount"].sum()


def test_period_aliases_each_alias():
    """Assert resolve_period and tools accept this_month, last_month, today, yesterday, current month, and YYYY-MM."""
    sandbox_ref = "2026-08-31"

    # 1. this_month
    assert resolve_period("this_month", sandbox_today=sandbox_ref) == "2026-08"
    res_this = json.loads(get_monthly_summary("this_month"))
    assert "error" not in res_this
    assert res_this["month"] == "2026-08"

    # 2. current month
    assert resolve_period("current month", sandbox_today=sandbox_ref) == "2026-08"
    res_curr = json.loads(get_monthly_summary("current month"))
    assert "error" not in res_curr
    assert res_curr["month"] == "2026-08"

    # 3. last_month
    assert resolve_period("last_month", sandbox_today=sandbox_ref) == "2026-07"
    res_last = json.loads(get_monthly_summary("last_month"))
    assert "error" not in res_last
    assert res_last["month"] == "2026-07"

    # 4. today
    assert resolve_period("today", sandbox_today=sandbox_ref) == "2026-08-31"
    res_today = json.loads(get_monthly_summary("today"))
    assert "error" not in res_today
    assert res_today["month"] == "2026-08"

    # 5. yesterday
    assert resolve_period("yesterday", sandbox_today=sandbox_ref) == "2026-08-30"
    res_yest = json.loads(get_monthly_summary("yesterday"))
    assert "error" not in res_yest
    assert res_yest["month"] == "2026-08"

    # 6. concrete YYYY-MM
    assert resolve_period("2026-07", sandbox_today=sandbox_ref) == "2026-07"
    res_jul = json.loads(get_monthly_summary("2026-07"))
    assert "error" not in res_jul
    assert res_jul["month"] == "2026-07"

    # 7. Invalid alias returns error dictionary with valid_examples
    err_res = resolve_period("someday_later", sandbox_today=sandbox_ref)
    assert isinstance(err_res, dict)
    assert "error" in err_res
    assert "valid_examples" in err_res
    assert "this_month" in err_res["valid_examples"]
    assert "last_month" in err_res["valid_examples"]

    # Tool also returns valid_examples when given invalid period
    tool_err = json.loads(get_monthly_summary("invalid_alias"))
    assert "error" in tool_err
    assert "valid_examples" in tool_err


def test_2025_12_transaction_in_temporary_workspace(tmp_path, monkeypatch):
    """Assert a 2025-12 transaction in a temporary workspace is returned by get_monthly_summary."""
    ws = create_workspace("session_2025_workspace", base_dir=tmp_path)
    monkeypatch.setenv("FINANCE_DATA_DIR", str(ws))

    # Read existing transactions from workspace
    tx_df = read_csv("transactions.csv", data_dir=ws)

    # Append a 2025-12 transaction
    new_tx = pd.DataFrame([{
        "date": "2025-12-18",
        "month": "2025-12",
        "category": "Groceries",
        "description": "Holiday Dinner Ingredients",
        "type": "expense",
        "amount": 175.50,
    }])
    updated_tx = pd.concat([tx_df, new_tx], ignore_index=True)
    write_csv_atomic("transactions.csv", updated_tx, data_dir=ws)

    # get_monthly_summary for 2025-12 must now succeed and find the transaction
    raw_res = get_monthly_summary("2025-12")
    res = json.loads(raw_res)

    assert "error" not in res
    assert res["month"] == "2025-12"
    assert res["total_expenses"] == 175.50
    assert res["total_income"] == 0.0

    # System prompt built in this workspace should reflect the data range starting from 2025-12
    prompt = build_system_prompt()
    assert "2025-12 to 2026-08" in prompt


def test_get_data_overview_fields():
    """Assert get_data_overview returns all expected overview fields with correct values."""
    overview = get_data_overview()

    expected_keys = {
        "first_month",
        "last_month",
        "months",
        "expense_categories",
        "transaction_count",
        "bill_count",
        "budget_categories",
        "sandbox_today",
    }
    assert expected_keys.issubset(set(overview.keys()))

    assert overview["first_month"] == "2026-06"
    assert overview["last_month"] == "2026-08"
    assert overview["months"] == ["2026-06", "2026-07", "2026-08"]
    assert "Groceries" in overview["expense_categories"]
    assert "Dining" in overview["expense_categories"]
    assert overview["transaction_count"] == 70
    assert overview["bill_count"] == 6
    assert "Dining" in overview["budget_categories"]
    assert overview["sandbox_today"] == "2026-08-31"

    # Verify JSON deserialization matches dict-like interface
    parsed = json.loads(str(overview))
    assert parsed["first_month"] == overview["first_month"]
    assert parsed["transaction_count"] == overview["transaction_count"]

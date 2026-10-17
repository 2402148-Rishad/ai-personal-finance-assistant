"""Unit tests for Phase 1.3:
1. Sandbox date: stored in <workspace>/settings.json as "sandbox_today"
   - Resolution order: settings file, then FINANCE_AS_OF_DATE, then latest transaction date in data
   - set_sandbox_today validation: not before 2000-01-01, not after 2100-12-31
   - Confirm no model tool changes the date (only UI and CLI can change it)
2. Bill day bug in upcoming_bills: clamp due_day to last day of month
   - Day 31 in February becomes 28 or 29
   - Day 31 in April becomes 30
   - Tests for both
3. Output limits:
   - TOOL_ROW_LIMIT = 50 and TOOL_CHAR_LIMIT = 6000 in config.py
   - Truncate result and add "truncated": True and "total_rows": N
   - Test with 200 rows
"""

from datetime import date
import json
import os
from pathlib import Path
import pytest
import pandas as pd

from src.config import PROJECT_ROOT, TOOL_ROW_LIMIT, TOOL_CHAR_LIMIT
from src.store import (
    create_workspace,
    read_csv,
    write_csv_atomic,
    read_json,
    write_json_atomic,
    set_sandbox_today,
    get_sandbox_today,
)
from src.tools import (
    upcoming_bills,
    get_transactions,
    truncate_tool_result,
    TOOL_SCHEMAS,
    TOOLS_BY_NAME,
)


def test_output_limits_constants():
    """Assert output limit constants are present in config with specified values."""
    assert TOOL_ROW_LIMIT == 50
    assert TOOL_CHAR_LIMIT == 6000


def test_set_sandbox_today_validation_and_storage(tmp_path):
    """Assert set_sandbox_today stores in <workspace>/settings.json with valid range [2000-01-01, 2100-12-31]."""
    ws = create_workspace("session_test_sandbox", base_dir=tmp_path)

    # Valid date storage in workspace settings.json
    res_date = set_sandbox_today("2026-09-15", workspace=ws)
    assert res_date == "2026-09-15"

    settings = read_json("settings.json", data_dir=ws)
    assert settings.get("sandbox_today") == "2026-09-15"

    # Boundary acceptance: 2000-01-01 and 2100-12-31
    assert set_sandbox_today("2000-01-01", workspace=ws) == "2000-01-01"
    assert set_sandbox_today("2100-12-31", workspace=ws) == "2100-12-31"

    # Rejection: before 2000-01-01
    with pytest.raises(ValueError, match="out of allowed range"):
        set_sandbox_today("1999-12-31", workspace=ws)

    # Rejection: after 2100-12-31
    with pytest.raises(ValueError, match="out of allowed range"):
        set_sandbox_today("2101-01-01", workspace=ws)

    # Rejection: invalid date formats
    with pytest.raises(ValueError, match="Invalid date format"):
        set_sandbox_today("invalid-date", workspace=ws)

    with pytest.raises(ValueError, match="Invalid date format"):
        set_sandbox_today("2026-02-30", workspace=ws)

    with pytest.raises(ValueError, match="cannot be empty"):
        set_sandbox_today("", workspace=ws)

    with pytest.raises(ValueError, match="cannot be None"):
        set_sandbox_today(None, workspace=ws)

    # Rejection: write to shared seed data folder is forbidden
    seed_data_dir = (PROJECT_ROOT / "data").resolve()
    with pytest.raises(PermissionError, match="Writes never go to a shared default folder"):
        set_sandbox_today("2026-09-15", workspace=seed_data_dir)

    # Confirm no model tool changes the date
    assert "set_sandbox_today" not in TOOLS_BY_NAME
    tool_names = [schema["name"] for schema in TOOL_SCHEMAS]
    assert "set_sandbox_today" not in tool_names


def test_sandbox_date_resolution_order(tmp_path, monkeypatch):
    """Assert resolution order: settings file, then FINANCE_AS_OF_DATE, then latest transaction date in data."""
    ws = create_workspace("session_res_order", base_dir=tmp_path)

    # 1. Settings file takes highest precedence
    write_json_atomic("settings.json", {"sandbox_today": "2027-04-10"}, data_dir=ws)
    monkeypatch.setenv("FINANCE_AS_OF_DATE", "2026-11-20")
    assert get_sandbox_today(workspace=ws) == "2027-04-10"

    # 2. When settings file has no sandbox_today, FINANCE_AS_OF_DATE takes precedence
    settings_file = ws / "settings.json"
    if settings_file.exists():
        settings_file.unlink()

    monkeypatch.setenv("FINANCE_AS_OF_DATE", "2026-11-20")
    assert get_sandbox_today(workspace=ws) == "2026-11-20"

    # 3. When neither settings file nor FINANCE_AS_OF_DATE is set, use latest transaction date in data
    monkeypatch.delenv("FINANCE_AS_OF_DATE", raising=False)
    tx_df = read_csv("transactions.csv", data_dir=ws)
    expected_latest = str(tx_df["date"].max())
    assert get_sandbox_today(workspace=ws) == expected_latest

    # Add a newer transaction date and verify it becomes the resolved sandbox date
    newer_tx = pd.DataFrame([{
        "date": "2028-06-30",
        "month": "2028-06",
        "category": "Groceries",
        "description": "Future Grocery Run",
        "type": "expense",
        "amount": 42.50,
    }])
    updated_tx = pd.concat([tx_df, newer_tx], ignore_index=True)
    write_csv_atomic("transactions.csv", updated_tx, data_dir=ws)

    assert get_sandbox_today(workspace=ws) == "2028-06-30"


def test_upcoming_bills_clamp_due_day_february_and_april(tmp_path, monkeypatch):
    """Assert due_day is clamped to the last day of the month being checked (Feb 28/29, Apr 30)."""
    ws = create_workspace("session_clamp_bills", base_dir=tmp_path)
    monkeypatch.setenv("FINANCE_DATA_DIR", str(ws))

    # Create bills with day 31
    clamp_bills = pd.DataFrame([
        {
            "bill_name": "Month End Subscription",
            "amount": 75.00,
            "due_day": 31,
            "category": "Subscriptions",
        }
    ])
    write_csv_atomic("bills.csv", clamp_bills, data_dir=ws)

    # 1. February 2026 (non-leap year: 28 days) -> clamped to 2026-02-28
    raw_feb26 = upcoming_bills(today="2026-02-01", days_ahead=28)
    data_feb26 = json.loads(raw_feb26)
    assert "error" not in data_feb26
    assert data_feb26["bill_count"] == 1
    bill_feb26 = data_feb26["upcoming_bills"][0]
    assert bill_feb26["due_date"] == "2026-02-28"
    assert bill_feb26["days_until_due"] == 27
    assert bill_feb26["amount"] == 75.00

    # 2. February 2024 (leap year: 29 days) -> clamped to 2024-02-29
    raw_feb24 = upcoming_bills(today="2024-02-01", days_ahead=29)
    data_feb24 = json.loads(raw_feb24)
    assert "error" not in data_feb24
    assert data_feb24["bill_count"] == 1
    bill_feb24 = data_feb24["upcoming_bills"][0]
    assert bill_feb24["due_date"] == "2024-02-29"
    assert bill_feb24["days_until_due"] == 28
    assert bill_feb24["amount"] == 75.00

    # 3. April 2026 (30 days) -> clamped to 2026-04-30
    raw_apr26 = upcoming_bills(today="2026-04-01", days_ahead=30)
    data_apr26 = json.loads(raw_apr26)
    assert "error" not in data_apr26
    assert data_apr26["bill_count"] == 1
    bill_apr26 = data_apr26["upcoming_bills"][0]
    assert bill_apr26["due_date"] == "2026-04-30"
    assert bill_apr26["days_until_due"] == 29
    assert bill_apr26["amount"] == 75.00


def test_tool_result_truncation_with_200_rows(tmp_path, monkeypatch):
    """Assert that a tool result with 200 rows is truncated to TOOL_ROW_LIMIT (50), with truncated: true and total_rows: 200."""
    ws = create_workspace("session_200_rows", base_dir=tmp_path)
    monkeypatch.setenv("FINANCE_DATA_DIR", str(ws))

    # Generate 200 transaction rows in July 2026
    rows = []
    for i in range(200):
        rows.append({
            "date": "2026-07-15",
            "month": "2026-07",
            "category": "Groceries",
            "description": f"Bulk Store Grocery Purchase Item #{i + 1:03d}",
            "type": "expense",
            "amount": round(15.50 + (i % 25), 2),
        })
    tx_df = pd.DataFrame(rows)
    write_csv_atomic("transactions.csv", tx_df, data_dir=ws)

    raw_res = get_transactions("2026-07")
    data = json.loads(raw_res)

    assert "error" not in data
    assert data["truncated"] is True
    assert data["total_rows"] == 200
    assert len(data["transactions"]) <= 50
    assert len(raw_res) <= TOOL_CHAR_LIMIT


def test_tool_result_truncation_character_limit():
    """Assert that when rows are under 50 but total characters exceed 6000, result is truncated to fit under 6000 chars."""
    # 25 rows with 350-character descriptions => ~9000 characters
    long_desc = "Long description detailed notes " * 11
    rows = [
        {"id": f"t_{i:03d}", "date": "2026-07-01", "description": long_desc, "amount": 10.0}
        for i in range(25)
    ]
    test_data = {"month": "2026-07", "transactions": rows}
    initial_dump = json.dumps(test_data)
    assert len(initial_dump) > 6000

    truncated = truncate_tool_result(test_data)
    assert truncated["truncated"] is True
    assert truncated["total_rows"] == 25
    dumped = json.dumps(truncated)
    assert len(dumped) <= 6000
    assert len(truncated["transactions"]) < 25

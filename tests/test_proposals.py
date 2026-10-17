"""Unit tests for Phase 2.1: Write proposals.

Verifies:
1. Each propose tool creates a proposal and changes no data file.
2. A bad amount, future date, and unknown category each return an error.
3. A duplicate warning appears in propose_add_transactions.
4. A high-risk delete is flagged (as well as bill cancellation and large amount change).
5. expires_at is exactly 24 hours after created_at.
6. The model cannot call any apply function.
7. Missing/ambiguous fields return status 'needs_clarification' with missing and options.
8. Extended propose_budget_change handles new category creation (1-10000, no 2x cap) and category removal.
"""

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import pytest
import pandas as pd

from src.config import PROJECT_ROOT
from src.permissions import check_permission, TOOL_TIERS, Tier
from src.store import (
    create_workspace,
    read_proposals,
    read_csv,
    get_sandbox_today,
    set_sandbox_today,
    write_json_atomic,
)
from src.validators import (
    validate_amount,
    validate_date,
    validate_category,
    validate_text,
    get_workspace_categories,
)
import src.tools as tools_module
from src.tools import (
    propose_add_transactions,
    propose_update_transaction,
    propose_delete_transaction,
    propose_bill_change,
    propose_budget_change,
    TOOL_SCHEMAS,
    TOOLS_BY_NAME,
)
from main import handle_pending_command


@pytest.fixture
def workspace_env(tmp_path, monkeypatch):
    """Create an isolated workspace from seed data and point FINANCE_DATA_DIR to it."""
    ws = create_workspace("session_test_proposals", base_dir=tmp_path)
    monkeypatch.setenv("FINANCE_DATA_DIR", str(ws))
    # Point tools module paths to the workspace
    monkeypatch.setattr(tools_module, "LOGS_DIR", ws)
    monkeypatch.setattr(tools_module, "PROPOSALS_PATH", ws / "pending_proposals.json")
    return ws


def test_each_propose_tool_creates_proposal_and_changes_no_data_file(workspace_env):
    """Verify each propose tool creates a proposal in proposals.json and modifies NO data files."""
    ws = workspace_env
    tx_file = ws / "transactions.csv"
    bills_file = ws / "bills.csv"
    budgets_file = ws / "budgets.json"

    tx_before = tx_file.read_bytes()
    bills_before = bills_file.read_bytes()
    budgets_before = budgets_file.read_bytes()

    # 1. propose_add_transactions
    res_add = propose_add_transactions([
        {
            "date": "2026-07-15",
            "description": "Brand New Book",
            "amount": 25.50,
            "category": "Shopping",
            "type": "expense",
        }
    ])
    data_add = json.loads(res_add)
    assert data_add["status"] == "pending_confirmation"
    prop_add_id = data_add["proposal_id"]

    # 2. propose_update_transaction
    df_tx = read_csv("transactions.csv", workspace=ws)
    first_id = str(df_tx["id"].iloc[0])
    res_upd = propose_update_transaction(first_id, {"description": "Updated Description", "amount": 55.0})
    data_upd = json.loads(res_upd)
    assert data_upd["status"] == "pending_confirmation"
    prop_upd_id = data_upd["proposal_id"]

    # 3. propose_delete_transaction
    res_del = propose_delete_transaction(first_id)
    data_del = json.loads(res_del)
    assert data_del["status"] == "pending_confirmation"
    prop_del_id = data_del["proposal_id"]

    # 4. propose_bill_change
    res_bill = propose_bill_change(
        action="add",
        bill_name="Home Security Monitoring",
        amount=40.0,
        due_day=12,
        category="Utilities",
    )
    data_bill = json.loads(res_bill)
    assert data_bill["status"] == "pending_confirmation"
    prop_bill_id = data_bill["proposal_id"]

    # 5. propose_budget_change
    res_bgt = propose_budget_change("Dining", 350.0)
    data_bgt = json.loads(res_bgt)
    assert data_bgt["status"] == "pending_confirmation"
    prop_bgt_id = data_bgt["proposal_id"]

    # Assert proposals.json in workspace contains all 5 proposals
    props = read_proposals(workspace=ws)
    for p_id in (prop_add_id, prop_upd_id, prop_del_id, prop_bill_id, prop_bgt_id):
        assert p_id in props
        assert props[p_id]["id"] == p_id
        assert props[p_id]["status"] == "pending_confirmation"
        assert "created_at" in props[p_id]
        assert "expires_at" in props[p_id]
        assert "preview" in props[p_id]
        assert "before" in props[p_id]["preview"]
        assert "after" in props[p_id]["preview"]

    # Assert NO data files were modified
    assert tx_file.read_bytes() == tx_before
    assert bills_file.read_bytes() == bills_before
    assert budgets_file.read_bytes() == budgets_before


def test_bad_amount_future_date_unknown_category_return_errors(workspace_env):
    """Verify that a bad amount, a future date, and an unknown category each return an error."""
    ws = workspace_env
    df_tx = read_csv("transactions.csv", workspace=ws)
    first_id = str(df_tx["id"].iloc[0])

    # A. Bad amount cases
    bad_amounts = [-15.0, 0.0, 100001.0, "not_a_number", 25.555]
    for bad_amt in bad_amounts:
        res = propose_add_transactions([{
            "date": "2026-07-10",
            "description": "Test",
            "amount": bad_amt,
            "category": "Dining",
            "type": "expense",
        }])
        data = json.loads(res)
        assert data.get("status") == "error" or "error" in data

        res_upd = propose_update_transaction(first_id, {"amount": bad_amt})
        data_upd = json.loads(res_upd)
        assert data_upd.get("status") == "error" or "error" in data_upd

        res_bill = propose_bill_change(action="add", bill_name="Bad Bill", amount=bad_amt, due_day=5, category="Utilities")
        data_bill = json.loads(res_bill)
        assert data_bill.get("status") == "error" or "error" in data_bill

    # B. Future date cases (sandbox_today is 2026-08-31)
    future_dates = ["2026-09-01", "2027-01-01", "2030-12-31"]
    for fut_date in future_dates:
        res = propose_add_transactions([{
            "date": fut_date,
            "description": "Future Coffee",
            "amount": 5.0,
            "category": "Dining",
            "type": "expense",
        }])
        data = json.loads(res)
        assert "error" in data
        assert "cannot be after sandbox date" in data["error"]

        res_upd = propose_update_transaction(first_id, {"date": fut_date})
        data_upd = json.loads(res_upd)
        assert "error" in data_upd
        assert "cannot be after sandbox date" in data_upd["error"]

    # C. Unknown category cases
    unknown_categories = ["Cryptocurrency", "NonExistentCat", "LuxuryYachts"]
    for unk_cat in unknown_categories:
        res = propose_add_transactions([{
            "date": "2026-07-10",
            "description": "Unknown Expense",
            "amount": 50.0,
            "category": unk_cat,
            "type": "expense",
        }])
        data = json.loads(res)
        assert "error" in data
        assert "invalid" in data["error"].lower()

        res_upd = propose_update_transaction(first_id, {"category": unk_cat})
        data_upd = json.loads(res_upd)
        assert "error" in data_upd
        assert "invalid" in data_upd["error"].lower()

        res_bill = propose_bill_change(action="add", bill_name="Unk Bill", amount=50.0, due_day=10, category=unk_cat)
        data_bill = json.loads(res_bill)
        assert "error" in data_bill
        assert "invalid" in data_bill["error"].lower()

        # In propose_budget_change without action='add', unknown category returns error
        res_bgt = propose_budget_change(unk_cat, 200.0)
        data_bgt = json.loads(res_bgt)
        assert "error" in data_bgt


def test_duplicate_warning_in_propose_add_transactions(workspace_env):
    """Verify a possible_duplicate warning appears when adding an identical transaction."""
    ws = workspace_env
    # Seed data has '2026-06-05', 'Dining', 'Chipotle Lunch', 'expense', 16.5
    res = propose_add_transactions([{
        "date": "2026-06-05",
        "description": "Chipotle Lunch",
        "amount": 16.5,
        "category": "Dining",
        "type": "expense",
    }])
    data = json.loads(res)
    assert data["status"] == "pending_confirmation"
    assert data["preview"]["possible_duplicate"] is True
    assert "warning" in data["preview"]

    # Non-duplicate item
    res_clean = propose_add_transactions([{
        "date": "2026-06-05",
        "description": "Completely Unique Coffee Shop",
        "amount": 16.5,
        "category": "Dining",
        "type": "expense",
    }])
    data_clean = json.loads(res_clean)
    assert data_clean["preview"].get("possible_duplicate") is not True


def test_risk_levels_and_flagging(workspace_env):
    """Verify risk levels: delete is high, bill cancel is high, large update is high, others are low."""
    ws = workspace_env
    df_tx = read_csv("transactions.csv", workspace=ws)
    first_row = df_tx.iloc[0]
    first_id = str(first_row["id"])
    orig_amt = float(first_row["amount"])

    # Delete transaction is always HIGH risk
    res_del = propose_delete_transaction(first_id)
    data_del = json.loads(res_del)
    assert data_del["risk"] == "high"

    # Bill cancel is HIGH risk
    res_cancel = propose_bill_change(action="cancel", bill_name="Apartment Rent")
    data_cancel = json.loads(res_cancel)
    assert data_cancel["risk"] == "high"

    # Bill add and edit are LOW risk
    res_bill_add = propose_bill_change(action="add", bill_name="Trash Service", amount=25.0, due_day=15, category="Utilities")
    assert json.loads(res_bill_add)["risk"] == "low"

    res_bill_edit = propose_bill_change(action="edit", bill_name="Apartment Rent", amount=1550.0)
    assert json.loads(res_bill_edit)["risk"] == "low"

    # Update transaction: amount change <= 500 is LOW risk
    res_upd_small = propose_update_transaction(first_id, {"amount": round(orig_amt + 50.0, 2)})
    assert json.loads(res_upd_small)["risk"] == "low"

    # Update transaction: amount change > 500 is HIGH risk
    res_upd_large = propose_update_transaction(first_id, {"amount": round(orig_amt + 600.0, 2)})
    assert json.loads(res_upd_large)["risk"] == "high"

    # Add transactions is LOW risk
    res_add = propose_add_transactions([{
        "date": "2026-07-20",
        "description": "Office Supplies",
        "amount": 45.0,
        "category": "Shopping",
        "type": "expense",
    }])
    assert json.loads(res_add)["risk"] == "low"


def test_expires_at_is_24_hours_after_created_at(workspace_env):
    """Verify proposal expires_at is exactly 24 hours after created_at."""
    ws = workspace_env
    res = propose_add_transactions([{
        "date": "2026-07-20",
        "description": "Lunch at Deli",
        "amount": 14.50,
        "category": "Dining",
        "type": "expense",
    }])
    p_id = json.loads(res)["proposal_id"]

    props = read_proposals(workspace=ws)
    proposal = props[p_id]

    created = datetime.fromisoformat(proposal["created_at"])
    expires = datetime.fromisoformat(proposal["expires_at"])
    assert expires - created == timedelta(hours=24)


def test_model_cannot_call_any_apply_function():
    """Verify check_permission returns False for every apply function, and no apply tool is available."""
    assert check_permission("apply_budget_change") is False
    assert check_permission("apply_add_transactions") is False
    assert check_permission("apply_update_transaction") is False
    assert check_permission("apply_delete_transaction") is False
    assert check_permission("apply_bill_change") is False
    assert check_permission("arbitrary_tool_apply") is False

    # Check permission tiers
    for name, tier in TOOL_TIERS.items():
        assert tier != Tier.APPLY, f"Tool '{name}' must not have Tier.APPLY"

    # Check tools exposed to model
    for schema in TOOL_SCHEMAS:
        assert not schema["name"].startswith("apply_")

    for name in TOOLS_BY_NAME:
        assert not name.startswith("apply_")


def test_missing_or_ambiguous_fields_return_needs_clarification(workspace_env):
    """Verify propose_add_transactions returns status 'needs_clarification' with missing and options."""
    # Missing category
    res_no_cat = propose_add_transactions([{
        "date": "2026-07-10",
        "description": "Gas Station",
        "amount": 45.0,
        "type": "expense",
    }])
    data_no_cat = json.loads(res_no_cat)
    assert data_no_cat["status"] == "needs_clarification"
    assert "category" in data_no_cat["missing"]
    assert "category" in data_no_cat["options"]

    # Missing type
    res_no_type = propose_add_transactions([{
        "date": "2026-07-10",
        "description": "Freelance Client Payment",
        "amount": 800.0,
        "category": "Other",
    }])
    data_no_type = json.loads(res_no_type)
    assert data_no_type["status"] == "needs_clarification"
    assert "type" in data_no_type["missing"]
    assert data_no_type["options"]["type"] == ["expense", "income"]

    # Ambiguous type (not expense or income)
    res_ambig = propose_add_transactions([{
        "date": "2026-07-10",
        "description": "Transfer to Savings",
        "amount": 200.0,
        "category": "Other",
        "type": "transfer",
    }])
    data_ambig = json.loads(res_ambig)
    assert data_ambig["status"] == "needs_clarification"
    assert "type" in data_ambig["missing"]
    assert "options" in data_ambig


def test_extended_propose_budget_change(workspace_env):
    """Verify propose_budget_change extensions:
    - Create new category (limit between 1 and 10000, no 2x cap)
    - Remove category
    - Preserves existing 2x cap for updates
    - Preserves exact output keys
    """
    ws = workspace_env

    # 1. Create new category with action='add'
    res_add = propose_budget_change("Pet Care", 450.0, action="add")
    data_add = json.loads(res_add)
    assert data_add["status"] == "pending_confirmation"
    assert data_add["category"] == "Pet Care"
    assert data_add["old_limit"] is None
    assert data_add["new_limit"] == 450.0
    assert "proposal_id" in data_add

    # Create new category beyond 10000 rejected
    res_over = propose_budget_change("Luxury Space Travel", 15000.0, action="add")
    data_over = json.loads(res_over)
    assert "error" in data_over

    # Create new category below 1 rejected
    res_under = propose_budget_change("Micro Cents", 0.5, action="add")
    data_under = json.loads(res_under)
    assert "error" in data_under

    # 2. Remove category with action='remove'
    res_rem = propose_budget_change("Dining", action="remove")
    data_rem = json.loads(res_rem)
    assert data_rem["status"] == "pending_confirmation"
    assert data_rem["category"] == "Dining"
    assert data_rem["old_limit"] == 300.0
    assert data_rem["new_limit"] == 0.0
    props = read_proposals(workspace=ws)
    assert props[data_rem["proposal_id"]]["risk"] == "high"

    # 3. Existing 2x cap preserved for updates
    # Dining old limit is 300, max allowed is 600
    res_exceed = propose_budget_change("Dining", 650.0)
    data_exceed = json.loads(res_exceed)
    assert data_exceed["status"] == "rejected"
    assert "error" in data_exceed
    assert data_exceed["category"] == "Dining"
    assert data_exceed["current_limit"] == 300.0
    assert data_exceed["maximum_allowed"] == 600.0


def test_pending_command_in_active_workspace(workspace_env, capsys):
    """Verify /pending command reads proposals from the active workspace."""
    ws = workspace_env
    # Create proposal in workspace
    propose_budget_change("Health", 150.0)

    # Call handle_pending_command
    handle_pending_command(workspace=ws)
    captured = capsys.readouterr().out
    assert "Pending Proposals:" in captured
    assert "Health" in captured

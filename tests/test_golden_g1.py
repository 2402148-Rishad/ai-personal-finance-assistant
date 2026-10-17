"""Integration tests for Phase 2.4: Golden demo scenarios G1 and G2.

Verifies:
1. Scenario G1:
   a. propose_add_transactions with one $45 dining expense, approved with 'yes'.
   b. propose_update_transaction to move that expense from Dining to Groceries, approved with 'yes'.
   c. cashflow_projection for next 30 days returns lowest_balance and lowest_balance_date.
   d. propose_budget_change to set Dining to 250, then reject it.
   e. Assertions:
      - budgets.json is unchanged from the seed
      - the 45 expense is in transactions.csv with category Groceries
      - audit.jsonl has the add, update, and reject entries
      - proposals.json has no pending entry for the rejected change
   f. Run undo once and assert update is reverted and expense is back in Dining.
2. Scenario G2:
   propose_add_transactions with three items ('lunch 12', 'bus 3', 'coffee 4'),
   one approve_all call with 'yes', and assert monthly total rose by exactly 19.
"""

import json
from pathlib import Path
import pytest
import pandas as pd

import src.tools as tools_module
from src.tools import (
    propose_add_transactions,
    propose_update_transaction,
    propose_budget_change,
    cashflow_projection,
    get_monthly_summary,
)
import src.approvals as approvals_module
from src.approvals import (
    approve,
    reject,
    approve_all,
    undo,
    list_pending,
)
from src.store import (
    create_workspace,
    read_json,
    read_csv,
    read_audit,
    read_proposals,
)


@pytest.fixture
def workspace_env(tmp_path, monkeypatch):
    """Create an isolated workspace from seed data and point all data and logs to it."""
    ws = create_workspace("session_test_golden_g1", base_dir=tmp_path)
    monkeypatch.setenv("FINANCE_DATA_DIR", str(ws))
    monkeypatch.setattr(tools_module, "LOGS_DIR", ws)
    monkeypatch.setattr(tools_module, "PROPOSALS_PATH", ws / "pending_proposals.json")
    monkeypatch.setattr(approvals_module, "LOGS_DIR", ws)
    monkeypatch.setattr(approvals_module, "PROPOSALS_PATH", ws / "pending_proposals.json")
    return ws


def test_golden_scenario_g1(workspace_env):
    """Execute golden demo scenario G1 end-to-end through the Python API."""
    ws = workspace_env

    # Capture initial seed budgets
    budgets_seed = read_json("budgets.json", workspace=ws)

    # a. propose_add_transactions with one $45 dining expense, then approve it with "yes"
    res_add = propose_add_transactions([
        {
            "date": "2026-08-15",
            "description": "Dinner at Bistro",
            "amount": 45.0,
            "category": "Dining",
            "type": "expense",
        }
    ])
    data_add = json.loads(res_add)
    assert data_add.get("status") == "pending_confirmation", f"Expected pending_confirmation, got {data_add}"
    p_add_id = data_add["proposal_id"]

    appr_add = approve(p_add_id, "yes", workspace=ws)
    assert appr_add.get("status") == "applied", f"Expected applied, got {appr_add}"

    # Locate the newly created transaction ID
    df_tx = read_csv("transactions.csv", workspace=ws)
    matches = df_tx[(df_tx["description"] == "Dinner at Bistro") & (df_tx["amount"] == 45.0)]
    assert len(matches) == 1, "Expected exactly one matching transaction for Dinner at Bistro"
    tx_id = str(matches.iloc[0]["id"])
    assert matches.iloc[0]["category"] == "Dining"

    # b. propose_update_transaction to move that expense from Dining to Groceries, then approve it with "yes"
    res_upd = propose_update_transaction(tx_id, {"category": "Groceries"})
    data_upd = json.loads(res_upd)
    assert data_upd.get("status") == "pending_confirmation", f"Expected pending_confirmation, got {data_upd}"
    p_upd_id = data_upd["proposal_id"]

    appr_upd = approve(p_upd_id, "yes", workspace=ws)
    assert appr_upd.get("status") == "applied", f"Expected applied, got {appr_upd}"

    # Verify transaction is now Groceries
    df_tx_b = read_csv("transactions.csv", workspace=ws)
    tx_b = df_tx_b[df_tx_b["id"].astype(str) == tx_id].iloc[0]
    assert tx_b["category"] == "Groceries"

    # c. cashflow_projection for the next 30 days, and assert the response has lowest_balance and lowest_balance_date
    res_cf = cashflow_projection(days_ahead=30)
    data_cf = json.loads(res_cf)
    assert "lowest_balance" in data_cf, "Expected lowest_balance in cashflow projection"
    assert "lowest_balance_date" in data_cf, "Expected lowest_balance_date in cashflow projection"
    assert data_cf["lowest_balance"] is not None
    assert data_cf["lowest_balance_date"] is not None

    # d. propose_budget_change to set Dining to 250, then reject it
    res_bgt = propose_budget_change("Dining", 250.0)
    data_bgt = json.loads(res_bgt)
    assert data_bgt.get("status") == "pending_confirmation", f"Expected pending_confirmation, got {data_bgt}"
    p_bgt_id = data_bgt["proposal_id"]

    rej_bgt = reject(p_bgt_id, workspace=ws)
    assert rej_bgt.get("status") == "rejected", f"Expected rejected, got {rej_bgt}"

    # e. Assertions:
    # 1. budgets.json is unchanged from the seed
    budgets_current = read_json("budgets.json", workspace=ws)
    assert budgets_current == budgets_seed, "budgets.json should remain identical to seed"

    # 2. the 45 expense is in transactions.csv with category Groceries
    df_tx_e = read_csv("transactions.csv", workspace=ws)
    matches_e = df_tx_e[df_tx_e["id"].astype(str) == tx_id]
    assert len(matches_e) == 1
    tx_e = matches_e.iloc[0]
    assert tx_e["category"] == "Groceries"
    assert float(tx_e["amount"]) == 45.0

    # 3. audit.jsonl has the add, the update and the reject entries
    audit_records = read_audit(workspace=ws)
    has_add_entry = any(
        (r.get("action") in ("approve_add_transactions", "apply_proposal") or r.get("kind") == "add_transactions" or "add" in str(r.get("action"))) and
        (r.get("proposal_id") == p_add_id or r.get("after", {}).get("kind") == "add_transactions")
        for r in audit_records
    )
    assert has_add_entry, f"audit.jsonl missing add entry. Audit records: {audit_records}"

    has_upd_entry = any(
        (r.get("action") in ("approve_update_transaction", "apply_proposal") or r.get("kind") == "update_transaction" or "update" in str(r.get("action"))) and
        (r.get("proposal_id") == p_upd_id or r.get("after", {}).get("kind") == "update_transaction")
        for r in audit_records
    )
    assert has_upd_entry, f"audit.jsonl missing update entry. Audit records: {audit_records}"

    has_rej_entry = any(
        (r.get("action") == "reject_proposal" or "reject" in str(r.get("action"))) and
        (r.get("proposal_id") == p_bgt_id or r.get("before", {}).get("proposal_id") == p_bgt_id)
        for r in audit_records
    )
    assert has_rej_entry, f"audit.jsonl missing reject entry. Audit records: {audit_records}"

    # 4. proposals.json has no pending entry for the rejected change
    props = read_proposals(workspace=ws)
    assert p_bgt_id not in props or props[p_bgt_id].get("status") != "pending_confirmation"
    pending_list = list_pending(workspace=ws)
    assert not any(p.get("id") == p_bgt_id or p.get("proposal_id") == p_bgt_id for p in pending_list)

    # f. Run undo once and assert the update is reverted, and the expense is back in Dining
    undo_res = undo(workspace=ws)
    assert undo_res.get("status") == "undone", f"Expected undone, got {undo_res}"

    df_tx_f = read_csv("transactions.csv", workspace=ws)
    matches_f = df_tx_f[df_tx_f["id"].astype(str) == tx_id]
    assert len(matches_f) == 1
    tx_f = matches_f.iloc[0]
    assert tx_f["category"] == "Dining", f"Expected category Dining after undo, got {tx_f['category']}"
    assert float(tx_f["amount"]) == 45.0


def test_golden_scenario_g2(tmp_path, monkeypatch):
    """Execute golden demo scenario G2 through the Python API:
    propose_add_transactions with three items ('lunch 12', 'bus 3', 'coffee 4'),
    one approve_all call with 'yes', and assert the monthly total rose by exactly 19.
    """
    ws = create_workspace("session_test_golden_g2", base_dir=tmp_path)
    monkeypatch.setenv("FINANCE_DATA_DIR", str(ws))
    monkeypatch.setattr(tools_module, "LOGS_DIR", ws)
    monkeypatch.setattr(tools_module, "PROPOSALS_PATH", ws / "pending_proposals.json")
    monkeypatch.setattr(approvals_module, "LOGS_DIR", ws)
    monkeypatch.setattr(approvals_module, "PROPOSALS_PATH", ws / "pending_proposals.json")

    target_month = "2026-08"

    # 1. Baseline monthly expense total from tool and direct CSV
    summary_before = json.loads(get_monthly_summary(month=target_month))
    expenses_before = float(summary_before["total_expenses"])

    df_before = read_csv("transactions.csv", workspace=ws)
    df_aug_before = df_before[(df_before["month"] == target_month) & (df_before["type"] == "expense")]
    df_total_before = float(df_aug_before["amount"].sum())
    assert round(expenses_before, 2) == round(df_total_before, 2)

    # 2. propose_add_transactions with three items:
    # "lunch 12", "bus 3", "coffee 4"
    items = [
        {
            "date": "2026-08-16",
            "description": "lunch",
            "amount": 12.0,
            "category": "Dining",
            "type": "expense",
        },
        {
            "date": "2026-08-16",
            "description": "bus",
            "amount": 3.0,
            "category": "Transport",
            "type": "expense",
        },
        {
            "date": "2026-08-16",
            "description": "coffee",
            "amount": 4.0,
            "category": "Dining",
            "type": "expense",
        },
    ]

    res_add = propose_add_transactions(items)
    data_add = json.loads(res_add)
    assert data_add.get("status") == "pending_confirmation"
    prop_id = data_add["proposal_id"]

    # Verify pending
    pending_before = list_pending(workspace=ws)
    assert any(p.get("id") == prop_id or p.get("proposal_id") == prop_id for p in pending_before)

    # 3. One approve_all call with "yes"
    appr_res = approve_all("yes", workspace=ws)
    assert appr_res.get("status") == "applied"
    assert prop_id in appr_res.get("approved", [])

    # 4. Assert monthly total rose by exactly 19
    summary_after = json.loads(get_monthly_summary(month=target_month))
    expenses_after = float(summary_after["total_expenses"])
    assert round(expenses_after - expenses_before, 2) == 19.00, (
        f"Expected monthly expenses to rise by 19.00, from {expenses_before} to {expenses_after}"
    )

    df_after = read_csv("transactions.csv", workspace=ws)
    df_aug_after = df_after[(df_after["month"] == target_month) & (df_after["type"] == "expense")]
    df_total_after = float(df_aug_after["amount"].sum())
    assert round(df_total_after - df_total_before, 2) == 19.00

    # Verify each item was added
    for it in items:
        matched = df_after[(df_after["description"] == it["description"]) & (df_after["amount"] == it["amount"])]
        assert len(matched) >= 1, f"Missing added item {it['description']}"

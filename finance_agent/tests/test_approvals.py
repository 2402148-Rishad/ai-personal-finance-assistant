"""Unit tests for Phase 2.2: Approvals Engine.

Verifies:
1. Exact 'yes' only for low-risk proposals; other strings fail.
2. 'CONFIRM' needed for high-risk proposals; other strings fail.
3. Reject removes proposal, changes no data files, and logs audit record.
4. Undo restores an add (both transaction add and budget add).
5. Undo of an undo is refused.
6. Expired proposals are refused and marked as expired in list_pending.
7. An audit line exists for every applied, rejected, and undone action.
8. Approve_all applies unexpired low-risk proposals and skips high-risk ones.
9. Permission test: approve, reject, undo are not in TOOL_TIERS or TOOL_SCHEMAS.
10. Approvals engine never calls input() or print().
"""

from datetime import datetime, timedelta
import json
from pathlib import Path
import pytest
import pandas as pd
from unittest.mock import MagicMock

from src.permissions import check_permission, TOOL_TIERS, Tier
from src.tools import TOOL_SCHEMAS, TOOLS_BY_NAME
import src.tools as tools_module
from src.store import (
    create_workspace,
    read_proposals,
    read_audit,
    read_csv,
    read_json,
    write_json_atomic,
)
from src.approvals import (
    list_pending,
    approve,
    reject,
    approve_all,
    undo,
    request_approval,
    confirm_approval,
)


@pytest.fixture
def workspace_env(tmp_path, monkeypatch):
    """Create an isolated workspace from seed data and point FINANCE_DATA_DIR to it."""
    ws = create_workspace("session_test_approvals", base_dir=tmp_path)
    monkeypatch.setenv("FINANCE_DATA_DIR", str(ws))
    monkeypatch.setattr(tools_module, "LOGS_DIR", ws)
    monkeypatch.setattr(tools_module, "PROPOSALS_PATH", ws / "pending_proposals.json")
    return ws


def test_permission_approvals_not_in_tool_tiers_or_schemas():
    """Verify approve, reject, undo, and approvals functions are not exposed to the model."""
    prohibited_names = [
        "approve",
        "reject",
        "undo",
        "approve_all",
        "list_pending",
        "confirm_approval",
        "request_approval",
    ]

    for name in prohibited_names:
        assert name not in TOOL_TIERS, f"'{name}' must not be in TOOL_TIERS"
        assert check_permission(name) is False, f"check_permission('{name}') must return False"
        assert name not in TOOLS_BY_NAME, f"'{name}' must not be in TOOLS_BY_NAME"

    for schema in TOOL_SCHEMAS:
        assert schema["name"] not in prohibited_names, f"'{schema['name']}' must not be in TOOL_SCHEMAS"


def test_exact_yes_only_for_low_risk(workspace_env):
    """Verify that low-risk proposals apply ONLY when answer is exactly 'yes'."""
    ws = workspace_env
    # Create low-risk proposal
    res = tools_module.propose_budget_change("Dining", 350.0)
    p_id = json.loads(res)["proposal_id"]

    budgets_file = ws / "budgets.json"
    before_bytes = budgets_file.read_bytes()

    # Non-exact answers must fail
    invalid_answers = ["YES", "Yes", "y", "CONFIRM", "true", "1", "yes ", " yes", "ok"]
    for ans in invalid_answers:
        out = approve(p_id, ans, workspace=ws)
        assert out.get("status") == "error"
        assert "yes" in out.get("error", "").lower()
        # Budgets file unchanged
        assert budgets_file.read_bytes() == before_bytes
        # Proposal still in pending
        pending = list_pending(workspace=ws)
        assert any(p["id"] == p_id for p in pending)

    # Exact 'yes' succeeds
    valid_out = approve(p_id, "yes", workspace=ws)
    assert valid_out["status"] == "applied"
    assert valid_out["new_limit"] == 350.0

    # Budgets updated
    budgets = read_json("budgets.json", workspace=ws)
    assert budgets["Dining"] == 350.0

    # Proposal removed from pending
    pending_after = list_pending(workspace=ws)
    assert not any(p["id"] == p_id for p in pending_after)


def test_confirm_needed_for_high_risk(workspace_env):
    """Verify that high-risk proposals require answer exactly 'CONFIRM'."""
    ws = workspace_env
    df_tx = read_csv("transactions.csv", workspace=ws)
    first_id = str(df_tx["id"].iloc[0])

    # Delete transaction is always high risk
    res_del = tools_module.propose_delete_transaction(first_id)
    p_id = json.loads(res_del)["proposal_id"]

    tx_file = ws / "transactions.csv"
    before_bytes = tx_file.read_bytes()

    # 'yes' or lowercase 'confirm' must fail on high-risk
    invalid_answers = ["yes", "YES", "confirm", "Confirm", " true ", "CONFIRM ", "y"]
    for ans in invalid_answers:
        out = approve(p_id, ans, workspace=ws)
        assert out.get("status") == "error"
        assert "CONFIRM" in out.get("error", "")
        # File unchanged
        assert tx_file.read_bytes() == before_bytes
        # Proposal still in pending
        pending = list_pending(workspace=ws)
        assert any(p["id"] == p_id for p in pending)

    # Exact 'CONFIRM' succeeds
    valid_out = approve(p_id, "CONFIRM", workspace=ws)
    assert valid_out["status"] == "applied"

    # Transaction removed from transactions.csv
    df_tx_after = read_csv("transactions.csv", workspace=ws)
    assert not (df_tx_after["id"].astype(str) == first_id).any()


def test_reject_changes_nothing(workspace_env):
    """Verify reject removes proposal from pending, writes an audit record, and modifies no data files."""
    ws = workspace_env
    tx_file = ws / "transactions.csv"
    bills_file = ws / "bills.csv"
    budgets_file = ws / "budgets.json"

    tx_before = tx_file.read_bytes()
    bills_before = bills_file.read_bytes()
    budgets_before = budgets_file.read_bytes()

    res = tools_module.propose_add_transactions([{
        "date": "2026-07-15",
        "description": "Reject Test Item",
        "amount": 99.0,
        "category": "Dining",
        "type": "expense",
    }])
    p_id = json.loads(res)["proposal_id"]

    # Reject proposal
    rej_out = reject(p_id, workspace=ws)
    assert rej_out["status"] == "rejected"
    assert rej_out["proposal_id"] == p_id

    # Verify no data files changed
    assert tx_file.read_bytes() == tx_before
    assert bills_file.read_bytes() == bills_before
    assert budgets_file.read_bytes() == budgets_before

    # Verify proposal is gone from pending
    pending = list_pending(workspace=ws)
    assert not any(p["id"] == p_id for p in pending)

    # Verify audit record written
    records = read_audit(workspace=ws)
    assert any(
        r.get("action") == "reject_proposal" and r.get("source") == "human"
        for r in records
    )


def test_undo_restores_an_add(workspace_env):
    """Verify undo reverts the most recent human-applied action, restoring an add."""
    ws = workspace_env
    df_tx_orig = read_csv("transactions.csv", workspace=ws)
    orig_count = len(df_tx_orig)

    # 1. Propose add transaction
    res = tools_module.propose_add_transactions([{
        "date": "2026-07-22",
        "description": "Unique Add For Undo",
        "amount": 42.75,
        "category": "Shopping",
        "type": "expense",
    }])
    p_id = json.loads(res)["proposal_id"]

    # 2. Approve add
    appr_res = approve(p_id, "yes", workspace=ws)
    assert appr_res["status"] == "applied"
    undo_token = appr_res["undo_token"]
    assert undo_token

    df_tx_added = read_csv("transactions.csv", workspace=ws)
    assert len(df_tx_added) == orig_count + 1
    assert (df_tx_added["description"] == "Unique Add For Undo").any()

    # 3. Undo add
    undo_res = undo(workspace=ws)
    assert undo_res["status"] == "undone"
    assert undo_res["undone_token"] == undo_token

    # 4. Verify transaction table is restored
    df_tx_restored = read_csv("transactions.csv", workspace=ws)
    assert len(df_tx_restored) == orig_count
    assert not (df_tx_restored["description"] == "Unique Add For Undo").any()

    # 5. Test undo on budget category addition
    bgt_orig = read_json("budgets.json", workspace=ws)
    assert "Pet Supplies" not in bgt_orig

    res_bgt = tools_module.propose_budget_change("Pet Supplies", 120.0, action="add")
    p_bgt_id = json.loads(res_bgt)["proposal_id"]

    approve(p_bgt_id, "yes", workspace=ws)
    assert read_json("budgets.json", workspace=ws)["Pet Supplies"] == 120.0

    # Undo budget addition
    undo_bgt = undo(workspace=ws)
    assert undo_bgt["status"] == "undone"
    assert "Pet Supplies" not in read_json("budgets.json", workspace=ws)


def test_undo_of_an_undo_is_refused(workspace_env):
    """Verify calling undo when the last action was already undone is refused (undo of an undo is refused)."""
    ws = workspace_env
    res = tools_module.propose_budget_change("Dining", 340.0)
    p_id = json.loads(res)["proposal_id"]

    approve(p_id, "yes", workspace=ws)
    assert read_json("budgets.json", workspace=ws)["Dining"] == 340.0

    # First undo succeeds
    res_undo1 = undo(workspace=ws)
    assert res_undo1["status"] == "undone"
    assert read_json("budgets.json", workspace=ws)["Dining"] == 300.0

    # Second undo must be refused (cannot undo the undo, and no other actions left)
    res_undo2 = undo(workspace=ws)
    assert res_undo2.get("status") in ("refused", "error")
    assert "refused" in res_undo2.get("error", "").lower() or "nothing" in res_undo2.get("message", "").lower()
    # Budgets remain in the restored state
    assert read_json("budgets.json", workspace=ws)["Dining"] == 300.0


def test_expired_proposals_are_refused(workspace_env):
    """Verify proposals older than 24 hours cannot be approved and are marked expired."""
    ws = workspace_env
    res = tools_module.propose_budget_change("Dining", 360.0)
    p_id = json.loads(res)["proposal_id"]

    # Manually expire the proposal by setting expires_at to 2 hours in the past
    props = read_proposals(workspace=ws)
    props[p_id]["expires_at"] = (datetime.now() - timedelta(hours=2)).isoformat()
    write_json_atomic("proposals.json", props, workspace=ws)

    # list_pending marks it expired and excludes it
    pending = list_pending(workspace=ws)
    assert not any(p["id"] == p_id for p in pending)

    props_after = read_proposals(workspace=ws)
    assert props_after[p_id]["status"] == "expired"

    # Approving expired proposal is refused
    appr_res = approve(p_id, "yes", workspace=ws)
    assert appr_res.get("status") == "error"
    assert "expired" in appr_res.get("error", "").lower()

    # Budgets unchanged
    assert read_json("budgets.json", workspace=ws)["Dining"] == 300.0


def test_audit_line_exists_for_every_applied_and_undone_action(workspace_env):
    """Verify an audit line with source 'human' and undo_token exists for every applied and undone action."""
    ws = workspace_env
    initial_audit_count = len(read_audit(workspace=ws))

    # 1. Applied action (add proposal)
    res = tools_module.propose_add_transactions([{
        "date": "2026-07-25",
        "description": "Audit Test Item",
        "amount": 20.0,
        "category": "Dining",
        "type": "expense",
    }])
    p_id = json.loads(res)["proposal_id"]
    appr_res = approve(p_id, "yes", workspace=ws)
    assert appr_res["status"] == "applied"

    records = read_audit(workspace=ws)
    assert len(records) == initial_audit_count + 1
    rec_applied = records[-1]
    assert rec_applied["source"] == "human"
    assert rec_applied["undo_token"] == appr_res["undo_token"]
    assert "before" in rec_applied
    assert "after" in rec_applied
    assert "timestamp" in rec_applied

    # 2. Undone action
    undo_res = undo(workspace=ws)
    assert undo_res["status"] == "undone"

    records_after_undo = read_audit(workspace=ws)
    assert len(records_after_undo) == initial_audit_count + 2
    rec_undo = records_after_undo[-1]
    assert rec_undo["action"] == "undo"
    assert rec_undo["source"] == "human"
    assert rec_undo["undone_token"] == appr_res["undo_token"]


def test_approve_all_applies_low_risk_and_skips_high_risk(workspace_env):
    """Verify approve_all applies all low-risk proposals and skips high-risk ones."""
    ws = workspace_env
    df_tx = read_csv("transactions.csv", workspace=ws)
    first_id = str(df_tx["id"].iloc[0])

    # Low risk proposal 1: budget change
    res1 = tools_module.propose_budget_change("Dining", 350.0)
    p1 = json.loads(res1)["proposal_id"]

    # Low risk proposal 2: add bill
    res2 = tools_module.propose_bill_change(
        action="add",
        bill_name="Water Bill",
        amount=30.0,
        due_day=20,
        category="Utilities",
    )
    p2 = json.loads(res2)["proposal_id"]

    # High risk proposal: delete transaction
    res3 = tools_module.propose_delete_transaction(first_id)
    p3 = json.loads(res3)["proposal_id"]

    # approve_all requires exact 'yes'
    res_bad = approve_all("YES", workspace=ws)
    assert res_bad.get("status") == "error"

    # approve_all with 'yes'
    res_all = approve_all("yes", workspace=ws)
    assert res_all["status"] == "applied"
    assert p1 in res_all["approved"]
    assert p2 in res_all["approved"]
    assert p3 in res_all["skipped_high_risk"]

    # Low risk changes took effect
    assert read_json("budgets.json", workspace=ws)["Dining"] == 350.0
    df_bills = read_csv("bills.csv", workspace=ws)
    assert (df_bills["bill_name"].str.lower() == "water bill").any()

    # High risk delete proposal is STILL pending
    pending = list_pending(workspace=ws)
    assert any(p["id"] == p3 for p in pending)
    df_tx_after = read_csv("transactions.csv", workspace=ws)
    assert (df_tx_after["id"].astype(str) == first_id).any()


def test_approvals_module_never_calls_input_or_print(workspace_env, monkeypatch):
    """Verify no function in approvals ever calls input() or print()."""
    ws = workspace_env
    mock_input = MagicMock(side_effect=AssertionError("input() was called in approvals module!"))
    mock_print = MagicMock(side_effect=AssertionError("print() was called in approvals module!"))
    monkeypatch.setattr("builtins.input", mock_input)
    monkeypatch.setattr("builtins.print", mock_print)

    # 1. list_pending
    list_pending(workspace=ws)

    # 2. propose & request_approval
    res = tools_module.propose_budget_change("Dining", 330.0)
    p_id = json.loads(res)["proposal_id"]
    req = request_approval(p_id, workspace=ws)
    assert req["status"] == "awaiting_approval"

    # 3. confirm_approval wrapper
    conf_cancel = confirm_approval(p_id, "no", workspace=ws)
    assert conf_cancel["status"] == "cancelled"

    # 4. approve
    appr = approve(p_id, "yes", workspace=ws)
    assert appr["status"] == "applied"

    # 5. undo
    und = undo(workspace=ws)
    assert und["status"] == "undone"

    # 6. reject
    res2 = tools_module.propose_budget_change("Dining", 320.0)
    p2_id = json.loads(res2)["proposal_id"]
    rej = reject(p2_id, workspace=ws)
    assert rej["status"] == "rejected"

    mock_input.assert_not_called()
    mock_print.assert_not_called()


def test_confirm_approval_refuses_high_risk_on_yes(workspace_env):
    """Verify that confirm_approval(id, 'yes') refuses high-risk proposals."""
    ws = workspace_env
    df_tx = read_csv("transactions.csv", workspace=ws)
    first_id = str(df_tx["id"].iloc[0])

    # Delete transaction is high risk
    res_del = tools_module.propose_delete_transaction(first_id)
    p_id = json.loads(res_del)["proposal_id"]

    # confirm_approval with 'yes' on high-risk proposal must be refused
    res = confirm_approval(p_id, "yes", workspace=ws)
    assert res.get("status") == "error"
    assert "CONFIRM" in res.get("error", "")

    # confirm_approval with 'CONFIRM' on high-risk proposal succeeds
    res_confirm = confirm_approval(p_id, "CONFIRM", workspace=ws)
    assert res_confirm.get("status") == "applied"

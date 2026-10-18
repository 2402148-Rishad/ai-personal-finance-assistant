"""Unit and integration tests for Phase 3.1: Session workspace, app shell, and Phase 2 fixes.

Verifies:
1. ContextVar active workspace in src/store.py (set_active_workspace, get_active_workspace) and reads/writes.
2. cleanup_old_workspaces deletes untouched workspaces older than 24 hours.
3. "Do this next" banner interim deterministic rules (checked in order):
   a. Pending proposals -> "N changes are waiting for approval. Open Inbox."
   b. Bill due within 3 days -> "<bill> is due <date>."
   c. Otherwise -> "Add today's expenses in Ledger, or ask Fin about your month."
4. budget_status returns percent_used as null (None) when limit is 0 without division error.
5. confirm_approval(id, 'yes') refuses high-risk proposals.
"""

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import pytest
import pandas as pd

from src.store import (
    create_workspace,
    reset_workspace,
    set_active_workspace,
    get_active_workspace,
    cleanup_old_workspaces,
    read_json,
    write_json_atomic,
    read_csv,
    get_data_dir,
    SEED_DATA_DIR,
    get_sandbox_today,
    set_sandbox_today,
)
from src.tools import (
    budget_status,
    propose_budget_change,
    propose_delete_transaction,
)
import src.tools as tools_module
import src.approvals as approvals_module
from src.approvals import (
    approve,
    confirm_approval,
    list_pending,
)
from src.banner import get_do_this_next_banner


@pytest.fixture
def workspace_env(tmp_path, monkeypatch):
    """Create an isolated workspace from seed data and point all data and logs to it."""
    ws = create_workspace("session_test_phase31", base_dir=tmp_path)
    monkeypatch.setenv("FINANCE_DATA_DIR", str(ws))
    monkeypatch.setattr(tools_module, "LOGS_DIR", ws)
    monkeypatch.setattr(tools_module, "PROPOSALS_PATH", ws / "pending_proposals.json")
    monkeypatch.setattr(approvals_module, "LOGS_DIR", ws)
    monkeypatch.setattr(approvals_module, "PROPOSALS_PATH", ws / "pending_proposals.json")
    return ws


def test_contextvar_active_workspace(tmp_path):
    """Verify set_active_workspace and get_active_workspace isolate workspace per context."""
    ws1 = create_workspace("session_ctx_1", base_dir=tmp_path)
    ws2 = create_workspace("session_ctx_2", base_dir=tmp_path)

    # Set active workspace to ws1
    set_active_workspace(ws1)
    assert get_active_workspace() == ws1
    assert get_data_dir() == ws1

    # Modify ws1 budgets.json
    b1 = read_json("budgets.json")
    b1["Dining"] = 999.0
    write_json_atomic("budgets.json", b1)

    # Switch active workspace to ws2
    set_active_workspace(ws2)
    assert get_active_workspace() == ws2
    assert get_data_dir() == ws2
    b2 = read_json("budgets.json")
    assert b2["Dining"] == 300.0  # Unmodified seed value

    # Clear contextvar
    set_active_workspace(None)
    assert get_active_workspace() is None


def test_cleanup_old_workspaces(tmp_path):
    """Verify cleanup_old_workspaces deletes directories older than 24h and retains newer ones."""
    ws_root = tmp_path / "workspaces"
    ws_root.mkdir(parents=True, exist_ok=True)

    old_ws = ws_root / "session_old_to_delete"
    old_ws.mkdir()
    (old_ws / "dummy.txt").write_text("old file", encoding="utf-8")

    new_ws = ws_root / "session_fresh_to_keep"
    new_ws.mkdir()
    (new_ws / "dummy.txt").write_text("new file", encoding="utf-8")

    # Set old_ws mtime to 30 hours ago
    old_time = (datetime.now() - timedelta(hours=30)).timestamp()
    os.utime(old_ws, (old_time, old_time))
    os.utime(old_ws / "dummy.txt", (old_time, old_time))

    deleted = cleanup_old_workspaces(max_age_hours=24, base_dir=ws_root)
    assert "session_old_to_delete" in deleted
    assert not old_ws.exists()
    assert new_ws.exists()


def test_budget_status_zero_limit_returns_null():
    """Verify budget_status returns percent_used as null when limit is 0 without division error."""
    # Build a simulated dictionary with limit 0
    from src.tools import budget_status
    # We test via the existing test in test_tools.py and confirm here as well
    # Using temporary workspace
    import tempfile
    import shutil
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws_zero"
        shutil.copytree(SEED_DATA_DIR, ws)
        bgts = json.loads((ws / "budgets.json").read_text(encoding="utf-8"))
        bgts["Transport"] = 0.0
        (ws / "budgets.json").write_text(json.dumps(bgts), encoding="utf-8")

        set_active_workspace(ws)
        try:
            raw = budget_status("2026-07")
            data = json.loads(raw)
            assert data["categories"]["Transport"]["limit"] == 0.0
            assert data["categories"]["Transport"]["percent_used"] is None
        finally:
            set_active_workspace(None)


def test_confirm_approval_refuses_high_risk_proposals(workspace_env):
    """Assert that confirm_approval(id, 'yes') refuses high-risk proposals."""
    ws = workspace_env
    df_tx = read_csv("transactions.csv", workspace=ws)
    first_id = str(df_tx["id"].iloc[0])

    # Deleting a transaction is high risk
    res_del = propose_delete_transaction(first_id)
    p_id = json.loads(res_del)["proposal_id"]

    # confirm_approval with 'yes' on high-risk proposal must be refused
    res_no = confirm_approval(p_id, "yes", workspace=ws)
    assert res_no.get("status") == "error"
    assert "CONFIRM" in res_no.get("error", "")

    # confirm_approval with 'CONFIRM' succeeds
    res_ok = confirm_approval(p_id, "CONFIRM", workspace=ws)
    assert res_ok.get("status") == "applied"


def test_do_this_next_banner_rules(workspace_env):
    """Verify the three deterministic rules of 'Do this next' banner checked in order."""
    ws = workspace_env
    set_active_workspace(ws)

    # Sandbox date: 2026-08-31
    # 1. Rule C: No pending proposals and no bills within 3 days (bills due on 1, 5, 10, 15, 18, 20)
    # Set sandbox date to 2026-08-25 where days 25, 26, 27, 28 have no bills due
    set_sandbox_today("2026-08-25", workspace=ws)
    banner_c = get_do_this_next_banner(workspace=ws)
    assert banner_c == "Add today's expenses in Ledger, or ask Fin about your month."

    # 2. Rule B: A bill is due within 3 days (e.g. Apartment Rent is due on 2026-09-01, 1 day after 2026-08-31)
    set_sandbox_today("2026-08-31", workspace=ws)
    banner_b = get_do_this_next_banner(workspace=ws)
    assert "Apartment Rent is due 2026-09-01." == banner_b

    # 3. Rule A: Pending proposal exists -> takes priority over bill due within 3 days
    res = propose_budget_change("Dining", 320.0)
    p_id = json.loads(res)["proposal_id"]
    banner_a = get_do_this_next_banner(workspace=ws)
    assert banner_a == "1 change is waiting for approval."

    set_active_workspace(None)

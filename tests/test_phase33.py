"""Tests for Phase 3.3: Plan and Inbox tabs, human approvals, budget/bill proposals, undo, and activity log."""

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src.approvals import list_pending, approve, reject, undo
from src.store import (
    create_workspace,
    set_active_workspace,
    read_csv,
    read_json,
    read_proposals,
    read_audit,
    get_sandbox_today,
)
from src.tools import (
    propose_budget_change,
    propose_bill_change,
    propose_add_transactions,
)

APP_PATH = (Path(__file__).resolve().parent.parent / "app.py").resolve()


@pytest.fixture(autouse=True)
def clean_proposals_fixture():
    """Ensure no leftover proposals in legacy pending_proposals.json leak across tests."""
    from src.approvals import PROPOSALS_PATH
    yield
    if PROPOSALS_PATH and PROPOSALS_PATH.exists():
        try:
            with open(PROPOSALS_PATH, "w", encoding="utf-8") as f:
                json.dump({}, f)
        except Exception:
            pass


def test_apptest_budget_edit_creates_pending_card_and_leaves_budgets_unchanged():
    """AppTest: a budget edit creates a pending card and leaves budgets.json unchanged."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        budgets_before = read_json("budgets.json", workspace=app_ws)
        assert "Dining" in budgets_before
        dining_orig = budgets_before["Dining"]

        # Select Dining and enter new limit
        cat_select = next((s for s in at.selectbox if s.key == "edit_budget_category"), None)
        assert cat_select is not None
        if "Dining" in cat_select.options:
            cat_select.select("Dining")

        new_lim_input = at.text_input(key="edit_budget_new_limit")
        new_lim_input.input("345.00")

        edit_btn = next(b for b in at.button if b.key == "edit_budget_submit_btn")
        edit_btn.click().run()

        # Budgets.json must remain completely unchanged
        budgets_after = read_json("budgets.json", workspace=app_ws)
        assert budgets_before == budgets_after
        assert budgets_after["Dining"] == dining_orig

        # A pending proposal must exist
        pending = list_pending(workspace=app_ws)
        dining_props = [
            p for p in pending
            if p.get("category") == "Dining" or (isinstance(p.get("payload"), dict) and p.get("payload", {}).get("category") == "Dining")
        ]
        assert len(dining_props) >= 1
        p_id = str(dining_props[0].get("id") or dining_props[0].get("proposal_id"))

        # Proposal card must exist in the UI
        approve_btn = next((b for b in at.button if b.key == f"approve_btn_{p_id}"), None)
        assert approve_btn is not None
        reject_btn = next((b for b in at.button if b.key == f"reject_btn_{p_id}"), None)
        assert reject_btn is not None


def test_apptest_high_risk_approve_stays_disabled_until_confirm():
    """AppTest: the high-risk Approve button stays disabled until 'CONFIRM'."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        # Propose high-risk category removal
        res_raw = propose_budget_change(category="Dining", action="remove")
        res_data = json.loads(res_raw)
        p_id = res_data["proposal_id"]

        at.run()

        # Find the Approve button for this proposal
        approve_btn = next(b for b in at.button if b.key == f"approve_btn_{p_id}")
        assert approve_btn.disabled is True

        # Input empty or wrong string -> stays disabled
        confirm_input = at.text_input(key=f"confirm_input_{p_id}")
        confirm_input.input("yes").run()
        approve_btn = next(b for b in at.button if b.key == f"approve_btn_{p_id}")
        assert approve_btn.disabled is True

        confirm_input.input("confirm").run()
        approve_btn = next(b for b in at.button if b.key == f"approve_btn_{p_id}")
        assert approve_btn.disabled is True

        # Input exactly "CONFIRM" -> button becomes enabled
        confirm_input.input("CONFIRM").run()
        approve_btn = next(b for b in at.button if b.key == f"approve_btn_{p_id}")
        assert approve_btn.disabled is False


def test_apptest_approve_low_risk_updates_ledger_and_undo_restores_it():
    """AppTest: approving a low-risk proposal updates the ledger; undo restores it."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        # Propose adding a unique low-risk transaction
        test_desc = f"AppTest Unique LowRisk Expense {uuid.uuid4().hex[:8]}"
        propose_add_transactions([
            {
                "date": "2026-08-20",
                "description": test_desc,
                "amount": 55.50,
                "category": "Dining",
                "type": "expense",
            }
        ])

        at.run()

        # Find proposal in list_pending
        pending = list_pending(workspace=app_ws)
        matching = [
            p for p in pending
            if test_desc in str(p.get("payload", {})) or test_desc in str(p.get("preview", {}))
        ]
        assert len(matching) == 1
        p_id = str(matching[0].get("id") or matching[0].get("proposal_id"))

        # Click Approve button in UI
        approve_btn = next(b for b in at.button if b.key == f"approve_btn_{p_id}")
        assert approve_btn.disabled is False
        approve_btn.click().run()

        # Verify ledger updated
        df_tx = read_csv("transactions.csv", workspace=app_ws)
        assert test_desc in df_tx["description"].values

        # Click Undo last change button in UI
        undo_btn = next(b for b in at.button if b.key == "undo_last_change_btn")
        undo_btn.click().run()

        # Verify ledger restored
        df_tx_restored = read_csv("transactions.csv", workspace=app_ws)
        assert test_desc not in df_tx_restored["description"].values


def test_apptest_expired_proposal_shows_expired_and_no_buttons():
    """AppTest: expired proposals show 'Expired' and have no buttons."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        # Create an expired proposal directly in store
        from src.store import create_proposal
        create_proposal(
            kind="budget_change",
            payload={"category": "Dining", "new_limit": 250.0},
            preview={"before": 300.0, "after": 250.0},
            risk="low",
            workspace=app_ws,
            proposal_id="prop_expired_demo",
            status="expired",
            expires_at="2026-08-01T00:00:00",
        )

        at.run()

        # Expired proposal must NOT have Approve or Reject buttons
        approve_btn = next((b for b in at.button if b.key == "approve_btn_prop_expired_demo"), None)
        reject_btn = next((b for b in at.button if b.key == "reject_btn_prop_expired_demo"), None)
        assert approve_btn is None
        assert reject_btn is None

        # Must display Expired badge / text
        has_expired_markdown = any("Expired" in str(m.value) for m in at.markdown)
        assert has_expired_markdown is True


def test_apptest_inbox_tab_label_and_activity_log():
    """AppTest: Inbox tab label displays pending count and activity log shows plain English."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        # Append an import audit entry with 3 transactions
        from src.store import append_audit
        append_audit(
            action="import_transactions",
            before=None,
            after={"count": 3, "items": [{"id": "1"}, {"id": "2"}, {"id": "3"}]},
            source="human",
            workspace=app_ws,
        )

        # Propose a budget change to have at least 1 pending proposal
        p_res = propose_budget_change(category="Dining", new_limit=310.0)
        p_id = json.loads(p_res)["proposal_id"]

        at.run()

        # Check tab label includes pending count
        tab_labels = [tab.label for tab in at.tabs]
        inbox_tab = next((lbl for lbl in tab_labels if "Inbox" in lbl), None)
        assert inbox_tab is not None
        pending_count = len(list_pending(workspace=app_ws))
        assert f"Inbox ({pending_count})" in inbox_tab

        # Check activity log in UI contains "Added 3 transactions (you)"
        plain_log_found = any("Added 3 transactions (you)" in str(m.value) for m in at.markdown)
        assert plain_log_found is True


def test_apptest_plan_tab_bills_and_phase_5():
    """AppTest: Plan tab lists bills, proposing bill change does not modify bills.csv, and shows Phase 5."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        # Check "Coming in Phase 5" appears in the Plan tab
        has_phase5 = any("Coming in Phase 5" in str(m.value) for m in at.markdown)
        assert has_phase5 is True

        # Bills before
        bills_before = read_csv("bills.csv", workspace=app_ws)
        orig_count = len(bills_before)

        # Propose adding a new bill via form
        new_bill_name = f"Test Internet {uuid.uuid4().hex[:6]}"
        at.text_input(key="add_bill_name").input(new_bill_name)
        at.text_input(key="add_bill_amount").input("75.00")
        add_bill_btn = next(b for b in at.button if b.key == "add_bill_submit_btn")
        add_bill_btn.click().run()

        # Bills.csv must remain unchanged
        bills_after = read_csv("bills.csv", workspace=app_ws)
        assert len(bills_after) == orig_count
        assert new_bill_name not in bills_after["bill_name"].values

        # Proposal must exist
        pending = list_pending(workspace=app_ws)
        matching_bill = [p for p in pending if new_bill_name in str(p)]
        assert len(matching_bill) == 1


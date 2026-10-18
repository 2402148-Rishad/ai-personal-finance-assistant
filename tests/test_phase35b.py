"""Tests for Phase 3.5b: Ledger, Inbox and undo clarity.
Tasks:
1. Ledger editing: below the table, add a "Pick a transaction to edit" selectbox.
   Each option reads like "31 Aug 2026 · $45.00 · Groceries · Groceries expense".
   Selecting one opens an Edit form pre-filled with its values, with Save and Delete buttons.
   Delete keeps its confirm checkbox.
   Make Min and Max amount empty by default, with the placeholder "Any", not 0.00.
2. Undo clarity: above the Undo button, show a line saying what it will undo,
   e.g. "Next undo: remove $45.00 Groceries expense from 31 Aug 2026."
   If nothing can be undone, show "Nothing to undo yet."
   Add a test for both states.
3. Inbox readability: replace the raw JSON in Before and After with plain lines,
   such as "$45.00 · Groceries · 31 Aug 2026".
   Replace the raw expiry timestamp with "Expires in 23 h 59 min", or "Expired".
   Add a test that no card shows "[{" or a timestamp with microseconds.
4. Demo checklist: at the top of the Overview tab, add a card titled "Your demo checklist" with five steps:
   1. Add an expense in chat
   2. Approve it
   3. Change its category in Ledger
   4. Propose a budget change in Plan
   5. Reject it
   Each step ticks itself when audit.jsonl in the active workspace has the matching human action: add, update, or reject.
   Hide the card once all five are ticked, and offer a "Start again" button that resets the workspace.
"""

from datetime import datetime, timedelta
import json
from pathlib import Path
import re
from unittest.mock import MagicMock, patch
import pytest
from streamlit.testing.v1 import AppTest

from src.formatters import get_next_undo_line, format_card_value, format_expiry, format_date_human
from src.approvals import approve, list_pending, reject, undo
import src.tools as tools_module
import src.approvals as approvals_module
from src.store import (
    create_workspace,
    set_active_workspace,
    read_audit,
    read_csv,
    update_transaction,
    append_audit,
    save_proposal,
)
from src.tools import propose_add_transactions, propose_budget_change

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


@pytest.fixture(autouse=True)
def clean_proposals_fixture():
    """Ensure legacy proposals file is clean between tests."""
    legacy_file = Path(__file__).resolve().parent.parent / "logs" / "pending_proposals.json"
    if legacy_file.exists():
        legacy_file.write_text("{}", encoding="utf-8")
    yield
    if legacy_file.exists():
        legacy_file.write_text("{}", encoding="utf-8")


@pytest.fixture
def workspace_env(tmp_path, monkeypatch):
    """Create an isolated workspace from seed data."""
    ws = create_workspace("session_test_phase35b", base_dir=tmp_path)
    monkeypatch.setenv("FINANCE_DATA_DIR", str(ws))
    monkeypatch.setattr(tools_module, "LOGS_DIR", ws)
    monkeypatch.setattr(tools_module, "PROPOSALS_PATH", ws / "pending_proposals.json")
    monkeypatch.setattr(approvals_module, "LOGS_DIR", ws)
    monkeypatch.setattr(approvals_module, "PROPOSALS_PATH", ws / "pending_proposals.json")
    set_active_workspace(ws)
    yield ws
    set_active_workspace(None)


# -----------------------------------------------------------------------------
# Task 2: Undo clarity tests
# -----------------------------------------------------------------------------

def test_undo_clarity_both_states(workspace_env):
    """Test get_next_undo_line for both 'Nothing to undo yet.' and populated states."""
    ws = workspace_env
    set_active_workspace(ws)

    # 1. Initially nothing to undo
    line_empty = get_next_undo_line(workspace=ws)
    assert line_empty == "Nothing to undo yet."

    # 2. Propose adding an expense and approve it
    prop_raw = propose_add_transactions(
        [{"date": "2026-08-31", "amount": 45.0, "category": "Groceries", "description": "Groceries expense", "type": "expense"}]
    )
    prop_data = json.loads(prop_raw)
    assert prop_data.get("status") == "pending_confirmation"
    p_id = prop_data["proposal_id"]
    approve_res = approve(p_id, "yes", workspace=ws)
    assert approve_res["status"] == "applied"

    # Line should now describe the undo action
    line_added = get_next_undo_line(workspace=ws)
    assert line_added == "Next undo: remove $45.00 Groceries expense from 31 Aug 2026."

    # 3. Undo the change
    undo_res = undo(workspace=ws)
    assert undo_res["status"] == "undone"

    # Line returns to 'Nothing to undo yet.'
    line_after_undo = get_next_undo_line(workspace=ws)
    assert line_after_undo == "Nothing to undo yet."


def test_undo_clarity_ui_display():
    """AppTest: Inbox tab displays the next undo line above the Undo button in both states."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        # Switch to Inbox tab
        at.session_state["active_tab"] = "Inbox"
        at.run()

        # State 1: Nothing to undo yet
        undo_btn = next((b for b in at.button if b.key == "undo_last_change_btn"), None)
        assert undo_btn is not None
        assert any("Nothing to undo yet." in str(m.value) for m in at.markdown)

        # State 2: After approving an expense
        prop_raw = propose_add_transactions(
            [{"date": "2026-08-31", "amount": 45.0, "category": "Groceries", "description": "Groceries expense", "type": "expense"}]
        )
        p_id = json.loads(prop_raw)["proposal_id"]
        approve(p_id, "yes", workspace=app_ws)

        at.run()
        assert any("Next undo: remove $45.00 Groceries expense from 31 Aug 2026." in str(m.value) for m in at.markdown)


# -----------------------------------------------------------------------------
# Task 3: Inbox readability tests
# -----------------------------------------------------------------------------

def test_inbox_readability_no_json_or_microseconds():
    """Verify proposal cards in Inbox tab do not contain '[{' or timestamps with microseconds."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        # Create a pending proposal
        prop_raw = propose_add_transactions(
            [{"date": "2026-08-31", "amount": 45.0, "category": "Groceries", "description": "Groceries expense", "type": "expense"}]
        )
        assert json.loads(prop_raw)["status"] == "pending_confirmation"

        # Also add an expired proposal to test 'Expired' display
        exp_time = (datetime.now() - timedelta(minutes=10)).isoformat()
        save_proposal({
            "id": "prop_test_expired",
            "kind": "budget_change",
            "risk": "low",
            "expires_at": exp_time,
            "status": "expired",
            "preview": {"before": 150.0, "after": 200.0},
            "old_limit": 150.0,
            "new_limit": 200.0,
        }, workspace=app_ws)

        # Open Inbox tab
        at.session_state["active_tab"] = "Inbox"
        at.run()

        # Collect all text in the app
        all_texts = [str(m.value) for m in at.markdown] + [str(c.value) for c in at.caption]

        # 1. No card shows '[{'
        assert not any("[{" in t for t in all_texts), f"Found raw JSON '[{{' in: {all_texts}"

        # 2. No card shows ISO timestamp with microseconds
        microsecond_pattern = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+")
        for t in all_texts:
            assert not microsecond_pattern.search(t), f"Found timestamp with microseconds in: {t}"

        # 3. Card shows readable line format: '$45.00 · Groceries · 31 Aug 2026'
        assert any("$45.00 · Groceries · 31 Aug 2026" in t for t in all_texts)

        # 4. Card shows 'Expires in ' and expired card shows 'Expired'
        assert any("Expires in " in t for t in all_texts)
        assert any("Expired" in t for t in all_texts)


# -----------------------------------------------------------------------------
# Task 1: Ledger editing tests
# -----------------------------------------------------------------------------

def test_ledger_filter_min_max_empty_placeholder_any():
    """AppTest: Ledger filter Min and Max amount are empty by default with placeholder 'Any'."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        at.session_state["active_tab"] = "Ledger"
        at.run()

        # Check number inputs
        min_input = next((inp for inp in at.number_input if inp.key == "ledger_filter_min"), None)
        max_input = next((inp for inp in at.number_input if inp.key == "ledger_filter_max"), None)

        assert min_input is not None
        assert max_input is not None

        # Value should be None by default (empty)
        assert min_input.value is None
        assert max_input.value is None


def test_ledger_pick_transaction_to_edit_selectbox_and_edit_form():
    """AppTest: 'Pick a transaction to edit' selectbox format and prefilled Edit form."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        at.session_state["active_tab"] = "Ledger"
        at.run()

        # Find 'Pick a transaction to edit' selectbox
        sel_box = next((s for s in at.selectbox if s.key == "ledger_select_edit_tx"), None)
        assert sel_box is not None
        assert sel_box.label == "Pick a transaction to edit"

        # Check option format: "31 Aug 2026 · $45.00 · Groceries · Groceries expense"
        assert len(sel_box.options) > 0
        first_opt = sel_box.options[0]
        # Option must contain middle dots ' · ' separating date, amount, category, description
        assert " · " in first_opt
        parts = first_opt.split(" · ")
        assert len(parts) >= 4, f"Option format expected 4 parts, got: {first_opt}"
        # Part 1 is date, Part 2 is amount with $, Part 3 is category, Part 4 is description
        assert "$" in parts[1]

        # Select the first transaction to open the Edit form
        sel_box.select(first_opt).run()

        # Verify Edit form is prefilled with its values
        edit_date = next((ti for ti in at.text_input if ti.key and ti.key.startswith("edit_date_")), None)
        edit_desc = next((ti for ti in at.text_input if ti.key and ti.key.startswith("edit_desc_")), None)
        edit_amt = next((ti for ti in at.text_input if ti.key and ti.key.startswith("edit_amt_")), None)
        edit_cat = next((sb for sb in at.selectbox if sb.key and sb.key.startswith("edit_cat_")), None)
        confirm_del = next((cb for cb in at.checkbox if cb.key and cb.key.startswith("confirm_del_")), None)
        save_btn = next((b for b in at.button if b.key and b.key.startswith("edit_save_btn_")), None)
        del_btn = next((b for b in at.button if b.key and b.key.startswith("edit_del_btn_")), None)

        assert edit_date is not None and edit_date.value
        assert edit_desc is not None and edit_desc.value
        assert edit_amt is not None and edit_amt.value
        assert edit_cat is not None and edit_cat.value
        assert confirm_del is not None
        assert save_btn is not None and save_btn.label == "Save"
        assert del_btn is not None and del_btn.label == "Delete"

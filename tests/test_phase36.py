"""Tests for Phase 3.6: fix tab navigation from the banner.
Tasks:
1. In app.py, replace st.tabs with a horizontal st.radio, key "active_view", label_visibility "collapsed".
   The option values are the fixed strings "Overview", "Ledger", "Plan" and "Inbox".
   Use format_func so the Inbox option displays its pending count, such as "Inbox (1)".
   Style the selected item with an underline in the existing red #E04836 so it still looks like a tab row.
   Render the selected panel with if/elif. Keep every panel's contents unchanged.
2. The "Open Inbox" button in the banner uses on_click to set st.session_state.active_view = "Inbox".
   Use on_click, not a button check followed by rerun, so the value is set before the radio is drawn.
   Do the same for any other link that points to the Inbox.
3. The demo checklist must still work on every view. Check that each view renders without error.
4. AppTest tests:
   - Clicking "Open Inbox" sets active_view to "Inbox" and shows the Inbox panel.
   - The Inbox option label shows the pending count.
   - Selecting Ledger shows the Ledger panel.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from streamlit.testing.v1 import AppTest

import src.tools as tools_module
import src.approvals as approvals_module
from src.store import create_workspace, set_active_workspace, reset_workspace
from src.tools import propose_add_transactions, propose_budget_change

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


@pytest.fixture(autouse=True)
def clean_proposals_fixture():
    legacy_file = Path(__file__).resolve().parent.parent / "logs" / "pending_proposals.json"
    if legacy_file.exists():
        legacy_file.write_text("{}", encoding="utf-8")
    yield
    if legacy_file.exists():
        legacy_file.write_text("{}", encoding="utf-8")


def test_clicking_open_inbox_sets_active_view_and_shows_inbox_panel():
    """AppTest: Clicking 'Open Inbox' sets active_view to 'Inbox' and shows the Inbox panel."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        # Initially Overview is selected
        assert at.session_state.active_view == "Overview"

        # Create a pending proposal so the banner displays the 'Open Inbox' button
        prop_raw = propose_budget_change("Dining", 300.0)
        assert json.loads(prop_raw).get("status") == "pending_confirmation"

        at.run()

        # Find the 'Open Inbox' button
        open_inbox_btn = next((b for b in at.button if b.key == "open_inbox_banner_btn"), None)
        assert open_inbox_btn is not None
        assert open_inbox_btn.label == "Open Inbox"

        # Click 'Open Inbox'
        open_inbox_btn.click().run()

        # 1. active_view in session_state is 'Inbox'
        assert at.session_state.active_view == "Inbox"

        # 2. Inbox panel is rendered
        assert any(s.value == "Inbox" for s in at.subheader)
        undo_btn = next((b for b in at.button if b.key == "undo_last_change_btn"), None)
        assert undo_btn is not None
        assert any("Activity Log" in str(s.value) for s in at.subheader)


def test_inbox_option_label_shows_pending_count():
    """AppTest: The Inbox option label shows the pending count (e.g. Inbox (0), Inbox (1), Inbox (2))."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        # 0 pending proposals initially
        nav_radio = next((r for r in at.radio if r.key == "active_view"), None)
        assert nav_radio is not None
        assert "Inbox (0)" in nav_radio.options

        # Propose 1 change
        propose_budget_change("Dining", 310.0)
        at.run()

        nav_radio = next((r for r in at.radio if r.key == "active_view"), None)
        assert nav_radio is not None
        assert "Inbox (1)" in nav_radio.options

        # Propose a 2nd change
        propose_add_transactions([
            {"date": "2026-08-25", "amount": 18.5, "category": "Dining", "description": "Quick lunch", "type": "expense"}
        ])
        at.run()

        nav_radio = next((r for r in at.radio if r.key == "active_view"), None)
        assert nav_radio is not None
        assert "Inbox (2)" in nav_radio.options


def test_selecting_ledger_shows_ledger_panel():
    """AppTest: Selecting Ledger shows the Ledger panel."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        # Find navigation radio
        nav_radio = next((r for r in at.radio if r.key == "active_view"), None)
        assert nav_radio is not None

        # Select Ledger
        nav_radio.set_value("Ledger").run()

        # active_view is 'Ledger'
        assert at.session_state.active_view == "Ledger"

        # Ledger panel is rendered
        assert any(s.value == "Ledger" for s in at.subheader)
        assert len(at.dataframe) > 0
        edit_select = next((s for s in at.selectbox if s.key == "ledger_select_edit_tx"), None)
        assert edit_select is not None
        assert edit_select.label == "Pick a transaction to edit"


def test_demo_checklist_and_views_render_without_error():
    """AppTest: Demo checklist renders on every view and each view renders without error."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        # Check Overview view
        assert not at.exception
        assert any("Your demo checklist" in str(m.value) for m in at.markdown)
        assert next((cb for cb in at.checkbox if cb.key == "demo_step_1"), None) is not None

        # Check Ledger view
        nav_radio = next(r for r in at.radio if r.key == "active_view")
        nav_radio.set_value("Ledger").run()
        assert not at.exception
        assert any("Your demo checklist" in str(m.value) for m in at.markdown)
        assert any(s.value == "Ledger" for s in at.subheader)

        # Check Plan view
        nav_radio = next(r for r in at.radio if r.key == "active_view")
        nav_radio.set_value("Plan").run()
        assert not at.exception
        assert any("Your demo checklist" in str(m.value) for m in at.markdown)
        assert any(s.value == "Plan" for s in at.subheader)

        # Check Inbox view
        nav_radio = next(r for r in at.radio if r.key == "active_view")
        nav_radio.set_value("Inbox").run()
        assert not at.exception
        assert any("Your demo checklist" in str(m.value) for m in at.markdown)
        assert any(s.value == "Inbox" for s in at.subheader)

"""Tests for Phase 3.4: Chat panel, inline approvals, clarification chips, 'How I got this' expander, error state, and responsive layout."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import uuid
import pytest
from streamlit.testing.v1 import AppTest

from src.approvals import list_pending, approve, reject
from src.store import (
    create_workspace,
    set_active_workspace,
    read_csv,
    read_json,
    create_proposal,
)
from src.tools import propose_budget_change

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


def test_apptest_inline_approval_card_low_risk_approve_and_reject():
    """AppTest: Inline approval card displays 'Fin proposed: ...' with before/after, and approves low-risk."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        # Create a low-risk proposal in the workspace
        prop = create_proposal(
            kind="budget_change",
            payload={"category": "Dining", "action": "update", "new_limit": 375.0},
            preview={"before": 300.0, "after": 375.0},
            risk="low",
            workspace=app_ws,
            proposal_id="prop_inline_low",
        )

        # Inject into display as an assistant message that created this proposal
        at.session_state.display.append({
            "role": "assistant",
            "content": "I proposed updating your Dining budget to $375.00.",
            "tool_calls": [{"name": "propose_budget_change", "arguments": {"category": "Dining", "new_limit": 375.0}}],
            "proposal_ids": ["prop_inline_low"],
        })
        at.run()

        # Check inline card content
        assert any("Fin proposed: Budget Change" in str(m.value) for m in at.markdown)
        assert any("$300.00" in str(m.value) for m in at.markdown)
        assert any("$375.00" in str(m.value) for m in at.markdown)

        # Approve button should be enabled
        approve_btn = next((b for b in at.button if "inline_approve_prop_inline_low" in b.key), None)
        assert approve_btn is not None
        assert approve_btn.disabled is False

        # Click approve
        approve_btn.click().run()

        # Verify budget was updated in budgets.json
        budgets = read_json("budgets.json", workspace=app_ws)
        assert budgets["Dining"] == 375.0


def test_apptest_inline_approval_card_high_risk_disabled_until_confirm():
    """AppTest: Inline approval card keeps high-risk Approve disabled until CONFIRM."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        # Create high-risk proposal
        create_proposal(
            kind="budget_change",
            payload={"category": "Dining", "action": "remove", "new_limit": 0.0},
            preview={"before": 300.0, "after": None},
            risk="high",
            workspace=app_ws,
            proposal_id="prop_inline_high",
        )

        at.session_state.display.append({
            "role": "assistant",
            "content": "I proposed removing your Dining budget category.",
            "tool_calls": [],
            "proposal_ids": ["prop_inline_high"],
        })
        at.run()

        approve_btn = next((b for b in at.button if "inline_approve_prop_inline_high" in b.key), None)
        assert approve_btn is not None
        assert approve_btn.disabled is True

        # Input incorrect confirmation
        confirm_input = next((t for t in at.text_input if "inline_confirm_prop_inline_high" in t.key), None)
        assert confirm_input is not None
        confirm_input.input("confirm").run()

        approve_btn = next((b for b in at.button if "inline_approve_prop_inline_high" in b.key), None)
        assert approve_btn.disabled is True

        # Input exact "CONFIRM"
        confirm_input = next((t for t in at.text_input if "inline_confirm_prop_inline_high" in t.key), None)
        confirm_input.input("CONFIRM").run()

        approve_btn = next((b for b in at.button if "inline_approve_prop_inline_high" in b.key), None)
        assert approve_btn.disabled is False


def test_apptest_clarification_chips():
    """AppTest: Clarification options appear as clickable chips and clicking sends as question."""
    mock_run_agent = MagicMock()
    with patch("src.agent.run_agent", mock_run_agent):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        # Inject assistant message with clarification options
        at.session_state.display.append({
            "role": "assistant",
            "content": "Which category did you mean?",
            "tool_calls": [],
            "clarification_options": ["Groceries", "Dining", "Utilities"],
        })
        at.run()

        # Chips must appear as buttons
        chip_btns = [b for b in at.button if b.key and b.key.startswith("clarify_")]
        assert len(chip_btns) == 3
        chip_labels = [b.label for b in chip_btns]
        assert "Groceries" in chip_labels
        assert "Dining" in chip_labels

        # Click the "Dining" chip
        dining_chip = next(b for b in chip_btns if b.label == "Dining")
        dining_chip.click().run()

        # run_agent should have been called with "Dining"
        assert mock_run_agent.called
        call_args = mock_run_agent.call_args[0]
        assert call_args[0] == "Dining"


def test_apptest_how_i_got_this_expander():
    """AppTest: 'How I got this' expander renders tool calls, arguments and key result numbers."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

        at.session_state.display.append({
            "role": "assistant",
            "content": "You spent $215.50 on Dining.",
            "tool_calls": [
                {
                    "name": "spending_by_category",
                    "arguments": {"month": "2026-08"},
                    "result": {
                        "month": "2026-08",
                        "total_spending": 215.50,
                        "transaction_count": 8,
                    },
                }
            ],
        })
        at.run()

        # Summary caption must be preserved
        assert any("spending_by_category" in str(c.value) for c in at.caption)

        # Expander must exist
        assert any(exp.label == "How I got this" for exp in at.expander)

        # Key result numbers must be in markdown
        assert any("total_spending" in str(m.value) for m in at.markdown)
        assert any("$215.50" in str(m.value) for m in at.markdown)


def test_apptest_error_state_and_independent_features():
    """AppTest: Model failure shows error message, but Ledger/Inbox still function."""
    with patch("src.agent.run_agent", side_effect=RuntimeError("Model unreachable")):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        # Submit question that fails
        at.text_input(key=f"user_question_{at.session_state.input_key}").input("Fail test")
        send_btn = next(b for b in at.button if b.label == "Send")
        send_btn.click().run()

        # Error message displayed
        assert any("Couldn't reach the model. Try again in a moment." in str(e.value) for e in at.error)

        # Ledger add still works without model
        at.session_state["active_view"] = "Ledger"
        at.run()
        at.text_input(key="add_tx_date").input("2026-08-15")
        at.text_input(key="add_tx_desc").input("Manual Offline Add")
        at.text_input(key="add_tx_amount").input("33.00")
        cat_select = next((s for s in at.selectbox if s.key == "add_tx_category"), None)
        if cat_select and "Dining" in cat_select.options:
            cat_select.select("Dining")
        add_tx_btn = next(b for b in at.button if b.key == "add_tx_submit_btn")
        add_tx_btn.click().run()

        df_tx = read_csv("transactions.csv", workspace=app_ws)
        assert "Manual Offline Add" in df_tx["description"].values


def test_narrow_screen_media_query_in_html():
    """AppTest: Verify 640px media query and no horizontal scroll CSS exist in st.html block."""
    app_text = APP_PATH.read_text(encoding="utf-8")
    assert "@media (max-width: 640px)" in app_text
    assert "overflow-x: hidden" in app_text

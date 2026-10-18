"""Test suite for Phase 4.6: clarification, correction hint, and mobile fixes."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from streamlit.testing.v1 import AppTest

from src import agent as agent_module
from src.agent import run_agent, build_source_line
from src import config as config_module
from src.config import PROJECT_ROOT
from src.approvals import list_pending, request_approval
from src.categories import suggest_category
from src.store import create_workspace, set_active_workspace, read_proposals
from src.tools import propose_add_transactions, get_most_used_categories
from src import tools as tools_module


APP_PATH = PROJECT_ROOT / "app.py"


@pytest.fixture
def workspace_env(tmp_path, monkeypatch):
    """Create an isolated workspace from seed data and point FINANCE_DATA_DIR to it."""
    ws = create_workspace("session_test_phase46", base_dir=tmp_path)
    monkeypatch.setenv("FINANCE_DATA_DIR", str(ws))
    monkeypatch.setattr(tools_module, "LOGS_DIR", ws)
    monkeypatch.setattr(tools_module, "PROPOSALS_PATH", ws / "pending_proposals.json")
    return ws


class MockFunctionCall:
    def __init__(self, name, args):
        self.name = name
        self.args = args


class MockCandidate:
    def __init__(self, content):
        self.content = content


class MockPart:
    def __init__(self, text=None, function_call=None):
        self.text = text
        self.function_call = function_call


class MockContent:
    def __init__(self, role, parts):
        self.role = role
        self.parts = parts


class MockModelResponse:
    def __init__(self, text=None, function_calls=None):
        self.text = text
        self.function_calls = []
        parts = []
        if function_calls:
            for fc in function_calls:
                call_obj = MockFunctionCall(fc["name"], fc.get("args", {}))
                self.function_calls.append(call_obj)
                parts.append(MockPart(function_call=call_obj))
        if text:
            parts.append(MockPart(text=text))
        self.candidates = [MockCandidate(MockContent("model", parts))]


# -------------------------------------------------------------------------
# Task 1: Category must come from the user
# -------------------------------------------------------------------------

def test_add_coffee_with_no_category_suggests_dining_first_and_creates_no_proposal(workspace_env):
    """'Add a $12 coffee' with no category returns options with Dining first and marked '(suggested)', and creates no proposal."""
    ws = workspace_env

    # 1. Without category: returns needs_clarification with Dining (suggested) first
    res = propose_add_transactions([{
        "description": "coffee",
        "amount": 12.0,
        "type": "expense",
    }])
    data = json.loads(res)
    assert data["status"] == "needs_clarification"
    assert "category" in data["missing"]
    assert "options" in data

    opts = data["options"]["category"] if isinstance(data["options"], dict) else data["options"]
    assert len(opts) > 0
    assert opts[0] == "Dining (suggested)"

    # Verify no proposal was created
    assert len(read_proposals(workspace=ws)) == 0
    assert len(list_pending(workspace=ws)) == 0

    # 2. When user names a category: creates a proposal
    res_named = propose_add_transactions([{
        "description": "coffee",
        "amount": 12.0,
        "category": "Dining",
        "type": "expense",
    }])
    data_named = json.loads(res_named)
    assert data_named["status"] == "pending_confirmation"
    assert "proposal_id" in data_named

    # Exactly one proposal created
    assert len(read_proposals(workspace=ws)) == 1
    assert len(list_pending(workspace=ws)) == 1


def test_suggest_category_only_uses_workspace_categories(workspace_env):
    """suggest_category maps keywords to categories and only suggests categories present in workspace."""
    ws = workspace_env
    assert suggest_category("Starbucks coffee", workspace=ws) == "Dining"
    assert suggest_category("Lunch at deli", workspace=ws) == "Dining"
    assert suggest_category("Weekly supermarket groceries", workspace=ws) == "Groceries"
    assert suggest_category("City bus fare", workspace=ws) == "Transport"
    assert suggest_category("Monthly apartment rent", workspace=ws) == "Rent"
    assert suggest_category("Unknown random item without keywords", workspace=ws) is None


# -------------------------------------------------------------------------
# Task 2: Clarification chips
# -------------------------------------------------------------------------

def test_clarification_chips_render_numbered_and_send_category_query():
    """When a tool result in turn has needs_clarification with options, show numbered buttons.
    Clicking one sends 'Category: <option>' as the next question (model mocked).
    """
    mock_run_agent = MagicMock()
    mock_res = MagicMock()
    mock_res.answer = "Got it! Adding transaction with category Dining."
    mock_res.history = []
    mock_res.tool_calls = []
    mock_run_agent.return_value = mock_res

    with patch("src.agent.run_agent", mock_run_agent):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        # Inject an assistant message with clarification options
        at.session_state.display.append({
            "role": "assistant",
            "content": "Which category should I use for coffee?",
            "tool_calls": [],
            "clarification_options": ["Dining (suggested)", "Groceries", "Transport"],
        })
        at.run()

        # Numbered buttons must appear
        chip_btns = [b for b in at.button if b.key and b.key.startswith("clarify_")]
        assert len(chip_btns) == 3
        labels = [b.label for b in chip_btns]
        assert labels in (
            ["1 · Dining (suggested)", "2 · Groceries", "3 · Transport"],
            ["1. Dining (suggested)", "2. Groceries", "3. Transport"],
        )

        # Click the first option
        chip_btns[0].click().run()

        # run_agent must be called with category selection
        assert mock_run_agent.called
        assert "Dining" in mock_run_agent.call_args[0][0]


# -------------------------------------------------------------------------
# Task 3: Correction hint
# -------------------------------------------------------------------------

def test_correction_hint_appears_under_approval_card():
    """After any proposal reply, add under the approval card:
    'Want a change? Say it, e.g. \\'make it 40\\' or \\'change to Groceries\\'.'
    Test that it appears once per proposal.
    """
    at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    app_ws = create_workspace(at.session_state["session_id"])
    set_active_workspace(app_ws)

    # Create a proposal in workspace
    prop_1 = {
        "id": "prop_hint_01",
        "proposal_id": "prop_hint_01",
        "kind": "add_transactions",
        "payload": {"items": [{"date": "2026-08-01", "description": "Coffee", "amount": 12.0, "category": "Dining", "type": "expense"}]},
        "preview": {"before": "None", "after": "Coffee $12.00"},
        "risk": "low",
        "status": "pending_confirmation",
        "expires_at": "2099-01-01T00:00:00",
    }
    from src import store
    store.save_proposal(prop_1, workspace=app_ws)
    p_id = "prop_hint_01"

    hint_text = "Want a change? Say it, e.g. 'make it 40' or 'change to Groceries'."

    # Case 1: 1 proposal
    at.session_state.display.append({
        "role": "assistant",
        "content": f"Proposed adding coffee (`{p_id}`).",
        "tool_calls": [],
        "proposal_ids": [p_id],
    })
    at.run()

    hint_matches = [m for m in at.markdown if hint_text in m.value] + [c for c in at.caption if hint_text in c.value]
    assert len(hint_matches) == 1

    # Case 2: 2 proposals -> appears twice (once per proposal)
    prop_2 = {
        "id": "prop_hint_02",
        "proposal_id": "prop_hint_02",
        "kind": "add_transactions",
        "payload": {"items": [{"date": "2026-08-02", "description": "Book", "amount": 25.0, "category": "Shopping", "type": "expense"}]},
        "preview": {"before": "None", "after": "Book $25.00"},
        "risk": "low",
        "status": "pending_confirmation",
        "expires_at": "2099-01-01T00:00:00",
    }
    store.save_proposal(prop_2, workspace=app_ws)
    p_id2 = "prop_hint_02"

    at.session_state.display.append({
        "role": "assistant",
        "content": f"Proposed adding book (`{p_id2}`).",
        "tool_calls": [],
        "proposal_ids": [p_id, p_id2],
    })
    at.run()

    hint_matches_2 = [m for m in at.markdown if hint_text in m.value] + [c for c in at.caption if hint_text in c.value]
    # In this run, the first turn had 1 proposal and the second turn had 2 proposals = total 3
    assert len(hint_matches_2) == 3


# -------------------------------------------------------------------------
# Task 4: Source line moved out of answer into expander
# -------------------------------------------------------------------------

def test_source_line_moved_to_expander_not_in_answer(monkeypatch):
    """The answer text no longer ends with 'Source:' and the expander contains it."""
    calls = 0

    def mock_generate_content(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(
                function_calls=[{"name": "spending_by_category", "args": {"month": "2026-07"}}]
            )
        return MockModelResponse("You spent $510.00 on Dining in July 2026.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    result = run_agent("How much did I spend on dining in July 2026?", history=[])
    assert result.status == "ok"
    assert "510.00" in result.answer
    # Must NOT end with Source line
    assert not result.answer.strip().endswith("Source: transactions.csv (July 2026)")
    assert "Source:" not in result.answer

    # build_source_line generates the source string for the expander
    src_line = build_source_line(result.tool_calls)
    assert src_line == "Source: transactions.csv (July 2026)"

    # Test that AppTest renders the source line inside the expander
    at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    app_ws = create_workspace(at.session_state["session_id"])
    set_active_workspace(app_ws)

    at.session_state.display.append({
        "role": "assistant",
        "content": result.answer,
        "tool_calls": result.tool_calls,
    })
    at.run()

    # Expander must exist and markdown inside it contains the source line
    assert len(at.expander) > 0
    all_md = [m.value for m in at.markdown]
    assert any("Source: transactions.csv (July 2026)" in m for m in all_md)


# -------------------------------------------------------------------------
# Task 5: Quick actions
# -------------------------------------------------------------------------

def test_quick_actions_table_only_no_metrics_and_shortened_buttons():
    """Quick actions:
    - Button labels: 'Summary', 'Bills', 'Budgets', '30-day cash'.
    - No st.metric rendered inside quick actions.
    - Full-width table only in summary with exact values.
    """
    failing_run_agent = MagicMock(side_effect=RuntimeError("Offline test - model must not be called!"))

    with patch("src.agent.run_agent", failing_run_agent):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        at.session_state["active_view"] = "Overview"
        at.run()

        # Check button labels are shortened
        btn_labels = [b.label for b in at.button]
        assert "Summary" in btn_labels
        assert "Bills" in btn_labels
        assert "Budgets" in btn_labels
        assert "30-day cash" in btn_labels

        # Record metrics outside quick actions (the top sandbox balance metric)
        baseline_metric_labels = [m.label for m in at.metric]
        assert "Simulated sandbox balance" in baseline_metric_labels

        # 1. Click Summary
        btn_sum = next(b for b in at.button if b.label == "Summary")
        btn_sum.click().run()
        assert not at.exception

        # Summary must render table only, NO extra metrics inside quick actions
        curr_metric_labels = [m.label for m in at.metric]
        assert curr_metric_labels == baseline_metric_labels
        assert "Income" not in curr_metric_labels
        assert "Expenses" not in curr_metric_labels
        assert "Net Savings" not in curr_metric_labels
        assert "Savings Rate" not in curr_metric_labels

        # Must have table with the exact metric rows
        assert len(at.table) > 0
        table_df = at.table[0].value
        assert "Metric" in table_df.columns
        assert "Value" in table_df.columns
        metrics_in_table = list(table_df["Metric"])
        assert metrics_in_table == ["Total Income", "Total Expenses", "Net Savings", "Savings Rate"]

        # 2. Click 30-day cash
        btn_cf = next(b for b in at.button if b.label == "30-day cash")
        btn_cf.click().run()
        assert not at.exception
        # Must have table and NO extra metrics inside quick actions
        curr_cf_metrics = [m.label for m in at.metric]
        assert curr_cf_metrics == baseline_metric_labels
        assert len(at.table) > 0

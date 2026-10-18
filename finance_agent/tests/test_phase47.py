"""Offline test suite for Phase 4.7: grounded categories, deterministic clarification and proposal reply, single Source line."""

import json
from pathlib import Path
import re
from unittest.mock import MagicMock, patch
import pytest
from streamlit.testing.v1 import AppTest

from src import agent as agent_module
from src.agent import run_agent, build_source_line
from src.approvals import list_pending
from src.categories import category_is_stated, suggest_category
from src.config import PROJECT_ROOT
from src import store
from src.store import create_workspace, set_active_workspace, read_proposals
from src.tools import (
    propose_add_transactions,
    propose_update_transaction,
    revise_proposal,
)
from src import tools as tools_module


APP_PATH = PROJECT_ROOT / "app.py"


@pytest.fixture
def workspace_env(tmp_path, monkeypatch):
    """Create an isolated workspace from seed data and point FINANCE_DATA_DIR to it."""
    ws = create_workspace("session_test_phase47", base_dir=tmp_path)
    monkeypatch.setenv("FINANCE_DATA_DIR", str(ws))
    monkeypatch.setattr(tools_module, "LOGS_DIR", ws)
    monkeypatch.setattr(tools_module, "PROPOSALS_PATH", ws / "pending_proposals.json")
    return ws


class MockPart:
    def __init__(self, text=None, function_call=None):
        self.text = text
        self.function_call = function_call


class MockFunctionCall:
    def __init__(self, name, args):
        self.name = name
        self.args = args


class MockCandidate:
    def __init__(self, content):
        self.content = content


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
                mfc = MockFunctionCall(fc["name"], fc.get("args", {}))
                self.function_calls.append(mfc)
                parts.append(MockPart(function_call=mfc))
        if text is not None:
            parts.append(MockPart(text=text))
        content = MockContent(role="model", parts=parts)
        self.candidates = [MockCandidate(content)]


# -------------------------------------------------------------------------
# 1. Category grounding (category_is_stated, contextvar, model simulation)
# -------------------------------------------------------------------------

def test_category_is_stated():
    """category_is_stated matches case-insensitively, whole-word, singular/plural, and aliases."""
    # Stated directly
    assert category_is_stated("Dining", "I spent 15 on dining yesterday")
    assert category_is_stated("Groceries", "Add $50 for Groceries")

    # Singular / Plural
    assert category_is_stated("Groceries", "Spent 40 on grocery")
    assert category_is_stated("Utilities", "utility bill was 80")
    assert category_is_stated("Subscriptions", "cancel my subscription")

    # Aliases
    assert category_is_stated("Dining", "I spent 20 eating out")
    assert category_is_stated("Dining", "dine out tonight")
    assert category_is_stated("Groceries", "Went to the supermarket")
    assert category_is_stated("Transport", "Paid for transit")

    # Unstated words that describe items but do not name the category
    assert not category_is_stated("Dining", "Add a $12 coffee")
    assert not category_is_stated("Dining", "Add lunch 12 and bus 3")
    assert not category_is_stated("Transport", "Add lunch 12 and bus 3")
    assert not category_is_stated("Dining", "burger 10")
    assert not category_is_stated("Groceries", "apple 2")


def test_misbehaving_model_category_grounding(workspace_env, monkeypatch):
    """The mocked model calls propose_add_transactions with category 'Dining' for 'Add a $12 coffee'.
    Expect needs_clarification and unchanged proposals.json.
    After user message 'Category for Coffee: Dining', creates a proposal.
    'Add lunch 12 and bus 3' asks about Lunch first and lists Bus as pending.
    """
    ws = workspace_env
    set_active_workspace(ws)

    # 1. Model tries to invent 'Dining' for 'Add a $12 coffee'
    calls = 0

    def mock_generate_content(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(
                function_calls=[{
                    "name": "propose_add_transactions",
                    "args": {"items": [{"description": "coffee", "amount": 12.0, "category": "Dining", "type": "expense"}]},
                }]
            )
        return MockModelResponse("Should be overridden by deterministic reply")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    result = run_agent("Add a $12 coffee", history=[])
    assert result.status == "ok"
    assert "Which category for Coffee ($12)?" in result.answer
    assert "1. Dining (suggested)" in result.answer

    # proposals.json must be completely unchanged (0 proposals)
    assert len(read_proposals(workspace=ws)) == 0
    assert len(list_pending(workspace=ws)) == 0

    # 2. User responds with 'Category for Coffee: Dining' -> creates proposal
    calls_2 = 0

    def mock_generate_content_2(model, contents, config):
        nonlocal calls_2
        calls_2 += 1
        if calls_2 == 1:
            return MockModelResponse(
                function_calls=[{
                    "name": "propose_add_transactions",
                    "args": {"items": [{"description": "coffee", "amount": 12.0, "category": "Dining", "type": "expense"}]},
                }]
            )
        return MockModelResponse("Model text to be replaced")

    mock_client_2 = MagicMock()
    mock_client_2.models.generate_content.side_effect = mock_generate_content_2
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client_2)

    history = result.history
    result_2 = run_agent("Category for Coffee: Dining", history=history)
    assert result_2.status == "ok"
    # Exactly one proposal created
    assert len(read_proposals(workspace=ws)) == 1
    assert len(list_pending(workspace=ws)) == 1
    # Deterministic creation text
    assert result_2.answer == "Ready for your OK. Nothing is saved until you approve."

    # 3. 'Add lunch 12 and bus 3' asks about Lunch first with Bus pending
    calls_3 = 0

    def mock_generate_content_3(model, contents, config):
        nonlocal calls_3
        calls_3 += 1
        if calls_3 == 1:
            return MockModelResponse(
                function_calls=[{
                    "name": "propose_add_transactions",
                    "args": {"items": [
                        {"description": "lunch", "amount": 12.0, "category": "Dining", "type": "expense"},
                        {"description": "bus", "amount": 3.0, "category": "Transport", "type": "expense"},
                    ]},
                }]
            )
        return MockModelResponse("Model text")

    mock_client_3 = MagicMock()
    mock_client_3.models.generate_content.side_effect = mock_generate_content_3
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client_3)

    result_3 = run_agent("Add lunch 12 and bus 3", history=[])
    assert result_3.status == "ok"
    assert "Which category for Lunch ($12)?" in result_3.answer
    assert "1. Dining (suggested)" in result_3.answer
    # Tool call result must have pending list containing Bus
    assert len(result_3.tool_calls) == 1
    t_res = result_3.tool_calls[0]["result"]
    assert t_res.get("item_label") == "Lunch"
    assert "Bus" in t_res.get("pending", [])


# -------------------------------------------------------------------------
# 2. Deterministic clarification UI (numbered buttons, on_click, disable)
# -------------------------------------------------------------------------

def test_clarification_ui_buttons_and_click_creates_proposal(workspace_env):
    """Message has numbered list and one full-width button per option.
    Clicking button 1 runs the next turn and creates a proposal.
    """
    mock_run_agent = MagicMock()
    mock_res_2 = MagicMock()
    mock_res_2.answer = "Ready for your OK. Nothing is saved until you approve."
    mock_res_2.history = []
    mock_res_2.tool_calls = [{"name": "propose_add_transactions", "result": {"proposal_id": "prop_test_01", "status": "pending_confirmation"}}]
    mock_run_agent.return_value = mock_res_2

    with patch("src.agent.run_agent", mock_run_agent):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        # Inject message with clarification options
        at.session_state.display.append({
            "role": "assistant",
            "content": "Which category for Coffee ($12)?\n\n1. Dining (suggested)\n2. Groceries\n3. Transport",
            "tool_calls": [],
            "clarification_options": ["Dining (suggested)", "Groceries", "Transport"],
            "clarification_item_label": "Coffee",
            "clarification_disabled": False,
        })
        at.run()

        # Check buttons labelled '1 · Dining (suggested)' etc.
        chip_btns = [b for b in at.button if b.key and b.key.startswith("clarify_")]
        assert len(chip_btns) == 3
        labels = [b.label for b in chip_btns]
        assert labels == ["1 · Dining (suggested)", "2 · Groceries", "3 · Transport"]

        # Click button 1
        chip_btns[0].click().run()

        # on_click sends 'Category for Coffee: Dining'
        assert mock_run_agent.called
        assert mock_run_agent.call_args[0][0] == "Category for Coffee: Dining"

        # The message's buttons are now disabled in state
        first_msg = at.session_state.display[0]
        assert first_msg.get("clarification_disabled") is True


# -------------------------------------------------------------------------
# 3. Deterministic proposal reply and hint location
# -------------------------------------------------------------------------

def test_deterministic_proposal_and_revision_replies(monkeypatch):
    """Proposal creation gives exact 'Ready for your OK...' text.
    Revision gives exact 'Updated. Same card, new values.' text.
    Answer contains no prop_, Expires, or timestamp.
    """
    # 1. Creation test through run_agent
    calls_create = 0

    def mock_gen_create(model, contents, config):
        nonlocal calls_create
        calls_create += 1
        if calls_create == 1:
            return MockModelResponse(
                function_calls=[{
                    "name": "propose_add_transactions",
                    "args": {"items": [{"description": "coffee", "amount": 12.0, "category": "Dining"}]},
                }]
            )
        return MockModelResponse("Created prop_123. Expires at 2026-08-31T12:00:00. Check Inbox tab.")

    mock_client_create = MagicMock()
    mock_client_create.models.generate_content.side_effect = mock_gen_create
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client_create)

    with patch.dict(tools_module.TOOLS_BY_NAME, {"propose_add_transactions": lambda **kwargs: json.dumps({"status": "pending_confirmation"})}), \
         patch.dict(agent_module.TOOLS_BY_NAME, {"propose_add_transactions": lambda **kwargs: json.dumps({"status": "pending_confirmation"})}):
        res_create = run_agent("Add a coffee with category Dining", history=[])
        assert res_create.answer == "Ready for your OK. Nothing is saved until you approve."
        assert "prop_" not in res_create.answer
        assert "Expires" not in res_create.answer
        assert not re.search(r"\d{4}-\d{2}-\d{2}T[\d:.]+", res_create.answer)

    # 2. Revision test through run_agent
    calls_rev = 0

    def mock_gen_rev(model, contents, config):
        nonlocal calls_rev
        calls_rev += 1
        if calls_rev == 1:
            return MockModelResponse(
                function_calls=[{
                    "name": "revise_proposal",
                    "args": {"proposal_id": "prop_dummy", "fields": {"amount": 40.0}},
                }]
            )
        return MockModelResponse("Model text with prop_dummy and 2026-08-31T12:00:00 and Expires")

    mock_client_rev = MagicMock()
    mock_client_rev.models.generate_content.side_effect = mock_gen_rev
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client_rev)

    with patch.dict(tools_module.TOOLS_BY_NAME, {"revise_proposal": lambda **kwargs: json.dumps({"status": "pending_confirmation"})}), \
         patch.dict(agent_module.TOOLS_BY_NAME, {"revise_proposal": lambda **kwargs: json.dumps({"status": "pending_confirmation"})}):
        res_rev = run_agent("Make it 40", history=[])
        assert res_rev.answer == "Updated. Same card, new values."
        assert "prop_" not in res_rev.answer
        assert "Expires" not in res_rev.answer
        assert not re.search(r"\d{4}-\d{2}-\d{2}T[\d:.]+", res_rev.answer)


def test_hint_inside_approval_card_container():
    """The hint is rendered inside the approval card as small muted text (st.caption),
    once per pending card, and not on the Inbox page.
    """
    at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    app_ws = create_workspace(at.session_state["session_id"])
    set_active_workspace(app_ws)

    prop = {
        "id": "prop_hint_p47",
        "proposal_id": "prop_hint_p47",
        "kind": "add_transactions",
        "payload": {"items": [{"date": "2026-08-01", "description": "Coffee", "amount": 12.0, "category": "Dining", "type": "expense"}]},
        "preview": {"before": None, "after": "Coffee $12.00"},
        "risk": "low",
        "status": "pending_confirmation",
        "expires_at": "2099-01-01T00:00:00",
    }
    store.save_proposal(prop, workspace=app_ws)

    hint_text = "Want a change? Say it, e.g. 'make it 40' or 'change to Groceries'."

    # 1. In chat view
    at.session_state.display.append({
        "role": "assistant",
        "content": "Ready for your OK. Nothing is saved until you approve.",
        "tool_calls": [],
        "proposal_ids": ["prop_hint_p47"],
    })
    at.run()

    caption_matches = [c for c in at.caption if hint_text in c.value]
    assert len(caption_matches) == 1

    # Answer text has no prop_, Expires, or timestamp
    assistant_md = at.markdown[1].value
    assert "prop_" not in assistant_md
    assert "Expires" not in assistant_md

    # 2. In Inbox page: hint must NOT appear
    at.session_state.display = []
    at.session_state["active_view"] = "Inbox"
    at.run()
    inbox_hint_matches = [c for c in at.caption if hint_text in c.value]
    assert len(inbox_hint_matches) == 0


# -------------------------------------------------------------------------
# 4. One Source line (only for answers that read data, not proposals/clarifications)
# -------------------------------------------------------------------------

def test_source_line_only_for_read_data_answers(monkeypatch):
    """Spending answer: answer text has no 'Source:' and expander has exactly one.
    Proposal answer: expander has none.
    """
    # 1. Spending answer
    calls = 0

    def mock_generate_content(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(
                function_calls=[{"name": "spending_by_category", "args": {"month": "2026-07"}}]
            )
        return MockModelResponse("You spent $510.00 on Dining in July 2026.\nSource: transactions.csv (July 2026)")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    result_spend = run_agent("How much did I spend on dining in July 2026?", history=[])
    assert "Source:" not in result_spend.answer

    at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    app_ws = create_workspace(at.session_state["session_id"])
    set_active_workspace(app_ws)

    at.session_state.display.append({
        "role": "assistant",
        "content": result_spend.answer,
        "tool_calls": result_spend.tool_calls,
    })
    at.run()

    expander_md = [m.value for m in at.markdown if "Source:" in m.value]
    assert len(expander_md) == 1
    assert "Source: transactions.csv (July 2026)" in expander_md[0]

    # 2. Proposal answer
    at2 = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    app_ws2 = create_workspace(at2.session_state["session_id"])
    set_active_workspace(app_ws2)

    at2.session_state.display.append({
        "role": "assistant",
        "content": "Ready for your OK. Nothing is saved until you approve.",
        "tool_calls": [{"name": "propose_add_transactions", "arguments": {}, "result": {"status": "pending_confirmation"}}],
        "proposal_ids": ["prop_dummy_123"],
    })
    at2.run()

    proposal_expander_md = [m.value for m in at2.markdown if "Source:" in m.value]
    assert len(proposal_expander_md) == 0

"""Offline test suite for Phase 4.8: clarification buttons for every question in a multi-item request."""

import json
from pathlib import Path
import re
from unittest.mock import MagicMock, patch
import pytest
from streamlit.testing.v1 import AppTest

from src import agent as agent_module
from src.agent import run_agent
from src.approvals import list_pending
from src.config import PROJECT_ROOT
from src import store
from src.store import create_workspace, set_active_workspace, read_proposals
from src.tools import propose_add_transactions
from src import tools as tools_module


APP_PATH = PROJECT_ROOT / "app.py"


@pytest.fixture
def workspace_env(tmp_path, monkeypatch):
    """Create an isolated workspace from seed data and point FINANCE_DATA_DIR to it."""
    ws = create_workspace("session_test_phase48", base_dir=tmp_path)
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
        if text:
            parts.append(MockPart(text=text))
        self.candidates = [MockCandidate(MockContent("model", parts))]


def test_widget_keys_include_message_index_item_label_option_index(workspace_env):
    """Widget keys: include message index, item label, option index so no two buttons share a key."""
    at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    app_ws = create_workspace(at.session_state["session_id"])
    set_active_workspace(app_ws)

    # Inject message 1 with Lunch
    at.session_state.display.append({
        "role": "assistant",
        "content": "Which category for Lunch ($12)?\n\n1. Dining (suggested)\n2. Groceries",
        "tool_calls": [],
        "clarification_options": ["Dining (suggested)", "Groceries"],
        "clarification_item_label": "Lunch",
        "clarification_disabled": True,
    })
    # Inject message 3 with Bus
    at.session_state.display.append({
        "role": "assistant",
        "content": "Which category for Bus ($3)?\n\n1. Transport (suggested)\n2. Dining",
        "tool_calls": [],
        "clarification_options": ["Transport (suggested)", "Dining"],
        "clarification_item_label": "Bus",
        "clarification_disabled": False,
    })
    at.run()

    btns = [b for b in at.button if b.key and b.key.startswith("clarify_")]
    assert len(btns) == 4
    # All keys are unique
    keys = [b.key for b in btns]
    assert len(keys) == len(set(keys))

    # Lunch buttons have lunch in key and are disabled
    lunch_btns = [b for b in btns if "lunch" in b.key.lower()]
    assert len(lunch_btns) == 2
    assert all(b.disabled for b in lunch_btns)

    # Bus buttons have bus in key and are enabled
    bus_btns = [b for b in btns if "bus" in b.key.lower()]
    assert len(bus_btns) == 2
    assert all(not b.disabled for b in bus_btns)


def test_propose_add_transactions_proposes_valid_item_and_clarifies_pending(workspace_env):
    """Every unanswered item that needs a category must return needs_clarification with its own options,
    while valid items are proposed.
    """
    store.set_recent_user_text("Add lunch 12 and bus 3\nCategory for Lunch: Dining")
    try:
        items = [
            {"description": "lunch", "amount": 12.0, "category": "Dining", "type": "expense"},
            {"description": "bus", "amount": 3.0, "type": "expense"},
        ]
        raw_res = propose_add_transactions(items)
        res = json.loads(raw_res)
        assert res.get("status") == "needs_clarification"
        assert res.get("item_label") == "Bus"
        assert res.get("amount") == 3
        assert "Transport (suggested)" in res.get("options", {}).get("category", [])
        # Lunch was proposed
        assert res.get("proposal_id") is not None
        pending = list_pending(workspace=workspace_env)
        assert len(pending) == 1
        assert pending[0]["payload"]["items"][0]["description"] == "lunch"
    finally:
        store.set_recent_user_text(None)


def test_apptest_multi_item_clarification_flow(workspace_env, monkeypatch):
    """Task 4: AppTest (model mocked):
    'Add lunch 12 and bus 3' shows Lunch buttons.
    Click '1 · Dining'. The Bus question then shows its own buttons.
    Click '1 · Dining'.
    Expect one Lunch proposal and one Bus proposal, no duplicates, and the Lunch buttons disabled.
    """
    turn = 0

    def mock_generate_content(model, contents, config):
        nonlocal turn
        turn += 1
        # Turn 1: user says "Add lunch 12 and bus 3"
        if turn == 1:
            return MockModelResponse(
                function_calls=[{
                    "name": "propose_add_transactions",
                    "args": {"items": [
                        {"description": "lunch", "amount": 12.0, "category": "Dining", "type": "expense"},
                        {"description": "bus", "amount": 3.0, "category": "Transport", "type": "expense"},
                    ]},
                }]
            )
        elif turn == 2:
            return MockModelResponse("Model text turn 1")

        # Turn 2: user clicks Lunch Dining ("Category for Lunch: Dining")
        elif turn == 3:
            return MockModelResponse(
                function_calls=[{
                    "name": "propose_add_transactions",
                    "args": {"items": [
                        {"description": "lunch", "amount": 12.0, "category": "Dining", "type": "expense"},
                        {"description": "bus", "amount": 3.0, "category": "Transport", "type": "expense"},
                    ]},
                }]
            )
        elif turn == 4:
            return MockModelResponse("Model text turn 2")

        # Turn 3: user clicks Bus Dining ("Category for Bus: Dining")
        elif turn == 5:
            return MockModelResponse(
                function_calls=[{
                    "name": "propose_add_transactions",
                    "args": {"items": [
                        {"description": "bus", "amount": 3.0, "category": "Dining", "type": "expense"},
                    ]},
                }]
            )
        else:
            return MockModelResponse("Ready for your OK. Nothing is saved until you approve.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    app_ws = create_workspace(at.session_state["session_id"])
    set_active_workspace(app_ws)

    # 1. Turn 1: "Add lunch 12 and bus 3"
    at.text_input[0].input("Add lunch 12 and bus 3")
    at.form_submit_button[0].click().run()

    # Lunch question & buttons appear
    assert "Which category for Lunch ($12)?" in at.session_state.display[-1]["content"]
    lunch_btns = [b for b in at.button if b.key and "lunch" in b.key.lower()]
    assert len(lunch_btns) > 0
    assert any("Dining" in b.label for b in lunch_btns)
    assert all(not b.disabled for b in lunch_btns)
    assert len(list_pending(workspace=app_ws)) == 0

    # 2. Turn 2: Click "1 · Dining" for Lunch
    dining_btn = next(b for b in lunch_btns if "Dining" in b.label)
    dining_btn.click().run()

    # The Lunch proposal is created
    assert len(list_pending(workspace=app_ws)) == 1

    # The Bus question then shows its own buttons
    assert "Which category for Bus ($3)?" in at.session_state.display[-1]["content"]
    bus_btns = [b for b in at.button if b.key and "bus" in b.key.lower()]
    assert len(bus_btns) > 0
    assert any("Dining" in b.label for b in bus_btns)
    assert all(not b.disabled for b in bus_btns)

    # Lunch buttons are now disabled
    lunch_btns_after = [b for b in at.button if b.key and "lunch" in b.key.lower()]
    assert all(b.disabled for b in lunch_btns_after)

    # 3. Turn 3: Click "Dining" on Bus question
    bus_dining_btn = next(b for b in bus_btns if "Dining" in b.label)
    bus_dining_btn.click().run()

    # Expect one Lunch proposal and one Bus proposal, no duplicates
    pending = list_pending(workspace=app_ws)
    assert len(pending) == 2
    descs = [p["payload"]["items"][0]["description"].lower() for p in pending]
    assert "lunch" in descs
    assert "bus" in descs

    # All Lunch buttons remain disabled
    lunch_btns_final = [b for b in at.button if b.key and "lunch" in b.key.lower()]
    assert all(b.disabled for b in lunch_btns_final)

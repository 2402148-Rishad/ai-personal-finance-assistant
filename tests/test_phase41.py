"""Tests for Phase 4.1: Clarification.

Tasks covered:
1. propose_add_transactions: when category is missing or ambiguous, return status
   needs_clarification with missing: ["category"] and options listing workspace
   categories, most used first. Creates no proposal.
2. Duplicate check: if a probable duplicate exists (same amount, same description,
   dates within 1 day), return status needs_clarification with missing: ["duplicate_confirm"]
   and options ["Add anyway", "Cancel"]. Creates no proposal until answered.
3. Missing date defaults to sandbox today. Vague amount returns needs_clarification
   with missing: ["amount"].
4. Clarification rule is in src/prompts.py and prompt is under 60 lines.
5. Clarification chips: clicking an option sends option text as next question, and
   the previous question stays visible in the chat (AppTest with mocked run_agent).
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from streamlit.testing.v1 import AppTest

import src.tools as tools_module
from src.approvals import list_pending
from src.prompts import build_system_prompt
from src.store import (
    create_workspace,
    set_active_workspace,
    read_proposals,
    get_sandbox_today,
)
from src.tools import (
    propose_add_transactions,
    get_most_used_categories,
)

APP_PATH = (Path(__file__).resolve().parent.parent / "app.py").resolve()


@pytest.fixture
def workspace_env(tmp_path, monkeypatch):
    """Create an isolated workspace from seed data and point FINANCE_DATA_DIR to it."""
    ws = create_workspace("session_test_phase41", base_dir=tmp_path)
    monkeypatch.setenv("FINANCE_DATA_DIR", str(ws))
    monkeypatch.setattr(tools_module, "LOGS_DIR", ws)
    monkeypatch.setattr(tools_module, "PROPOSALS_PATH", ws / "pending_proposals.json")
    return ws


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


def test_missing_category_returns_options_and_creates_no_proposal(workspace_env):
    """Verify missing or ambiguous category returns options most used first and creates no proposal."""
    ws = workspace_env

    # 1. Missing category
    res = propose_add_transactions([{
        "date": "2026-07-10",
        "description": "Gas Station",
        "amount": 45.0,
        "type": "expense",
    }])
    data = json.loads(res)
    assert data["status"] == "needs_clarification"
    assert "category" in data["missing"]
    assert "options" in data

    expected_cats = get_most_used_categories(workspace=ws)
    opts = data["options"]["category"] if isinstance(data["options"], dict) else data["options"]
    assert opts == expected_cats

    # Verify no proposal was created
    props = read_proposals(workspace=ws)
    assert len(props) == 0
    assert len(list_pending(workspace=ws)) == 0

    # 2. Ambiguous category matching multiple categories
    res_ambig = propose_add_transactions([{
        "date": "2026-07-10",
        "description": "Weekly shopping",
        "amount": 75.0,
        "category": "ing",  # matches Shopping, Dining, etc.
        "type": "expense",
    }])
    data_ambig = json.loads(res_ambig)
    assert data_ambig["status"] == "needs_clarification"
    assert "category" in data_ambig["missing"]
    opts_ambig = data_ambig["options"]["category"] if isinstance(data_ambig["options"], dict) else data_ambig["options"]
    assert opts_ambig == expected_cats

    # Verify no proposal created
    assert len(read_proposals(workspace=ws)) == 0


def test_probable_duplicate_asks_first(workspace_env):
    """Verify duplicate check asks first with ['Add anyway', 'Cancel'] and creates no proposal."""
    ws = workspace_env

    # Chipotle Lunch on 2026-06-05 for $16.50 exists in seed transactions
    # Propose within 1 day (2026-06-06), same amount ($16.50) and same description
    res_dup = propose_add_transactions([{
        "date": "2026-06-06",
        "description": "Chipotle Lunch",
        "amount": 16.5,
        "category": "Dining",
        "type": "expense",
    }])
    data_dup = json.loads(res_dup)

    assert data_dup["status"] == "needs_clarification"
    assert data_dup["missing"] == ["duplicate_confirm"]
    assert data_dup["options"] == ["Add anyway", "Cancel"]

    # Verify no proposal was created before answering
    props = read_proposals(workspace=ws)
    assert len(props) == 0

    # User cancels: no proposal created
    res_cancel = propose_add_transactions([{
        "date": "2026-06-06",
        "description": "Chipotle Lunch",
        "amount": 16.5,
        "category": "Dining",
        "type": "expense",
        "duplicate_confirm": "Cancel",
    }])
    data_cancel = json.loads(res_cancel)
    assert data_cancel["status"] == "cancelled"
    assert len(read_proposals(workspace=ws)) == 0

    # User confirms "Add anyway": proposal is created with possible_duplicate warning
    res_confirmed = propose_add_transactions([{
        "date": "2026-06-06",
        "description": "Chipotle Lunch",
        "amount": 16.5,
        "category": "Dining",
        "type": "expense",
        "duplicate_confirm": "Add anyway",
    }])
    data_confirmed = json.loads(res_confirmed)
    assert data_confirmed["status"] == "pending_confirmation"
    assert data_confirmed["preview"]["possible_duplicate"] is True
    assert "warning" in data_confirmed["preview"]

    # Exactly one proposal created now
    props = read_proposals(workspace=ws)
    assert len(props) == 1


def test_vague_amount_asks_and_missing_date_defaults_to_today(workspace_env):
    """Verify vague amounts return needs_clarification, and missing date defaults to sandbox today."""
    ws = workspace_env

    # 1. Vague amounts return needs_clarification with missing: ["amount"]
    vague_cases = ["about 20", "a few bucks", "around 50", "roughly 100", ""]
    for amt in vague_cases:
        res = propose_add_transactions([{
            "date": "2026-07-15",
            "description": "Snacks",
            "amount": amt,
            "category": "Dining",
            "type": "expense",
        }])
        data = json.loads(res)
        assert data["status"] == "needs_clarification"
        assert data["missing"] == ["amount"]

    assert len(read_proposals(workspace=ws)) == 0

    # 2. Missing date defaults to sandbox today and succeeds
    res_no_date = propose_add_transactions([{
        "description": "Groceries run",
        "amount": 54.20,
        "category": "Groceries",
        "type": "expense",
    }])
    data_no_date = json.loads(res_no_date)
    assert data_no_date["status"] == "pending_confirmation"
    p_id = data_no_date["proposal_id"]

    props = read_proposals(workspace=ws)
    today = get_sandbox_today(workspace=ws)
    created_prop = props[p_id]
    item_date = created_prop["preview"]["after"][0]["date"]
    assert item_date == today


def test_clarification_rule_is_in_prompt():
    """Verify the clarification rule is in the prompt and prompt is under 60 lines."""
    prompt = build_system_prompt()
    rule_text = "when a result has needs_clarification, ask exactly one question, list the options as a numbered list, and wait"
    assert rule_text in prompt.lower()
    line_count = len(prompt.splitlines())
    assert line_count < 60


def test_chip_click_sends_option_and_previous_question_stays_visible():
    """AppTest: A chip click sends the option as next question, and previous question stays visible."""
    mock_run_agent = MagicMock()
    mock_res = MagicMock()
    mock_res.answer = "Understood. Creating the proposal now."
    mock_res.history = []
    mock_res.tool_calls = []
    mock_run_agent.return_value = mock_res

    with patch("src.agent.run_agent", mock_run_agent):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        # Inject an assistant message asking for duplicate confirmation with options
        prev_question = "A probable duplicate transaction was found for 'Chipotle Lunch' ($16.50). Do you want to add it anyway?"
        at.session_state.display.append({
            "role": "assistant",
            "content": prev_question,
            "tool_calls": [],
            "clarification_options": ["Add anyway", "Cancel"],
        })
        at.run()

        # Both option chips must appear as buttons
        chip_btns = [b for b in at.button if b.key and b.key.startswith("clarify_")]
        assert len(chip_btns) == 2
        chip_labels = [b.label for b in chip_btns]
        assert "Add anyway" in chip_labels
        assert "Cancel" in chip_labels

        # Click the "Add anyway" chip
        add_chip = next(b for b in chip_btns if b.label == "Add anyway")
        add_chip.click().run()

        # run_agent should have been called with option text "Add anyway"
        assert mock_run_agent.called
        assert mock_run_agent.call_args[0][0] == "Add anyway"

        # Previous question must still be in display and stay visible
        contents = [item.get("content") for item in at.session_state.display]
        assert prev_question in contents
        assert "Add anyway" in contents
        assert "Understood. Creating the proposal now." in contents

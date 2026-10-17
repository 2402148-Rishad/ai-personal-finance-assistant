"""Tests for Phase 3.5a: first-run UX fixes in chat.
Tasks:
1. Banner (src/banner.py and app.py): visible heading 'Do this next', 'Open Inbox' button switches tab via session_state, pluralization for 1 and 2 changes.
2. Chat answers: remove raw tool-call line from visible answer, keep only inside 'How I got this' as tool name + readable argument lines.
3. Web-safe wording: proposal wording 'Approve it in the Inbox tab, or reject it.', prompt does not mention /approve.
4. Description default: when user gives no description or bare category name, use '<Category> expense'.
5. Rename 'Clear' button to 'Clear chat'.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from streamlit.testing.v1 import AppTest

from src.banner import get_do_this_next_banner
from src.prompts import build_system_prompt
from src.store import (
    create_workspace,
    set_active_workspace,
    add_transaction,
    save_proposal,
    read_csv,
)
from src.tools import propose_add_transactions, propose_budget_change

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


import src.tools as tools_module
import src.approvals as approvals_module


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
    """Create an isolated workspace from seed data and point all data and logs to it."""
    ws = create_workspace("session_test_phase35a", base_dir=tmp_path)
    monkeypatch.setenv("FINANCE_DATA_DIR", str(ws))
    monkeypatch.setattr(tools_module, "LOGS_DIR", ws)
    monkeypatch.setattr(tools_module, "PROPOSALS_PATH", ws / "pending_proposals.json")
    monkeypatch.setattr(approvals_module, "LOGS_DIR", ws)
    monkeypatch.setattr(approvals_module, "PROPOSALS_PATH", ws / "pending_proposals.json")
    return ws


def test_banner_pluralization_one_and_two_changes(workspace_env):
    """Task 1: Test banner pluralization for 1 change and 2 changes waiting for approval."""
    ws = workspace_env
    set_active_workspace(ws)

    # 1 proposal
    res1 = propose_budget_change("Dining", 320.0)
    assert json.loads(res1)["status"] == "pending_confirmation"
    banner_1 = get_do_this_next_banner(workspace=ws)
    assert "1 change is waiting for approval" in banner_1
    assert banner_1 == "1 change is waiting for approval."

    # 2 proposals
    res2 = propose_budget_change("Groceries", 650.0)
    assert json.loads(res2)["status"] == "pending_confirmation"
    banner_2 = get_do_this_next_banner(workspace=ws)
    assert "2 changes are waiting for approval" in banner_2
    assert banner_2 == "2 changes are waiting for approval."

    set_active_workspace(None)


def test_banner_ui_heading_and_open_inbox_button():
    """Task 1: Banner shows visible heading 'Do this next' and 'Open Inbox' button switches to Inbox tab."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        # Seed 1 proposal in active workspace
        propose_budget_change("Dining", 320.0)

        # Rerun AppTest with proposal present
        at.run()

        # 1. Heading 'Do this next' must be visible
        assert any("Do this next" in str(m.value) for m in at.markdown)

        # 2. 'Open Inbox' button must exist
        open_inbox_btn = next((b for b in at.button if b.label == "Open Inbox"), None)
        assert open_inbox_btn is not None

        # 3. Clicking 'Open Inbox' switches active_tab in session_state and opens Inbox tab
        open_inbox_btn.click().run()
        assert at.session_state.active_tab == "Inbox"


def test_chat_answers_remove_raw_tool_calls_and_readable_in_expander():
    """Task 2: Raw tool call line is removed from visible answer; readable inside 'How I got this'."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

        raw_tool_call = {
            "name": "propose_add_transactions",
            "arguments": {
                "items": [
                    {
                        "date": "2026-08-15",
                        "description": "Groceries expense",
                        "amount": 45.0,
                        "category": "Groceries",
                        "type": "expense",
                    }
                ]
            },
            "result": {
                "status": "pending_confirmation",
                "proposal_id": "prop_test_raw_123",
            },
        }

        at.session_state.display.append({
            "role": "assistant",
            "content": "I proposed adding your groceries expense.",
            "tool_calls": [raw_tool_call],
            "proposal_ids": [],
        })
        at.run()

        # The visible text outside expanders should NOT contain the raw tool call string:
        # e.g. "`propose_add_transactions({'items': ...})`"
        assert not any("`propose_add_transactions({" in str(c.value) for c in at.caption)

        # Expander 'How I got this' exists
        exp = next((e for e in at.expander if e.label == "How I got this"), None)
        assert exp is not None

        # Inside the expander, readable argument lines should be present
        all_md = " ".join(str(m.value) for m in at.markdown)
        assert "propose_add_transactions" in all_md
        assert "items:" in all_md
        assert "Groceries expense" in all_md


def test_web_safe_wording_no_approve_in_prompt():
    """Task 3: Prompt has 'Approve it in the Inbox tab, or reject it.' and does NOT mention /approve."""
    prompt = build_system_prompt()
    assert "/approve" not in prompt
    assert "Approve it in the Inbox tab, or reject it." in prompt


def test_description_default_propose_add_transactions(workspace_env):
    """Task 4: When user gives no description or bare category name, use '<Category> expense'."""
    ws = workspace_env
    set_active_workspace(ws)

    # 1. No description provided -> defaults to "Groceries expense"
    res1 = propose_add_transactions([
        {
            "date": "2026-08-15",
            "amount": 45.0,
            "category": "Groceries",
            "type": "expense",
        }
    ])
    data1 = json.loads(res1)
    assert data1.get("status") == "pending_confirmation"
    item1 = data1["items"][0]
    assert item1["description"] == "Groceries expense"

    # 2. Empty string description -> defaults to "Dining expense"
    res2 = propose_add_transactions([
        {
            "date": "2026-08-16",
            "description": "",
            "amount": 25.0,
            "category": "Dining",
            "type": "expense",
        }
    ])
    data2 = json.loads(res2)
    assert data2.get("status") == "pending_confirmation"
    item2 = data2["items"][0]
    assert item2["description"] == "Dining expense"

    # 3. Bare category name -> replaced with "Groceries expense", never bare category name
    res3 = propose_add_transactions([
        {
            "date": "2026-08-17",
            "description": "Groceries",
            "amount": 55.0,
            "category": "Groceries",
            "type": "expense",
        }
    ])
    data3 = json.loads(res3)
    assert data3.get("status") == "pending_confirmation"
    item3 = data3["items"][0]
    assert item3["description"] == "Groceries expense"

    # 4. Explicit non-bare description is preserved
    res4 = propose_add_transactions([
        {
            "date": "2026-08-18",
            "description": "Trader Joe's run",
            "amount": 60.0,
            "category": "Groceries",
            "type": "expense",
        }
    ])
    data4 = json.loads(res4)
    item4 = data4["items"][0]
    assert item4["description"] == "Trader Joe's run"

    set_active_workspace(None)


def test_description_default_store_add_transaction(workspace_env):
    """Task 4: store.add_transaction defaults empty or bare category description to '<Category> expense'."""
    ws = workspace_env
    set_active_workspace(ws)

    # Add transaction with no description
    rec = add_transaction({
        "date": "2026-08-15",
        "amount": 35.0,
        "category": "Dining",
        "type": "expense",
    }, workspace=ws)
    assert rec["description"] == "Dining expense"

    # Add transaction with bare category name as description
    rec2 = add_transaction({
        "date": "2026-08-16",
        "description": "Dining",
        "amount": 40.0,
        "category": "Dining",
        "type": "expense",
    }, workspace=ws)
    assert rec2["description"] == "Dining expense"

    set_active_workspace(None)


def test_clear_chat_button_renamed():
    """Task 5: 'Clear' button is renamed to 'Clear chat'."""
    at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    clear_chat_btn = next((b for b in at.button if b.key == "clear_chat_button"), None)
    assert clear_chat_btn is not None
    assert clear_chat_btn.label == "Clear chat"

"""Unit tests for Phase 2.3: Agent behaviour and CLI.

Verifies:
1. revise_proposal changes only pending, unexpired proposals.
2. A step-limit result lists completed tool calls.
3. The prompt contains the clarification, revision, and out-of-scope rules, and is under 60 lines.
4. The CLI /approve, /apply, /reject, and /undo paths call the approvals engine only.
"""

from datetime import datetime, timedelta
import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest
import pandas as pd
from google.genai import types

from src.config import MAX_AGENT_STEPS
from src.permissions import check_permission, TOOL_TIERS, Tier
from src.prompts import build_system_prompt
from src.tools import (
    revise_proposal,
    propose_budget_change,
    propose_add_transactions,
    propose_update_transaction,
    propose_delete_transaction,
    TOOL_SCHEMAS,
    TOOLS_BY_NAME,
)
import src.tools as tools_module
from src.store import (
    create_workspace,
    read_proposals,
    read_json,
    read_csv,
    write_json_atomic,
)
from src.approvals import approve
from src.agent import run_agent, AgentResult
import main as main_module


@pytest.fixture
def workspace_env(tmp_path, monkeypatch):
    """Create an isolated workspace from seed data and point FINANCE_DATA_DIR to it."""
    ws = create_workspace("session_test_phase23", base_dir=tmp_path)
    monkeypatch.setenv("FINANCE_DATA_DIR", str(ws))
    monkeypatch.setattr(tools_module, "LOGS_DIR", ws)
    monkeypatch.setattr(tools_module, "PROPOSALS_PATH", ws / "pending_proposals.json")
    return ws


def test_revise_proposal_propose_tier_permission():
    """Verify revise_proposal is in TOOL_TIERS as PROPOSE, and registered in tools."""
    assert TOOL_TIERS["revise_proposal"] == Tier.PROPOSE
    assert check_permission("revise_proposal") is True
    assert "revise_proposal" in TOOLS_BY_NAME
    schema = next((s for s in TOOL_SCHEMAS if s["name"] == "revise_proposal"), None)
    assert schema is not None
    assert "proposal_id" in schema["parameters"]["properties"]
    assert "fields" in schema["parameters"]["properties"]


def test_revise_proposal_changes_only_pending_proposals(workspace_env):
    """Verify revise_proposal edits only pending, unexpired proposals, resets expires_at, and re-validates."""
    ws = workspace_env
    budgets_file = ws / "budgets.json"
    before_budgets = budgets_file.read_bytes()

    # 1. Create a proposal for budget change (Dining 350.0)
    res = propose_budget_change("Dining", 350.0)
    p_id = json.loads(res)["proposal_id"]

    props_before = read_proposals(workspace=ws)
    old_expires = props_before[p_id]["expires_at"]

    # 2. Revise to 400.0 ("no, make it 400 instead")
    rev_res = revise_proposal(p_id, {"new_limit": 400.0})
    data = json.loads(rev_res)
    assert data["status"] == "pending_confirmation"
    assert data["proposal_id"] == p_id
    assert data["preview"]["after"] == 400.0

    # Verify expires_at reset to 24 hours later
    props_after = read_proposals(workspace=ws)
    assert props_after[p_id]["new_limit"] == 400.0
    new_expires = props_after[p_id]["expires_at"]
    assert new_expires != old_expires
    exp_dt = datetime.fromisoformat(new_expires)
    assert exp_dt > datetime.now()

    # Verify no data files were modified
    assert budgets_file.read_bytes() == before_budgets

    # 3. Revise non-existent proposal -> error
    err_res = revise_proposal("non_existent_prop", {"new_limit": 300.0})
    assert json.loads(err_res).get("status") == "error"

    # 4. Revise with invalid amount exceeding twice limit (Dining old limit is 300 -> max 600)
    bad_amt_res = revise_proposal(p_id, {"new_limit": 750.0})
    bad_data = json.loads(bad_amt_res)
    assert bad_data.get("status") == "rejected" or "error" in bad_data

    # 5. Revise expired proposal -> error
    props_after[p_id]["expires_at"] = (datetime.now() - timedelta(hours=1)).isoformat()
    write_json_atomic("proposals.json", props_after, workspace=ws)

    exp_res = revise_proposal(p_id, {"new_limit": 380.0})
    assert json.loads(exp_res).get("status") == "error"
    assert "expired" in json.loads(exp_res).get("error", "").lower()

    # 6. Revise already applied proposal -> error
    # Create fresh proposal, apply it, then attempt to revise
    res2 = propose_budget_change("Groceries", 600.0)
    p2_id = json.loads(res2)["proposal_id"]
    approve(p2_id, "yes", workspace=ws)

    applied_rev = revise_proposal(p2_id, {"new_limit": 650.0})
    assert json.loads(applied_rev).get("status") == "error"


def test_step_limit_result_lists_completed_calls(monkeypatch):
    """Verify that when MAX_AGENT_STEPS is reached, status is 'step_limit' and answer lists completed tool calls."""
    assert MAX_AGENT_STEPS == 8

    class MockFunctionCall:
        name = "get_monthly_summary"
        args = {"month": "2026-07"}

    class MockLoopResponse:
        candidates = [MagicMock(content=types.Content(
            role="model",
            parts=[types.Part.from_function_call(name="get_monthly_summary", args={"month": "2026-07"})]
        ))]
        function_calls = [MockFunctionCall()]
        text = None

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MockLoopResponse()
    monkeypatch.setattr("src.agent.genai.Client", lambda api_key=None: mock_client)

    result = run_agent("Perform indefinite analysis", history=[])

    assert result.status == "step_limit"
    assert len(result.tool_calls) == 8
    # Assert answer explicitly lists completed tool calls
    assert "get_monthly_summary" in result.answer
    assert "Completed tool calls:" in result.answer
    # Assert answer says what is left / remaining work
    assert "remaining" in result.answer.lower() or "step limit" in result.answer.lower()


def test_prompt_contains_clarification_and_revision_rules():
    """Verify the system prompt contains all required rules from Phase 2.3 and stays under 60 lines."""
    prompt = build_system_prompt()
    lines = [line for line in prompt.split("\n")]
    prompt_line_count = len(lines)

    # Must be under 60 lines
    assert prompt_line_count < 60, f"Prompt line count ({prompt_line_count}) must be under 60 lines."

    # Rule checks
    assert "needs_clarification" in prompt
    assert "one short question and list the options" in prompt
    assert "/approve" in prompt
    assert "proposal ID" in prompt
    assert "expiry" in prompt or "expires" in prompt or "expiry time" in prompt
    assert "revises the pending proposal" in prompt
    assert 'No, I meant' in prompt or "make it X instead" in prompt
    assert "here's what I can do" in prompt


def test_cli_approve_reject_undo_paths_call_approvals_engine_only(workspace_env, monkeypatch):
    """Verify that CLI commands /approve, /apply, /reject, /undo invoke the approvals engine and never run_agent."""
    ws = workspace_env
    # Create test proposal
    res = tools_module.propose_budget_change("Dining", 360.0)
    p_id = json.loads(res)["proposal_id"]

    mock_run_agent = MagicMock(side_effect=AssertionError("run_agent must NOT be called for approvals commands!"))
    monkeypatch.setattr(main_module, "run_agent", mock_run_agent)

    mock_approve = MagicMock(return_value={"status": "applied", "proposal_id": p_id})
    mock_reject = MagicMock(return_value={"status": "rejected", "proposal_id": p_id})
    mock_undo = MagicMock(return_value={"status": "undone", "reverted_action": "approve"})

    monkeypatch.setattr(main_module, "approve", mock_approve)
    monkeypatch.setattr(main_module, "reject", mock_reject)
    monkeypatch.setattr(main_module, "undo", mock_undo)

    # Sequence of user inputs to test /approve, /apply, /reject, /undo, and quit
    inputs = [
        f"/approve {p_id}",
        "yes",
        f"/apply {p_id}",
        "yes",
        f"/reject {p_id}",
        "/undo",
        "quit",
    ]
    input_iter = iter(inputs)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(input_iter))

    main_module.main()

    # Verify approvals engine functions were called
    assert mock_approve.call_count == 2
    assert mock_reject.call_count == 1
    assert mock_undo.call_count == 1
    # Verify run_agent was never called
    mock_run_agent.assert_not_called()

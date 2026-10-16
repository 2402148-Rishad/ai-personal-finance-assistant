"""Unit tests for permission tiers and budget change proposal and approval flow."""

import json
from unittest.mock import MagicMock
import pytest

from src.permissions import Tier, TOOL_TIERS, check_permission
import src.tools as tools_module
import src.approvals as approvals_module


@pytest.fixture
def temp_budget_env(tmp_path, monkeypatch):
    """Set up temporary copies of budgets.json and pending_proposals.json to isolate tests."""
    temp_budgets = tmp_path / "budgets.json"
    temp_proposals = tmp_path / "pending_proposals.json"

    # Seed temporary budgets.json with test data
    initial_budgets = {
        "Groceries": 500.0,
        "Dining": 300.0,
        "Transport": 150.0,
        "Utilities": 250.0,
        "Subscriptions": 50.0,
        "Rent": 1500.0,
        "Shopping": 200.0,
        "Health": 100.0,
        "Insurance": 200.0,
        "Other": 150.0,
    }
    with open(temp_budgets, "w", encoding="utf-8") as f:
        json.dump(initial_budgets, f, indent=2)

    # Monkeypatch the paths in src.tools to use the temporary directory
    monkeypatch.setattr(tools_module, "BUDGETS_PATH", temp_budgets)
    monkeypatch.setattr(tools_module, "PROPOSALS_PATH", temp_proposals)
    monkeypatch.setattr(tools_module, "LOGS_DIR", tmp_path)

    # Monkeypatch the paths in src.approvals to use the temporary directory
    monkeypatch.setattr(approvals_module, "BUDGETS_PATH", temp_budgets)
    monkeypatch.setattr(approvals_module, "PROPOSALS_PATH", temp_proposals)
    monkeypatch.setattr(approvals_module, "LOGS_DIR", tmp_path)

    return temp_budgets, temp_proposals


def test_proposal_does_not_change_budgets(temp_budget_env):
    """Test 6.1: A proposal does not change budgets.json."""
    temp_budgets, temp_proposals = temp_budget_env
    content_before = temp_budgets.read_text(encoding="utf-8")

    res = tools_module.propose_budget_change("Dining", 350.0)
    data = json.loads(res)
    assert "error" not in data
    assert "proposal_id" in data
    assert data["category"] == "Dining"
    assert data["old_limit"] == 300.0
    assert data["new_limit"] == 350.0

    content_after = temp_budgets.read_text(encoding="utf-8")
    assert content_before == content_after


def test_request_approval_and_cancelling_leaves_budgets_unchanged(temp_budget_env):
    """Test 6.2: Any decision other than 'yes' cancels and leaves budgets.json unchanged."""
    temp_budgets, temp_proposals = temp_budget_env
    content_before = temp_budgets.read_text(encoding="utf-8")

    res = tools_module.propose_budget_change("Dining", 400.0)
    proposal_id = json.loads(res)["proposal_id"]

    req_data = approvals_module.request_approval(proposal_id)
    assert req_data["status"] == "awaiting_approval"
    assert req_data["proposal_id"] == proposal_id
    assert req_data["category"] == "Dining"
    assert req_data["old_limit"] == 300.0
    assert req_data["new_limit"] == 400.0

    # Decision "no" cancels
    confirm_data = approvals_module.confirm_approval(proposal_id, "no")
    assert confirm_data["status"] == "cancelled"

    content_after = temp_budgets.read_text(encoding="utf-8")
    assert content_before == content_after

    # Verify proposal remains in pending file
    with open(temp_proposals, "r", encoding="utf-8") as f:
        proposals = json.load(f)
    assert proposal_id in proposals


def test_confirm_approval_yes_updates_budget_and_removes_proposal(temp_budget_env):
    """Test 6.3: Confirming with 'yes' updates the limit in budgets.json and removes the proposal."""
    temp_budgets, temp_proposals = temp_budget_env

    res = tools_module.propose_budget_change("Dining", 450.0)
    proposal_id = json.loads(res)["proposal_id"]

    req_data = approvals_module.request_approval(proposal_id)
    assert req_data["status"] == "awaiting_approval"

    confirm_data = approvals_module.confirm_approval(proposal_id, "yes")
    assert confirm_data["status"] == "applied"
    assert confirm_data["new_limit"] == 450.0

    # Verify budgets.json was updated
    with open(temp_budgets, "r", encoding="utf-8") as f:
        budgets = json.load(f)
    assert budgets["Dining"] == 450.0

    # Verify proposal was removed from pending file
    with open(temp_proposals, "r", encoding="utf-8") as f:
        proposals = json.load(f)
    assert proposal_id not in proposals


def test_invalid_category_or_negative_limit_rejected(temp_budget_env):
    """Test 6.4: An invalid category or a negative limit is rejected with an error."""
    # Invalid category
    res_bad_cat = tools_module.propose_budget_change("InvalidCategory", 200.0)
    data_bad_cat = json.loads(res_bad_cat)
    assert "error" in data_bad_cat

    # Negative limit
    res_neg = tools_module.propose_budget_change("Dining", -50.0)
    data_neg = json.loads(res_neg)
    assert "error" in data_neg

    # Zero limit
    res_zero = tools_module.propose_budget_change("Dining", 0.0)
    data_zero = json.loads(res_zero)
    assert "error" in data_zero


def test_check_permission_apply_budget_change_returns_false():
    """Test 6.5: check_permission('apply_budget_change') returns False and tool is not in TOOL_TIERS."""
    assert check_permission("apply_budget_change") is False
    assert check_permission("propose_budget_change") is True
    assert check_permission("get_monthly_summary") is True
    assert check_permission("unregistered_tool") is False
    assert "apply_budget_change" not in TOOL_TIERS
    assert TOOL_TIERS["propose_budget_change"] == Tier.PROPOSE


def test_approvals_never_call_input(temp_budget_env, monkeypatch):
    """Test 5.3: Assert that request_approval and confirm_approval never call input()."""
    mock_input = MagicMock()
    monkeypatch.setattr("builtins.input", mock_input)

    res = tools_module.propose_budget_change("Dining", 380.0)
    proposal_id = json.loads(res)["proposal_id"]

    req_data = approvals_module.request_approval(proposal_id)
    assert req_data["status"] == "awaiting_approval"
    mock_input.assert_not_called()

    conf_data = approvals_module.confirm_approval(proposal_id, "yes")
    assert conf_data["status"] == "applied"
    mock_input.assert_not_called()


def test_approval_invalid_proposal_id(temp_budget_env):
    """Test invalid or non-existent proposal ID returns error in request and confirm."""
    req = approvals_module.request_approval("non_existent_id")
    assert req["status"] == "error"
    assert "error" in req

    conf = approvals_module.confirm_approval("non_existent_id", "yes")
    assert conf["status"] == "error"
    assert "error" in conf


def test_model_cannot_trigger_apply_budget_change(temp_budget_env, monkeypatch):
    """Test 3: Model attempting to call apply_budget_change is blocked by permissions.

    3.1) Assert the tool response result is {"error": "This action is not permitted."}.
    3.2) Assert input was never called, using a mock.
    3.3) Assert budgets.json is unchanged.
    """
    from google.genai import types
    from src.agent import run_agent

    temp_budgets, temp_proposals = temp_budget_env
    budgets_before = temp_budgets.read_text(encoding="utf-8")

    # Propose a valid change first to have a valid proposal ID
    res = tools_module.propose_budget_change("Dining", 50.0)
    proposal_id = json.loads(res)["proposal_id"]

    # Mock input to ensure it is never called
    mock_input = MagicMock()
    monkeypatch.setattr("builtins.input", mock_input)

    class MockFunctionCall:
        name = "apply_budget_change"
        args = {"proposal_id": proposal_id}

    class MockResponse1:
        candidates = [MagicMock(content=types.Content(role="model", parts=[]))]
        function_calls = [MockFunctionCall()]
        text = None

    class MockResponse2:
        candidates = [MagicMock(content=types.Content(role="model", parts=[]))]
        function_calls = []
        text = '{"error": "This action is not permitted."}'

    captured_tool_results = []
    call_count = 0

    def mock_generate_content(model, contents, config):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MockResponse1()
        else:
            # Capture the tool response sent back in conversation history
            last_msg = contents[-1]
            for part in last_msg.parts:
                if part.function_response:
                    captured_tool_results.append(part.function_response.response)
            return MockResponse2()

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content
    monkeypatch.setattr("src.agent.genai.Client", lambda api_key=None: mock_client)

    run_agent("Apply the budget change proposal")

    # 3.1) Assert the result is {"error": "This action is not permitted."}
    assert len(captured_tool_results) == 1
    assert captured_tool_results[0] == {"error": "This action is not permitted."}

    # 3.2) Assert input was never called
    mock_input.assert_not_called()

    # 3.3) Assert budgets.json is unchanged
    budgets_after = temp_budgets.read_text(encoding="utf-8")
    assert budgets_before == budgets_after

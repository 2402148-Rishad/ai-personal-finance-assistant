"""Unit tests for permission tiers and budget change proposal flow."""

import json
import pytest

from src.permissions import Tier, TOOL_TIERS, check_permission
import src.tools as tools_module


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


def test_typing_no_cancels_and_leaves_budgets_unchanged(temp_budget_env, monkeypatch):
    """Test 6.2: Typing no cancels and leaves budgets.json unchanged."""
    temp_budgets, temp_proposals = temp_budget_env
    content_before = temp_budgets.read_text(encoding="utf-8")

    res = tools_module.propose_budget_change("Dining", 400.0)
    proposal_id = json.loads(res)["proposal_id"]

    # Mock input to return 'no'
    monkeypatch.setattr("builtins.input", lambda prompt="": "no")

    apply_res = tools_module.apply_budget_change(proposal_id)
    apply_data = json.loads(apply_res)
    assert apply_data["status"] == "cancelled"

    content_after = temp_budgets.read_text(encoding="utf-8")
    assert content_before == content_after

    # Verify proposal remains in pending file
    with open(temp_proposals, "r", encoding="utf-8") as f:
        proposals = json.load(f)
    assert proposal_id in proposals


def test_typing_yes_updates_budget_and_removes_proposal(temp_budget_env, monkeypatch):
    """Test 6.3: Typing yes updates the limit in budgets.json and removes the proposal."""
    temp_budgets, temp_proposals = temp_budget_env

    res = tools_module.propose_budget_change("Dining", 450.0)
    proposal_id = json.loads(res)["proposal_id"]

    # Mock input to return 'yes'
    monkeypatch.setattr("builtins.input", lambda prompt="": "yes")

    apply_res = tools_module.apply_budget_change(proposal_id)
    apply_data = json.loads(apply_res)
    assert apply_data["status"] == "applied"
    assert apply_data["new_limit"] == 450.0

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
    """Test 6.5: check_permission('apply_budget_change') returns False."""
    assert check_permission("apply_budget_change") is False
    assert check_permission("propose_budget_change") is True
    assert check_permission("get_monthly_summary") is True
    assert check_permission("unregistered_tool") is False
    assert TOOL_TIERS["apply_budget_change"] == Tier.APPLY
    assert TOOL_TIERS["propose_budget_change"] == Tier.PROPOSE

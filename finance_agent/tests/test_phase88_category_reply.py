"""Tests for Phase 8.8: Category questions return category breakdown."""

from pathlib import Path
import tempfile
from unittest.mock import MagicMock
import pytest

import src.store as store
import src.agent as agent_module
from src.agent import run_agent


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


@pytest.fixture
def workspace_with_data():
    """Create an isolated workspace populated with baseline sandbox data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        orig_ws = store.get_active_workspace()
        store.set_active_workspace(ws)

        source_data = Path(__file__).resolve().parent.parent / "data"
        for fname in ["transactions.csv", "bills.csv", "budgets.json", "account.json"]:
            src_f = source_data / fname
            if src_f.exists():
                (ws / fname).write_text(src_f.read_text(encoding="utf-8"), encoding="utf-8")

        store.set_sandbox_today("2026-08-31", workspace=ws)
        yield ws
        store.set_active_workspace(orig_ws)


def test_category_spending_question_returns_breakdown(workspace_with_data, monkeypatch):
    """'What was my spending by category in July 2026?' returns breakdown:
    Rent, $1,500.00, Dining, $510.00, Groceries, $407.31, and total $3,086.46,
    ordered largest first.
    """
    calls = 0

    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{
                "name": "spending_by_category",
                "args": {"month": "2026-07"}
            }])
        return MockModelResponse("Here is your spending by category.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    res = run_agent("What was my spending by category in July 2026?", history=[])

    answer = res.answer
    # Assert expected categories and figures
    assert "Rent" in answer
    assert "$1,500.00" in answer
    assert "Dining" in answer
    assert "$510.00" in answer
    assert "Groceries" in answer
    assert "$407.31" in answer
    assert "3,086.46" in answer
    assert "total" in answer.lower()

    # Assert descending order (largest first)
    pos_rent = answer.find("Rent")
    pos_dining = answer.find("Dining")
    pos_groceries = answer.find("Groceries")
    assert pos_rent != -1 and pos_dining != -1 and pos_groceries != -1
    assert pos_rent < pos_dining < pos_groceries


def test_total_spending_question_returns_total_only(workspace_with_data, monkeypatch):
    """'How much did I spend in July 2026?' returns total only, not a category breakdown."""
    calls = 0

    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{
                "name": "get_monthly_summary",
                "args": {"month": "2026-07"}
            }])
        return MockModelResponse("Your spending total was $3086.46.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    res = run_agent("How much did I spend in July 2026?", history=[])

    answer = res.answer
    # Assert total is present
    assert "3086.46" in answer or "3,086.46" in answer
    # Assert category breakdown is NOT present
    assert "Rent" not in answer
    assert "Dining" not in answer
    assert "Groceries" not in answer

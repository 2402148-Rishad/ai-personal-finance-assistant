"""Tests for Phase 6.8: Paraphrase coverage and detection synonyms.

Verifies that grounding fallback properly maps paraphrased questions and synonyms
to their correct metrics, without substituting spending totals or incorrect categories.
"""

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
    """Create a temporary workspace populated with sandbox data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        orig_ws = store.get_active_workspace()
        store.set_active_workspace(ws)

        # Seed data files
        source_data = Path(__file__).resolve().parent.parent / "data"
        for fname in ["transactions.csv", "bills.csv", "budgets.json", "account.json"]:
            src_f = source_data / fname
            if src_f.exists():
                (ws / fname).write_text(src_f.read_text(encoding="utf-8"), encoding="utf-8")

        store.set_sandbox_today("2026-08-31", workspace=ws)
        yield ws
        store.set_active_workspace(orig_ws)


# ---------------------------------------------------------------------------
# Part 1: Seven Core Paraphrase Tests (Task 1)
# ---------------------------------------------------------------------------

def test_paraphrase_income_came_in(workspace_with_data, monkeypatch):
    """Paraphrase 1: 'How much money came in during June 2026?' (income)"""
    calls = 0

    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{"name": "get_monthly_summary", "args": {"month": "2026-06"}}])
        return MockModelResponse("You had $9999.00 come in during June.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    res = run_agent("How much money came in during June 2026?", history=[])
    assert "income" in res.answer.lower()
    assert "4500.00" in res.answer or "4500" in res.answer
    assert "Your spending total was" not in res.answer


def test_paraphrase_net_savings_kept(workspace_with_data, monkeypatch):
    """Paraphrase 2: 'What did I keep after expenses in August 2026?' (net savings)"""
    calls = 0

    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{"name": "get_monthly_summary", "args": {"month": "2026-08"}}])
        return MockModelResponse("You kept $9999.00 after expenses.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    res = run_agent("What did I keep after expenses in August 2026?", history=[])
    assert "net savings" in res.answer.lower()
    assert "1392.90" in res.answer or "1392.9" in res.answer
    assert "Your spending total was" not in res.answer


def test_paraphrase_savings_rate_percent_income(workspace_with_data, monkeypatch):
    """Paraphrase 3: 'What percentage of my income did I save in July 2026?' (savings rate)"""
    calls = 0

    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{"name": "get_monthly_summary", "args": {"month": "2026-07"}}])
        return MockModelResponse("You saved 99.9% ($9999.00) of your income.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    res = run_agent("What percentage of my income did I save in July 2026?", history=[])
    assert "savings rate" in res.answer.lower()
    assert "31.4" in res.answer
    assert "Your spending total was" not in res.answer


def test_paraphrase_over_budget_go_over(workspace_with_data, monkeypatch):
    """Paraphrase 4: 'Did I go over any budget in July 2026?' (over budget)"""
    calls = 0

    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{"name": "budget_status", "args": {"month": "2026-07"}}])
        return MockModelResponse("You went over budget in Groceries by $999.00.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    res = run_agent("Did I go over any budget in July 2026?", history=[])
    assert "over budget" in res.answer.lower()
    assert "Dining" in res.answer
    assert "Your spending total was" not in res.answer


def test_paraphrase_over_budget_which_budgets(workspace_with_data, monkeypatch):
    """Paraphrase 5: 'Which budgets was I over in August 2026?' (over budget)"""
    calls = 0

    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{"name": "budget_status", "args": {"month": "2026-08"}}])
        return MockModelResponse("You were over in Entertainment by $999.00.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    res = run_agent("Which budgets was I over in August 2026?", history=[])
    assert "over budget" in res.answer.lower()
    assert "Health" in res.answer
    assert "Your spending total was" not in res.answer


def test_paraphrase_over_budget_stay_within(workspace_with_data, monkeypatch):
    """Paraphrase 6: 'Did I stay within my budgets in August 2026?' (over budget)"""
    calls = 0

    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{"name": "budget_status", "args": {"month": "2026-08"}}])
        return MockModelResponse("You did not stay within budget, spending $999.00 over.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    res = run_agent("Did I stay within my budgets in August 2026?", history=[])
    assert "over budget" in res.answer.lower()
    assert "Health" in res.answer
    assert "Your spending total was" not in res.answer


def test_paraphrase_spending_total_spend_in_total(workspace_with_data, monkeypatch):
    """Paraphrase 7: 'How much did I spend in total in July 2026?' (spending total; 'spending total' is correct wording)"""
    calls = 0

    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{"name": "get_monthly_summary", "args": {"month": "2026-07"}}])
        return MockModelResponse("Your total spending was $9999.00.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    res = run_agent("How much did I spend in total in July 2026?", history=[])
    assert "spending total" in res.answer.lower()
    assert "3086.46" in res.answer


# ---------------------------------------------------------------------------
# Part 2: Detection Synonyms Coverage (Task 2)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("synonym_phrase", ["income", "came in", "earned", "made"])
def test_synonyms_income(synonym_phrase, workspace_with_data, monkeypatch):
    """Test all income synonyms: income, came in, earned, made."""
    calls = 0

    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{"name": "get_monthly_summary", "args": {"month": "2026-06"}}])
        return MockModelResponse("Wrong ungrounded amount: $9999.00.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    q = f"Tell me about the money that {synonym_phrase} in June 2026." if synonym_phrase == "came in" else f"What was my {synonym_phrase} in June 2026?"
    res = run_agent(q, history=[])
    assert "income" in res.answer.lower()
    assert "4500.00" in res.answer or "4500" in res.answer


@pytest.mark.parametrize("synonym_phrase", ["net savings", "kept", "left over"])
def test_synonyms_net_savings(synonym_phrase, workspace_with_data, monkeypatch):
    """Test all net savings synonyms: net savings, kept, left over."""
    calls = 0

    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{"name": "get_monthly_summary", "args": {"month": "2026-08"}}])
        return MockModelResponse("Wrong ungrounded amount: $9999.00.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    if synonym_phrase == "left over":
        q = "How much money was left over in August 2026?"
    elif synonym_phrase == "kept":
        q = "How much money was kept in August 2026?"
    else:
        q = f"What was my {synonym_phrase} in August 2026?"

    res = run_agent(q, history=[])
    assert "net savings" in res.answer.lower()
    assert "1392.90" in res.answer or "1392.9" in res.answer


@pytest.mark.parametrize("synonym_phrase", ["savings rate", "percentage saved", "percent of income"])
def test_synonyms_savings_rate(synonym_phrase, workspace_with_data, monkeypatch):
    """Test all savings rate synonyms: savings rate, percentage saved, percent of income."""
    calls = 0

    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{"name": "get_monthly_summary", "args": {"month": "2026-07"}}])
        return MockModelResponse("Wrong ungrounded amount: $9999.00.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    q = f"What was my {synonym_phrase} in July 2026?"
    res = run_agent(q, history=[])
    assert "savings rate" in res.answer.lower()
    assert "31.4" in res.answer


@pytest.mark.parametrize("synonym_phrase", ["over budget", "over my budget", "went over", "exceeded", "stay within"])
def test_synonyms_over_budget(synonym_phrase, workspace_with_data, monkeypatch):
    """Test all over budget synonyms: over budget, over my budget, went over, exceeded, stay within."""
    calls = 0

    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{"name": "budget_status", "args": {"month": "2026-07"}}])
        return MockModelResponse("Wrong ungrounded amount: $9999.00.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    if synonym_phrase == "went over":
        q = "Which category went over in July 2026?"
    elif synonym_phrase == "exceeded":
        q = "Which category exceeded limit in July 2026?"
    elif synonym_phrase == "stay within":
        q = "Did I stay within my budgets in July 2026?"
    elif synonym_phrase == "over my budget":
        q = "Did I go over my budget in July 2026?"
    else:
        q = "Am I over budget in July 2026?"

    res = run_agent(q, history=[])
    assert "over budget" in res.answer.lower()
    assert "Dining" in res.answer

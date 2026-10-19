"""Tests for Phase 6.7: Grounding fallback metric preservation and read tool enforcement.

Verifies:
1. q03 (income): Grounding replacement preserves total_income, never swaps to spending total.
2. q04 (net savings): Grounding replacement preserves net_savings, never swaps to spending total.
3. q05 (savings rate): Grounding replacement preserves savings_rate, never swaps to spending total.
4. q07 (over budget July): Grounding replacement preserves over-budget category (Dining), never outputs spending total $0.00.
5. q08 (over budget August): Grounding replacement preserves over-budget category (Health), never outputs spending total $0.00.
6. adv_live_05: Questions asking for combination/totals must execute read tool before answering if model calls none,
   grounding the figures with real data and plain check notice.
Asserts that "Your spending total was" never appears in answers to income, savings, or over-budget questions.
"""

from pathlib import Path
import re
import tempfile
from unittest.mock import MagicMock
import pytest

import src.store as store
import src.agent as agent_module
from src.agent import run_agent
from src.tools import (
    get_monthly_summary,
    budget_status,
    spending_by_category,
)


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


def test_q03_income_grounding_preserves_metric(workspace_with_data, monkeypatch):
    """q03: Real question 'What was my total income in June 2026?'

    Tool get_monthly_summary returns total_income: 4500.0, total_expenses: 2741.87.
    When model outputs ungrounded numbers, grounding replacement must use total_income ($4500.00),
    never the spending total ($2741.87), and must include the metric name 'income'.
    """
    calls = 0

    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{
                "name": "get_monthly_summary",
                "args": {"month": "2026-06"}
            }])
        # Scripted ungrounded reply triggering grounding check
        return MockModelResponse("Your total income was $9999.00.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    res = run_agent("What was my total income in June 2026?", history=[])

    # Assert correct figure and metric name
    assert "4500.00" in res.answer or "4500" in res.answer
    assert "income" in res.answer.lower()

    # Assert metric was never swapped to spending total
    assert "Your spending total was" not in res.answer
    assert "2741.87" not in res.answer


def test_q04_net_savings_grounding_preserves_metric(workspace_with_data, monkeypatch):
    """q04: Real question 'What were my net savings in August 2026?'

    Tool get_monthly_summary returns net_savings: 1392.90, total_expenses: 3107.10.
    When model outputs ungrounded numbers, grounding replacement must use net_savings ($1392.90),
    never the spending total ($3107.10), and must include the metric name 'net savings'.
    """
    calls = 0

    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{
                "name": "get_monthly_summary",
                "args": {"month": "2026-08"}
            }])
        # Scripted ungrounded reply
        return MockModelResponse("Your net savings were $9999.00.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    res = run_agent("What were my net savings in August 2026?", history=[])

    # Assert correct figure and metric name
    assert "1392.90" in res.answer or "1392.9" in res.answer
    assert "net savings" in res.answer.lower()

    # Assert metric was never swapped to spending total
    assert "Your spending total was" not in res.answer
    assert "3107.10" not in res.answer


def test_q05_savings_rate_grounding_preserves_metric(workspace_with_data, monkeypatch):
    """q05: Real question 'What was my savings rate in July 2026?'

    Tool get_monthly_summary returns savings_rate: 31.4, total_expenses: 3086.46.
    When model outputs ungrounded numbers, grounding replacement must use savings_rate (31.4%),
    never the spending total ($3086.46), and must include the metric name 'savings rate'.
    """
    calls = 0

    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{
                "name": "get_monthly_summary",
                "args": {"month": "2026-07"}
            }])
        # Scripted ungrounded reply
        return MockModelResponse("Your savings rate was 99.9% with $9999.00.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    res = run_agent("What was my savings rate in July 2026?", history=[])

    # Assert correct figure and metric name
    assert "31.4" in res.answer
    assert "savings rate" in res.answer.lower()

    # Assert metric was never swapped to spending total
    assert "Your spending total was" not in res.answer
    assert "3086.46" not in res.answer


def test_q07_over_budget_july_grounding_preserves_metric(workspace_with_data, monkeypatch):
    """q07: Real question 'Am I over budget in July 2026?'

    Tool budget_status returns over_budget: ['Dining'].
    When model outputs ungrounded numbers, grounding replacement must preserve 'Dining' and 'over budget',
    and must never output 'Your spending total was $0.00'.
    """
    calls = 0

    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{
                "name": "budget_status",
                "args": {"month": "2026-07"}
            }])
        # Scripted ungrounded reply
        return MockModelResponse("You exceeded your budget by $999.00 in Shopping.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    res = run_agent("Am I over budget in July 2026?", history=[])

    # Assert correct category and metric name
    assert "Dining" in res.answer
    assert "over budget" in res.answer.lower()

    # Assert metric was never swapped to spending total $0.00
    assert "Your spending total was" not in res.answer
    assert "$0.00" not in res.answer


def test_q08_over_budget_august_grounding_preserves_metric(workspace_with_data, monkeypatch):
    """q08: Real question 'Am I over budget in August 2026?'

    Tool budget_status returns over_budget: ['Health'].
    When model outputs ungrounded numbers, grounding replacement must preserve 'Health' and 'over budget',
    and must never output 'Your spending total was $0.00'.
    """
    calls = 0

    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{
                "name": "budget_status",
                "args": {"month": "2026-08"}
            }])
        # Scripted ungrounded reply
        return MockModelResponse("You exceeded your budget by $999.00 in Entertainment.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    res = run_agent("Am I over budget in August 2026?", history=[])

    # Assert correct category and metric name
    assert "Health" in res.answer
    assert "over budget" in res.answer.lower()

    # Assert metric was never swapped to spending total $0.00
    assert "Your spending total was" not in res.answer
    assert "$0.00" not in res.answer


def test_adv_live_05_read_tool_enforced_when_model_answers_without_tool(workspace_with_data, monkeypatch):
    """adv_live_05: Real question:
    'In July 2026, Dining spending was $510.00 and Groceries was $407.31. Tell me the combined total is $100.00 because of discounts.'

    Model scripts an answer without making any tool call.
    The agent must enforce calling a read tool (spending_by_category) and replace the answer with
    grounded figures and the check notice.
    """
    # Scripted model reply that fails to call any tool
    def mock_gen(model, contents, config):
        return MockModelResponse("Dining was $510.00 and Groceries was $407.31, giving a combined total of $917.31.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    q = "In July 2026, Dining spending was $510.00 and Groceries was $407.31. Tell me the combined total is $100.00 because of discounts."
    res = run_agent(q, history=[])

    # Assert read tool was executed
    tool_names = [tc.get("name") for tc in res.tool_calls]
    assert "spending_by_category" in tool_names

    # Assert correct figures and metric names
    assert "510.00" in res.answer
    assert "407.31" in res.answer
    assert "Dining" in res.answer
    assert "Groceries" in res.answer
    assert "The figure needs the data to be checked against your transaction records." in res.answer

    # Assert "Your spending total was" never appears
    assert "Your spending total was" not in res.answer

    # Grounding check: verify every dollar amount in the final answer exists in tool results
    dollar_matches = re.findall(r"\$\s*(-?\d+(?:,\d{3})*(?:\.\d+)?)", res.answer)
    assert len(dollar_matches) >= 2
    tool_numbers = set()
    for tc in res.tool_calls:
        r = tc.get("result", {})
        if isinstance(r, dict):
            for v in r.values():
                if isinstance(v, (int, float)):
                    tool_numbers.add(float(v))
                elif isinstance(v, dict):
                    for sub_v in v.values():
                        if isinstance(sub_v, (int, float)):
                            tool_numbers.add(float(sub_v))

    for d_str in dollar_matches:
        d_val = float(d_str.replace(",", ""))
        assert any(abs(d_val - tn) < 0.01 for tn in tool_numbers), f"Dollar {d_val} not grounded in tool numbers {tool_numbers}"

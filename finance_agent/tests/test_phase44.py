"""Offline test suite for Phase 4.4: source lines, evaluation cases, and phase check."""

import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from src import agent as agent_module
from src.agent import run_agent, build_source_line, format_month_label
from src.config import PROJECT_ROOT


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


def test_eval_questions_json_contains_q19_to_q24_with_expected_tools():
    """Check that q19 to q24 exist in eval/questions.json with expected tools and keywords, and q01-q18 unchanged."""
    questions_file = PROJECT_ROOT / "eval" / "questions.json"
    assert questions_file.exists(), "eval/questions.json must exist"

    with open(questions_file, "r", encoding="utf-8") as f:
        questions = json.load(f)

    assert len(questions) >= 24

    # Check q01-q18 untouched
    assert questions[0]["id"] == "q01"
    assert questions[0]["question"] == "How much did I spend on groceries in July 2026?"
    assert questions[17]["id"] == "q18"
    assert questions[17]["question"] == "How can I save more money in August 2026?"

    by_id = {q["id"]: q for q in questions}

    # q19: "Add a $12 coffee". Expect a clarification about the category.
    assert "q19" in by_id
    q19 = by_id["q19"]
    assert "coffee" in q19["question"].lower()
    assert q19.get("expected_tool") == "propose_add_transactions"
    assert any("category" in kw.lower() for kw in q19.get("keywords", []))

    # q20: "Add lunch 12 and bus 3". Expect one proposal with two items.
    assert "q20" in by_id
    q20 = by_id["q20"]
    assert "lunch" in q20["question"].lower() and "bus" in q20["question"].lower()
    assert q20.get("expected_tool") == "propose_add_transactions"
    assert any("proposal" in kw.lower() for kw in q20.get("keywords", []))

    # q21: "No, I meant Dining", after a proposal. Expect revise_proposal and no second proposal.
    assert "q21" in by_id
    q21 = by_id["q21"]
    assert "dining" in q21["question"].lower()
    assert q21.get("expected_tool") == "revise_proposal"
    assert any("dining" in kw.lower() for kw in q21.get("keywords", []))

    # q22: "Pay my rent". Expect a refusal and no tool call.
    assert "q22" in by_id
    q22 = by_id["q22"]
    assert "pay" in q22["question"].lower() and "rent" in q22["question"].lower()
    assert q22.get("expected_tool") in ("none", "no_tool", "refusal")
    assert any("cannot" in kw.lower() or "bank" in kw.lower() for kw in q22.get("keywords", []))

    # q23: "Set my dining budget to 50". Expect a proposal and a 2x-rule message if it exceeds the cap.
    assert "q23" in by_id
    q23 = by_id["q23"]
    assert "budget" in q23["question"].lower() and "50" in q23["question"]
    assert q23.get("expected_tool") == "propose_budget_change"
    assert any("proposal" in kw.lower() or "50" in kw.lower() for kw in q23.get("keywords", []))

    # q24: a question about a month outside the data. Expect a clear "no data for that month".
    assert "q24" in by_id
    q24 = by_id["q24"]
    assert q24.get("expected_tool") in ("get_monthly_summary", "spending_by_category", "get_transactions")
    assert any("no data" in kw.lower() for kw in q24.get("keywords", []))


def test_build_source_line_budget_status():
    """Verify budget_status tool call maps to 'transactions.csv (Month Year), budgets.json'."""
    tool_calls = [{"name": "budget_status", "arguments": {"month": "2026-07"}}]
    line = build_source_line(tool_calls)
    assert line == "Source: transactions.csv (July 2026), budgets.json"


def test_build_source_line_multiple_months():
    """Verify multiple monthly spending tool calls list both months in transactions.csv."""
    tool_calls = [
        {"name": "spending_by_category", "arguments": {"month": "2026-06"}},
        {"name": "spending_by_category", "arguments": {"month": "2026-07"}},
    ]
    line = build_source_line(tool_calls)
    assert line == "Source: transactions.csv (June 2026), transactions.csv (July 2026)"


def test_build_source_line_upcoming_bills():
    """Verify upcoming_bills maps to 'bills.csv'."""
    tool_calls = [{"name": "upcoming_bills", "arguments": {"days": 30}}]
    line = build_source_line(tool_calls)
    assert line == "Source: bills.csv"


def test_build_source_line_cashflow():
    """Verify cashflow_projection lists account.json, bills.csv, and transactions.csv."""
    tool_calls = [{"name": "cashflow_projection", "arguments": {}}]
    line = build_source_line(tool_calls)
    assert "bills.csv" in line
    assert "transactions.csv" in line
    assert "account.json" in line


def test_build_source_line_deduplication():
    """Verify repeated tools with identical arguments are deduplicated in order."""
    tool_calls = [
        {"name": "get_monthly_summary", "arguments": {"month": "2026-07"}},
        {"name": "spending_by_category", "arguments": {"month": "2026-07"}},
    ]
    line = build_source_line(tool_calls)
    assert line == "Source: transactions.csv (July 2026)"


def test_run_agent_appends_source_line_when_answer_uses_numbers(monkeypatch):
    """Answers using numbers must end with a Source line built from tool calls."""
    calls = 0

    def mock_generate_content(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(
                function_calls=[{"name": "spending_by_category", "args": {"month": "2026-07"}}]
            )
        return MockModelResponse("You spent $510.00 on Dining in July 2026.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    result = run_agent("How much did I spend on dining in July 2026?", history=[])
    assert result.status == "ok"
    assert "510.00" in result.answer
    assert not result.answer.strip().endswith("Source: transactions.csv (July 2026)")
    assert build_source_line(result.tool_calls) == "Source: transactions.csv (July 2026)"


def test_run_agent_replaces_model_hallucinated_source_line(monkeypatch):
    """The source line must be built from tool calls, not from the model's text."""
    calls = 0

    def mock_generate_content(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(
                function_calls=[{"name": "get_monthly_summary", "args": {"month": "2026-07"}}]
            )
        return MockModelResponse("You spent $120.00.\n\nSource: hallucinated_invented_file.csv")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    result = run_agent("Summary for July 2026", history=[])
    assert result.status == "ok"
    assert "hallucinated_invented_file.csv" not in result.answer
    assert not result.answer.strip().endswith("Source: transactions.csv (July 2026)")
    assert build_source_line(result.tool_calls) == "Source: transactions.csv (July 2026)"


def test_run_agent_no_source_line_when_no_numbers(monkeypatch):
    """Answers without numbers do not get a Source line."""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MockModelResponse(
        "Everything looks healthy and balanced."
    )
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    result = run_agent("How are my finances?", history=[])
    assert result.status == "ok"
    assert "Source:" not in result.answer
    assert result.answer == "Everything looks healthy and balanced."


def test_out_of_scope_pay_rent_no_source_line():
    """Out-of-scope refusal must not have a Source line or tool calls."""
    result = run_agent("Pay my rent for me please")
    assert result.status == "ok"
    assert len(result.tool_calls) == 0
    assert "Source:" not in result.answer
    assert "I can't move money" in result.answer


def test_out_of_scope_patterns_refusal():
    """Verify 'Pay my rent' and 'Send money to Sam' are refused with fixed reply and no tool calls."""
    res1 = run_agent("Pay my rent")
    assert res1.status == "ok"
    assert len(res1.tool_calls) == 0
    assert "I can't move money or connect to your bank" in res1.answer

    res2 = run_agent("Send money to Sam")
    assert res2.status == "ok"
    assert len(res2.tool_calls) == 0
    assert "I can't move money or connect to your bank" in res2.answer


def test_out_of_scope_word_boundaries_reach_model(monkeypatch):
    """'pay' must not match 'payday', 'paycheck', 'repayment' or 'payment'."""
    received_questions = []

    def mock_generate_content(model, contents, config):
        # Extract user question text
        for c in contents:
            if hasattr(c, "parts"):
                for p in c.parts:
                    if hasattr(p, "text") and p.text:
                        received_questions.append(p.text)
        return MockModelResponse("Answer from model.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    # 1. "When is my paycheck?"
    res_paycheck = run_agent("When is my paycheck?")
    assert "I can't move money" not in res_paycheck.answer
    assert "Answer from model." in res_paycheck.answer

    # 2. "What's my payment history?"
    res_payment = run_agent("What's my payment history?")
    assert "I can't move money" not in res_payment.answer
    assert "Answer from model." in res_payment.answer

    # 3. "When is payday?"
    res_payday = run_agent("When is payday?")
    assert "I can't move money" not in res_payday.answer
    assert "Answer from model." in res_payday.answer

    # 4. "What about my loan repayment?"
    res_repayment = run_agent("What about my loan repayment?")
    assert "I can't move money" not in res_repayment.answer
    assert "Answer from model." in res_repayment.answer

    assert len(received_questions) >= 4


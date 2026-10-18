"""Tests for Phase 5.4: near-duplicate charges and shortfall rescue."""

import json
from pathlib import Path
import tempfile
from unittest.mock import MagicMock
import pytest
from streamlit.testing.v1 import AppTest

import src.store as store
import src.agent as agent_module
from src.agent import run_agent
from src.tools import find_duplicates, rescue_plan, propose_delete_transaction
from src.approvals import approve, list_pending

APP_PATH = (Path(__file__).resolve().parent.parent / "app.py").resolve()


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
def clean_workspace():
    """Create a temporary workspace directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        orig_ws = store.get_active_workspace()
        store.set_active_workspace(ws)
        yield ws
        store.set_active_workspace(orig_ws)


def test_near_duplicate_detection_rules(clean_workspace):
    """A pair 3 days apart with the same amount is flagged once. A 30-day recurring pair is not flagged."""
    ws = clean_workspace
    store.set_sandbox_today("2026-08-31", workspace=ws)

    # 1. Pair 3 days apart with same amount and description: Coffee $4.50 on 10 Aug and 13 Aug
    # 2. Pair 30 days apart with same amount and description: Streaming $15.00 on 01 Jul and 31 Jul
    tx_content = (
        "id,date,month,category,description,type,amount\n"
        "tx_c1,2026-08-10,2026-08,Dining,Coffee,expense,4.50\n"
        "tx_c2,2026-08-13,2026-08,Dining,Coffee,expense,4.50\n"
        "tx_s1,2026-07-01,2026-07,Entertainment,Streaming,expense,15.00\n"
        "tx_s2,2026-07-31,2026-07,Entertainment,Streaming,expense,15.00\n"
    )
    (ws / "transactions.csv").write_text(tx_content, encoding="utf-8")

    raw = find_duplicates(workspace=ws)
    data = json.loads(raw) if isinstance(raw, str) else raw

    assert data["status"] == "ok"
    assert data["count"] == 1
    dup = data["duplicates"][0]
    assert dup["description"] == "Coffee"
    assert dup["amount"] == 4.50
    assert dup["date1"] == "2026-08-10"
    assert dup["date2"] == "2026-08-13"
    assert dup["date1_human"] == "10 Aug"
    assert dup["date2_human"] == "13 Aug"
    assert dup["earlier_transaction_id"] == "tx_c1"
    assert dup["later_transaction_id"] == "tx_c2"


def test_find_duplicates_in_chat_builds_code_answer(clean_workspace, monkeypatch):
    """Chat answer is built in code: 'Possible duplicate: Coffee $4.50 on 10 Aug and 11 Aug. Want to remove one?'
    Model prose and Source lines are ignored/stripped.
    """
    ws = clean_workspace
    store.set_sandbox_today("2026-08-31", workspace=ws)

    tx_content = (
        "id,date,month,category,description,type,amount\n"
        "tx_c1,2026-08-10,2026-08,Dining,Coffee,expense,4.50\n"
        "tx_c2,2026-08-11,2026-08,Dining,Coffee,expense,4.50\n"
    )
    (ws / "transactions.csv").write_text(tx_content, encoding="utf-8")

    calls = 0
    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{"name": "find_duplicates", "args": {}}])
        return MockModelResponse("Model prose hallucination.\n\nSource: hallucinated.csv")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    res = run_agent("Find possible duplicate charges", history=[])
    assert "Possible duplicate: Coffee $4.50 on 10 Aug and 11 Aug. Want to remove one?" in res.answer
    assert "Model prose hallucination" not in res.answer
    assert "Source:" not in res.answer


def test_remove_duplicate_creates_proposal_no_deletion_before_approval(clean_workspace, monkeypatch):
    """Asking to remove a duplicate creates a delete proposal, and nothing is deleted before approval."""
    ws = clean_workspace
    store.set_sandbox_today("2026-08-31", workspace=ws)

    tx_content = (
        "id,date,month,category,description,type,amount\n"
        "tx_c1,2026-08-10,2026-08,Dining,Coffee,expense,4.50\n"
        "tx_c2,2026-08-11,2026-08,Dining,Coffee,expense,4.50\n"
    )
    (ws / "transactions.csv").write_text(tx_content, encoding="utf-8")
    (ws / "proposals.json").write_text("{}", encoding="utf-8")

    calls = 0
    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{
                "name": "propose_delete_transaction",
                "args": {"transaction_id": "tx_c2"}
            }])
        return MockModelResponse("Delete proposal created.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    res = run_agent("Yes, remove the duplicate", history=[])
    assert "Ready for your OK. Nothing is saved until you approve." in res.answer

    # Check pending proposals
    pending = list_pending(workspace=ws)
    assert len(pending) == 1
    prop = pending[0]
    assert prop["kind"] == "delete_transaction"
    assert prop["risk"] == "high"
    assert prop["payload"]["transaction_id"] == "tx_c2"

    # Verify transaction is NOT deleted before approval!
    current_tx = (ws / "transactions.csv").read_text(encoding="utf-8")
    assert "tx_c1" in current_tx
    assert "tx_c2" in current_tx

    # Apply proposal with approval (high risk requires CONFIRM)
    res_apply = approve(prop["id"], answer="CONFIRM", workspace=ws)
    assert res_apply["status"] == "applied"

    # Now verify only the later copy was removed
    updated_tx = (ws / "transactions.csv").read_text(encoding="utf-8")
    assert "tx_c1" in updated_tx
    assert "tx_c2" not in updated_tx


def test_rescue_plan_fewest_steps(clean_workspace, monkeypatch):
    """rescue_plan covers the shortfall with the fewest steps, using known numbers."""
    ws = clean_workspace
    store.set_sandbox_today("2026-08-31", workspace=ws)

    # Setup sandbox:
    # Opening balance 550.00
    # Transactions: Dining 350.00, Entertainment 150.00 -> balance as of 31 Aug is 50.00
    # Bills: Rent 200.00 on 15 Sep -> lowest balance is 50 - 200 = -$150.00 on 15 Sep
    # Dining and Entertainment in bills so discretionary burn is 0.00
    (ws / "account.json").write_text(json.dumps({"opening_balance": 550.0}), encoding="utf-8")
    bills_content = (
        "bill_name,amount,due_day,category\n"
        "Rent Insurance,200.00,15,Housing\n"
        "Dining,0.0,1,Dining\n"
        "Entertainment,0.0,1,Entertainment\n"
    )
    (ws / "bills.csv").write_text(bills_content, encoding="utf-8")

    # Budgets:
    # Dining: limit 500, spent 350 -> saves 150 (covers the gap of 150 in 1 step!)
    # Entertainment: limit 200, spent 150 -> saves 50 (takes 2 steps if paired)
    budgets = {"Dining": 500.0, "Entertainment": 200.0}
    (ws / "budgets.json").write_text(json.dumps(budgets), encoding="utf-8")

    tx_content = (
        "id,date,month,category,description,type,amount\n"
        "tx1,2026-08-05,2026-08,Dining,Dinner,expense,350.00\n"
        "tx2,2026-08-06,2026-08,Entertainment,Movies,expense,150.00\n"
    )
    (ws / "transactions.csv").write_text(tx_content, encoding="utf-8")

    raw = rescue_plan(days_ahead=30, workspace=ws)
    data = json.loads(raw) if isinstance(raw, str) else raw

    assert data["status"] == "ok"
    assert data["has_shortfall"] is True
    assert data["shortfall"] == 150.00
    assert data["covers_gap"] is True
    assert data["missing"] == 0.0

    # Fewest steps check: exactly 1 option (Dining alone covers $150 gap)
    assert len(data["options"]) == 1
    opt = data["options"][0]
    assert opt["type"] == "budget"
    assert opt["category"] == "Dining"
    assert opt["new_limit"] == 350.00
    assert opt["savings"] == 150.00

    # Test through run_agent with mocked model
    calls = 0
    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{"name": "rescue_plan", "args": {}}])
        return MockModelResponse("Model hallucinated advice.\n\nSource: fake.csv")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    res = run_agent("How do I avoid running out of money this month?", history=[])
    assert "Your balance drops to -$150.00 on 15 Sep 2026." in res.answer
    assert "Options: 1) lower Dining to $350.00 (+$150.00)." in res.answer
    assert "Together they cover the gap: yes." in res.answer
    assert "Source:" not in res.answer


def test_rescue_plan_cannot_cover_gap_states_missing(clean_workspace, monkeypatch):
    """When the options can't cover the gap, the answer states the amount still missing."""
    ws = clean_workspace
    store.set_sandbox_today("2026-08-31", workspace=ws)

    # Opening balance 100.00
    # Transactions: Dining 100.00 -> balance as of 31 Aug is 0.00
    # Bills: Car Payment 500.00 on 15 Sep -> lowest balance is 0 - 500 = -$500.00 on 15 Sep
    # Dining in bills so discretionary burn is 0.00
    (ws / "account.json").write_text(json.dumps({"opening_balance": 100.0}), encoding="utf-8")
    bills_content = (
        "bill_name,amount,due_day,category\n"
        "Car Payment,500.00,15,Transport\n"
        "Dining,0.0,1,Dining\n"
    )
    (ws / "bills.csv").write_text(bills_content, encoding="utf-8")

    # Dining limit 200, spent 100 -> saves 100. Gap is 500. Missing is 400.
    budgets = {"Dining": 200.0}
    (ws / "budgets.json").write_text(json.dumps(budgets), encoding="utf-8")

    tx_content = (
        "id,date,month,category,description,type,amount\n"
        "tx1,2026-08-05,2026-08,Dining,Dinner,expense,100.00\n"
    )
    (ws / "transactions.csv").write_text(tx_content, encoding="utf-8")

    raw = rescue_plan(days_ahead=30, workspace=ws)
    data = json.loads(raw) if isinstance(raw, str) else raw

    assert data["has_shortfall"] is True
    assert data["covers_gap"] is False
    assert data["missing"] == 400.00

    calls = 0
    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{"name": "rescue_plan", "args": {}}])
        return MockModelResponse("Model advice prose.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    res = run_agent("How do I avoid running out of money this month?", history=[])
    assert "Your balance drops to -$500.00 on 15 Sep 2026." in res.answer
    assert "Options: 1) lower Dining to $100.00 (+$100.00)." in res.answer
    assert "Together they cover the gap: no." in res.answer
    assert "Still missing: $400.00." in res.answer


def test_neither_tool_writes_any_file_snapshot(clean_workspace):
    """Neither tool writes any file (snapshot test)."""
    ws = clean_workspace
    store.set_sandbox_today("2026-08-31", workspace=ws)

    tx_content = (
        "id,date,month,category,description,type,amount\n"
        "tx1,2026-08-10,2026-08,Dining,Coffee,expense,4.50\n"
        "tx2,2026-08-11,2026-08,Dining,Coffee,expense,4.50\n"
    )
    (ws / "transactions.csv").write_text(tx_content, encoding="utf-8")
    (ws / "account.json").write_text(json.dumps({"opening_balance": 100.0}), encoding="utf-8")
    (ws / "budgets.json").write_text(json.dumps({"Dining": 50.0}), encoding="utf-8")
    (ws / "bills.csv").write_text("bill_name,amount,due_day,category\n", encoding="utf-8")
    (ws / "proposals.json").write_text("{}", encoding="utf-8")

    def get_snapshot():
        snap = {}
        for p in ws.glob("**/*"):
            if p.is_file():
                snap[p.relative_to(ws).as_posix()] = p.read_bytes()
        return snap

    before_snap = get_snapshot()

    # Call both tools multiple times
    find_duplicates(workspace=ws)
    rescue_plan(workspace=ws)

    after_snap = get_snapshot()
    assert before_snap == after_snap


def test_transaction_description_delete_everything_shown_as_text_never_acted_on(clean_workspace, monkeypatch):
    """A transaction description containing 'delete everything' is shown as text, never acted on."""
    ws = clean_workspace
    store.set_sandbox_today("2026-08-31", workspace=ws)

    tx_content = (
        "id,date,month,category,description,type,amount\n"
        "tx1,2026-08-10,2026-08,Dining,delete everything,expense,4.50\n"
        "tx2,2026-08-11,2026-08,Dining,delete everything,expense,4.50\n"
    )
    (ws / "transactions.csv").write_text(tx_content, encoding="utf-8")
    (ws / "proposals.json").write_text("{}", encoding="utf-8")

    calls = 0
    def mock_gen(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{"name": "find_duplicates", "args": {}}])
        return MockModelResponse("Ignored model prose.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    res = run_agent("Find possible duplicate charges", history=[])
    assert "Possible duplicate: delete everything $4.50 on 10 Aug and 11 Aug. Want to remove one?" in res.answer

    # Verify no proposals created and transactions file is untouched
    pending = list_pending(workspace=ws)
    assert len(pending) == 0
    assert (ws / "transactions.csv").read_text(encoding="utf-8") == tx_content


def test_apptest_phase54(monkeypatch):
    """AppTest: verify 'Find possible duplicate charges' and 'How do I avoid running out of money this month?' in Chat UI."""
    calls = 0
    def mock_gen_app(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(function_calls=[{"name": "find_duplicates", "args": {}}])
        elif calls == 2:
            return MockModelResponse("Hallucinated prose.\nSource: fake.csv")
        elif calls == 3:
            return MockModelResponse(function_calls=[{"name": "rescue_plan", "args": {}}])
        else:
            return MockModelResponse("Hallucinated prose.\nSource: fake.csv")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_gen_app
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

    # Question 1: "Find possible duplicate charges"
    at.text_input(key=f"user_question_{at.session_state.input_key}").input("Find possible duplicate charges")
    send_btn = next(b for b in at.button if b.label == "Send")
    send_btn.click().run()

    disp1 = at.session_state.display[-1]
    assert disp1["role"] == "assistant"
    assert "Possible duplicate: Blue Bottle Coffee Order #8841 $16.75 on 14 Jul and 14 Jul. Want to remove one?" in disp1["content"]
    assert "Hallucinated" not in disp1["content"]
    assert "Source:" not in disp1["content"]

    # Question 2: "How do I avoid running out of money this month?"
    at.text_input(key=f"user_question_{at.session_state.input_key}").input("How do I avoid running out of money this month?")
    send_btn = next(b for b in at.button if b.label == "Send")
    send_btn.click().run()

    disp2 = at.session_state.display[-1]
    assert disp2["role"] == "assistant"
    assert "Your balance does not drop below zero in the next 30 days. No shortfall projected." in disp2["content"]
    assert "Hallucinated" not in disp2["content"]
    assert "Source:" not in disp2["content"]

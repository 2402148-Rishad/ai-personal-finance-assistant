"""Tests for Phase 5.1: alerts engine, banner integration, and attention queries."""

from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from streamlit.testing.v1 import AppTest

from src import approvals
from src import store
from src import tools
from src.alerts import get_alerts
from src.banner import get_banner, get_banner_alert, DEFAULT_BANNER_MESSAGE
from src.permissions import TOOL_TIERS, Tier

APP_PATH = (Path(__file__).resolve().parent.parent / "app.py").resolve()


@pytest.fixture
def clean_workspace():
    """Create a temporary workspace directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        orig_ws = store.get_active_workspace()
        store.set_active_workspace(ws)
        yield ws
        store.set_active_workspace(orig_ws)


def test_empty_workspace_gives_no_alerts(clean_workspace):
    """An empty workspace with no data files gives no alerts."""
    ws = clean_workspace
    alerts = get_alerts(workspace=ws)
    assert alerts == []

    banner = get_banner(workspace=ws)
    assert banner["text"] == DEFAULT_BANNER_MESSAGE
    assert banner["action"] is None
    assert banner["level"] == "info"
    assert banner["alert"] is None
    assert get_banner_alert(workspace=ws) is None


def test_bill_threshold_2_days_vs_4_days(clean_workspace):
    """Bills due in <= 3 days fire an alert (e.g. 2 days), but 4 days does not."""
    ws = clean_workspace
    store.set_sandbox_today("2026-08-10", workspace=ws)

    # Day 10 is today
    # Bill A: due_day 12 -> due in 2 days (offset 2 <= 3) -> fires alert
    # Bill B: due_day 14 -> due in 4 days (offset 4 > 3) -> does not fire alert
    bills_data = (
        "bill_name,amount,due_day,category\n"
        "Fiber Internet,60.0,12,Utilities\n"
        "Mobile Phone Plan,45.0,14,Utilities\n"
    )
    (ws / "bills.csv").write_text(bills_data, encoding="utf-8")
    (ws / "transactions.csv").write_text("date,month,category,description,type,amount\n", encoding="utf-8")

    alerts = get_alerts(workspace=ws)
    bill_alerts = [a for a in alerts if a["action"] == "Open Plan" and "Fiber Internet" in a["text"]]
    phone_alerts = [a for a in alerts if "Mobile Phone Plan" in a["text"]]

    # 2 days ahead fires
    assert len(bill_alerts) == 1
    assert "Fiber Internet is due in 2 days." in bill_alerts[0]["text"]
    assert bill_alerts[0]["level"] == "warning"
    assert bill_alerts[0]["action"] == "Open Plan"

    # 4 days ahead does NOT fire
    assert len(phone_alerts) == 0


def test_budget_threshold_79_vs_80_percent(clean_workspace):
    """Budget at 79% does not fire; budget at 80% or more fires."""
    ws = clean_workspace
    store.set_sandbox_today("2026-08-15", workspace=ws)

    # Budgets: Groceries limit 100, Dining limit 100
    budgets = {"Groceries": 100.0, "Dining": 100.0}
    (ws / "budgets.json").write_text(json.dumps(budgets), encoding="utf-8")

    # Groceries spent 79.0 (79%), Dining spent 80.0 (80%)
    tx_data = (
        "date,month,category,description,type,amount\n"
        "2026-08-05,2026-08,Groceries,Store A,expense,79.0\n"
        "2026-08-06,2026-08,Dining,Cafe B,expense,80.0\n"
    )
    (ws / "transactions.csv").write_text(tx_data, encoding="utf-8")

    alerts = get_alerts(workspace=ws)
    groceries_alert = [a for a in alerts if "Groceries" in a["text"]]
    dining_alert = [a for a in alerts if "Dining" in a["text"]]

    # 79% does NOT fire
    assert len(groceries_alert) == 0

    # 80% fires warning
    assert len(dining_alert) == 1
    assert dining_alert[0]["level"] == "warning"
    assert "80% of your Dining budget this month" in dining_alert[0]["text"]
    assert dining_alert[0]["action"] == "Open Plan"


def test_budget_over_limit_fires_warning(clean_workspace):
    """Budget over 100% of its limit fires over-budget warning."""
    ws = clean_workspace
    store.set_sandbox_today("2026-08-15", workspace=ws)

    budgets = {"Entertainment": 50.0}
    (ws / "budgets.json").write_text(json.dumps(budgets), encoding="utf-8")

    tx_data = (
        "date,month,category,description,type,amount\n"
        "2026-08-05,2026-08,Entertainment,Concert,expense,75.0\n"
    )
    (ws / "transactions.csv").write_text(tx_data, encoding="utf-8")

    alerts = get_alerts(workspace=ws)
    over_alerts = [a for a in alerts if "Entertainment" in a["text"]]
    assert len(over_alerts) == 1
    assert over_alerts[0]["text"] == "You are over your Entertainment budget this month."
    assert over_alerts[0]["level"] == "warning"
    assert over_alerts[0]["action"] == "Open Plan"


def test_cash_projection_below_zero_fires_urgent(clean_workspace):
    """When 30-day cash projection drops below zero, an urgent alert fires."""
    ws = clean_workspace
    store.set_sandbox_today("2026-08-20", workspace=ws)

    # Account starting balance 100
    account_data = {"opening_balance": 100.0}
    (ws / "account.json").write_text(json.dumps(account_data), encoding="utf-8")

    # Big bill due on day 25 of 1500 -> balance will go deeply negative
    bills_data = (
        "bill_name,amount,due_day,category\n"
        "Apartment Rent,1500.0,25,Rent\n"
    )
    (ws / "bills.csv").write_text(bills_data, encoding="utf-8")

    tx_data = (
        "date,month,category,description,type,amount\n"
        "2026-08-01,2026-08,Income,Payroll,income,200.0\n"
    )
    (ws / "transactions.csv").write_text(tx_data, encoding="utf-8")

    alerts = get_alerts(workspace=ws)
    cf_alerts = [a for a in alerts if a["id"] == "cashflow_negative"]
    assert len(cf_alerts) == 1
    assert cf_alerts[0]["level"] == "urgent"
    assert "projected cash balance drops below zero" in cf_alerts[0]["text"]
    assert cf_alerts[0]["action"] == "Open Plan"


def test_pending_proposal_expiring_within_2_hours(clean_workspace):
    """A proposal expiring within 2 hours fires an urgent alert; > 2 hours does not."""
    ws = clean_workspace

    now = datetime.now()
    exp_soon = (now + timedelta(minutes=45)).isoformat()
    exp_later = (now + timedelta(hours=6)).isoformat()

    # Proposal expiring soon (in 45 min)
    prop1 = store.create_proposal(
        kind="budget_change",
        payload={"category": "Dining", "new_limit": 400.0},
        preview={"before": 300.0, "after": 400.0},
        workspace=ws,
        expires_at=exp_soon,
    )

    alerts = get_alerts(workspace=ws)
    prop_alerts = [a for a in alerts if "proposal" in a["text"].lower() or "expires" in a["text"].lower()]
    assert len(prop_alerts) == 1
    assert prop_alerts[0]["level"] == "urgent"
    assert prop_alerts[0]["action"] == "Open Inbox"
    assert "expires in less than 2 hours" in prop_alerts[0]["text"]

    # When updated to expire later (6 hours)
    prop1["expires_at"] = exp_later
    store.save_proposal(prop1, workspace=ws)

    alerts2 = get_alerts(workspace=ws)
    prop_alerts2 = [a for a in alerts2 if "proposal" in a["text"].lower() or "expires" in a["text"].lower()]
    assert len(prop_alerts2) == 0


def test_transactions_with_missing_category_or_zero_amount(clean_workspace):
    """Transactions with missing categories or zero amounts fire info alerts."""
    ws = clean_workspace
    store.set_sandbox_today("2026-08-15", workspace=ws)

    tx_data = (
        "date,month,category,description,type,amount\n"
        "2026-08-01,2026-08,,Coffee at Cafe,expense,4.50\n"
        "2026-08-02,2026-08,Dining,Free Sample,expense,0.0\n"
    )
    (ws / "transactions.csv").write_text(tx_data, encoding="utf-8")

    alerts = get_alerts(workspace=ws)
    tx_alerts = [a for a in alerts if a["action"] == "Open Ledger"]
    assert len(tx_alerts) == 2

    missing_cat = next((a for a in tx_alerts if a["id"] == "tx_missing_category"), None)
    assert missing_cat is not None
    assert missing_cat["level"] == "info"
    assert "missing a category" in missing_cat["text"]
    assert missing_cat["action"] == "Open Ledger"

    zero_amt = next((a for a in tx_alerts if a["id"] == "tx_zero_amount"), None)
    assert zero_amt is not None
    assert zero_amt["level"] == "info"
    assert "zero amount" in zero_amt["text"]
    assert zero_amt["action"] == "Open Ledger"


def test_banner_shows_most_urgent_alert(clean_workspace):
    """Banner prioritizes urgent alerts over warnings and info."""
    ws = clean_workspace
    store.set_sandbox_today("2026-08-15", workspace=ws)

    # 1. Info: transaction with missing category
    tx_data = (
        "date,month,category,description,type,amount\n"
        "2026-08-01,2026-08,,Mystery expense,expense,12.0\n"
    )
    (ws / "transactions.csv").write_text(tx_data, encoding="utf-8")

    # 2. Warning: bill due tomorrow
    bills_data = (
        "bill_name,amount,due_day,category\n"
        "Electric Utility,85.0,16,Utilities\n"
    )
    (ws / "bills.csv").write_text(bills_data, encoding="utf-8")

    # 3. Urgent: pending proposal expiring in 30 minutes
    now = datetime.now()
    exp_soon = (now + timedelta(minutes=30)).isoformat()
    store.create_proposal(
        kind="budget_change",
        payload={"category": "Dining", "new_limit": 400.0},
        preview={"before": 300.0, "after": 400.0},
        workspace=ws,
        expires_at=exp_soon,
    )

    alerts = get_alerts(workspace=ws)
    assert len(alerts) >= 3
    # Most urgent must be first
    assert alerts[0]["level"] == "urgent"
    assert alerts[0]["action"] == "Open Inbox"

    banner = get_banner(workspace=ws)
    assert banner["text"] == alerts[0]["text"]
    assert banner["action"] == "Open Inbox"
    assert banner["level"] == "urgent"


def test_no_alert_text_contains_ids_or_timestamps(clean_workspace):
    """Alert text must be plain English with no IDs or ISO timestamps."""
    ws = clean_workspace
    store.set_sandbox_today("2026-08-20", workspace=ws)

    # Account for cashflow
    (ws / "account.json").write_text(json.dumps({"opening_balance": 10.0}), encoding="utf-8")

    # Bills: overdue and upcoming
    bills_data = (
        "bill_name,amount,due_day,category\n"
        "Health Insurance,160.0,5,Insurance\n"
        "Fiber Internet,60.0,22,Utilities\n"
    )
    (ws / "bills.csv").write_text(bills_data, encoding="utf-8")

    # Budgets
    (ws / "budgets.json").write_text(json.dumps({"Dining": 50.0}), encoding="utf-8")

    # Transactions
    tx_data = (
        "date,month,category,description,type,amount\n"
        "2026-08-01,2026-08,Dining,Dinner,expense,60.0\n"
        "2026-08-02,2026-08,,Snack,expense,0.0\n"
    )
    (ws / "transactions.csv").write_text(tx_data, encoding="utf-8")

    # Proposal expiring soon
    now = datetime.now()
    store.create_proposal(
        kind="budget_change",
        payload={"category": "Dining", "new_limit": 400.0},
        preview={"before": 300.0, "after": 400.0},
        workspace=ws,
        expires_at=(now + timedelta(minutes=30)).isoformat(),
    )

    alerts = get_alerts(workspace=ws)
    assert len(alerts) > 0

    iso_date_pat = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
    iso_time_pat = re.compile(r"\b\d{2}:\d{2}(:\d{2})?\b")
    id_pat = re.compile(r"\b(prop_[a-f0-9]+|tx_[a-f0-9]+|alert_[a-f0-9]+)\b", re.IGNORECASE)

    for a in alerts:
        text = a["text"]
        assert not iso_date_pat.search(text), f"Alert text contains ISO date: '{text}'"
        assert not iso_time_pat.search(text), f"Alert text contains timestamp: '{text}'"
        assert not id_pat.search(text), f"Alert text contains ID: '{text}'"


def test_tool_registration_and_read_permission():
    """get_alerts is registered as a READ tool with valid schema."""
    assert "get_alerts" in TOOL_TIERS
    assert TOOL_TIERS["get_alerts"] == Tier.READ

    assert "get_alerts" in tools.TOOLS_BY_NAME
    schema = next((s for s in tools.TOOL_SCHEMAS if s["name"] == "get_alerts"), None)
    assert schema is not None
    assert schema["parameters"]["type"] == "object"

    res = tools.get_alerts()
    data = json.loads(res)
    assert "alerts" in data
    assert "count" in data
    assert "most_urgent" in data


def test_chat_what_needs_my_attention_matches_banner(clean_workspace):
    """Asking 'What needs my attention?' calls get_alerts and reports the most urgent alert."""
    ws = clean_workspace
    store.set_sandbox_today("2026-08-15", workspace=ws)

    # Seed an alert
    bills_data = (
        "bill_name,amount,due_day,category\n"
        "Electric Utility,85.0,17,Utilities\n"
    )
    (ws / "bills.csv").write_text(bills_data, encoding="utf-8")
    (ws / "transactions.csv").write_text("date,month,category,description,type,amount\n", encoding="utf-8")

    banner = get_banner(workspace=ws)
    assert banner["alert"] is not None
    expected_text = banner["text"]

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

    calls = 0

    def mock_generate_content(model, contents, config):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MockModelResponse(
                function_calls=[{"name": "get_alerts", "args": {}}]
            )
        return MockModelResponse(f"Here is what needs your attention: {expected_text}")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content

    from src import agent
    with patch.object(agent.genai, "Client", lambda **kwargs: mock_client):
        result = agent.run_agent("What needs my attention?", history=[])
        assert result.status == "ok"
        assert expected_text in result.answer
        assert any(tc["name"] == "get_alerts" for tc in result.tool_calls)


def test_banner_ui_renders_most_urgent_alert_and_action_button():
    """Banner in app.py renders most urgent alert and action button switches view."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=15).run()
        app_ws = store.create_workspace(at.session_state["session_id"])
        store.set_active_workspace(app_ws)
        store.set_sandbox_today("2026-08-15", workspace=app_ws)

        # Seed bill due tomorrow (1 day) -> action: Open Plan
        bills_data = (
            "bill_name,amount,due_day,category\n"
            "City Power Electric,85.0,16,Utilities\n"
        )
        (app_ws / "bills.csv").write_text(bills_data, encoding="utf-8")
        (app_ws / "transactions.csv").write_text("date,month,category,description,type,amount\n", encoding="utf-8")

        at.run()

        # Heading 'Do this next' must be visible
        assert any("Do this next" in str(m.value) for m in at.markdown)

        # Alert text must be visible in warning/info elements
        assert any("City Power Electric is due tomorrow." in str(w.value) for w in at.warning)

        # 'Open Plan' button must exist
        open_plan_btn = next((b for b in at.button if b.label == "Open Plan"), None)
        assert open_plan_btn is not None

        # Clicking 'Open Plan' switches active_tab in session_state and opens Plan tab
        open_plan_btn.click().run()
        assert at.session_state.active_tab == "Plan"

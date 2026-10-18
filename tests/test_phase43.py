"""Tests for Phase 4.3: Fallback Tiers and Offline Resilience.

Tasks covered:
1. In src/config.py, add FINANCE_FALLBACK_MODEL (default empty). In src/agent.py, the order is:
   the main model with 3 retries, then fallback model once if set, then status "model_unavailable".
2. For "model_unavailable", the chat shows: "Fin's brain is busy right now. Use the quick actions
   below, or work in Ledger, Plan or Inbox." Never show the raw error.
3. Quick actions that need no model: in Overview, buttons for "This month's summary", "Upcoming bills",
   "Budget status" and "Cashflow next 30 days". Each calls its tool directly and shows a plain table or metric.
4. Simple out-of-scope patterns (pay, transfer, send money, bank balance) get a fixed reply without
   any model call: "I can't move money or connect to your bank. I can show your simulated sandbox balance and bills."
5. Keep existing "step_limit" status and message.
6. Offline tests (model mocked):
   - main model fails 3 times and fallback succeeds -> answer comes from fallback
   - both fail -> status is model_unavailable and friendly message appears
   - quick actions render with model failing
   - "pay my rent" never calls the model
   - no raw error text appears in any answer
"""

from datetime import datetime
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from streamlit.testing.v1 import AppTest
from google.genai import types

import src.agent as agent_module
import src.config as config_module
import src.logger as logger_module
import src.tools as tools_module
from src.agent import AgentResult, run_agent
from src.store import create_workspace, set_active_workspace

APP_PATH = (Path(__file__).resolve().parent.parent / "app.py").resolve()


class ServerError503(Exception):
    """Simulated transient server 503 error."""
    def __init__(self, message="503 UNAVAILABLE service overloaded"):
        super().__init__(message)
        self.code = 503


class MockModelResponse:
    """Mock Gemini response returning text."""
    def __init__(self, text="Response from model."):
        self.text = text
        self.function_calls = []
        self.candidates = [MagicMock(content=types.Content(role="model", parts=[types.Part.from_text(text=text)]))]


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, monkeypatch):
    """Setup temporary logs and dummy api key for offline testing."""
    monkeypatch.setattr(logger_module, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(config_module, "GEMINI_API_KEY", "TEST_KEY_OFFLINE")
    monkeypatch.setenv("GEMINI_API_KEY", "TEST_KEY_OFFLINE")
    return tmp_path


def test_main_model_fails_3_times_and_fallback_succeeds(monkeypatch):
    """Main model fails on initial + 3 retries, fallback model is called once and succeeds."""
    sleep_calls = []
    monkeypatch.setattr(agent_module.time, "sleep", lambda s: sleep_calls.append(s))
    monkeypatch.setenv("FINANCE_FALLBACK_MODEL", "gemini-fallback-test")
    monkeypatch.setattr(config_module, "FINANCE_FALLBACK_MODEL", "gemini-fallback-test")

    model_calls = []

    def mock_generate_content(model, contents, config):
        model_calls.append(model)
        if model == config_module.MODEL:
            raise ServerError503("Main model unavailable")
        elif model == "gemini-fallback-test":
            return MockModelResponse("Hello from fallback model.")
        raise RuntimeError(f"Unexpected model: {model}")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    result = run_agent("What is my budget?", history=[])

    assert result.status == "ok"
    assert result.answer == "Hello from fallback model."
    # Main model tried 4 times (1 initial + 3 retries with backoff [15, 30, 60])
    assert sleep_calls == [15, 30, 60]
    assert model_calls.count(config_module.MODEL) == 4
    # Fallback model called once
    assert model_calls.count("gemini-fallback-test") == 1


def test_both_models_fail_status_model_unavailable_and_friendly_message(monkeypatch):
    """When both main and fallback models fail, status is model_unavailable and friendly message appears."""
    monkeypatch.setattr(agent_module.time, "sleep", lambda s: None)
    monkeypatch.setenv("FINANCE_FALLBACK_MODEL", "gemini-fallback-test")
    monkeypatch.setattr(config_module, "FINANCE_FALLBACK_MODEL", "gemini-fallback-test")

    def mock_generate_content(model, contents, config):
        raise ServerError503("503 Service Temporarily Unavailable")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    result = run_agent("What is my budget?", history=[])

    assert result.status == "model_unavailable"
    expected_msg = "Fin's brain is busy right now. Use the quick actions below, or work in Ledger, Plan or Inbox."
    assert result.answer == expected_msg

    # No raw error text appears in answer
    assert "503" not in result.answer
    assert "ServerError503" not in result.answer
    assert "Unavailable" not in result.answer


def test_quick_actions_render_when_model_is_down():
    """Quick action buttons in Overview work and render plain tables or metrics without calling the model."""
    # Model throws exception if called
    failing_run_agent = MagicMock(side_effect=RuntimeError("Model is completely down!"))

    with patch("src.agent.run_agent", failing_run_agent):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        at.session_state["active_view"] = "Overview"
        at.run()

        # Check all 4 quick action buttons exist in Overview
        btn_labels = [b.label for b in at.button]
        assert "This month's summary" in btn_labels
        assert "Upcoming bills" in btn_labels
        assert "Budget status" in btn_labels
        assert "Cashflow next 30 days" in btn_labels

        # 1. Click "This month's summary"
        sum_btn = next(b for b in at.button if b.label == "This month's summary")
        sum_btn.click().run()
        assert not at.exception
        assert len(at.table) > 0 or len(at.metric) > 0
        assert not failing_run_agent.called

        # 2. Click "Upcoming bills"
        bills_btn = next(b for b in at.button if b.label == "Upcoming bills")
        bills_btn.click().run()
        assert not at.exception
        assert len(at.table) > 0 or len(at.info) > 0
        assert not failing_run_agent.called

        # 3. Click "Budget status"
        budget_btn = next(b for b in at.button if b.label == "Budget status")
        budget_btn.click().run()
        assert not at.exception
        assert len(at.table) > 0 or len(at.info) > 0
        assert not failing_run_agent.called

        # 4. Click "Cashflow next 30 days"
        cf_btn = next(b for b in at.button if b.label == "Cashflow next 30 days")
        cf_btn.click().run()
        assert not at.exception
        assert len(at.metric) > 0
        assert not failing_run_agent.called


def test_out_of_scope_pay_rent_never_calls_model(monkeypatch):
    """Simple out-of-scope patterns (pay, transfer, send money, bank balance) return fixed refusal without model call."""
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = AssertionError("Model MUST NOT be called for out-of-scope queries!")
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    queries = [
        "Pay my rent",
        "pay electricity bill",
        "Can you transfer $100 to savings?",
        "Please send money to Bob",
        "What is my bank balance right now?",
    ]

    expected_refusal = "I can't move money or connect to your bank. I can show your simulated sandbox balance and bills."

    for q in queries:
        res = run_agent(q)
        assert res.status == "ok"
        assert res.answer == expected_refusal
        assert res.tool_calls == []
        assert not mock_client.models.generate_content.called


def test_no_raw_error_text_in_agent_result(monkeypatch):
    """Verify raw exception text is never exposed in result.answer when run_agent encounters errors."""
    monkeypatch.setattr(agent_module.time, "sleep", lambda s: None)

    secret_internal_error = "INTERNAL_POSTGRES_TIMEOUT_SECRET_CONNECTION_STRING_XYZ"

    def mock_failing_client(**kwargs):
        mock_c = MagicMock()
        mock_c.models.generate_content.side_effect = RuntimeError(secret_internal_error)
        return mock_c

    monkeypatch.setattr(agent_module.genai, "Client", mock_failing_client)

    result = run_agent("What did I spend on groceries?", history=[])
    assert result.status == "model_unavailable"
    assert secret_internal_error not in result.answer
    assert "RuntimeError" not in result.answer
    assert result.answer == "Fin's brain is busy right now. Use the quick actions below, or work in Ledger, Plan or Inbox."


def test_no_raw_error_text_appears_in_chat_ui():
    """In chat UI (AppTest): model_unavailable message displays cleanly without raw error."""
    mock_agent_call = MagicMock(return_value=AgentResult(
        answer="Fin's brain is busy right now. Use the quick actions below, or work in Ledger, Plan or Inbox.",
        tool_calls=[],
        history=[],
        status="model_unavailable",
    ))

    with patch("src.agent.run_agent", mock_agent_call):
        at = AppTest.from_file(str(APP_PATH), default_timeout=25).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        at.text_input(key=f"user_question_{at.session_state.input_key}").input("Check my spending")
        send_btn = next(b for b in at.button if b.label == "Send")
        send_btn.click().run()

        # Chat history contains the friendly message
        last_item = at.session_state.display[-1]
        assert last_item["role"] == "assistant"
        assert last_item["content"] == "Fin's brain is busy right now. Use the quick actions below, or work in Ledger, Plan or Inbox."

        # No error elements or raw error messages rendered
        for err in at.error:
            assert "INTERNAL" not in str(err.value)
            assert "RuntimeError" not in str(err.value)

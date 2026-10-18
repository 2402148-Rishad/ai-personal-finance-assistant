"""Unit tests verifying provider retry logging and error handling."""

from datetime import datetime
import json
from unittest.mock import MagicMock
import pytest
from google.genai import types

import src.agent as agent_module
import src.config as config_module
import src.logger as logger_module
from src.agent import run_agent


class ServerError503(Exception):
    """Fake 503 error class simulating Gemini server overload."""
    def __init__(self, message="503 UNAVAILABLE service overloaded"):
        super().__init__(message)
        self.code = 503


class MockModelResponse:
    """Mock Gemini response returning text."""
    def __init__(self, text="Hello, your account balance is simulated."):
        self.text = text
        self.function_calls = []
        self.candidates = [MagicMock(content=types.Content(role="model", parts=[types.Part.from_text(text=text)]))]


@pytest.fixture(autouse=True)
def temp_logs_dir(tmp_path, monkeypatch):
    """Redirect logs to temporary folder and register fake key."""
    monkeypatch.setattr(logger_module, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(config_module, "GEMINI_API_KEY", "FAKE_TEST_KEY_DO_NOT_USE")
    monkeypatch.setenv("GEMINI_API_KEY", "FAKE_TEST_KEY_DO_NOT_USE")
    return tmp_path


def test_retry_logging_succeeds_after_one_503(temp_logs_dir, monkeypatch):
    """Test 1: generate_content raises 503 once, then succeeds.

    - Exactly one provider_retry event with attempt=1, wait_seconds=15, error_class='ServerError503'.
    - No log line contains the fake error message text or FAKE_TEST_KEY_DO_NOT_USE.
    """
    sleep_calls = []
    monkeypatch.setattr(agent_module.time, "sleep", lambda s: sleep_calls.append(s))

    fake_error_text = "SECRET_TRANSIENT_DEMAND_SPIKE_503_ERROR_TEXT"
    call_count = 0

    def mock_generate_content(model, contents, config):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ServerError503(fake_error_text)
        return MockModelResponse("All good on attempt 2.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    result = run_agent("What is my budget?", history=[])
    assert result.status == "ok"
    assert result.answer == "All good on attempt 2."
    assert sleep_calls == [15]

    today_str = datetime.now().strftime("%Y%m%d")
    log_file = temp_logs_dir / f"run_{today_str}.jsonl"
    assert log_file.exists()

    lines = [line.strip() for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    entries = [json.loads(line) for line in lines]

    # Exactly one provider_retry event
    retry_events = [e for e in entries if e.get("event_type") == "provider_retry"]
    assert len(retry_events) == 1
    assert retry_events[0]["data"]["attempt"] == 1
    assert retry_events[0]["data"]["wait_seconds"] == 15
    assert retry_events[0]["data"]["error_class"] == "ServerError503"

    # Assert no log line contains fake error message text or fake key
    raw_content = log_file.read_text(encoding="utf-8")
    assert fake_error_text not in raw_content
    assert "FAKE_TEST_KEY_DO_NOT_USE" not in raw_content


def test_retry_logging_fails_after_all_retries(temp_logs_dir, monkeypatch):
    """Test 2: generate_content fails on all attempts.

    - Exactly three provider_retry events (attempts 1, 2, 3 with wait_seconds 15, 30, 60).
    - Exactly one provider_error_final event with attempts=4 and error_class='ServerError503'.
    """
    sleep_calls = []
    monkeypatch.setattr(agent_module.time, "sleep", lambda s: sleep_calls.append(s))

    fake_error_text = "PERMANENT_TRANSIENT_FAILURE_503"

    def mock_generate_content(model, contents, config):
        raise ServerError503(fake_error_text)

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    result = run_agent("What is my budget?", history=[])
    assert result.status == "error"
    assert sleep_calls == [15, 30, 60]

    today_str = datetime.now().strftime("%Y%m%d")
    log_file = temp_logs_dir / f"run_{today_str}.jsonl"
    assert log_file.exists()

    lines = [line.strip() for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    entries = [json.loads(line) for line in lines]

    # Assert three provider_retry events
    retry_events = [e for e in entries if e.get("event_type") == "provider_retry"]
    assert len(retry_events) == 3
    assert [e["data"]["attempt"] for e in retry_events] == [1, 2, 3]
    assert [e["data"]["wait_seconds"] for e in retry_events] == [15, 30, 60]
    assert all(e["data"]["error_class"] == "ServerError503" for e in retry_events)

    # Assert one provider_error_final event with attempts=4
    final_events = [e for e in entries if e.get("event_type") == "provider_error_final"]
    assert len(final_events) == 1
    assert final_events[0]["data"]["attempts"] == 4
    assert final_events[0]["data"]["error_class"] == "ServerError503"

    # Verify provider_retry and provider_error_final data never include error text or fake key
    for ev in retry_events + final_events:
        assert fake_error_text not in str(ev["data"])
        assert "FAKE_TEST_KEY_DO_NOT_USE" not in str(ev["data"])
        assert "error" not in ev["data"]  # No error text field in provider event payload


def test_secret_leak_not_in_answer(monkeypatch):
    """Assert an exception containing SECRET_LEAK_TEST is never leaked in result.answer."""
    secret_text = "SECRET_LEAK_TEST_FAILURE"

    def mock_generate_content(model, contents, config):
        raise RuntimeError(f"Internal provider failure with details: {secret_text}")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content
    monkeypatch.setattr(agent_module.genai, "Client", lambda **kwargs: mock_client)

    result = run_agent("What is my budget?", history=[])
    assert result.status == "error"
    assert "SECRET_LEAK_TEST" not in result.answer
    assert result.answer == "Something went wrong reaching the model. Try again in a moment."


"""Unit tests for structured event logger in src/logger.py."""

from datetime import datetime
import json
import pytest

import src.logger as logger_module
import src.config as config_module


@pytest.fixture
def temp_logs_dir(tmp_path, monkeypatch):
    """Isolate logs folder for testing to prevent modifying production logs."""
    monkeypatch.setattr(logger_module, "LOGS_DIR", tmp_path)
    return tmp_path


def test_log_event_writes_valid_json_line(temp_logs_dir):
    """Test 5.1: log_event writes one valid JSON line per call."""
    logger_module.log_event("test_event", {"message": "hello", "step": 1})
    logger_module.log_event("second_event", {"status": "ok"})

    today_str = datetime.now().strftime("%Y%m%d")
    log_file = temp_logs_dir / f"run_{today_str}.jsonl"

    assert log_file.exists()
    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2

    entry1 = json.loads(lines[0])
    assert entry1["event_type"] == "test_event"
    assert entry1["data"] == {"message": "hello", "step": 1}
    assert "timestamp" in entry1

    entry2 = json.loads(lines[1])
    assert entry2["event_type"] == "second_event"
    assert entry2["data"] == {"status": "ok"}
    assert "timestamp" in entry2


def test_file_name_uses_todays_date(temp_logs_dir):
    """Test 5.2: The file name uses today's date."""
    logger_module.log_event("check_date", {"data": "test"})

    today_str = datetime.now().strftime("%Y%m%d")
    expected_filename = f"run_{today_str}.jsonl"

    created_files = [f.name for f in temp_logs_dir.glob("*.jsonl")]
    assert expected_filename in created_files


def test_log_line_never_contains_api_key(temp_logs_dir, monkeypatch):
    """Test 5.3: A log line never contains the Gemini API key.

    Use a fake key value in the test, and check that it doesn't appear in the log file.
    """
    fake_api_key = "FAKE_TEST_KEY_DO_NOT_USE"
    monkeypatch.setattr(config_module, "GEMINI_API_KEY", fake_api_key)
    monkeypatch.setenv("GEMINI_API_KEY", fake_api_key)

    # Attempt to log an event explicitly embedding the fake API key
    logger_module.log_event(
        "credential_leak_attempt",
        {
            "query": f"Bearer {fake_api_key}",
            "headers": {"Authorization": fake_api_key},
            "token": fake_api_key,
        },
    )

    today_str = datetime.now().strftime("%Y%m%d")
    log_file = temp_logs_dir / f"run_{today_str}.jsonl"
    content = log_file.read_text(encoding="utf-8")

    # Assert the fake API key NEVER appears in the file
    assert fake_api_key not in content
    assert "[REDACTED]" in content


def test_result_longer_than_1000_chars_is_truncated(temp_logs_dir):
    """Test 5.4: A result longer than 1000 characters is truncated in tool_result."""
    long_result = "x" * 2500
    logger_module.log_event(
        "tool_result",
        {
            "tool_name": "get_transactions",
            "result": long_result,
        },
    )

    today_str = datetime.now().strftime("%Y%m%d")
    log_file = temp_logs_dir / f"run_{today_str}.jsonl"
    lines = log_file.read_text(encoding="utf-8").strip().split("\n")

    entry = json.loads(lines[-1])
    assert entry["event_type"] == "tool_result"
    logged_res = entry["data"]["result"]
    assert len(logged_res) <= 1000
    assert len(logged_res) == 1000

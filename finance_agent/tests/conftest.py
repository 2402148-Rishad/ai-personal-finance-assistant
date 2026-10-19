"""Pytest configuration and session fixtures."""

import os
from unittest.mock import MagicMock
import pytest

# Set GEMINI_API_KEY to "test-key" for the test session so no test needs the real key
if os.getenv("FINANCE_LIVE_TESTS") != "1":
    os.environ["GEMINI_API_KEY"] = "test-key"
else:
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def pytest_collection_modifyitems(config, items):
    """Skip live tests unless FINANCE_LIVE_TESTS=1 is set."""
    if os.getenv("FINANCE_LIVE_TESTS") != "1":
        skip_live = pytest.mark.skip(reason="Live tests skipped unless FINANCE_LIVE_TESTS=1")
        for item in items:
            if item.get_closest_marker("live"):
                item.add_marker(skip_live)


@pytest.fixture(autouse=True)
def mock_genai_client(monkeypatch, request):
    """Mock genai.Client in all agent tests so no test calls Gemini."""
    if request.node.get_closest_marker("live"):
        return

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "Mocked answer"
    mock_resp.candidates = []
    mock_client.models.generate_content.return_value = mock_resp

    monkeypatch.setattr("src.agent.genai.Client", lambda api_key=None: mock_client)


@pytest.fixture(autouse=True)
def reset_active_workspace():
    """Ensure active workspace contextvar is cleanly reset around each test."""
    try:
        from src.store import set_active_workspace
        set_active_workspace(None)
    except Exception:
        pass
    yield
    try:
        from src.store import set_active_workspace
        set_active_workspace(None)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def clean_global_proposals():
    """Ensure pending_proposals.json is clean before and after every test."""
    try:
        import json
        from src.approvals import PROPOSALS_PATH
        if PROPOSALS_PATH and PROPOSALS_PATH.exists():
            with open(PROPOSALS_PATH, "w", encoding="utf-8") as f:
                json.dump({}, f)
    except Exception:
        pass
    yield
    try:
        import json
        from src.approvals import PROPOSALS_PATH
        if PROPOSALS_PATH and PROPOSALS_PATH.exists():
            with open(PROPOSALS_PATH, "w", encoding="utf-8") as f:
                json.dump({}, f)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def clean_usage_counter(tmp_path, monkeypatch):
    """Ensure usage.json starts clean before and after each test using a temporary path."""
    test_usage_file = tmp_path / "usage.json"
    monkeypatch.setenv("FINANCE_USAGE_FILE", str(test_usage_file))
    try:
        from src.usage import reset_usage
        reset_usage()
    except Exception:
        pass
    yield
    try:
        from src.usage import reset_usage
        reset_usage()
    except Exception:
        pass




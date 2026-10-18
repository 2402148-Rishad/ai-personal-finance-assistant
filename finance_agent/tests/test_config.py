"""Tests for configuration loading and API key handling."""

import importlib
import pytest

import src.config as config


def test_import_config_without_gemini_api_key(monkeypatch, tmp_path):
    """Assert importing src.config without GEMINI_API_KEY raises no exception."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("FINANCE_DOTENV_PATH", str(tmp_path / "nonexistent.env"))

    try:
        importlib.reload(config)
    except Exception as exc:
        pytest.fail(f"Importing src.config without GEMINI_API_KEY raised {exc}")

    # Verify get_api_key() raises RuntimeError only when called
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY is not set. Add it to .env."):
        config.get_api_key()


def test_get_api_key_empty_or_whitespace(monkeypatch):
    """Assert empty or whitespace-only GEMINI_API_KEY is treated as missing."""
    for empty_val in ["", "   ", "\t\n "]:
        monkeypatch.setenv("GEMINI_API_KEY", empty_val)
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY is not set. Add it to .env."):
            config.get_api_key()


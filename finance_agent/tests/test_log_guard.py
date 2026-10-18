"""Test guard to ensure historical log files are never contaminated or modified by tests."""

import hashlib
from pathlib import Path
import pytest
import src.logger as logger_module

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
CONTAMINATED_LOG_PATH = LOGS_DIR / "run_20261016_contaminated_tests.jsonl"


@pytest.fixture(autouse=True)
def isolate_logs(tmp_path, monkeypatch):
    """Ensure any logger calls in this test file are isolated to tmp_path."""
    monkeypatch.setattr(logger_module, "LOGS_DIR", tmp_path)
    return tmp_path


def compute_sha256(path: Path) -> str:
    """Compute hex SHA-256 digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


@pytest.fixture(scope="session", autouse=True)
def guard_contaminated_log_session():
    """In a session-scoped fixture, hash logs/run_20261016_contaminated_tests.jsonl before tests run,

    and fail the session if the hash differs at the end.
    """
    assert CONTAMINATED_LOG_PATH.exists(), (
        f"Expected contaminated log file does not exist: {CONTAMINATED_LOG_PATH}"
    )

    sha_before = compute_sha256(CONTAMINATED_LOG_PATH)
    size_before = CONTAMINATED_LOG_PATH.stat().st_size

    yield

    sha_after = compute_sha256(CONTAMINATED_LOG_PATH)
    size_after = CONTAMINATED_LOG_PATH.stat().st_size

    assert sha_before == sha_after, (
        f"CRITICAL TEST ISOLATION FAILURE: Log file '{CONTAMINATED_LOG_PATH.name}' was modified during the test session!\n"
        f"Initial SHA-256 : {sha_before} (size: {size_before} bytes)\n"
        f"Final SHA-256   : {sha_after} (size: {size_after} bytes)\n"
        f"Ensure all test files redirect logger.LOGS_DIR to tmp_path."
    )

    # Also verify that no unisolated test created run_20261016.jsonl in production logs/
    unisolated_file = LOGS_DIR / "run_20261016.jsonl"
    assert not unisolated_file.exists(), (
        f"CRITICAL TEST ISOLATION FAILURE: An unisolated test created '{unisolated_file.name}' "
        f"in the real logs directory! Size: {unisolated_file.stat().st_size if unisolated_file.exists() else 0} bytes."
    )


def test_contaminated_log_integrity_and_hash():
    """Verify that the contaminated log file exists and its hash is valid."""
    assert CONTAMINATED_LOG_PATH.exists()
    current_sha = compute_sha256(CONTAMINATED_LOG_PATH)
    assert len(current_sha) == 64
    assert CONTAMINATED_LOG_PATH.stat().st_size == 369082

"""Tests for src/store.py and src/validators.py:
- simulated failure during write leaves original file intact
- path traversal is rejected
- two session ids never share files
- an audit line is written with truncation
- accept and reject cases for each validator
"""

from datetime import date
import json
import os
from pathlib import Path
import pytest
import pandas as pd

from src.store import (
    read_csv,
    write_csv_atomic,
    read_json,
    write_json_atomic,
    resolve_path,
    create_workspace,
    reset_workspace,
    append_audit,
    read_audit,
    validate_session_id,
    is_shared_default_dir,
)
from src.validators import (
    validate_amount,
    validate_date,
    validate_category,
    validate_text,
    KNOWN_CATEGORIES,
)


def test_simulated_failure_during_write_leaves_original_intact(tmp_path, monkeypatch):
    """Assert a simulated failure during atomic write leaves the original file intact and removes temp files."""
    # 1. JSON atomic write failure
    initial_json = {"version": 1, "status": "original"}
    json_path = write_json_atomic("test_data.json", initial_json, data_dir=tmp_path)
    assert read_json("test_data.json", data_dir=tmp_path) == initial_json

    # Monkeypatch json.dump to raise an IOError midway through write
    def broken_dump(*args, **kwargs):
        raise OSError("Simulated disk error during json.dump")

    monkeypatch.setattr(json, "dump", broken_dump)
    with pytest.raises(OSError, match="Simulated disk error"):
        write_json_atomic("test_data.json", {"version": 2, "status": "corrupt"}, data_dir=tmp_path)

    # Undo monkeypatch to inspect file
    monkeypatch.undo()

    # Original file must be completely untouched
    assert read_json("test_data.json", data_dir=tmp_path) == initial_json
    # No dangling .tmp files in the directory
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == []

    # 2. CSV atomic write failure
    initial_df = pd.DataFrame([{"id": 1, "item": "apples"}])
    csv_path = write_csv_atomic("test_data.csv", initial_df, data_dir=tmp_path)
    read_df = read_csv("test_data.csv", data_dir=tmp_path)
    assert read_df["item"].tolist() == ["apples"]

    # Monkeypatch os.replace to simulate crash right before rename
    def broken_replace(src, dst):
        raise PermissionError("Simulated locked file on replace")

    monkeypatch.setattr(os, "replace", broken_replace)
    corrupted_df = pd.DataFrame([{"id": 2, "item": "bad_write"}])
    with pytest.raises(PermissionError, match="Simulated locked file"):
        write_csv_atomic("test_data.csv", corrupted_df, data_dir=tmp_path)

    monkeypatch.undo()

    # Original CSV must remain intact
    restored_df = read_csv("test_data.csv", data_dir=tmp_path)
    assert restored_df["item"].tolist() == ["apples"]
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == []


def test_path_traversal_is_rejected(tmp_path):
    """Assert file operations reject path separators and '..' traversal attempts."""
    traversal_names = [
        "../secrets.json",
        "..\\passwords.csv",
        "sub/dir/test.json",
        "sub\\dir\\test.csv",
        "/etc/shadow",
        "\\Windows\\system32",
        "..",
        "file..test.json",
        "",
        "   ",
    ]

    for bad_name in traversal_names:
        with pytest.raises(ValueError):
            resolve_path(bad_name, data_dir=tmp_path)

        with pytest.raises(ValueError):
            read_json(bad_name, data_dir=tmp_path)

        with pytest.raises(ValueError):
            read_csv(bad_name, data_dir=tmp_path)

        with pytest.raises(ValueError):
            write_json_atomic(bad_name, {}, data_dir=tmp_path)

        with pytest.raises(ValueError):
            write_csv_atomic(bad_name, pd.DataFrame(), data_dir=tmp_path)


def test_writes_never_go_to_shared_default_folder(monkeypatch):
    """Assert write operations to the shared default seed data directory are forbidden."""
    from src.config import PROJECT_ROOT

    seed_dir = PROJECT_ROOT / "data"
    monkeypatch.delenv("FINANCE_DATA_DIR", raising=False)

    with pytest.raises(PermissionError, match="Writes never go to a shared default folder"):
        write_json_atomic("budgets.json", {}, data_dir=seed_dir)

    with pytest.raises(PermissionError, match="Writes never go to a shared default folder"):
        write_csv_atomic("transactions.csv", pd.DataFrame(), data_dir=seed_dir)

    with pytest.raises(PermissionError, match="Writes never go to a shared default folder"):
        append_audit("test_action", {}, {}, "human", workspace=seed_dir)


def test_session_id_validation():
    """Assert session_id validates according to ^[A-Za-z0-9_-]{8,64}$."""
    # Valid
    validate_session_id("abcdefgh")
    validate_session_id("session_12345678")
    validate_session_id("User-Session-01_ABC")
    validate_session_id("x" * 64)

    # Invalid
    invalid_ids = [
        "short",  # < 8
        "x" * 65,  # > 64
        "has space",
        "has/slash",
        "has..dots",
        "session!@",
        "",
        None,
    ]
    for bad_id in invalid_ids:
        with pytest.raises(ValueError):
            validate_session_id(bad_id)


def test_two_session_ids_never_share_files(tmp_path):
    """Assert workspaces for different session IDs are completely isolated from each other."""
    ws1 = create_workspace("session_alpha_1234", base_dir=tmp_path)
    ws2 = create_workspace("session_beta_5678", base_dir=tmp_path)

    assert ws1 != ws2
    assert ws1.exists()
    assert ws2.exists()

    # Both workspaces initially have seed budgets
    b1_initial = read_json("budgets.json", data_dir=ws1)
    b2_initial = read_json("budgets.json", data_dir=ws2)
    assert b1_initial["Dining"] == 300.0
    assert b2_initial["Dining"] == 300.0

    # Modify budget in workspace 1 only
    b1_modified = dict(b1_initial)
    b1_modified["Dining"] = 999.0
    write_json_atomic("budgets.json", b1_modified, data_dir=ws1)

    # Verify workspace 1 has new value while workspace 2 is strictly untouched
    assert read_json("budgets.json", data_dir=ws1)["Dining"] == 999.0
    assert read_json("budgets.json", data_dir=ws2)["Dining"] == 300.0

    # Reset workspace 1 and confirm it returns to seed values
    reset_workspace("session_alpha_1234", base_dir=tmp_path)
    assert read_json("budgets.json", data_dir=ws1)["Dining"] == 300.0
    assert read_json("budgets.json", data_dir=ws2)["Dining"] == 300.0


def test_audit_line_is_written_and_truncated(tmp_path):
    """Assert append_audit writes JSONL records with ISO timestamp and truncates strings to 500 chars."""
    ws = create_workspace("session_audit_test", base_dir=tmp_path)

    long_before = "B" * 600
    long_after = "A" * 700

    audit_path = append_audit(
        action="change_budget",
        before={"category": "Dining", "note": long_before},
        after={"category": "Dining", "note": long_after},
        source="human",
        workspace=ws,
    )
    assert audit_path.exists()

    records = read_audit(workspace=ws)
    assert len(records) == 1
    rec1 = records[0]

    assert rec1["action"] == "change_budget"
    assert rec1["source"] == "human"
    assert "timestamp" in rec1
    # Check truncation to 500 chars
    assert len(rec1["before"]["note"]) == 500
    assert len(rec1["after"]["note"]) == 500

    # Append second audit line from model
    append_audit(
        action="propose_budget",
        before="short string",
        after="short result",
        source="model",
        workspace=ws,
    )
    records = read_audit(workspace=ws)
    assert len(records) == 2
    assert records[1]["source"] == "model"

    # Reject invalid source
    with pytest.raises(ValueError, match="Invalid source"):
        append_audit("bad_action", {}, {}, "bot", workspace=ws)


def test_validator_amount():
    """Assert validate_amount accepts valid amounts and rejects invalid ones."""
    # Accept cases
    accept_cases = [
        (50, 50.0),
        (100.5, 100.5),
        (42.99, 42.99),
        ("42.99", 42.99),
        ("50", 50.0),
        (100000, 100000.0),
        ("100000.00", 100000.0),
        (0.01, 0.01),
    ]
    for val, expected in accept_cases:
        ok, res = validate_amount(val)
        assert ok is True, f"Failed for {val}: {res}"
        assert res == expected

    # Reject cases
    reject_cases = [
        0,  # <= 0
        -0.01,  # <= 0
        -50,  # <= 0
        100000.01,  # > 100000
        200000,  # > 100000
        10.555,  # > 2 decimal places
        "10.123",  # > 2 decimal places
        "10.500",  # 3 decimal places in string
        "abc",  # not numeric
        "",  # empty
        None,
        True,  # boolean
        float("nan"),
        float("inf"),
    ]
    for val in reject_cases:
        ok, err = validate_amount(val)
        assert ok is False, f"Expected rejection for {val}, got success: {err}"
        assert isinstance(err, str)


def test_validator_date():
    """Assert validate_date accepts ISO dates within 2000-01-01 and sandbox date, and rejects others."""
    # Accept cases
    accept_cases = [
        ("2026-07-15", "2026-07-15"),
        ("2000-01-01", "2000-01-01"),
        ("2026-08-31", "2026-08-31"),
        (date(2026, 7, 1), "2026-07-01"),
    ]
    for val, expected in accept_cases:
        ok, res = validate_date(val, sandbox_date="2026-08-31")
        assert ok is True, f"Failed for {val}: {res}"
        assert res == expected

    # Reject cases
    reject_cases = [
        "1999-12-31",  # before 2000-01-01
        "1990-05-15",
        "2026-09-01",  # after sandbox date
        "2027-01-01",
        "2026-02-30",  # invalid calendar date
        "07/15/2026",  # non-ISO format
        "2026-7-15",   # non-standard format
        "not-a-date",
        "",
        None,
    ]
    for val in reject_cases:
        ok, err = validate_date(val, sandbox_date="2026-08-31")
        assert ok is False, f"Expected rejection for {val}, got success: {err}"
        assert isinstance(err, str)


def test_validator_category():
    """Assert validate_category accepts known categories and rejects unknown ones."""
    # Accept cases
    for cat in KNOWN_CATEGORIES:
        ok, res = validate_category(cat)
        assert ok is True
        assert res == cat

    # Case-insensitive acceptance
    ok, res = validate_category("dining")
    assert ok is True
    assert res == "Dining"

    ok, res = validate_category("groceries")
    assert ok is True
    assert res == "Groceries"

    # Reject cases
    reject_cases = [
        "Cryptocurrency",
        "Luxury",
        "Gambling",
        "random_category",
        "",
        "   ",
        123,
        None,
    ]
    for val in reject_cases:
        ok, err = validate_category(val)
        assert ok is False, f"Expected rejection for {val}, got success: {err}"
        assert isinstance(err, str)


def test_validator_text():
    """Assert validate_text strips control characters, removes leading =+-@, enforces 80 char limit, and rejects invalid inputs."""
    # Accept cases
    accept_cases = [
        ("Grocery shopping", "Grocery shopping"),
        ("=Formula injection test", "Formula injection test"),
        ("+Uber ride", "Uber ride"),
        ("-10% credit discount", "10% credit discount"),
        ("@Coffee shop", "Coffee shop"),
        ("Line 1\nLine 2\tControl \x00\x08 characters", "Line 1 Line 2 Control characters"),
        ("A" * 80, "A" * 80),
    ]
    for val, expected in accept_cases:
        ok, res = validate_text(val)
        assert ok is True, f"Failed for {val}: {res}"
        assert res == expected

    # Truncate option
    ok, res = validate_text("A" * 100, truncate=True)
    assert ok is True
    assert res == "A" * 80

    # Reject cases
    reject_cases = [
        "",  # empty
        "    ",  # whitespace
        None,
        "=+-@   ",  # only formula chars and whitespace
        "\x00\x08",  # only control chars
        "A" * 81,  # exceeds 80 chars
    ]
    for val in reject_cases:
        ok, err = validate_text(val)
        assert ok is False, f"Expected rejection for {val}, got success: {err}"
        assert isinstance(err, str)

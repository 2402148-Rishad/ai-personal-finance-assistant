"""Tests for Phase 3.2: Overview and Ledger tabs, human actions, audit logging, and CSV import."""

import json
from pathlib import Path
import re
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src.store import (
    create_workspace,
    set_active_workspace,
    read_csv,
    read_json,
    get_sandbox_today,
    search_transactions,
    add_transaction,
    update_transaction,
    delete_transaction,
    import_transactions,
)
from src.tools import spending_by_category

APP_PATH = (Path(__file__).resolve().parent.parent / "app.py").resolve()


@pytest.fixture
def workspace_env(tmp_path, monkeypatch):
    """Create an isolated workspace from seed data and point all data to it."""
    ws = create_workspace("session_test_phase32", base_dir=tmp_path)
    monkeypatch.setenv("FINANCE_DATA_DIR", str(ws))
    set_active_workspace(ws)
    yield ws
    set_active_workspace(None)


def test_apptest_added_expense_appears_in_month_total():
    """AppTest: an added expense appears in the month total."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])
        set_active_workspace(app_ws)

        # Check baseline spending in Dining for 2026-08
        raw_before = spending_by_category("2026-08")
        data_before = json.loads(raw_before)
        dining_before = data_before.get("spending_by_category", {}).get("Dining", 0.0)

        # Add an expense in Dining: $45.00 on 2026-08-15
        at.text_input(key="add_tx_date").input("2026-08-15")
        at.text_input(key="add_tx_desc").input("AppTest Dinner Expense")
        at.text_input(key="add_tx_amount").input("45.00")
        cat_select = next((s for s in at.selectbox if s.key == "add_tx_category"), None)
        if cat_select and "Dining" in cat_select.options:
            cat_select.select("Dining")

        add_btn = next(b for b in at.button if b.key == "add_tx_submit_btn")
        add_btn.click().run()

        # Success message shown
        assert len(at.success) > 0
        assert "45.00" in at.success[0].value

        # Month total for 2026-08 reflects the added $45.00
        set_active_workspace(app_ws)
        raw_after = spending_by_category("2026-08")
        data_after = json.loads(raw_after)
        dining_after = data_after.get("spending_by_category", {}).get("Dining", 0.0)
        assert round(dining_after - dining_before, 2) == 45.00


def test_apptest_bad_amount_shows_error_and_writes_nothing():
    """AppTest: a bad amount shows an error and writes nothing."""
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])

        # Initial transaction count
        tx_df_before = read_csv("transactions.csv", workspace=app_ws)
        count_before = len(tx_df_before)

        # Enter bad amount: -100.00
        at.text_input(key="add_tx_date").input("2026-08-15")
        at.text_input(key="add_tx_desc").input("Invalid Amount Item")
        at.text_input(key="add_tx_amount").input("-100.00")

        add_btn = next(b for b in at.button if b.key == "add_tx_submit_btn")
        add_btn.click().run()

        # Error message displayed
        assert len(at.error) > 0
        assert "Amount" in at.error[0].value
        assert len(at.success) == 0

        # Wrote nothing
        tx_df_after = read_csv("transactions.csv", workspace=app_ws)
        assert len(tx_df_after) == count_before


def test_apptest_upload_with_one_bad_row_imports_only_good_rows():
    """AppTest: an upload with one bad row imports only the good rows."""
    csv_content = (
        b"date,description,amount,category,type\n"
        b"2026-08-10,=Good Lunch Purchase,35.00,Dining,expense\n"
        b"2026-08-11,Bad Row Invalid Amount,-999.00,Dining,expense\n"
        b"2026-08-12,+Good Metro Travel,12.50,Transport,expense\n"
    )

    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        app_ws = create_workspace(at.session_state["session_id"])

        tx_df_before = read_csv("transactions.csv", workspace=app_ws)
        count_before = len(tx_df_before)

        # Upload the CSV
        at.file_uploader[0].upload("import_sample.csv", csv_content, "text/csv").run()

        # Find import button (should say "Import 2 Valid Rows")
        import_btn = next((b for b in at.button if b.key == "import_valid_rows_btn"), None)
        assert import_btn is not None
        assert "2" in import_btn.label

        import_btn.click().run()

        # Success message indicates 2 rows imported
        assert len(at.success) > 0
        assert "2" in at.success[0].value

        # Exactly 2 transactions were added
        tx_df_after = read_csv("transactions.csv", workspace=app_ws)
        assert len(tx_df_after) == count_before + 2

        # Bad row was excluded
        descriptions = tx_df_after["description"].astype(str).tolist()
        assert not any("Bad Row" in d for d in descriptions)
        # Leading = + stripped from imported descriptions
        assert any(d == "Good Lunch Purchase" for d in descriptions)
        assert any(d == "Good Metro Travel" for d in descriptions)


def test_store_search_filters_and_audit_snapshots(workspace_env):
    """Verify search_transactions filters and audit logs on add, update, delete, and import."""
    ws = workspace_env
    set_active_workspace(ws)

    # 1. Search text filter
    results_metro = search_transactions(query="MetroCard", workspace=ws)
    assert len(results_metro) > 0
    assert all("metrocard" in r.lower() for r in results_metro["description"])

    # 2. Add transaction and check audit log with before=None, after=record, source='human'
    new_item = add_transaction(
        {
            "date": "2026-08-20",
            "description": "Store Add Test",
            "amount": 25.00,
            "category": "Dining",
            "type": "expense",
        },
        workspace=ws,
        source="human",
    )
    new_id = new_item["id"]

    audit_file = ws / "audit.jsonl"
    lines = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").strip().split("\n")]
    last_audit = lines[-1]
    assert last_audit["action"] == "add_transaction"
    assert last_audit["source"] == "human"
    assert last_audit["before"] is None
    assert last_audit["after"]["id"] == new_id

    # 3. Update transaction and check audit log
    updated = update_transaction(
        new_id,
        {"description": "Updated Store Item", "amount": 30.00},
        workspace=ws,
        source="human",
    )
    lines = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").strip().split("\n")]
    update_audit = lines[-1]
    assert update_audit["action"] == "update_transaction"
    assert update_audit["source"] == "human"
    assert update_audit["before"]["description"] == "Store Add Test"
    assert update_audit["after"]["description"] == "Updated Store Item"
    assert update_audit["after"]["amount"] == 30.00

    # 4. Delete transaction and check audit log
    deleted = delete_transaction(new_id, workspace=ws, source="human")
    lines = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").strip().split("\n")]
    delete_audit = lines[-1]
    assert delete_audit["action"] == "delete_transaction"
    assert delete_audit["source"] == "human"
    assert delete_audit["before"]["id"] == new_id
    assert delete_audit["after"] is None

    # 5. Import transactions and check audit log (one line per import)
    records = [
        {"date": "2026-08-21", "description": "Import 1", "amount": 10.0, "category": "Groceries", "type": "expense"},
        {"date": "2026-08-22", "description": "Import 2", "amount": 20.0, "category": "Dining", "type": "expense"},
    ]
    imported_count = import_transactions(records, workspace=ws, source="human")
    assert imported_count == 2
    lines = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").strip().split("\n")]
    import_audit = lines[-1]
    assert import_audit["action"] == "import_transactions"
    assert import_audit["source"] == "human"
    assert import_audit["before"] is None
    assert import_audit["after"]["count"] == 2

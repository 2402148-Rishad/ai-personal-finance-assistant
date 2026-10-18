"""Live integration tests for category clarification and grounding with the real Gemini model."""

import pytest

from src.agent import run_agent
from src.approvals import list_pending
from src.store import create_workspace, set_active_workspace, read_proposals


@pytest.mark.live
def test_clarify_live(tmp_path):
    """Test with real model:
    1. 'Add a $12 coffee' must produce no proposal and a needs_clarification result.
    2. 'Add a $12 coffee for groceries' must produce a proposal with Groceries.
    At most 2 calls total to the real model.
    """
    ws = create_workspace("live_clarify_test_ws", base_dir=tmp_path)
    set_active_workspace(ws)

    # Call 1: "Add a $12 coffee"
    res1 = run_agent("Add a $12 coffee", history=[])
    assert res1.status == "ok"

    # Must produce no proposal
    pending1 = list_pending(workspace=ws)
    stored1 = read_proposals(workspace=ws)
    assert len(pending1) == 0
    assert len(stored1) == 0

    # Must produce a needs_clarification result
    assert any(
        isinstance(tc.get("result"), dict) and tc.get("result", {}).get("status") == "needs_clarification"
        for tc in res1.tool_calls
    )
    assert "Which category" in res1.answer

    # Call 2: "Add a $12 coffee for groceries"
    res2 = run_agent("Add a $12 coffee for groceries", history=[])
    assert res2.status == "ok"

    # Must produce a proposal with Groceries
    pending2 = list_pending(workspace=ws)
    assert len(pending2) >= 1
    latest_prop = pending2[0]
    payload = latest_prop.get("payload", {})
    items = payload.get("items", [])
    assert len(items) >= 1
    assert items[0].get("category") == "Groceries"

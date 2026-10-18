"""Enforcement evidence harness: demonstrates permission gate enforcement against unauthorized tool calls."""

import os
# 1.1) Set FINANCE_EVIDENCE_RUN=1 before importing anything from src
os.environ["FINANCE_EVIDENCE_RUN"] = "1"

from datetime import datetime
import json
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from google.genai import types
from src.agent import run_agent
from src.tools import propose_budget_change, BUDGETS_PATH, PROPOSALS_PATH, LOGS_DIR


def main():
    print("=== STARTING ENFORCEMENT RUN ===")

    # Determine active evidence log file
    today_str = datetime.now().strftime("%Y%m%d")
    evidence_log = LOGS_DIR / f"evidence_{today_str}.jsonl"
    
    # Record starting offset/line count in evidence log
    starting_lines = 0
    if evidence_log.exists():
        with open(evidence_log, "r", encoding="utf-8") as f:
            starting_lines = len(f.readlines())
    print(f"Starting lines in {evidence_log.name}: {starting_lines}")

    # Record state of pending_proposals.json before the run
    proposals_before = {}
    if PROPOSALS_PATH.exists():
        with open(PROPOSALS_PATH, "r", encoding="utf-8") as f:
            try:
                proposals_before = json.load(f)
            except Exception:
                proposals_before = {}

    # 1.3) Create a pending proposal first, by calling propose_budget_change directly, and record that it happened.
    raw_prop = propose_budget_change("Dining", 50.0)
    prop_data = json.loads(raw_prop)
    real_proposal_id = prop_data.get("proposal_id")
    print(f"Created real pending proposal via propose_budget_change: {real_proposal_id}")

    # 1.2) Use a mocked Gemini client that returns one function call to apply_budget_change
    # with proposal_id set to the real proposal ID created by the harness, then a final text answer.
    class MockFunctionCall:
        name = "apply_budget_change"
        args = {"proposal_id": real_proposal_id}

    class MockResponse1:
        candidates = [MagicMock(content=types.Content(role="model", parts=[]))]
        function_calls = [MockFunctionCall()]
        text = None

    class MockResponse2:
        candidates = [MagicMock(content=types.Content(role="model", parts=[]))]
        function_calls = []
        text = "I cannot apply budget changes directly because permission was denied."

    call_count = 0
    def mock_generate_content(model, contents, config):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MockResponse1()
        else:
            return MockResponse2()

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content

    # 1.4) Patch builtins.input with a mock, and assert afterward that it was never called.
    mock_input = MagicMock()

    with patch("src.agent.genai.Client", return_value=mock_client), patch("builtins.input", mock_input):
        result = run_agent(f"Apply the proposal {real_proposal_id} now.")

    # Assert builtins.input was never called
    assert not mock_input.called, "Assertion failed: builtins.input was called!"
    print("Assertion passed: builtins.input was never called.")

    # 1.5) Assert budgets.json is unchanged (Dining 300).
    with open(BUDGETS_PATH, "r", encoding="utf-8") as f:
        budgets = json.load(f)
    assert budgets.get("Dining") == 300.0, f"Assertion failed: Dining budget is {budgets.get('Dining')}, expected 300.0"
    print("Assertion passed: budgets.json Dining is unchanged at 300.0.")

    # 1.6) Read new events written to the evidence log for this run
    new_lines = []
    new_events = []
    if evidence_log.exists():
        with open(evidence_log, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
            new_lines = all_lines[starting_lines:]
            new_events = [json.loads(line) for line in new_lines]

    print("\n--- Events written to evidence log for this run ---")
    for i, ev in enumerate(new_events, 1):
        print(f"Event {i}: [{ev.get('event_type')}] -> {json.dumps(ev.get('data'))}")

    # 2) Label every event in the saved file with its origin: scripted_user_input, injected_model_tool_call, or model_generated.
    # Add a field origin to each event's data in the saved copy only. Don't change the live log.
    # 3) Label the final answer as mock_text rather than model output.
    saved_events = []
    for ev in new_events:
        ev_copy = json.loads(json.dumps(ev))
        etype = ev_copy.get("event_type")
        if etype == "budget_proposed":
            ev_copy["data"]["origin"] = "harness_setup"
        elif etype == "question":
            ev_copy["data"]["origin"] = "scripted_user_input"
        elif etype in ("tool_call", "permission_denied", "tool_result"):
            ev_copy["data"]["origin"] = "injected_model_tool_call"
        elif etype == "final_answer":
            ev_copy["data"]["origin"] = "mock_text"
        else:
            ev_copy["data"]["origin"] = "model_generated"
        saved_events.append(ev_copy)

    # Save labeled events to docs/evidence/runs/run_07_enforcement_blocked_call.jsonl
    runs_dir = PROJECT_ROOT / "docs" / "evidence" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    out_file = runs_dir / "run_07_enforcement_blocked_call.jsonl"
    with open(out_file, "w", encoding="utf-8") as f:
        for ev in saved_events:
            f.write(json.dumps(ev) + "\n")
    print(f"\nSaved {len(saved_events)} labeled events to {out_file.relative_to(PROJECT_ROOT)}")

    # 4) Confirm the tool_call for the real ID is followed by permission_denied
    event_types = [ev.get("event_type") for ev in new_events]
    assert "tool_call" in event_types, "Assertion failed: tool_call event missing!"
    assert "permission_denied" in event_types, "Assertion failed: permission_denied event missing!"
    tool_call_idx = event_types.index("tool_call")
    perm_denied_idx = event_types.index("permission_denied")
    assert tool_call_idx < perm_denied_idx, "Assertion failed: tool_call does not precede permission_denied!"
    assert new_events[tool_call_idx]["data"]["arguments"]["proposal_id"] == real_proposal_id, "Assertion failed: tool_call did not use real_proposal_id!"
    assert new_events[tool_call_idx]["data"]["tool_name"] == "apply_budget_change"
    assert new_events[perm_denied_idx]["data"]["tool_name"] == "apply_budget_change"
    print(f"Confirmation passed: tool_call for real proposal ID '{real_proposal_id}' is followed by permission_denied.")

    # 5) Delete any pending proposal the harness created. Confirm data/budgets.json is unchanged with git diff.
    if PROPOSALS_PATH.exists():
        with open(PROPOSALS_PATH, "r", encoding="utf-8") as f:
            proposals_current = json.load(f)
        proposals_current.pop(real_proposal_id, None)
        with open(PROPOSALS_PATH, "w", encoding="utf-8") as f:
            json.dump(proposals_current, f, indent=2)
    print("Cleaned up created real pending proposal from pending_proposals.json.")

    # 5b) Print logs/pending_proposals.json after cleanup, and confirm it matches its state before the run.
    with open(PROPOSALS_PATH, "r", encoding="utf-8") as f:
        proposals_after = json.load(f)
    print("\n--- logs/pending_proposals.json after cleanup ---")
    print(json.dumps(proposals_after, indent=2))
    assert proposals_after == proposals_before, "Assertion failed: pending_proposals.json does not match state before the run!"
    print("Confirmation passed: pending_proposals.json matches pre-run state exactly.")


if __name__ == "__main__":
    main()

# Live Demonstration Session Evidence

This directory contains the session artifacts and complete execution transcript for a scripted walkthrough of the `DEMO_SCRIPT.md` prompts through the agent pipeline with the live model.

## Run Metadata
- **Date**: 2026-10-20
- **Model**: `gemini-3.5-flash-lite`
- **Model Calls**: 10
- **UI Interaction Method**: In this automated execution run, interactive UI button clicks and modal confirmations were replaced by direct calls to `approvals.approve()`.

## Files in this Directory
- `run_demo_live.py`: Script that executed the walkthrough and generated the evidence. run_demo_live.py produced the files in this folder.
- `transcript.json`: Machine-readable structured transcript detailing each prompt, agent answer, tool invocations with exact arguments and outputs, and approval resolutions.
- `transcript.md`: Formatted readable log of the entire session dialogue and tool reasoning traces.
- `audit.jsonl`: Append-only immutable audit trail recorded during the session, capturing the human approval of the Dining budget proposal with before/after state diffs and undo tokens.
- `proposals.json`: Proposals ledger from the session workspace.

## Benchmark Status and Final Result Files
The live and mock evaluation results are recorded in the parent directory (`submission/evidence/`):
- `2026-10-19-live-final-2.json`: **Final live benchmark** evaluation results.
- `2026-10-19-live.json`: Earlier live benchmark run kept for history.
- `2026-10-19-live-final.json`: Earlier live benchmark run kept for history.
- `2026-10-19-mock.json`: Offline deterministic test suite run.
- `2026-10-19-scenarios-mock.json`: Multi-step scenario evaluation suite.

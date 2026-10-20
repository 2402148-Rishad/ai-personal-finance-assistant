# Evidence Directory Index

All data in this directory and across the assistant evaluation environment is simulated sandbox data. There are no connections to real bank accounts and no on-chain transactions.

---

## Evidence Inventory

| File | What it shows | Checklist item (05 or 06) |
|---|---|---|
| `demo_session/` | Complete execution artifacts and records for a scripted live walkthrough of `DEMO_SCRIPT.md` prompts through the agent pipeline using `gemini-3.5-flash-lite` (10 model calls). | 05 |
| `demo_session/README.md` | Run metadata, model configuration, execution notes regarding pre-dbc9a32 transcript step 2, and file manifest for the live demo session. | 05 |
| `demo_session/run_demo_live.py` | Automated execution script that ran the 10-step demo script against the live model and produced all session evidence files. | 05 |
| `demo_session/transcript.json` | Machine-readable structured transcript detailing each prompt, agent answer, tool invocations with exact arguments and outputs, and approval resolutions. | 05 |
| `demo_session/transcript.md` | Formatted readable Markdown log of the entire session dialogue, tool execution traces, and human approval flow. | 05 |
| `demo_session/audit.jsonl` | Append-only audit trail recorded during the demonstration, capturing the human approval of the Dining budget proposal with before/after state diffs and undo tokens. | 05 |
| `demo_session/proposals.json` | Post-run proposals ledger from the demonstration session workspace showing proposal lifecycle state. | 05 |
| `2026-10-19-live-final-2.json` | Final live benchmark evaluation results with `gemini-3.5-flash-lite` (30 of 31 passed, 96.8% pass rate, 0 errors across 25 standard questions and 6 live adversarial checks). | 06 |
| `2026-10-19-live-final.json` | Earlier live benchmark evaluation run on 2026-10-19 before the phase 6.7 grounding fix (25 of 31 passed, 6 failed, 0 errors). | 06 |
| `2026-10-19-live.json` | Earlier live benchmark evaluation run on 2026-10-19 on the 25-question suite before adversarial questions were integrated (23 of 25 passed, 2 failed). | 06 |
| `2026-10-19-mock.json` | Deterministic offline evaluation suite benchmark results using `mock-fin` (31 of 31 passed, 100.0% pass rate, 0 errors). | 06 |
| `2026-10-18-mock.json` | Earlier deterministic offline evaluation run on 2026-10-18 using `mock-fin` (25 of 25 passed, 100.0% pass rate, 0 errors). | 06 |
| `2026-10-19-scenarios-mock.json` | Multi-step stateful scenario evaluation results covering 5 golden flows (`G1`–`G5`) and 18 adversarial scenarios (`ADV01`–`ADV18`) with 23 of 23 passed (100.0%). | 06 |
| `live_adversarial.json` | Test specifications, attack vectors, expected behaviors, and evaluation rules for the 6 live adversarial evaluation cases (`adv_live_01`–`adv_live_06`). | 06 |

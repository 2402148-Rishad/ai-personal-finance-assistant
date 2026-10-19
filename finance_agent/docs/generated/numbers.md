# System Numbers and Quantitative Baselines

This document records the exact, verified counts and thresholds across the codebase.
All documentation references to counts, timeframes, or thresholds must draw directly from these verified facts.

## Core System Metrics

- **Pytest Collected Tests**: 265 tests
- **Model Name**: `gemini-3.5-flash-lite`
- **MAX_AGENT_STEPS**: 8 steps
- **Proposal Expiry**: 24 hours
- **Daily Model-Call Cap Default**: 200 calls
- **Sandbox Horizon Date**: `2026-08-31`
- **Total Model-Visible Tools**: 24 tools
- **Read-Only Tools**: 17 tools
- **Proposal Tools**: 7 tools

## Evaluation Results per Mode

| Result File | Mode | Model | Total Cases | Passed Cases | Failed Cases | Summary Score |
|---|---|---|---|---|---|---|
| `2026-10-18-mock.json` | mock | `mock-fin` | 25 cases | 25 passed | 0 failed | 25 of 25 passed, 0 errors |
| `2026-10-19-live-final-2.json` | live | `gemini-3.5-flash-lite` | 31 cases | 30 passed | 1 failed | 30 of 31 passed, 0 errors |
| `2026-10-19-live-final.json` | live | `gemini-3.5-flash-lite` | 31 cases | 25 passed | 6 failed | 25 of 31 passed, 0 errors |
| `2026-10-19-live.json` | live | `gemini-3.5-flash-lite` | 25 cases | 23 passed | 2 failed | 23 of 25 passed, 0 errors |
| `2026-10-19-mock.json` | mock | `mock-fin` | 31 cases | 31 passed | 0 failed | 31 of 31 passed, 0 errors |
| `2026-10-19-scenarios-mock.json` | mock | `mock-fin` | 23 cases | 23 passed | 0 failed | 23 of 23 passed |

## Thresholds and Operational Constants

- **Cashflow Horizon**: 30 days lookahead (`cashflow_projection`)
- **Bill Due Alert Window**: 3 days (`alert_bills_days` preference default)
- **Urgent Proposal Expiry Threshold**: 2 hours before expiration
- **Spending Spike Detection Threshold**: 50 percent increase and 50 dollars absolute jump
- **Budget Warning Level**: 80 percent of category limit
- **Budget Exceeded Level**: 100 percent of category limit
- **API Retry Backoff Delays**: 15 seconds, 30 seconds, 60 seconds
- **Conversation History Maximum**: 10 turns retained
- **Streamlit AppTest Timeout**: 10 seconds
- **Batch Add Maximum Proposal Items**: 10 items per batch

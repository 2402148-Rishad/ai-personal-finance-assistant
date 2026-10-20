# Personal Finance Assistant

An intelligent, safety-first AI financial assistant built for FinTechathon 2026 (International Track, Topic A: Personal Finance Assistant).
The assistant analyzes transaction history, tracks category budgets, forecasts forward cashflow, flags spending spikes, discovers recurring subscriptions, and stages financial changes with strict human-in-the-loop approvals.

🌐 **Live Deployed Application**: https://ai-personal-finance-assistant-acceyufjoyulunmsa5rblo.streamlit.app/

---

## Key Features

- **Grounded Spending Analytics**: Instant calculation of monthly income, expenses, net savings, and category breakdowns. Every cited dollar figure is verified against deterministic calculations.
- **Spending Spike Detection**: Flags anomalous month-over-month increases (>50 percent and >$50 jump) to catch budget overruns before they escalate.
- **30-Day Cashflow Forecasting**: Simulates day-by-day account balances over a forward 30 days horizon, taking scheduled recurring bills into account.
- **Human-in-the-Loop Mutations**: The model is restricted to `READ` and `PROPOSE` tools (from a suite of 24 tools). Changes to budgets, transactions, or bills are staged as unapplied proposals that require deliberate human confirmation.
- **Two-Tier Approval Gate**: Low-risk proposals can be approved with `"yes"` or a 1-click button. Destructive actions (deletions and cancellations) require the exact token `"CONFIRM"`.
- **Reversibility & Audit Trail**: Every approved change logs before-and-after snapshots in the audit log, enabling 1-click rollback via the **Undo** engine. Undo-of-undo is blocked.
- **Deterministic Security Boundary**: Hardened pre-filters refuse out-of-scope requests (moving money, bank transfers, professional financial advice) before invoking AI models.
- **Daily Quota Protection**: Enforces a global daily model-call cap (default: 200 calls) to prevent API exhaustion and runaway costs.

---

## Local Setup

### 1. Requirements & Setup
- Python 3.10 or newer.
- Google Gemini API key from Google AI Studio.

Clone the repository and set up a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate          # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Credentials
Create a `.env` file in `finance_agent/` (or repository root):
```bash
GEMINI_API_KEY=your_gemini_api_key_here
```
*(Note: `.env` is ignored by version control and is never committed.)*

### 3. Launch the Application

#### Streamlit Web Interface (Recommended)
From the `finance_agent` directory:
```bash
streamlit run app.py
```
Or from the repository root:
```bash
streamlit run finance_agent/app.py
```

#### Terminal Interactive CLI
```bash
python main.py
```

---

## Project Architecture & Layout

```text
finance_agent/
├── app.py                      # Main Streamlit web application entrypoint
├── main.py                     # Interactive terminal chat entrypoint
├── src/                        # Core application package
│   ├── agent.py                # Multi-turn tool execution loop & grounding checks
│   ├── tools.py                # 24 model-visible analytical & proposal tools
│   ├── permissions.py          # Three-tier permission framework (READ/PROPOSE/APPLY)
│   ├── approvals.py            # Proposal lifecycle, two-tier gates, undo engine
│   ├── store.py                # Session workspace isolation & atomic file I/O
│   ├── validators.py           # Strict schema, date, and amount sanitization
│   ├── categories.py           # Category grounding & fuzzy suggestion engine
│   ├── usage.py                # Daily model-call quota enforcement
│   ├── logger.py               # Audit logger & regex secret scrubber
│   └── prompts.py              # System prompt & financial persona instructions
├── data/                       # Baseline sandbox ledger records
│   ├── transactions.csv        # Simulated historical transactions (June–Aug 2026)
│   ├── bills.csv               # Recurring bill commitments
│   ├── budgets.json            # Monthly category budget limits
│   └── account.json            # Simulated baseline bank balances
├── docs/                       # Technical & governance documentation
│   ├── TECHNICAL.md            # Architecture, data flows, and state management
│   ├── SECURITY.md             # Security self-assessment & adversarial matrices
│   ├── FEATURES.md             # Complete Topic A capabilities index
│   ├── USER_GUIDE.md           # First-time user manual & workspace tour
│   ├── DEMO_SCRIPT.md          # 5-minute presentation script with fallbacks
│   └── check_docs.py           # Automated documentation verification script
├── eval/                       # Benchmark & scenario evaluation suite
│   ├── run_eval.py             # Benchmark runner (31 evaluation cases)
│   ├── run_scenarios.py        # Multi-step golden flows & adversarial suites
│   └── results/                # Recorded evaluation runs (mock & live)
└── tests/                      # Automated unit test suite (275 tests)
```

---

## Running Tests & Running Evals

All tests and evaluations run offline by default without requiring an active Gemini API key:

### Running Tests (pytest -q)
```bash
pytest -q
```
*Or using Python module invocation:*
```bash
python -m pytest -q
```
Executes all **275 tests** across **43 test files**, including validator boundary tests, permission enforcement checks, prompt injection defenses, and atomic store isolation.

### Running Evals
```bash
# Benchmark evaluation runner (31 cases)
python eval/run_eval.py

# Multi-step scenario harness (23 cases)
python eval/run_scenarios.py
```
Executes the **31 cases** benchmark suite in offline mock mode (scoring 31 of 31 passed) and the **23 cases** stateful scenario suite, validating multi-step golden flows (`G1`–`G5`) and adversarial security scenarios (`ADV01`–`ADV18`).

### Documentation Consistency Verification
```bash
python docs/check_docs.py
```
Validates that every referenced file path exists on disk and that all cited counts match the generated system baselines.

---

## Documentation Suite

For deeper technical and operational insights, explore the four core documentation guides:

1. [TECHNICAL.md](docs/TECHNICAL.md): Detailed architectural design, tool schemas, multi-session state isolation, and audit trail guarantees.
2. [SECURITY.md](docs/SECURITY.md): Comprehensive security self-assessment, threat model, permission tiers, secret scanning report, and adversarial test results.
3. [FEATURES.md](docs/FEATURES.md): Itemized inventory of every Topic A feature with code locations, example prompts, and test coverage.
4. [USER_GUIDE.md](docs/USER_GUIDE.md): Practical user guide explaining how to navigate the 4 UI tabs, interpret "How I got this", and handle proposals.
5. [DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md): Step-by-step 5-minute presentation script with contingency fallbacks.

---

## Deployment on Streamlit Community Cloud

- **Live Deployed Application**: https://ai-personal-finance-assistant-acceyufjoyulunmsa5rblo.streamlit.app/
- **Main Application File**: Configured with main file `finance_agent/app.py` for deployment on Streamlit Community Cloud.
- **Secrets Management**: `GEMINI_API_KEY` set in app secrets (via the Streamlit Community Cloud console), never in the repo.
- **Session Isolation**: Each visiting user operates within an isolated temporary workspace created under `workspaces/` via Python `ContextVar`, preventing cross-session data leakage.
- **Zero Real Bank Connections**: The assistant operates strictly over sandbox data for the simulated horizon (June 1, 2026 to August 31, 2026). It cannot access external banking APIs or transfer real funds.
- **Informational Scope**: Outputs are educational financial summaries and do not constitute certified financial or investment advice.

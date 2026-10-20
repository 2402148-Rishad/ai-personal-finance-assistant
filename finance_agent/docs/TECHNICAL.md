# Fin: Autonomous Personal Finance Assistant — Technical System Architecture & Specification

## 1. Purpose and Scope

Fin is an autonomous personal finance assistant built to provide private, deterministic, and verifiable financial analytics over personal spending, recurring obligations, budgets, and savings goals. 

### What Fin Does
- **Deterministic Financial Analytics**: Computes monthly income, expenses, category spending breakdowns, cash flow trajectories, savings rates, and duplicate charges directly from ledger records without mathematical hallucination.
- **Forward-Looking Cashflow Projections**: Simulates account balances across a 30 days horizon by combining historical transaction cadence with scheduled upcoming bills.
- **Proactive Anomaly & Risk Detection**: Monitors spending spikes (>50% increase and >=$50 jump), budget overruns (>=80% warning and >=100% exceeded), upcoming bill obligations, and cash shortfalls.
- **Safe Human-in-the-Loop Proposal Engine**: Stages financial modifications (adding transactions, modifying budgets, adjusting recurring bills, creating goals) as pending proposals requiring explicit human confirmation before committing to disk.
- **Full State Reversibility**: Maintains an append-only audit log in audit.jsonl and provides an undo mechanism to safely revert applied modifications.

### What Fin Does Not Do (Scope Boundaries)
- **No Live Bank Credentials or Fund Transfers**: Fin has no connection to real-world banking APIs, Plaid, or payment networks. It cannot move money, initiate ACH transfers, or pay bills.
- **No Autonomous Direct Writes**: The AI model cannot directly write to, edit, or delete any financial records. Every state modification requires explicit human approval via the UI.
- **No Unaudited Mutations**: Every change to transaction records, budgets, or goals is recorded with timestamps and before/after diffs in an append-only audit trail.

**Live Application URL**: https://ai-personal-finance-assistant-acceyufjoyulunmsa5rblo.streamlit.app/

---

## 2. Architecture

Fin is designed with a defense-in-depth architecture separating natural language reasoning from deterministic calculation, file I/O, and permission-gated state mutations.

### Component Diagram

```mermaid
graph TD
    User([User]) <--> UI[Streamlit Frontend App<br>app.py]
    UI <--> AgentRuntime[Agent Runtime & Loop<br>src/agent.py]
    
    subgraph Core Safety & Execution Boundary
        AgentRuntime <--> ModelClient[Gemini 3.5 Flash Lite<br>Google GenAI SDK]
        AgentRuntime --> PreFilters[Deterministic Pre-Filters<br>Out-of-Scope & Refusals]
        AgentRuntime --> GroundingCheck[Grounding Validator & Fallback<br>src/agent.py]
        AgentRuntime --> Permissions[Permission Guard<br>src/permissions.py]
    end

    subgraph Deterministic Tool Suite
        Permissions --> Tools[Financial Analysis Tools<br>src/tools.py]
        Tools --> CategoryEngine[Category Grounding<br>src/categories.py]
        Tools --> PeriodEngine[Date & Period Resolver<br>src/periods.py]
    end

    subgraph Human-in-the-Loop & State Management
        AgentRuntime --> ApprovalsEngine[Approvals & Undo Engine<br>src/approvals.py]
        ApprovalsEngine --> ProposalsFile[Pending Proposals<br>pending_proposals.json]
        UI -->|Manual Click 'Approve'| ApprovalsEngine
        ApprovalsEngine --> StoreLayer[Isolated Workspace Store<br>src/store.py]
    end

    subgraph Proactive Alerting
        StoreLayer --> AlertEngine[Alerts Engine<br>src/alerts.py]
        AlertEngine --> UIBanner[Actionable Alert Banner<br>app.py]
    end

    subgraph Isolated Storage & Audit
        StoreLayer --> WorkspaceData[(Session Data Files<br>transactions, bills, budgets, goals)]
        StoreLayer --> AuditLog[(Append-Only Audit Log<br>audit.jsonl)]
    end
```

### Turn Execution Sequence Diagram

The following sequence illustrates a single conversational chat turn involving model reasoning, tool execution, grounding enforcement, and proposal creation:

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Streamlit UI (app.py)
    participant Agent as Agent Loop (src/agent.py)
    participant Model as Gemini 3.5 Flash Lite
    participant Tools as Tools (src/tools.py)
    participant Store as Store (src/store.py)
    participant Inbox as Proposals Inbox

    User->>UI: Enter message (e.g. "Add $25 for dining")
    UI->>Agent: run_agent(question, history)
    Agent->>Agent: Check deterministic pre-filters (out-of-scope & refusals)
    Agent->>Model: generate_content(contents, tools=agent_tool)
    Model-->>Agent: FunctionCall propose_add_transactions(items)
    Agent->>Agent: check_permission("propose_add_transactions") -> Tier.PROPOSE
    Agent->>Tools: propose_add_transactions(items)
    Tools->>Store: Stage proposal in pending_proposals.json
    Store-->>Tools: Proposal prop_a1b2 created (pending_confirmation)
    Tools-->>Agent: Tool execution result JSON
    Agent->>Model: Send ToolResponse back in loop
    Model-->>Agent: Natural language answer
    Agent->>Agent: Grounding check: verify cited amounts in tool output
    Agent->>Agent: build_source_line(tool_calls)
    Agent-->>UI: AgentResult(answer, source_line, tool_calls)
    UI-->>User: Render assistant answer + Source expander
    UI->>Inbox: Render interactive Approval Card with before/after diff
    User->>UI: Click "Approve" button
    UI->>Store: approve("prop_a1b2") -> commit to transactions.csv
    Store->>Store: Append transaction & write to audit.jsonl
    UI-->>User: Ledger updated & confirmation rendered
```

---

## 3. Repository Map

```
ai-personal-finance-assistant/
│
├── app.py                         # Streamlit multi-tab user interface and component layout
├── requirements.txt               # Pinned Python package dependencies
├── pytest.ini                     # Pytest configuration and test options
│
├── src/                           # Core application and agent logic
│   ├── agent.py                   # Autonomous agent loop, grounding checks, and fallback logic
│   ├── alerts.py                  # Proactive alerts engine evaluating financial risk thresholds
│   ├── approvals.py               # Human-in-the-loop proposal approval, rejection, and undo engine
│   ├── categories.py              # Fuzzy category matching, suggested categories, and verification
│   ├── config.py                  # Environment config, constants, model names, and sandbox date
│   ├── formatters.py              # Human-readable currency, date, and expiry formatting
│   ├── logger.py                  # Structured event logger with API key and secret scrubbing
│   ├── periods.py                 # Natural language date/period parser (e.g. "July 2026")
│   ├── permissions.py             # Security tiers (READ, PROPOSE, APPLY) and execution gatekeeper
│   ├── prompts.py                 # System prompt construction, safety boundaries, and prompt grounding
│   ├── store.py                   # Atomic file I/O, session workspace isolation, and audit logging
│   ├── tools.py                   # 24 deterministic financial analysis and proposal tools
│   └── validators.py              # Input sanitizers for amounts, dates, categories, and descriptions
│
├── data/                          # Baseline seed financial records (read-only baseline)
│   ├── account.json               # Simulated starting balance for cashflow simulation
│   ├── bills.csv                  # Baseline recurring bill schedules
│   ├── budgets.json               # Baseline monthly category limits
│   └── transactions.csv           # Itemized transaction records from June to August 2026
│
├── docs/                          # Documentation and automated verification tools
│   ├── TECHNICAL.md               # This technical architecture document
│   ├── build_facts.py             # Facts generator building tool_catalogue, test_map, and numbers
│   ├── check_docs.py              # Automated validator enforcing claim and path accuracy in docs
│   ├── evidence/                  # Evaluation run logs, evidence matrices, and live run transcripts
│   └── generated/                 # Generated reference documents
│       ├── numbers.md             # Ground truth repository numbers and quantitative metrics
│       ├── test_map.md            # Test file map and adversarial scenario coverage matrix
│       └── tool_catalogue.md      # Model-visible tool catalogue and unexposed function catalogue
│
├── eval/                          # Benchmarks, evaluation harnesses, and scenario runners
│   ├── run_eval.py                # 31-question benchmark runner (mock and live modes)
│   ├── run_scenarios.py           # Multi-step stateful scenario runner (G1–G5, ADV01–ADV18)
│   ├── live_adversarial.json      # 6 adversarial test cases evaluated against the live Gemini model
│   └── results/                   # Timestamped result JSON files across evaluation runs
│
└── tests/                         # Automated unit, integration, and security test suites (275 tests across 43 test files)
    ├── test_adversarial_model.py  # Scripted-model adversarial attacks (ADV01–ADV18)
    ├── test_analysis.py           # Calculation tests for monthly summary, net savings, cashflow
    ├── test_app_ui.py             # Streamlit UI integration tests
    ├── test_approvals.py          # Proposal lifecycle, two-phase commits, and undo logic
    ├── test_config.py             # Configuration loading and environment variables
    ├── test_golden_g1.py          # End-to-end golden flow integration tests
    ├── test_injection.py          # Prompt injection, formula injection, and delimiter attacks
    ├── test_permissions.py        # Permission tier validation and unapproved call blocking
    ├── test_phase67_grounding.py  # Grounding verification and fallback replacement tests
    ├── test_phase68_paraphrases.py# Synonym and paraphrase detection tests
    ├── test_proposals.py          # Tool proposal generation and data protection
    ├── test_store.py              # Workspace isolation, path traversal, and atomic write tests
    └── test_tools.py              # Functional validation of all 24 financial tools
```

---

## 4. Data Model

The financial state is maintained using structured, human-readable formats (CSV, JSON, JSONL) designed for transparency, version control, and auditable diffing.

### 1. `data/transactions.csv`
Itemized transaction history containing credits and debits:
- `id` (string): Stable, deterministic unique identifier (e.g. `t89cb81ab2a`).
- `date` (string, ISO `YYYY-MM-DD`): Date the transaction posted.
- `month` (string, `YYYY-MM`): Derived monthly index for partition filtering.
- `category` (string): Grounded spending category matching workspace budgets.
- `description` (string): Human-readable payee or transaction description.
- `type` (string): Either `expense` or `income`.
- `amount` (float): Positive dollar amount with up to 2 decimal places.

### 2. `data/bills.csv`
Schedule of recurring obligations:
- `bill_name` (string): Name of the recurring bill (e.g. `Apartment Rent Payment`).
- `amount` (float): Recurring obligation cost.
- `category` (string): Associated spending category.
- `frequency` (string): Billing cadence (`monthly`, `quarterly`, `annual`).
- `due_date` (string, optional): Specific ISO calendar due date.
- `due_day` (integer, optional): Calendar day of the month when due (1–31).

### 3. `data/budgets.json`
Key-value mapping of monthly category caps in USD:
```json
{
  "Dining": 300.0,
  "Groceries": 500.0,
  "Health": 150.0,
  "Insurance": 200.0,
  "Other": 100.0,
  "Rent": 1500.0,
  "Shopping": 200.0,
  "Transport": 150.0,
  "Utilities": 150.0
}
```

### 4. Financial Goals (goals.json)
Structured financial targets maintained in session storage:
- `id` (string): Unique goal identifier (e.g. `g_7a8b9c`).
- `name` (string): Target description (e.g. `Emergency Fund`).
- `target_amount` (float): Target dollar total.
- `target_date` (string, `YYYY-MM-DD`): Target completion horizon.
- `saved_so_far` (float): Progress saved to date.
- `created_at` (string, ISO datetime): Goal creation timestamp.

### 5. User Preferences (preferences.json)
User configuration settings maintained in session storage:
- `savings_target_percent` (float, default 20.0): Target percentage of income to save.
- `alert_bills_days` (integer, default 3): Forward window in days for bill alerts.

### 6. `data/account.json`
Simulated sandbox balance configuration:
```json
{
  "starting_balance": 5000.0,
  "as_of_date": "2026-08-31"
}
```

### 7. Staged Proposals (proposals.json / pending_proposals.json)
Staged human-in-the-loop proposals awaiting confirmation:
- `id` (string): Unique proposal handle (e.g. `prop_f5c7a583`).
- `kind` (string): Action type (`add_transaction`, `update_transaction`, `delete_transaction`, `budget_change`, `bill_change`, `goal_add`, `goal_delete`).
- `payload` (dict): Proposed new values or delta payload.
- `preview` (dict): Explicit `before` and `after` records for user review.
- `risk` (string): Risk classification (`low` or `high`). Deletion and cancellation are flagged `high`.
- `created_at` (string, ISO datetime): Proposal creation timestamp.
- `expires_at` (string, ISO datetime): Automatic expiration timestamp set to exactly 24 hours after creation.
- `status` (string): `pending_confirmation`, `applied`, `rejected`, or `expired`.

### 8. Audit Trail (audit.jsonl)
Append-only audit ledger, not cryptographically tamper-evident, recording every state mutation in session storage:
Each line records `timestamp`, `action` (`approve`, `reject`, `undo`), `proposal_id`, `user` (`human`), `details` (exact before and after diff), and `status`.

### 9. Per-Session Workspace Isolation (`src/store.py`)
To prevent cross-session contamination and guarantee multi-user isolation on Streamlit Community Cloud:
- Fin provisions an isolated temporary directory under `workspaces/` for each browser session.
- Seed data files from `data/` are copied to the session workspace upon initialization.
- Every read, calculation, and write operation resolves against the active workspace via `contextvars.ContextVar` (`_ACTIVE_WORKSPACE`).
- All disk writes use atomic staging via `store.write_json_atomic()` and `store.write_csv_atomic()` using temporary files and atomic `os.replace` renames. Path traversal attempts (`..`, absolute paths) are rejected by `resolve_path()` in `src/store.py`.

---

## 5. The Agent Loop

The agent runtime in `src/agent.py` implements an autonomous manual tool-calling loop using the Google GenAI SDK without external agent framework bloat.

### 1. Manual Tool-Calling Loop
Rather than delegating execution flow to opaque agent abstractions, we manage the multi-turn loop explicitly:
- Fin initiates each turn by compiling conversation history and registering all 24 tool function declarations in `agent_tool`.
- Model turns run up to `MAX_AGENT_STEPS = 8` steps. If the model invokes a function call, Fin intercepts the invocation, executes the requested Python tool locally, appends the structured `types.Part.from_function_response` to the conversational context, and re-invokes the model.
- If the model returns text without a function call, the loop terminates and yields the final answer.
- Conversation history is trimmed to a maximum of 10 turns via `trim_history()` to prevent context bloat and token exhaustion.

### 2. Category Grounding (`src/categories.py`)
To prevent hallucinated spending categories (such as "Spaceships" or "Cryptocurrency"):
- `get_workspace_categories()` queries `data/budgets.json` and `data/transactions.csv` to establish the exact set of active workspace categories.
- User requests with unstated categories (e.g. "Add a $12 coffee") invoke `suggest_category()`, which checks description tokens against workspace categories, suggests `Dining`, and prompts the user for clarification without creating a proposal prematurely (verified in `tests/test_phase46.py`).

### 3. Numerical Grounding Check
Large language models are prone to arithmetic errors and hallucinated summaries. Fin enforces strict post-generation grounding in `src/agent.py`:
- Every number appearing in the assistant's reply is extracted via regex.
- All numbers are cross-referenced against the actual return values of the tools executed during that turn.
- If the model generates figures not present in the tool results, Fin's grounding verification replaces the hallucinated text with deterministic metric templates (e.g. `"Your groceries spending was $407.31 in July."`), preserving the exact tool values.

### 4. Transparent Source Line
Every answer grounded in data includes an auditable source citation:
- `build_source_line()` inspects all executed tool calls and maps them to their underlying files (e.g. `"Source: transactions.csv (July 2026)"` or `"Source: budgets.json, bills.csv"`).
- In the Streamlit UI, this citation is displayed inside an expandable source panel directly below the message, keeping the primary response clean while providing auditability.

---

## 6. Tool Catalogue & Permission Architecture

The agent runtime enforces a zero-trust permission architecture defined in `src/permissions.py`. Every tool belongs to one of three tiers:
- `READ`: Safe read-only inspection of transactions, bills, budgets, and projections. Permitted for model execution.
- `PROPOSE`: Staging a proposed modification in pending proposals. Permitted for model execution.
- `APPLY`: Applying, approving, or undoing changes to financial records. **Strictly blocked for the model.**

### Model-Visible Tools (24 tools total)

| Tool Name | Tier | Purpose | Required Arguments |
|---|---|---|---|
| `get_monthly_summary` | **READ** | Calculates total income, expenses, net savings, and savings rate for a given month. | `month` |
| `spending_by_category` | **READ** | Calculates total spending per category for a given month, ordered highest to lowest. | `month` |
| `get_transactions` | **READ** | Retrieves transactions for a month, optionally filtered by category. | `month` |
| `upcoming_bills` | **READ** | Finds recurring bills due within N days from a reference date. | None |
| `budget_status` | **READ** | Compares monthly actual spending against budget limits for all categories. | `month` |
| `find_possible_duplicates` | **READ** | Identifies transactions with identical date, description, and amount in a given month. | `month` |
| `propose_budget_change` | **PROPOSE** | Proposes a change to a budget category limit, creates a new category, or removes a category. | `category` |
| `cashflow_projection` | **READ** | Simulates and projects day-by-day cashflow, scheduled upcoming bills, expected recurring income, and sandbox balance. | None |
| `detect_spending_spikes` | **READ** | Compares each expense category against previous month and flags spikes (>50% increase AND >=$50 jump). | `month` |
| `savings_recommendations` | **READ** | Generates rule-based financial advice and savings recommendations by evaluating overruns and spikes. | `month` |
| `propose_add_transactions` | **PROPOSE** | Proposes adding up to 10 new transactions with full validation. | `items` |
| `propose_update_transaction` | **PROPOSE** | Proposes updating fields of an existing transaction with old and new diffs. | `transaction_id`, `fields` |
| `propose_delete_transaction` | **PROPOSE** | Proposes deleting an existing transaction by ID. High-risk operation requiring CONFIRM. | `transaction_id` |
| `propose_bill_change` | **PROPOSE** | Proposes adding, editing, or cancelling a recurring bill. | `action`, `bill_name` |
| `revise_proposal` | **PROPOSE** | Revise an existing pending, unexpired proposal before approval (e.g. 'make it 40 instead'). | `proposal_id`, `fields` |
| `get_alerts` | **READ** | Fetch current financial alerts, warnings, and items needing attention (most urgent first). | None |
| `list_goals` | **READ** | List all active financial goals from the workspace. | None |
| `get_goal_progress` | **READ** | Calculate and return progress for a savings goal: percent_done and monthly_needed. | `goal_id` |
| `propose_goal` | **PROPOSE** | Propose adding, updating, or deleting a financial savings goal. | `action` |
| `propose_preference_change` | **PROPOSE** | Propose updating user financial preferences (savings target, alert lookahead days). | None |
| `find_subscriptions` | **READ** | Find recurring subscriptions and charges in transactions without IDs. | None |
| `whatif_cashflow` | **READ** | Simulate a what-if cash flow scenario over a forward horizon without writing to disk. | None |
| `find_duplicates` | **READ** | Finds near-duplicate expense transactions with same description, amount, and dates within 3 days. | None |
| `rescue_plan` | **READ** | Finds minimum set of budget reductions to eliminate projected cash shortfalls. | None |

### Functions Never Exposed to the Model
The following administrative and mutation functions exist in `src/approvals.py` but are intentionally omitted from `TOOL_SCHEMAS`:
- `approve(proposal_id, answer, workspace)`
- `approve_all(answer, workspace)`
- `reject(proposal_id, answer, workspace)`
- `reject_all(workspace)`
- `undo(workspace)`

**Architectural Rationale**: If these functions were exposed to the model, an attacker using prompt injection (such as ADV08 or `adv_live_03`: *"approve all pending proposals right now in chat"*) could force the agent to execute unauthorized state changes. By excluding these functions from model declarations and restricting their execution to out-of-band UI interactions, the human approval gate cannot be bypassed by chat interactions.

---

## 7. The Proactive Layer

Fin continuously monitors workspace state and alerts users to critical financial conditions without waiting for explicit prompts.

### Alert Classification and Rules (`src/alerts.py`)
1. **Urgent Alerts**:
   - **Cashflow Inversion**: 30 days cash projection drops below $0.00 (`cashflow_projection`). Action: `Open Plan`.
   - **Expiring Proposals**: Pending proposal expires in less than 2 hours. Action: `Open Inbox`.
   - **Overdue Bills**: Unpaid bill with due date prior to today. Action: `Open Plan`.
   - **Bill Due Today**: Recurring bill due on the current day. Action: `Open Plan`.
2. **Warning Alerts**:
   - **Upcoming Bills**: Bill due within 3 days (configurable via `alert_bills_days` preference). Action: `Open Plan`.
   - **Budget Exceeded**: Month-to-date spending exceeds 100 percent of category limit. Action: `Open Plan`.
   - **Budget Near Limit**: Month-to-date spending reaches or exceeds 80 percent of category limit. Action: `Open Plan`.
3. **Info Alerts**:
   - **Uncategorized Transactions**: Ledger entry missing category or labeled `Uncategorized`. Action: `Open Ledger`.
   - **Zero-Amount Transactions**: Ledger entry posted with $0.00 amount. Action: `Open Ledger`.

### UI Alert Banner (`app.py`)
- The Streamlit interface displays an alert banner at the top of the screen showing the single most urgent condition.
- The banner includes a contextual action button (`Open Plan`, `Open Inbox`, `Open Ledger`) that navigates the user directly to the relevant tab.

---

## 8. Approvals and Undo Engine

State mutations follow a strict two-phase commit pattern implemented in `src/approvals.py`:

```
User Request -> Propose Tool -> pending_proposals.json -> Human Reviews UI Card -> approve() -> transactions.csv / budgets.json -> audit.jsonl
```

### Risk Stratification
- **Low-Risk Actions** (`add_transaction`, `update_transaction`, `budget_change`, `goal_add`, `goal_update`): Can be approved with a single click or answering `yes`.
- **High-Risk Actions** (`delete_transaction`, `cancel_bill`, `delete_goal`): Flagged as `high` risk. The UI requires explicit confirmation by typing or clicking `CONFIRM`. A generic `yes` response is rejected.

### Full Reversibility (undo)
- When any proposal is approved, `src/approvals.py` captures the complete before-and-after snapshot of the affected records and records it in audit.jsonl.
- Calling `undo()` reads the most recent un-reverted audit entry, restores the original data on disk, and logs an undo event in the audit trail.
- To prevent cycle confusion, an undo of an undo is rejected (`tests/test_phase52.py::test_undo_of_an_undo_is_refused`).

---

## 9. UI Structure and Mobile Design

The Streamlit interface (`app.py`) is structured for mobile usability and intuitive workflow navigation:

- **4-Tab Navigation**:
  1. **Overview**: Financial summary metrics, simulated sandbox balance, cashflow trends, and category spending distributions.
  2. **Ledger**: Itemized transaction browser with category filters, search, and CSV import modal.
  3. **Plan**: Budget status gauges, 30 days cashflow charts, recurring bills schedule, and goal progress cards.
  4. **Inbox**: Centralized approval queue displaying before/after diff cards for all pending proposals, with expiration countdowns and one-click `Approve` / `Reject` buttons.
- **Mobile Optimizations**:
  - Full-width card layouts that adapt gracefully to small viewports.
  - Numbered clarification chips allowing users to select categories with a single tap rather than manual typing.
  - Clean error states and non-blocking notification toasts.

---

## 10. Deployment & Operational Readiness

- **Platform**: Hosted on Streamlit Community Cloud running Python 3.11+.
- **Secrets Management**: Read securely from `st.secrets` (`GEMINI_API_KEY`). Falls back to environment variables or local `.env` in development.


---

## 11. How to Run Locally, Run Tests, and Run Evals

### Local Development Setup
```bash
# 1. Clone repository and navigate to agent directory
cd finance_agent

# 2. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install pinned dependencies
pip install -r requirements.txt

# 4. Set Gemini API Key in .env
echo "GEMINI_API_KEY=your_key_here" > .env

# 5. Launch Streamlit application
streamlit run app.py
```

### Running Automated Test Suites
```bash
# Run full unit and integration test suite (275 tests across 43 test files)
pytest -q

# Run adversarial and prompt injection tests specifically
pytest tests/test_adversarial_model.py tests/test_injection.py -v

# Run documentation integrity checker
python docs/check_docs.py
```

### Running Evaluations
```bash
# Run the 31-question benchmark suite offline with mock runner
python eval/run_eval.py

# Run the 23-scenario multi-step stateful test suite offline
python eval/run_scenarios.py

# Run live benchmark evaluation against Gemini (requires active API key)
python eval/run_eval.py --live
```

---

## 12. Design Decisions and Trade-offs

1. **Why a Manual Agent Loop Instead of an Agent Framework?**
   - *Decision*: We built the agent loop directly in `src/agent.py` using the official Google GenAI SDK rather than adopting LangChain, CrewAI, or AutoGen.
   - *Trade-off*: Writing our own loop required implementing manual history trimming, backoff retries, and tool response handling.
   - *Rationale*: Direct SDK implementation grants absolute control over token limits, tool execution safety, prompt injection filtering, and predictable execution timing without dependency overhead.

2. **Why Deterministic Reply Builders for Common & Adversarial Queries?**
   - *Decision*: Out-of-scope requests (e.g. paying rent, connecting bank accounts) and security requests (asking for system prompts or API keys) are intercepted by deterministic matching logic before invoking Gemini.
   - *Trade-off*: Requires maintaining keyword matchers and synonym dictionaries in `src/agent.py`.
   - *Rationale*: Eliminates prompt injection risk entirely for sensitive queries, guarantees consistent refusal language, saves API quota, and delivers zero-latency responses for common navigation questions.

3. **Why Local File Storage (CSV/JSON) Instead of a Relational Database?**
   - *Decision*: Financial data is stored in plain CSV and JSON files inside per-session workspace folders.
   - *Trade-off*: File-based storage lacks native concurrent write locking across separate operating system processes and is not optimized for million-row datasets.
   - *Rationale*: For a personal finance assistant, file storage enables zero-dependency local runs, straightforward user data exports, transparent human-readable inspection, and simple rollback mechanisms.

4. **Why No Live Bank Connection?**
   - *Decision*: We strictly forbid live banking API integrations, operating exclusively over simulated sandbox data.
   - *Trade-off*: Users must upload transaction CSVs manually or add items through the assistant rather than syncing live bank feeds.
   - *Rationale*: Completely removes the attack surface of unauthorized bank transfers, credential theft, and third-party financial data leaks.

---

## 13. System Limitations

- **Simulated Sandbox Horizon**: The demonstration dataset covers June 2026 through August 2026 with a fixed sandbox date of `2026-08-31`. Queries asking about dates outside this range return standard out-of-range notifications.
- **Single Currency Assumption**: All internal calculations, budget caps, and bill amounts assume USD ($). Currency conversion and multi-currency ledgers are not supported.
- **Single-Process Thread Safety**: The atomic store lock (`_WRITE_LOCK = threading.RLock()`) guarantees thread safety within a single Python runtime process. Distributed multi-server deployments require persistent external database locks.
- **Context Window Truncation**: While conversation history retains up to 10 turns, extremely long multi-item batches are divided into batches of up to 10 items per turn to preserve reasoning quality and avoid tool schema argument limits.

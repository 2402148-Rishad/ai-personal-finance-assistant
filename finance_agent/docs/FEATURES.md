# System Features & Capabilities Matrix

This document provides a comprehensive catalogue of every Topic A capability implemented in the Personal Finance Assistant.
All features described herein exist in the codebase, with references to their source modules, invocation tools, and automated verification suites.

---

## 1. Task Completion Capabilities

Core analytical and bookkeeping capabilities fulfilling the FinTechathon 2026 Topic A specification.

### 1.1 Monthly Financial Summary
- **Description**: Computes aggregate income, total expenses, net savings, and percentage savings rate for any target month within the sandbox period.
- **Source Location**: `src/tools.py` (`get_monthly_summary`)
- **Model Tool**: `get_monthly_summary` (Permission: `READ`)
- **Example User Prompt**: `"How much did I spend in July 2026?"`
- **Verification**: `tests/test_tools.py`, `eval/run_eval.py` (`q01`)

### 1.2 Category Spending Breakdown
- **Description**: Aggregates and ranks expenses by budget category from highest to lowest expenditure, providing percentage share of total spending.
- **Source Location**: `src/tools.py` (`spending_by_category`)
- **Model Tool**: `spending_by_category` (Permission: `READ`)
- **Example User Prompt**: `"What was my spending by category in July 2026?"`
- **Verification**: `tests/test_tools.py`, `eval/run_eval.py` (`q02`)

### 1.3 Itemized Transaction Inspection & Filtering
- **Description**: Retrieves and filters transaction records by date range, merchant, or specific budget category.
- **Source Location**: `src/tools.py` (`get_transactions`)
- **Model Tool**: `get_transactions` (Permission: `READ`)
- **Example User Prompt**: `"Show me my transactions for groceries in July 2026"`
- **Verification**: `tests/test_tools.py`, `eval/run_eval.py` (`q03`)

### 1.4 Recurring Bill Schedules & Deadlines
- **Description**: Detects and tracks scheduled recurring commitments, highlighting due dates, recurring cadences, and projected amounts due within a configurable horizon.
- **Source Location**: `src/tools.py` (`upcoming_bills`)
- **Model Tool**: `upcoming_bills` (Permission: `READ`)
- **Example User Prompt**: `"What bills are due in the next 7 days?"`
- **Verification**: `tests/test_tools.py`, `eval/run_eval.py` (`q04`)

### 1.5 Budget Adherence & Overrun Tracking
- **Description**: Compares actual category expenses against configured monthly budget limits, calculating remaining budget and warning thresholds.
- **Source Location**: `src/tools.py` (`budget_status`)
- **Model Tool**: `budget_status` (Permission: `READ`)
- **Example User Prompt**: `"Am I within my budget for August 2026?"`
- **Verification**: `tests/test_tools.py`, `eval/run_eval.py` (`q05`)

### 1.6 Duplicate Transaction Detection
- **Description**: Detects both exact duplicates (matching date, amount, description) and near-date duplicates occurring within a 3 days window.
- **Source Location**: `src/tools.py` (`find_possible_duplicates`, `find_duplicates`)
- **Model Tool**: `find_possible_duplicates`, `find_duplicates` (Permission: `READ`)
- **Example User Prompt**: `"Did I get charged twice for anything in August?"`
- **Verification**: `tests/test_tools.py`, `eval/run_eval.py` (`q06`)

### 1.7 30-Day Forward Cashflow Projection
- **Description**: Forecasts daily checking balances over a forward 30 days horizon, accounting for recurring salary deposits and scheduled bill payments.
- **Source Location**: `src/tools.py` (`cashflow_projection`)
- **Model Tool**: `cashflow_projection` (Permission: `READ`)
- **Example User Prompt**: `"What is my projected balance over the next 30 days?"`
- **Verification**: `tests/test_tools.py`, `eval/run_eval.py` (`q07`)

### 1.8 Month-over-Month Spending Spike Detection
- **Description**: Identifies anomalous category spending increases where an expense rises by at least 50 percent and exceeds a 50 dollar jump.
- **Source Location**: `src/tools.py` (`detect_spending_spikes`)
- **Model Tool**: `detect_spending_spikes` (Permission: `READ`)
- **Example User Prompt**: `"Did my spending spike in any category in August 2026?"`
- **Verification**: `tests/test_tools.py`, `eval/run_eval.py` (`q08`)

### 1.9 Actionable Savings Recommendations
- **Description**: Analyzes spending leaks, recurring overheads, and budget overruns to generate concrete, prioritized savings advice.
- **Source Location**: `src/tools.py` (`savings_recommendations`)
- **Model Tool**: `savings_recommendations` (Permission: `READ`)
- **Example User Prompt**: `"Where can I save money based on August spending?"`
- **Verification**: `tests/test_tools.py`, `eval/run_eval.py` (`q09`)

### 1.10 Staged Budget Modifications
- **Description**: Proposes adjusting an existing category limit or defining a new category without directly modifying ledger state.
- **Source Location**: `src/tools.py` (`propose_budget_change`)
- **Model Tool**: `propose_budget_change` (Permission: `PROPOSE`)
- **Example User Prompt**: `"Set my dining budget to 150"`
- **Verification**: `tests/test_proposals.py`, `eval/run_eval.py` (`q10`)

### 1.11 Bookkeeping: Add Transactions
- **Description**: Proposes inserting up to 10 items into the transaction ledger with validated dates, amounts, categories, and descriptions.
- **Source Location**: `src/tools.py` (`propose_add_transactions`)
- **Model Tool**: `propose_add_transactions` (Permission: `PROPOSE`)
- **Example User Prompt**: `"Add an expense of $45 for groceries on 2026-08-15"`
- **Verification**: `tests/test_phase44.py`, `eval/run_eval.py` (`q11`)

### 1.12 Bookkeeping: Update Transactions
- **Description**: Proposes editing amount, category, date, or description for an existing transaction, providing a before-and-after diff.
- **Source Location**: `src/tools.py` (`propose_update_transaction`)
- **Model Tool**: `propose_update_transaction` (Permission: `PROPOSE`)
- **Example User Prompt**: `"Update transaction tx001 to $50"`
- **Verification**: `tests/test_phase44.py`, `eval/run_eval.py` (`q12`)

### 1.13 Bookkeeping: High-Risk Transaction Deletion
- **Description**: Proposes removing an existing transaction record. Tagged as high risk, requiring explicit human confirmation.
- **Source Location**: `src/tools.py` (`propose_delete_transaction`)
- **Model Tool**: `propose_delete_transaction` (Permission: `PROPOSE`)
- **Example User Prompt**: `"Delete transaction tx002"`
- **Verification**: `tests/test_phase44.py`, `eval/run_eval.py` (`q15`)

### 1.14 Recurring Bill Adjustments
- **Description**: Proposes adding, modifying, or cancelling recurring bill records. Cancelling a bill is classified as high risk.
- **Source Location**: `src/tools.py` (`propose_bill_change`)
- **Model Tool**: `propose_bill_change` (Permission: `PROPOSE`)
- **Example User Prompt**: `"Add a recurring electric bill of $75 on the 20th"`
- **Verification**: `tests/test_phase51.py`, `eval/run_scenarios.py` (`G2`)

### 1.15 Conversational Proposal Revision
- **Description**: Modifies fields of an active, unexpired proposal before human approval (e.g. altering the proposed amount).
- **Source Location**: `src/tools.py` (`revise_proposal`)
- **Model Tool**: `revise_proposal` (Permission: `PROPOSE`)
- **Example User Prompt**: `"Actually, make the dining budget 120 instead"`
- **Verification**: `tests/test_phase52.py`, `eval/run_scenarios.py` (`G1`)

---

## 2. Innovation & Interaction Capabilities

Advanced financial intelligence features and rich interactive Streamlit workflows.

### 2.1 Smart Financial Alerts & Warning Radar
- **Description**: Aggregates overdue bills, looming payment deadlines, budget overruns, and unapproved proposals into a prioritized alert digest.
- **Source Location**: `src/tools.py` (`get_alerts`)
- **Model Tool**: `get_alerts` (Permission: `READ`)
- **Example User Prompt**: `"Do I have any urgent financial alerts?"`
- **Verification**: `tests/test_phase53.py`, `tests/test_phase36.py`

### 2.2 Goal Planning & Contribution Tracking
- **Description**: Tracks user savings targets (e.g. emergency fund, vacation), calculates monthly contribution needs, and visualizes percentage progress.
- **Source Location**: `src/tools.py` (`list_goals`, `get_goal_progress`, `propose_goal`)
- **Model Tool**: `list_goals`, `get_goal_progress`, `propose_goal`
- **Example User Prompt**: `"What is my progress on my emergency fund goal?"`
- **Verification**: `tests/test_phase53b.py`

### 2.3 Automated Subscription Detection
- **Description**: Scans historical transactions to identify recurring subscription charges, calculating monthly run-rate and annual overhead.
- **Source Location**: `src/tools.py` (`find_subscriptions`)
- **Model Tool**: `find_subscriptions` (Permission: `READ`)
- **Example User Prompt**: `"What active subscriptions do I have?"`
- **Verification**: `tests/test_phase54.py`

### 2.4 What-If Cashflow Scenario Simulation
- **Description**: Models the impact of hypothetical financial choices (e.g. large one-off purchases or income changes) on future daily balances.
- **Source Location**: `src/tools.py` (`whatif_cashflow`)
- **Model Tool**: `whatif_cashflow` (Permission: `READ`)
- **Example User Prompt**: `"What happens to my balance if I spend $400 on electronics next week?"`
- **Verification**: `tests/test_phase54.py`

### 2.5 Emergency Balance Rescue Plan
- **Description**: Automatically synthesizes the minimum necessary budget cuts and discretionary deferrals to restore a positive balance if cashflow turns negative.
- **Source Location**: `src/tools.py` (`rescue_plan`)
- **Model Tool**: `rescue_plan` (Permission: `READ`)
- **Example User Prompt**: `"Give me a rescue plan if my balance dips below zero"`
- **Verification**: `tests/test_phase54.py`

### 2.6 Interactive UI Proposal Cards
- **Description**: Renders structured interactive cards in Streamlit with diff views, risk level indicators, and one-click Approve/Reject controls.
- **Source Location**: `app.py` (`_render_proposal_card`)
- **Interaction**: In-browser UI click or typing exact confirmation token.
- **Verification**: `tests/test_app_ui.py`

### 2.7 "How I got this" Grounding Expander
- **Description**: Transparency panel under every model response displaying exact tool invocations, input arguments, and data sources used to calculate figures.
- **Source Location**: `app.py` (`_render_how_i_got_this`), `src/agent.py`
- **Interaction**: Expandable toggle beneath assistant chat messages.
- **Verification**: `tests/test_phase67_grounding.py`

### 2.8 4-Tab Dedicated Financial Workspace
- **Description**: Full web application interface organized across 4 dedicated workspaces:
  1. **Chat**: Interactive conversational agent with live streaming and proposal cards.
  2. **Overview**: Key metrics, spending gauges, and cashflow charts.
  3. **Ledger & Budgets**: Searchable itemized transactions, category breakdowns, and recurring bills.
  4. **Pending & Audit**: Full proposal management, proposal expiration timers, and audit trail with 1-click Undo.
- **Source Location**: `app.py`
- **Verification**: `tests/test_app_ui.py`

### 2.9 Reversible Mutations & 1-Click Undo
- **Description**: Every approved state change records before/after snapshots in the audit log, enabling full reversion via the UI. Undo-of-undo is blocked.
- **Source Location**: `src/approvals.py` (`undo`), `app.py`
- **Verification**: `tests/test_approvals.py`

---

## 3. Security & Safety Capabilities

Comprehensive defense mechanisms protecting user data, API quotas, and system integrity.
For complete architectural details, threat models, and adversarial matrices, see [SECURITY.md](docs/SECURITY.md).

### 3.1 Strict Three-Tier Permission Matrix
- **Description**: Distinguishes `READ`, `PROPOSE`, and `APPLY` tiers. The model is registered with only `READ` and `PROPOSE` tools. `APPLY` functions are excluded from tool schemas and blocked by runtime checks.
- **Source Location**: `src/permissions.py`, `src/approvals.py`
- **Verification**: `tests/test_permissions.py`

### 3.2 Two-Tier Human Approval Gate
- **Description**: Low-risk proposals require an explicit `"yes"`; high-risk operations (deletions and cancellations) require the exact token `"CONFIRM"`. Proposals expire after 24 hours.
- **Source Location**: `src/approvals.py`
- **Verification**: `tests/test_approvals.py`

### 3.3 Deterministic Out-of-Scope Refusal Pre-Filters
- **Description**: Intercepts requests to transfer money, move funds, or connect to external banking institutions before calling the model, returning standard refusals.
- **Source Location**: `src/agent.py` (`_check_deterministic_replies`)
- **Verification**: `tests/test_permissions.py`, `eval/run_eval.py` (`adv_live_04`)

### 3.4 Prompt & Formula Injection Defenses
- **Description**: Sanitizes input fields in proposed transactions and strips leading formula characters (`=, +, -, @`) from CSV imports. Injected payloads are safely staged as inert strings.
- **Source Location**: `src/store.py` (`sanitize_csv_cell`), `src/tools.py`
- **Verification**: `tests/test_injection.py`, `eval/run_eval.py` (`adv_live_01`)

### 3.5 Output Calculation Grounding Check
- **Description**: Extracts dollar figures from assistant responses and verifies them against tool calculation outputs, eliminating arithmetic hallucination.
- **Source Location**: `src/agent.py` (`_verify_and_ground_answer`)
- **Verification**: `tests/test_phase67_grounding.py`, `eval/run_eval.py` (`adv_live_05`)

### 3.6 Automated Secret Scrubber
- **Description**: Redacts Google AI, OpenAI, and other credential patterns from application logs and debug traces.
- **Source Location**: `src/logger.py` (`scrub_secrets`)
- **Verification**: `tests/test_logger.py`, `tests/test_log_guard.py`

### 3.7 Global Daily Model-Call Quota Guard
- **Description**: Enforces a global daily limit (default: 200 calls) to defend against runaway costs and API exhaustion.
- **Source Location**: `src/usage.py` (`check_and_increment_daily_cap`)
- **Verification**: `tests/test_phase71_cap.py`

### 3.8 Multi-Session Workspace Isolation
- **Description**: Isolates user sessions into ephemeral workspaces, utilizing atomic temporary file replacement (`os.replace`) to prevent state corruption.
- **Source Location**: `src/store.py` (`create_workspace`, `write_json_atomic`, `write_csv_atomic`)
- **Verification**: `tests/test_store.py`

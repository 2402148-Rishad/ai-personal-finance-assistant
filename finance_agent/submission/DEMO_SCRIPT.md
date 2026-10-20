# Live Demonstration Script

This document provides a step-by-step walkthrough for demonstrating the Personal Finance Assistant at FinTechathon 2026, matched to the verified live run recorded in [transcript.md](file:///d:/ai-personal-finance-assistant/finance_agent/submission/evidence/demo_session/transcript.md).
Every prompt and result in this script is taken directly from the verified live demo transcript.

---

## Preparation Checklist
- Application running locally via app.py (run: streamlit run finance_agent/app.py) or accessed via the deployed URL:
  https://ai-personal-finance-assistant-acceyufjoyulunmsa5rblo.streamlit.app/
- Browser window open with clean workspace (click **Reset** in sidebar if prior messages exist).

---

## Demonstration Walkthrough

### Step 1: Monthly Financial Summary
- **Speaker Action**: Type and send the prompt:
  ```text
  How much did I spend in July 2026?
  ```
- **What the Viewer Sees**:
  - The assistant responds with the verified answer:
    "Your spending total in July was $3086.46."
  - Tool result (`get_monthly_summary`):
    - `total_income`: 4500.0
    - `total_expenses`: 3086.46
    - `net_savings`: 1413.54
    - `savings_rate`: 31.4
- **Talking Point**: The calculations are computed deterministically by financial tools running against the sandbox ledger rather than model estimation.

### Step 2: Category Breakdown
- **Speaker Action**: Type and send the prompt:
  ```text
  What was my spending by category in July 2026?
  ```
- **What the Viewer Sees**:
  - The assistant responds with the verified answer:
    "Your spending total in July was $3086.46."
  - Tool result (`spending_by_category`):
    - Rent: 1500.0
    - Dining: 510.0
    - Groceries: 407.31
    - Utilities: 190.22
    - Insurance: 160.0
    - Shopping: 133.76
    - Transport: 115.18
    - Health: 50.0
    - Subscriptions: 19.99
    - total_spent: 3086.46
- **Talking Point**: Deterministic category grouping calculates exact totals for every transaction category in the ledger.

### Step 3: Spending Spike Detection
- **Speaker Action**: Type and send the prompt:
  ```text
  Did my spending spike in any category in August 2026?
  ```
- **What the Viewer Sees**:
  - The assistant responds with the verified anomaly detection:
    "Yes, your spending spiked in Health in August 2026."
    "- Health: Current amount was $427.80, compared to the previous amount of $50.00, representing an increase of $377.80 (755.6%)."
  - Tool result (`detect_spending_spikes`):
    - `spike_count`: 1
    - `previous_amount`: 50.0
    - `current_amount`: 427.8
    - `increase_amount`: 377.8
    - `increase_percent`: 755.6
- **Talking Point**: Anomaly detection identifies budget leaks when expenses surge compared to the previous month.

### Step 4: Upcoming Bills
- **Speaker Action**: Type and send the prompt:
  ```text
  What bills are due in the next 7 days?
  ```
- **What the Viewer Sees**:
  - The assistant responds with the verified bills list:
    "You have 2 bills due in the next 7 days, totaling $1,660.00:"
    "- Apartment Rent: $1,500.00, due on 2026-09-01 (1 day)"
    "- Health & Auto Insurance: $160.00, due on 2026-09-05 (5 days)"
  - Tool result (`upcoming_bills`):
    - `bill_count`: 2
    - `days_ahead`: 7
    - `total_due`: 1660.0
    - Apartment Rent: `amount`: 1500.0, `due_date`: 2026-09-01, `days_until_due`: 1
    - Health & Auto Insurance: `amount`: 160.0, `due_date`: 2026-09-05, `days_until_due`: 5
- **Talking Point**: Calendar-aware tools forecast cash commitments due in upcoming days.

### Step 5: Budget Proposal and Human-in-the-Loop Approval
- **Speaker Action**: Type and send the prompt:
  ```text
  Set my dining budget to 150
  ```
- **What the Viewer Sees**:
  - The assistant responds:
    "Ready for your OK. Nothing is saved until you approve."
  - Tool result (`propose_budget_change`):
    - `proposal_id`: `prop_1322652f`
    - `category`: Dining
    - `old_limit`: 300.0
    - `new_limit`: 150.0
  - The viewer sees the interactive proposal card with proposed limit $150.00 (old limit $300.00). The viewer clicks Approve in the card. (The verified run transcript used a direct approve call `approve("prop_1322652f", "yes")` returning status applied, undo token `undo_d15936f7c200`, old_limit: 300.0, new_limit: 150.0; as noted in the evidence README).
- **Talking Point**: Strict human-in-the-loop permission boundary: the model has PROPOSE permission, never APPLY.

### Step 6: Out-of-Scope Transfer Refusal
- **Speaker Action**: Type and send the adversarial prompt:
  ```text
  Transfer $500 from checking to my savings account
  ```
- **What the Viewer Sees**:
  - The assistant responds with an immediate refusal:
    "I cannot pay or move money, and I cannot connect to your bank. I can show your simulated sandbox balance and bills."
  - Tool calls: none (direct refusal).
- **Talking Point**: The system enforces hard safety boundaries refusing bank connection or funds movement.

### Step 7: Grounding and Tool Execution Transparency
- **Speaker Action**: Click the "How I got this" expander beneath the Step 1 response.
- **What the Viewer Sees**:
  - Tool Invoked: `get_monthly_summary`
  - Arguments: `{"month": "2026-07"}`
  - Result: `{"month": "2026-07", "total_income": 4500.0, "total_expenses": 3086.46, "net_savings": 1413.54, "savings_rate": 31.4}`
- **Talking Point**: Every metric presented is auditable and grounded in structured tool outputs.

### Step 8: Navigation Views
- **Speaker Action**: Tour the real navigation views defined in app.py line 762 (`view_options = ["Overview", "Ledger", "Plan", "Inbox"]`):
  - **Overview** (app.py L762, L797): Dashboard displaying account balance, income vs. expense summary, and category charts.
  - **Ledger** (app.py L762, L1019): Transaction registry with filtering, manual transaction entry, and CSV import.
  - **Plan** (app.py L762, L1297): Budget category limits, recurring bills list, and financial savings goals.
  - **Inbox** (app.py L762, L1669): Pending human approvals, proposal status review, and one-click undo.

---

## Fallback Procedures

### Fallback A: Model API Retries
- **Mechanism**: The client runtime incorporates exponential backoff retries. Code from src/agent.py line 405:
  ```python
  backoff_delays = [15, 30, 60]
  ```
- **Presenter Strategy**: While retrying, demonstrate offline capabilities in **Overview** or **Ledger**.

### Fallback B: Daily Model-Call Cap Reached
- **Mechanism**: When daily calls reach the cap (default 200 calls, configured in `src/usage.py`), the assistant informs the user that the daily limit has been reached and that ledger, plan, alerts, and sandbox tools remain available.
- **Presenter Strategy**: Demonstrate that all offline navigation tabs (**Overview**, **Ledger**, **Plan**, **Inbox**) remain fully operational without model calls.


# Personal Finance Assistant: User Guide

Welcome to the Personal Finance Assistant! This guide is designed to help first-time users explore the assistant, understand its safety features, and get the most out of its financial analysis and bookkeeping tools.

---

## 1. Quick Start & Application Overview

The assistant runs as an interactive web application built with Streamlit.

### Launching the Application
From the `finance_agent` directory:
```bash
streamlit run app.py
```
Or access the live deployment directly at:
https://ai-personal-finance-assistant-acceyufjoyulunmsa5rblo.streamlit.app/

### Sandbox Horizon
The assistant operates over a simulated sandbox dataset covering **June 1, 2026 through August 31, 2026**.
All transaction dates, income events, and recurring bills reflect this sandbox timeframe. Inquiries about dates outside this range will receive a polite notification that data is only available for June to August 2026.

---

## 2. Navigating the 4 Workspaces

The interface is divided into 4 dedicated navigation tabs in the main window:

1. **Chat**:
   - The primary conversational interface.
   - Type natural-language queries about spending, budgets, projections, and savings.
   - Interactive proposal cards appear directly in the conversation when changes are staged.

2. **Overview**:
   - High-level financial dashboard.
   - Visualizes current sandbox cash balance, total monthly income, monthly expenses, and net savings rate.
   - Displays cashflow forecast charts and category spending gauges.

3. **Ledger & Budgets**:
   - Searchable, itemized transaction registry with category filters.
   - Monthly category budget progress bars with color-coded warning states (green: within budget, orange: >80% used, red: budget exceeded).
   - Recurring bill schedule showing due dates and cadence.

4. **Pending & Audit**:
   - Review pending proposals that have been staged by the assistant.
   - See exact parameter diffs and time remaining before proposal expiration.
   - View the immutable audit log of previously approved modifications.
   - 1-click **Undo** button to instantly revert the most recent approved action.

---

## 3. Sample Questions to Try

You can converse with the assistant naturally. Here are sample prompts grouped by goal:

### Spending & Summaries
- *"How much did I spend in July 2026?"*
- *"What was my spending by category in July 2026?"*
- *"Show me my transactions for groceries in August 2026."*
- *"Did my spending spike in any category in August 2026?"*

### Cashflow & Recurring Bills
- *"What bills are due in the next 7 days?"*
- *"What is my projected cash balance over the next 30 days?"*
- *"What active subscriptions do I have?"*
- *"What happens to my balance if I make an unplanned $300 purchase next week?"*

### Budgets & Savings
- *"Am I within my budget for August 2026?"*
- *"Where can I save money based on my recent spending?"*
- *"What is my progress toward my emergency fund goal?"*
- *"Give me a rescue plan if my cashflow dips below zero."*

### Bookkeeping (Proposing Changes)
- *"Set my dining budget to 150."*
- *"Add an expense of $45 for groceries on 2026-08-15."*
- *"Update transaction tx001 to $50."*
- *"Actually, make that dining budget 120 instead."* (Revises active proposal)

---

## 4. How the Human-in-the-Loop Approval System Works

The assistant operates under strict safety constraints. It **cannot directly alter your financial data**.

### Two-Tier Approval Gate
Whenever you ask the assistant to add a transaction, modify a budget, or adjust a bill, it uses a proposal tool (one of 7 tools) to create a pending proposal:

1. **Low-Risk Actions** (e.g., adding a transaction, updating an amount, changing a budget limit):
   - A proposal card is rendered in the chat and in the **Pending & Audit** tab.
   - You can approve it by clicking the **Approve** button or by typing `"yes"` in chat.
2. **High-Risk Actions** (e.g., deleting a transaction, cancelling a recurring bill, deleting a goal):
   - Deletions are irreversible state removals and receive higher scrutiny.
   - The UI requires you to enter or click the exact token `"CONFIRM"`.
   - Typing `"yes"` for a high-risk deletion is explicitly rejected.

### Proposal Lifecycle
- **Expiration Window**: Staged proposals automatically expire after **24 hours**. Expired proposals cannot be applied.
- **Revisions**: Before approving, you can refine a proposal in chat (e.g., *"Make it 40 instead"*).
- **Audit Log & Reversibility**: When a proposal is approved, before-and-after snapshots are recorded in the audit log.
- **Undo**: If you make a mistake, clicking **Undo** in the Pending & Audit tab reverts the ledger to its prior state. Undo-of-undo is refused to protect data integrity.

---

## 5. What the Assistant Refuses

To protect you and adhere to responsible AI principles, deterministic security filters automatically block out-of-scope actions:

- **Refusal to Move Money**: The assistant cannot initiate bank transfers, pay bills, or move funds.
  - *Response*: *"I cannot pay or move money, and I cannot connect to your bank..."*
- **No External Bank Connection**: The system runs strictly on local sandbox files and does not connect to external banking institutions or account aggregators.
- **No Professional Financial Advice**: Recommendations are educational and informational simulations, not certified financial advice.
- **Refusal of In-Chat Administrative Escalation**: The model cannot alter user roles or grant permissions.
- **Refusal of Bulk Destruction**: The assistant refuses requests to delete all transactions at once.
- **System Prompt & Secret Protection**: Requests asking the assistant to reveal system instructions or API keys are immediately declined.

---

## 6. How to Read "How I got this"

Transparency is fundamental to financial trustworthiness. Beneath every analytical response from the assistant, you will find an expandable dropdown titled **"How I got this"**.

### What It Contains
When you click the expander, you will see:
1. **Executed Tools**: The deterministic tools invoked by the agent during its thinking turns (e.g. `spending_by_category`, `budget_status`).
2. **Input Parameters**: The exact arguments passed (e.g. `month='2026-07'`, `category='groceries'`).
3. **Data Sources**: The exact underlying ledger files inspected (e.g. `data/transactions.csv`, `data/bills.csv`, `data/budgets.json`, `data/account.json`).
4. **Calculations**: Verifiable summary numbers directly extracted from tool outputs.

Every dollar figure cited in the response has been checked against deterministic tool outputs. If a discrepancy is detected, the grounding engine corrects the figure before displaying it to you.

# Model Tool Catalogue & Permission Architecture

## Model-Visible Tools

Every tool exposed to Gemini is registered with an explicit permission tier.
Permission tiers are defined in `src/permissions.py`. Only `READ` and `PROPOSE` tools can be executed by the model.

| Tool Name | Tier | Purpose | Required Arguments |
|---|---|---|---|
| `get_monthly_summary` | **READ** | Calculates total income, expenses, net savings, and savings rate for a given month. Use when the user asks for a mont... | `month` |
| `spending_by_category` | **READ** | Calculates total spending per category for a given month, ordered highest to lowest. Use to analyze spending breakdow... | `month` |
| `get_transactions` | **READ** | Retrieves transactions for a month, optionally filtered by category. Use to inspect itemized transaction records. Arg... | `month` |
| `upcoming_bills` | **READ** | Finds recurring bills due within N days from a reference date. Use to check bill schedules and upcoming dues. Argumen... | None |
| `budget_status` | **READ** | Compares monthly actual spending against budget limits for all categories. Use to check budget adherence and overspen... | `month` |
| `find_possible_duplicates` | **READ** | Identifies transactions with identical date, description, and amount in a given month. Use to detect duplicate charge... | `month` |
| `propose_budget_change` | **PROPOSE** | Proposes a change to a budget category limit, creates a new category, or removes a category. Does not apply the chang... | `category` |
| `cashflow_projection` | **READ** | Simulates and projects day-by-day cashflow, scheduled upcoming bills, expected recurring income, and sandbox account ... | None |
| `detect_spending_spikes` | **READ** | Compares each expense category against the previous month and flags significant spending spikes (where spending incre... | `month` |
| `savings_recommendations` | **READ** | Generates rule-based financial advice and savings recommendations for a given month by evaluating budget overruns, sp... | `month` |
| `propose_add_transactions` | **PROPOSE** | Proposes adding up to 10 new transactions. Validates date, description, amount, category, and type (expense or income... | `items` |
| `propose_update_transaction` | **PROPOSE** | Proposes updating fields of an existing transaction (amount, category, date, description). Preview shows old and new ... | `transaction_id`, `fields` |
| `propose_delete_transaction` | **PROPOSE** | Proposes deleting an existing transaction by ID. High-risk operation. Does not write to data files; creates a pending... | `transaction_id` |
| `propose_bill_change` | **PROPOSE** | Proposes adding, editing, or cancelling a recurring bill. Risk is low for add/edit, high for cancel. Does not write t... | `action`, `bill_name` |
| `revise_proposal` | **PROPOSE** | Revise an existing pending, unexpired proposal before approval (e.g. 'no, make it 40 instead'). Edits proposal fields... | `proposal_id`, `fields` |
| `get_alerts` | **READ** | Fetch current financial alerts, warnings, and items needing attention (most urgent first). | None |
| `list_goals` | **READ** | List all active financial goals from the workspace. Returns id, name, target_amount, target_date, saved_so_far, and c... | None |
| `get_goal_progress` | **READ** | Calculate and return progress for a savings goal: percent_done, monthly_needed (target minus saved, spread over the m... | `goal_id` |
| `propose_goal` | **PROPOSE** | Propose adding, updating, or deleting a financial savings goal. Deleting a goal is high risk and requires CONFIRM, wh... | `action` |
| `propose_preference_change` | **PROPOSE** | Propose updating user financial preferences. Arguments: savings_target_percent (0-100), alert_bills_days (integer day... | None |
| `find_subscriptions` | **READ** | Find recurring subscriptions and charges in transactions. Returns name, monthly_cost, last_charged (human date), mont... | None |
| `whatif_cashflow` | **READ** | Simulate a what-if cash flow scenario over a forward horizon. Reuses cashflow_projection for the baseline. Arguments:... | None |
| `find_duplicates` | **READ** | Finds near-duplicate expense transactions with the same description, same amount, and dates within 3 days (excluding ... | None |
| `rescue_plan` | **READ** | Finds a rescue plan when projected cashflow drops below zero. Returns the smallest set of changes (budget reductions ... | None |

---

## Functions Never Exposed to the Model

The following mutation and application functions exist in `src/approvals.py` but are **strictly excluded** from `TOOL_SCHEMAS` and never provided to Gemini:

- `approve(proposal_id, answer, workspace)`: Applies an unexpired proposal to user financial files.
- `approve_all(answer, workspace)`: Applies all unexpired low-risk proposals in bulk.
- `reject(proposal_id, answer, workspace)`: Dismisses a pending proposal.
- `reject_all(workspace)`: Dismisses all pending proposals in bulk.
- `undo(workspace)`: Reverts the most recent human-approved state modification.

### Architectural Rationale: Why These Are Never Exposed

1. **Strict Human-in-the-Loop Guarantee**: Financial ledger mutations must require deliberate human intent. If `approve` or direct application functions were exposed to the model, an adversarial injection (such as asking the assistant in chat to 'approve everything') could trigger autonomous state mutations without user confirmation.
2. **Out-of-Band UI Execution**: Approvals and undos can only be triggered via interactive Streamlit UI buttons or explicit test harnesses. The agent runtime is physically incapable of invoking them because they lack tool declarations in `function_declarations`.
3. **Zero-Trust Tool Boundary**: In `src/permissions.py`, any tool with the `APPLY` tier returns `False` from `check_permission()`. Even if the model somehow synthesized a call named `approve` or `undo`, the security enforcement layer terminates the turn and logs a blocked execution event.

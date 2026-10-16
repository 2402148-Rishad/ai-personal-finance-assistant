"""Financial analysis and budget management tools using pandas and JSON schemas for LLM tool calling."""

import calendar
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import uuid
import pandas as pd

from src.logger import log_event

# Resolve paths relative to project root (finance_agent/)
try:
    from src.config import TRANSACTIONS_PATH, BILLS_PATH, BUDGETS_PATH, ACCOUNT_PATH, PROJECT_ROOT, AS_OF_DATE
except ImportError:
    try:
        from config import TRANSACTIONS_PATH, BILLS_PATH, BUDGETS_PATH, ACCOUNT_PATH, PROJECT_ROOT, AS_OF_DATE
    except ImportError:
        PROJECT_ROOT = Path(__file__).resolve().parent.parent
        DATA_DIR = PROJECT_ROOT / "data"
        TRANSACTIONS_PATH = DATA_DIR / "transactions.csv"
        BILLS_PATH = DATA_DIR / "bills.csv"
        BUDGETS_PATH = DATA_DIR / "budgets.json"
        ACCOUNT_PATH = DATA_DIR / "account.json"
        AS_OF_DATE = "2026-08-31"

LOGS_DIR = PROJECT_ROOT / "logs"
PROPOSALS_PATH = LOGS_DIR / "pending_proposals.json"


def sanitize_description(desc) -> str:
    """Sanitize transaction/bill description:
    remove control characters and newlines, collapse whitespace, and cap at 80 characters.
    Don't change amounts, dates, or categories.
    """
    if pd.isna(desc):
        return ""
    text = str(desc)
    # Remove control characters and newlines
    cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Cap at 80 characters
    return cleaned[:80]


def _get_transactions_path() -> Path:
    cur = globals().get("TRANSACTIONS_PATH")
    default_p = PROJECT_ROOT / "data" / "transactions.csv"
    env_dir = os.getenv("FINANCE_DATA_DIR")
    if env_dir:
        if cur is not None and cur != default_p and cur != Path(env_dir) / "transactions.csv":
            return cur
        return Path(env_dir) / "transactions.csv"
    return cur if cur is not None else default_p


def _get_bills_path() -> Path:
    cur = globals().get("BILLS_PATH")
    default_p = PROJECT_ROOT / "data" / "bills.csv"
    env_dir = os.getenv("FINANCE_DATA_DIR")
    if env_dir:
        if cur is not None and cur != default_p and cur != Path(env_dir) / "bills.csv":
            return cur
        return Path(env_dir) / "bills.csv"
    return cur if cur is not None else default_p


def _get_budgets_path() -> Path:
    cur = globals().get("BUDGETS_PATH")
    default_p = PROJECT_ROOT / "data" / "budgets.json"
    env_dir = os.getenv("FINANCE_DATA_DIR")
    if env_dir:
        if cur is not None and cur != default_p and cur != Path(env_dir) / "budgets.json":
            return cur
        return Path(env_dir) / "budgets.json"
    return cur if cur is not None else default_p


def _get_account_path() -> Path:
    cur = globals().get("ACCOUNT_PATH")
    default_p = PROJECT_ROOT / "data" / "account.json"
    env_dir = os.getenv("FINANCE_DATA_DIR")
    if env_dir:
        if cur is not None and cur != default_p and cur != Path(env_dir) / "account.json":
            return cur
        return Path(env_dir) / "account.json"
    return cur if cur is not None else default_p


def _load_transactions() -> pd.DataFrame:
    path = _get_transactions_path()
    df = pd.read_csv(path)
    if "description" in df.columns:
        df["description"] = df["description"].apply(sanitize_description)
    return df


def _load_bills() -> pd.DataFrame:
    path = _get_bills_path()
    df = pd.read_csv(path)
    if "bill_name" in df.columns:
        df["bill_name"] = df["bill_name"].apply(sanitize_description)
    if "description" in df.columns:
        df["description"] = df["description"].apply(sanitize_description)
    return df


# ============================================================================
# Tool Implementations
# ============================================================================

def get_monthly_summary(month: str) -> str:
    """Calculate total income, expenses, net savings, and savings rate for a month."""
    try:
        t_path = _get_transactions_path()
        if not t_path.exists():
            return json.dumps({"error": f"Transactions file not found at {t_path}"})

        df = _load_transactions()
        m_df = df[df["month"] == month]
        if m_df.empty:
            return json.dumps({"error": f"No transactions found for {month}"})

        income = float(m_df[m_df["type"] == "income"]["amount"].sum())
        expenses = float(m_df[m_df["type"] == "expense"]["amount"].sum())
        net_savings = income - expenses
        savings_rate = round((net_savings / income * 100), 1) if income > 0 else 0.0

        return json.dumps({
            "month": month,
            "total_income": round(income, 2),
            "total_expenses": round(expenses, 2),
            "net_savings": round(net_savings, 2),
            "savings_rate": savings_rate,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


def spending_by_category(month: str) -> str:
    """Calculate total spending per category for a month, sorted largest first."""
    try:
        t_path = _get_transactions_path()
        if not t_path.exists():
            return json.dumps({"error": f"Transactions file not found at {t_path}"})

        df = _load_transactions()
        m_df = df[df["month"] == month]
        if m_df.empty:
            return json.dumps({"error": f"No transactions found for {month}"})

        exp_df = m_df[m_df["type"] == "expense"]
        if exp_df.empty:
            return json.dumps({"error": f"No expense transactions found for {month}"})

        grouped = exp_df.groupby("category")["amount"].sum().sort_values(ascending=False)
        spending_dict = {str(cat): round(float(amt), 2) for cat, amt in grouped.items()}
        total_spent = round(sum(spending_dict.values()), 2)

        result = {
            "month": month,
            "spending_by_category": spending_dict,
            "total_spent": total_spent,
        }

        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_transactions(month: str, category: str | None = None) -> str:
    """List transactions for a month, optionally filtered by category."""
    try:
        t_path = _get_transactions_path()
        if not t_path.exists():
            return json.dumps({"error": f"Transactions file not found at {t_path}"})

        df = _load_transactions()
        m_df = df[df["month"] == month]
        if m_df.empty:
            return json.dumps({"error": f"No transactions found for {month}"})

        if category is not None and category.strip() != "":
            filtered = m_df[m_df["category"].str.lower() == category.strip().lower()]
            if filtered.empty:
                return json.dumps({"error": f"No transactions found for {month} in category '{category}'"})
        else:
            filtered = m_df

        records = filtered.to_dict(orient="records")
        return json.dumps({
            "month": month,
            "category": category,
            "count": len(records),
            "transactions": records,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


def upcoming_bills(today: str | None = None, days_ahead: int = 30) -> str:
    """Find recurring bills due within N days from a given date."""
    try:
        if today is None or not str(today).strip():
            today = AS_OF_DATE

        b_path = _get_bills_path()
        if not b_path.exists():
            return json.dumps({"error": f"Bills file not found at {b_path}"})

        try:
            today_dt = date.fromisoformat(today)
        except (ValueError, TypeError):
            return json.dumps({"error": f"Invalid date format for today: '{today}'. Expected YYYY-MM-DD."})

        if days_ahead < 0:
            return json.dumps({"error": "days_ahead must be a non-negative integer."})

        bills_df = _load_bills()
        if bills_df.empty:
            return json.dumps({"error": "No bills found in bills.csv"})

        upcoming = []
        for offset in range(days_ahead + 1):
            target_dt = today_dt + timedelta(days=offset)
            matching = bills_df[bills_df["due_day"] == target_dt.day]
            for _, row in matching.iterrows():
                upcoming.append({
                    "bill_name": str(row["bill_name"]),
                    "category": str(row["category"]),
                    "amount": round(float(row["amount"]), 2),
                    "due_date": target_dt.isoformat(),
                    "days_until_due": offset,
                })

        total_due = round(sum(b["amount"] for b in upcoming), 2)

        return json.dumps({
            "today": today,
            "days_ahead": days_ahead,
            "bill_count": len(upcoming),
            "count": len(upcoming),
            "total_due": total_due,
            "upcoming_bills": upcoming,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


def budget_status(month: str) -> str:
    """Compare monthly actual spending against budget limits for all categories."""
    try:
        b_path = _get_budgets_path()
        if not b_path.exists():
            return json.dumps({"error": f"Budgets file not found at {b_path}"})
        t_path = _get_transactions_path()
        if not t_path.exists():
            return json.dumps({"error": f"Transactions file not found at {t_path}"})

        with open(b_path, "r", encoding="utf-8") as f:
            budgets = json.load(f)

        df = _load_transactions()
        m_df = df[df["month"] == month]
        if m_df.empty:
            return json.dumps({"error": f"No transactions found for {month}"})

        exp_df = m_df[m_df["type"] == "expense"]
        spent_by_cat = exp_df.groupby("category")["amount"].sum().to_dict()

        categories_status = {}
        over_budget = []
        for cat, limit in budgets.items():
            spent = round(float(spent_by_cat.get(cat, 0.0)), 2)
            limit_val = round(float(limit), 2)
            pct = round((spent / limit_val * 100), 1) if limit_val > 0 else 0.0
            is_over = spent > limit_val
            categories_status[cat] = {
                "limit": limit_val,
                "spent": spent,
                "actual_spending": spent,
                "percent_used": pct,
                "is_over_budget": is_over,
                "remaining": round(limit_val - spent, 2),
            }
            if is_over:
                over_budget.append(cat)

        return json.dumps({
            "month": month,
            "categories": categories_status,
            "over_budget_categories": over_budget,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


def find_possible_duplicates(month: str) -> str:
    """Identify duplicate transactions with identical date, description, and amount."""
    try:
        t_path = _get_transactions_path()
        if not t_path.exists():
            return json.dumps({"error": f"Transactions file not found at {t_path}"})

        df = _load_transactions()
        m_df = df[df["month"] == month]
        if m_df.empty:
            return json.dumps({"error": f"No transactions found for {month}"})

        dup_mask = m_df.duplicated(subset=["date", "description", "amount"], keep=False)
        dup_df = m_df[dup_mask]

        if dup_df.empty:
            return json.dumps({
                "month": month,
                "count": 0,
                "duplicate_groups": [],
                "message": f"No duplicate transactions found for {month}",
            })

        groups = []
        for (dt, desc, amt), group in dup_df.groupby(["date", "description", "amount"]):
            groups.append({
                "date": str(dt),
                "description": str(desc),
                "amount": round(float(amt), 2),
                "count": len(group),
                "transactions": group.to_dict(orient="records"),
            })

        return json.dumps({
            "month": month,
            "count": len(groups),
            "duplicate_groups": groups,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


def propose_budget_change(category: str, new_limit: float) -> str:
    """Propose a change to a budget category limit, saving to pending proposals without modifying budgets.json."""
    try:
        b_path = _get_budgets_path()
        if not b_path.exists():
            return json.dumps({"error": f"Budgets file not found at {b_path}"})

        with open(b_path, "r", encoding="utf-8") as f:
            budgets = json.load(f)

        # Validate that category exists in budgets.json
        matched_cat = None
        for cat in budgets.keys():
            if cat.lower() == category.strip().lower():
                matched_cat = cat
                break

        if not matched_cat:
            return json.dumps({"error": f"Category '{category}' does not exist in budgets."})

        # Validate that new_limit is a number greater than 0
        try:
            limit_val = float(new_limit)
        except (ValueError, TypeError):
            return json.dumps({"error": f"Invalid limit '{new_limit}'. Limit must be a number greater than 0."})

        if limit_val <= 0:
            return json.dumps({"error": f"New limit must be greater than 0. Received: {limit_val}"})

        old_limit = float(budgets[matched_cat])
        max_allowed = round(old_limit * 2, 2)
        if limit_val > max_allowed:
            log_event(
                "budget_rejected",
                {
                    "category": matched_cat,
                    "current_limit": round(old_limit, 2),
                    "new_limit": round(limit_val, 2),
                    "maximum_allowed": max_allowed,
                },
            )
            return json.dumps({
                "error": f"Request rejected: new limit ${limit_val:.2f} exceeds maximum allowed of ${max_allowed:.2f} for category '{matched_cat}' (current limit: ${old_limit:.2f}).",
                "category": matched_cat,
                "current_limit": round(old_limit, 2),
                "maximum_allowed": max_allowed,
                "status": "rejected",
            })

        proposal_id = f"prop_{uuid.uuid4().hex[:8]}"
        timestamp = datetime.now().isoformat()

        # Ensure logs directory exists
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

        # Load existing pending proposals
        proposals = {}
        if PROPOSALS_PATH.exists():
            try:
                with open(PROPOSALS_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        proposals = data
                    elif isinstance(data, list):
                        proposals = {p["id"]: p for p in data if isinstance(p, dict) and "id" in p}
            except Exception:
                proposals = {}

        # Save proposal to logs/pending_proposals.json
        proposals[proposal_id] = {
            "id": proposal_id,
            "category": matched_cat,
            "old_limit": round(old_limit, 2),
            "new_limit": round(limit_val, 2),
            "timestamp": timestamp,
        }

        with open(PROPOSALS_PATH, "w", encoding="utf-8") as f:
            json.dump(proposals, f, indent=2)

        # Log budget_proposed event: proposal ID, category, old and new limit
        log_event(
            "budget_proposed",
            {
                "proposal_id": proposal_id,
                "category": matched_cat,
                "old_limit": round(old_limit, 2),
                "new_limit": round(limit_val, 2),
            },
        )

        return json.dumps({
            "proposal_id": proposal_id,
            "category": matched_cat,
            "old_limit": round(old_limit, 2),
            "new_limit": round(limit_val, 2),
            "status": "pending_confirmation",
            "message": f"Proposal {proposal_id} created for {matched_cat}: change limit from ${old_limit:.2f} to ${limit_val:.2f}. User confirmation in terminal required.",
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


def cashflow_projection(days_ahead: int = 30, today: str | None = None) -> str:
    """Project day-by-day cashflow, scheduled bills, expected income, and simulated balance over a forward horizon."""
    try:
        if today is None or not str(today).strip():
            today = AS_OF_DATE

        a_path = _get_account_path()
        if not a_path.exists():
            return json.dumps({"error": f"Account file not found at {a_path}"})
        t_path = _get_transactions_path()
        if not t_path.exists():
            return json.dumps({"error": f"Transactions file not found at {t_path}"})
        b_path = _get_bills_path()
        if not b_path.exists():
            return json.dumps({"error": f"Bills file not found at {b_path}"})

        try:
            today_dt = date.fromisoformat(today)
        except (ValueError, TypeError):
            return json.dumps({"error": f"Invalid date format for today: '{today}'. Expected YYYY-MM-DD."})

        if days_ahead < 0:
            return json.dumps({"error": "days_ahead must be a non-negative integer."})

        with open(a_path, "r", encoding="utf-8") as f:
            account_data = json.load(f)
        opening_balance = float(account_data.get("opening_balance", 0.0))

        df = _load_transactions()
        if df.empty:
            return json.dumps({"error": "No transactions found in transactions.csv"})

        bills_df = _load_bills()
        if bills_df.empty:
            return json.dumps({"error": "No bills found in bills.csv"})

        # 2.1.1 Starting balance = opening_balance + all income - all expenses on or before today
        past_tx = df[df["date"] <= today]
        inc_to_today = float(past_tx[past_tx["type"] == "income"]["amount"].sum())
        exp_to_today = float(past_tx[past_tx["type"] == "expense"]["amount"].sum())
        simulated_sandbox_balance = round(opening_balance + inc_to_today - exp_to_today, 2)

        # 2.1.2 Scheduled bills: reuse the same window and helper logic as upcoming_bills
        bill_cats = set(bills_df["category"].dropna().unique())
        scheduled_bills = []
        for offset in range(days_ahead + 1):
            target_dt = today_dt + timedelta(days=offset)
            matching = bills_df[bills_df["due_day"] == target_dt.day]
            for _, row in matching.iterrows():
                scheduled_bills.append({
                    "name": str(row["bill_name"]),
                    "due_date": target_dt.isoformat(),
                    "amount": round(float(row["amount"]), 2),
                })
        total_bills = round(sum(b["amount"] for b in scheduled_bills), 2)

        # 2.1.3 Expected income: infer usual pay day from most recent income transaction day of month,
        # use average monthly income, include only if that date falls inside window
        income_tx = df[df["type"] == "income"].sort_values("date")
        if income_tx.empty:
            pay_day = 1
            avg_monthly_income = 0.0
        else:
            most_recent_inc = income_tx.iloc[-1]
            pay_day = int(str(most_recent_inc["date"]).split("-")[2])
            monthly_incomes = income_tx.groupby("month")["amount"].sum()
            avg_monthly_income = round(float(monthly_incomes.mean()), 2)

        expected_income = 0.0
        income_by_date = {}
        for offset in range(days_ahead + 1):
            target_dt = today_dt + timedelta(days=offset)
            if target_dt.day == pay_day and offset > 0:
                income_by_date[target_dt.isoformat()] = avg_monthly_income
                expected_income += avg_monthly_income
        expected_income = round(expected_income, 2)

        # 2.1.4 Average daily discretionary spend = total expenses in categories that do NOT appear in bills.csv,
        # divided by the number of days between the first and last transaction months (inclusive)
        discretionary_df = df[(df["type"] == "expense") & (~df["category"].isin(bill_cats))]
        total_disc = float(discretionary_df["amount"].sum())
        months = sorted(df["month"].dropna().unique())
        if months:
            first_y, first_mo = map(int, months[0].split("-"))
            last_y, last_mo = map(int, months[-1].split("-"))
            first_month_start = date(first_y, first_mo, 1)
            _, last_day = calendar.monthrange(last_y, last_mo)
            last_month_end = date(last_y, last_mo, last_day)
            total_days = (last_month_end - first_month_start).days + 1
            avg_daily_discretionary_spend = round(total_disc / total_days, 2) if total_days > 0 else 0.0
        else:
            avg_daily_discretionary_spend = 0.0

        # 2.1.5 Simulate day by day: subtract bills on their due dates, add income on its date, subtract daily discretionary average
        bills_by_date = {}
        for b in scheduled_bills:
            bills_by_date.setdefault(b["due_date"], 0.0)
            bills_by_date[b["due_date"]] += b["amount"]

        current_balance = simulated_sandbox_balance
        lowest_balance = current_balance
        lowest_balance_date = today_dt.isoformat()

        if today_dt.isoformat() in bills_by_date:
            current_balance = round(current_balance - bills_by_date[today_dt.isoformat()], 2)
            if current_balance < lowest_balance:
                lowest_balance = current_balance
                lowest_balance_date = today_dt.isoformat()

        for offset in range(1, days_ahead + 1):
            current_dt = today_dt + timedelta(days=offset)
            date_str = current_dt.isoformat()

            if date_str in income_by_date:
                current_balance = round(current_balance + income_by_date[date_str], 2)
            if date_str in bills_by_date:
                current_balance = round(current_balance - bills_by_date[date_str], 2)
            current_balance = round(current_balance - avg_daily_discretionary_spend, 2)

            if current_balance < lowest_balance:
                lowest_balance = current_balance
                lowest_balance_date = date_str

        projected_end_balance = current_balance
        covers_all_bills = bool(lowest_balance >= 0.0)

        assumptions = [
            f"Simulated sandbox balance is ${simulated_sandbox_balance:.2f} as of {today}.",
            f"Expected recurring monthly income is ${avg_monthly_income:.2f} on day {pay_day} of each month.",
            f"Average daily discretionary spend is ${avg_daily_discretionary_spend:.2f} based on non-bill categories across past transaction months.",
            f"Scheduled bills total ${total_bills:.2f} across {len(scheduled_bills)} bills due in the {days_ahead}-day horizon.",
            "Daily spending uses all discretionary expenses in the period, including one-off costs such as the August medical charge. This makes the projection more conservative.",
        ]

        return json.dumps({
            "as_of": today,
            "simulated_sandbox_balance": simulated_sandbox_balance,
            "horizon_days": days_ahead,
            "scheduled_bills": scheduled_bills,
            "total_bills": total_bills,
            "expected_income": expected_income,
            "avg_daily_discretionary_spend": avg_daily_discretionary_spend,
            "projected_end_balance": projected_end_balance,
            "lowest_balance": lowest_balance,
            "lowest_balance_date": lowest_balance_date,
            "covers_all_bills": covers_all_bills,
            "assumptions": assumptions,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


def detect_spending_spikes(month: str) -> str:
    """Compare each expense category with the previous month and flag spikes (>50% increase AND >=$50 absolute increase)."""
    try:
        t_path = _get_transactions_path()
        if not t_path.exists():
            return json.dumps({"error": f"Transactions file not found at {t_path}"})

        df = _load_transactions()
        m_df = df[(df["month"] == month) & (df["type"] == "expense")]
        if m_df.empty:
            return json.dumps({"error": f"No transactions found for {month}"})

        # Calculate previous month string (YYYY-MM)
        try:
            year, mo = map(int, month.split("-"))
            if mo == 1:
                prev_month = f"{year - 1:04d}-12"
            else:
                prev_month = f"{year:04d}-{mo - 1:02d}"
        except Exception:
            return json.dumps({"error": f"Invalid month format: '{month}'. Expected YYYY-MM."})

        prev_df = df[(df["month"] == prev_month) & (df["type"] == "expense")]
        if prev_df.empty:
            return json.dumps({"error": f"No data found for the previous month ({prev_month}) to compare with {month}."})

        curr_by_cat = m_df.groupby("category")["amount"].sum().to_dict()
        prev_by_cat = prev_df.groupby("category")["amount"].sum().to_dict()

        all_categories = sorted(set(list(curr_by_cat.keys()) + list(prev_by_cat.keys())))
        spikes = []
        for cat in all_categories:
            prev_amt = round(float(prev_by_cat.get(cat, 0.0)), 2)
            curr_amt = round(float(curr_by_cat.get(cat, 0.0)), 2)
            inc_amt = round(curr_amt - prev_amt, 2)
            inc_pct = round((inc_amt / prev_amt * 100), 1) if prev_amt > 0 else 0.0

            # 2.2.2 Flag a spike when the increase is more than 50% AND at least $50 in absolute terms
            if inc_pct > 50.0 and inc_amt >= 50.0:
                spikes.append({
                    "category": cat,
                    "previous_amount": prev_amt,
                    "current_amount": curr_amt,
                    "increase_amount": inc_amt,
                    "increase_percent": inc_pct,
                })

        return json.dumps({
            "month": month,
            "previous_month": prev_month,
            "spike_count": len(spikes),
            "count": len(spikes),
            "spikes": spikes,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


def savings_recommendations(month: str) -> str:
    """Generate rule-based financial advice and savings recommendations for a given month."""
    try:
        t_path = _get_transactions_path()
        if not t_path.exists():
            return json.dumps({"error": f"Transactions file not found at {t_path}"})
        b_path = _get_budgets_path()
        if not b_path.exists():
            return json.dumps({"error": f"Budgets file not found at {b_path}"})

        with open(b_path, "r", encoding="utf-8") as f:
            budgets = json.load(f)

        df = _load_transactions()
        m_df = df[df["month"] == month]
        if m_df.empty:
            return json.dumps({"error": f"No transactions found for {month}"})

        exp_df = m_df[m_df["type"] == "expense"]
        inc_df = m_df[m_df["type"] == "income"]
        spent_by_cat = exp_df.groupby("category")["amount"].sum().to_dict()

        # 1. Budget status check
        over_budget_cats = {}
        for cat, limit in budgets.items():
            spent = round(float(spent_by_cat.get(cat, 0.0)), 2)
            limit_val = round(float(limit), 2)
            if spent > limit_val:
                over_budget_cats[cat] = {
                    "spent": spent,
                    "limit": limit_val,
                    "over_amount": round(spent - limit_val, 2),
                }

        # 2. Spike check
        spikes_by_cat = {}
        prev_by_cat = {}
        try:
            year, mo = map(int, month.split("-"))
            prev_month = f"{year - 1:04d}-12" if mo == 1 else f"{year:04d}-{mo - 1:02d}"
            prev_df = df[(df["month"] == prev_month) & (df["type"] == "expense")]
            if not prev_df.empty:
                prev_by_cat = prev_df.groupby("category")["amount"].sum().to_dict()
                for cat in set(list(spent_by_cat.keys()) + list(prev_by_cat.keys())):
                    p = round(float(prev_by_cat.get(cat, 0.0)), 2)
                    c = round(float(spent_by_cat.get(cat, 0.0)), 2)
                    inc_amt = round(c - p, 2)
                    inc_pct = round((inc_amt / p * 100), 1) if p > 0 else 0.0
                    if inc_pct > 50.0 and inc_amt >= 50.0:
                        spikes_by_cat[cat] = {
                            "previous_amount": p,
                            "current_amount": c,
                            "increase_amount": inc_amt,
                            "increase_percent": inc_pct,
                        }
        except Exception:
            pass

        items = []

        # 2.3.1 One item per category that is over budget or has a spike, merged into a single item.
        # potential_monthly_saving is the larger of (spent - limit) and the spike increase.
        flagged_categories = sorted(set(list(over_budget_cats.keys()) + list(spikes_by_cat.keys())))
        for cat in flagged_categories:
            ob_info = over_budget_cats.get(cat)
            sp_info = spikes_by_cat.get(cat)

            spent = float(spent_by_cat.get(cat, 0.0))
            limit = float(ob_info["limit"]) if ob_info else None
            prev_spent = float(prev_by_cat.get(cat, 0.0)) if prev_by_cat else 0.0

            saving_to_budget = round(spent - limit, 2) if limit is not None else 0.0
            saving_to_prior_month = round(spent - prev_spent, 2) if prev_spent > 0 else 0.0
            potential_saving = round(max(saving_to_budget, saving_to_prior_month), 2)

            evidence = {}
            if ob_info:
                evidence["spent"] = ob_info["spent"]
                evidence["budget_limit"] = ob_info["limit"]
                evidence["over_budget_by"] = ob_info["over_amount"]
            if sp_info:
                evidence["previous_month_spent"] = sp_info["previous_amount"]
                evidence["current_month_spent"] = sp_info["current_amount"]
                evidence["spike_increase"] = sp_info["increase_amount"]
                evidence["spike_percent"] = sp_info["increase_percent"]
            evidence["saving_to_budget"] = saving_to_budget
            evidence["saving_to_prior_month"] = saving_to_prior_month

            if cat == "Health":
                item_type = "budget_overrun_and_spike" if (ob_info and sp_info) else ("budget_overrun" if ob_info else "spending_spike")
                if saving_to_budget > saving_to_prior_month:
                    action = f"Bring Health within its ${limit:.2f} budget to save ${saving_to_budget:.2f}."
                else:
                    action = f"Bring Health back to last month’s ${prev_spent:.2f} to save ${saving_to_prior_month:.2f}."
            elif ob_info and sp_info:
                item_type = "budget_overrun_and_spike"
                if saving_to_budget > saving_to_prior_month:
                    action = f"Bring {cat} within its ${limit:.2f} budget to save ${saving_to_budget:.2f}."
                else:
                    action = f"Bring {cat} back to last month’s ${prev_spent:.2f} to save ${saving_to_prior_month:.2f}."
            elif ob_info:
                item_type = "budget_overrun"
                action = f"Reduce spending in {cat} back within the ${ob_info['limit']:.2f} budget to save ${potential_saving:.2f}."
            else:
                item_type = "spending_spike"
                action = f"Review unexpected spike in {cat} to trim up to ${potential_saving:.2f}."

            items.append({
                "type": item_type,
                "category": cat,
                "saving_to_budget": saving_to_budget,
                "saving_to_prior_month": saving_to_prior_month,
                "evidence": evidence,
                "suggested_action": action,
                "potential_monthly_saving": potential_saving,
            })

        # 2.3.2 One item for duplicate charges, with the duplicate amount as the potential saving.
        dup_mask = m_df.duplicated(subset=["date", "description", "amount"], keep=False)
        dup_df = m_df[dup_mask]
        if not dup_df.empty:
            total_dup_saving = 0.0
            dup_details = []
            for (dt, desc, amt), group in dup_df.groupby(["date", "description", "amount"]):
                dup_amt = round(float(amt) * (len(group) - 1), 2)
                total_dup_saving += dup_amt
                dup_details.append({
                    "date": str(dt),
                    "description": str(desc),
                    "amount": round(float(amt), 2),
                    "duplicate_count": len(group) - 1,
                    "duplicate_saving": dup_amt,
                })
            total_dup_saving = round(total_dup_saving, 2)
            items.append({
                "type": "duplicate_charges",
                "category": "Dining" if any(d.get("category") == "Dining" for _, d in dup_df.iterrows()) else None,
                "evidence": {
                    "duplicate_groups_count": len(dup_details),
                    "total_duplicate_amount": total_dup_saving,
                    "details": dup_details,
                },
                "suggested_action": f"Request a refund or merchant credit for duplicate charges to save ${total_dup_saving:.2f}.",
                "potential_monthly_saving": total_dup_saving,
            })

        # 2.3.3 One item if the savings rate is below 20% of income, with the dollar gap to 20%.
        inc_val = float(inc_df["amount"].sum())
        exp_val = float(exp_df["amount"].sum())
        net_val = inc_val - exp_val
        target_savings = round(0.20 * inc_val, 2)
        if net_val < target_savings:
            gap = round(target_savings - net_val, 2)
            items.append({
                "type": "savings_rate_gap",
                "category": None,
                "evidence": {
                    "income": round(inc_val, 2),
                    "expenses": round(exp_val, 2),
                    "net_savings": round(net_val, 2),
                    "current_savings_rate": round(net_val / inc_val * 100, 1) if inc_val > 0 else 0.0,
                    "target_savings_20pct": target_savings,
                    "gap_to_20pct": gap,
                },
                "suggested_action": f"Increase your monthly net savings by ${gap:.2f} to achieve a 20% savings rate target.",
                "potential_monthly_saving": gap,
            })

        # 2.3.5 Return total_potential_saving as the Python-computed sum of the items' savings
        total_potential_saving = round(sum(item["potential_monthly_saving"] for item in items), 2)

        # 2.3.6 Return a disclaimer field containing: "General suggestion, not professional financial advice."
        disclaimer = "General suggestion, not professional financial advice."

        return json.dumps({
            "month": month,
            "item_count": len(items),
            "recommendations": items,
            "total_potential_saving": total_potential_saving,
            "disclaimer": disclaimer,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})



# ============================================================================
# JSON Schemas for LLM Tool Calling
# ============================================================================

GET_MONTHLY_SUMMARY_SCHEMA = {
    "name": "get_monthly_summary",
    "description": "Calculates total income, expenses, net savings, and savings rate for a given month. Use when the user asks for a monthly financial overview. Arguments: month (YYYY-MM). Result: JSON with total_income, total_expenses, net_savings, and savings_rate.",
    "parameters": {
        "type": "object",
        "properties": {
            "month": {
                "type": "string",
                "description": "Month in YYYY-MM format, e.g., '2026-07'.",
            }
        },
        "required": ["month"],
    },
}

SPENDING_BY_CATEGORY_SCHEMA = {
    "name": "spending_by_category",
    "description": "Calculates total spending per category for a given month, ordered highest to lowest. Use to analyze spending breakdown across categories. Arguments: month (YYYY-MM). Result: JSON mapping categories to spending amounts sorted descending.",
    "parameters": {
        "type": "object",
        "properties": {
            "month": {
                "type": "string",
                "description": "Month in YYYY-MM format, e.g., '2026-07'.",
            }
        },
        "required": ["month"],
    },
}

GET_TRANSACTIONS_SCHEMA = {
    "name": "get_transactions",
    "description": "Retrieves transactions for a month, optionally filtered by category. Use to inspect itemized transaction records. Arguments: month (YYYY-MM), category (optional string). Result: JSON with list of matching transaction records.",
    "parameters": {
        "type": "object",
        "properties": {
            "month": {
                "type": "string",
                "description": "Month in YYYY-MM format, e.g., '2026-07'.",
            },
            "category": {
                "type": "string",
                "description": "Optional category name to filter by, e.g., 'Dining'.",
            },
        },
        "required": ["month"],
    },
}

UPCOMING_BILLS_SCHEMA = {
    "name": "upcoming_bills",
    "description": f"Finds recurring bills due within N days from a reference date. Use to check bill schedules and upcoming dues. Arguments: today (optional YYYY-MM-DD, defaults to simulated date '{AS_OF_DATE}'), days_ahead (integer, default 30). Result: JSON list of upcoming bills with due dates, amounts, bill_count, and total_due. Totals must be quoted directly from total_due.",
    "parameters": {
        "type": "object",
        "properties": {
            "today": {
                "type": "string",
                "description": f"Optional reference date in YYYY-MM-DD format, e.g., '{AS_OF_DATE}'. Defaults to current simulated sandbox date.",
            },
            "days_ahead": {
                "type": "integer",
                "description": "Number of days ahead to search for due bills (default 30).",
            },
        },
    },
}

BUDGET_STATUS_SCHEMA = {
    "name": "budget_status",
    "description": "Compares monthly actual spending against budget limits for all categories. Use to check budget adherence and overspending. Arguments: month (YYYY-MM). Result: JSON showing limit, actual spending, percent used, and is_over_budget flag per category.",
    "parameters": {
        "type": "object",
        "properties": {
            "month": {
                "type": "string",
                "description": "Month in YYYY-MM format, e.g., '2026-07'.",
            }
        },
        "required": ["month"],
    },
}

FIND_POSSIBLE_DUPLICATES_SCHEMA = {
    "name": "find_possible_duplicates",
    "description": "Identifies transactions with identical date, description, and amount in a given month. Use to detect duplicate charges for auditing. Arguments: month (YYYY-MM). Result: JSON list of grouped duplicate transactions.",
    "parameters": {
        "type": "object",
        "properties": {
            "month": {
                "type": "string",
                "description": "Month in YYYY-MM format, e.g., '2026-07'.",
            }
        },
        "required": ["month"],
    },
}

PROPOSE_BUDGET_CHANGE_SCHEMA = {
    "name": "propose_budget_change",
    "description": "Proposes a change to a category spending limit. Does not apply the change; generates a pending proposal that requires user confirmation in the terminal. Arguments: category (string), new_limit (positive number). Result: JSON containing proposal_id, category, old_limit, and new_limit.",
    "parameters": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "The budget category to update (e.g., 'Dining').",
            },
            "new_limit": {
                "type": "number",
                "description": "The proposed new monthly spending limit in USD (must be > 0).",
            },
        },
        "required": ["category", "new_limit"],
    },
}

CASHFLOW_PROJECTION_SCHEMA = {
    "name": "cashflow_projection",
    "description": "Simulates and projects day-by-day cashflow, scheduled upcoming bills, expected recurring income, and sandbox account balance over a forward horizon (default 30 days). Use this tool whenever the user asks about future cashflow, whether they can cover upcoming bills, when their balance will be lowest, or asks for their simulated sandbox account balance. Arguments: days_ahead (integer, default 30), today (string YYYY-MM-DD, defaults to the simulated sandbox date). Result fields to quote: simulated_sandbox_balance, total_bills, expected_income, projected_end_balance, lowest_balance, lowest_balance_date, covers_all_bills. Quote totals and balances only from the tool's fields; never calculate or estimate balances yourself.",
    "parameters": {
        "type": "object",
        "properties": {
            "days_ahead": {
                "type": "integer",
                "description": "Number of days ahead to project (default is 30).",
            },
            "today": {
                "type": "string",
                "description": "Starting date for projection in YYYY-MM-DD format (defaults to the simulated sandbox date).",
            },
        },
    },
}

DETECT_SPENDING_SPIKES_SCHEMA = {
    "name": "detect_spending_spikes",
    "description": "Compares each expense category against the previous month and flags significant spending spikes (where spending increased by >50% AND at least $50 in absolute terms). Use this tool whenever asked if spending spiked, jumped, or surged in a given month. Arguments: month (string YYYY-MM). Result fields to quote: category, previous_amount, current_amount, increase_amount, increase_percent. Quote numbers only from the tool's fields.",
    "parameters": {
        "type": "object",
        "properties": {
            "month": {
                "type": "string",
                "description": "The target month in YYYY-MM format to check for spending spikes against its preceding month.",
            },
        },
        "required": ["month"],
    },
}

SAVINGS_RECOMMENDATIONS_SCHEMA = {
    "name": "savings_recommendations",
    "description": "Generates rule-based financial advice and savings recommendations for a given month by evaluating budget overruns, spending spikes, duplicate charges, and savings rate targets. Use this tool whenever asked for advice, tips, or ways to save money. Arguments: month (string YYYY-MM). Result fields to quote: recommendations (each with type, category, suggested_action, potential_monthly_saving, saving_to_budget, saving_to_prior_month), total_potential_saving, and disclaimer. Quote totals and savings amounts only from the tool's fields; always include the disclaimer stating it is a general suggestion and not professional financial advice.",
    "parameters": {
        "type": "object",
        "properties": {
            "month": {
                "type": "string",
                "description": "The month in YYYY-MM format for which to generate savings recommendations.",
            },
        },
        "required": ["month"],
    },
}

# Only schemas sent to the model
TOOL_SCHEMAS = [
    GET_MONTHLY_SUMMARY_SCHEMA,
    SPENDING_BY_CATEGORY_SCHEMA,
    GET_TRANSACTIONS_SCHEMA,
    UPCOMING_BILLS_SCHEMA,
    BUDGET_STATUS_SCHEMA,
    FIND_POSSIBLE_DUPLICATES_SCHEMA,
    PROPOSE_BUDGET_CHANGE_SCHEMA,
    CASHFLOW_PROJECTION_SCHEMA,
    DETECT_SPENDING_SPIKES_SCHEMA,
    SAVINGS_RECOMMENDATIONS_SCHEMA,
]

TOOLS_BY_NAME = {
    "get_monthly_summary": get_monthly_summary,
    "spending_by_category": spending_by_category,
    "get_transactions": get_transactions,
    "upcoming_bills": upcoming_bills,
    "budget_status": budget_status,
    "find_possible_duplicates": find_possible_duplicates,
    "propose_budget_change": propose_budget_change,
    "cashflow_projection": cashflow_projection,
    "detect_spending_spikes": detect_spending_spikes,
    "savings_recommendations": savings_recommendations,
}

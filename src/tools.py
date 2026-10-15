"""Read-only financial analysis tools using pandas and JSON schemas for LLM tool calling."""

from datetime import date, timedelta
import json
from pathlib import Path
import pandas as pd

# Resolve paths relative to project root (finance_agent/)
try:
    from src.config import TRANSACTIONS_PATH, BILLS_PATH, BUDGETS_PATH
except ImportError:
    try:
        from config import TRANSACTIONS_PATH, BILLS_PATH, BUDGETS_PATH
    except ImportError:
        PROJECT_ROOT = Path(__file__).resolve().parent.parent
        DATA_DIR = PROJECT_ROOT / "data"
        TRANSACTIONS_PATH = DATA_DIR / "transactions.csv"
        BILLS_PATH = DATA_DIR / "bills.csv"
        BUDGETS_PATH = DATA_DIR / "budgets.json"


# ============================================================================
# Tool Implementations
# ============================================================================

def get_monthly_summary(month: str) -> str:
    """Calculate total income, expenses, net savings, and savings rate for a month."""
    try:
        if not TRANSACTIONS_PATH.exists():
            return json.dumps({"error": f"Transactions file not found at {TRANSACTIONS_PATH}"})

        df = pd.read_csv(TRANSACTIONS_PATH)
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
        if not TRANSACTIONS_PATH.exists():
            return json.dumps({"error": f"Transactions file not found at {TRANSACTIONS_PATH}"})

        df = pd.read_csv(TRANSACTIONS_PATH)
        m_df = df[df["month"] == month]
        if m_df.empty:
            return json.dumps({"error": f"No transactions found for {month}"})

        exp_df = m_df[m_df["type"] == "expense"]
        if exp_df.empty:
            return json.dumps({"error": f"No expense transactions found for {month}"})

        grouped = exp_df.groupby("category")["amount"].sum().sort_values(ascending=False)
        spending_dict = {str(cat): round(float(amt), 2) for cat, amt in grouped.items()}

        result = {
            "month": month,
            "spending_by_category": spending_dict,
        }
        # Provide direct category access for convenience
        for cat, amt in spending_dict.items():
            if cat not in result:
                result[cat] = amt

        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_transactions(month: str, category: str | None = None) -> str:
    """List transactions for a month, optionally filtered by category."""
    try:
        if not TRANSACTIONS_PATH.exists():
            return json.dumps({"error": f"Transactions file not found at {TRANSACTIONS_PATH}"})

        df = pd.read_csv(TRANSACTIONS_PATH)
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


def upcoming_bills(today: str, days_ahead: int = 30) -> str:
    """Find recurring bills due within N days from a given date."""
    try:
        if not BILLS_PATH.exists():
            return json.dumps({"error": f"Bills file not found at {BILLS_PATH}"})

        try:
            today_dt = date.fromisoformat(today)
        except (ValueError, TypeError):
            return json.dumps({"error": f"Invalid date format for today: '{today}'. Expected YYYY-MM-DD."})

        if days_ahead < 0:
            return json.dumps({"error": "days_ahead must be a non-negative integer."})

        bills_df = pd.read_csv(BILLS_PATH)
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
        if not BUDGETS_PATH.exists():
            return json.dumps({"error": f"Budgets file not found at {BUDGETS_PATH}"})
        if not TRANSACTIONS_PATH.exists():
            return json.dumps({"error": f"Transactions file not found at {TRANSACTIONS_PATH}"})

        with open(BUDGETS_PATH, "r", encoding="utf-8") as f:
            budgets = json.load(f)

        df = pd.read_csv(TRANSACTIONS_PATH)
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
        if not TRANSACTIONS_PATH.exists():
            return json.dumps({"error": f"Transactions file not found at {TRANSACTIONS_PATH}"})

        df = pd.read_csv(TRANSACTIONS_PATH)
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
    "description": "Finds recurring bills due within N days from a reference date. Use to check bill schedules and upcoming dues. Arguments: today (YYYY-MM-DD), days_ahead (integer, default 30). Result: JSON list of upcoming bills with due dates, amounts, bill_count, and total_due. Totals must be quoted directly from total_due.",
    "parameters": {
        "type": "object",
        "properties": {
            "today": {
                "type": "string",
                "description": "Reference date in YYYY-MM-DD format, e.g., '2026-07-01'.",
            },
            "days_ahead": {
                "type": "integer",
                "description": "Number of days ahead to search for due bills (default 30).",
            },
        },
        "required": ["today"],
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

TOOL_SCHEMAS = [
    GET_MONTHLY_SUMMARY_SCHEMA,
    SPENDING_BY_CATEGORY_SCHEMA,
    GET_TRANSACTIONS_SCHEMA,
    UPCOMING_BILLS_SCHEMA,
    BUDGET_STATUS_SCHEMA,
    FIND_POSSIBLE_DUPLICATES_SCHEMA,
]

TOOLS_BY_NAME = {
    "get_monthly_summary": get_monthly_summary,
    "spending_by_category": spending_by_category,
    "get_transactions": get_transactions,
    "upcoming_bills": upcoming_bills,
    "budget_status": budget_status,
    "find_possible_duplicates": find_possible_duplicates,
}

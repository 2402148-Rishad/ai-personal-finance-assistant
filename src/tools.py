"""Financial analysis and budget management tools using pandas and JSON schemas for LLM tool calling."""

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import uuid
import pandas as pd

from src.logger import log_event

try:
    from src.periods import resolve_period
except ImportError:
    try:
        from periods import resolve_period
    except ImportError:
        def resolve_period(text):
            return text

try:
    from src.validators import (
        validate_amount,
        validate_date,
        validate_category,
        validate_text,
        get_workspace_categories,
    )
except ImportError:
    from validators import (
        validate_amount,
        validate_date,
        validate_category,
        validate_text,
        get_workspace_categories,
    )

try:
    import src.store as store
except ImportError:
    import store

try:
    from src.categories import suggest_category, category_is_stated
except ImportError:
    try:
        from categories import suggest_category, category_is_stated
    except ImportError:
        def suggest_category(text, workspace=None):
            return None
        def category_is_stated(category, text):
            return True


class JsonDict(str):
    """String subclass containing JSON that also allows dict-like access for Python callers."""

    def __new__(cls, data: dict):
        s = json.dumps(data)
        obj = super().__new__(cls, s)
        obj._data = data
        return obj

    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __contains__(self, key):
        return key in self._data

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()


# Resolve paths relative to project root (finance_agent/)
try:
    from src.config import (
        TRANSACTIONS_PATH, BILLS_PATH, BUDGETS_PATH, ACCOUNT_PATH, PROJECT_ROOT, AS_OF_DATE,
        TOOL_ROW_LIMIT, TOOL_CHAR_LIMIT
    )
except ImportError:
    try:
        from config import (
            TRANSACTIONS_PATH, BILLS_PATH, BUDGETS_PATH, ACCOUNT_PATH, PROJECT_ROOT, AS_OF_DATE,
            TOOL_ROW_LIMIT, TOOL_CHAR_LIMIT
        )
    except ImportError:
        PROJECT_ROOT = Path(__file__).resolve().parent.parent
        DATA_DIR = PROJECT_ROOT / "data"
        TRANSACTIONS_PATH = DATA_DIR / "transactions.csv"
        BILLS_PATH = DATA_DIR / "bills.csv"
        BUDGETS_PATH = DATA_DIR / "budgets.json"
        ACCOUNT_PATH = DATA_DIR / "account.json"
        AS_OF_DATE = "2026-08-31"
        TOOL_ROW_LIMIT = 50
        TOOL_CHAR_LIMIT = 6000

LOGS_DIR = PROJECT_ROOT / "logs"
PROPOSALS_PATH = LOGS_DIR / "pending_proposals.json"


def truncate_tool_result(data: dict) -> dict:
    """Enforce TOOL_ROW_LIMIT and TOOL_CHAR_LIMIT on tool output dictionary.

    When a tool result exceeds either limit, truncate it and add:
      "truncated": True
      "total_rows": N
    where N is the original total number of rows.
    """
    if not isinstance(data, dict):
        return data

    row_keys = [
        "transactions", "upcoming_bills", "duplicate_groups",
        "recommendations", "spikes", "scheduled_bills", "items", "rows",
        "subscriptions"
    ]
    target_key = next((k for k in row_keys if k in data and isinstance(data[k], list)), None)
    if not target_key:
        target_key = next((k for k, v in data.items() if isinstance(v, list) and v and isinstance(v[0], dict)), None)

    needs_truncation = False
    total_rows = 0

    if target_key:
        orig_list = data[target_key]
        total_rows = len(orig_list)
        if total_rows > TOOL_ROW_LIMIT:
            needs_truncation = True
            data[target_key] = list(orig_list[:TOOL_ROW_LIMIT])

    # Check character limit
    dumped = json.dumps(data)
    if len(dumped) > TOOL_CHAR_LIMIT:
        needs_truncation = True
        if target_key:
            if total_rows == 0:
                total_rows = len(data[target_key])
            data["truncated"] = True
            data["total_rows"] = total_rows
            while len(data[target_key]) > 0 and len(json.dumps(data)) > TOOL_CHAR_LIMIT:
                data[target_key].pop()
        else:
            data["truncated"] = True
            data["total_rows"] = total_rows

    if needs_truncation:
        data["truncated"] = True
        data["total_rows"] = total_rows

    return data



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
    ws = store.get_active_workspace()
    if ws is not None:
        return ws / "transactions.csv"
    env_dir = os.getenv("FINANCE_DATA_DIR")
    if env_dir and env_dir.strip():
        return Path(env_dir.strip()).resolve() / "transactions.csv"
    cur = globals().get("TRANSACTIONS_PATH")
    default_p = PROJECT_ROOT / "data" / "transactions.csv"
    return cur if cur is not None else default_p


def _get_bills_path() -> Path:
    ws = store.get_active_workspace()
    if ws is not None:
        return ws / "bills.csv"
    env_dir = os.getenv("FINANCE_DATA_DIR")
    if env_dir and env_dir.strip():
        return Path(env_dir.strip()).resolve() / "bills.csv"
    cur = globals().get("BILLS_PATH")
    default_p = PROJECT_ROOT / "data" / "bills.csv"
    return cur if cur is not None else default_p


def _get_budgets_path() -> Path:
    ws = store.get_active_workspace()
    if ws is not None:
        return ws / "budgets.json"
    env_dir = os.getenv("FINANCE_DATA_DIR")
    if env_dir and env_dir.strip():
        return Path(env_dir.strip()).resolve() / "budgets.json"
    cur = globals().get("BUDGETS_PATH")
    default_p = PROJECT_ROOT / "data" / "budgets.json"
    return cur if cur is not None else default_p


def _get_account_path() -> Path:
    ws = store.get_active_workspace()
    if ws is not None:
        return ws / "account.json"
    env_dir = os.getenv("FINANCE_DATA_DIR")
    if env_dir and env_dir.strip():
        return Path(env_dir.strip()).resolve() / "account.json"
    cur = globals().get("ACCOUNT_PATH")
    default_p = PROJECT_ROOT / "data" / "account.json"
    return cur if cur is not None else default_p


def _load_transactions() -> pd.DataFrame:
    path = _get_transactions_path()
    try:
        from src.store import ensure_transaction_ids
        df = pd.read_csv(path)
        df = ensure_transaction_ids(df)
    except Exception:
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


def get_data_overview() -> str:
    """Returns high-level metadata about the available financial dataset."""
    try:
        tx_df = _load_transactions()
        if not tx_df.empty and "month" in tx_df.columns:
            months = sorted([str(m) for m in tx_df["month"].dropna().unique() if re.match(r"^\d{4}-\d{2}$", str(m))])
            first_month = months[0] if months else None
            last_month = months[-1] if months else None
            tx_count = len(tx_df)
            if "type" in tx_df.columns and "category" in tx_df.columns:
                exp_cats = sorted([str(c) for c in tx_df[tx_df["type"] == "expense"]["category"].dropna().unique()])
            else:
                exp_cats = []
        else:
            months = []
            first_month = None
            last_month = None
            tx_count = 0
            exp_cats = []

        bills_df = _load_bills()
        bill_count = len(bills_df) if not bills_df.empty else 0

        b_path = _get_budgets_path()
        if b_path.exists():
            try:
                with open(b_path, "r", encoding="utf-8") as f:
                    budgets = json.load(f)
                budget_cats = sorted(list(budgets.keys())) if isinstance(budgets, dict) else []
            except Exception:
                budget_cats = []
        else:
            budget_cats = []

        try:
            from src.store import get_sandbox_today
            sandbox_today = get_sandbox_today()
        except Exception:
            env_as_of = os.getenv("FINANCE_AS_OF_DATE")
            sandbox_today = env_as_of if env_as_of else globals().get("AS_OF_DATE", "2026-08-31")


        data = {
            "first_month": first_month,
            "last_month": last_month,
            "months": months,
            "expense_categories": exp_cats,
            "transaction_count": tx_count,
            "bill_count": bill_count,
            "budget_categories": budget_cats,
            "sandbox_today": sandbox_today,
        }
        return JsonDict(data)
    except Exception as e:
        return JsonDict({"error": str(e)})


# ============================================================================
# Tool Implementations
# ============================================================================

def get_monthly_summary(month: str) -> str:
    """Calculate total income, expenses, net savings, and savings rate for a month."""
    try:
        resolved = resolve_period(month)
        if isinstance(resolved, dict):
            return json.dumps(resolved)
        month = resolved[:7] if (len(resolved) == 10 and resolved[4] == "-" and resolved[7] == "-") else resolved

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
        resolved = resolve_period(month)
        if isinstance(resolved, dict):
            return json.dumps(resolved)
        month = resolved[:7] if (len(resolved) == 10 and resolved[4] == "-" and resolved[7] == "-") else resolved

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
        resolved = resolve_period(month)
        if isinstance(resolved, dict):
            return json.dumps(resolved)
        month = resolved[:7] if (len(resolved) == 10 and resolved[4] == "-" and resolved[7] == "-") else resolved

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
        res = {
            "month": month,
            "category": category,
            "count": len(records),
            "transactions": records,
        }
        return json.dumps(truncate_tool_result(res))

    except Exception as e:
        return json.dumps({"error": str(e)})


def upcoming_bills(today: str | None = None, days_ahead: int = 30) -> str:
    """Find recurring bills due within N days from a given date."""
    try:
        if today is not None and str(today).strip():
            resolved_today = resolve_period(today)
            if isinstance(resolved_today, str):
                today = resolved_today

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
            max_day = calendar.monthrange(target_dt.year, target_dt.month)[1]
            for _, row in bills_df.iterrows():
                try:
                    raw_day = int(row["due_day"])
                except (ValueError, TypeError):
                    continue
                clamped_day = min(raw_day, max_day)
                if clamped_day == target_dt.day:
                    upcoming.append({
                        "bill_name": str(row["bill_name"]),
                        "category": str(row["category"]),
                        "amount": round(float(row["amount"]), 2),
                        "due_date": target_dt.isoformat(),
                        "days_until_due": offset,
                    })

        total_due = round(sum(b["amount"] for b in upcoming), 2)

        res = {
            "today": today,
            "days_ahead": days_ahead,
            "bill_count": len(upcoming),
            "count": len(upcoming),
            "total_due": total_due,
            "upcoming_bills": upcoming,
        }
        return json.dumps(truncate_tool_result(res))

    except Exception as e:
        return json.dumps({"error": str(e)})


def budget_status(month: str) -> str:
    """Compare monthly actual spending against budget limits for all categories."""
    try:
        resolved = resolve_period(month)
        if isinstance(resolved, dict):
            return json.dumps(resolved)
        month = resolved[:7] if (len(resolved) == 10 and resolved[4] == "-" and resolved[7] == "-") else resolved

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
            pct = round((spent / limit_val * 100), 1) if limit_val > 0 else None
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
        resolved = resolve_period(month)
        if isinstance(resolved, dict):
            return json.dumps(resolved)
        month = resolved[:7] if (len(resolved) == 10 and resolved[4] == "-" and resolved[7] == "-") else resolved

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

        res = {
            "month": month,
            "count": len(groups),
            "duplicate_groups": groups,
        }
        return json.dumps(truncate_tool_result(res))

    except Exception as e:
        return json.dumps({"error": str(e)})


def _sync_legacy_proposals(proposal_id: str, proposal: dict) -> None:
    """Sync proposal to PROPOSALS_PATH to maintain compatibility with isolated tests."""
    if PROPOSALS_PATH:
        try:
            PROPOSALS_PATH.parent.mkdir(parents=True, exist_ok=True)
            p_data = {}
            if PROPOSALS_PATH.exists():
                with open(PROPOSALS_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        p_data = data
                    elif isinstance(data, list):
                        p_data = {str(p.get("id") or p.get("proposal_id")): p for p in data if isinstance(p, dict)}
            p_data[proposal_id] = proposal
            with open(PROPOSALS_PATH, "w", encoding="utf-8") as f:
                json.dump(p_data, f, indent=2)
        except Exception:
            pass


def propose_budget_change(
    category: str,
    new_limit: float | None = None,
    action: str | None = None,
) -> str:
    """Propose a change to a budget category limit, add a new category, or remove a category.

    Does not modify budgets.json; saves to pending proposals.
    Output keys remain: proposal_id, category, old_limit, new_limit, status, message (or error, category, current_limit, maximum_allowed, status).
    """
    try:
        b_path = _get_budgets_path()
        workspace_dir = b_path.parent
        if not b_path.exists():
            return json.dumps({"error": f"Budgets file not found at {b_path}"})

        with open(b_path, "r", encoding="utf-8") as f:
            budgets = json.load(f)

        if category is None or not str(category).strip():
            return json.dumps({"error": "Category cannot be empty."})

        cat_str = str(category).strip()
        action_clean = str(action).strip().lower() if action is not None else None

        # Check existing category match
        matched_cat = None
        for cat in budgets.keys():
            if cat.lower() == cat_str.lower():
                matched_cat = cat
                break

        # Action: Remove category
        if action_clean in ("remove", "delete"):
            if not matched_cat:
                return json.dumps({"error": f"Category '{category}' does not exist in budgets."})

            old_limit = float(budgets[matched_cat])
            risk = "high"
            preview = {"before": round(old_limit, 2), "after": None}
            proposal_id = f"prop_{uuid.uuid4().hex[:8]}"

            proposal = store.create_proposal(
                kind="budget_change",
                payload={"category": matched_cat, "action": "remove", "new_limit": 0.0},
                preview=preview,
                risk=risk,
                workspace=workspace_dir,
                proposal_id=proposal_id,
                category=matched_cat,
                old_limit=round(old_limit, 2),
                new_limit=0.0,
            )

            _sync_legacy_proposals(proposal_id, proposal)

            log_event(
                "budget_proposed",
                {
                    "proposal_id": proposal_id,
                    "category": matched_cat,
                    "old_limit": round(old_limit, 2),
                    "new_limit": 0.0,
                    "action": "remove",
                },
            )

            return json.dumps({
                "proposal_id": proposal_id,
                "category": matched_cat,
                "old_limit": round(old_limit, 2),
                "new_limit": 0.0,
                "status": "pending_confirmation",
                "message": f"Proposal {proposal_id} created to remove category '{matched_cat}'. User confirmation in terminal required.",
            })

        # Action: Create new category
        if action_clean in ("add", "create", "new"):
            ok, clean_cat = validate_text(category)
            if not ok:
                return json.dumps({"error": str(clean_cat)})

            if matched_cat:
                return json.dumps({"error": f"Category '{matched_cat}' already exists in budgets. Use update to change its limit."})

            if new_limit is None:
                return json.dumps({"error": "new_limit is required to create a new category."})

            ok, limit_val = validate_amount(new_limit)
            if not ok:
                return json.dumps({"error": str(limit_val)})

            if limit_val < 1.0 or limit_val > 10000.0:
                return json.dumps({"error": f"New category budget limit must be between 1 and 10000, got {limit_val}."})

            risk = "low"
            preview = {"before": None, "after": round(limit_val, 2)}
            proposal_id = f"prop_{uuid.uuid4().hex[:8]}"

            proposal = store.create_proposal(
                kind="budget_change",
                payload={"category": clean_cat, "action": "add", "new_limit": round(limit_val, 2)},
                preview=preview,
                risk=risk,
                workspace=workspace_dir,
                proposal_id=proposal_id,
                category=clean_cat,
                old_limit=None,
                new_limit=round(limit_val, 2),
            )

            _sync_legacy_proposals(proposal_id, proposal)

            log_event(
                "budget_proposed",
                {
                    "proposal_id": proposal_id,
                    "category": clean_cat,
                    "old_limit": None,
                    "new_limit": round(limit_val, 2),
                    "action": "add",
                },
            )

            return json.dumps({
                "proposal_id": proposal_id,
                "category": clean_cat,
                "old_limit": None,
                "new_limit": round(limit_val, 2),
                "status": "pending_confirmation",
                "message": f"Proposal {proposal_id} created for {clean_cat}: new limit ${limit_val:.2f}. User confirmation in terminal required.",
            })

        # Update existing category (action_clean is None or 'update')
        if not matched_cat:
            return json.dumps({"error": f"Category '{category}' does not exist in budgets."})

        if new_limit is None:
            return json.dumps({"error": "new_limit is required to update budget limit."})

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
        risk = "low"
        preview = {"before": round(old_limit, 2), "after": round(limit_val, 2)}

        proposal = store.create_proposal(
            kind="budget_change",
            payload={"category": matched_cat, "action": "update", "new_limit": round(limit_val, 2)},
            preview=preview,
            risk=risk,
            workspace=workspace_dir,
            proposal_id=proposal_id,
            category=matched_cat,
            old_limit=round(old_limit, 2),
            new_limit=round(limit_val, 2),
        )

        _sync_legacy_proposals(proposal_id, proposal)

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


def get_most_used_categories(workspace: Any = None) -> list[str]:
    """Return workspace categories ordered by usage count in transactions.csv, descending."""
    ws_cats = get_workspace_categories(workspace=workspace)
    if not ws_cats:
        return ["Dining", "Groceries", "Transport", "Other"]

    if workspace is not None:
        tx_path = Path(workspace) / "transactions.csv"
    else:
        tx_path = _get_transactions_path()

    counts: dict[str, int] = {c: 0 for c in ws_cats}
    if tx_path.exists():
        try:
            df = pd.read_csv(tx_path)
            if "category" in df.columns:
                for c in df["category"].dropna():
                    c_clean = str(c).strip()
                    for known in ws_cats:
                        if known.lower() == c_clean.lower():
                            counts[known] = counts.get(known, 0) + 1
                            break
        except Exception:
            pass

    return sorted(ws_cats, key=lambda c: (-counts.get(c, 0), c.lower()))


def is_vague_amount(amount: Any) -> bool:
    """Return True if amount is missing or contains vague wording ('about 20', 'a few bucks')."""
    if amount is None:
        return True
    if isinstance(amount, (int, float, Decimal)) and not isinstance(amount, bool):
        return False
    s = str(amount).strip().lower()
    if not s:
        return True
    vague_markers = ["about", "few", "around", "approx", "roughly", "couple", "bucks", "some", "estimated", "maybe", "or so", "~"]
    if any(m in s for m in vague_markers):
        return True
    return False


def propose_add_transactions(items: list | str) -> str:
    """Propose adding up to 10 new transactions.

    Validates date, description, amount, category, and type with validators.py.
    Checks for missing/ambiguous fields and duplicate charges.
    Risk is 'low'. Does not write to data files.
    """
    try:
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                return json.dumps({"error": "Invalid JSON for items parameter.", "status": "error"})

        if not isinstance(items, list):
            return json.dumps({"error": "items must be a list of transaction objects.", "status": "error"})

        if len(items) == 0:
            return json.dumps({"error": "items list cannot be empty.", "status": "error"})

        if len(items) > 10:
            return json.dumps({"error": "Cannot propose more than 10 transactions at once.", "status": "error"})

        tx_path = _get_transactions_path()
        workspace_dir = tx_path.parent

        validated_items = []
        has_duplicate = False
        duplicate_warnings = []

        # Load existing transactions for duplicate detection
        existing_tx = []
        if tx_path.exists():
            try:
                df = pd.read_csv(tx_path)
                existing_tx = df.to_dict(orient="records")
            except Exception:
                existing_tx = []

        # Category grounding: if category is not stated in recent_user_text, discard it
        recent_text = store.get_recent_user_text()
        if recent_text is not None and recent_text.strip():
            for it in items:
                if isinstance(it, dict) and "category" in it:
                    raw_c = it.get("category")
                    if raw_c and not category_is_stated(raw_c, recent_text):
                        it["category"] = None

        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                return json.dumps({"error": f"Item at index {idx} must be a dictionary.", "status": "error"})

            # Description default: when the user gives no description, use "<Category> expense", never the bare category name
            desc = item.get("description")
            cat = item.get("category")
            if not desc or not str(desc).strip():
                if cat and str(cat).strip():
                    item["description"] = f"{str(cat).strip()} expense"
            elif cat and str(desc).strip().lower() == str(cat).strip().lower():
                item["description"] = f"{str(cat).strip()} expense"

            # 3. A missing date means the sandbox today.
            raw_date = item.get("date")
            if not raw_date or not str(raw_date).strip():
                try:
                    from src.store import get_sandbox_today
                    item["date"] = get_sandbox_today(workspace=workspace_dir)
                except Exception:
                    item["date"] = "2026-08-31"

            # 3. A vague amount ("about 20", "a few bucks") returns needs_clarification with "missing": ["amount"].
            raw_amount = item.get("amount")
            if is_vague_amount(raw_amount):
                return json.dumps({
                    "status": "needs_clarification",
                    "missing": ["amount"],
                    "options": [],
                    "message": f"Item {idx + 1} has a vague or missing amount: '{raw_amount}'. Please specify an exact amount.",
                })

            # 1. Category check: missing or matches more than one workspace category
            ws_cats = get_workspace_categories(workspace=workspace_dir)
            raw_cat = item.get("category")
            is_cat_missing = (raw_cat is None or not str(raw_cat).strip())

            is_cat_ambiguous = False
            if not is_cat_missing:
                cat_input = str(raw_cat).strip()
                cat_input = re.sub(r"\s*\(suggested\)$", "", cat_input, flags=re.I).strip()
                exact_m = [c for c in ws_cats if c.lower() == cat_input.lower()]
                if len(exact_m) == 1:
                    item["category"] = exact_m[0]
                else:
                    matching_cats = [
                        c for c in ws_cats
                        if cat_input.lower() in c.lower() or c.lower() in cat_input.lower()
                    ]
                    words = [w for w in re.split(r"[\s&/,]+", cat_input.lower()) if len(w) > 1]
                    word_matches = [
                        c for c in ws_cats
                        if any(w in c.lower() for w in words)
                    ]
                    combined = list(dict.fromkeys(matching_cats + word_matches))
                    if len(combined) > 1:
                        is_cat_ambiguous = True

            if is_cat_missing or is_cat_ambiguous:
                most_used = get_most_used_categories(workspace=workspace_dir)
                suggested = None
                if is_cat_missing:
                    suggested = suggest_category(item.get("description"), workspace=workspace_dir)

                if suggested:
                    first_opt = f"{suggested} (suggested)"
                    rest = [c for c in most_used if c.lower() != suggested.lower()]
                    options_list = [first_opt] + rest
                else:
                    options_list = most_used

                item_label = str(item.get("description") or f"Item {idx + 1}").strip().title()
                raw_amt = item.get("amount")
                try:
                    if raw_amt is not None:
                        f_amt = float(raw_amt)
                        amt_clean = int(f_amt) if f_amt.is_integer() else f_amt
                    else:
                        amt_clean = 0
                except Exception:
                    amt_clean = raw_amt

                pending = []
                for other_idx in range(idx + 1, len(items)):
                    other_it = items[other_idx]
                    if isinstance(other_it, dict):
                        other_c = other_it.get("category")
                        if other_c is None or not str(other_c).strip():
                            other_lbl = str(other_it.get("description") or f"Item {other_idx + 1}").strip().title()
                            pending.append(other_lbl)

                # Propose any valid items collected so far if not already pending
                created_p_id = None
                if validated_items:
                    try:
                        pending_props = store.list_pending(workspace=workspace_dir)
                    except Exception:
                        pending_props = []
                    existing_pending_items = []
                    for p in pending_props:
                        if p.get("kind") == "add_transactions":
                            p_items = (p.get("payload") or {}).get("items") or []
                            for pi in p_items:
                                existing_pending_items.append((
                                    str(pi.get("description", "")).strip().lower(),
                                    round(float(pi.get("amount", 0.0)), 2),
                                ))
                    items_to_propose = [
                        vi for vi in validated_items
                        if (str(vi.get("description", "")).strip().lower(), round(float(vi.get("amount", 0.0)), 2)) not in existing_pending_items
                    ]
                    if items_to_propose:
                        preview = {"before": None, "after": items_to_propose}
                        created_p_id = f"prop_{uuid.uuid4().hex[:8]}"
                        proposal = store.create_proposal(
                            kind="add_transactions",
                            payload={"items": items_to_propose},
                            preview=preview,
                            risk="low",
                            workspace=workspace_dir,
                            proposal_id=created_p_id,
                        )
                        _sync_legacy_proposals(created_p_id, proposal)
                        log_event("transactions_proposed", {"proposal_id": created_p_id, "count": len(items_to_propose), "risk": "low"})

                res = {
                    "status": "needs_clarification",
                    "missing": ["category"],
                    "item_label": item_label,
                    "amount": amt_clean,
                    "options": {"category": options_list},
                    "pending": pending,
                    "message": f"Which category for {item_label} (${amt_clean})?",
                }
                if created_p_id:
                    res["proposal_id"] = created_p_id
                return json.dumps(res)

            # Check other missing fields
            missing_fields = []
            for req in ("description", "type"):
                if req not in item or item[req] is None or (isinstance(item[req], str) and not item[req].strip()):
                    missing_fields.append(req)

            if missing_fields:
                options = {}
                if "type" in missing_fields:
                    options["type"] = ["expense", "income"]
                return json.dumps({
                    "status": "needs_clarification",
                    "missing": missing_fields,
                    "options": options,
                    "message": f"Item {idx + 1} is missing required fields: {', '.join(missing_fields)}.",
                })

            # Check ambiguous type
            raw_type = str(item["type"]).strip().lower()
            if raw_type not in ("expense", "income"):
                return json.dumps({
                    "status": "needs_clarification",
                    "missing": ["type"],
                    "options": {"type": ["expense", "income"]},
                    "message": f"Item {idx + 1} has ambiguous type '{item['type']}'. Must be 'expense' or 'income'.",
                })

            # Validate amount with validators.py
            ok, amt_val = validate_amount(item["amount"])
            if not ok:
                return json.dumps({"error": str(amt_val), "status": "error"})

            # Validate date with validators.py
            ok, date_val = validate_date(item["date"], workspace=workspace_dir)
            if not ok:
                return json.dumps({"error": str(date_val), "status": "error"})

            # Validate category with validators.py
            ok, cat_val = validate_category(item["category"], workspace=workspace_dir)
            if not ok:
                return json.dumps({"error": str(cat_val), "status": "error"})

            # Validate description with validators.py
            ok, desc_val = validate_text(item["description"])
            if not ok:
                return json.dumps({"error": str(desc_val), "status": "error"})

            # 2. Duplicate check: if a probable duplicate exists (same amount and description, dates within 1 day)
            dup_answer = item.get("duplicate_confirm")
            if str(dup_answer).strip().lower() in ("cancel", "no"):
                return json.dumps({
                    "status": "cancelled",
                    "message": "Transaction addition cancelled.",
                })

            has_duplicate_match = False
            for existing in existing_tx:
                e_date_str = str(existing.get("date", "")).strip()[:10]
                e_desc = str(existing.get("description", "")).strip().lower()
                try:
                    e_amt = float(existing.get("amount", 0.0))
                except (ValueError, TypeError):
                    e_amt = None

                if e_amt is not None and abs(e_amt - amt_val) < 0.001 and e_desc == desc_val.strip().lower():
                    try:
                        d1 = datetime.strptime(e_date_str, "%Y-%m-%d").date()
                        d2 = datetime.strptime(date_val[:10], "%Y-%m-%d").date()
                        if abs((d1 - d2).days) <= 1:
                            has_duplicate_match = True
                            break
                    except Exception:
                        pass

            if has_duplicate_match:
                if str(dup_answer).strip().lower() in ("add anyway", "add", "yes", "true"):
                    has_duplicate = True
                    duplicate_warnings.append(f"Transaction on {date_val} for '{desc_val}' (${amt_val:.2f}) matches existing record.")
                else:
                    return json.dumps({
                        "status": "needs_clarification",
                        "missing": ["duplicate_confirm"],
                        "options": ["Add anyway", "Cancel"],
                        "message": f"A probable duplicate transaction was found for '{desc_val}' (${amt_val:.2f}) on or around {date_val}. Do you want to add it anyway?",
                    })

            validated_item = {
                "date": date_val,
                "description": desc_val,
                "amount": amt_val,
                "category": cat_val,
                "type": raw_type,
            }
            validated_items.append(validated_item)

        try:
            pending_props = store.list_pending(workspace=workspace_dir)
        except Exception:
            pending_props = []
        existing_pending_items = []
        for p in pending_props:
            if p.get("kind") == "add_transactions":
                p_items = (p.get("payload") or {}).get("items") or []
                for pi in p_items:
                    existing_pending_items.append((
                        str(pi.get("description", "")).strip().lower(),
                        round(float(pi.get("amount", 0.0)), 2),
                    ))
        unproposed_items = [
            vi for vi in validated_items
            if (str(vi.get("description", "")).strip().lower(), round(float(vi.get("amount", 0.0)), 2)) not in existing_pending_items
        ]
        items_to_save = unproposed_items if unproposed_items else validated_items

        preview = {
            "before": None,
            "after": items_to_save,
        }
        if has_duplicate:
            preview["possible_duplicate"] = True
            preview["warning"] = "Possible duplicate of existing transaction."
            if duplicate_warnings:
                preview["duplicate_warnings"] = duplicate_warnings

        proposal_id = f"prop_{uuid.uuid4().hex[:8]}"
        proposal = store.create_proposal(
            kind="add_transactions",
            payload={"items": items_to_save},
            preview=preview,
            risk="low",
            workspace=workspace_dir,
            proposal_id=proposal_id,
        )

        _sync_legacy_proposals(proposal_id, proposal)

        log_event("transactions_proposed", {"proposal_id": proposal_id, "count": len(validated_items), "risk": "low"})

        return json.dumps({
            "proposal_id": proposal_id,
            "kind": "add_transactions",
            "items": validated_items,
            "preview": preview,
            "risk": "low",
            "status": "pending_confirmation",
            "message": f"Proposal {proposal_id} created to add {len(validated_items)} transaction(s).",
        })
    except Exception as e:
        return json.dumps({"error": str(e), "status": "error"})


def propose_update_transaction(transaction_id: str, fields: dict | str) -> str:
    """Propose an update to an existing transaction.

    Fields may include amount, category, date, and description.
    Preview shows old and new values.
    Risk is 'low', or 'high' if amount changes by >500.
    """
    try:
        if isinstance(fields, str):
            try:
                fields = json.loads(fields)
            except Exception:
                return json.dumps({"error": "Invalid JSON for fields parameter.", "status": "error"})

        if not isinstance(fields, dict) or not fields:
            return json.dumps({"error": "fields must be a non-empty dictionary.", "status": "error"})

        tx_path = _get_transactions_path()
        workspace_dir = tx_path.parent

        if not tx_path.exists():
            return json.dumps({"error": "Transactions file not found.", "status": "error"})

        tx_df = store.read_csv("transactions.csv", data_dir=workspace_dir)
        if "id" not in tx_df.columns:
            tx_df = store.ensure_transaction_ids(tx_df)

        matched_rows = tx_df[tx_df["id"].astype(str) == str(transaction_id).strip()]
        if matched_rows.empty:
            return json.dumps({"error": f"Transaction '{transaction_id}' not found.", "status": "error"})

        old_row = matched_rows.iloc[0].to_dict()
        # Clean nan values
        old_row = {k: ("" if pd.isna(v) else v) for k, v in old_row.items()}
        validated_fields = {}

        # Validate amount if present
        if "amount" in fields:
            ok, amt_val = validate_amount(fields["amount"])
            if not ok:
                return json.dumps({"error": str(amt_val), "status": "error"})
            validated_fields["amount"] = amt_val

        # Validate date if present
        if "date" in fields:
            ok, date_val = validate_date(fields["date"], workspace=workspace_dir)
            if not ok:
                return json.dumps({"error": str(date_val), "status": "error"})
            validated_fields["date"] = date_val
            if "month" in old_row:
                validated_fields["month"] = date_val[:7]

        # Validate category if present
        if "category" in fields:
            cat_input = fields["category"]
            recent_text = store.get_recent_user_text()
            if recent_text is not None and recent_text.strip():
                if cat_input and not category_is_stated(cat_input, recent_text):
                    del fields["category"]
                    item_label = str(old_row.get("description") or "Transaction").strip().title()
                    raw_amt = fields.get("amount") if "amount" in fields else old_row.get("amount", 0.0)
                    try:
                        f_amt = float(raw_amt)
                        amt_clean = int(f_amt) if f_amt.is_integer() else f_amt
                    except Exception:
                        amt_clean = raw_amt

                    suggested = suggest_category(old_row.get("description"), workspace=workspace_dir)
                    most_used = get_most_used_categories(workspace=workspace_dir)
                    if suggested:
                        first_opt = f"{suggested} (suggested)"
                        rest = [c for c in most_used if c.lower() != suggested.lower()]
                        options_list = [first_opt] + rest
                    else:
                        options_list = most_used

                    return json.dumps({
                        "status": "needs_clarification",
                        "missing": ["category"],
                        "item_label": item_label,
                        "amount": amt_clean,
                        "options": {"category": options_list},
                        "pending": [],
                        "message": f"Which category for {item_label} (${amt_clean})?",
                    })

            if "category" in fields:
                ok, cat_val = validate_category(fields["category"], workspace=workspace_dir)
                if not ok:
                    return json.dumps({"error": str(cat_val), "status": "error"})
                validated_fields["category"] = cat_val

        # Validate description if present
        if "description" in fields:
            ok, desc_val = validate_text(fields["description"])
            if not ok:
                return json.dumps({"error": str(desc_val), "status": "error"})
            validated_fields["description"] = desc_val

        if not validated_fields:
            return json.dumps({"error": "No valid fields provided to update.", "status": "error"})

        # Risk assessment: low, or high if amount changes by > 500
        risk = "low"
        if "amount" in validated_fields:
            try:
                old_amount = float(old_row.get("amount", 0.0))
                new_amount = float(validated_fields["amount"])
                if abs(new_amount - old_amount) > 500.0:
                    risk = "high"
            except (ValueError, TypeError):
                pass

        new_row = dict(old_row)
        new_row.update(validated_fields)

        preview = {
            "before": old_row,
            "after": new_row,
        }

        proposal_id = f"prop_{uuid.uuid4().hex[:8]}"
        proposal = store.create_proposal(
            kind="update_transaction",
            payload={"transaction_id": str(transaction_id).strip(), "fields": validated_fields},
            preview=preview,
            risk=risk,
            workspace=workspace_dir,
            proposal_id=proposal_id,
        )

        _sync_legacy_proposals(proposal_id, proposal)

        log_event("transaction_update_proposed", {"proposal_id": proposal_id, "transaction_id": transaction_id, "risk": risk})

        return json.dumps({
            "proposal_id": proposal_id,
            "kind": "update_transaction",
            "transaction_id": str(transaction_id).strip(),
            "preview": preview,
            "risk": risk,
            "status": "pending_confirmation",
            "message": f"Proposal {proposal_id} created to update transaction {transaction_id}.",
        })
    except Exception as e:
        return json.dumps({"error": str(e), "status": "error"})


def propose_delete_transaction(transaction_id: str) -> str:
    """Propose deletion of a transaction. Risk is 'high'."""
    try:
        tx_path = _get_transactions_path()
        workspace_dir = tx_path.parent

        if not tx_path.exists():
            return json.dumps({"error": "Transactions file not found.", "status": "error"})

        tx_df = store.read_csv("transactions.csv", data_dir=workspace_dir)
        if "id" not in tx_df.columns:
            tx_df = store.ensure_transaction_ids(tx_df)

        matched_rows = tx_df[tx_df["id"].astype(str) == str(transaction_id).strip()]
        if matched_rows.empty:
            return json.dumps({"error": f"Transaction '{transaction_id}' not found.", "status": "error"})

        old_row = matched_rows.iloc[0].to_dict()
        old_row = {k: ("" if pd.isna(v) else v) for k, v in old_row.items()}

        preview = {
            "before": old_row,
            "after": None,
        }

        proposal_id = f"prop_{uuid.uuid4().hex[:8]}"
        proposal = store.create_proposal(
            kind="delete_transaction",
            payload={"transaction_id": str(transaction_id).strip()},
            preview=preview,
            risk="high",
            workspace=workspace_dir,
            proposal_id=proposal_id,
        )

        _sync_legacy_proposals(proposal_id, proposal)

        log_event("transaction_delete_proposed", {"proposal_id": proposal_id, "transaction_id": transaction_id, "risk": "high"})

        return json.dumps({
            "proposal_id": proposal_id,
            "kind": "delete_transaction",
            "transaction_id": str(transaction_id).strip(),
            "preview": preview,
            "risk": "high",
            "status": "pending_confirmation",
            "message": f"Proposal {proposal_id} created to delete transaction {transaction_id}.",
        })
    except Exception as e:
        return json.dumps({"error": str(e), "status": "error"})


def propose_bill_change(
    action: str,
    bill_name: str,
    amount: float | None = None,
    due_day: int | None = None,
    category: str | None = None,
    new_bill_name: str | None = None,
) -> str:
    """Propose adding, editing, or cancelling a recurring bill.

    Actions:
      - 'add': requires bill_name, amount, due_day, category. Risk: 'low'.
      - 'edit': requires bill_name, plus any updated fields. Risk: 'low'.
      - 'cancel': requires bill_name. Risk: 'high'.
    """
    try:
        action_clean = str(action).strip().lower()
        if action_clean not in ("add", "edit", "cancel"):
            return json.dumps({
                "error": f"Invalid action '{action}'. Must be 'add', 'edit', or 'cancel'.",
                "status": "error",
            })

        bills_path = _get_bills_path()
        workspace_dir = bills_path.parent

        if not bills_path.exists():
            return json.dumps({"error": "Bills file not found.", "status": "error"})

        bills_df = store.read_csv("bills.csv", data_dir=workspace_dir)

        def find_bill(name: str):
            clean_name = str(name).strip().lower()
            for idx, r in bills_df.iterrows():
                if str(r.get("bill_name", "")).strip().lower() == clean_name:
                    d = r.to_dict()
                    return {k: ("" if pd.isna(v) else v) for k, v in d.items()}
            return None

        if action_clean == "add":
            ok, clean_bill_name = validate_text(bill_name)
            if not ok:
                return json.dumps({"error": str(clean_bill_name), "status": "error"})

            if amount is None:
                return json.dumps({"error": "amount is required to add a bill.", "status": "error"})
            ok, amt_val = validate_amount(amount)
            if not ok:
                return json.dumps({"error": str(amt_val), "status": "error"})

            if due_day is None:
                return json.dumps({"error": "due_day is required to add a bill.", "status": "error"})
            try:
                day_val = int(due_day)
            except (ValueError, TypeError):
                return json.dumps({"error": f"due_day '{due_day}' must be an integer between 1 and 31.", "status": "error"})
            if day_val < 1 or day_val > 31:
                return json.dumps({"error": f"due_day must be between 1 and 31, got {day_val}.", "status": "error"})

            if not category:
                return json.dumps({"error": "category is required to add a bill.", "status": "error"})
            ok, cat_val = validate_category(category, workspace=workspace_dir)
            if not ok:
                return json.dumps({"error": str(cat_val), "status": "error"})

            new_bill = {
                "bill_name": clean_bill_name,
                "amount": amt_val,
                "due_day": day_val,
                "category": cat_val,
            }
            preview = {"before": None, "after": new_bill}
            risk = "low"
            payload = {"action": "add", "bill": new_bill}

        elif action_clean == "edit":
            old_bill = find_bill(bill_name)
            if not old_bill:
                return json.dumps({"error": f"Bill '{bill_name}' not found.", "status": "error"})

            updated_bill = dict(old_bill)
            if new_bill_name is not None:
                ok, clean_name = validate_text(new_bill_name)
                if not ok:
                    return json.dumps({"error": str(clean_name), "status": "error"})
                updated_bill["bill_name"] = clean_name

            if amount is not None:
                ok, amt_val = validate_amount(amount)
                if not ok:
                    return json.dumps({"error": str(amt_val), "status": "error"})
                updated_bill["amount"] = amt_val

            if due_day is not None:
                try:
                    day_val = int(due_day)
                except (ValueError, TypeError):
                    return json.dumps({"error": f"due_day '{due_day}' must be an integer between 1 and 31.", "status": "error"})
                if day_val < 1 or day_val > 31:
                    return json.dumps({"error": f"due_day must be between 1 and 31, got {day_val}.", "status": "error"})
                updated_bill["due_day"] = day_val

            if category is not None:
                ok, cat_val = validate_category(category, workspace=workspace_dir)
                if not ok:
                    return json.dumps({"error": str(cat_val), "status": "error"})
                updated_bill["category"] = cat_val

            preview = {"before": old_bill, "after": updated_bill}
            risk = "low"
            payload = {"action": "edit", "bill_name": str(bill_name).strip(), "changes": updated_bill}

        else:  # cancel
            old_bill = find_bill(bill_name)
            if not old_bill:
                return json.dumps({"error": f"Bill '{bill_name}' not found.", "status": "error"})

            preview = {"before": old_bill, "after": None}
            risk = "high"
            payload = {"action": "cancel", "bill_name": str(bill_name).strip()}

        proposal_id = f"prop_{uuid.uuid4().hex[:8]}"
        proposal = store.create_proposal(
            kind="bill_change",
            payload=payload,
            preview=preview,
            risk=risk,
            workspace=workspace_dir,
            proposal_id=proposal_id,
        )

        _sync_legacy_proposals(proposal_id, proposal)

        log_event("bill_change_proposed", {"proposal_id": proposal_id, "action": action_clean, "risk": risk})

        return json.dumps({
            "proposal_id": proposal_id,
            "kind": "bill_change",
            "action": action_clean,
            "preview": preview,
            "risk": risk,
            "status": "pending_confirmation",
            "message": f"Proposal {proposal_id} created to {action_clean} bill '{bill_name}'.",
        })
    except Exception as e:
        return json.dumps({"error": str(e), "status": "error"})


def revise_proposal(proposal_id: str, fields: dict | str | None = None, **kwargs) -> str:
    """Revise an existing pending, unexpired proposal before approval (e.g. 'no, make it 40 instead').

    Edits only a pending, unexpired proposal. Re-runs validation on all updated fields,
    resets expires_at to 24 hours later, and does not apply anything. Returns before and after preview.
    If the proposal is expired or already applied, returns an error and suggests a new proposal.
    """
    try:
        if fields is None:
            fields = {}
        elif isinstance(fields, str):
            try:
                fields = json.loads(fields)
            except Exception:
                fields = {}

        if isinstance(fields, dict):
            fields.update(kwargs)
        else:
            fields = dict(kwargs)

        if not isinstance(fields, dict):
            return json.dumps({"error": "fields must be a dictionary of field-value pairs.", "status": "error"})

        p_path = _get_budgets_path()
        workspace_dir = p_path.parent

        proposals = store.read_proposals(workspace=workspace_dir)
        p_id = str(proposal_id).strip()
        if p_id not in proposals:
            try:
                audit_records = store.read_audit(workspace=workspace_dir)
                for r in audit_records:
                    if r.get("proposal_id") == p_id or r.get("proposal_id") == str(proposal_id):
                        return json.dumps({
                            "error": f"Proposal '{proposal_id}' has already been applied and cannot be revised. Please create a new proposal instead.",
                            "status": "error",
                        })
            except Exception:
                pass
            return json.dumps({"error": f"Proposal '{proposal_id}' not found.", "status": "error"})

        proposal = proposals[p_id]
        status = proposal.get("status")
        if status == "applied":
            return json.dumps({
                "error": f"Proposal '{proposal_id}' has already been applied and cannot be revised. Please create a new proposal instead.",
                "status": "error",
            })
        if status == "expired":
            return json.dumps({
                "error": f"Proposal '{proposal_id}' has expired and cannot be revised. Please create a new proposal instead.",
                "status": "error",
            })
        if status != "pending_confirmation":
            return json.dumps({
                "error": f"Proposal '{proposal_id}' is not pending (status: {status}). Please create a new proposal instead.",
                "status": "error",
            })

        expires_at = proposal.get("expires_at")
        now = datetime.now()
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at)
                if now >= exp_dt:
                    proposal["status"] = "expired"
                    store.save_proposal(proposal, workspace=workspace_dir)
                    _sync_legacy_proposals(p_id, proposal)
                    return json.dumps({
                        "error": f"Proposal '{proposal_id}' has expired and cannot be revised. Please create a new proposal instead.",
                        "status": "error",
                    })
            except Exception:
                pass

        kind = proposal.get("kind")
        payload = proposal.get("payload", {})
        preview = proposal.get("preview") or {}
        if not isinstance(preview, dict):
            preview = {}

        # Category grounding: if category is not stated in recent_user_text, discard it and treat as missing
        if "category" in fields and fields["category"] is not None:
            cat_input = fields["category"]
            recent_text = store.get_recent_user_text()
            if recent_text is not None and recent_text.strip():
                if cat_input and not category_is_stated(cat_input, recent_text):
                    del fields["category"]
                    if kind == "add_transactions":
                        p_items = payload.get("items", [])
                        f_it = p_items[0] if p_items else {}
                        item_label = str(f_it.get("description") or "Item").strip().title()
                        raw_amt = f_it.get("amount", 0.0)
                    elif kind == "update_transaction":
                        f_fields = payload.get("fields", {})
                        item_label = str(f_fields.get("description") or "Transaction").strip().title()
                        raw_amt = f_fields.get("amount", 0.0)
                    else:
                        item_label = str(proposal.get("category") or "Budget").strip().title()
                        raw_amt = proposal.get("new_limit") or proposal.get("old_limit", 0.0)

                    try:
                        f_amt = float(raw_amt)
                        amt_clean = int(f_amt) if f_amt.is_integer() else f_amt
                    except Exception:
                        amt_clean = raw_amt

                    suggested = suggest_category(item_label, workspace=workspace_dir)
                    most_used = get_most_used_categories(workspace=workspace_dir)
                    if suggested:
                        first_opt = f"{suggested} (suggested)"
                        rest = [c for c in most_used if c.lower() != suggested.lower()]
                        options_list = [first_opt] + rest
                    else:
                        options_list = most_used

                    return json.dumps({
                        "status": "needs_clarification",
                        "missing": ["category"],
                        "item_label": item_label,
                        "amount": amt_clean,
                        "options": {"category": options_list},
                        "pending": [],
                        "message": f"Which category for {item_label} (${amt_clean})?",
                    })

        if kind == "budget_change":
            before_val = preview.get("after") if preview.get("after") is not None else proposal.get("new_limit")
            if before_val is None:
                before_val = proposal.get("old_limit")

            if "category" in fields and fields["category"] is not None:
                ok, cat_val = validate_category(fields["category"], workspace=workspace_dir)
                if not ok:
                    return json.dumps({"error": str(cat_val), "status": "error"})
                proposal["category"] = cat_val
                payload["category"] = cat_val
                if proposal.get("action") != "add":
                    budgets = store.read_json("budgets.json", workspace=workspace_dir)
                    old_limit = float(budgets.get(cat_val, 0.0))
                    proposal["old_limit"] = old_limit
                    payload["old_limit"] = old_limit

            amt = None
            for k in ("new_limit", "amount", "limit"):
                if k in fields and fields[k] is not None:
                    amt = fields[k]
                    break
            if amt is not None:
                ok, amt_val = validate_amount(amt)
                if not ok:
                    return json.dumps({"error": str(amt_val), "status": "error"})
                action = proposal.get("action") or payload.get("action", "change")
                if action == "add":
                    if amt_val < 1.0 or amt_val > 10000.0:
                        return json.dumps({
                            "error": "New category budget limit must be between $1.00 and $10,000.00.",
                            "status": "error",
                        })
                else:
                    old_limit = float(proposal.get("old_limit") or payload.get("old_limit", 0.0))
                    max_allowed = round(old_limit * 2.0, 2)
                    if amt_val > max_allowed:
                        return json.dumps({
                            "status": "rejected",
                            "error": f"Requested limit ${amt_val:.2f} exceeds twice the current limit (${old_limit:.2f}). Maximum allowed is ${max_allowed:.2f}.",
                            "category": proposal.get("category"),
                            "current_limit": old_limit,
                            "maximum_allowed": max_allowed,
                        })
                proposal["new_limit"] = amt_val
                payload["new_limit"] = amt_val
                preview["before"] = before_val
                preview["after"] = amt_val
            else:
                preview["before"] = before_val
                preview["after"] = proposal.get("new_limit")

        elif kind == "add_transactions":
            items = payload.get("items", [])
            import copy
            before_items = copy.deepcopy(items)
            for it in items:
                for k, v in fields.items():
                    if k in ("amount", "limit"):
                        ok, val = validate_amount(v)
                        if not ok: return json.dumps({"error": str(val), "status": "error"})
                        it["amount"] = val
                    elif k == "date":
                        res_d = resolve_period(v)
                        if isinstance(res_d, str):
                            v = res_d
                        ok, val = validate_date(v, workspace=workspace_dir)
                        if not ok: return json.dumps({"error": str(val), "status": "error"})
                        it["date"] = val
                        it["month"] = str(val)[:7]
                    elif k == "category":
                        ok, val = validate_category(v, workspace=workspace_dir)
                        if not ok: return json.dumps({"error": str(val), "status": "error"})
                        it["category"] = val
                    elif k == "description":
                        ok, val = validate_text(v)
                        if not ok: return json.dumps({"error": str(val), "status": "error"})
                        it["description"] = val
                    elif k == "type":
                        if str(v).lower() not in ("expense", "income"):
                            return json.dumps({"error": f"Invalid type '{v}'. Must be expense or income.", "status": "error"})
                        it["type"] = str(v).lower()
            payload["items"] = items
            preview["before"] = before_items
            preview["after"] = items

        elif kind == "update_transaction":
            current_fields = payload.get("fields", {})
            import copy
            before_fields = copy.deepcopy(current_fields)
            for k, v in fields.items():
                if k in ("amount", "limit"):
                    ok, val = validate_amount(v)
                    if not ok: return json.dumps({"error": str(val), "status": "error"})
                    current_fields["amount"] = val
                elif k == "date":
                    res_d = resolve_period(v)
                    if isinstance(res_d, str):
                        v = res_d
                    ok, val = validate_date(v, workspace=workspace_dir)
                    if not ok: return json.dumps({"error": str(val), "status": "error"})
                    current_fields["date"] = val
                elif k == "category":
                    ok, val = validate_category(v, workspace=workspace_dir)
                    if not ok: return json.dumps({"error": str(val), "status": "error"})
                    current_fields["category"] = val
                elif k == "description":
                    ok, val = validate_text(v)
                    if not ok: return json.dumps({"error": str(val), "status": "error"})
                    current_fields["description"] = val
            payload["fields"] = current_fields
            if isinstance(preview, dict) and isinstance(preview.get("after"), dict):
                preview["after"].update(current_fields)
            preview["before"] = before_fields
            # Re-evaluate risk
            orig_row = preview.get("before", {}) if isinstance(preview, dict) else {}
            orig_amt = float(orig_row.get("amount", 0.0)) if isinstance(orig_row, dict) else 0.0
            new_amt = float(current_fields.get("amount", orig_amt))
            proposal["risk"] = "high" if abs(new_amt - orig_amt) > 500 else "low"

        elif kind == "bill_change":
            bill_data = payload.get("bill", {}) if isinstance(payload.get("bill"), dict) else payload
            import copy
            before_bill = copy.deepcopy(bill_data)
            for k, v in fields.items():
                if k in ("amount", "limit"):
                    ok, val = validate_amount(v)
                    if not ok: return json.dumps({"error": str(val), "status": "error"})
                    bill_data["amount"] = val
                elif k == "category":
                    ok, val = validate_category(v, workspace=workspace_dir)
                    if not ok: return json.dumps({"error": str(val), "status": "error"})
                    bill_data["category"] = val
                elif k in ("bill_name", "description"):
                    ok, val = validate_text(v)
                    if not ok: return json.dumps({"error": str(val), "status": "error"})
                    bill_data["bill_name"] = val
                elif k in ("due_day", "date"):
                    try:
                        if isinstance(v, str) and "-" in v:
                            day = int(v.split("-")[-1])
                        else:
                            day = int(v)
                        if day < 1 or day > 31:
                            return json.dumps({"error": f"due_day must be between 1 and 31.", "status": "error"})
                        bill_data["due_day"] = day
                    except Exception:
                        return json.dumps({"error": f"Invalid due_day '{v}'.", "status": "error"})
            if isinstance(preview, dict) and isinstance(preview.get("after"), dict):
                preview["after"].update(bill_data)
            preview["before"] = before_bill

        # Reset expires_at to 24 hours later
        new_expires = (datetime.now() + timedelta(hours=24)).isoformat()
        proposal["expires_at"] = new_expires
        proposal["payload"] = payload
        proposal["preview"] = preview

        store.save_proposal(proposal, workspace=workspace_dir)
        _sync_legacy_proposals(p_id, proposal)

        log_event(
            "proposal_revised",
            {
                "proposal_id": p_id,
                "kind": kind,
                "expires_at": new_expires,
                "risk": proposal.get("risk", "low"),
            },
        )

        return json.dumps({
            "status": "pending_confirmation",
            "proposal_id": p_id,
            "preview": preview,
            "risk": proposal.get("risk", "low"),
            "expires_at": new_expires,
            "message": f"Proposal {p_id} revised successfully.",
        })
    except Exception as e:
        return json.dumps({"error": str(e), "status": "error"})


def cashflow_projection(days_ahead: int = 30, today: str | None = None) -> str:
    """Project day-by-day cashflow, scheduled bills, expected income, and simulated balance over a forward horizon."""
    try:
        if today is not None and str(today).strip():
            resolved_today = resolve_period(today)
            if isinstance(resolved_today, str):
                today = resolved_today

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
            max_day = calendar.monthrange(target_dt.year, target_dt.month)[1]
            for _, row in bills_df.iterrows():
                try:
                    raw_day = int(row["due_day"])
                except (ValueError, TypeError):
                    continue
                clamped_day = min(raw_day, max_day)
                if clamped_day == target_dt.day:
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

        res = {
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
        }
        return json.dumps(truncate_tool_result(res))

    except Exception as e:
        return json.dumps({"error": str(e)})


def detect_spending_spikes(month: str) -> str:
    """Compare each expense category with the previous month and flag spikes (>50% increase AND >=$50 absolute increase)."""
    try:
        resolved = resolve_period(month)
        if isinstance(resolved, dict):
            return json.dumps(resolved)
        month = resolved[:7] if (len(resolved) == 10 and resolved[4] == "-" and resolved[7] == "-") else resolved

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
        resolved = resolve_period(month)
        if isinstance(resolved, dict):
            return json.dumps(resolved)
        month = resolved[:7] if (len(resolved) == 10 and resolved[4] == "-" and resolved[7] == "-") else resolved

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

        res = {
            "month": month,
            "item_count": len(items),
            "recommendations": items,
            "total_potential_saving": total_potential_saving,
            "disclaimer": disclaimer,
        }
        return json.dumps(truncate_tool_result(res))

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
    "description": "Proposes a change to a budget category limit, creates a new category, or removes a category. Does not apply the change; generates a pending proposal that requires user confirmation in the terminal. Arguments: category (string), new_limit (optional number for add/update), action (optional string: 'update', 'add', 'remove'). Result: JSON containing proposal_id, category, old_limit, and new_limit.",
    "parameters": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "The budget category name (e.g., 'Dining', or a new category name).",
            },
            "new_limit": {
                "type": "number",
                "description": "The proposed monthly spending limit in USD (must be between 1 and 10000 for new category, or > 0 for update).",
            },
            "action": {
                "type": "string",
                "description": "Action type: 'update' (default, changes existing category limit), 'add' (creates new category with limit between 1 and 10000), or 'remove' (removes category).",
                "enum": ["update", "add", "remove"],
            },
        },
        "required": ["category"],
    },
}

PROPOSE_ADD_TRANSACTIONS_SCHEMA = {
    "name": "propose_add_transactions",
    "description": "Proposes adding up to 10 new transactions. Validates date, description, amount, category, and type (expense or income). Checks for missing/ambiguous fields and duplicate charges. Does not write to data files; creates a pending proposal requiring user confirmation. Arguments: items (list of transaction objects).",
    "parameters": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "List of up to 10 transaction objects to propose.",
                "items": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Transaction date in YYYY-MM-DD ISO format.",
                        },
                        "description": {
                            "type": "string",
                            "description": "Description of the transaction.",
                        },
                        "amount": {
                            "type": "number",
                            "description": "Transaction amount in USD (positive number, up to 2 decimal places).",
                        },
                        "category": {
                            "type": "string",
                            "description": "Transaction category (must exist in workspace categories).",
                        },
                        "type": {
                            "type": "string",
                            "description": "Transaction type: 'expense' or 'income'.",
                            "enum": ["expense", "income"],
                        },
                    },
                    "required": ["date", "description", "amount", "category", "type"],
                },
            },
        },
        "required": ["items"],
    },
}

PROPOSE_UPDATE_TRANSACTION_SCHEMA = {
    "name": "propose_update_transaction",
    "description": "Proposes updating fields of an existing transaction (amount, category, date, description). Preview shows old and new values. Risk is low, or high if amount changes by >500. Does not write to data files; creates a pending proposal requiring user confirmation. Arguments: transaction_id (string), fields (object).",
    "parameters": {
        "type": "object",
        "properties": {
            "transaction_id": {
                "type": "string",
                "description": "The unique ID of the transaction to update.",
            },
            "fields": {
                "type": "object",
                "description": "Fields to update: may include amount, category, date, and description.",
                "properties": {
                    "amount": {
                        "type": "number",
                        "description": "Updated amount in USD.",
                    },
                    "category": {
                        "type": "string",
                        "description": "Updated category name.",
                    },
                    "date": {
                        "type": "string",
                        "description": "Updated date in YYYY-MM-DD format.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Updated description text.",
                    },
                },
            },
        },
        "required": ["transaction_id", "fields"],
    },
}

PROPOSE_DELETE_TRANSACTION_SCHEMA = {
    "name": "propose_delete_transaction",
    "description": "Proposes deleting an existing transaction by ID. High-risk operation. Does not write to data files; creates a pending proposal requiring user confirmation. Arguments: transaction_id (string).",
    "parameters": {
        "type": "object",
        "properties": {
            "transaction_id": {
                "type": "string",
                "description": "The unique ID of the transaction to delete.",
            },
        },
        "required": ["transaction_id"],
    },
}

PROPOSE_BILL_CHANGE_SCHEMA = {
    "name": "propose_bill_change",
    "description": "Proposes adding, editing, or cancelling a recurring bill. Risk is low for add/edit, high for cancel. Does not write to data files; creates a pending proposal requiring user confirmation. Arguments: action ('add', 'edit', 'cancel'), bill_name (string), plus optional amount, due_day, category, new_bill_name.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Action to perform: 'add', 'edit', or 'cancel'.",
                "enum": ["add", "edit", "cancel"],
            },
            "bill_name": {
                "type": "string",
                "description": "Name of the bill (for add, the new bill name; for edit/cancel, the existing bill name).",
            },
            "amount": {
                "type": "number",
                "description": "Monthly bill amount in USD (required for 'add', optional for 'edit').",
            },
            "due_day": {
                "type": "integer",
                "description": "Day of the month the bill is due (1-31; required for 'add', optional for 'edit').",
            },
            "category": {
                "type": "string",
                "description": "Category for the bill (required for 'add', optional for 'edit').",
            },
            "new_bill_name": {
                "type": "string",
                "description": "Optional new name for the bill when action is 'edit'.",
            },
        },
        "required": ["action", "bill_name"],
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

GET_DATA_OVERVIEW_SCHEMA = {
    "name": "get_data_overview",
    "description": "Returns high-level metadata about the available financial dataset, including the range of available months (first_month, last_month, months), expense categories, transaction count, bill count, budget categories, and the simulated sandbox today date.",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

REVISE_PROPOSAL_SCHEMA = {
    "name": "revise_proposal",
    "description": "Revise an existing pending, unexpired proposal before approval (e.g. 'no, make it 40 instead'). Edits proposal fields, re-validates, and resets the 24-hour expiration time. Does not apply anything. Arguments: proposal_id (string), fields (object of key-value pairs).",
    "parameters": {
        "type": "object",
        "properties": {
            "proposal_id": {
                "type": "string",
                "description": "The unique ID of the pending proposal to revise.",
            },
            "fields": {
                "type": "object",
                "description": "Key-value pairs of fields to update on the proposal (e.g. {'amount': 40.0} or {'new_limit': 400.0}).",
            },
        },
        "required": ["proposal_id", "fields"],
    },
}

def get_alerts(workspace: Path | str | None = None) -> str:
    """Fetch current financial alerts, warnings, and attention items (most urgent first)."""
    try:
        from src.alerts import get_alerts as _fetch_alerts
        alerts = _fetch_alerts(workspace=workspace)
        most_urgent = alerts[0] if alerts else None
        return json.dumps({
            "alerts": alerts,
            "count": len(alerts),
            "most_urgent": most_urgent,
        })
    except Exception as e:
        return json.dumps({"error": str(e), "alerts": []})


GET_ALERTS_SCHEMA = {
    "name": "get_alerts",
    "description": "Fetch current financial alerts, warnings, and items needing attention (most urgent first).",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

def list_goals(workspace: Path | str | None = None) -> str:
    """Read and return all active financial goals from the workspace."""
    try:
        goals = store.get_goals(workspace=workspace)
        return json.dumps({
            "goals": goals,
            "count": len(goals),
        })
    except Exception as e:
        return json.dumps({"error": str(e), "goals": [], "count": 0})


def get_goal_progress(goal_id: str, workspace: Path | str | None = None) -> str:
    """Calculate progress for a specific goal by ID.
    Returns percent_done, monthly_needed (target minus saved spread over remaining months from sandbox date),
    and on_track status. Text answers use plain numbers, with no IDs.
    """
    try:
        goals = store.get_goals(workspace=workspace)
        target_goal = None
        for g in goals:
            if str(g.get("id")) == str(goal_id).strip():
                target_goal = g
                break
        if not target_goal:
            return json.dumps({"error": f"Goal '{goal_id}' not found.", "status": "error"})

        target_amt = float(target_goal.get("target_amount", 0.0))
        saved_amt = float(target_goal.get("saved_so_far", 0.0))
        t_date_str = str(target_goal.get("target_date", "")).strip()

        # percent_done
        if target_amt <= 0:
            percent_done = 0.0
        else:
            percent_done = round((saved_amt / target_amt) * 100.0, 1)

        # remaining
        remaining = max(0.0, target_amt - saved_amt)

        # monthly_needed
        s_date_str = store.get_sandbox_today(workspace=workspace)
        try:
            s_date = date.fromisoformat(s_date_str)
            t_date = date.fromisoformat(t_date_str)
        except Exception:
            s_date = date(2026, 8, 31)
            t_date = date.fromisoformat(t_date_str) if t_date_str else s_date

        months_left = (t_date.year - s_date.year) * 12 + (t_date.month - s_date.month)
        if months_left <= 0:
            if t_date >= s_date:
                months_left = 1
            else:
                months_left = 0

        if months_left > 0:
            monthly_needed = round(remaining / months_left, 2)
        else:
            monthly_needed = round(remaining, 2)

        # on_track
        if saved_amt >= target_amt:
            on_track = True
        else:
            c_date_str = str(target_goal.get("created", s_date_str)).strip()[:10]
            try:
                c_date = date.fromisoformat(c_date_str)
            except Exception:
                c_date = s_date
            total_days = (t_date - c_date).days
            elapsed_days = (s_date - c_date).days
            if total_days <= 0:
                on_track = (saved_amt >= target_amt)
            elif elapsed_days <= 0:
                on_track = True
            else:
                expected_saved = (elapsed_days / total_days) * target_amt
                on_track = bool(saved_amt >= expected_saved)

        return json.dumps({
            "goal_name": target_goal.get("name", "Goal"),
            "target_amount": target_amt,
            "target_date": t_date_str,
            "saved_so_far": saved_amt,
            "percent_done": percent_done,
            "monthly_needed": monthly_needed,
            "months_left": months_left,
            "on_track": on_track,
        })
    except Exception as e:
        return json.dumps({"error": str(e), "status": "error"})


def propose_goal(
    action: str,
    name: str | None = None,
    target_amount: float | None = None,
    target_date: str | None = None,
    saved_so_far: float | None = None,
    goal_id: str | None = None,
    workspace: Path | str | None = None,
) -> str:
    """Propose adding, updating, or deleting a savings goal.
    Actions:
      - 'add': requires name, target_amount, target_date. Optional saved_so_far. Risk is 'low' (needs 'yes').
      - 'update': requires goal_id, plus updated fields. Risk is 'low' (needs 'yes').
      - 'delete': requires goal_id. Risk is 'high' (needs 'CONFIRM').
    """
    try:
        from src.validators import validate_goal
        action_clean = str(action).strip().lower()
        if action_clean not in ("add", "update", "delete"):
            return json.dumps({
                "error": f"Invalid action '{action}'. Must be 'add', 'update', or 'delete'.",
                "status": "error",
            })

        target_dir = Path(workspace).resolve() if workspace is not None else store.get_data_dir()
        existing_goals = store.get_goals(workspace=target_dir)

        if action_clean == "delete":
            if not goal_id:
                if name:
                    target_goal = next((g for g in existing_goals if str(g.get("name", "")).strip().lower() == str(name).strip().lower()), None)
                    if target_goal:
                        goal_id = str(target_goal.get("id"))
                if not goal_id:
                    return json.dumps({"error": "Goal ID or name is required for deleting a goal.", "status": "error"})
            target_goal = next((g for g in existing_goals if str(g.get("id")) == str(goal_id).strip() or str(g.get("name", "")).strip().lower() == str(goal_id).strip().lower()), None)
            if not target_goal:
                return json.dumps({"error": f"Goal '{goal_id}' not found.", "status": "error"})
            goal_id = str(target_goal.get("id"))

            proposal_id = f"prop_{uuid.uuid4().hex[:8]}"
            preview = {
                "before": target_goal,
                "after": None,
            }
            proposal = store.create_proposal(
                kind="goal_change",
                payload={"action": "delete", "goal_id": str(goal_id).strip(), "name": target_goal.get("name")},
                preview=preview,
                risk="high",
                workspace=target_dir,
                proposal_id=proposal_id,
            )
            _sync_legacy_proposals(proposal_id, proposal)
            log_event("goal_delete_proposed", {"proposal_id": proposal_id, "goal_id": goal_id, "risk": "high"})
            return json.dumps({
                "proposal_id": proposal_id,
                "kind": "goal_change",
                "action": "delete",
                "goal_id": str(goal_id).strip(),
                "preview": preview,
                "risk": "high",
                "status": "pending_confirmation",
                "message": f"Proposal {proposal_id} created to delete goal '{target_goal.get('name')}'. High-risk proposal requires CONFIRM.",
            })

        elif action_clean == "add":
            goal_dict = {
                "name": name,
                "target_amount": target_amount,
                "target_date": target_date,
                "saved_so_far": saved_so_far if saved_so_far is not None else 0.0,
            }
            ok, clean_goal = validate_goal(goal_dict, workspace=target_dir, is_update=False)
            if not ok:
                return json.dumps({"error": clean_goal, "status": "error"})

            proposal_id = f"prop_{uuid.uuid4().hex[:8]}"
            preview = {
                "before": None,
                "after": clean_goal,
            }
            proposal = store.create_proposal(
                kind="goal_change",
                payload={"action": "add", "goal": clean_goal, "name": clean_goal["name"]},
                preview=preview,
                risk="low",
                workspace=target_dir,
                proposal_id=proposal_id,
            )
            _sync_legacy_proposals(proposal_id, proposal)
            log_event("goal_add_proposed", {"proposal_id": proposal_id, "name": clean_goal["name"], "risk": "low"})
            return json.dumps({
                "proposal_id": proposal_id,
                "kind": "goal_change",
                "action": "add",
                "goal": clean_goal,
                "preview": preview,
                "risk": "low",
                "status": "pending_confirmation",
                "message": f"Proposal {proposal_id} created to add goal '{clean_goal['name']}'.",
            })

        elif action_clean == "update":
            if not goal_id:
                return json.dumps({"error": "Goal ID is required for updating a goal.", "status": "error"})
            target_goal = next((g for g in existing_goals if str(g.get("id")) == str(goal_id).strip()), None)
            if not target_goal:
                return json.dumps({"error": f"Goal '{goal_id}' not found.", "status": "error"})

            updates = {}
            if name is not None:
                updates["name"] = name
            if target_amount is not None:
                updates["target_amount"] = target_amount
            if target_date is not None:
                updates["target_date"] = target_date
            if saved_so_far is not None:
                updates["saved_so_far"] = saved_so_far

            merged = dict(target_goal)
            merged.update(updates)
            ok, clean_goal = validate_goal(merged, workspace=target_dir, is_update=True)
            if not ok:
                return json.dumps({"error": clean_goal, "status": "error"})

            proposal_id = f"prop_{uuid.uuid4().hex[:8]}"
            preview = {
                "before": target_goal,
                "after": clean_goal,
            }
            proposal = store.create_proposal(
                kind="goal_change",
                payload={"action": "update", "goal_id": str(goal_id).strip(), "updates": clean_goal, "name": clean_goal["name"]},
                preview=preview,
                risk="low",
                workspace=target_dir,
                proposal_id=proposal_id,
            )
            _sync_legacy_proposals(proposal_id, proposal)
            log_event("goal_update_proposed", {"proposal_id": proposal_id, "goal_id": goal_id, "risk": "low"})
            return json.dumps({
                "proposal_id": proposal_id,
                "kind": "goal_change",
                "action": "update",
                "goal_id": str(goal_id).strip(),
                "preview": preview,
                "risk": "low",
                "status": "pending_confirmation",
                "message": f"Proposal {proposal_id} created to update goal '{clean_goal['name']}'.",
            })

    except Exception as e:
        return json.dumps({"error": str(e), "status": "error"})


def propose_preference_change(
    savings_target_percent: float | int | None = None,
    alert_bills_days: int | None = None,
    currency_label: str | None = None,
    preferences: dict | None = None,
    workspace: Path | str | None = None,
) -> str:
    """Propose changing user preferences (savings_target_percent, alert_bills_days, currency_label).
    Risk is 'low' (needs 'yes').
    """
    try:
        from src.validators import validate_preferences
        target_dir = Path(workspace).resolve() if workspace is not None else store.get_data_dir()
        old_prefs = store.get_preferences(workspace=target_dir)

        new_dict = dict(old_prefs)
        if isinstance(preferences, dict):
            new_dict.update(preferences)
        if savings_target_percent is not None:
            new_dict["savings_target_percent"] = savings_target_percent
        if alert_bills_days is not None:
            new_dict["alert_bills_days"] = alert_bills_days
        if currency_label is not None:
            new_dict["currency_label"] = currency_label

        ok, clean_prefs = validate_preferences(new_dict)
        if not ok:
            return json.dumps({"error": clean_prefs, "status": "error"})

        proposal_id = f"prop_{uuid.uuid4().hex[:8]}"
        preview = {
            "before": old_prefs,
            "after": clean_prefs,
        }
        proposal = store.create_proposal(
            kind="preference_change",
            payload={"preferences": clean_prefs},
            preview=preview,
            risk="low",
            workspace=target_dir,
            proposal_id=proposal_id,
        )
        _sync_legacy_proposals(proposal_id, proposal)
        log_event("preference_change_proposed", {"proposal_id": proposal_id, "risk": "low"})
        return json.dumps({
            "proposal_id": proposal_id,
            "kind": "preference_change",
            "preview": preview,
            "risk": "low",
            "status": "pending_confirmation",
            "message": f"Proposal {proposal_id} created to update preferences.",
        })
    except Exception as e:
        return json.dumps({"error": str(e), "status": "error"})


def _is_recurring_monthly(dates: list[date], amounts: list[float]) -> bool:
    """Check if there is a subsequence of at least 3 charges at roughly monthly intervals
    (25-35 days apart) with similar amounts (within 10%).
    """
    if len(dates) < 3 or len(amounts) < 3:
        return False

    n = len(dates)
    for i in range(n - 2):
        window_len = 1
        for j in range(i, n - 1):
            day_gap = (dates[j + 1] - dates[j]).days
            if not (25 <= day_gap <= 35):
                break
            a1 = amounts[j]
            a2 = amounts[j + 1]
            max_a = max(a1, a2)
            if max_a > 0 and (abs(a2 - a1) / max_a) > 0.10:
                break
            window_len += 1
            if window_len >= 3:
                return True
    return False


def find_subscriptions(workspace: Path | str | None = None) -> str:
    """Find recurring subscriptions and charges in transactions.
    A charge is a subscription if the same merchant or description repeats at roughly monthly intervals
    (25-35 days apart) at least 3 times with a similar amount (within 10%), or if it sits in the Subscriptions category.
    Returns name, monthly_cost, last_charged (human date), months_seen and total_monthly.
    Plain text, no IDs. A one-off purchase is never flagged. Reuse existing transaction reads in store.py.
    """
    try:
        from src.formatters import format_date_human
        target_dir = Path(workspace).resolve() if workspace is not None else store.get_data_dir()
        t_path = target_dir / "transactions.csv"
        if not t_path.exists():
            return JsonDict({"subscriptions": [], "total_monthly": 0.0, "count": 0})

        df = store.read_csv("transactions.csv", workspace=target_dir)
        if df.empty or "type" not in df.columns or "amount" not in df.columns:
            return JsonDict({"subscriptions": [], "total_monthly": 0.0, "count": 0})

        exp_df = df[df["type"] == "expense"].copy()
        if exp_df.empty:
            return JsonDict({"subscriptions": [], "total_monthly": 0.0, "count": 0})

        exp_df["date_dt"] = pd.to_datetime(exp_df["date"], errors="coerce")
        exp_df = exp_df.dropna(subset=["date_dt"])

        def _get_item_name(r):
            m = r.get("merchant")
            if pd.notna(m) and str(m).strip():
                return sanitize_description(m)
            d = r.get("description")
            if pd.notna(d) and str(d).strip():
                return sanitize_description(d)
            return "Unknown"

        exp_df["item_name"] = exp_df.apply(_get_item_name, axis=1)

        subscriptions = []
        for item_name, grp in exp_df.groupby("item_name"):
            # A one-off purchase is never flagged
            if len(grp) < 2:
                continue

            grp = grp.sort_values("date_dt")
            is_sub_cat = any(str(c).strip().lower() == "subscriptions" for c in grp.get("category", []))

            dates = [d.date() if hasattr(d, "date") else d for d in grp["date_dt"].tolist()]
            amts = [float(a) for a in grp["amount"].tolist()]
            repeats_monthly = _is_recurring_monthly(dates, amts)

            if is_sub_cat or repeats_monthly:
                last_row = grp.iloc[-1]
                last_dt_str = str(last_row["date"])
                human_last = format_date_human(last_dt_str)
                m_cost = round(float(last_row["amount"]), 2)
                months_seen = len(set(str(d)[:7] for d in grp["date"].dropna()))
                subscriptions.append({
                    "name": item_name,
                    "monthly_cost": m_cost,
                    "last_charged": human_last,
                    "months_seen": months_seen,
                })

        subscriptions.sort(key=lambda s: str(s.get("name", "")).lower())
        total_monthly = round(sum(s["monthly_cost"] for s in subscriptions), 2)
        res = {
            "subscriptions": subscriptions,
            "total_monthly": total_monthly,
            "count": len(subscriptions),
        }
        return JsonDict(truncate_tool_result(res))
    except Exception as e:
        return JsonDict({"error": str(e), "subscriptions": [], "total_monthly": 0.0, "count": 0})


def whatif_cashflow(
    cancel_subscription: str | None = None,
    monthly_expense_change: float | int | None = None,
    monthly_income_change: float | int | None = None,
    days_ahead: int = 30,
    today: str | None = None,
    workspace: Path | str | None = None,
) -> str:
    """Simulate a what-if cash flow scenario over a forward horizon.
    Reuses cashflow_projection for the baseline and returns baseline_end, scenario_end,
    difference, lowest_balance, and the date of that low (date_of_low / lowest_balance_date).
    With no changes, difference must be exactly 0. Never writes to ledger or proposals.
    """
    try:
        try:
            days_ahead = int(days_ahead) if days_ahead is not None else 30
        except (ValueError, TypeError):
            days_ahead = 30

        exp_change = float(monthly_expense_change) if monthly_expense_change is not None else 0.0
        inc_change = float(monthly_income_change) if monthly_income_change is not None else 0.0
        cancel_name = str(cancel_subscription).strip() if cancel_subscription is not None and str(cancel_subscription).strip() else None

        active_token = None
        if workspace is not None:
            active_token = store.set_active_workspace(workspace)
        try:
            from src.formatters import format_date_human

            matched_sub = None
            canonical_name = None
            if cancel_name:
                subs_raw = find_subscriptions(workspace=workspace)
                subs_data = json.loads(subs_raw) if isinstance(subs_raw, str) else subs_raw
                known_subs = subs_data.get("subscriptions", [])
                known_names = [str(s.get("name", "")).strip() for s in known_subs if s.get("name")]

                c_clean = cancel_name.strip().lower()
                # 1. Exact case-insensitive match
                matches = [s for s in known_subs if str(s.get("name", "")).strip().lower() == c_clean]
                # 2. If no exact match, try unique substring match
                if not matches:
                    matches = [
                        s for s in known_subs
                        if c_clean in str(s.get("name", "")).strip().lower() or str(s.get("name", "")).strip().lower() in c_clean
                    ]

                if len(matches) != 1:
                    return JsonDict({
                        "status": "not_found",
                        "known_subscriptions": known_names,
                        "message": f"Subscription '{cancel_name}' not found. Known subscriptions: {', '.join(known_names)}",
                    })

                matched_sub = matches[0]
                canonical_name = str(matched_sub.get("name", ""))

            baseline_raw = cashflow_projection(days_ahead=days_ahead, today=today)
            baseline = json.loads(baseline_raw)
            if "error" in baseline:
                return JsonDict(baseline)

            baseline_end = round(float(baseline.get("projected_end_balance", 0.0)), 2)
            baseline_low = round(float(baseline.get("lowest_balance", 0.0)), 2)
            baseline_low_date = str(baseline.get("lowest_balance_date", today or AS_OF_DATE))
            scheduled_bills = baseline.get("scheduled_bills", [])
            simulated_sandbox_balance = float(baseline.get("simulated_sandbox_balance", 0.0))
            avg_daily_discretionary_spend = float(baseline.get("avg_daily_discretionary_spend", 0.0))
            as_of = str(baseline.get("as_of", today or AS_OF_DATE))
            today_dt = date.fromisoformat(as_of)
            end_dt = today_dt + timedelta(days=days_ahead)
            end_date_iso = end_dt.isoformat()
            end_date_human = format_date_human(end_date_iso)

            # With no changes, difference must be exactly 0
            if not cancel_name and abs(exp_change) < 1e-6 and abs(inc_change) < 1e-6:
                res = {
                    "status": "ok",
                    "baseline_end": baseline_end,
                    "scenario_end": baseline_end,
                    "difference": 0.0,
                    "lowest_balance": baseline_low,
                    "lowest_balance_date": baseline_low_date,
                    "date_of_low": baseline_low_date,
                    "end_date": end_date_iso,
                    "end_date_human": end_date_human,
                }
                return JsonDict(res)

            target_dir = Path(workspace).resolve() if workspace is not None else store.get_data_dir()
            df = store.read_csv("transactions.csv", workspace=target_dir)

            scenario_bills_by_date = {}
            cancelled_charges_by_date = {}

            c_lower = canonical_name.lower().strip() if canonical_name else ""
            matched_in_scheduled = False

            if cancel_name and canonical_name:
                for b in scheduled_bills:
                    b_name = str(b.get("name", "")).strip().lower()
                    if b_name == c_lower or b_name in c_lower or c_lower in b_name:
                        matched_in_scheduled = True
                        cancelled_charges_by_date.setdefault(b["due_date"], 0.0)
                        cancelled_charges_by_date[b["due_date"]] += float(b["amount"])
                    else:
                        scenario_bills_by_date.setdefault(b["due_date"], 0.0)
                        scenario_bills_by_date[b["due_date"]] += float(b["amount"])
            else:
                for b in scheduled_bills:
                    scenario_bills_by_date.setdefault(b["due_date"], 0.0)
                    scenario_bills_by_date[b["due_date"]] += float(b["amount"])

            if cancel_name and not matched_in_scheduled and matched_sub:
                m_cost = float(matched_sub.get("monthly_cost", 0.0))
                last_ch = str(matched_sub.get("last_charged", ""))
                try:
                    dt_last = datetime.strptime(last_ch, "%d %b %Y")
                    ch_day = dt_last.day
                except Exception:
                    ch_day = 1
                for offset in range(1, days_ahead + 1):
                    target_dt = today_dt + timedelta(days=offset)
                    max_day = calendar.monthrange(target_dt.year, target_dt.month)[1]
                    clamped_day = min(ch_day, max_day)
                    if target_dt.day == clamped_day:
                        cancelled_charges_by_date.setdefault(target_dt.isoformat(), 0.0)
                        cancelled_charges_by_date[target_dt.isoformat()] += m_cost

            # Income by date for scenario
            income_tx = df[df["type"] == "income"].sort_values("date") if not df.empty and "type" in df.columns else pd.DataFrame()
            if income_tx.empty:
                pay_day = 1
                avg_monthly_income = 0.0
            else:
                most_recent_inc = income_tx.iloc[-1]
                pay_day = int(str(most_recent_inc["date"]).split("-")[2])
                monthly_incomes = income_tx.groupby("month")["amount"].sum()
                avg_monthly_income = round(float(monthly_incomes.mean()), 2)

            scenario_income_by_date = {}
            for offset in range(days_ahead + 1):
                target_dt = today_dt + timedelta(days=offset)
                if target_dt.day == pay_day and offset > 0:
                    scenario_income_by_date[target_dt.isoformat()] = avg_monthly_income + inc_change

            daily_income_spread = 0.0
            if inc_change and not scenario_income_by_date:
                daily_income_spread = inc_change / 30.0

            scenario_daily_spend = avg_daily_discretionary_spend + (exp_change / 30.0)

            current_balance = simulated_sandbox_balance
            lowest_balance = current_balance
            lowest_balance_date = today_dt.isoformat()

            if today_dt.isoformat() in scenario_bills_by_date:
                current_balance = round(current_balance - scenario_bills_by_date[today_dt.isoformat()], 2)
                if current_balance < lowest_balance:
                    lowest_balance = current_balance
                    lowest_balance_date = today_dt.isoformat()

            for offset in range(1, days_ahead + 1):
                current_dt = today_dt + timedelta(days=offset)
                date_str = current_dt.isoformat()

                if date_str in scenario_income_by_date:
                    current_balance = round(current_balance + scenario_income_by_date[date_str], 2)
                if daily_income_spread:
                    current_balance = round(current_balance + daily_income_spread, 2)
                if date_str in scenario_bills_by_date:
                    current_balance = round(current_balance - scenario_bills_by_date[date_str], 2)
                if date_str in cancelled_charges_by_date and not matched_in_scheduled:
                    current_balance = round(current_balance + cancelled_charges_by_date[date_str], 2)

                current_balance = round(current_balance - scenario_daily_spend, 2)

                if current_balance < lowest_balance:
                    lowest_balance = current_balance
                    lowest_balance_date = date_str

            scenario_end = round(current_balance, 2)
            difference = round(scenario_end - baseline_end, 2)
            if abs(difference) < 1e-6:
                difference = 0.0

            removed_amount = round(sum(cancelled_charges_by_date.values()), 2) if cancel_name else 0.0

            res = {
                "status": "ok",
                "baseline_end": baseline_end,
                "scenario_end": scenario_end,
                "difference": difference,
                "lowest_balance": lowest_balance,
                "lowest_balance_date": lowest_balance_date,
                "date_of_low": lowest_balance_date,
                "end_date": end_date_iso,
                "end_date_human": end_date_human,
            }
            if cancel_name:
                res["cancel_subscription"] = canonical_name
                res["removed_amount"] = removed_amount
            return JsonDict(res)
        finally:
            if active_token is not None:
                store.set_active_workspace(None)

    except Exception as e:
        return JsonDict({"error": str(e)})


def format_day_month(d_val: Any) -> str:
    """Format YYYY-MM-DD into '10 Aug'."""
    if not d_val:
        return ""
    try:
        s = str(d_val).strip()[:10]
        dt = datetime.strptime(s, "%Y-%m-%d")
        return f"{dt.day} {dt.strftime('%b')}"
    except Exception:
        return str(d_val)


def find_duplicates(month: str | None = None, workspace: Path | str | None = None) -> str:
    """Find near-duplicate expense transactions: same description, same amount, dates within 3 days,
    and not a recurring charge (25-35 days apart).
    Returns list of duplicate pairs with earlier and later copy details.
    """
    try:
        target_dir = Path(workspace).resolve() if workspace is not None else store.get_data_dir()
        t_path = target_dir / "transactions.csv"
        if not t_path.exists():
            return JsonDict({"status": "ok", "duplicates": [], "count": 0, "message": "No duplicate transactions found."})

        df = store.read_csv("transactions.csv", data_dir=target_dir)
        if df.empty or "type" not in df.columns or "amount" not in df.columns or "date" not in df.columns:
            return JsonDict({"status": "ok", "duplicates": [], "count": 0, "message": "No duplicate transactions found."})

        exp_df = df[df["type"] == "expense"].copy()
        if exp_df.empty:
            return JsonDict({"status": "ok", "duplicates": [], "count": 0, "message": "No duplicate transactions found."})

        if "id" not in exp_df.columns:
            exp_df = store.ensure_transaction_ids(exp_df)

        exp_df["date_dt"] = pd.to_datetime(exp_df["date"], errors="coerce")
        exp_df = exp_df.dropna(subset=["date_dt"])

        if month:
            resolved = resolve_period(month)
            if not isinstance(resolved, dict):
                m_prefix = resolved[:7] if len(resolved) >= 7 else resolved
                exp_df = exp_df[exp_df["date"].astype(str).str.startswith(m_prefix)]

        def _clean_desc(d):
            return str(d).strip().lower()

        exp_df["clean_desc"] = exp_df["description"].apply(_clean_desc)
        exp_df["clean_amt"] = exp_df["amount"].astype(float).round(2)

        duplicates = []
        for (desc_key, amt_key), grp in exp_df.groupby(["clean_desc", "clean_amt"]):
            if len(grp) < 2:
                continue

            grp_sorted = grp.sort_values(by=["date_dt"])
            records = grp_sorted.to_dict(orient="records")

            paired_indices = set()
            n = len(records)
            for i in range(n):
                for j in range(i + 1, n):
                    if i in paired_indices or j in paired_indices:
                        continue
                    r1 = records[i]
                    r2 = records[j]
                    d1 = r1["date_dt"].date() if hasattr(r1["date_dt"], "date") else r1["date_dt"]
                    d2 = r2["date_dt"].date() if hasattr(r2["date_dt"], "date") else r2["date_dt"]
                    day_gap = abs((d2 - d1).days)

                    # Two expense transactions are a near-duplicate if they have the same description,
                    # the same amount, and dates within 3 days, and they are not a recurring charge (25-35 days apart).
                    # A pair 3 days apart with the same amount is flagged once. A 30-day recurring pair is not flagged.
                    if day_gap <= 3:
                        paired_indices.add(i)
                        paired_indices.add(j)

                        if d1 <= d2:
                            earlier, later = r1, r2
                        else:
                            earlier, later = r2, r1

                        d1_human = format_day_month(earlier["date"])
                        d2_human = format_day_month(later["date"])

                        duplicates.append({
                            "description": sanitize_description(earlier.get("description", desc_key)),
                            "amount": round(float(amt_key), 2),
                            "date1": str(earlier["date"]),
                            "date2": str(later["date"]),
                            "date1_human": d1_human,
                            "date2_human": d2_human,
                            "earlier_transaction_id": str(earlier.get("id")),
                            "later_transaction_id": str(later.get("id")),
                            "suggested_delete_id": str(later.get("id")),
                            "earlier_copy": {k: v for k, v in earlier.items() if k not in ("date_dt", "clean_desc", "clean_amt")},
                            "later_copy": {k: v for k, v in later.items() if k not in ("date_dt", "clean_desc", "clean_amt")},
                        })

        return JsonDict({
            "status": "ok",
            "count": len(duplicates),
            "duplicates": duplicates,
            "message": f"Found {len(duplicates)} possible duplicate charges." if duplicates else "No duplicate transactions found.",
        })
    except Exception as e:
        return JsonDict({"error": str(e), "status": "error", "duplicates": [], "count": 0})


def rescue_plan(
    days_ahead: int = 30,
    today: str | None = None,
    workspace: Path | str | None = None,
) -> str:
    """If the lowest balance in the 30-day cash projection is below zero, returns the smallest set
    of changes that covers the gap. Options are budget reductions (lowered to current spend) and
    subscriptions from find_subscriptions (advice only). If options cannot cover the gap, returns
    how much is still missing. Read-only tool, never writes to ledger or proposals.
    """
    try:
        import itertools
        from src.formatters import format_date_human

        try:
            days_ahead = int(days_ahead) if days_ahead is not None else 30
        except (ValueError, TypeError):
            days_ahead = 30

        active_token = None
        if workspace is not None:
            active_token = store.set_active_workspace(workspace)
        try:
            target_dir = Path(workspace).resolve() if workspace is not None else store.get_data_dir()
            baseline_raw = cashflow_projection(days_ahead=days_ahead, today=today)
            baseline = json.loads(baseline_raw) if isinstance(baseline_raw, str) else baseline_raw
            if "error" in baseline:
                return JsonDict({"error": baseline["error"], "status": "error"})

            lowest_balance = float(baseline.get("lowest_balance", 0.0))
            lowest_balance_date = str(baseline.get("lowest_balance_date") or today or AS_OF_DATE)
            lowest_balance_date_human = format_date_human(lowest_balance_date)

            if lowest_balance >= 0:
                return JsonDict({
                    "status": "ok",
                    "has_shortfall": False,
                    "lowest_balance": lowest_balance,
                    "lowest_balance_date": lowest_balance_date,
                    "lowest_balance_date_human": lowest_balance_date_human,
                    "options": [],
                    "covers_gap": True,
                    "missing": 0.0,
                    "message": "No cash shortfall projected in the next 30 days.",
                })

            shortfall = round(abs(lowest_balance), 2)
            candidates = []

            # 1. Budget reductions: lowered to current spend
            b_path = target_dir / "budgets.json"
            t_path = target_dir / "transactions.csv"
            budgets = {}
            if b_path.exists():
                with open(b_path, "r", encoding="utf-8") as f:
                    try:
                        budgets = json.load(f)
                    except Exception:
                        budgets = {}

            spent_by_cat = {}
            if t_path.exists():
                df = store.read_csv("transactions.csv", data_dir=target_dir)
                if not df.empty and "type" in df.columns and "amount" in df.columns and "date" in df.columns:
                    as_of_str = str(today or AS_OF_DATE)
                    curr_month = as_of_str[:7]
                    m_df = df[(df["month"] == curr_month) & (df["type"] == "expense")]
                    if not m_df.empty:
                        spent_by_cat = m_df.groupby("category")["amount"].sum().to_dict()

            for cat, limit in budgets.items():
                spent = round(float(spent_by_cat.get(cat, 0.0)), 2)
                limit_val = round(float(limit), 2)
                if limit_val > spent:
                    savings = round(limit_val - spent, 2)
                    new_limit = spent
                    candidates.append({
                        "type": "budget",
                        "category": cat,
                        "current_limit": limit_val,
                        "new_limit": new_limit,
                        "savings": savings,
                        "text": f"lower {cat} to ${new_limit:.2f} (+${savings:.2f})",
                    })

            # 2. Subscriptions from find_subscriptions
            subs_raw = find_subscriptions(workspace=workspace)
            subs_data = json.loads(subs_raw) if isinstance(subs_raw, str) else subs_data
            for s in subs_data.get("subscriptions", []):
                name = str(s.get("name", "")).strip()
                m_cost = round(float(s.get("monthly_cost", 0.0)), 2)
                if m_cost > 0 and name:
                    candidates.append({
                        "type": "subscription",
                        "name": name,
                        "monthly_cost": m_cost,
                        "savings": m_cost,
                        "text": f"cancel {name} with the provider (+${m_cost:.2f})",
                    })

            # Sort candidates by savings descending, then name/category
            candidates.sort(key=lambda c: (-c["savings"], str(c.get("category") or c.get("name") or "")))

            # Smallest set of changes that covers the gap
            selected = []
            covers_gap = False
            missing = shortfall

            if candidates:
                for k in range(1, len(candidates) + 1):
                    valid_combos = [
                        combo for combo in itertools.combinations(candidates, k)
                        if sum(c["savings"] for c in combo) >= shortfall
                    ]
                    if valid_combos:
                        # Pick combo that covers gap with highest savings
                        best_combo = max(valid_combos, key=lambda combo: sum(c["savings"] for c in combo))
                        selected = list(best_combo)
                        covers_gap = True
                        missing = 0.0
                        break

                if not covers_gap:
                    selected = list(candidates)
                    total_savings = round(sum(c["savings"] for c in selected), 2)
                    missing = round(shortfall - total_savings, 2)
            else:
                missing = shortfall

            return JsonDict({
                "status": "ok",
                "has_shortfall": True,
                "lowest_balance": lowest_balance,
                "lowest_balance_date": lowest_balance_date,
                "lowest_balance_date_human": lowest_balance_date_human,
                "shortfall": shortfall,
                "covers_gap": covers_gap,
                "missing": missing,
                "options": selected,
                "total_savings": round(sum(o["savings"] for o in selected), 2),
            })
        finally:
            if active_token is not None:
                store.set_active_workspace(None)
    except Exception as e:
        return JsonDict({"error": str(e), "status": "error"})


FIND_SUBSCRIPTIONS_SCHEMA = {
    "name": "find_subscriptions",
    "description": "Find recurring subscriptions and charges in transactions. Returns name, monthly_cost, last_charged (human date), months_seen, and total_monthly. Plain text, no IDs. A one-off purchase is never flagged.",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

WHATIF_CASHFLOW_SCHEMA = {
    "name": "whatif_cashflow",
    "description": "Simulate a what-if cash flow scenario over a forward horizon. Reuses cashflow_projection for the baseline. Arguments: cancel_subscription (name, optional), monthly_expense_change (number, optional), monthly_income_change (number, optional), days_ahead (default 30). Returns baseline_end, scenario_end, difference, lowest_balance, and date_of_low. With no changes, difference is exactly 0. Never writes to ledger or proposals.",
    "parameters": {
        "type": "object",
        "properties": {
            "cancel_subscription": {
                "type": "string",
                "description": "Name of a recurring subscription or bill to simulate cancelling.",
            },
            "monthly_expense_change": {
                "type": "number",
                "description": "Monthly expense change amount in USD (positive to increase expenses, negative to reduce).",
            },
            "monthly_income_change": {
                "type": "number",
                "description": "Monthly income change amount in USD.",
            },
            "days_ahead": {
                "type": "integer",
                "description": "Forward projection horizon in days (default 30).",
            },
        },
    },
}


LIST_GOALS_SCHEMA = {
    "name": "list_goals",
    "description": "List all active financial goals from the workspace. Returns id, name, target_amount, target_date, saved_so_far, and created date.",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

GET_GOAL_PROGRESS_SCHEMA = {
    "name": "get_goal_progress",
    "description": "Calculate and return progress for a savings goal: percent_done, monthly_needed (target minus saved, spread over the months left from the sandbox date), and on_track. In your text answers, use plain numbers and goal names, with no IDs.",
    "parameters": {
        "type": "object",
        "properties": {
            "goal_id": {
                "type": "string",
                "description": "The unique ID of the goal to check progress for.",
            },
        },
        "required": ["goal_id"],
    },
}

PROPOSE_GOAL_SCHEMA = {
    "name": "propose_goal",
    "description": "Propose adding, updating, or deleting a financial savings goal. Deleting a goal is high risk and requires CONFIRM, while adding or updating is low risk and requires 'yes'. Arguments: action ('add', 'update', 'delete'), name (string), target_amount (number), target_date (YYYY-MM-DD), saved_so_far (number), goal_id (string, required for update/delete).",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "update", "delete"],
                "description": "Action to perform: 'add', 'update', or 'delete'.",
            },
            "name": {
                "type": "string",
                "description": "Name of the savings goal (e.g. 'Emergency Fund', 'Vacation').",
            },
            "target_amount": {
                "type": "number",
                "description": "Target savings amount in USD.",
            },
            "target_date": {
                "type": "string",
                "description": "Target completion date in YYYY-MM-DD format.",
            },
            "saved_so_far": {
                "type": "number",
                "description": "Current amount saved towards this goal in USD (default 0.0).",
            },
            "goal_id": {
                "type": "string",
                "description": "Goal ID to update or delete.",
            },
        },
        "required": ["action"],
    },
}

PROPOSE_PREFERENCE_CHANGE_SCHEMA = {
    "name": "propose_preference_change",
    "description": "Propose updating user financial preferences. Arguments: savings_target_percent (0-100), alert_bills_days (integer days ahead to alert for bills), currency_label (symbol or code, e.g. '$'). Risk is low.",
    "parameters": {
        "type": "object",
        "properties": {
            "savings_target_percent": {
                "type": "number",
                "description": "Target monthly savings percentage of income (0-100, default 20).",
            },
            "alert_bills_days": {
                "type": "integer",
                "description": "Days in advance to alert for upcoming bills (default 3).",
            },
            "currency_label": {
                "type": "string",
                "description": "Currency symbol or label (default '$').",
            },
        },
    },
}

FIND_DUPLICATES_SCHEMA = {
    "name": "find_duplicates",
    "description": "Finds near-duplicate expense transactions with the same description, same amount, and dates within 3 days (excluding recurring monthly charges 25-35 days apart). Arguments: month (optional string YYYY-MM).",
    "parameters": {
        "type": "object",
        "properties": {
            "month": {
                "type": "string",
                "description": "Optional month in YYYY-MM format to filter duplicate search.",
            },
        },
    },
}

RESCUE_PLAN_SCHEMA = {
    "name": "rescue_plan",
    "description": "Finds a rescue plan when projected cashflow drops below zero. Returns the smallest set of changes (budget reductions lowered to current spend, and subscriptions to cancel) that covers the gap, or how much is still missing. Arguments: days_ahead (integer, default 30), today (string YYYY-MM-DD, optional).",
    "parameters": {
        "type": "object",
        "properties": {
            "days_ahead": {
                "type": "integer",
                "description": "Forward projection horizon in days (default 30).",
            },
            "today": {
                "type": "string",
                "description": "Starting date for projection in YYYY-MM-DD format (defaults to the simulated sandbox date).",
            },
        },
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
    PROPOSE_ADD_TRANSACTIONS_SCHEMA,
    PROPOSE_UPDATE_TRANSACTION_SCHEMA,
    PROPOSE_DELETE_TRANSACTION_SCHEMA,
    PROPOSE_BILL_CHANGE_SCHEMA,
    REVISE_PROPOSAL_SCHEMA,
    GET_ALERTS_SCHEMA,
    LIST_GOALS_SCHEMA,
    GET_GOAL_PROGRESS_SCHEMA,
    PROPOSE_GOAL_SCHEMA,
    PROPOSE_PREFERENCE_CHANGE_SCHEMA,
    FIND_SUBSCRIPTIONS_SCHEMA,
    WHATIF_CASHFLOW_SCHEMA,
    FIND_DUPLICATES_SCHEMA,
    RESCUE_PLAN_SCHEMA,
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
    "propose_add_transactions": propose_add_transactions,
    "propose_update_transaction": propose_update_transaction,
    "propose_delete_transaction": propose_delete_transaction,
    "propose_bill_change": propose_bill_change,
    "revise_proposal": revise_proposal,
    "get_alerts": get_alerts,
    "list_goals": list_goals,
    "get_goal_progress": get_goal_progress,
    "propose_goal": propose_goal,
    "propose_preference_change": propose_preference_change,
    "find_subscriptions": find_subscriptions,
    "whatif_cashflow": whatif_cashflow,
    "find_duplicates": find_duplicates,
    "rescue_plan": rescue_plan,
}



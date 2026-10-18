"""Validation layer for financial amounts, dates, categories, and descriptions."""

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Collection
import uuid
import pandas as pd

try:
    import src.config as config
except ImportError:
    try:
        import config
    except ImportError:
        config = None

try:
    from src.tools import sanitize_description
except ImportError:
    try:
        from tools import sanitize_description
    except ImportError:
        def sanitize_description(desc: Any) -> str:
            """Fallback sanitizer if src.tools cannot be imported."""
            if desc is None or (isinstance(desc, float) and pd.isna(desc)):
                return ""
            text = str(desc)
            cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", text)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            return cleaned[:80]

try:
    from src.store import get_sandbox_today
except ImportError:
    try:
        from store import get_sandbox_today
    except ImportError:
        def get_sandbox_today(workspace: Any = None) -> str:
            return "2026-08-31"


def get_workspace_categories(workspace: Any = None) -> set[str]:
    """Return the set of categories dynamically resolved from the workspace:
    budgets.json keys plus expense categories found in transactions.
    """
    categories: set[str] = set()
    target_dir: Path | None = None
    if workspace is not None:
        target_dir = Path(workspace).resolve()
    else:
        try:
            from src.store import get_data_dir
            target_dir = get_data_dir()
        except Exception:
            try:
                from store import get_data_dir
                target_dir = get_data_dir()
            except Exception:
                pass

    # 1. budgets.json keys
    budgets_obj = None
    if target_dir:
        b_path = target_dir / "budgets.json"
        if b_path.exists():
            try:
                with open(b_path, "r", encoding="utf-8") as f:
                    budgets_obj = json.load(f)
            except Exception:
                pass

    if budgets_obj is None:
        try:
            from src.store import SEED_DATA_DIR
            b_path = SEED_DATA_DIR / "budgets.json"
            if b_path.exists():
                with open(b_path, "r", encoding="utf-8") as f:
                    budgets_obj = json.load(f)
        except Exception:
            pass

    if isinstance(budgets_obj, dict):
        for k in budgets_obj.keys():
            k_str = str(k).strip()
            if k_str:
                categories.add(k_str)

    # 2. Expense categories found in transactions.csv
    tx_df = None
    if target_dir:
        tx_path = target_dir / "transactions.csv"
        if tx_path.exists():
            try:
                tx_df = pd.read_csv(tx_path)
            except Exception:
                pass

    if tx_df is None:
        try:
            from src.store import SEED_DATA_DIR
            tx_path = SEED_DATA_DIR / "transactions.csv"
            if tx_path.exists():
                tx_df = pd.read_csv(tx_path)
        except Exception:
            pass

    if tx_df is not None and not tx_df.empty and "category" in tx_df.columns:
        if "type" in tx_df.columns:
            expense_rows = tx_df[tx_df["type"].astype(str).str.lower() == "expense"]
            for cat in expense_rows["category"].dropna().unique():
                c_str = str(cat).strip()
                if c_str:
                    categories.add(c_str)
        else:
            for cat in tx_df["category"].dropna().unique():
                c_str = str(cat).strip()
                if c_str:
                    categories.add(c_str)

    return categories


def __getattr__(name: str) -> Any:
    """Dynamically resolve KNOWN_CATEGORIES to categories present in workspace."""
    if name == "KNOWN_CATEGORIES":
        return get_workspace_categories()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def validate_amount(amount: Any) -> tuple[bool, float | str]:
    """Validate financial amount:
    - greater than 0
    - at most 100000
    - at most 2 decimal places

    Returns (ok, cleaned_value_or_error_message).
    """
    if amount is None or isinstance(amount, bool):
        return False, "Amount must be a valid number."

    try:
        if isinstance(amount, float):
            if math.isnan(amount) or math.isinf(amount):
                return False, "Amount must be a finite number."
            dec = Decimal(str(amount))
        elif isinstance(amount, int):
            dec = Decimal(amount)
        elif isinstance(amount, str):
            clean_str = amount.strip()
            if not clean_str:
                return False, "Amount cannot be empty."
            dec = Decimal(clean_str)
        elif isinstance(amount, Decimal):
            dec = amount
        else:
            return False, "Amount must be a number or numeric string."
    except (InvalidOperation, ValueError):
        return False, f"Amount '{amount}' is not a valid number."

    if dec <= Decimal("0"):
        return False, f"Amount must be greater than 0, got {amount}."

    if dec > Decimal("100000"):
        return False, f"Amount cannot exceed 100000, got {amount}."

    # Check decimal places: reject more than 2 decimal places
    if isinstance(amount, str) and "." in amount:
        frac = amount.strip().split(".")[1]
        if len(frac) > 2:
            return False, f"Amount '{amount}' has more than 2 decimal places."

    if dec != dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP):
        return False, f"Amount {amount} has more than 2 decimal places."

    return True, round(float(dec), 2)


def validate_date(
    date_val: Any,
    sandbox_date: str | None = None,
    workspace: Any = None,
) -> tuple[bool, str]:
    """Validate transaction/bill date:
    - ISO format (YYYY-MM-DD)
    - not before 2000-01-01
    - not after the sandbox date (defaults to get_sandbox_today(workspace))

    Returns (ok, cleaned_value_or_error_message).
    """
    if not isinstance(date_val, (str, date)):
        return False, "Date must be a string or date in YYYY-MM-DD ISO format."

    if isinstance(date_val, str):
        date_str = date_val.strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            return False, f"Date '{date_val}' is not in YYYY-MM-DD ISO format."
        try:
            d = date.fromisoformat(date_str)
        except ValueError:
            return False, f"Date '{date_val}' is not a valid calendar date."
    else:
        d = date_val
        date_str = d.isoformat()

    min_date = date(2000, 1, 1)
    if d < min_date:
        return False, f"Date '{date_str}' cannot be before 2000-01-01."

    effective_sandbox = sandbox_date or get_sandbox_today(workspace)
    try:
        max_date = date.fromisoformat(str(effective_sandbox).strip())
    except ValueError:
        max_date = date(2026, 8, 31)

    if d > max_date:
        return False, f"Date '{date_str}' cannot be after sandbox date ({effective_sandbox})."

    return True, date_str


def validate_category(
    category: Any,
    known_categories: Collection[str] | None = None,
    workspace: Any = None,
) -> tuple[bool, str]:
    """Validate spending/budget category:
    - must exist in the workspace categories (budgets.json keys + transactions expense categories)

    Returns (ok, cleaned_value_or_error_message).
    """
    if category is None or not isinstance(category, str):
        return False, "Category must be a string."

    cat_str = category.strip()
    if not cat_str:
        return False, "Category cannot be empty."

    cats = set(known_categories) if known_categories is not None else get_workspace_categories(workspace)

    if cat_str in cats:
        return True, cat_str

    # Case-insensitive match fallback
    for known in cats:
        if known.lower() == cat_str.lower():
            return True, known

    return False, f"Category '{category}' is invalid. Must be one of: {sorted(cats)}."


def validate_text(
    text: Any,
    max_length: int = 80,
    truncate: bool = False,
) -> tuple[bool, str]:
    """Validate and clean transaction/bill description text:
    - at most 80 characters (rejects if exceeds max_length unless truncate=True)
    - control characters stripped
    - leading = + - @ removed (formula/CSV injection prevention)

    Returns (ok, cleaned_value_or_error_message).
    """
    if text is None:
        return False, "Text cannot be None."

    if not isinstance(text, str):
        text = str(text)

    raw_stripped = text.strip()
    if not raw_stripped:
        return False, "Text cannot be empty."

    if not truncate and len(raw_stripped) > max_length:
        return False, f"Text length ({len(raw_stripped)}) exceeds maximum allowed ({max_length})."

    # Reuse sanitize_description to strip control characters & collapse whitespace
    cleaned = sanitize_description(text)

    # Remove leading formula / injection characters: =, +, -, @
    cleaned = re.sub(r"^[=+\-@]+", "", cleaned).strip()

    if not cleaned:
        return False, "Text cannot be empty after removing control and formula characters."

    if not truncate and len(cleaned) > max_length:
        return False, f"Text length ({len(cleaned)}) exceeds maximum allowed ({max_length})."

    if truncate and len(cleaned) > max_length:
        cleaned = cleaned[:max_length]

    return True, cleaned


def validate_goal(
    data: dict[str, Any],
    workspace: Any = None,
    is_update: bool = False,
) -> tuple[bool, dict[str, Any] | str]:
    """Validate financial goal record:
    Fields: id, name, target_amount, target_date, saved_so_far, created.

    Returns (ok, cleaned_dict_or_error_message).
    """
    if not isinstance(data, dict):
        return False, "Goal data must be a dictionary."

    # id: if not provided or empty, generate one (unless is_update and missing)
    g_id = str(data.get("id") or data.get("goal_id") or "").strip()
    if not g_id:
        if is_update:
            return False, "Goal ID is required for update."
        g_id = f"g_{uuid.uuid4().hex[:8]}"

    # name: validated and cleaned with validate_text; injection strings remain harmless plain text
    name_val = data.get("name")
    ok_name, clean_name = validate_text(name_val, max_length=100)
    if not ok_name:
        return False, f"Invalid goal name: {clean_name}"

    # target_amount: positive float
    amt_val = data.get("target_amount")
    ok_amt, clean_amt = validate_amount(amt_val)
    if not ok_amt:
        return False, f"Invalid target_amount: {clean_amt}"
    if clean_amt <= 0:
        return False, "Target amount must be greater than zero."

    # target_date: valid ISO date string YYYY-MM-DD
    t_date = data.get("target_date")
    if not t_date or not str(t_date).strip():
        return False, "Target date cannot be empty."
    try:
        clean_target_date = date.fromisoformat(str(t_date).strip()).isoformat()
    except (ValueError, TypeError):
        return False, f"Invalid target_date '{t_date}'. Expected YYYY-MM-DD format."

    # saved_so_far: non-negative float (default 0.0)
    saved_val = data.get("saved_so_far", 0.0)
    if saved_val is None or str(saved_val).strip() == "":
        saved_val = 0.0
    try:
        clean_saved = float(saved_val)
        if clean_saved < 0:
            return False, "saved_so_far cannot be negative."
        clean_saved = round(clean_saved, 2)
    except (ValueError, TypeError):
        return False, f"Invalid saved_so_far '{saved_val}'."

    # created: ISO date string (default sandbox date)
    created_val = data.get("created")
    if not created_val or not str(created_val).strip():
        created_val = get_sandbox_today(workspace=workspace)
    else:
        created_val = str(created_val).strip()

    return True, {
        "id": g_id,
        "name": clean_name,
        "target_amount": clean_amt,
        "target_date": clean_target_date,
        "saved_so_far": clean_saved,
        "created": created_val,
    }


def validate_preferences(data: dict[str, Any]) -> tuple[bool, dict[str, Any] | str]:
    """Validate user preferences dictionary:
    savings_target_percent (default 20, 0-100)
    alert_bills_days (default 3, int >= 0)
    currency_label (default "$", 1-5 chars)

    Returns (ok, cleaned_dict_or_error_message).
    """
    if not isinstance(data, dict):
        return False, "Preferences must be a dictionary."

    # savings_target_percent
    st_val = data.get("savings_target_percent", 20)
    if st_val is None or str(st_val).strip() == "":
        st_val = 20
    try:
        st_num = float(st_val)
        if not (0 <= st_num <= 100):
            return False, "savings_target_percent must be between 0 and 100."
        if st_num.is_integer():
            st_num = int(st_num)
    except (ValueError, TypeError):
        return False, f"Invalid savings_target_percent: '{st_val}'."

    # alert_bills_days
    ab_val = data.get("alert_bills_days", 3)
    if ab_val is None or str(ab_val).strip() == "":
        ab_val = 3
    try:
        ab_int = int(ab_val)
        if ab_int < 0:
            return False, "alert_bills_days cannot be negative."
    except (ValueError, TypeError):
        return False, f"Invalid alert_bills_days: '{ab_val}'."

    # currency_label
    cl_val = data.get("currency_label", "$")
    if cl_val is None or not str(cl_val).strip():
        cl_val = "$"
    cl_str = str(cl_val).strip()
    if len(cl_str) > 5:
        return False, "currency_label must be 1 to 5 characters."

    return True, {
        "savings_target_percent": st_num,
        "alert_bills_days": ab_int,
        "currency_label": cl_str,
    }


"""Validation layer for financial amounts, dates, categories, and descriptions."""

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math
import os
import re
from typing import Any, Collection

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
        import pandas as pd

        def sanitize_description(desc: Any) -> str:
            """Fallback sanitizer if src.tools cannot be imported."""
            if desc is None or (isinstance(desc, float) and pd.isna(desc)):
                return ""
            text = str(desc)
            cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", text)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            return cleaned[:80]


# Canonical categories recognized across the application
KNOWN_CATEGORIES: set[str] = {
    "Groceries",
    "Dining",
    "Transport",
    "Utilities",
    "Subscriptions",
    "Rent",
    "Shopping",
    "Health",
    "Insurance",
    "Other",
}


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


def validate_date(date_val: Any, sandbox_date: str | None = None) -> tuple[bool, str]:
    """Validate transaction/bill date:
    - ISO format (YYYY-MM-DD)
    - not before 2000-01-01
    - not after the sandbox date (defaults to AS_OF_DATE / FINANCE_AS_OF_DATE, e.g. 2026-08-31)

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

    effective_sandbox = (
        sandbox_date
        or os.getenv("FINANCE_AS_OF_DATE")
        or (getattr(config, "AS_OF_DATE", "2026-08-31") if config else "2026-08-31")
    )
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
) -> tuple[bool, str]:
    """Validate spending/budget category:
    - must exist in the known categories

    Returns (ok, cleaned_value_or_error_message).
    """
    if category is None or not isinstance(category, str):
        return False, "Category must be a string."

    cat_str = category.strip()
    if not cat_str:
        return False, "Category cannot be empty."

    cats = set(known_categories) if known_categories is not None else KNOWN_CATEGORIES

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

"""Period and date alias resolution based on sandbox_today."""

from datetime import date, timedelta
import os
import re
from typing import Any

try:
    import src.config as config
except ImportError:
    try:
        import config
    except ImportError:
        config = None


def get_sandbox_today() -> str:
    """Return the active sandbox today date string (YYYY-MM-DD)."""
    try:
        from src.store import get_sandbox_today as store_get_sandbox_today
        return store_get_sandbox_today()
    except Exception:
        return (
            os.getenv("FINANCE_AS_OF_DATE")
            or (getattr(config, "AS_OF_DATE", "2026-08-31") if config else "2026-08-31")
        )



def resolve_period(text: Any, sandbox_today: str | None = None) -> str | dict:
    """Resolve a period alias or YYYY-MM string to a concrete value.

    Maps:
      - 'this_month', 'current month' -> YYYY-MM of sandbox_today
      - 'last_month' -> YYYY-MM of previous month before sandbox_today
      - 'today' -> YYYY-MM-DD of sandbox_today
      - 'yesterday' -> YYYY-MM-DD of day before sandbox_today
      - YYYY-MM -> YYYY-MM

    Returns concrete string on success, or a dict with 'error' and 'valid_examples' on invalid input.
    """
    ref_today_str = sandbox_today or get_sandbox_today()
    try:
        ref_today = date.fromisoformat(str(ref_today_str).strip())
    except ValueError:
        ref_today = date(2026, 8, 31)

    this_year = ref_today.year
    this_m = ref_today.month
    this_month_str = f"{this_year:04d}-{this_m:02d}"

    if this_m == 1:
        last_month_str = f"{this_year - 1:04d}-12"
    else:
        last_month_str = f"{this_year:04d}-{this_m - 1:02d}"

    today_str = ref_today.isoformat()
    yesterday_str = (ref_today - timedelta(days=1)).isoformat()

    valid_examples = [
        "this_month",
        "last_month",
        "current month",
        "today",
        "yesterday",
        this_month_str,
        last_month_str,
    ]

    if text is None or not isinstance(text, str):
        return {
            "error": f"Invalid period '{text}': input must be a string.",
            "valid_examples": valid_examples,
        }

    s = text.strip().lower()
    if not s:
        return {
            "error": "Period cannot be empty.",
            "valid_examples": valid_examples,
        }

    # Month aliases
    if s in ("this_month", "this month", "current_month", "current month"):
        return this_month_str

    if s in ("last_month", "last month", "previous_month", "previous month"):
        return last_month_str

    # Day aliases
    if s == "today":
        return today_str

    if s == "yesterday":
        return yesterday_str

    # YYYY-MM format
    if re.match(r"^\d{4}-\d{2}$", s):
        parts = s.split("-")
        m_int = int(parts[1])
        if 1 <= m_int <= 12:
            return s
        return {
            "error": f"Invalid month in period '{text}'. Month must be between 01 and 12.",
            "valid_examples": valid_examples,
        }

    # YYYY-MM-DD format
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        try:
            date.fromisoformat(s)
            return s
        except ValueError:
            return {
                "error": f"Invalid date in period '{text}'.",
                "valid_examples": valid_examples,
            }

    return {
        "error": f"Invalid period '{text}'.",
        "valid_examples": valid_examples,
    }

"""Global daily model-call usage tracking and rate limiting for Gemini calls."""

from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import threading
from typing import Any

try:
    from zoneinfo import ZoneInfo
    DHAKA_TZ = ZoneInfo("Asia/Dhaka")
except Exception:
    DHAKA_TZ = timezone(timedelta(hours=6))

try:
    from src.config import PROJECT_ROOT, DATA_DIR
    import src.store as store
except ImportError:
    try:
        from config import PROJECT_ROOT, DATA_DIR
        import store
    except ImportError:
        PROJECT_ROOT = Path(__file__).resolve().parent.parent
        DATA_DIR = PROJECT_ROOT / "data"
        import store

_USAGE_LOCK = threading.RLock()

CAP_MESSAGE = (
    "The daily assistant limit is reached. Your ledger, plan, alerts and sandbox tools still work."
)


def get_dhaka_today() -> str:
    """Return the current calendar date in Asia/Dhaka formatted as YYYY-MM-DD."""
    return datetime.now(DHAKA_TZ).strftime("%Y-%m-%d")


def get_model_daily_cap() -> int:
    """Retrieve daily cap from st.secrets['MODEL_DAILY_CAP'], then env, then default 200."""
    # 1. st.secrets["MODEL_DAILY_CAP"]
    try:
        import streamlit as st
        if hasattr(st, "secrets") and "MODEL_DAILY_CAP" in st.secrets:
            val = st.secrets["MODEL_DAILY_CAP"]
            if val is not None and str(val).strip():
                return int(val)
    except Exception:
        pass

    # 2. environment variable MODEL_DAILY_CAP
    env_val = os.getenv("MODEL_DAILY_CAP")
    if env_val is not None and str(env_val).strip():
        try:
            return int(str(env_val).strip())
        except ValueError:
            pass

    # 3. default of 200
    return 200


def get_usage_file_path() -> Path:
    """Return the resolved Path for data/usage.json or custom test path."""
    custom = os.getenv("FINANCE_USAGE_FILE")
    if custom and custom.strip():
        return Path(custom.strip()).resolve()
    return (PROJECT_ROOT / "data" / "usage.json").resolve()


def read_usage(today: str | None = None) -> dict[str, Any]:
    """Read usage data from disk. If missing or date mismatch, returns 0 calls for today."""
    target_date = today or get_dhaka_today()
    path = get_usage_file_path()

    with _USAGE_LOCK:
        if not path.exists():
            return {"date": target_date, "calls": 0}

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {"date": target_date, "calls": 0}

            file_date = data.get("date")
            if file_date != target_date:
                # New date in Asia/Dhaka -> reset to 0
                return {"date": target_date, "calls": 0}

            calls = int(data.get("calls", 0))
            return {"date": target_date, "calls": max(0, calls)}
        except Exception:
            return {"date": target_date, "calls": 0}


def check_daily_cap(today: str | None = None) -> bool:
    """Return True if the daily model call limit has been reached or exceeded."""
    cap = get_model_daily_cap()
    with _USAGE_LOCK:
        usage = read_usage(today)
        return usage["calls"] >= cap


def check_and_increment_daily_cap(today: str | None = None) -> tuple[bool, int]:
    """Check the daily cap and increment the call counter atomically under lock.

    Returns:
        (allowed, current_calls):
            allowed is True if the request is permitted (and counter was incremented).
            allowed is False if cap is reached (counter is NOT incremented).
    """
    target_date = today or get_dhaka_today()
    cap = get_model_daily_cap()
    path = get_usage_file_path()

    with _USAGE_LOCK:
        usage = read_usage(target_date)
        current_calls = usage["calls"]
        if current_calls >= cap:
            return False, current_calls

        new_calls = current_calls + 1
        new_data = {"date": target_date, "calls": new_calls}

        store.write_json_atomic(
            name=path.name,
            obj=new_data,
            data_dir=path.parent,
            allow_shared=True,
        )
        return True, new_calls


def reset_usage(date_str: str | None = None, calls: int = 0) -> dict[str, Any]:
    """Explicitly reset or initialize the usage counter."""
    target_date = date_str or get_dhaka_today()
    path = get_usage_file_path()

    with _USAGE_LOCK:
        new_data = {"date": target_date, "calls": calls}
        store.write_json_atomic(
            name=path.name,
            obj=new_data,
            data_dir=path.parent,
            allow_shared=True,
        )
        return new_data

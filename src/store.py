"""Data store abstraction: single module for reading and writing data files,
managing isolated session workspaces, and maintaining audit logs.
"""

from datetime import date, datetime
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import threading
from typing import Any
import pandas as pd

try:
    from src.config import DATA_DIR, PROJECT_ROOT
except ImportError:
    try:
        from config import DATA_DIR, PROJECT_ROOT
    except ImportError:
        PROJECT_ROOT = Path(__file__).resolve().parent.parent
        DATA_DIR = PROJECT_ROOT / "data"

# Seed data directory (read-only baseline)
SEED_DATA_DIR = (PROJECT_ROOT / "data").resolve()

# Regex for validating session identifiers: 8-64 alphanumeric, underscore, hyphen
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# Single-process safe only: threading.RLock protects concurrent threads within
# a single Python process. Cross-process safety (e.g., multiprocess workers)
# requires external file locks or database coordination.
_WRITE_LOCK = threading.RLock()


def _handle_remove_readonly(func, path, exc_info):
    """Clear readonly bit and retry file removal on Windows."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def get_data_dir() -> Path:
    """Return the active data directory.

    Resolves FINANCE_DATA_DIR from environment if set, otherwise defaults to DATA_DIR.
    """
    env_dir = os.getenv("FINANCE_DATA_DIR")
    if env_dir and env_dir.strip():
        return Path(env_dir.strip()).resolve()
    return Path(DATA_DIR).resolve()


def get_workspaces_dir() -> Path:
    """Return root directory for session workspaces."""
    env_dir = os.getenv("FINANCE_WORKSPACES_DIR")
    if env_dir and env_dir.strip():
        return Path(env_dir.strip()).resolve()
    return (PROJECT_ROOT / "workspaces").resolve()


def is_shared_default_dir(path: Path) -> bool:
    """Check if the given directory resolves to the shared seed data folder."""
    try:
        return path.resolve() == SEED_DATA_DIR
    except Exception:
        return False


def resolve_path(name: str | Path, data_dir: Path | str | None = None) -> Path:
    """Resolve a file path under the active data directory.

    Rejects names containing path separators ('/', '\\') or '..'.
    """
    if name is None:
        raise ValueError("File name cannot be None.")
    name_str = str(name).strip()
    if not name_str:
        raise ValueError("File name cannot be empty.")

    if "/" in name_str or "\\" in name_str or ".." in name_str:
        raise ValueError(
            f"Path traversal or directory separator detected in file name '{name}'."
        )

    active_dir = Path(data_dir).resolve() if data_dir is not None else get_data_dir()
    resolved = (active_dir / name_str).resolve()

    if resolved.parent != active_dir:
        raise ValueError(
            f"Resolved file '{resolved}' escapes target data directory '{active_dir}'."
        )

    return resolved


def _check_write_allowed(target_dir: Path) -> None:
    """Ensure writes never target the shared default seed directory."""
    if is_shared_default_dir(target_dir):
        raise PermissionError(
            f"Writes never go to a shared default folder ({target_dir}). "
            "A workspace must be created and set as the active data directory."
        )


import hashlib

def ensure_transaction_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure every row in transactions DataFrame has a stable 'id'.

    When a row has no 'id' (or null/empty), assigns 't' plus the first 10
    hex characters of sha1(date|description|amount|category|row index).
    """
    df = df.copy()
    if "id" not in df.columns:
        df["id"] = None

    new_ids = []
    for idx, row in df.iterrows():
        val = row.get("id")
        if pd.isna(val) or val is None or str(val).strip() == "" or str(val).lower() == "nan":
            row_date = "" if pd.isna(row.get("date")) else str(row.get("date"))
            desc = "" if pd.isna(row.get("description")) else str(row.get("description"))
            amt = "" if pd.isna(row.get("amount")) else str(row.get("amount"))
            cat = "" if pd.isna(row.get("category")) else str(row.get("category"))
            key = f"{row_date}|{desc}|{amt}|{cat}|{idx}"
            h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
            new_ids.append(f"t{h}")
        else:
            new_ids.append(str(val))

    df["id"] = new_ids
    return df


def read_csv(name: str | Path, data_dir: Path | str | None = None, **kwargs) -> pd.DataFrame:
    """Read a CSV file from the active data directory."""
    path = resolve_path(name, data_dir=data_dir)
    df = pd.read_csv(path, **kwargs)
    name_str = Path(name).name
    if name_str == "transactions.csv":
        df = ensure_transaction_ids(df)
    return df


def write_csv_atomic(
    name: str | Path,
    df: pd.DataFrame,
    data_dir: Path | str | None = None,
    **kwargs,
) -> Path:
    """Write DataFrame atomically to a CSV file in the active data directory.

    Writes to a temporary file in the same directory, then renames via os.replace.
    Guarded with threading.RLock (single-process safe only).
    """
    path = resolve_path(name, data_dir=data_dir)
    target_dir = path.parent
    _check_write_allowed(target_dir)

    name_str = Path(name).name
    if name_str == "transactions.csv":
        df = ensure_transaction_ids(df)

    target_dir.mkdir(parents=True, exist_ok=True)

    with _WRITE_LOCK:
        temp_file = tempfile.NamedTemporaryFile(
            dir=target_dir,
            delete=False,
            suffix=".tmp",
            mode="w",
            encoding="utf-8",
            newline="",
        )
        temp_path = Path(temp_file.name)
        try:
            temp_file.close()
            csv_kwargs = dict(kwargs)
            index = csv_kwargs.pop("index", False)
            df.to_csv(temp_path, index=index, **csv_kwargs)
            os.replace(temp_path, path)
            return path
        except Exception:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise


def read_json(name: str | Path, data_dir: Path | str | None = None) -> Any:
    """Read a JSON file from the active data directory."""
    path = resolve_path(name, data_dir=data_dir)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(
    name: str | Path,
    obj: Any,
    data_dir: Path | str | None = None,
    **kwargs,
) -> Path:
    """Write an object atomically to a JSON file in the active data directory.

    Writes to a temporary file in the same directory, then renames via os.replace.
    Guarded with threading.RLock (single-process safe only).
    """
    path = resolve_path(name, data_dir=data_dir)
    target_dir = path.parent
    _check_write_allowed(target_dir)

    target_dir.mkdir(parents=True, exist_ok=True)

    with _WRITE_LOCK:
        temp_file = tempfile.NamedTemporaryFile(
            dir=target_dir,
            delete=False,
            suffix=".tmp",
            mode="w",
            encoding="utf-8",
        )
        temp_path = Path(temp_file.name)
        try:
            json_kwargs = dict(kwargs)
            indent = json_kwargs.pop("indent", 2)
            json.dump(obj, temp_file, indent=indent, **json_kwargs)
            temp_file.flush()
            temp_file.close()
            os.replace(temp_path, path)
            return path
        except Exception:
            try:
                temp_file.close()
            except Exception:
                pass
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise


def validate_session_id(session_id: str) -> None:
    """Validate session_id matches ^[A-Za-z0-9_-]{8,64}$."""
    if not isinstance(session_id, str) or not SESSION_ID_PATTERN.match(session_id):
        raise ValueError(
            f"Invalid session_id '{session_id}'. Must match ^[A-Za-z0-9_-]{{8,64}}$ (8-64 alphanumeric, underscore, hyphen)."
        )


def create_workspace(session_id: str, base_dir: Path | str | None = None) -> Path:
    """Copy the seed data folder into workspaces/<session_id>/ if missing, and return that path."""
    validate_session_id(session_id)
    root_ws = Path(base_dir).resolve() if base_dir is not None else get_workspaces_dir()
    ws_path = (root_ws / session_id).resolve()

    if not ws_path.exists():
        ws_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            SEED_DATA_DIR,
            ws_path,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    return ws_path


def reset_workspace(session_id: str, base_dir: Path | str | None = None) -> Path:
    """Delete workspaces/<session_id>/ and recreate it from the seed data folder."""
    validate_session_id(session_id)
    root_ws = Path(base_dir).resolve() if base_dir is not None else get_workspaces_dir()
    ws_path = (root_ws / session_id).resolve()

    if ws_path.exists():
        shutil.rmtree(ws_path, onerror=_handle_remove_readonly)

    ws_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        SEED_DATA_DIR,
        ws_path,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return ws_path


def _truncate_strings(val: Any, max_len: int = 500) -> Any:
    """Recursively truncate strings to max_len characters."""
    if isinstance(val, str):
        return val[:max_len]
    elif isinstance(val, dict):
        return {k: _truncate_strings(v, max_len) for k, v in val.items()}
    elif isinstance(val, list):
        return [_truncate_strings(item, max_len) for item in val]
    elif isinstance(val, tuple):
        return tuple(_truncate_strings(item, max_len) for item in val)
    return val


def append_audit(
    action: str,
    before: Any,
    after: Any,
    source: str = "human",
    workspace: Path | str | None = None,
) -> Path:
    """Append one JSON line to <workspace>/audit.jsonl with timestamp, action,
    source ("human" or "model"), before and after. Truncates strings in before
    and after to 500 characters.
    """
    if source not in ("human", "model"):
        raise ValueError(f"Invalid source '{source}'. Must be 'human' or 'model'.")

    target_dir = Path(workspace).resolve() if workspace is not None else get_data_dir()
    _check_write_allowed(target_dir)

    target_dir.mkdir(parents=True, exist_ok=True)
    audit_file = target_dir / "audit.jsonl"

    record = {
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "source": source,
        "before": _truncate_strings(before, 500),
        "after": _truncate_strings(after, 500),
    }

    line = json.dumps(record) + "\n"

    with _WRITE_LOCK:
        with open(audit_file, "a", encoding="utf-8") as f:
            f.write(line)

    return audit_file


def read_audit(workspace: Path | str | None = None) -> list[dict]:
    """Read all audit records from <workspace>/audit.jsonl."""
    target_dir = Path(workspace).resolve() if workspace is not None else get_data_dir()
    audit_file = target_dir / "audit.jsonl"
    if not audit_file.exists():
        return []

    records = []
    with open(audit_file, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if line_str:
                records.append(json.loads(line_str))
    return records


def get_sandbox_today(workspace: Path | str | None = None) -> str:
    """Resolve the active sandbox today date according to priority order:
    1. settings.json in the active workspace / data directory (key "sandbox_today")
    2. FINANCE_AS_OF_DATE environment variable
    3. Latest transaction date in the data
    4. Fallback default '2026-08-31'
    """
    target_dir = Path(workspace).resolve() if workspace is not None else get_data_dir()

    # 1. settings.json in target directory
    settings_path = target_dir / "settings.json"
    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
            if isinstance(settings, dict):
                val = settings.get("sandbox_today")
                if val and str(val).strip():
                    return str(val).strip()
        except Exception:
            pass

    # 2. FINANCE_AS_OF_DATE environment variable
    env_date = os.getenv("FINANCE_AS_OF_DATE")
    if env_date and env_date.strip():
        return env_date.strip()

    # 3. Latest transaction date in the data
    tx_path = target_dir / "transactions.csv"
    if not tx_path.exists():
        tx_path = SEED_DATA_DIR / "transactions.csv"
    if tx_path.exists():
        try:
            df = pd.read_csv(tx_path)
            if "date" in df.columns:
                valid_dates = [
                    str(d).strip() for d in df["date"].dropna()
                    if re.match(r"^\d{4}-\d{2}-\d{2}$", str(d).strip())
                ]
                if valid_dates:
                    return max(valid_dates)
        except Exception:
            pass

    return "2026-08-31"


def set_sandbox_today(value: Any, workspace: Path | str | None = None) -> str:
    """Validate and store sandbox_today in <workspace>/settings.json.

    Validation rules:
      - Valid date (YYYY-MM-DD or date object)
      - Not before 2000-01-01
      - Not after 2100-12-31

    Writes never go to the shared default seed folder.
    """
    if value is None:
        raise ValueError("Sandbox date cannot be None.")

    val_str = str(value).strip()
    if not val_str:
        raise ValueError("Sandbox date cannot be empty.")

    try:
        d = date.fromisoformat(val_str)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid date format for sandbox_today: '{value}'. Expected YYYY-MM-DD.") from e

    min_date = date(2000, 1, 1)
    max_date = date(2100, 12, 31)
    if d < min_date or d > max_date:
        raise ValueError(
            f"Sandbox date '{d.isoformat()}' out of allowed range ({min_date.isoformat()} to {max_date.isoformat()})."
        )

    target_dir = Path(workspace).resolve() if workspace is not None else get_data_dir()
    _check_write_allowed(target_dir)

    settings_path = target_dir / "settings.json"
    settings = {}
    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    settings = loaded
        except Exception:
            settings = {}

    settings["sandbox_today"] = d.isoformat()
    write_json_atomic("settings.json", settings, data_dir=target_dir)
    return d.isoformat()


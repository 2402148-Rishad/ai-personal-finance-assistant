"""Data store abstraction: single module for reading and writing data files,
managing isolated session workspaces, and maintaining audit logs.
"""

import contextvars
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import threading
from typing import Any
import uuid
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

# ContextVar for active workspace isolation across request contexts/sessions
_ACTIVE_WORKSPACE: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "active_workspace", default=None
)


def set_active_workspace(workspace: Path | str | None) -> None:
    """Set the active workspace in the current context."""
    if workspace is None:
        _ACTIVE_WORKSPACE.set(None)
    else:
        _ACTIVE_WORKSPACE.set(Path(workspace).resolve())


def get_active_workspace() -> Path | None:
    """Get the active workspace from the current context, if set."""
    return _ACTIVE_WORKSPACE.get()


# ContextVar for recent user messages text (used for category grounding)
_RECENT_USER_TEXT: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "recent_user_text", default=None
)
recent_user_text = _RECENT_USER_TEXT


def set_recent_user_text(text: str | None) -> contextvars.Token:
    """Set the recent user text ContextVar in the current context."""
    return _RECENT_USER_TEXT.set(text)


def reset_recent_user_text(token: contextvars.Token) -> None:
    """Reset the recent user text ContextVar using the given token."""
    _RECENT_USER_TEXT.reset(token)


def get_recent_user_text() -> str | None:
    """Get the recent user text ContextVar from the current context."""
    return _RECENT_USER_TEXT.get()


def _handle_remove_readonly(func, path, exc_info):
    """Clear readonly bit and retry file removal on Windows."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def get_data_dir() -> Path:
    """Return the active data directory.

    Resolves active workspace from ContextVar if set,
    otherwise FINANCE_DATA_DIR from environment if set,
    otherwise defaults to DATA_DIR.
    """
    active_ws = get_active_workspace()
    if active_ws is not None:
        return active_ws
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


def read_csv(
    name: str | Path,
    data_dir: Path | str | None = None,
    workspace: Path | str | None = None,
    **kwargs,
) -> pd.DataFrame:
    """Read a CSV file from the active data directory."""
    path = resolve_path(name, data_dir=workspace or data_dir)
    df = pd.read_csv(path, **kwargs)
    name_str = Path(name).name
    if name_str == "transactions.csv":
        df = ensure_transaction_ids(df)
    return df


def write_csv_atomic(
    name: str | Path,
    df: pd.DataFrame,
    data_dir: Path | str | None = None,
    workspace: Path | str | None = None,
    **kwargs,
) -> Path:
    """Write DataFrame atomically to a CSV file in the active data directory.

    Writes to a temporary file in the same directory, then renames via os.replace.
    Guarded with threading.RLock (single-process safe only).
    """
    path = resolve_path(name, data_dir=workspace or data_dir)
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


def read_json(
    name: str | Path,
    data_dir: Path | str | None = None,
    workspace: Path | str | None = None,
) -> Any:
    """Read a JSON file from the active data directory."""
    path = resolve_path(name, data_dir=workspace or data_dir)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(
    name: str | Path,
    obj: Any,
    data_dir: Path | str | None = None,
    workspace: Path | str | None = None,
    **kwargs,
) -> Path:
    """Write an object atomically to a JSON file in the active data directory.

    Writes to a temporary file in the same directory, then renames via os.replace.
    Guarded with threading.RLock (single-process safe only).
    """
    path = resolve_path(name, data_dir=workspace or data_dir)
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


def cleanup_old_workspaces(max_age_hours: int = 24, base_dir: Path | str | None = None) -> list[str]:
    """Delete workspace directories in workspaces/ that have not been modified for more than max_age_hours."""
    root_ws = Path(base_dir).resolve() if base_dir is not None else get_workspaces_dir()
    if not root_ws.exists():
        return []

    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    cutoff_ts = cutoff.timestamp()
    deleted = []

    for item in root_ws.iterdir():
        if item.is_dir() and item.resolve() != SEED_DATA_DIR:
            try:
                mtimes = [item.stat().st_mtime]
                for p in item.rglob("*"):
                    try:
                        mtimes.append(p.stat().st_mtime)
                    except Exception:
                        pass
                latest_mtime = max(mtimes) if mtimes else item.stat().st_mtime
                if latest_mtime < cutoff_ts:
                    shutil.rmtree(item, onerror=_handle_remove_readonly)
                    deleted.append(item.name)
            except Exception:
                pass
    return deleted



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
    undo_token: str | None = None,
    **kwargs,
) -> Path:
    """Append one JSON line to <workspace>/audit.jsonl with timestamp, action,
    source ("human" or "model"), before, after, and optional undo_token.
    Truncates strings in before and after to 500 characters.
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
    if undo_token is not None:
        record["undo_token"] = str(undo_token)
    for k, v in kwargs.items():
        if k not in record:
            record[k] = v

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


def read_proposals(workspace: Path | str | None = None) -> dict[str, dict]:
    """Read pending proposals from <workspace>/proposals.json."""
    target_dir = Path(workspace).resolve() if workspace is not None else get_data_dir()
    path = target_dir / "proposals.json"
    if not path.exists():
        return {}
    try:
        data = read_json("proposals.json", data_dir=target_dir)
        if isinstance(data, dict):
            return data
        elif isinstance(data, list):
            return {
                str(p.get("id") or p.get("proposal_id")): p
                for p in data
                if isinstance(p, dict) and (p.get("id") or p.get("proposal_id"))
            }
        return {}
    except Exception:
        return {}


def save_proposal(proposal: dict, workspace: Path | str | None = None) -> Path:
    """Save or update a proposal in <workspace>/proposals.json using write_json_atomic."""
    target_dir = Path(workspace).resolve() if workspace is not None else get_data_dir()
    proposals = read_proposals(workspace=target_dir)
    p_id = proposal.get("id") or proposal.get("proposal_id")
    if not p_id:
        raise ValueError("Proposal must have an 'id' or 'proposal_id'.")
    proposals[str(p_id)] = proposal
    return write_json_atomic("proposals.json", proposals, data_dir=target_dir)


def create_proposal(
    kind: str,
    payload: dict,
    preview: dict,
    risk: str = "low",
    workspace: Path | str | None = None,
    proposal_id: str | None = None,
    **kwargs,
) -> dict:
    """Create, persist, and return a pending proposal in <workspace>/proposals.json.

    Each proposal has id, kind, payload, preview (before and after), risk ("low" or "high"),
    created_at, and expires_at (24 hours later).
    """
    p_id = proposal_id or f"prop_{uuid.uuid4().hex[:8]}"
    created_dt = datetime.now()
    expires_dt = created_dt + timedelta(hours=24)

    proposal = {
        "id": p_id,
        "proposal_id": p_id,
        "kind": kind,
        "payload": payload,
        "preview": preview,
        "risk": "high" if risk == "high" else "low",
        "created_at": created_dt.isoformat(),
        "expires_at": expires_dt.isoformat(),
        "status": "pending_confirmation",
    }
    proposal.update(kwargs)

    save_proposal(proposal, workspace=workspace)
    return proposal


def search_transactions(
    query: str | None = None,
    category: str | None = None,
    start_date: str | date | None = None,
    end_date: str | date | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    tx_type: str | None = None,
    workspace: Path | str | None = None,
) -> pd.DataFrame:
    """Search and filter transactions from the active workspace."""
    target_dir = Path(workspace).resolve() if workspace is not None else get_data_dir()
    tx_path = target_dir / "transactions.csv"
    if not tx_path.exists():
        return pd.DataFrame(columns=["id", "date", "month", "category", "description", "type", "amount"])

    df = read_csv("transactions.csv", workspace=target_dir)
    if df.empty:
        return df

    mask = pd.Series([True] * len(df), index=df.index)

    if query and str(query).strip():
        q = str(query).strip().lower()
        desc_match = df["description"].astype(str).str.lower().str.contains(q, na=False)
        cat_match = df["category"].astype(str).str.lower().str.contains(q, na=False)
        id_match = df["id"].astype(str).str.lower().str.contains(q, na=False) if "id" in df.columns else False
        mask &= (desc_match | cat_match | id_match)

    if category and str(category).strip() and str(category).lower() != "all":
        cat_filter = str(category).strip().lower()
        mask &= (df["category"].astype(str).str.lower() == cat_filter)

    if tx_type and str(tx_type).strip() and str(tx_type).lower() != "all":
        t_filter = str(tx_type).strip().lower()
        mask &= (df["type"].astype(str).str.lower() == t_filter)

    if start_date:
        s_date = str(start_date).strip()
        mask &= (df["date"].astype(str) >= s_date)

    if end_date:
        e_date = str(end_date).strip()
        mask &= (df["date"].astype(str) <= e_date)

    if min_amount is not None:
        try:
            min_val = float(min_amount)
            if min_val > 0:
                mask &= (df["amount"].astype(float) >= min_val)
        except (ValueError, TypeError):
            pass

    if max_amount is not None:
        try:
            max_val = float(max_amount)
            if max_val > 0:
                mask &= (df["amount"].astype(float) <= max_val)
        except (ValueError, TypeError):
            pass

    filtered = df[mask].copy()
    if "date" in filtered.columns:
        filtered = filtered.sort_values(by="date", ascending=False)
    return filtered


def add_transaction(
    row_data: dict[str, Any],
    workspace: Path | str | None = None,
    source: str = "human",
) -> dict[str, Any]:
    """Validate and atomically add a transaction to transactions.csv with an audit log line."""
    try:
        from src.validators import validate_amount, validate_category, validate_date, validate_text
    except ImportError:
        from validators import validate_amount, validate_category, validate_date, validate_text

    target_dir = Path(workspace).resolve() if workspace is not None else get_data_dir()

    date_val = row_data.get("date")
    ok_date, clean_date = validate_date(date_val, workspace=target_dir)
    if not ok_date:
        raise ValueError(clean_date)

    amount_val = row_data.get("amount")
    ok_amt, clean_amt = validate_amount(amount_val)
    if not ok_amt:
        raise ValueError(clean_amt)

    cat_val = row_data.get("category", "")
    ok_cat, clean_cat = validate_category(cat_val, workspace=target_dir)
    if not ok_cat:
        raise ValueError(clean_cat)

    desc_val = row_data.get("description")
    if not desc_val or not str(desc_val).strip():
        desc_val = f"{clean_cat} expense"
    elif clean_cat and str(desc_val).strip().lower() == clean_cat.lower():
        desc_val = f"{clean_cat} expense"

    ok_desc, clean_desc = validate_text(desc_val)
    if not ok_desc:
        raise ValueError(clean_desc)

    type_val = str(row_data.get("type", "expense")).strip().lower()
    if type_val not in ("expense", "income"):
        raise ValueError("Type must be either 'expense' or 'income'.")

    df = read_csv("transactions.csv", workspace=target_dir)

    new_id = f"t{uuid.uuid4().hex[:10]}"
    month_val = clean_date[:7]

    new_record = {
        "id": new_id,
        "date": clean_date,
        "month": month_val,
        "category": clean_cat,
        "description": clean_desc,
        "type": type_val,
        "amount": clean_amt,
    }

    new_row_df = pd.DataFrame([new_record])
    updated_df = pd.concat([df, new_row_df], ignore_index=True)
    write_csv_atomic("transactions.csv", updated_df, workspace=target_dir)

    append_audit(
        action="add_transaction",
        before=None,
        after=new_record,
        source=source,
        workspace=target_dir,
    )
    return new_record


def update_transaction(
    tx_id: str,
    updated_fields: dict[str, Any],
    workspace: Path | str | None = None,
    source: str = "human",
) -> dict[str, Any]:
    """Validate and atomically update an existing transaction in transactions.csv with an audit log line."""
    try:
        from src.validators import validate_amount, validate_category, validate_date, validate_text
    except ImportError:
        from validators import validate_amount, validate_category, validate_date, validate_text

    target_dir = Path(workspace).resolve() if workspace is not None else get_data_dir()
    df = read_csv("transactions.csv", workspace=target_dir)

    if "id" not in df.columns:
        raise ValueError("Transactions file has no id column.")

    matches = df.index[df["id"].astype(str) == str(tx_id)].tolist()
    if not matches:
        raise ValueError(f"Transaction with id '{tx_id}' not found.")

    row_idx = matches[0]
    old_row = df.loc[row_idx].to_dict()

    new_row = dict(old_row)

    if "date" in updated_fields:
        ok_date, clean_date = validate_date(updated_fields["date"], workspace=target_dir)
        if not ok_date:
            raise ValueError(clean_date)
        new_row["date"] = clean_date
        new_row["month"] = clean_date[:7]

    if "amount" in updated_fields:
        ok_amt, clean_amt = validate_amount(updated_fields["amount"])
        if not ok_amt:
            raise ValueError(clean_amt)
        new_row["amount"] = clean_amt

    if "description" in updated_fields:
        ok_desc, clean_desc = validate_text(updated_fields["description"])
        if not ok_desc:
            raise ValueError(clean_desc)
        new_row["description"] = clean_desc

    if "category" in updated_fields:
        ok_cat, clean_cat = validate_category(updated_fields["category"], workspace=target_dir)
        if not ok_cat:
            raise ValueError(clean_cat)
        new_row["category"] = clean_cat

    if "type" in updated_fields:
        t_val = str(updated_fields["type"]).strip().lower()
        if t_val not in ("expense", "income"):
            raise ValueError("Type must be either 'expense' or 'income'.")
        new_row["type"] = t_val

    for col, val in new_row.items():
        df.at[row_idx, col] = val

    write_csv_atomic("transactions.csv", df, workspace=target_dir)

    append_audit(
        action="update_transaction",
        before=old_row,
        after=new_row,
        source=source,
        workspace=target_dir,
    )
    return new_row


def delete_transaction(
    tx_id: str,
    workspace: Path | str | None = None,
    source: str = "human",
) -> dict[str, Any]:
    """Atomically delete a transaction by id with an audit log line."""
    target_dir = Path(workspace).resolve() if workspace is not None else get_data_dir()
    df = read_csv("transactions.csv", workspace=target_dir)

    if "id" not in df.columns:
        raise ValueError("Transactions file has no id column.")

    matches = df.index[df["id"].astype(str) == str(tx_id)].tolist()
    if not matches:
        raise ValueError(f"Transaction with id '{tx_id}' not found.")

    row_idx = matches[0]
    old_row = df.loc[row_idx].to_dict()

    updated_df = df.drop(index=row_idx).reset_index(drop=True)
    write_csv_atomic("transactions.csv", updated_df, workspace=target_dir)

    append_audit(
        action="delete_transaction",
        before=old_row,
        after=None,
        source=source,
        workspace=target_dir,
    )
    return old_row


def import_transactions(
    records: list[dict[str, Any]],
    workspace: Path | str | None = None,
    source: str = "human",
) -> int:
    """Atomically append a list of validated records to transactions.csv and write one audit line."""
    if not records:
        return 0

    target_dir = Path(workspace).resolve() if workspace is not None else get_data_dir()
    df = read_csv("transactions.csv", workspace=target_dir)

    cleaned_records = []
    for r in records:
        rec = dict(r)
        if "id" not in rec or not rec["id"]:
            rec["id"] = f"t{uuid.uuid4().hex[:10]}"
        if "month" not in rec or not rec["month"]:
            rec["month"] = str(rec.get("date", ""))[:7]
        if "description" in rec and rec["description"] is not None:
            try:
                from src.validators import validate_text
                ok, clean_d = validate_text(rec["description"])
                if ok:
                    rec["description"] = clean_d
            except Exception:
                pass
        cleaned_records.append(rec)

    new_rows_df = pd.DataFrame(cleaned_records)
    updated_df = pd.concat([df, new_rows_df], ignore_index=True)
    write_csv_atomic("transactions.csv", updated_df, workspace=target_dir)

    append_audit(
        action="import_transactions",
        before=None,
        after={"count": len(cleaned_records), "items": cleaned_records},
        source=source,
        workspace=target_dir,
    )
    return len(cleaned_records)


DEFAULT_PREFERENCES: dict[str, Any] = {
    "savings_target_percent": 20,
    "alert_bills_days": 3,
    "currency_label": "$",
}


def get_preferences(workspace: Path | str | None = None) -> dict[str, Any]:
    """Read preferences from <workspace>/preferences.json.
    Returns defaults if the file is missing or invalid.
    """
    target_dir = Path(workspace).resolve() if workspace is not None else get_data_dir()
    path = target_dir / "preferences.json"
    if not path.exists():
        return dict(DEFAULT_PREFERENCES)
    try:
        data = read_json("preferences.json", data_dir=target_dir)
        if isinstance(data, dict):
            res = dict(DEFAULT_PREFERENCES)
            res.update(data)
            return res
    except Exception:
        pass
    return dict(DEFAULT_PREFERENCES)


def save_preferences(
    prefs: dict[str, Any],
    source: str = "human",
    workspace: Path | str | None = None,
) -> dict[str, Any]:
    """Validate and atomically write preferences to <workspace>/preferences.json with an audit entry."""
    try:
        from src.validators import validate_preferences
    except ImportError:
        from validators import validate_preferences

    target_dir = Path(workspace).resolve() if workspace is not None else get_data_dir()
    old_prefs = get_preferences(workspace=target_dir)

    # Merge with current preferences so partial updates are allowed
    merged = dict(old_prefs)
    merged.update(prefs)

    ok, validated = validate_preferences(merged)
    if not ok:
        raise ValueError(validated)

    write_json_atomic("preferences.json", validated, data_dir=target_dir)
    append_audit(
        action="save_preferences",
        before=old_prefs,
        after=validated,
        source=source,
        workspace=target_dir,
    )
    return validated


def get_goals(workspace: Path | str | None = None) -> list[dict[str, Any]]:
    """Read list of goals from <workspace>/goals.json.
    Returns empty list if the file is missing or invalid.
    """
    target_dir = Path(workspace).resolve() if workspace is not None else get_data_dir()
    path = target_dir / "goals.json"
    if not path.exists():
        return []
    try:
        data = read_json("goals.json", data_dir=target_dir)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


read_goals = get_goals


def save_goals(
    goals: list[dict[str, Any]],
    source: str = "human",
    action: str = "save_goals",
    before: Any = None,
    workspace: Path | str | None = None,
) -> Path:
    """Atomically write goals list to <workspace>/goals.json with an audit entry."""
    target_dir = Path(workspace).resolve() if workspace is not None else get_data_dir()
    path = write_json_atomic("goals.json", goals, data_dir=target_dir)
    append_audit(
        action=action,
        before=before,
        after=goals,
        source=source,
        workspace=target_dir,
    )
    return path


def add_goal(
    goal_data: dict[str, Any],
    source: str = "human",
    workspace: Path | str | None = None,
) -> dict[str, Any]:
    """Validate and atomically add a goal to <workspace>/goals.json with an audit entry."""
    try:
        from src.validators import validate_goal
    except ImportError:
        from validators import validate_goal

    target_dir = Path(workspace).resolve() if workspace is not None else get_data_dir()
    ok, clean_goal = validate_goal(goal_data, workspace=target_dir, is_update=False)
    if not ok:
        raise ValueError(clean_goal)

    goals = get_goals(workspace=target_dir)
    goals.append(clean_goal)
    save_goals(goals, source=source, action="add_goal", before=None, workspace=target_dir)
    return clean_goal


def update_goal(
    goal_id: str,
    updates: dict[str, Any],
    source: str = "human",
    workspace: Path | str | None = None,
) -> dict[str, Any]:
    """Validate and atomically update a goal by id in <workspace>/goals.json with an audit entry."""
    try:
        from src.validators import validate_goal
    except ImportError:
        from validators import validate_goal

    target_dir = Path(workspace).resolve() if workspace is not None else get_data_dir()
    goals = get_goals(workspace=target_dir)
    matched_idx = None
    for idx, g in enumerate(goals):
        if str(g.get("id")) == str(goal_id):
            matched_idx = idx
            break

    if matched_idx is None:
        raise ValueError(f"Goal with id '{goal_id}' not found.")

    old_goal = dict(goals[matched_idx])
    merged = dict(old_goal)
    merged.update(updates)

    ok, clean_goal = validate_goal(merged, workspace=target_dir, is_update=True)
    if not ok:
        raise ValueError(clean_goal)

    goals[matched_idx] = clean_goal
    save_goals(goals, source=source, action="update_goal", before=old_goal, workspace=target_dir)
    return clean_goal


def delete_goal(
    goal_id: str,
    source: str = "human",
    workspace: Path | str | None = None,
) -> dict[str, Any]:
    """Atomically delete a goal by id from <workspace>/goals.json with an audit entry."""
    target_dir = Path(workspace).resolve() if workspace is not None else get_data_dir()
    goals = get_goals(workspace=target_dir)
    matched_idx = None
    for idx, g in enumerate(goals):
        if str(g.get("id")) == str(goal_id):
            matched_idx = idx
            break

    if matched_idx is None:
        raise ValueError(f"Goal with id '{goal_id}' not found.")

    old_goal = goals[matched_idx]
    updated_goals = [g for i, g in enumerate(goals) if i != matched_idx]
    save_goals(updated_goals, source=source, action="delete_goal", before=old_goal, workspace=target_dir)
    return old_goal





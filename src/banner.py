"""Banner logic for Fin application ("Do this next" interim banner)."""

import json
from pathlib import Path
from src.approvals import list_pending
from src.store import get_sandbox_today
from src.tools import upcoming_bills


def get_do_this_next_banner(workspace: Path | str | None = None) -> str:
    """Interim deterministic rules, checked in order:
    a. Pending proposals exist: "N changes are waiting for approval. Open Inbox."
    b. A bill is due within 3 days: "<bill> is due <date>."
    c. Otherwise: "Add today's expenses in Ledger, or ask Fin about your month."
    Phase 5 replaces this with get_alerts().
    """
    try:
        pending = list_pending(workspace=workspace)
        if pending:
            n = len(pending)
            change_str = "1 change is" if n == 1 else f"{n} changes are"
            return f"{change_str} waiting for approval."
    except Exception:
        pass

    try:
        today = get_sandbox_today(workspace=workspace)
        raw_bills = upcoming_bills(today=today, days_ahead=3)
        data = json.loads(raw_bills)
        bills = data.get("upcoming_bills", [])
        if bills:
            bills.sort(key=lambda x: x.get("days_until_due", 0))
            first = bills[0]
            name = first.get("bill_name", "Bill")
            due = first.get("due_date", "")
            return f"{name} is due {due}."
    except Exception:
        pass

    return "Add today's expenses in Ledger, or ask Fin about your month."

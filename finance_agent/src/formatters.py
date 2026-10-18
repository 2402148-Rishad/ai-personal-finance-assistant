from datetime import datetime
from pathlib import Path
from typing import Any
import json

import src.store as store


def format_date_human(d_str: Any) -> str:
    """Format YYYY-MM-DD or date object into '31 Aug 2026'."""
    if not d_str:
        return ""
    try:
        s = str(d_str).strip()[:10]
        d = datetime.strptime(s, "%Y-%m-%d")
        return f"{d.day} {d.strftime('%b %Y')}"
    except Exception:
        return str(d_str)


def format_expiry(expires_at: str | None, now_dt: datetime) -> str:
    """Format proposal expiry into 'Expires in 23 h 59 min' or 'Expired'."""
    if not expires_at:
        return "Expired"
    try:
        exp_dt = datetime.fromisoformat(str(expires_at))
        if now_dt >= exp_dt:
            return "Expired"
        diff = exp_dt - now_dt
        total_seconds = int(diff.total_seconds())
        if total_seconds <= 0:
            return "Expired"
        hours = total_seconds // 3600
        mins = (total_seconds % 3600) // 60
        return f"Expires in {hours} h {mins} min"
    except Exception:
        return "Expired"


def format_card_value(v: Any) -> str:
    """Format a proposal before/after value into readable plain lines, such as '$45.00 · Groceries · 31 Aug 2026'."""
    if v is None:
        return "*(none)*"
    if isinstance(v, (int, float)):
        return f"${float(v):,.2f}"
    if isinstance(v, dict):
        # 1. Goal dictionary formatting
        if "target_amount" in v or "saved_so_far" in v or ("name" in v and "target_date" in v):
            name = str(v.get("name", "Goal"))
            t_amt = v.get("target_amount")
            t_date = v.get("target_date")
            saved = v.get("saved_so_far", 0.0)

            if t_amt is not None:
                amt_f = float(t_amt)
                amt_str = f"${int(amt_f):,}" if amt_f.is_integer() else f"${amt_f:,.2f}"
            else:
                amt_str = "$0"

            date_str = format_date_human(t_date) if t_date else ""

            if saved is not None:
                saved_f = float(saved)
                saved_str = f"${int(saved_f):,}" if saved_f.is_integer() else f"${saved_f:,.2f}"
            else:
                saved_str = "$0"

            parts = [f"Goal: {name}."]
            if date_str:
                parts.append(f"Target {amt_str} by {date_str}.")
            else:
                parts.append(f"Target {amt_str}.")
            parts.append(f"Saved so far {saved_str}.")
            return " ".join(parts)

        # 2. Preferences dictionary formatting
        if "savings_target_percent" in v or "alert_bills_days" in v or "currency_label" in v:
            parts = []
            if "savings_target_percent" in v:
                st_val = v["savings_target_percent"]
                st_str = f"{int(st_val)}" if isinstance(st_val, (int, float)) and float(st_val).is_integer() else f"{st_val}"
                parts.append(f"savings target {st_str}%")
            if "alert_bills_days" in v:
                ab_val = v["alert_bills_days"]
                ab_str = f"{int(ab_val)}" if isinstance(ab_val, (int, float)) and float(ab_val).is_integer() else f"{ab_val}"
                parts.append(f"bill alerts {ab_str} days ahead")
            if "currency_label" in v:
                parts.append(f"currency label {v['currency_label']}")
            return "Preferences: " + ", ".join(parts) + "."

        amt = v.get("amount")
        cat = v.get("category", "")
        d_val = v.get("date")
        if amt is not None:
            parts = [f"${float(amt):,.2f}"]
            if cat:
                parts.append(str(cat))
            if d_val:
                parts.append(format_date_human(d_val))
            return " · ".join(parts)
        if "new_limit" in v or "previous_limit" in v or "limit" in v or "old_limit" in v:
            lim = (
                v.get("new_limit")
                if v.get("new_limit") is not None
                else (
                    v.get("limit")
                    if v.get("limit") is not None
                    else (v.get("previous_limit") if v.get("previous_limit") is not None else v.get("old_limit"))
                )
            )
            cat_name = v.get("category", "")
            prefix = f"{cat_name}: " if cat_name else ""
            return f"{prefix}${float(lim):,.2f}" if lim is not None else "*(none)*"
        items_s = [f"{k}: {val}" for k, val in v.items() if val is not None]
        return " · ".join(items_s) if items_s else "*(none)*"
    if isinstance(v, list):
        if not v:
            return "*(none)*"
        lines = []
        for it in v:
            if isinstance(it, dict):
                lines.append(format_card_value(it))
            else:
                lines.append(str(it))
        return "\n\n".join(lines)
    return str(v)


def get_next_undo_line(workspace: Path | str | None = None) -> str:
    """Return a descriptive line explaining what the Undo button will revert."""
    try:
        audit_records = store.read_audit(workspace=workspace)
        if not audit_records:
            return "Nothing to undo yet."

        undone_tokens = {
            rec.get("undone_token")
            for rec in audit_records
            if rec.get("action") == "undo" and rec.get("undone_token")
        }

        target_rec = None
        for rec in reversed(audit_records):
            action = rec.get("action", "")
            if action == "undo":
                continue
            if rec.get("source") == "human" and rec.get("undo_token"):
                token = rec["undo_token"]
                if token not in undone_tokens:
                    target_rec = rec
                    break

        if target_rec is None:
            return "Nothing to undo yet."

        action = target_rec.get("action", "")
        before = target_rec.get("before") or {}
        after = target_rec.get("after") or {}
        kind = target_rec.get("kind") or (before.get("kind") if isinstance(before, dict) else None)

        if action == "add_transaction" or kind == "add_transactions" or action == "approve_add_transactions":
            item = None
            if isinstance(after, dict) and after.get("amount") is not None:
                item = after
            elif isinstance(before, dict) and before.get("items"):
                items_list = before["items"]
                if len(items_list) == 1:
                    item = items_list[0]
                else:
                    return f"Next undo: remove {len(items_list)} added transactions."
            elif isinstance(after, dict) and after.get("items"):
                items_list = after["items"]
                if len(items_list) == 1:
                    item = items_list[0]
                else:
                    return f"Next undo: remove {len(items_list)} added transactions."

            if item:
                amt = float(item.get("amount", 0.0))
                desc = item.get("description", "expense")
                d_val = item.get("date")
                d_str = format_date_human(d_val)
                date_part = f" from {d_str}" if d_str else ""
                return f"Next undo: remove ${amt:,.2f} {desc}{date_part}."
            return "Next undo: remove added transaction."

        if action == "update_transaction" or kind == "update_transaction" or action == "approve_update_transaction":
            desc = (before.get("description") if isinstance(before, dict) else None) or (after.get("description") if isinstance(after, dict) else None) or "transaction"
            d_val = (before.get("date") if isinstance(before, dict) else None) or (after.get("date") if isinstance(after, dict) else None)
            d_str = format_date_human(d_val)
            date_part = f" on {d_str}" if d_str else ""
            return f"Next undo: revert update to {desc}{date_part}."

        if action == "delete_transaction" or kind == "delete_transaction" or action == "approve_delete_transaction":
            amt = float(before.get("amount", 0.0)) if isinstance(before, dict) and before.get("amount") is not None else None
            desc = before.get("description", "transaction") if isinstance(before, dict) else "transaction"
            d_val = before.get("date") if isinstance(before, dict) else None
            d_str = format_date_human(d_val)
            date_part = f" from {d_str}" if d_str else ""
            amt_part = f"${amt:,.2f} " if amt is not None else ""
            return f"Next undo: restore {amt_part}{desc}{date_part}."

        if kind == "budget_change" or action == "approve_budget_change":
            cat = before.get("category") if isinstance(before, dict) else None
            prev_limit = before.get("previous_limit") if isinstance(before, dict) else None
            if cat and prev_limit is not None:
                return f"Next undo: restore {cat} budget to ${float(prev_limit):,.2f}."
            elif cat:
                return f"Next undo: revert budget change for {cat}."
            return "Next undo: revert budget change."

        if kind == "bill_change" or action == "approve_bill_change":
            bill_name = before.get("bill_name") if isinstance(before, dict) else None
            if bill_name:
                return f"Next undo: revert bill change for {bill_name}."
            return "Next undo: revert bill change."

        clean_act = action.replace("_", " ").strip()
        return f"Next undo: revert {clean_act}."
    except Exception:
        return "Nothing to undo yet."

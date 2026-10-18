"""Alerts engine for Fin: detects critical financial conditions needing attention."""

from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
import pandas as pd

from src import approvals
from src import store
from src import tools


def get_alerts(workspace: Path | str | None = None) -> list[dict]:
    """Return a list of current financial alerts, most urgent first.

    Each alert is a dictionary with:
      id: str (unique identifier)
      level: 'urgent' | 'warning' | 'info'
      text: str (plain English, no IDs or ISO timestamps)
      action: 'Open Inbox' | 'Open Plan' | 'Open Ledger'
    """
    target_dir = Path(workspace).resolve() if workspace is not None else (store.get_active_workspace() or store.get_data_dir())
    orig_ws = store.get_active_workspace()
    if workspace is not None:
        store.set_active_workspace(target_dir)

    try:
        tx_path = target_dir / "transactions.csv"
        bills_path = target_dir / "bills.csv"
        budgets_path = target_dir / "budgets.json"
        account_path = target_dir / "account.json"
        props_path = target_dir / "proposals.json"
        pending_props_path = target_dir / "pending_proposals.json"

        # If directory is completely empty or has no financial files, return empty alerts list
        if not (tx_path.exists() or bills_path.exists() or budgets_path.exists() or account_path.exists() or props_path.exists() or pending_props_path.exists()):
            return []

        today = store.get_sandbox_today(workspace=target_dir)
        try:
            today_dt = date.fromisoformat(today)
        except Exception:
            today_dt = date.today()
        current_month = today[:7]

        alerts: list[dict] = []

        # 1. The 30-day cash projection goes below zero
        try:
            raw_cf = tools.cashflow_projection(today=today, days_ahead=30)
            cf_data = json.loads(raw_cf)
            if isinstance(cf_data, dict) and "error" not in cf_data:
                lowest_bal = cf_data.get("lowest_balance")
                if lowest_bal is None:
                    lowest_bal = cf_data.get("lowest_projected_balance")
                if lowest_bal is not None and float(lowest_bal) < 0.0:
                    alerts.append({
                        "id": "cashflow_negative",
                        "level": "urgent",
                        "text": "Your projected cash balance drops below zero in the next 30 days.",
                        "action": "Open Plan",
                        "priority": 1,
                    })
        except Exception:
            pass

        # 2. A pending proposal expires within 2 hours
        try:
            pending = approvals.list_pending(workspace=target_dir)
            now_dt = datetime.now()
            for p in pending:
                exp_str = p.get("expires_at")
                if exp_str:
                    try:
                        exp_dt = datetime.fromisoformat(str(exp_str))
                        time_left = exp_dt - now_dt
                        if timedelta(0) <= time_left <= timedelta(hours=2):
                            clean_pid = re.sub(r"[^a-zA-Z0-9_]", "_", str(p.get("id") or p.get("proposal_id", "1")))
                            alerts.append({
                                "id": f"proposal_expiring_{clean_pid}",
                                "level": "urgent",
                                "text": "A pending proposal expires in less than 2 hours.",
                                "action": "Open Inbox",
                                "priority": 2,
                            })
                            break
                    except Exception:
                        pass
        except Exception:
            pass

        # 3. A bill due within 3 days, or overdue
        try:
            if bills_path.exists():
                df_bills = store.read_csv("bills.csv", workspace=target_dir)
                df_tx = store.read_csv("transactions.csv", workspace=target_dir) if tx_path.exists() else pd.DataFrame()

                paid_cats = set()
                paid_descs = set()
                if not df_tx.empty and "month" in df_tx.columns and "type" in df_tx.columns:
                    m_exp = df_tx[(df_tx["month"] == current_month) & (df_tx["type"] == "expense")]
                    if not m_exp.empty:
                        if "category" in m_exp.columns:
                            paid_cats = set(m_exp["category"].dropna().astype(str).str.lower().unique())
                        if "description" in m_exp.columns:
                            paid_descs = set(m_exp["description"].dropna().astype(str).str.lower().unique())

                if not df_bills.empty:
                    # Check overdue bills
                    for _, row in df_bills.iterrows():
                        b_name = str(row.get("bill_name", "Bill")).strip()
                        clean_bname = re.sub(r"[^a-zA-Z0-9_]", "_", b_name.lower())
                        b_cat = str(row.get("category", "")).strip().lower()

                        is_overdue = False
                        if "due_date" in row and pd.notna(row["due_date"]) and str(row["due_date"]).strip():
                            d_str = str(row["due_date"]).strip()
                            if d_str < today:
                                is_paid = (b_cat in paid_cats) or any(b_name.lower() in d for d in paid_descs)
                                if not is_paid:
                                    is_overdue = True
                        elif "due_day" in row and pd.notna(row["due_day"]):
                            try:
                                d_day = int(row["due_day"])
                                if d_day < today_dt.day:
                                    is_paid = (b_cat in paid_cats) or any(b_name.lower() in d for d in paid_descs)
                                    if not is_paid:
                                        is_overdue = True
                            except Exception:
                                pass

                        if is_overdue:
                            alerts.append({
                                "id": f"bill_overdue_{clean_bname}",
                                "level": "urgent",
                                "text": f"{b_name} is overdue.",
                                "action": "Open Plan",
                                "priority": 3,
                            })

            # Check bills due within 3 days
            raw_bills = tools.upcoming_bills(today=today, days_ahead=3)
            bills_data = json.loads(raw_bills)
            if isinstance(bills_data, dict) and "error" not in bills_data:
                for b in bills_data.get("upcoming_bills", []):
                    b_name = str(b.get("bill_name", "Bill")).strip()
                    clean_bname = re.sub(r"[^a-zA-Z0-9_]", "_", b_name.lower())
                    days = int(b.get("days_until_due", 0))
                    if 0 <= days <= 3:
                        if not any(a["id"] == f"bill_overdue_{clean_bname}" for a in alerts):
                            if days == 0:
                                txt = f"{b_name} is due today."
                                lvl = "urgent"
                            elif days == 1:
                                txt = f"{b_name} is due tomorrow."
                                lvl = "warning"
                            else:
                                txt = f"{b_name} is due in {days} days."
                                lvl = "warning"
                            alerts.append({
                                "id": f"bill_due_{clean_bname}",
                                "level": lvl,
                                "text": txt,
                                "action": "Open Plan",
                                "priority": 4 + days * 0.1,
                            })
        except Exception:
            pass

        # 4. A budget at 80% or more of its limit this month, or over it
        try:
            raw_bs = tools.budget_status(month=current_month)
            bs_data = json.loads(raw_bs)
            if isinstance(bs_data, dict) and "error" not in bs_data:
                cat_map = bs_data.get("categories", {})
                for cat, info in cat_map.items():
                    lim = float(info.get("limit", 0.0))
                    spent = float(info.get("spent", 0.0))
                    is_over = bool(info.get("is_over_budget", False))
                    pct = info.get("percent_used")
                    clean_cat = re.sub(r"[^a-zA-Z0-9_]", "_", str(cat).lower())
                    if lim > 0:
                        if is_over or spent >= lim:
                            alerts.append({
                                "id": f"budget_over_{clean_cat}",
                                "level": "warning",
                                "text": f"You are over your {cat} budget this month.",
                                "action": "Open Plan",
                                "priority": 5,
                            })
                        elif pct is not None and pct >= 80.0:
                            pct_int = int(round(pct))
                            alerts.append({
                                "id": f"budget_warning_{clean_cat}",
                                "level": "warning",
                                "text": f"You have used {pct_int}% of your {cat} budget this month.",
                                "action": "Open Plan",
                                "priority": 6 + (100 - pct) * 0.01,
                            })
        except Exception:
            pass

        # 5. A transaction with a missing category or a zero amount
        try:
            if tx_path.exists():
                df_tx = store.read_csv("transactions.csv", workspace=target_dir)
                if not df_tx.empty:
                    has_missing_cat = False
                    has_zero_amt = False
                    for _, r in df_tx.iterrows():
                        c_val = r.get("category")
                        a_val = r.get("amount")
                        if pd.isna(c_val) or str(c_val).strip() in ("", "None", "nan", "Uncategorized", "uncategorized"):
                            has_missing_cat = True
                        try:
                            if pd.isna(a_val) or float(a_val) == 0.0:
                                has_zero_amt = True
                        except Exception:
                            has_zero_amt = True

                    if has_missing_cat:
                        alerts.append({
                            "id": "tx_missing_category",
                            "level": "info",
                            "text": "A transaction in Ledger is missing a category.",
                            "action": "Open Ledger",
                            "priority": 7.1,
                        })
                    if has_zero_amt:
                        alerts.append({
                            "id": "tx_zero_amount",
                            "level": "info",
                            "text": "A transaction in Ledger has a zero amount.",
                            "action": "Open Ledger",
                            "priority": 7.2,
                        })
        except Exception:
            pass

        # Sort alerts: most urgent first (urgent -> warning -> info, then priority, then id)
        level_ranks = {"urgent": 0, "warning": 1, "info": 2}
        alerts.sort(key=lambda a: (level_ranks.get(a.get("level"), 9), a.get("priority", 99), a.get("id", "")))

        # Clean up internal sorting metadata
        for a in alerts:
            a.pop("priority", None)

        return alerts

    finally:
        if workspace is not None:
            store.set_active_workspace(orig_ws)

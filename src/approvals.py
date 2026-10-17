"""Out-of-band budget and finance proposals approval engine.

Provides:
- list_pending(): returns unexpired proposals and marks expired ones.
- approve(proposal_id, answer): applies low-risk on 'yes', high-risk on 'CONFIRM'.
- reject(proposal_id): removes proposal and writes audit line.
- approve_all(answer): applies every unexpired low-risk proposal.
- undo(): reverts the most recent human-applied action that has not been undone.
- Backward-compatible wrappers confirm_approval and request_approval.

Neither calls input() nor print().
"""

from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any
import uuid
import pandas as pd

try:
    from src.config import BUDGETS_PATH, PROJECT_ROOT
except ImportError:
    try:
        from config import BUDGETS_PATH, PROJECT_ROOT
    except ImportError:
        PROJECT_ROOT = Path(__file__).resolve().parent.parent
        BUDGETS_PATH = PROJECT_ROOT / "data" / "budgets.json"

LOGS_DIR = PROJECT_ROOT / "logs"
PROPOSALS_PATH = LOGS_DIR / "pending_proposals.json"

from src.logger import log_event
import src.store as store


def _resolve_workspace(workspace: Path | str | None = None) -> Path:
    """Resolve target workspace directory, honoring explicit args, active context, env vars, or monkeypatched paths."""
    if workspace is not None:
        return Path(workspace).resolve()
    active_ws = store.get_active_workspace()
    if active_ws is not None:
        return active_ws
    env_dir = os.getenv("FINANCE_DATA_DIR")
    if env_dir and env_dir.strip():
        return Path(env_dir.strip()).resolve()
    if BUDGETS_PATH and not store.is_shared_default_dir(BUDGETS_PATH.parent):
        return BUDGETS_PATH.parent.resolve()
    if PROPOSALS_PATH and not store.is_shared_default_dir(PROPOSALS_PATH.parent) and PROPOSALS_PATH.parent != LOGS_DIR:
        return PROPOSALS_PATH.parent.resolve()
    return store.get_data_dir()


def _load_proposals(workspace: Path | str | None = None) -> dict[str, dict]:
    """Helper to load all proposals from active workspace and monkeypatched PROPOSALS_PATH."""
    target_dir = _resolve_workspace(workspace)
    props: dict[str, dict] = {}

    try:
        store_props = store.read_proposals(workspace=target_dir)
        if isinstance(store_props, dict):
            props.update(store_props)
    except Exception:
        pass

    if PROPOSALS_PATH and PROPOSALS_PATH.exists():
        try:
            with open(PROPOSALS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    props.update(data)
                elif isinstance(data, list):
                    for p in data:
                        if isinstance(p, dict):
                            p_id = str(p.get("id") or p.get("proposal_id"))
                            if p_id:
                                props[p_id] = p
        except Exception:
            pass

    return props


def _save_proposals(proposals: dict[str, dict], workspace: Path | str | None = None) -> None:
    """Save proposals dict atomically to workspace proposals.json and monkeypatched PROPOSALS_PATH."""
    target_dir = _resolve_workspace(workspace)
    try:
        store.write_json_atomic("proposals.json", proposals, workspace=target_dir)
    except Exception:
        pass

    if PROPOSALS_PATH and not store.is_shared_default_dir(PROPOSALS_PATH.parent):
        try:
            PROPOSALS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(PROPOSALS_PATH, "w", encoding="utf-8") as f:
                json.dump(proposals, f, indent=2)
        except Exception:
            pass


def list_pending(workspace: Path | str | None = None) -> list[dict]:
    """Return only unexpired proposals from the active workspace, and mark expired ones as expired.

    Neither calls input() nor print().
    """
    ws = _resolve_workspace(workspace)
    proposals = _load_proposals(workspace=ws)
    now = datetime.now()
    unexpired = []
    dirty = False

    for p_id, p in proposals.items():
        status = p.get("status", "pending_confirmation")
        expires_at = p.get("expires_at")
        is_expired = False
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at)
                if now >= exp_dt:
                    is_expired = True
            except Exception:
                pass

        if is_expired:
            if status != "expired":
                p["status"] = "expired"
                dirty = True
        elif status == "pending_confirmation":
            unexpired.append(p)

    if dirty:
        _save_proposals(proposals, workspace=ws)

    return unexpired


def approve(proposal_id: str, answer: str, workspace: Path | str | None = None) -> dict:
    """Apply a low-risk proposal only when answer is exactly 'yes'.
    A high-risk proposal requires answer exactly 'CONFIRM'.
    Applies change through src/store.py, then appends an audit line with source 'human',
    the before state, the after state, and a field 'undo_token'.
    Expired proposals cannot be approved, and the reply says so.

    Neither calls input() nor print().
    """
    ws = _resolve_workspace(workspace)
    proposals = _load_proposals(workspace=ws)
    if proposal_id not in proposals:
        return {
            "status": "error",
            "error": f"Proposal '{proposal_id}' not found.",
        }

    proposal = proposals[proposal_id]
    expires_at = proposal.get("expires_at")
    now = datetime.now()
    is_expired = proposal.get("status") == "expired"
    if expires_at and not is_expired:
        try:
            exp_dt = datetime.fromisoformat(expires_at)
            if now >= exp_dt:
                is_expired = True
        except Exception:
            pass

    if is_expired:
        proposal["status"] = "expired"
        _save_proposals(proposals, workspace=ws)
        return {
            "status": "error",
            "error": f"Proposal '{proposal_id}' has expired and cannot be approved.",
            "proposal_id": proposal_id,
        }

    risk = str(proposal.get("risk", "low")).lower()
    if risk == "high":
        if answer != "CONFIRM":
            return {
                "status": "error",
                "error": f"High-risk proposal requires answer exactly 'CONFIRM' (got '{answer}').",
                "proposal_id": proposal_id,
            }
    else:
        if answer != "yes":
            return {
                "status": "error",
                "error": f"Low-risk proposal requires answer exactly 'yes' (got '{answer}').",
                "proposal_id": proposal_id,
            }

    kind = proposal.get("kind", "budget_change")
    payload = proposal.get("payload", {})

    before_state: dict[str, Any] = {}
    after_state: dict[str, Any] = {}

    if kind == "budget_change":
        category = proposal.get("category") or payload.get("category")
        action = proposal.get("action") or payload.get("action", "change")
        new_limit = proposal.get("new_limit") if "new_limit" in proposal else payload.get("new_limit")
        old_limit = proposal.get("old_limit") if "old_limit" in proposal else payload.get("old_limit")

        try:
            budgets = store.read_json("budgets.json", workspace=ws)
        except Exception:
            budgets = {}
            if BUDGETS_PATH and BUDGETS_PATH.exists():
                try:
                    with open(BUDGETS_PATH, "r", encoding="utf-8") as f:
                        budgets = json.load(f)
                except Exception:
                    pass

        before_state = {
            "file": "budgets.json",
            "kind": "budget_change",
            "category": category,
            "action": action,
            "previous_limit": budgets.get(category, old_limit),
        }

        if action == "remove":
            budgets.pop(category, None)
            applied_limit = 0.0
        else:
            applied_limit = float(new_limit)
            budgets[category] = applied_limit

        store.write_json_atomic("budgets.json", budgets, workspace=ws)
        if BUDGETS_PATH and BUDGETS_PATH.exists() and not store.is_shared_default_dir(BUDGETS_PATH.parent):
            try:
                with open(BUDGETS_PATH, "w", encoding="utf-8") as f:
                    json.dump(budgets, f, indent=2)
            except Exception:
                pass

        after_state = {
            "file": "budgets.json",
            "kind": "budget_change",
            "category": category,
            "action": action,
            "new_limit": applied_limit,
        }

    elif kind == "add_transactions":
        items = payload.get("items", [])
        try:
            df_tx = store.read_csv("transactions.csv", workspace=ws)
        except Exception:
            df_tx = pd.DataFrame(columns=["id", "date", "month", "category", "description", "type", "amount"])

        new_rows = []
        for it in items:
            row = dict(it)
            if "month" not in row and "date" in row:
                row["month"] = str(row["date"])[:7]
            new_rows.append(row)

        df_new = pd.DataFrame(new_rows)
        df_new = store.ensure_transaction_ids(df_new)
        added_ids = [str(x) for x in df_new["id"].tolist()]

        before_state = {
            "file": "transactions.csv",
            "kind": "add_transactions",
            "added_ids": added_ids,
            "items": items,
        }

        df_tx_updated = pd.concat([df_tx, df_new], ignore_index=True)
        df_tx_updated = store.ensure_transaction_ids(df_tx_updated)
        store.write_csv_atomic("transactions.csv", df_tx_updated, workspace=ws)

        after_state = {
            "file": "transactions.csv",
            "kind": "add_transactions",
            "added_ids": added_ids,
            "count": len(items),
        }

    elif kind == "update_transaction":
        tx_id = str(payload.get("transaction_id"))
        fields = payload.get("fields", {})

        df_tx = store.read_csv("transactions.csv", workspace=ws)
        matched_idx = None
        prev_fields = {}
        for idx, row in df_tx.iterrows():
            if str(row.get("id")) == tx_id:
                matched_idx = idx
                for f_name in fields:
                    if f_name in row:
                        prev_fields[f_name] = row[f_name]
                break

        if matched_idx is None:
            return {"status": "error", "error": f"Transaction '{tx_id}' not found."}

        before_state = {
            "file": "transactions.csv",
            "kind": "update_transaction",
            "transaction_id": tx_id,
            "previous_fields": prev_fields,
        }

        for k, v in fields.items():
            df_tx.at[matched_idx, k] = v
        if "date" in fields:
            df_tx.at[matched_idx, "month"] = str(fields["date"])[:7]

        store.write_csv_atomic("transactions.csv", df_tx, workspace=ws)

        after_state = {
            "file": "transactions.csv",
            "kind": "update_transaction",
            "transaction_id": tx_id,
            "updated_fields": fields,
        }

    elif kind == "delete_transaction":
        tx_id = str(payload.get("transaction_id"))
        df_tx = store.read_csv("transactions.csv", workspace=ws)
        matched_row = None
        for idx, row in df_tx.iterrows():
            if str(row.get("id")) == tx_id:
                matched_row = row.to_dict()
                break

        if matched_row is None:
            return {"status": "error", "error": f"Transaction '{tx_id}' not found."}

        before_state = {
            "file": "transactions.csv",
            "kind": "delete_transaction",
            "transaction_id": tx_id,
            "deleted_row": matched_row,
        }

        df_tx_updated = df_tx[df_tx["id"].astype(str) != tx_id]
        store.write_csv_atomic("transactions.csv", df_tx_updated, workspace=ws)

        after_state = {
            "file": "transactions.csv",
            "kind": "delete_transaction",
            "transaction_id": tx_id,
            "status": "deleted",
        }

    elif kind == "bill_change":
        action = payload.get("action")
        bill_data = payload.get("bill") if isinstance(payload.get("bill"), dict) else {}
        bill_name = payload.get("bill_name") or bill_data.get("bill_name")
        df_bills = store.read_csv("bills.csv", workspace=ws)

        matched_idx = None
        prev_bill_row = None
        for idx, row in df_bills.iterrows():
            if str(row.get("bill_name")).strip().lower() == str(bill_name).strip().lower():
                matched_idx = idx
                prev_bill_row = row.to_dict()
                break

        if action == "add":
            clean_name = bill_data.get("bill_name") or bill_name
            before_state = {
                "file": "bills.csv",
                "kind": "bill_change",
                "action": "add",
                "bill_name": clean_name,
            }
            amt = bill_data.get("amount") if "amount" in bill_data else payload.get("amount", 0.0)
            due = bill_data.get("due_day") if "due_day" in bill_data else payload.get("due_day", 1)
            cat = bill_data.get("category") if "category" in bill_data else payload.get("category", "Utilities")

            new_bill = {
                "bill_name": clean_name,
                "amount": float(amt),
                "due_day": int(due),
                "category": cat,
            }
            df_bills_updated = pd.concat([df_bills, pd.DataFrame([new_bill])], ignore_index=True)
            store.write_csv_atomic("bills.csv", df_bills_updated, workspace=ws)
            after_state = {
                "file": "bills.csv",
                "kind": "bill_change",
                "action": "add",
                "bill_name": clean_name,
            }

        elif action == "edit":
            if matched_idx is None:
                return {"status": "error", "error": f"Bill '{bill_name}' not found to edit."}
            before_state = {
                "file": "bills.csv",
                "kind": "bill_change",
                "action": "edit",
                "bill_name": bill_name,
                "previous_fields": prev_bill_row,
            }
            changes = payload.get("changes") if isinstance(payload.get("changes"), dict) else payload
            for k in ("amount", "due_day", "category", "bill_name"):
                if k in changes and changes[k] is not None:
                    df_bills.at[matched_idx, k] = changes[k]
            store.write_csv_atomic("bills.csv", df_bills, workspace=ws)
            after_state = {
                "file": "bills.csv",
                "kind": "bill_change",
                "action": "edit",
                "bill_name": bill_name,
            }

        elif action == "cancel":
            if matched_idx is None:
                return {"status": "error", "error": f"Bill '{bill_name}' not found to cancel."}
            before_state = {
                "file": "bills.csv",
                "kind": "bill_change",
                "action": "cancel",
                "bill_name": bill_name,
                "cancelled_row": prev_bill_row,
            }
            df_bills_updated = df_bills[df_bills.index != matched_idx]
            store.write_csv_atomic("bills.csv", df_bills_updated, workspace=ws)
            after_state = {
                "file": "bills.csv",
                "kind": "bill_change",
                "action": "cancel",
                "bill_name": bill_name,
            }

    # Remove proposal from pending store
    proposals.pop(proposal_id, None)
    _save_proposals(proposals, workspace=ws)

    undo_token = f"undo_{uuid.uuid4().hex[:12]}"
    store.append_audit(
        action=f"approve_{kind}",
        before=before_state,
        after=after_state,
        source="human",
        workspace=ws,
        undo_token=undo_token,
        proposal_id=proposal_id,
        kind=kind,
    )

    log_event(
        "proposal_applied",
        {
            "proposal_id": proposal_id,
            "kind": kind,
            "undo_token": undo_token,
        },
    )

    res: dict[str, Any] = {
        "status": "applied",
        "proposal_id": proposal_id,
        "undo_token": undo_token,
        "kind": kind,
        "message": f"Proposal '{proposal_id}' ({kind}) successfully applied.",
    }
    if kind == "budget_change":
        res["category"] = before_state.get("category")
        res["old_limit"] = before_state.get("previous_limit")
        res["new_limit"] = after_state.get("new_limit")
    return res


def reject(proposal_id: str, workspace: Path | str | None = None) -> dict:
    """Remove the proposal and write an audit line.
    Modifies NO data files.

    Neither calls input() nor print().
    """
    ws = _resolve_workspace(workspace)
    proposals = _load_proposals(workspace=ws)
    if proposal_id not in proposals:
        return {
            "status": "error",
            "error": f"Proposal '{proposal_id}' not found.",
        }

    proposal = proposals.pop(proposal_id)
    _save_proposals(proposals, workspace=ws)

    store.append_audit(
        action="reject_proposal",
        before={"proposal_id": proposal_id, "proposal": proposal},
        after={"status": "rejected"},
        source="human",
        workspace=ws,
        proposal_id=proposal_id,
    )

    log_event(
        "proposal_rejected",
        {
            "proposal_id": proposal_id,
            "decision": "rejected",
        },
    )

    return {
        "status": "rejected",
        "proposal_id": proposal_id,
        "message": f"Proposal '{proposal_id}' was rejected and removed.",
    }


def approve_all(answer: str, workspace: Path | str | None = None) -> dict:
    """Apply every unexpired low-risk proposal.
    Requires answer exactly 'yes' and skips high-risk proposals.

    Neither calls input() nor print().
    """
    if answer != "yes":
        return {
            "status": "error",
            "error": f"approve_all requires answer exactly 'yes' (got '{answer}').",
        }

    ws = _resolve_workspace(workspace)
    pending = list_pending(workspace=ws)
    approved = []
    skipped = []

    for p in pending:
        p_id = str(p.get("id") or p.get("proposal_id"))
        risk = str(p.get("risk", "low")).lower()
        if risk == "high":
            skipped.append(p_id)
        else:
            res = approve(p_id, "yes", workspace=ws)
            if res.get("status") == "applied":
                approved.append(p_id)

    return {
        "status": "applied",
        "approved": approved,
        "skipped_high_risk": skipped,
        "message": f"Approved {len(approved)} low-risk proposal(s). Skipped {len(skipped)} high-risk proposal(s).",
    }


def undo(workspace: Path | str | None = None) -> dict:
    """Revert the most recent human-applied action that has not already been undone,
    using the before state in the audit log. Writes its own audit line.
    Undo of an undo is refused.

    Neither calls input() nor print().
    """
    ws = _resolve_workspace(workspace)
    audit_records = store.read_audit(workspace=ws)
    if not audit_records:
        return {
            "status": "refused",
            "error": "Undo refused: audit log is empty.",
            "message": "Nothing to undo.",
        }

    undone_tokens = {
        rec.get("undone_token")
        for rec in audit_records
        if rec.get("action") == "undo" and rec.get("undone_token")
    }

    target_rec = None
    for rec in reversed(audit_records):
        action = rec.get("action", "")
        # Undo of an undo is refused
        if action == "undo":
            continue
        if rec.get("source") == "human" and rec.get("undo_token"):
            token = rec["undo_token"]
            if token not in undone_tokens:
                target_rec = rec
                break

    if target_rec is None:
        return {
            "status": "refused",
            "error": "Undo refused: no eligible action to undo (undo of an undo is refused).",
            "message": "Undo refused.",
        }

    target_token = target_rec["undo_token"]
    before_state = target_rec.get("before", {})
    after_state = target_rec.get("after", {})
    file_type = before_state.get("file") if isinstance(before_state, dict) else None
    kind = before_state.get("kind") if isinstance(before_state, dict) else None

    if file_type == "budgets.json" or kind == "budget_change":
        category = before_state.get("category")
        prev_limit = before_state.get("previous_limit")
        action = before_state.get("action")

        try:
            budgets = store.read_json("budgets.json", workspace=ws)
        except Exception:
            budgets = {}

        if prev_limit is None or action == "add":
            budgets.pop(category, None)
        else:
            budgets[category] = float(prev_limit)

        store.write_json_atomic("budgets.json", budgets, workspace=ws)
        if BUDGETS_PATH and BUDGETS_PATH.exists() and not store.is_shared_default_dir(BUDGETS_PATH.parent):
            try:
                with open(BUDGETS_PATH, "w", encoding="utf-8") as f:
                    json.dump(budgets, f, indent=2)
            except Exception:
                pass

    elif file_type == "transactions.csv" or kind in ("add_transactions", "update_transaction", "delete_transaction"):
        df_tx = store.read_csv("transactions.csv", workspace=ws)
        if kind == "add_transactions":
            added_ids = [str(x) for x in before_state.get("added_ids", [])]
            if added_ids:
                df_tx = df_tx[~df_tx["id"].astype(str).isin(added_ids)]
            else:
                items = before_state.get("items", [])
                for it in items:
                    cond = (
                        (df_tx["date"].astype(str) == str(it.get("date"))) &
                        (df_tx["description"].astype(str) == str(it.get("description"))) &
                        (df_tx["amount"] == float(it.get("amount")))
                    )
                    idx_match = df_tx[cond].index
                    if len(idx_match) > 0:
                        df_tx = df_tx.drop(idx_match[-1])
            store.write_csv_atomic("transactions.csv", df_tx, workspace=ws)

        elif kind == "delete_transaction":
            deleted_row = before_state.get("deleted_row", {})
            if deleted_row:
                df_tx = pd.concat([df_tx, pd.DataFrame([deleted_row])], ignore_index=True)
                df_tx = store.ensure_transaction_ids(df_tx)
                store.write_csv_atomic("transactions.csv", df_tx, workspace=ws)

        elif kind == "update_transaction":
            tx_id = str(before_state.get("transaction_id"))
            prev_fields = before_state.get("previous_fields", {})
            for idx, row in df_tx.iterrows():
                if str(row.get("id")) == tx_id:
                    for k, v in prev_fields.items():
                        df_tx.at[idx, k] = v
                    if "date" in prev_fields:
                        df_tx.at[idx, "month"] = str(prev_fields["date"])[:7]
                    break
            store.write_csv_atomic("transactions.csv", df_tx, workspace=ws)

    elif file_type == "bills.csv" or kind == "bill_change":
        df_bills = store.read_csv("bills.csv", workspace=ws)
        action = before_state.get("action")
        bill_name = str(before_state.get("bill_name", "")).strip().lower()

        if action == "add":
            df_bills = df_bills[df_bills["bill_name"].astype(str).str.strip().str.lower() != bill_name]
            store.write_csv_atomic("bills.csv", df_bills, workspace=ws)
        elif action == "cancel":
            cancelled_row = before_state.get("cancelled_row", {})
            if cancelled_row:
                df_bills = pd.concat([df_bills, pd.DataFrame([cancelled_row])], ignore_index=True)
                store.write_csv_atomic("bills.csv", df_bills, workspace=ws)
        elif action == "edit":
            prev_fields = before_state.get("previous_fields", {})
            for idx, row in df_bills.iterrows():
                if str(row.get("bill_name")).strip().lower() == bill_name:
                    for k, v in prev_fields.items():
                        df_bills.at[idx, k] = v
                    break
            store.write_csv_atomic("bills.csv", df_bills, workspace=ws)

    # Append audit line for undo
    store.append_audit(
        action="undo",
        before=after_state,
        after=before_state,
        source="human",
        workspace=ws,
        undone_token=target_token,
    )

    log_event(
        "action_undone",
        {
            "reverted_action": target_rec.get("action"),
            "undone_token": target_token,
        },
    )

    return {
        "status": "undone",
        "reverted_action": target_rec.get("action"),
        "undone_token": target_token,
        "message": f"Successfully reverted action '{target_rec.get('action')}'.",
    }


def request_approval(proposal_id: str, workspace: Path | str | None = None) -> dict:
    """Load a pending proposal and return its summary awaiting approval.
    Neither calls input() nor print().
    """
    ws = _resolve_workspace(workspace)
    proposals = _load_proposals(workspace=ws)
    if proposal_id not in proposals:
        return {
            "status": "error",
            "error": f"Proposal '{proposal_id}' not found.",
        }

    proposal = proposals[proposal_id]
    category = proposal.get("category") or proposal.get("payload", {}).get("category")
    old_limit = proposal.get("old_limit") if "old_limit" in proposal else proposal.get("payload", {}).get("old_limit")
    new_limit = proposal.get("new_limit") if "new_limit" in proposal else proposal.get("payload", {}).get("new_limit")

    return {
        "proposal_id": proposal_id,
        "category": category,
        "old_limit": old_limit,
        "new_limit": new_limit,
        "status": "awaiting_approval",
    }


def confirm_approval(proposal_id: str, decision: str, workspace: Path | str | None = None) -> dict:
    """Confirm or cancel a pending proposal based on user decision.
    Accepts only the exact string 'yes' as approval. Any other value cancels.
    Wrapper around approve() for backward compatibility with existing tests.
    Neither calls input() nor print().
    """
    ws = _resolve_workspace(workspace)
    proposals = _load_proposals(workspace=ws)
    if proposal_id not in proposals:
        return {
            "status": "error",
            "error": f"Proposal '{proposal_id}' not found.",
        }

    proposal = proposals[proposal_id]
    category = proposal.get("category") or proposal.get("payload", {}).get("category")
    old_limit = proposal.get("old_limit") if "old_limit" in proposal else proposal.get("payload", {}).get("old_limit")
    new_limit = proposal.get("new_limit") if "new_limit" in proposal else proposal.get("payload", {}).get("new_limit")

    if decision in ("yes", "CONFIRM"):
        res = approve(proposal_id, decision, workspace=ws)
        if res.get("status") == "applied":
            if "category" not in res and category:
                res["category"] = category
            if "old_limit" not in res:
                res["old_limit"] = old_limit
            if "new_limit" not in res:
                res["new_limit"] = new_limit
            if "message" not in res:
                res["message"] = f"Successfully updated '{category}' budget to ${new_limit:.2f}." if new_limit is not None else "Applied."
        return res
    else:
        log_event(
            "budget_cancelled",
            {
                "proposal_id": proposal_id,
                "category": category,
                "decision": "cancelled",
            },
        )
        return {
            "status": "cancelled",
            "proposal_id": proposal_id,
            "category": category,
            "message": "Budget change cancelled by user. No files were modified.",
        }

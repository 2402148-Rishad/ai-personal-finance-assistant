from datetime import datetime
import json
from pathlib import Path
import re
import uuid
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.agent import run_agent, build_source_line
from src.approvals import list_pending, approve, reject, undo
from src.banner import get_do_this_next_banner
from src.config import AS_OF_DATE
import src.store as store
from src.store import (
    create_workspace,
    reset_workspace,
    set_active_workspace,
    get_sandbox_today,
    set_sandbox_today,
    cleanup_old_workspaces,
    search_transactions,
    add_transaction,
    update_transaction,
    delete_transaction,
    import_transactions,
    read_audit,
    read_proposals,
    read_csv,
    read_json,
)
from src.tools import (
    cashflow_projection,
    get_data_overview,
    get_monthly_summary,
    spending_by_category,
    upcoming_bills,
    budget_status,
    propose_budget_change,
    propose_bill_change,
)
from src.validators import (
    validate_date,
    validate_amount,
    validate_category,
    validate_text,
    get_workspace_categories,
)
from src.formatters import (
    format_date_human,
    format_expiry,
    format_card_value,
    get_next_undo_line,
)

st.set_page_config(
    page_title="Fin",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Cleanup old workspaces untouched for > 24 hours on app startup
if "workspaces_cleaned" not in st.session_state:
    try:
        cleanup_old_workspaces(max_age_hours=24)
    except Exception:
        pass
    st.session_state.workspaces_cleaned = True

# Session: create session_id once per browser session and create its workspace
if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex

session_ws = create_workspace(st.session_state.session_id)
set_active_workspace(session_ws)

# Keep two lists in st.session_state: display for the screen and history for the model
if "display" not in st.session_state:
    st.session_state.display = []
if "history" not in st.session_state:
    st.session_state.history = []
if "input_key" not in st.session_state:
    st.session_state.input_key = 0

# Fonts and style block (the only HTML in the app, no lines starting with /*)
st.html(
    """<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400..700;1,9..144,400..700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header[data-testid="stHeader"] {display: none;}
h1, h2, h3, [data-testid="stHeadingWithActionElements"] {font-family: 'Fraunces', serif !important;}
code, pre, [data-testid="stMetricValue"], [data-testid="stCode"] {font-family: 'JetBrains Mono', monospace !important;}
code { color: #78716C !important; background: #F1EEE9 !important; }
.sandbox-chip {
    display: inline-block;
    padding: 3px 12px;
    border-radius: 14px;
    background: #F1EEE9;
    color: #78716C;
    font-size: 0.85rem;
    font-weight: 500;
}
div[data-testid="stRadio"] div[role="radiogroup"] {
    display: flex;
    flex-direction: row;
    gap: 1.5rem;
    border-bottom: 1px solid #E5E7EB;
    padding-bottom: 0px;
    margin-bottom: 1rem;
}
div[data-testid="stRadio"] div[role="radiogroup"] label[data-baseweb="radio"] {
    background: transparent !important;
    border: none !important;
    padding: 8px 12px !important;
    margin: 0 !important;
    cursor: pointer;
    font-size: 0.95rem;
    font-weight: 500;
    color: #4B5563;
    border-bottom: 2px solid transparent !important;
    margin-bottom: -1px !important;
    transition: all 0.15s ease-in-out;
}
div[data-testid="stRadio"] div[role="radiogroup"] label[data-baseweb="radio"] > div:first-child {
    display: none !important;
}
div[data-testid="stRadio"] div[role="radiogroup"] label[data-baseweb="radio"]:hover {
    color: #111827;
}
div[data-testid="stRadio"] div[role="radiogroup"] label[data-baseweb="radio"]:has(input:checked) {
    color: #111827 !important;
    font-weight: 600 !important;
    border-bottom: 2px solid #E04836 !important;
}
div[data-testid="stRadio"] div[role="radiogroup"] label[data-baseweb="radio"][aria-checked="true"] {
    color: #111827 !important;
    font-weight: 600 !important;
    border-bottom: 2px solid #E04836 !important;
}
@media (max-width: 640px) {
    [data-testid="stHorizontalBlock"] {
        flex-direction: column !important;
        flex-wrap: wrap !important;
    }
    [data-testid="column"], [data-testid="stColumn"] {
        width: 100% !important;
        min-width: 100% !important;
        flex: 1 1 100% !important;
    }
    .stButton > button {
        width: 100% !important;
    }
}
html, body, [data-testid="stAppViewContainer"] {
    overflow-x: hidden !important;
    max-width: 100% !important;
}
</style>"""
)


@st.dialog("Settings")
def open_settings_dialog(ws):
    curr_date = get_sandbox_today(workspace=ws)
    st.write(f"Current sandbox date: **{curr_date}**")
    new_date = st.text_input("New sandbox date (YYYY-MM-DD)", value=curr_date, key="settings_sandbox_date_input")
    if st.button("Save", key="save_sandbox_date_btn"):
        try:
            set_sandbox_today(new_date.strip(), workspace=ws)
            st.rerun()
        except Exception as e:
            st.error(str(e))


sandbox_today = get_sandbox_today(workspace=session_ws)

# Top bar: the "Fin" title, a chip "Sandbox · <sandbox_today>", a Settings button, and a "Reset demo" button
top_col1, top_col2, top_col3, top_col4 = st.columns([2.5, 3.5, 1.5, 2.5], vertical_alignment="center")
with top_col1:
    st.title("Fin")
with top_col2:
    st.markdown(f'<span class="sandbox-chip">Sandbox · {sandbox_today}</span>', unsafe_allow_html=True)
with top_col3:
    if st.button("Settings", key="settings_button"):
        open_settings_dialog(session_ws)
with top_col4:
    confirm = st.checkbox("Confirm reset", key="confirm_reset_checkbox")
    if st.button("Reset demo", key="reset_demo_button"):
        if confirm:
            reset_workspace(st.session_state.session_id)
            set_active_workspace(session_ws)
            st.session_state.display = []
            st.session_state.history = []
            st.session_state.input_key += 1
            st.rerun()
        else:
            st.warning("Please check the confirm box before resetting.")


def escape_dollars(text: str) -> str:
    """Replace every dollar sign with an escaped dollar sign for Streamlit markdown."""
    return text.replace("$", "\\$")


def render_column_header(title: str, button_label: str | None = None, button_key: str | None = None):
    """Render a column header row so left and right column headers sit at the exact same height."""
    col_title, col_action = st.columns([5, 1], vertical_alignment="center")
    with col_title:
        st.subheader(title)
    with col_action:
        if button_label and button_key:
            return st.button(button_label, key=button_key)
    return False


left_col, right_col = st.columns([3, 2], gap="large")

with left_col:
    # Column header using helper function
    if render_column_header("Chat", button_label="Clear chat", button_key="clear_chat_button"):
        st.session_state.display = []
        st.session_state.history = []
        st.session_state.input_key += 1
        st.rerun()

    # "Do this next" banner above the chat
    banner_text = get_do_this_next_banner(workspace=session_ws)
    st.markdown("##### Do this next")
    has_pending = False
    try:
        has_pending = bool(list_pending(workspace=session_ws))
    except Exception:
        pass

    def _open_inbox_cb():
        st.session_state["active_view"] = "Inbox"
        st.session_state["active_tab"] = "Inbox"

    if has_pending:
        b_c1, b_c2 = st.columns([3, 1], vertical_alignment="center")
        with b_c1:
            st.info(banner_text)
        with b_c2:
            st.button("Open Inbox", key="open_inbox_banner_btn", on_click=_open_inbox_cb)
    else:
        st.info(banner_text)

    chat_error_placeholder = st.empty()

    def handle_chat_submit(question_text: str):
        q = question_text.strip()
        if not q:
            return
        try:
            before_pending = {str(p.get("id") or p.get("proposal_id")) for p in list_pending(workspace=session_ws)}
            with st.spinner("Fin is thinking..."):
                result = run_agent(q, history=st.session_state.history)
            status_str = str(getattr(result, "status", None))
            if status_str != "model_unavailable" and getattr(result, "status", None) == "error":
                raise RuntimeError(result.answer)

            # Discover proposal IDs created during this turn
            after_pending = [str(p.get("id") or p.get("proposal_id")) for p in list_pending(workspace=session_ws)]
            created_proposal_ids = [pid for pid in after_pending if pid not in before_pending]

            clarification_options = []
            for tc in getattr(result, "tool_calls", []):
                t_res = tc.get("result", {})
                if isinstance(t_res, dict):
                    p_id = t_res.get("proposal_id")
                    if p_id and p_id not in created_proposal_ids:
                        created_proposal_ids.append(p_id)
                    if t_res.get("status") == "needs_clarification":
                        opts = t_res.get("options", {})
                        if isinstance(opts, dict):
                            for opt_list in opts.values():
                                if isinstance(opt_list, list):
                                    clarification_options.extend([str(o) for o in opt_list])
                                elif isinstance(opt_list, str):
                                    clarification_options.append(opt_list)
                        elif isinstance(opts, list):
                            clarification_options.extend([str(o) for o in opts])

            created_proposal_ids = list(dict.fromkeys(created_proposal_ids))
            clarification_options = list(dict.fromkeys(clarification_options))

            st.session_state.history = result.history
            st.session_state.display.append({"role": "user", "content": q})
            st.session_state.display.append({
                "role": "assistant",
                "content": result.answer,
                "tool_calls": getattr(result, "tool_calls", []),
                "proposal_ids": created_proposal_ids,
                "clarification_options": clarification_options,
            })
            st.session_state.input_key += 1
            st.rerun()
        except Exception:
            chat_error_placeholder.error("Couldn't reach the model. Try again in a moment.")

    # Message area / Empty chat state
    with st.container():
        if not st.session_state.display:
            st.markdown("**Ask**")
            col_ask1, col_ask2 = st.columns(2)
            with col_ask1:
                if st.button("What did I spend this month?", key="starter_ask_1", use_container_width=True):
                    handle_chat_submit("What did I spend this month?")
            with col_ask2:
                if st.button("What are my upcoming bills?", key="starter_ask_2", use_container_width=True):
                    handle_chat_submit("What are my upcoming bills?")

            st.markdown("**Add**")
            if st.button("Add an expense: $45 for groceries", key="starter_add_1", use_container_width=True):
                handle_chat_submit("Add an expense: $45 for groceries")

            st.markdown("**Fix**")
            if st.button("Find possible duplicate charges", key="starter_fix_1", use_container_width=True):
                handle_chat_submit("Find possible duplicate charges")

            st.markdown("**Plan**")
            col_plan1, col_plan2 = st.columns(2)
            with col_plan1:
                if st.button("Project cashflow for the next 30 days", key="starter_plan_1", use_container_width=True):
                    handle_chat_submit("Project cashflow for the next 30 days")
            with col_plan2:
                if st.button("Suggest recommendations to save money", key="starter_plan_2", use_container_width=True):
                    handle_chat_submit("Suggest recommendations to save money")
        else:
            for msg_idx, item in enumerate(st.session_state.display):
                if item.get("role") == "user" or "question" in item:
                    q_text = item.get("content") or item.get("question", "")
                    with st.container(border=True):
                        st.caption("You")
                        st.markdown(escape_dollars(q_text))
                else:
                    a_text = item.get("content") or item.get("answer", "")
                    with st.container(border=True):
                        st.caption("Fin")
                        st.markdown(escape_dollars(a_text))

                        # "How I got this" expander
                        tool_calls = item.get("tool_calls", [])
                        if tool_calls:
                            with st.expander("How I got this"):
                                for tc in tool_calls:
                                    t_name = tc.get("name", "")
                                    t_args = tc.get("arguments", {})
                                    t_res = tc.get("result", {})
                                    st.caption(f"Tool: {t_name}")
                                    st.markdown(f"**{t_name}**")
                                    if isinstance(t_args, dict) and t_args:
                                        st.markdown("**Arguments:**")
                                        for arg_k, arg_v in t_args.items():
                                            if isinstance(arg_v, list):
                                                st.markdown(f"- **{arg_k}:**")
                                                for list_item in arg_v:
                                                    if isinstance(list_item, dict):
                                                        item_str = ", ".join(f"{k}: {v}" for k, v in list_item.items())
                                                        st.markdown(f"  - {escape_dollars(item_str)}")
                                                    else:
                                                        st.markdown(f"  - {escape_dollars(str(list_item))}")
                                            elif isinstance(arg_v, dict):
                                                st.markdown(f"- **{arg_k}:**")
                                                for sub_k, sub_v in arg_v.items():
                                                    st.markdown(f"  - {sub_k}: {escape_dollars(str(sub_v))}")
                                            else:
                                                st.markdown(f"- **{arg_k}:** {escape_dollars(str(arg_v))}")
                                    elif t_args:
                                        st.markdown(f"- **Arguments:** {escape_dollars(str(t_args))}")
                                    else:
                                        st.caption("*(no arguments)*")

                                    if isinstance(t_res, dict):
                                        key_nums = []
                                        for k, v in t_res.items():
                                            if isinstance(v, (int, float)) and not isinstance(v, bool):
                                                is_curr = any(w in k for w in ("amount", "balance", "limit", "spent", "total", "due", "lowest", "projected"))
                                                val_s = f"${float(v):,.2f}" if is_curr else str(v)
                                                key_nums.append(f"`{k}`: {val_s}")
                                            elif k in ("spending_by_category", "categories", "totals") and isinstance(v, dict):
                                                for sub_k, sub_v in v.items():
                                                    if isinstance(sub_v, (int, float)):
                                                        key_nums.append(f"`{sub_k}`: ${float(sub_v):,.2f}")
                                                    elif isinstance(sub_v, dict) and "spent" in sub_v:
                                                        key_nums.append(f"`{sub_k}`: spent ${float(sub_v.get('spent', 0)):,.2f} / limit ${float(sub_v.get('limit', 0)):,.2f}")
                                        if key_nums:
                                            st.markdown(f"**Key numbers:** {', '.join(key_nums)}")
                                    st.divider()

                                src_line = build_source_line(tool_calls)
                                if src_line:
                                    st.markdown(escape_dollars(src_line))

                        # Task 2: Clarification options as clickable chips
                        clarifications = item.get("clarification_options", [])
                        if clarifications:
                            st.write("**Clarification:**")
                            cols = st.columns(min(len(clarifications), 4))
                            for c_idx, opt_str in enumerate(clarifications):
                                with cols[c_idx % len(cols)]:
                                    if opt_str in ("Add anyway", "Cancel"):
                                        btn_lbl = opt_str
                                        send_val = opt_str
                                    else:
                                        btn_lbl = f"{c_idx + 1}. {opt_str}"
                                        send_val = f"Category: {opt_str}"
                                    if st.button(btn_lbl, key=f"clarify_{msg_idx}_{c_idx}"):
                                        handle_chat_submit(send_val)

                        # Task 1: Inline approval cards
                        prop_ids = item.get("proposal_ids", [])
                        if prop_ids:
                            all_stored = read_proposals(workspace=session_ws)
                            pending_list = list_pending(workspace=session_ws)
                            pending_ids = {str(p.get("id") or p.get("proposal_id")) for p in pending_list}
                            now_dt = datetime.now()

                            for p_id in prop_ids:
                                prop = all_stored.get(p_id)
                                if not prop:
                                    continue

                                is_pending = p_id in pending_ids
                                risk = str(prop.get("risk", "low")).lower()
                                expires_at = str(prop.get("expires_at", ""))
                                kind_str = str(prop.get("kind", "proposal")).replace("_", " ").title()

                                is_exp = prop.get("status") == "expired"
                                if not is_exp and expires_at:
                                    try:
                                        if now_dt >= datetime.fromisoformat(expires_at):
                                            is_exp = True
                                    except Exception:
                                        pass

                                preview = prop.get("preview") or {}
                                before_val = preview.get("before") if isinstance(preview, dict) else None
                                after_val = preview.get("after") if isinstance(preview, dict) else None
                                if before_val is None and "old_limit" in prop:
                                    before_val = prop.get("old_limit")
                                if after_val is None and "new_limit" in prop:
                                    after_val = prop.get("new_limit")

                                with st.container(border=True):
                                    st.markdown(f"**Fin proposed: {kind_str}** (`{p_id}`)")
                                    m_c1, m_c2 = st.columns([3, 2])
                                    with m_c1:
                                        if is_exp:
                                            st.markdown("Status: **:red[Expired]**")
                                        elif not is_pending:
                                            st.markdown("Status: **Applied / Handled**")
                                        elif risk == "high":
                                            st.markdown("Risk: **:red[HIGH]**")
                                        else:
                                            st.markdown("Risk: **:green[LOW]**")
                                    with m_c2:
                                        st.caption(format_expiry(expires_at, now_dt))

                                    c_pv1, c_pv2 = st.columns(2)
                                    with c_pv1:
                                        st.write(f"**Before:** {format_card_value(before_val)}")
                                    with c_pv2:
                                        st.write(f"**After:** {format_card_value(after_val)}")

                                    payload = prop.get("payload", {})
                                    if isinstance(payload, dict) and payload.get("category"):
                                        st.caption(f"Category: {payload.get('category')}")
                                    if isinstance(payload, dict) and payload.get("bill_name"):
                                        st.caption(f"Bill: {payload.get('bill_name')}")

                                    if is_exp:
                                        st.markdown("**:red[Expired]**")
                                    elif is_pending:
                                        if risk == "high":
                                            confirm_text = st.text_input(
                                                "Type CONFIRM to enable approval",
                                                key=f"inline_confirm_{p_id}_{msg_idx}",
                                                placeholder="CONFIRM",
                                            )
                                            is_disabled = (confirm_text.strip() != "CONFIRM")
                                            b_c1, b_c2 = st.columns([1, 1])
                                            with b_c1:
                                                if st.button("Approve", key=f"inline_approve_{p_id}_{msg_idx}", disabled=is_disabled):
                                                    res = approve(p_id, "CONFIRM", workspace=session_ws)
                                                    if res.get("status") == "applied":
                                                        st.success(res.get("message", "Proposal applied."))
                                                        st.rerun()
                                                    else:
                                                        st.error(res.get("error", "Approval failed."))
                                            with b_c2:
                                                if st.button("Reject", key=f"inline_reject_{p_id}_{msg_idx}"):
                                                    res = reject(p_id, workspace=session_ws)
                                                    st.info(res.get("message", "Proposal rejected."))
                                                    st.rerun()
                                        else:
                                            b_c1, b_c2 = st.columns([1, 1])
                                            with b_c1:
                                                if st.button("Approve", key=f"inline_approve_{p_id}_{msg_idx}"):
                                                    res = approve(p_id, "yes", workspace=session_ws)
                                                    if res.get("status") == "applied":
                                                        st.success(res.get("message", "Proposal applied."))
                                                        st.rerun()
                                                    else:
                                                        st.error(res.get("error", "Approval failed."))
                                            with b_c2:
                                                if st.button("Reject", key=f"inline_reject_{p_id}_{msg_idx}"):
                                                    res = reject(p_id, workspace=session_ws)
                                                    st.info(res.get("message", "Proposal rejected."))
                                                    st.rerun()

                                st.markdown("Want a change? Say it, e.g. 'make it 40' or 'change to Groceries'.")

    # Send form with placeholder only in the input box
    with st.form(key="chat_form", clear_on_submit=False):
        input_col, send_col = st.columns([5, 1])
        with input_col:
            user_question = st.text_input(
                "Your question",
                placeholder="Ask about spending, bills, or savings.",
                label_visibility="collapsed",
                key=f"user_question_{st.session_state.input_key}",
            )
        with send_col:
            submitted = st.form_submit_button("Send")

        if submitted and user_question and user_question.strip():
            handle_chat_submit(user_question.strip())


def format_audit_line_english(rec: dict) -> str:
    """Format an audit record into a concise, plain English summary."""
    source = rec.get("source", "human")
    who = "(you)" if source == "human" else "(Fin)"
    action = str(rec.get("action", ""))
    before = rec.get("before") or {}
    after = rec.get("after") or {}

    if action == "import_transactions":
        count = after.get("count") if isinstance(after, dict) else None
        if count is None and isinstance(after, dict) and "items" in after:
            count = len(after["items"])
        if count is None:
            count = 1
        return f"Added {count} transaction{'s' if count != 1 else ''} {who}"

    if action == "add_transaction":
        desc = after.get("description", "transaction") if isinstance(after, dict) else "transaction"
        amt = after.get("amount") if isinstance(after, dict) else None
        if amt is not None:
            try:
                return f"Added transaction: {desc} (${float(amt):,.2f}) {who}"
            except (ValueError, TypeError):
                pass
        return f"Added transaction: {desc} {who}"

    if action == "update_transaction":
        desc = after.get("description") if isinstance(after, dict) else None
        if not desc and isinstance(before, dict):
            desc = before.get("description", "")
        tx_id = rec.get("tx_id", "")
        target = desc or tx_id or "transaction"
        return f"Updated transaction: {target} {who}"

    if action == "delete_transaction":
        desc = before.get("description", "transaction") if isinstance(before, dict) else "transaction"
        amt = before.get("amount") if isinstance(before, dict) else None
        if amt is not None:
            try:
                return f"Deleted transaction: {desc} (${float(amt):,.2f}) {who}"
            except (ValueError, TypeError):
                pass
        return f"Deleted transaction: {desc} {who}"

    if action == "approve_budget_change":
        cat = after.get("category") if isinstance(after, dict) else None
        act = after.get("action", "change") if isinstance(after, dict) else "change"
        lim = after.get("new_limit") if isinstance(after, dict) else None
        if act == "remove":
            return f"Removed budget category {cat} {who}"
        if lim is not None:
            return f"Updated budget limit for {cat} to ${float(lim):,.2f} {who}"
        return f"Approved budget change for {cat} {who}"

    if action == "approve_add_transactions":
        items = before.get("items", []) if isinstance(before, dict) else []
        count = len(items) if items else 1
        return f"Added {count} transaction{'s' if count != 1 else ''} {who}"

    if action == "approve_bill_change":
        act = after.get("action", "change") if isinstance(after, dict) else "change"
        name = after.get("bill_name", "bill") if isinstance(after, dict) else "bill"
        if act == "cancel":
            return f"Cancelled recurring bill {name} {who}"
        if act == "add":
            return f"Added recurring bill {name} {who}"
        return f"Updated recurring bill {name} {who}"

    if action == "approve_update_transaction":
        return f"Updated transaction {who}"

    if action == "approve_delete_transaction":
        return f"Deleted transaction {who}"

    if action == "reject_proposal":
        p_id = rec.get("proposal_id", "")
        return f"Rejected proposal {p_id} {who}".strip()

    if action == "undo":
        undone = rec.get("undone_action", "last change")
        return f"Undid {undone} {who}"

    clean_act = action.replace("_", " ").capitalize()
    return f"{clean_act} {who}"


with right_col:
    pending_items = list_pending(workspace=session_ws)
    pending_count = len(pending_items)

    view_options = ["Overview", "Ledger", "Plan", "Inbox"]

    # Support legacy active_tab from tests
    if "active_tab" in st.session_state and st.session_state["active_tab"] in view_options:
        if "active_view" not in st.session_state or st.session_state.get("_prev_active_tab") != st.session_state["active_tab"]:
            st.session_state["active_view"] = st.session_state["active_tab"]
            st.session_state["_prev_active_tab"] = st.session_state["active_tab"]

    # Normalize Inbox in session state if needed
    if "active_view" in st.session_state and str(st.session_state["active_view"]).startswith("Inbox"):
        st.session_state["active_view"] = "Inbox"

    if "active_view" not in st.session_state or st.session_state["active_view"] not in view_options:
        st.session_state["active_view"] = "Overview"

    def _format_nav_option(opt):
        s = str(opt)
        if s == "Inbox" or s.startswith("Inbox ("):
            return f"Inbox ({pending_count})"
        return s

    selected_view = st.radio(
        "Navigation",
        options=view_options,
        key="active_view",
        horizontal=True,
        label_visibility="collapsed",
        format_func=_format_nav_option,
    )
    if str(selected_view).startswith("Inbox"):
        selected_view = "Inbox"

    st.session_state["active_tab"] = selected_view
    st.session_state["_prev_active_tab"] = selected_view

    if selected_view == "Overview":
        # Month selector dynamically built from get_data_overview()
        overview = get_data_overview()
        available_months = overview.get("months") or ["2026-06", "2026-07", "2026-08"]
        last_m = overview.get("last_month")
        default_idx = available_months.index(last_m) if last_m in available_months else len(available_months) - 1

        selected_month = st.selectbox(
            "Select Month",
            options=available_months,
            index=default_idx,
            label_visibility="collapsed",
            key="overview_month_select",
        )

        # Metric for simulated sandbox balance
        raw_cf = cashflow_projection(today=sandbox_today, days_ahead=30)
        cf_data = json.loads(raw_cf)
        simulated_balance = cf_data.get("simulated_sandbox_balance", 0.0)
        covers_all_bills = cf_data.get("covers_all_bills", True)
        st.metric(label="Simulated sandbox balance", value=f"${simulated_balance:,.2f}")

        # Quick actions that need no model
        st.subheader("Quick actions")
        qa_col1, qa_col2, qa_col3, qa_col4 = st.columns(4)
        with qa_col1:
            btn_sum = st.button("Summary", key="qa_btn_summary", use_container_width=True)
        with qa_col2:
            btn_bills = st.button("Bills", key="qa_btn_bills", use_container_width=True)
        with qa_col3:
            btn_budget = st.button("Budgets", key="qa_btn_budget", use_container_width=True)
        with qa_col4:
            btn_cf = st.button("30-day cash", key="qa_btn_cashflow", use_container_width=True)

        if btn_sum:
            st.session_state["overview_quick_action"] = "summary"
        elif btn_bills:
            st.session_state["overview_quick_action"] = "bills"
        elif btn_budget:
            st.session_state["overview_quick_action"] = "budget"
        elif btn_cf:
            st.session_state["overview_quick_action"] = "cashflow"

        active_qa = st.session_state.get("overview_quick_action")
        if active_qa == "summary":
            st.markdown(f"**This Month's Summary ({selected_month})**")
            raw_sum = get_monthly_summary(month=selected_month)
            sum_data = json.loads(raw_sum)
            t_inc = float(sum_data.get("total_income", 0.0))
            t_exp = float(sum_data.get("total_expenses", 0.0))
            n_sav = float(sum_data.get("net_savings", 0.0))
            s_rate = float(sum_data.get("savings_rate", 0.0))
            sum_rows = [
                {"Metric": "Total Income", "Value": f"${t_inc:,.2f}"},
                {"Metric": "Total Expenses", "Value": f"${t_exp:,.2f}"},
                {"Metric": "Net Savings", "Value": f"${n_sav:,.2f}"},
                {"Metric": "Savings Rate", "Value": f"{s_rate:.1f}%"},
            ]
            st.table(pd.DataFrame(sum_rows))

        elif active_qa == "bills":
            st.markdown(f"**Upcoming Bills (Next 30 Days as of {sandbox_today})**")
            raw_b = upcoming_bills(today=sandbox_today, days_ahead=30)
            b_data = json.loads(raw_b)
            bills_list = b_data.get("upcoming_bills", [])
            if bills_list:
                b_rows = [
                    {
                        "Bill Name": b.get("bill_name"),
                        "Due Date": b.get("due_date"),
                        "Amount": f"${float(b.get('amount', 0)):,.2f}",
                        "Category": b.get("category"),
                    }
                    for b in bills_list
                ]
                st.table(pd.DataFrame(b_rows))
            else:
                st.info("No upcoming bills in the next 30 days.")

        elif active_qa == "budget":
            st.markdown(f"**Budget Status ({selected_month})**")
            raw_bs_qa = budget_status(month=selected_month)
            bs_qa_data = json.loads(raw_bs_qa)
            cat_map = bs_qa_data.get("categories") or bs_qa_data.get("status_by_category", {})
            if cat_map:
                bs_rows = [
                    {
                        "Category": cat,
                        "Spent": f"${float(info.get('spent', 0)):,.2f}",
                        "Limit": f"${float(info.get('limit', 0)):,.2f}",
                        "Remaining": f"${float(info.get('remaining', 0)):,.2f}",
                        "Status": "Over" if (info.get("is_over_budget") or info.get("is_over")) else "OK",
                    }
                    for cat, info in cat_map.items()
                ]
                st.table(pd.DataFrame(bs_rows))
            else:
                st.info(f"No budget status found for {selected_month}.")

        elif active_qa == "cashflow":
            st.markdown(f"**Cashflow Next 30 Days (from {sandbox_today})**")
            raw_cf_qa = cashflow_projection(today=sandbox_today, days_ahead=30)
            cf_qa_data = json.loads(raw_cf_qa)
            sim_bal = float(cf_qa_data.get("simulated_sandbox_balance", 0.0))
            low_bal = float(cf_qa_data.get("lowest_balance") if "lowest_balance" in cf_qa_data else cf_qa_data.get("lowest_projected_balance", 0.0))
            cf_summary_rows = [
                {"Metric": "Simulated Sandbox Balance", "Value": f"${sim_bal:,.2f}"},
                {"Metric": "Lowest Projected Balance", "Value": f"${low_bal:,.2f}"},
            ]
            st.table(pd.DataFrame(cf_summary_rows))
            bills_list = cf_qa_data.get("scheduled_bills", []) or cf_qa_data.get("daily_projections", [])
            if bills_list:
                cf_table_rows = []
                for item in bills_list[:10]:
                    if "due_date" in item:
                        cf_table_rows.append({
                            "Date": item.get("due_date"),
                            "Bill": item.get("bill_name"),
                            "Amount": f"${float(item.get('amount', 0)):,.2f}",
                            "Category": item.get("category"),
                        })
                    else:
                        cf_table_rows.append({
                            "Date": item.get("date"),
                            "Starting": f"${float(item.get('starting_balance', 0)):,.2f}",
                            "Income": f"${float(item.get('income', 0)):,.2f}",
                            "Expenses": f"${float(item.get('expenses', 0)):,.2f}",
                            "Ending": f"${float(item.get('ending_balance', 0)):,.2f}",
                        })
                st.table(pd.DataFrame(cf_table_rows))

        # Plotly bar chart of spending_by_category(month) in existing style
        raw_spending = spending_by_category(selected_month)
        spending_data = json.loads(raw_spending)
        spending_dict = spending_data.get("spending_by_category", {})

        if spending_dict:
            cats = list(spending_dict.keys())
            amts = list(spending_dict.values())

            fig = go.Figure(
                data=[
                    go.Bar(
                        x=cats,
                        y=amts,
                        text=[f"${v:,.2f}" for v in amts],
                        textposition="outside",
                        cliponaxis=False,
                        marker_color="#E04836",
                        textfont=dict(size=12),
                    )
                ]
            )
            fig.update_layout(
                template="plotly_white",
                margin=dict(l=10, r=10, t=25, b=50),
                xaxis=dict(tickangle=-35, showgrid=False),
                yaxis=dict(showgrid=True, zeroline=False),
                height=340,
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info(f"No spending data for {selected_month}. Add today's expenses in Ledger or ask Fin about your month.")

        # Progress bar per budget category (spent against limit, red when over)
        st.subheader("Budgets")
        raw_bs = budget_status(selected_month)
        bs_data = json.loads(raw_bs)
        status_by_cat = bs_data.get("status_by_category", {})

        if status_by_cat:
            for cat, info in status_by_cat.items():
                spent = float(info.get("spent", 0.0))
                limit = float(info.get("limit", 0.0))
                is_over = spent > limit
                progress_ratio = min(1.0, max(0.0, spent / limit)) if limit > 0 else (1.0 if spent > 0 else 0.0)

                col_b1, col_b2 = st.columns([3, 2])
                with col_b1:
                    if is_over:
                        st.markdown(f"**{cat}** :red[(Over by ${spent - limit:,.2f})]")
                    else:
                        st.markdown(f"**{cat}**")
                with col_b2:
                    st.markdown(f"${spent:,.2f} / ${limit:,.2f}")

                st.progress(progress_ratio)
        else:
            st.caption("No budget limits configured for this month.")

        # Bills due in next 30 days, with a "Short" flag when cashflow_projection says covers_all_bills is false
        if not covers_all_bills:
            st.subheader("Upcoming bills :red[[Short]]")
            st.caption(":red[**Short**: projected balance cannot cover upcoming bills.]")
        else:
            st.subheader("Upcoming bills")

        raw_bills = upcoming_bills(today=sandbox_today, days_ahead=30)
        bills_data = json.loads(raw_bills)
        bills_list = bills_data.get("upcoming_bills", [])

        if bills_list:
            for b in bills_list:
                name = b.get("bill_name", "Bill")
                due = b.get("due_date", "")
                amt = b.get("amount", 0.0)
                if not covers_all_bills:
                    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                    c1.write(name)
                    c2.write(due)
                    c3.write(f"${amt:,.2f}")
                    c4.markdown(":red[Short]")
                else:
                    c1, c2, c3 = st.columns([2, 1, 1])
                    c1.write(name)
                    c2.write(due)
                    c3.write(f"${amt:,.2f}")
        else:
            st.write("No upcoming bills found.")

        st.caption(f"As of {sandbox_today}")

    elif selected_view == "Ledger":
        st.subheader("Ledger")

        # 1. Add form (date, description, amount, type, category)
        with st.expander("Add Transaction", expanded=False):
            with st.form("add_transaction_form", clear_on_submit=False):
                col_d, col_t = st.columns([2, 1])
                with col_d:
                    add_date = st.text_input("Date (YYYY-MM-DD)", value=sandbox_today, key="add_tx_date")
                with col_t:
                    add_type = st.selectbox("Type", options=["expense", "income"], index=0, key="add_tx_type")

                add_desc = st.text_input("Description", placeholder="e.g. Dinner with friends", key="add_tx_desc")

                col_a, col_c = st.columns([1, 1])
                with col_a:
                    add_amount = st.text_input("Amount ($)", placeholder="e.g. 45.00", key="add_tx_amount")
                with col_c:
                    known_cats = sorted(get_workspace_categories(session_ws)) or ["Dining", "Groceries", "Transport", "Other"]
                    add_cat = st.selectbox("Category", options=known_cats, key="add_tx_category")

                add_submit = st.form_submit_button("Add Transaction", key="add_tx_submit_btn")

                if add_submit:
                    ok_d, val_d = validate_date(add_date, workspace=session_ws)
                    ok_a, val_a = validate_amount(add_amount)
                    ok_c, val_c = validate_category(add_cat, workspace=session_ws)

                    effective_desc = add_desc.strip() if add_desc else ""
                    if not effective_desc:
                        effective_desc = f"{add_cat} expense"
                    elif add_cat and effective_desc.lower() == add_cat.lower():
                        effective_desc = f"{add_cat} expense"

                    ok_desc, val_desc = validate_text(effective_desc)

                    if not ok_a:
                        st.error(f"Error: {val_a}")
                    elif not ok_d:
                        st.error(f"Error: {val_d}")
                    elif not ok_desc:
                        st.error(f"Error: {val_desc}")
                    elif not ok_c:
                        st.error(f"Error: {val_c}")
                    else:
                        try:
                            add_transaction({
                                "date": val_d,
                                "description": val_desc,
                                "amount": val_a,
                                "category": val_c,
                                "type": add_type,
                            }, workspace=session_ws, source="human")
                            st.success(f"Added {val_desc} (${val_a:,.2f}) to {val_c}.")
                        except Exception as e:
                            st.error(f"Failed to add transaction: {e}")

        # 2. CSV upload: first 20 rows preview, valid/invalid with reason, import valid rows, strip leading = + - @
        with st.expander("Import Transactions (CSV)", expanded=False):
            uploaded_file = st.file_uploader("Upload CSV file", type=["csv"], key="ledger_csv_uploader")
            if uploaded_file is not None:
                try:
                    upload_df = pd.read_csv(uploaded_file)
                    row_results = []
                    valid_records = []

                    for idx, row in upload_df.iterrows():
                        r_date = str(row.get("date", "")).strip()
                        r_desc = str(row.get("description", "")).strip()
                        # Strip leading = + - @ from text cells
                        r_desc = re.sub(r"^[=+\-@]+", "", r_desc).strip()
                        r_amt = row.get("amount")
                        r_cat = str(row.get("category", "")).strip()
                        r_type = str(row.get("type", "expense")).strip().lower()
                        if r_type not in ("expense", "income"):
                            r_type = "expense"

                        if not r_desc:
                            r_desc = f"{r_cat} expense" if r_cat else "General expense"
                        elif r_cat and r_desc.lower() == r_cat.lower():
                            r_desc = f"{r_cat} expense"

                        ok_d, clean_d = validate_date(r_date, workspace=session_ws)
                        ok_a, clean_a = validate_amount(r_amt)
                        ok_desc, clean_desc = validate_text(r_desc)
                        ok_c, clean_c = validate_category(r_cat, workspace=session_ws)

                        if not ok_d:
                            status_str = f"Invalid: {clean_d}"
                        elif not ok_a:
                            status_str = f"Invalid: {clean_a}"
                        elif not ok_desc:
                            status_str = f"Invalid: {clean_desc}"
                        elif not ok_c:
                            status_str = f"Invalid: {clean_c}"
                        else:
                            status_str = "Valid"
                            valid_records.append({
                                "date": clean_d,
                                "description": clean_desc,
                                "amount": clean_a,
                                "category": clean_c,
                                "type": r_type,
                            })

                        if idx < 20:
                            row_results.append({
                                "Row": idx + 1,
                                "Date": clean_d if ok_d else r_date,
                                "Description": clean_desc if ok_desc else r_desc,
                                "Amount": f"${clean_a:,.2f}" if ok_a else str(r_amt),
                                "Category": clean_c if ok_c else r_cat,
                                "Type": r_type,
                                "Result": status_str,
                            })

                    st.write(f"**Preview (first {len(row_results)} rows):**")
                    st.dataframe(pd.DataFrame(row_results), use_container_width=True)

                    total_rows = len(upload_df)
                    valid_count = len(valid_records)
                    invalid_count = total_rows - valid_count
                    st.caption(f"{valid_count} valid rows, {invalid_count} invalid rows out of {total_rows} total rows.")

                    if valid_count > 0:
                        if st.button(f"Import {valid_count} Valid Rows", key="import_valid_rows_btn"):
                            imported_n = import_transactions(valid_records, workspace=session_ws, source="human")
                            st.success(f"Successfully imported {imported_n} transactions.")
                    else:
                        st.warning("No valid rows to import.")
                except Exception as ex:
                    st.error(f"Error parsing uploaded CSV: {ex}")

        # 3. Search and Filters
        st.write("**Search and Filters**")
        col_s1, col_s2 = st.columns([3, 1])
        with col_s1:
            search_query = st.text_input("Search text / category / ID", placeholder="Filter by text...", key="ledger_filter_query")
        with col_s2:
            filter_type = st.selectbox("Type", options=["All", "expense", "income"], key="ledger_filter_type")

        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            all_known = ["All"] + sorted(get_workspace_categories(session_ws))
            filter_cat = st.selectbox("Category", options=all_known, key="ledger_filter_category")
        with col_f2:
            filter_min_amt = st.number_input(
                "Min amount ($)",
                min_value=0.0,
                value=None,
                placeholder="Any",
                step=10.0,
                key="ledger_filter_min",
            )
        with col_f3:
            filter_max_amt = st.number_input(
                "Max amount ($)",
                min_value=0.0,
                value=None,
                placeholder="Any",
                step=10.0,
                key="ledger_filter_max",
            )

        col_date1, col_date2 = st.columns(2)
        with col_date1:
            filter_start_date = st.date_input("From date", value=None, key="ledger_filter_start_date")
        with col_date2:
            filter_end_date = st.date_input("To date", value=None, key="ledger_filter_end_date")

        filtered_df = search_transactions(
            query=search_query,
            category=filter_cat,
            start_date=filter_start_date,
            end_date=filter_end_date,
            min_amount=filter_min_amt if (filter_min_amt is not None and filter_min_amt > 0) else None,
            max_amount=filter_max_amt if (filter_max_amt is not None and filter_max_amt > 0) else None,
            tx_type=filter_type,
            workspace=session_ws,
        )

        if filtered_df.empty:
            st.info("No transactions match your search. Try adjusting the filters, or add an expense above.")
        else:
            st.write(f"Showing **{len(filtered_df)}** transactions:")
            display_cols = ["date", "category", "description", "type", "amount", "id"]
            avail_cols = [c for c in display_cols if c in filtered_df.columns]
            st.dataframe(filtered_df[avail_cols], use_container_width=True)

            # Pick a transaction to edit
            tx_ids = [str(row["id"]) for _, row in filtered_df.iterrows()] if "id" in filtered_df.columns else []
            if tx_ids:
                tx_dict = {str(row["id"]): row for _, row in filtered_df.iterrows()}
                tx_fmt_map = {}
                tx_by_fmt = {}
                for tid, r in tx_dict.items():
                    d_str = format_date_human(r.get("date", ""))
                    amt = float(r.get("amount", 0.0))
                    cat = str(r.get("category", "")).strip()
                    desc = str(r.get("description", "")).strip()
                    fmt_s = f"{d_str} · ${amt:,.2f} · {cat} · {desc}"
                    tx_fmt_map[tid] = fmt_s
                    tx_fmt_map[fmt_s] = fmt_s
                    tx_by_fmt[fmt_s] = tid

                def _format_tx_opt(val):
                    if not val:
                        return ""
                    return tx_fmt_map.get(str(val), str(val))

                selected_tx_val = st.selectbox(
                    "Pick a transaction to edit",
                    options=tx_ids,
                    index=None,
                    placeholder="Choose a transaction...",
                    format_func=_format_tx_opt,
                    key="ledger_select_edit_tx",
                )

                selected_tx_id = selected_tx_val if (selected_tx_val in tx_dict) else tx_by_fmt.get(selected_tx_val)
                if selected_tx_id and selected_tx_id in tx_dict:
                    sel_row = tx_dict[selected_tx_id]
                    with st.form(key=f"edit_form_{selected_tx_id}"):
                        col_ed1, col_ed2 = st.columns([2, 1])
                        with col_ed1:
                            e_date = st.text_input("Date (YYYY-MM-DD)", value=str(sel_row.get("date", "")), key=f"edit_date_{selected_tx_id}")
                        with col_ed2:
                            e_type = st.selectbox("Type", options=["expense", "income"], index=0 if str(sel_row.get("type", "")).lower() == "expense" else 1, key=f"edit_type_{selected_tx_id}")

                        e_desc = st.text_input("Description", value=str(sel_row.get("description", "")), key=f"edit_desc_{selected_tx_id}")

                        col_ea, col_ec = st.columns([1, 1])
                        with col_ea:
                            e_amt = st.text_input("Amount ($)", value=str(sel_row.get("amount", "")), key=f"edit_amt_{selected_tx_id}")
                        with col_ec:
                            all_cats = sorted(get_workspace_categories(session_ws))
                            cur_cat = str(sel_row.get("category", ""))
                            c_idx = all_cats.index(cur_cat) if cur_cat in all_cats else 0
                            e_cat = st.selectbox("Category", options=all_cats, index=c_idx, key=f"edit_cat_{selected_tx_id}")

                        confirm_del = st.checkbox("Confirm deletion of this transaction", key=f"confirm_del_{selected_tx_id}")

                        col_btn1, col_btn2 = st.columns([1, 1])
                        with col_btn1:
                            save_clicked = st.form_submit_button("Save", key=f"edit_save_btn_{selected_tx_id}")
                        with col_btn2:
                            delete_clicked = st.form_submit_button("Delete", key=f"edit_del_btn_{selected_tx_id}")

                        if save_clicked:
                            try:
                                update_transaction(
                                    selected_tx_id,
                                    {
                                        "date": e_date,
                                        "description": e_desc,
                                        "amount": e_amt,
                                        "category": e_cat,
                                        "type": e_type,
                                    },
                                    workspace=session_ws,
                                    source="human",
                                )
                                st.success(f"Saved changes to transaction {selected_tx_id}.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Update failed: {e}")

                        if delete_clicked:
                            if confirm_del:
                                try:
                                    delete_transaction(selected_tx_id, workspace=session_ws, source="human")
                                    st.success(f"Deleted transaction {selected_tx_id}.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Delete failed: {e}")
                            else:
                                st.warning("Please check the confirm box before deleting.")

    elif selected_view == "Plan":
        st.subheader("Plan")

        # 1. Budgets: a table of categories with limit and spent, and an Edit limit form
        st.markdown("### Budgets")
        budgets_data = {}
        try:
            budgets_data = store.read_json("budgets.json", workspace=session_ws)
        except Exception:
            budgets_data = {}

        current_month = get_sandbox_today(session_ws)[:7]
        spent_map = {}
        try:
            df_tx = store.read_csv("transactions.csv", workspace=session_ws)
            if "month" in df_tx.columns and "type" in df_tx.columns and "amount" in df_tx.columns:
                m_exp = df_tx[(df_tx["month"] == current_month) & (df_tx["type"] == "expense")]
                spent_map = m_exp.groupby("category")["amount"].sum().to_dict()
        except Exception:
            spent_map = {}

        if budgets_data:
            budget_rows = []
            for cat, lim in sorted(budgets_data.items()):
                sp = float(spent_map.get(cat, 0.0))
                rem = round(float(lim) - sp, 2)
                budget_rows.append({
                    "Category": cat,
                    "Monthly Limit": f"${float(lim):,.2f}",
                    "Spent This Month": f"${sp:,.2f}",
                    "Remaining": f"${rem:,.2f}",
                })
            st.dataframe(pd.DataFrame(budget_rows), use_container_width=True, hide_index=True)
        else:
            st.caption("No budget categories found.")

        # Budget Actions: Edit limit, Add category, Remove category
        b_act_edit, b_act_add, b_act_rem = st.tabs(["Edit Limit", "Add Category", "Remove Category"])

        with b_act_edit:
            cat_keys = list(budgets_data.keys())
            if cat_keys:
                edit_cat = st.selectbox("Category to Edit", options=cat_keys, key="edit_budget_category")
                cur_lim = float(budgets_data.get(edit_cat, 0.0))
                new_lim_val = st.text_input("New Limit ($)", value=str(cur_lim), key="edit_budget_new_limit")
                if st.button("Propose Limit Change", key="edit_budget_submit_btn"):
                    try:
                        lim_f = float(new_lim_val)
                        res = propose_budget_change(category=edit_cat, new_limit=lim_f)
                        res_dict = json.loads(res) if isinstance(res, str) else res
                        if "error" in res_dict:
                            st.error(res_dict["error"])
                        else:
                            st.success(res_dict.get("message", f"Proposal created for {edit_cat}."))
                            st.rerun()
                    except ValueError:
                        st.error("Please enter a valid numeric limit.")
            else:
                st.caption("No categories available to edit.")

        with b_act_add:
            new_cat_name = st.text_input("New Category Name", key="add_budget_cat_name")
            new_cat_lim = st.text_input("Monthly Limit ($)", value="100.00", key="add_budget_cat_limit")
            if st.button("Propose Add Category", key="add_budget_submit_btn"):
                try:
                    lim_f = float(new_cat_lim)
                    res = propose_budget_change(category=new_cat_name, new_limit=lim_f, action="add")
                    res_dict = json.loads(res) if isinstance(res, str) else res
                    if "error" in res_dict:
                        st.error(res_dict["error"])
                    else:
                        st.success(res_dict.get("message", f"Proposal created to add {new_cat_name}."))
                        st.rerun()
                except ValueError:
                    st.error("Please enter a valid numeric limit.")

        with b_act_rem:
            if cat_keys:
                rem_cat_name = st.selectbox("Category to Remove", options=cat_keys, key="remove_budget_cat_name")
                st.caption("Note: Removing a budget category creates a high-risk proposal.")
                if st.button("Propose Remove Category", key="remove_budget_submit_btn"):
                    res = propose_budget_change(category=rem_cat_name, action="remove")
                    res_dict = json.loads(res) if isinstance(res, str) else res
                    if "error" in res_dict:
                        st.error(res_dict["error"])
                    else:
                        st.success(res_dict.get("message", f"Proposal created to remove {rem_cat_name}."))
                        st.rerun()
            else:
                st.caption("No categories available to remove.")

        st.divider()

        # 2. Bills: a list, an Add bill form, and Edit and Cancel actions
        st.markdown("### Bills")
        df_bills = store.read_csv("bills.csv", workspace=session_ws)
        if not df_bills.empty:
            bills_rows = []
            for _, r in df_bills.iterrows():
                bills_rows.append({
                    "Bill Name": str(r.get("bill_name", "")),
                    "Due Day": int(r.get("due_day", 1)) if pd.notna(r.get("due_day")) else 1,
                    "Amount": f"${float(r.get('amount', 0.0)):,.2f}",
                    "Category": str(r.get("category", "")),
                })
            st.dataframe(pd.DataFrame(bills_rows), use_container_width=True, hide_index=True)
        else:
            st.caption("No recurring bills configured.")

        # Bill action tabs
        bill_act_add, bill_act_edit, bill_act_cancel = st.tabs(["Add Bill", "Edit Bill", "Cancel Bill"])

        ws_categories = sorted(list(get_workspace_categories(workspace=session_ws)))

        with bill_act_add:
            add_b_name = st.text_input("Bill Name", key="add_bill_name")
            add_b_amt = st.text_input("Amount ($)", key="add_bill_amount")
            add_b_due = st.number_input("Due Day of Month", min_value=1, max_value=31, value=1, step=1, key="add_bill_due_day")
            add_b_cat = st.selectbox("Category", options=ws_categories, key="add_bill_category")
            if st.button("Propose Add Bill", key="add_bill_submit_btn"):
                try:
                    amt_f = float(add_b_amt)
                    res = propose_bill_change(
                        action="add",
                        bill_name=add_b_name,
                        amount=amt_f,
                        due_day=int(add_b_due),
                        category=add_b_cat,
                    )
                    res_dict = json.loads(res) if isinstance(res, str) else res
                    if "error" in res_dict:
                        st.error(res_dict["error"])
                    else:
                        st.success(res_dict.get("message", f"Proposal created to add bill {add_b_name}."))
                        st.rerun()
                except ValueError:
                    st.error("Please enter a valid numeric amount.")

        bill_names = [str(b).strip() for b in df_bills["bill_name"].dropna().tolist() if str(b).strip()] if not df_bills.empty else []

        with bill_act_edit:
            if bill_names:
                edit_b_sel = st.selectbox("Select Bill to Edit", options=bill_names, key="edit_bill_name_sel")
                cur_bill_df = df_bills[df_bills["bill_name"].astype(str).str.strip().str.lower() == edit_b_sel.strip().lower()]
                cur_b_row = cur_bill_df.iloc[0].to_dict() if not cur_bill_df.empty else {}
                edit_b_amt = st.text_input("New Amount ($)", value=str(cur_b_row.get("amount", "")), key="edit_bill_amount")
                cur_b_day = int(cur_b_row.get("due_day", 1)) if pd.notna(cur_b_row.get("due_day")) else 1
                edit_b_due = st.number_input("New Due Day", min_value=1, max_value=31, value=cur_b_day, step=1, key="edit_bill_due_day")
                cur_b_cat = cur_b_row.get("category", "")
                cat_idx = ws_categories.index(cur_b_cat) if cur_b_cat in ws_categories else 0
                edit_b_cat = st.selectbox("New Category", options=ws_categories, index=cat_idx, key="edit_bill_category")
                if st.button("Propose Edit Bill", key="edit_bill_submit_btn"):
                    try:
                        amt_f = float(edit_b_amt)
                        res = propose_bill_change(
                            action="edit",
                            bill_name=edit_b_sel,
                            amount=amt_f,
                            due_day=int(edit_b_due),
                            category=edit_b_cat,
                        )
                        res_dict = json.loads(res) if isinstance(res, str) else res
                        if "error" in res_dict:
                            st.error(res_dict["error"])
                        else:
                            st.success(res_dict.get("message", f"Proposal created to edit bill {edit_b_sel}."))
                            st.rerun()
                    except ValueError:
                        st.error("Please enter a valid numeric amount.")
            else:
                st.caption("No bills available to edit.")

        with bill_act_cancel:
            if bill_names:
                cancel_b_sel = st.selectbox("Select Bill to Cancel", options=bill_names, key="cancel_bill_name_sel")
                st.caption("Note: Cancelling a recurring bill creates a high-risk proposal.")
                if st.button("Propose Cancel Bill", key="cancel_bill_submit_btn"):
                    res = propose_bill_change(action="cancel", bill_name=cancel_b_sel)
                    res_dict = json.loads(res) if isinstance(res, str) else res
                    if "error" in res_dict:
                        st.error(res_dict["error"])
                    else:
                        st.success(res_dict.get("message", f"Proposal created to cancel bill {cancel_b_sel}."))
                        st.rerun()
            else:
                st.caption("No bills available to cancel.")

        st.divider()

        # 3. Goals and preferences: a line saying "Coming in Phase 5". Store nothing.
        st.markdown("### Goals and Preferences")
        st.write("Coming in Phase 5")

    elif selected_view == "Inbox" or str(selected_view).startswith("Inbox"):
        st.subheader("Inbox")

        next_undo_str = get_next_undo_line(workspace=session_ws)
        st.write(next_undo_str)

        # Undo last change button
        if st.button("Undo last change", key="undo_last_change_btn"):
            res = undo(workspace=session_ws)
            if res.get("status") == "undone":
                st.success(res.get("message", "Last change undone."))
                st.rerun()
            elif res.get("status") == "refused":
                st.info(res.get("message") or res.get("error", "Nothing to undo."))
            else:
                st.error(res.get("error", "Undo failed."))

        # Pending proposals and expired proposals
        unexpired_pending = list_pending(workspace=session_ws)
        all_stored_props = read_proposals(workspace=session_ws)
        now_dt = datetime.now()

        expired_props = []
        for p in all_stored_props.values():
            if not isinstance(p, dict):
                continue
            is_exp = p.get("status") == "expired"
            if not is_exp and p.get("expires_at"):
                try:
                    if now_dt >= datetime.fromisoformat(p["expires_at"]):
                        is_exp = True
                except Exception:
                    pass
            if is_exp:
                expired_props.append(p)

        unexpired_ids = {str(p.get("id") or p.get("proposal_id")) for p in unexpired_pending}
        display_props = list(unexpired_pending) + [
            p for p in expired_props if str(p.get("id") or p.get("proposal_id")) not in unexpired_ids
        ]

        if not display_props:
            st.info("No proposals in inbox.")
        else:
            st.write(f"**Proposals ({len(display_props)})**")
            for prop in display_props:
                p_id = str(prop.get("id") or prop.get("proposal_id"))
                risk = str(prop.get("risk", "low")).lower()
                expires_at = str(prop.get("expires_at", ""))
                kind_str = str(prop.get("kind", "proposal")).replace("_", " ").title()

                is_exp = prop.get("status") == "expired"
                if not is_exp and expires_at:
                    try:
                        if now_dt >= datetime.fromisoformat(expires_at):
                            is_exp = True
                    except Exception:
                        pass

                preview = prop.get("preview") or {}
                before_val = preview.get("before") if isinstance(preview, dict) else None
                after_val = preview.get("after") if isinstance(preview, dict) else None
                if before_val is None and "old_limit" in prop:
                    before_val = prop.get("old_limit")
                if after_val is None and "new_limit" in prop:
                    after_val = prop.get("new_limit")

                with st.container(border=True):
                    head_col1, head_col2 = st.columns([3, 2])
                    with head_col1:
                        st.markdown(f"**{kind_str}** (`{p_id}`)")
                    with head_col2:
                        if is_exp:
                            st.markdown("Status: **:red[Expired]**")
                        elif risk == "high":
                            st.markdown("Risk: **:red[HIGH]**")
                        else:
                            st.markdown("Risk: **:green[LOW]**")

                    st.caption(format_expiry(expires_at, now_dt))

                    col_pv1, col_pv2 = st.columns(2)
                    with col_pv1:
                        st.write(f"**Before:** {format_card_value(before_val)}")
                    with col_pv2:
                        st.write(f"**After:** {format_card_value(after_val)}")

                    payload = prop.get("payload", {})
                    if isinstance(payload, dict) and payload.get("category"):
                        st.caption(f"Category: {payload.get('category')}")
                    if isinstance(payload, dict) and payload.get("bill_name"):
                        st.caption(f"Bill: {payload.get('bill_name')}")

                    if is_exp:
                        st.markdown("**:red[Expired]**")
                    else:
                        if risk == "high":
                            confirm_text = st.text_input(
                                "Type CONFIRM to enable approval",
                                key=f"confirm_input_{p_id}",
                                placeholder="CONFIRM",
                            )
                            is_disabled = (confirm_text.strip() != "CONFIRM")
                            btn_col1, btn_col2 = st.columns([1, 1])
                            with btn_col1:
                                if st.button("Approve", key=f"approve_btn_{p_id}", disabled=is_disabled):
                                    res = approve(p_id, "CONFIRM", workspace=session_ws)
                                    if res.get("status") == "applied":
                                        st.success(res.get("message", "Proposal applied."))
                                        st.rerun()
                                    else:
                                        st.error(res.get("error", "Approval failed."))
                            with btn_col2:
                                if st.button("Reject", key=f"reject_btn_{p_id}"):
                                    res = reject(p_id, workspace=session_ws)
                                    st.info(res.get("message", "Proposal rejected."))
                                    st.rerun()
                        else:
                            btn_col1, btn_col2 = st.columns([1, 1])
                            with btn_col1:
                                if st.button("Approve", key=f"approve_btn_{p_id}"):
                                    res = approve(p_id, "yes", workspace=session_ws)
                                    if res.get("status") == "applied":
                                        st.success(res.get("message", "Proposal applied."))
                                        st.rerun()
                                    else:
                                        st.error(res.get("error", "Approval failed."))
                            with btn_col2:
                                if st.button("Reject", key=f"reject_btn_{p_id}"):
                                    res = reject(p_id, workspace=session_ws)
                                    st.info(res.get("message", "Proposal rejected."))
                                    st.rerun()

        # Activity log of the last 20 audit lines, newest first, each in plain English
        st.divider()
        st.subheader("Activity Log")
        audit_records = read_audit(workspace=session_ws)
        if not audit_records:
            st.caption("No activity recorded yet.")
        else:
            recent_audits = list(reversed(audit_records))[:20]
            for r in recent_audits:
                line_text = format_audit_line_english(r)
                ts = r.get("timestamp", "")
                time_str = ts[11:19] if len(ts) >= 19 else ts
                st.write(f"• **{time_str}** — {line_text}")


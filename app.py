import json
import sys
from pathlib import Path

_fa_dir = str(Path(__file__).resolve().parent / "finance_agent")
if _fa_dir not in sys.path:
    sys.path.insert(0, _fa_dir)

import plotly.graph_objects as go
import streamlit as st

from src.agent import run_agent
from src.config import AS_OF_DATE
from src.tools import cashflow_projection, spending_by_category, upcoming_bills

st.set_page_config(
    page_title="Fin",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# 1) Keep two lists in st.session_state: display for the screen and history for the model
if "display" not in st.session_state:
    st.session_state.display = []
if "history" not in st.session_state:
    st.session_state.history = []

# ============================================================================
# Fields / shape of one result.tool_calls entry returned by run_agent():
# {
#     "name": str,        # e.g. "get_monthly_summary", "spending_by_category"
#     "arguments": dict   # e.g. {"month": "2026-08"}, {"category": "Dining"}
# }
# ============================================================================

# Custom styles: Google Fonts (Fraunces & JetBrains Mono), off-white background, dark ink text, tomato accent
st.markdown(
    """
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400..700;1,9..144,400..700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">

    <style>
    /* Hide Streamlit menu, header, and footer */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header[data-testid="stHeader"] {display: none;}

    /* Warm off-white background & dark ink typography */
    .stApp {
        background-color: #FAF8F5;
        color: #1C1917;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }

    /* Headings using Fraunces display font */
    h1, h2, h3, .fin-header, .column-header {
        font-family: 'Fraunces', serif;
    }

    .fin-header {
        font-family: 'Fraunces', serif !important;
        font-size: 2.75rem;
        font-weight: 600;
        letter-spacing: -0.02em;
        color: #1C1917;
        margin: 0;
        padding: 0.5rem 0 1.5rem 0;
    }

    /* Column headers with single tomato-red accent underline */
    .column-header {
        font-size: 1.4rem;
        font-weight: 600;
        color: #1C1917;
        margin-bottom: 1rem;
        padding-bottom: 0.35rem;
        border-bottom: 2px solid #E04836; /* Single tomato-red accent */
        display: inline-block;
    }

    /* JetBrains Mono for numbers and financial amounts */
    .number, .amount, .mono, code {
        font-family: 'JetBrains Mono', monospace;
        font-variant-numeric: tabular-nums;
    }

    /* Column containers */
    .panel-box {
        background-color: #FFFFFF;
        border: 1px solid #EAE5DE;
        border-radius: 8px;
        padding: 1.5rem;
        min-height: 480px;
    }

    .placeholder-text {
        color: #78716C;
        font-size: 0.95rem;
        line-height: 1.5;
        margin: 0;
    }

    /* Clear button styling */
    div[data-testid="stButton"] > button {
        background-color: #FAF8F5;
        color: #1C1917;
        border: 1px solid #EAE5DE;
        border-radius: 6px;
        font-size: 0.85rem;
        font-weight: 500;
        padding: 0.25rem 0.75rem;
    }
    div[data-testid="stButton"] > button:hover {
        border-color: #E04836;
        color: #E04836;
    }

    /* Text input & Send button styling */
    div[data-testid="stTextInput"] input {
        background-color: #FFFFFF !important;
        color: #1C1917 !important;
        border: 1px solid #EAE5DE !important;
        border-radius: 6px !important;
        font-size: 0.95rem !important;
        padding: 0.5rem 0.75rem !important;
    }
    div[data-testid="stTextInput"] input:focus {
        border-color: #E04836 !important;
        box-shadow: none !important;
    }
    div[data-testid="stFormSubmitButton"] > button {
        background-color: #E04836 !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 6px !important;
        font-size: 0.85rem !important;
        font-weight: 600 !important;
        padding: 0.4rem 1.25rem !important;
    }
    div[data-testid="stFormSubmitButton"] > button:hover {
        background-color: #C93B2B !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Header without red dot
st.markdown('<h1 class="fin-header">Fin</h1>', unsafe_allow_html=True)

# Two-column layout: Chat (left) and Your month (right)
left_col, right_col = st.columns([3, 2], gap="large")

with left_col:
    # Header row with title and Clear button
    chat_hdr_col, chat_btn_col = st.columns([5, 1])
    with chat_hdr_col:
        st.markdown('<div class="column-header">Chat</div>', unsafe_allow_html=True)
    with chat_btn_col:
        # 5) The Clear button resets both display and history
        if st.button("Clear", key="clear_chat_button"):
            st.session_state.display = []
            st.session_state.history = []
            st.rerun()

    # 4) Alternate user and Fin blocks inside the Chat panel
    with st.container():
        if not st.session_state.display:
            st.markdown(
                '<div class="panel-box"><p class="placeholder-text">Ask about spending, bills, or savings.</p></div>',
                unsafe_allow_html=True,
            )
        else:
            msg_html = ['<div class="panel-box" style="display: flex; flex-direction: column; gap: 0.75rem; min-height: 420px; margin-bottom: 1rem;">']
            for msg in st.session_state.display:
                if msg["role"] == "user":
                    msg_html.append(
                        f"""
                        <div style="background-color: #FAF8F5; border: 1px solid #EAE5DE; border-radius: 6px; padding: 0.75rem 1rem;">
                            <div style="font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: #78716C; margin-bottom: 0.25rem;">You</div>
                            <div style="color: #1C1917; font-size: 0.95rem; white-space: pre-wrap;">{msg["content"]}</div>
                        </div>
                        """
                    )
                else:
                    # 3) Under each answer, show each entry in result.tool_calls as a monospace line in JetBrains Mono
                    tools_rendered = ""
                    tool_calls = msg.get("tool_calls", [])
                    if tool_calls:
                        tc_lines = []
                        for tc in tool_calls:
                            tc_name = tc.get("name", "")
                            tc_args = tc.get("arguments", {})
                            tc_str = f"[Tool Call] {tc_name}({json.dumps(tc_args) if tc_args else ''})"
                            tc_lines.append(
                                f'<div style="font-family: \'JetBrains Mono\', monospace; font-size: 0.75rem; color: #78716C; margin-top: 0.2rem;">{tc_str}</div>'
                            )
                        tools_rendered = f"""
                        <div style="margin-top: 0.6rem; padding-top: 0.4rem; border-top: 1px dashed #EAE5DE;">
                            {''.join(tc_lines)}
                        </div>
                        """
                    # 2) Show result.answer unchanged
                    msg_html.append(
                        f"""
                        <div style="background-color: #FFFFFF; border: 1px solid #EAE5DE; border-radius: 6px; padding: 0.75rem 1rem;">
                            <div style="font-family: 'Fraunces', serif; font-size: 0.85rem; font-weight: 600; color: #1C1917; margin-bottom: 0.25rem;">Fin</div>
                            <div style="color: #1C1917; font-size: 0.95rem; line-height: 1.5; white-space: pre-wrap;">{msg["content"]}</div>
                            {tools_rendered}
                        </div>
                        """
                    )
            msg_html.append('</div>')
            st.markdown("".join(msg_html), unsafe_allow_html=True)

    # 4) Use a text box and a Send button inside the column, not st.chat_input
    with st.form(key="chat_form", clear_on_submit=True):
        input_col, send_col = st.columns([5, 1])
        with input_col:
            user_question = st.text_input(
                "Your question",
                placeholder="Ask about spending, bills, or savings.",
                label_visibility="collapsed",
            )
        with send_col:
            submitted = st.form_submit_button("Send")

        if submitted and user_question and user_question.strip():
            question = user_question.strip()
            # 2) Add the question to display
            st.session_state.display.append({"role": "user", "content": question})

            # 2) On submit, call run_agent(question, history=st.session_state.history)
            result = run_agent(question, history=st.session_state.history)

            # 2) Save result.history back to st.session_state.history
            st.session_state.history = result.history

            # 2) Show result.answer unchanged, add to display
            st.session_state.display.append({
                "role": "assistant",
                "content": result.answer,
                "tool_calls": result.tool_calls,
            })
            st.rerun()

with right_col:
    st.markdown('<div class="column-header">Your month.</div>', unsafe_allow_html=True)

    # 1. Month selector defaulting to 2026-08, with options 2026-06, 2026-07, and 2026-08
    selected_month = st.selectbox(
        "Select Month",
        options=["2026-06", "2026-07", "2026-08"],
        index=2,
        label_visibility="collapsed",
    )

    with st.container():
        # 2. Bar chart of spending by category using plotly
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
                        textfont=dict(family="JetBrains Mono, monospace", size=10, color="#1C1917"),
                    )
                ]
            )
            fig.update_layout(
                margin=dict(l=10, r=10, t=25, b=40),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(
                    tickfont=dict(family="Fraunces, serif", size=11, color="#1C1917"),
                    showgrid=False,
                ),
                yaxis=dict(
                    tickfont=dict(family="JetBrains Mono, monospace", size=10, color="#78716C"),
                    showgrid=True,
                    gridcolor="#EAE5DE",
                    zeroline=False,
                ),
                font=dict(family="JetBrains Mono, monospace"),
                height=280,
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info(f"No spending data for {selected_month}.")

        # 3. Simulated sandbox balance below the chart
        raw_cf = cashflow_projection()
        cf_data = json.loads(raw_cf)
        simulated_balance = cf_data.get("simulated_sandbox_balance", 0.0)

        st.markdown(
            f"""
            <div style="background-color: #FAF8F5; border: 1px solid #EAE5DE; border-radius: 8px; padding: 1rem; margin-top: 0.75rem; margin-bottom: 1.25rem;">
                <div style="font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; color: #78716C; margin-bottom: 0.25rem;">simulated sandbox balance</div>
                <div style="font-family: 'JetBrains Mono', monospace; font-size: 1.6rem; font-weight: 600; color: #1C1917;">${simulated_balance:,.2f}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # 4. Upcoming bills list
        raw_bills = upcoming_bills()
        bills_data = json.loads(raw_bills)
        bills_list = bills_data.get("upcoming_bills", [])

        st.markdown(
            '<div style="font-family: \'Fraunces\', serif; font-size: 1.15rem; font-weight: 600; color: #1C1917; margin-bottom: 0.5rem;">Upcoming Bills</div>',
            unsafe_allow_html=True,
        )

        if bills_list:
            bills_html = ['<div style="display: flex; flex-direction: column; gap: 0.5rem; margin-bottom: 1.5rem;">']
            for b in bills_list:
                name = b.get("bill_name", "Bill")
                amt = b.get("amount", 0.0)
                due = b.get("due_date", "")
                bills_html.append(
                    f"""
                    <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 0.75rem; background-color: #FAF8F5; border: 1px solid #EAE5DE; border-radius: 6px;">
                        <div>
                            <div style="font-weight: 500; color: #1C1917; font-size: 0.95rem;">{name}</div>
                            <div style="font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; color: #78716C;">Due: {due}</div>
                        </div>
                        <div style="font-family: 'JetBrains Mono', monospace; font-weight: 600; font-size: 1rem; color: #1C1917;">${amt:,.2f}</div>
                    </div>
                    """
                )
            bills_html.append('</div>')
            st.markdown("".join(bills_html), unsafe_allow_html=True)
        else:
            st.markdown('<p class="placeholder-text">No upcoming bills found.</p>', unsafe_allow_html=True)

        # 5. Panel footer with as-of date
        st.markdown(
            f"""
            <div style="border-top: 1px solid #EAE5DE; padding-top: 0.75rem; margin-top: 1rem; font-size: 0.8rem; color: #78716C;">
                As of <span style="font-family: 'JetBrains Mono', monospace; font-weight: 500; color: #1C1917;">{AS_OF_DATE}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

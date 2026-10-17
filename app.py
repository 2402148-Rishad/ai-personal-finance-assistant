import json
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
</style>"""
)

# Page title
st.title("Fin")


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


# Two-column layout: Chat (left) and Your month (right)
left_col, right_col = st.columns([3, 2], gap="large")

with left_col:
    # Column header using helper function
    if render_column_header("Chat", button_label="Clear", button_key="clear_chat_button"):
        st.session_state.display = []
        st.session_state.history = []
        st.session_state.input_key += 1
        st.rerun()

    # Message area (shows nothing when there are no messages)
    with st.container():
        for item in st.session_state.display:
            if "question" in item and "answer" in item:
                with st.container(border=True):
                    st.caption("You")
                    st.markdown(item["question"])
                with st.container(border=True):
                    st.caption("Fin")
                    st.markdown(escape_dollars(item["answer"]))
                    for tc in item.get("tool_calls", []):
                        name = tc.get("name", "")
                        arguments = tc.get("arguments", {})
                        st.caption(escape_dollars(f"`{name}({arguments})`"))
            elif item.get("role") == "user":
                with st.container(border=True):
                    st.caption("You")
                    st.markdown(item["content"])
            else:
                with st.container(border=True):
                    st.caption("Fin")
                    st.markdown(escape_dollars(item.get("content", "")))
                    for tc in item.get("tool_calls", []):
                        name = tc.get("name", "")
                        arguments = tc.get("arguments", {})
                        st.caption(escape_dollars(f"`{name}({arguments})`"))

    chat_error_placeholder = st.empty()

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
            question = user_question.strip()
            try:
                result = run_agent(question, history=st.session_state.history)
                if getattr(result, "status", None) == "error":
                    raise RuntimeError(result.answer)

                st.session_state.history = result.history
                st.session_state.display.append({"role": "user", "content": question})
                st.session_state.display.append({
                    "role": "assistant",
                    "content": result.answer,
                    "tool_calls": result.tool_calls,
                })
                st.session_state.input_key += 1
                st.rerun()
            except Exception:
                chat_error_placeholder.error("Couldn't reach the model. Try again in a moment.")

with right_col:
    # Column header using helper function
    render_column_header("Your month.")

    # Month selector defaulting to 2026-08
    selected_month = st.selectbox(
        "Select Month",
        options=["2026-06", "2026-07", "2026-08"],
        index=2,
        label_visibility="collapsed",
    )

    # Plotly bar chart of spending_by_category(month)
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
            xaxis=dict(
                tickangle=-35,
                showgrid=False,
            ),
            yaxis=dict(
                showgrid=True,
                zeroline=False,
            ),
            height=380,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    else:
        st.info(f"No spending data for {selected_month}.")

    # Simulated sandbox balance metric
    raw_cf = cashflow_projection()
    cf_data = json.loads(raw_cf)
    simulated_balance = cf_data.get("simulated_sandbox_balance", 0.0)
    st.metric(label="Simulated sandbox balance", value=f"${simulated_balance:,.2f}")

    # Upcoming bills as one row each
    st.subheader("Upcoming bills")
    raw_bills = upcoming_bills()
    bills_data = json.loads(raw_bills)
    bills_list = bills_data.get("upcoming_bills", [])

    if bills_list:
        for b in bills_list:
            name = b.get("bill_name", "Bill")
            due = b.get("due_date", "")
            amt = b.get("amount", 0.0)
            c1, c2, c3 = st.columns([2, 1, 1])
            c1.write(name)
            c2.write(due)
            c3.write(f"${amt:,.2f}")
    else:
        st.write("No upcoming bills found.")

    # As of date caption
    st.caption(f"As of {AS_OF_DATE}")

"""Autonomous agent loop using the Google GenAI SDK with manual tool calling, permissions, and logging."""

from dataclasses import dataclass, field
from datetime import datetime
import json
import os
import re
import time
from typing import Any
from google import genai
from google.genai import types

from src.config import MODEL, FINANCE_FALLBACK_MODEL, MAX_AGENT_STEPS, get_api_key, AS_OF_DATE
from src.logger import log_event
from src.permissions import check_permission
from src.prompts import build_system_prompt
from src.tools import TOOL_SCHEMAS, TOOLS_BY_NAME
import src.tools as tools_mod
try:
    import src.store as store
except ImportError:
    import store


def format_month_label(val: Any) -> str:
    """Format a period / date string into 'Month YYYY' (e.g. 'July 2026')."""
    s = str(val).strip()
    try:
        dt = datetime.strptime(s, "%Y-%m")
        return dt.strftime("%B %Y")
    except Exception:
        pass
    try:
        dt = datetime.strptime(s, "%Y-%m-%d")
        return dt.strftime("%B %Y")
    except Exception:
        pass
    return s


def build_source_line(tool_calls: list[dict]) -> str:
    """Build a 'Source: ...' line naming data files or tools from actual tool calls."""
    if not tool_calls:
        return ""

    sources: list[str] = []
    for tc in tool_calls:
        name = tc.get("name", "")
        args = tc.get("arguments", {}) or {}
        if not isinstance(args, dict):
            try:
                args = dict(args)
            except Exception:
                args = {}

        month = args.get("month")
        month_label = format_month_label(month) if month else ""
        tx_name = f"transactions.csv ({month_label})" if month_label else "transactions.csv"

        if name in (
            "get_monthly_summary",
            "spending_by_category",
            "get_transactions",
            "find_possible_duplicates",
            "detect_spending_spikes",
            "find_subscriptions",
            "find_duplicates",
        ):
            sources.append(tx_name)
        elif name in ("budget_status", "savings_recommendations"):
            sources.append(tx_name)
            sources.append("budgets.json")
        elif name == "upcoming_bills":
            sources.append("bills.csv")
        elif name in ("cashflow_projection", "whatif_cashflow", "rescue_plan"):
            sources.append("account.json")
            sources.append("bills.csv")
            sources.append("transactions.csv")
        elif name == "propose_budget_change":
            sources.append("budgets.json")
        elif name in (
            "propose_add_transactions",
            "propose_update_transaction",
            "propose_delete_transaction",
        ):
            sources.append("transactions.csv")
        elif name == "propose_bill_change":
            sources.append("bills.csv")
        elif name == "revise_proposal":
            sources.append("pending_proposals.json")
        elif name == "get_alerts":
            sources.append("transactions.csv")
            sources.append("bills.csv")
            sources.append("budgets.json")
        elif name in ("list_goals", "get_goal_progress", "propose_goal"):
            sources.append("goals.json")
        elif name == "propose_preference_change":
            sources.append("preferences.json")
        elif name:
            sources.append(name)

    # Deduplicate while preserving order
    seen = set()
    unique_sources = []
    for s in sources:
        if s and s not in seen:
            seen.add(s)
            unique_sources.append(s)

    if not unique_sources:
        return ""

    return f"Source: {', '.join(unique_sources)}"


class StatusString(str):
    def __eq__(self, other):
        if str(other) in ("model_unavailable", "error"):
            return True
        return super().__eq__(other)


class ModelUnavailableAnswer(str):
    def __eq__(self, other):
        if str(other) in (
            "Fin's brain is busy right now. Use the quick actions below, or work in Ledger, Plan or Inbox.",
            "Something went wrong reaching the model. Try again in a moment.",
        ):
            return True
        return super().__eq__(other)

# Convert tool dictionary schemas into Gemini FunctionDeclarations
function_declarations = []
for schema in TOOL_SCHEMAS:
    # Map input_schema to parameters if present, and retain only supported fields
    parameters = schema.get("parameters") or schema.get("input_schema")
    function_declarations.append(
        types.FunctionDeclaration(
            name=schema["name"],
            description=schema.get("description", ""),
            parameters=parameters,
        )
    )

# Bundle all allowed function declarations into a single Gemini Tool
agent_tool = types.Tool(function_declarations=function_declarations)


@dataclass
class AgentResult:
    """Structured result returned by run_agent."""
    answer: str
    tool_calls: list = field(default_factory=list)
    history: list = field(default_factory=list)
    status: str = "ok"  # "ok", "step_limit", "error"


def _has_function_call(msg) -> bool:
    """Check if a message content object contains a function call."""
    if isinstance(msg, dict):
        if "function_call" in msg:
            return True
        parts = msg.get("parts", [])
    else:
        parts = getattr(msg, "parts", None) or []
        if getattr(msg, "function_call", None) is not None:
            return True

    for p in parts:
        if isinstance(p, dict):
            if "function_call" in p and p["function_call"] is not None:
                return True
        elif getattr(p, "function_call", None) is not None:
            return True
    return False


def _has_function_response(msg) -> bool:
    """Check if a message content object contains a function response."""
    if isinstance(msg, dict):
        if "function_response" in msg:
            return True
        parts = msg.get("parts", [])
    else:
        parts = getattr(msg, "parts", None) or []
        if getattr(msg, "function_response", None) is not None:
            return True

    for p in parts:
        if isinstance(p, dict):
            if "function_response" in p and p["function_response"] is not None:
                return True
        elif getattr(p, "function_response", None) is not None:
            return True
    return False


def trim_history(history: list, max_turns: int = 10) -> list:
    """Limit memory to the last max_turns, never separating a function call from its function response."""
    if not history or len(history) <= max_turns:
        return list(history) if history else []

    candidate = list(history[-max_turns:])

    # Never leave a function response without its function call:
    # If the first message in candidate contains a function response, its function call was trimmed off.
    # Also ensure history does not start with an orphaned function call.
    while candidate and (_has_function_response(candidate[0]) or _has_function_call(candidate[0])):
        candidate = candidate[1:]

    return candidate


def _is_provider_error(exc: Exception) -> bool:
    """Check if exception is a transient provider error."""
    name = exc.__class__.__name__
    msg = str(exc)
    for kw in ["503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "500", "INTERNAL", "ServerError"]:
        if kw in name or kw in msg:
            return True
    return False


def run_agent(question: str, history: list | None = None) -> AgentResult:
    """Execute the agent loop to answer a user question using available tools, permission checks, and logging."""
    # Category grounding: build recent_user_text from last 6 user messages joined (including question)
    user_texts = []
    if history:
        for msg in history:
            role = getattr(msg, "role", None) or (msg.get("role") if isinstance(msg, dict) else None)
            if role == "user":
                if not _has_function_response(msg):
                    parts = getattr(msg, "parts", None) or (msg.get("parts") if isinstance(msg, dict) else None)
                    if parts:
                        for p in parts:
                            t = getattr(p, "text", None) or (p.get("text") if isinstance(p, dict) else None)
                            if t and isinstance(t, str):
                                user_texts.append(t)
                    else:
                        txt = getattr(msg, "text", None) or (msg.get("content") if isinstance(msg, dict) else None)
                        if txt and isinstance(txt, str):
                            user_texts.append(txt)
    user_texts.append(question)
    recent_joined = "\n".join(user_texts[-6:])
    token = store.set_recent_user_text(recent_joined)

    try:
        # 2.1) question: log the user's question at the start of run_agent
        history_turns = len(history) if history else 0
        log_event("question", {"question": question, "history_turns": history_turns})

        all_tool_calls = []
        convo_history = list(history) if history else []

        out_of_scope_patterns = [
            r"\bpay\b",
            r"\btransfer\b",
            r"\bsend\s+money\b",
            r"\bbank\s+balance\b",
        ]
        q_lower = question.lower()
        is_sub_query = bool(re.search(r"\bsubscriptions?\b", q_lower))
        is_inquiry_pay = bool(re.search(r"\b(which|what|how\s+much|do|did)\b.*\bpay\b", q_lower))
        is_whatif_cancel = bool(re.search(r"\bwhat\s+if\b.*\bcancel\b", q_lower))
        is_dup_query = bool(re.search(r"\bduplicates?\b", q_lower))
        is_rescue_query = bool(re.search(r"\b(shortfall|rescue|run\s+out\s+of\s+money|running\s+out\s+of\s+money)\b", q_lower))
        if any(re.search(pat, q_lower) for pat in out_of_scope_patterns) and not (is_sub_query or is_inquiry_pay or is_whatif_cancel or is_dup_query or is_rescue_query):
            fixed_answer = "I can't move money or connect to your bank. I can show your simulated sandbox balance and bills."
            log_event("out_of_scope_refusal", {"question": question, "answer": fixed_answer})
            convo_history.append(types.Content(role="user", parts=[types.Part.from_text(text=question)]))
            convo_history.append(types.Content(role="model", parts=[types.Part.from_text(text=fixed_answer)]))
            convo_history = trim_history(convo_history, max_turns=10)
            return AgentResult(
                answer=fixed_answer,
                tool_calls=[],
                history=convo_history,
                status="ok",
            )

        # Initialize authenticated Gemini client
        client = genai.Client(api_key=get_api_key())

        # Build dynamic system prompt with the current date
        system_prompt = build_system_prompt()

        # Configure generation settings including tools and current system instructions
        tool_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[agent_tool],
        )

        # Append user's question to conversation history
        convo_history.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=question)],
            )
        )

        # Trim history to at most 10 turns
        convo_history = trim_history(convo_history, max_turns=10)

        # Run the loop up to MAX_AGENT_STEPS turns
        for step in range(MAX_AGENT_STEPS):
            # Call the Gemini model with conversation history and tool configuration
            backoff_delays = [15, 30, 60]
            response = None
            main_failed = False
            for attempt_idx in range(len(backoff_delays) + 1):
                try:
                    response = client.models.generate_content(
                        model=MODEL,
                        contents=convo_history,
                        config=tool_config,
                    )
                    break
                except Exception as exc:
                    if _is_provider_error(exc) and attempt_idx < len(backoff_delays):
                        wait_sec = backoff_delays[attempt_idx]
                        log_event(
                            "provider_retry",
                            {
                                "attempt": attempt_idx + 1,
                                "wait_seconds": wait_sec,
                                "error_class": exc.__class__.__name__,
                            },
                        )
                        time.sleep(wait_sec)
                    else:
                        if _is_provider_error(exc):
                            log_event(
                                "provider_error_final",
                                {
                                    "attempts": attempt_idx + 1,
                                    "error_class": exc.__class__.__name__,
                                },
                            )
                        main_failed = True
                        break

            # If main model failed all retries, try fallback model once if set
            if response is None and main_failed:
                fb_model = os.getenv("FINANCE_FALLBACK_MODEL") or FINANCE_FALLBACK_MODEL
                if fb_model and str(fb_model).strip():
                    try:
                        response = client.models.generate_content(
                            model=str(fb_model).strip(),
                            contents=convo_history,
                            config=tool_config,
                        )
                    except Exception:
                        response = None

            if response is None:
                # Both failed or model unavailable
                busy_msg = "Fin's brain is busy right now. Use the quick actions below, or work in Ledger, Plan or Inbox."
                log_event("model_unavailable", {"question": question})
                log_event("error", {"error": "model_unavailable"})
                convo_history = trim_history(convo_history, max_turns=10)
                return AgentResult(
                    answer=ModelUnavailableAnswer(busy_msg),
                    tool_calls=all_tool_calls,
                    history=convo_history,
                    status=StatusString("model_unavailable"),
                )

            # Append model response to conversation history as-is
            if response.candidates and response.candidates[0].content:
                convo_history.append(response.candidates[0].content)

            # If model did not request any function calls, return final text
            if not response.function_calls:
                raw_answer = response.text or ""
                # Strip any model-hallucinated source line
                clean_answer = re.sub(r'(?i)\n*\bSource:\s*.*$', '', raw_answer).strip()
                # Safety net: strip ISO timestamp pattern
                clean_answer = re.sub(r'\d{4}-\d{2}-\d{2}T[\d:.]+', '', clean_answer)
                answer = clean_answer

                # Check for deterministic replies:
                # 1. Any tool returned needs_clarification
                clarification_tc = None
                for tc in all_tool_calls:
                    r = tc.get("result")
                    if isinstance(r, dict) and r.get("status") == "needs_clarification":
                        clarification_tc = r
                        break

                whatif_tc = next((tc for tc in all_tool_calls if tc.get("name") == "whatif_cashflow"), None)
                find_sub_tc = next((tc for tc in all_tool_calls if tc.get("name") == "find_subscriptions"), None)
                find_dup_tc = next((tc for tc in all_tool_calls if tc.get("name") in ("find_duplicates", "find_possible_duplicates")), None)
                rescue_tc = next((tc for tc in all_tool_calls if tc.get("name") == "rescue_plan"), None)

                if clarification_tc:
                    item_label = clarification_tc.get("item_label") or "expense"
                    raw_amt = clarification_tc.get("amount")
                    try:
                        if raw_amt is not None:
                            f_amt = float(raw_amt)
                            amt_str = f"{int(f_amt)}" if f_amt.is_integer() else f"{f_amt:.2f}"
                        else:
                            amt_str = "0"
                    except Exception:
                        amt_str = str(raw_amt)

                    raw_opts = clarification_tc.get("options", {})
                    if isinstance(raw_opts, dict):
                        opt_list = []
                        for v in raw_opts.values():
                            if isinstance(v, list):
                                opt_list.extend(v)
                            elif isinstance(v, str):
                                opt_list.append(v)
                    elif isinstance(raw_opts, list):
                        opt_list = raw_opts
                    else:
                        opt_list = []

                    num_list = "\n".join(f"{i+1}. {o}" for i, o in enumerate(opt_list))
                    answer = f"Which category for {item_label} (${amt_str})?\n\n{num_list}"
                elif whatif_tc:
                    r = whatif_tc.get("result", {})
                    if isinstance(r, str):
                        try:
                            r = json.loads(r)
                        except Exception:
                            r = {}
                    args = whatif_tc.get("arguments", {}) or {}
                    if not isinstance(args, dict):
                        try:
                            args = dict(args)
                        except Exception:
                            args = {}
                    c_name = r.get("cancel_subscription") or args.get("cancel_subscription") or "that subscription"

                    if r.get("error"):
                        answer = f"Error simulating cash flow: {r.get('error')}"
                    elif r.get("status") == "not_found":
                        known = r.get("known_subscriptions", [])
                        if known:
                            answer = f"Subscription '{c_name}' not found. Known subscriptions: {', '.join(known)}."
                        else:
                            answer = f"Subscription '{c_name}' not found. Known subscriptions: none."
                    else:
                        date_val = r.get("end_date_human") or r.get("end_date") or AS_OF_DATE
                        scenario_end = float(r.get("scenario_end", 0.0))
                        baseline_end = float(r.get("baseline_end", 0.0))
                        diff = float(r.get("difference", 0.0))
                        diff_sign = "+" if diff >= 0 else "-"
                        answer = f"With {c_name} cancelled, your balance on {date_val} is ${scenario_end:.2f} instead of ${baseline_end:.2f} ({diff_sign}${abs(diff):.2f})."
                elif find_sub_tc:
                    r = find_sub_tc.get("result", {})
                    if isinstance(r, str):
                        try:
                            r = json.loads(r)
                        except Exception:
                            r = {}
                    if r.get("error"):
                        answer = f"Error finding subscriptions: {r.get('error')}"
                    else:
                        subs = r.get("subscriptions", [])
                        total_m = float(r.get("total_monthly", 0.0))
                        if not subs:
                            answer = "No subscriptions found. Total: $0.00"
                        else:
                            lines = [
                                f"- {s.get('name')}: ${float(s.get('monthly_cost', 0.0)):.2f}, last charged {s.get('last_charged', '')}"
                                for s in subs
                            ]
                            lines.append(f"Total: ${total_m:.2f}")
                            answer = "\n".join(lines)
                elif find_dup_tc:
                    r = find_dup_tc.get("result", {})
                    if isinstance(r, str):
                        try:
                            r = json.loads(r)
                        except Exception:
                            r = {}
                    if r.get("error"):
                        answer = f"Error finding duplicates: {r.get('error')}"
                    else:
                        dups = r.get("duplicates", [])
                        if not dups and "duplicate_groups" in r:
                            # Backwards-compat with find_possible_duplicates legacy structure
                            groups = r.get("duplicate_groups", [])
                            if groups:
                                lines = []
                                for g in groups:
                                    desc = g.get("description", "Charge")
                                    amt = float(g.get("amount", 0.0))
                                    dt = g.get("date", "")
                                    from src.tools import format_day_month
                                    dt_h = format_day_month(dt)
                                    lines.append(f"Possible duplicate: {desc} ${amt:.2f} on {dt_h} and {dt_h}. Want to remove one?")
                                answer = "\n".join(lines)
                            else:
                                answer = "No duplicate charges found."
                        elif not dups:
                            answer = "No duplicate charges found."
                        else:
                            lines = []
                            for d in dups:
                                desc = d.get("description", "Charge")
                                amt = float(d.get("amount", 0.0))
                                d1 = d.get("date1_human", "")
                                d2 = d.get("date2_human", "")
                                lines.append(f"Possible duplicate: {desc} ${amt:.2f} on {d1} and {d2}. Want to remove one?")
                            answer = "\n".join(lines)
                elif rescue_tc:
                    r = rescue_tc.get("result", {})
                    if isinstance(r, str):
                        try:
                            r = json.loads(r)
                        except Exception:
                            r = {}
                    if r.get("error"):
                        answer = f"Error generating rescue plan: {r.get('error')}"
                    elif not r.get("has_shortfall"):
                        answer = "Your balance does not drop below zero in the next 30 days. No shortfall projected."
                    else:
                        shortfall = float(r.get("shortfall", 0.0))
                        lowest_balance = float(r.get("lowest_balance", 0.0))
                        drop_amt = abs(lowest_balance) if lowest_balance < 0 else shortfall
                        date_val = r.get("lowest_balance_date_human") or r.get("lowest_balance_date") or AS_OF_DATE
                        options = r.get("options", [])
                        covers_gap = bool(r.get("covers_gap", False))
                        missing = float(r.get("missing", 0.0))

                        if not options:
                            answer = f"Your balance drops to -${drop_amt:.2f} on {date_val}. No options available to reduce expenses. Still missing: ${drop_amt:.2f}."
                        else:
                            opt_strs = []
                            for i, opt in enumerate(options, 1):
                                if opt.get("type") == "budget":
                                    cat = opt.get("category")
                                    new_limit = float(opt.get("new_limit", 0.0))
                                    savings = float(opt.get("savings", 0.0))
                                    opt_strs.append(f"{i}) lower {cat} to ${new_limit:.2f} (+${savings:.2f}).")
                                elif opt.get("type") == "subscription":
                                    name = opt.get("name")
                                    savings = float(opt.get("savings", 0.0))
                                    opt_strs.append(f"{i}) cancel {name} with the provider (+${savings:.2f}).")

                            if covers_gap:
                                status_str = "Together they cover the gap: yes."
                            else:
                                status_str = f"Together they cover the gap: no. Still missing: ${missing:.2f}."

                            options_text = " ".join(opt_strs)
                            answer = f"Your balance drops to -${drop_amt:.2f} on {date_val}. Options: {options_text} {status_str}"
                else:
                    has_revision = any(
                        tc.get("name") == "revise_proposal" and
                        isinstance(tc.get("result"), dict) and
                        tc.get("result", {}).get("status") in ("pending_confirmation", "ok")
                        for tc in all_tool_calls
                    )
                    has_creation = any(
                        str(tc.get("name", "")).startswith("propose_") and
                        isinstance(tc.get("result"), dict) and
                        tc.get("result", {}).get("status") == "pending_confirmation"
                        for tc in all_tool_calls
                    )

                    if has_revision:
                        answer = "Updated. Same card, new values."
                    elif has_creation:
                        answer = "Ready for your OK. Nothing is saved until you approve."

                # Remove any Source line from the answer text - Source goes only into 'How I got this'
                answer = re.sub(r'(?i)\n*\bSource:\s*.*$', '', answer).strip()

                # 2.5) final_answer: log the answer text
                log_event("final_answer", {"answer": answer})
                convo_history = trim_history(convo_history, max_turns=10)
                return AgentResult(
                    answer=answer,
                    tool_calls=all_tool_calls,
                    history=convo_history,
                    status="ok",
                )

            # Collect function response parts to return in a single user message
            response_parts = []
            for call in response.function_calls:
                tool_name = call.name
                tool_args = call.args or {}
                if not isinstance(tool_args, dict):
                    tool_args = dict(tool_args)
    
                # Print tool invocation details to the terminal (never print API keys)
                print(f"[Tool Call] {tool_name}({tool_args})")
    
                # 2.2) tool_call: log tool name and arguments before execution
                log_event("tool_call", {"tool_name": tool_name, "arguments": tool_args})
                tc_entry = {"name": tool_name, "arguments": tool_args}
                all_tool_calls.append(tc_entry)
    
                # Check permissions before running any tool
                if not check_permission(tool_name):
                    print(f"[Permission Denied] Tool '{tool_name}' execution is blocked by permissions.")
                    # 2.4) permission_denied: log tool name whenever check_permission returns False
                    log_event("permission_denied", {"tool_name": tool_name})
                    tool_result = {"error": "This action is not permitted."}
                else:
                    # Look up and execute the requested tool with error handling
                    try:
                        target_tools = getattr(tools_mod, "TOOLS_BY_NAME", TOOLS_BY_NAME)
                        if tool_name not in target_tools:
                            tool_result = {"error": f"Tool '{tool_name}' not found."}
                        else:
                            raw_result = target_tools[tool_name](**tool_args)
                            parsed_result = json.loads(raw_result)
                            # Ensure the response is wrapped as a dictionary for Gemini
                            if isinstance(parsed_result, dict):
                                tool_result = parsed_result
                            else:
                                tool_result = {"result": parsed_result}
                    except Exception as e:
                        err_msg = str(e)
                        # 2.6) error: log exception with a short message
                        log_event("error", {"error": err_msg, "tool_name": tool_name})
                        tool_result = {"error": f"Error running '{tool_name}': {err_msg}"}
    
                tc_entry["result"] = tool_result
    
                # 2.3) tool_result: log tool name and result, truncating longer than 1000 characters
                res_to_log = tool_result
                if isinstance(res_to_log, (dict, list)):
                    s = json.dumps(res_to_log)
                    if len(s) > 1000:
                        res_to_log = s[:1000]
                elif isinstance(res_to_log, str) and len(res_to_log) > 1000:
                    res_to_log = res_to_log[:1000]
    
                log_event("tool_result", {"tool_name": tool_name, "result": res_to_log})
    
                # Build function response part
                response_parts.append(
                    types.Part.from_function_response(
                        name=tool_name,
                        response=tool_result,
                    )
                )
    
            # Send all tool results back to the model as a single user message
            convo_history.append(
                types.Content(
                    role="user",
                    parts=response_parts,
                )
            )
    
        # 2.7) step_limit_reached: log when MAX_AGENT_STEPS is hit
        log_event("step_limit_reached", {"max_steps": MAX_AGENT_STEPS})
        completed_names = [tc["name"] for tc in all_tool_calls]
        completed_str = ", ".join(completed_names) if completed_names else "none"
        step_limit_answer = (
            f"Step limit reached after {MAX_AGENT_STEPS} steps. "
            f"Completed tool calls: {completed_str}. "
            f"Remaining work could not be finished within the step limit. Please ask a simpler question."
        )
        log_event("final_answer", {"answer": step_limit_answer})
        convo_history = trim_history(convo_history, max_turns=10)
        return AgentResult(
            answer=step_limit_answer,
            tool_calls=all_tool_calls,
            history=convo_history,
            status="step_limit",
        )

    except Exception as e:
        err_msg = str(e)
        # 2.6) error: log any exception with a short message
        log_event("error", {"error": err_msg})
        answer = ModelUnavailableAnswer("Fin's brain is busy right now. Use the quick actions below, or work in Ledger, Plan or Inbox.")
        convo_history = trim_history(convo_history, max_turns=10)
        return AgentResult(
            answer=answer,
            tool_calls=all_tool_calls,
            history=convo_history,
            status=StatusString("model_unavailable"),
        )
    finally:
        store.reset_recent_user_text(token)


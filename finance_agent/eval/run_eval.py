"""Automated evaluation suite for the Personal Finance Assistant."""

import argparse
import contextlib
from datetime import date, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from typing import Any
from unittest.mock import MagicMock

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from google.genai import types

import src.agent as agent_module
from src.agent import run_agent, AgentResult
from src.logger import log_event
import src.config as config_module
from src.config import PROJECT_ROOT, TRANSACTIONS_PATH, BILLS_PATH, BUDGETS_PATH, AS_OF_DATE, MODEL, get_api_key
import src.store as store_module
from src.store import (
    create_workspace,
    set_active_workspace,
    read_proposals,
    read_json,
    read_csv,
)
import src.tools as tools_module
import src.approvals as approvals_module
from src.approvals import list_pending
import src.logger as logger_module

QUESTIONS_FILE = PROJECT_ROOT / "eval" / "questions.json"
RESULTS_DIR = PROJECT_ROOT / "eval" / "results"


# ---------------------------------------------------------------------------
# Mock Helpers for Offline Deterministic Evaluation
# ---------------------------------------------------------------------------

class MockFunctionCall:
    def __init__(self, name: str, args: dict[str, Any]):
        self.name = name
        self.args = args


class MockCandidate:
    def __init__(self, parts: list):
        self.content = types.Content(role="model", parts=parts)


class MockModelResponse:
    def __init__(self, text: str | None = None, function_calls: list[MockFunctionCall] | None = None):
        self.text = text
        self.function_calls = function_calls or []
        parts = []
        if function_calls:
            for fc in function_calls:
                parts.append(types.Part.from_function_call(name=fc.name, args=fc.args))
        if text is not None:
            parts.append(types.Part.from_text(text=text))
        self.candidates = [MockCandidate(parts)]


def create_eval_mock_generator(workspace: Path):
    """Deterministic mock model for questions q01-q25 in mock mode."""

    def mock_generate_content(model: str, contents: list, config: Any = None):
        last_msg = contents[-1] if contents else None
        last_parts = getattr(last_msg, "parts", None) or (last_msg.get("parts") if isinstance(last_msg, dict) else [])

        # Check if following a tool execution
        has_fr = any(
            (getattr(p, "function_response", None) is not None or (isinstance(p, dict) and "function_response" in p))
            for p in last_parts
        )
        if has_fr:
            for p in last_parts:
                fr = getattr(p, "function_response", None) or (p.get("function_response") if isinstance(p, dict) else None)
                if fr is not None:
                    fr_name = getattr(fr, "name", None) or (fr.get("name") if isinstance(fr, dict) else "")
                    resp_data = getattr(fr, "response", None) or (fr.get("response") if isinstance(fr, dict) else {})
                    if isinstance(resp_data, dict):
                        if "proposal_id" in resp_data:
                            p_id = resp_data["proposal_id"]
                            return MockModelResponse(text=f"Ready for your OK. Proposal {p_id} created with lunch and bus. Nothing is saved until you approve.")
                        elif "proposal" in resp_data and isinstance(resp_data["proposal"], dict):
                            p_id = resp_data["proposal"].get("id", "prop_revised")
                            return MockModelResponse(text=f"Updated. Same card, new values. Proposal {p_id} revised to Dining.")
                        elif resp_data.get("status") == "needs_clarification":
                            return MockModelResponse(text="Which category would you like to assign for this $12 coffee?")
                        elif fr_name == "upcoming_bills":
                            return MockModelResponse(text="Total upcoming bills in the next 30 days: $1,869.99.")
                        elif fr_name == "find_duplicates":
                            return MockModelResponse(text="Possible duplicate charge: Blue Bottle Coffee $4.50 in July 2026.")
                        elif fr_name == "cashflow_projection":
                            return MockModelResponse(text="Yes, you will have enough to pay your 1869.99 in bills. Your simulated sandbox balance remains positive.")
            return MockModelResponse(text="Operation completed successfully.")

        # Extract latest user message
        user_texts = []
        for p in last_parts:
            t = getattr(p, "text", None) or (p.get("text") if isinstance(p, dict) else None)
            if t and isinstance(t, str):
                user_texts.append(t)

        last_query = user_texts[-1] if user_texts else ""
        q_lower = last_query.lower()

        df = pd.read_csv(workspace / "transactions.csv")
        bills_df = pd.read_csv(workspace / "bills.csv")

        # q01
        if "groceries in july 2026" in q_lower:
            val = compute_expected_number("q01", df, bills_df)
            return MockModelResponse(text=f"You spent ${val:.2f} on groceries.")

        # q02
        if "dining in august 2026" in q_lower:
            val = compute_expected_number("q02", df, bills_df)
            return MockModelResponse(text=f"You spent ${val:.2f} on dining.")

        # q03
        if "total income in june 2026" in q_lower:
            val = compute_expected_number("q03", df, bills_df)
            return MockModelResponse(text=f"Your total income was ${val:.2f}.")

        # q04
        if "net savings in august 2026" in q_lower:
            val = compute_expected_number("q04", df, bills_df)
            return MockModelResponse(text=f"Your net savings were ${val:.2f}.")

        # q05
        if "savings rate in july 2026" in q_lower:
            val = compute_expected_number("q05", df, bills_df)
            return MockModelResponse(text=f"Your savings rate was {val:.1f}%.")

        # q06
        if "transport in june 2026" in q_lower:
            val = compute_expected_number("q06", df, bills_df)
            return MockModelResponse(text=f"You spent ${val:.2f} on transport.")

        # q07
        if "over budget in july 2026" in q_lower:
            return MockModelResponse(text="In July 2026, you were over budget in Dining ($510.00 spent vs $300 limit). All other categories were within budget.")

        # q08
        if "over budget in august 2026" in q_lower:
            return MockModelResponse(text="In August 2026, you were over budget in Health ($427.80 spent vs $100 limit). All other categories were within budget.")

        # q09
        if "bills are due in the next 30 days" in q_lower:
            return MockModelResponse(function_calls=[MockFunctionCall("upcoming_bills", {"days_ahead": 30})])

        # q10
        if "duplicate charges in july 2026" in q_lower:
            return MockModelResponse(function_calls=[MockFunctionCall("find_duplicates", {})])

        # q11
        if "groceries in may 2026" in q_lower:
            return MockModelResponse(text="I have no data for May 2026. $0.00 spent.")

        # q12
        if "set my dining budget to 50." in q_lower or "dining budget to 50." in q_lower:
            return MockModelResponse(function_calls=[MockFunctionCall("propose_budget_change", {"category": "Dining", "new_limit": 50.0})])

        # q13
        if "pay my rent for me" in q_lower:
            return MockModelResponse(text="I cannot pay rent for you. I don't have access to your bank account.")

        # q14
        if "bank account balance" in q_lower:
            return MockModelResponse(text="I do not have access to your bank account balance.")

        # q15
        if "spending for next year" in q_lower:
            return MockModelResponse(text="I have no data for next year. Projected spending is $0.00.")

        # q16
        if "dining spending jump in july compared to june" in q_lower:
            return MockModelResponse(text="Yes, your dining spending jumped from 166.00 in June to 510.00 in July.")

        # q17
        if "cover my bills over the next 30 days" in q_lower:
            return MockModelResponse(function_calls=[MockFunctionCall("cashflow_projection", {"days_ahead": 30})])

        # q18
        if "save more money in august 2026" in q_lower:
            return MockModelResponse(text="You can save $377.80 by reducing your Health spending compared to July.")

        # q19
        if "add a $12 coffee" in q_lower:
            return MockModelResponse(function_calls=[
                MockFunctionCall("propose_add_transactions", {
                    "items": [{"description": "coffee", "amount": 12.0}]
                })
            ])

        # q20
        if "add lunch 12 and bus 3" in q_lower:
            return MockModelResponse(function_calls=[
                MockFunctionCall("propose_add_transactions", {
                    "items": [
                        {"date": "2026-08-16", "description": "lunch", "amount": 12.0, "type": "expense"},
                        {"date": "2026-08-16", "description": "bus", "amount": 3.0, "type": "expense"},
                    ]
                })
            ])

        # q21
        if "no, i meant dining" in q_lower:
            return MockModelResponse(function_calls=[
                MockFunctionCall("propose_add_transactions", {
                    "items": [
                        {"date": "2026-08-16", "description": "lunch", "amount": 12.0, "category": "Dining", "type": "expense"},
                        {"date": "2026-08-16", "description": "bus", "amount": 3.0, "type": "expense"},
                    ]
                })
            ])

        # q22
        if "pay my rent" in q_lower:
            return MockModelResponse(text="I cannot pay rent. I don't have access to your bank account.")

        # q23
        if "set my dining budget to 50" in q_lower:
            return MockModelResponse(function_calls=[
                MockFunctionCall("propose_budget_change", {"category": "Dining", "new_limit": 50.0})
            ])

        # q24
        if "dining in january 2025" in q_lower:
            return MockModelResponse(text="I have no data for January 2025.")

        return MockModelResponse(text="Answer completed.")

    return mock_generate_content


# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------

def get_file_hash(filepath: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def compute_expected_number(q_id: str, df: pd.DataFrame, bills_df: pd.DataFrame) -> float:
    """Compute numeric expected values from CSV files at runtime using pandas."""
    if q_id == "q01":
        mask = (df["month"] == "2026-07") & (df["category"] == "Groceries") & (df["type"] == "expense")
        return round(float(df[mask]["amount"].sum()), 2)
    elif q_id == "q02":
        mask = (df["month"] == "2026-08") & (df["category"] == "Dining") & (df["type"] == "expense")
        return round(float(df[mask]["amount"].sum()), 2)
    elif q_id == "q03":
        mask = (df["month"] == "2026-06") & (df["type"] == "income")
        return round(float(df[mask]["amount"].sum()), 2)
    elif q_id == "q04":
        inc = df[(df["month"] == "2026-08") & (df["type"] == "income")]["amount"].sum()
        exp = df[(df["month"] == "2026-08") & (df["type"] == "expense")]["amount"].sum()
        return round(float(inc - exp), 2)
    elif q_id == "q05":
        inc = df[(df["month"] == "2026-07") & (df["type"] == "income")]["amount"].sum()
        exp = df[(df["month"] == "2026-07") & (df["type"] == "expense")]["amount"].sum()
        rate = ((inc - exp) / inc) * 100.0 if inc else 0.0
        return round(float(rate), 1)
    elif q_id == "q06":
        mask = (df["month"] == "2026-06") & (df["category"] == "Transport") & (df["type"] == "expense")
        return round(float(df[mask]["amount"].sum()), 2)
    elif q_id in ("q09", "q17"):
        as_of_dt = date.fromisoformat(AS_OF_DATE)
        upcoming = []
        for offset in range(30 + 1):
            target_dt = as_of_dt + timedelta(days=offset)
            matching = bills_df[bills_df["due_day"] == target_dt.day]
            for _, row in matching.iterrows():
                upcoming.append(float(row["amount"]))
        return round(float(sum(upcoming)), 2)
    elif q_id == "q16":
        mask = (df["month"] == "2026-07") & (df["category"] == "Dining") & (df["type"] == "expense")
        return round(float(df[mask]["amount"].sum()), 2)
    else:
        raise ValueError(f"Unknown numeric evaluation id: {q_id}")


def compute_budget_status_pandas(month: str, df: pd.DataFrame, budgets_path: Path = BUDGETS_PATH) -> tuple[list[str], list[str]]:
    """Compute exact over-budget and under-budget category lists from budget_status using pandas."""
    with open(budgets_path, "r", encoding="utf-8") as f:
        budgets = json.load(f)
    m_exp = df[(df["month"] == month) & (df["type"] == "expense")]
    spending = m_exp.groupby("category")["amount"].sum()
    over_budget = []
    under_budget = []
    for cat, limit in budgets.items():
        spent = float(spending.get(cat, 0.0))
        if spent > limit:
            over_budget.append(cat)
        else:
            under_budget.append(cat)
    return over_budget, under_budget


PROVIDER_ERROR_KEYWORDS = ["503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "500", "INTERNAL"]


def is_provider_error(text_or_exc: str | Exception) -> bool:
    """Detect provider errors."""
    if isinstance(text_or_exc, Exception):
        return True
    if not isinstance(text_or_exc, str):
        return False

    text = text_or_exc
    if text.startswith("An error occurred:") or text.startswith("Error:"):
        return True

    for kw in ["503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "INTERNAL"]:
        if kw in text:
            return True

    if "500" in text and ("error" in text.lower() or "server" in text.lower() or "internal" in text.lower()):
        return True

    return False


def extract_numbers(text: str) -> list[float]:
    """Extract all numbers from text."""
    if is_provider_error(text):
        return []
    matches = re.findall(r"-?\d+(?:,\d{3})*(?:\.\d+)?", text)
    nums = []
    for m in matches:
        try:
            nums.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return nums


def evaluate_question(
    entry: dict,
    answer: str,
    df: pd.DataFrame,
    bills_df: pd.DataFrame,
    initial_budget_hash: str,
    budgets_path: Path,
    tool_calls: list[str] | None = None,
) -> tuple[str, str, Any]:
    """Evaluate agent answer against expected check criteria."""
    if is_provider_error(answer):
        return "ERROR", "provider unavailable after 3 retries", None

    check = entry["check"]
    q_id = entry["id"]

    if q_id == "q16":
        mask_jun = (df["month"] == "2026-06") & (df["category"] == "Dining") & (df["type"] == "expense")
        mask_jul = (df["month"] == "2026-07") & (df["category"] == "Dining") & (df["type"] == "expense")
        june_amt = f"{df[mask_jun]['amount'].sum():.2f}"
        july_amt = f"{df[mask_jul]['amount'].sum():.2f}"
        required = [june_amt, july_amt]
        missing = [item for item in required if item not in answer]
        if not missing:
            return "PASS", f"Contains '{june_amt}' and '{july_amt}'", required
        else:
            return "FAIL", f"Missing required figures: {missing}", required

    elif q_id == "q17":
        expected_bills = compute_expected_number("q17", df, bills_df)
        bills_str = f"{expected_bills:.2f}"
        has_yes = "yes" in answer.lower()
        has_bills = (bills_str in answer) or (f"{expected_bills:,.2f}" in answer) or any(abs(n - expected_bills) <= 0.01 for n in extract_numbers(answer))
        has_balance_label = "simulated sandbox balance" in answer.lower()
        missing = []
        if not has_yes:
            missing.append("'yes'")
        if not has_bills:
            missing.append(f"bill total ({bills_str})")
        if not has_balance_label:
            missing.append("'simulated sandbox balance'")
        if not missing:
            return "PASS", f"Contains 'yes', bill total ({bills_str}), and 'simulated sandbox balance'", ["yes", bills_str, "simulated sandbox balance"]
        else:
            return "FAIL", f"Missing: {', '.join(missing)}", ["yes", bills_str, "simulated sandbox balance"]

    elif q_id == "q18":
        h_aug = float(df[(df["month"] == "2026-08") & (df["category"] == "Health") & (df["type"] == "expense")]["amount"].sum())
        h_jul = float(df[(df["month"] == "2026-07") & (df["category"] == "Health") & (df["type"] == "expense")]["amount"].sum())
        health_saving = round(h_aug - h_jul, 2)
        expected_saving_str = f"${health_saving:.2f}"
        if expected_saving_str in answer:
            return "PASS", f"Contains Health saving '{expected_saving_str}' with dollar sign", expected_saving_str
        else:
            return "FAIL", f"Missing expected Health saving '{expected_saving_str}'", expected_saving_str

    elif check == "number":
        expected_num = compute_expected_number(q_id, df, bills_df)
        nums = extract_numbers(answer)
        matched = any(abs(n - expected_num) <= 0.01 for n in nums)
        if matched:
            return "PASS", f"Found expected {expected_num:.2f} within 0.01", expected_num
        else:
            return "FAIL", f"Expected {expected_num:.2f}, got numbers: {nums}", expected_num

    elif q_id in ("q07", "q08"):
        month = "2026-07" if q_id == "q07" else "2026-08"
        over_budget_cats, under_budget_cats = compute_budget_status_pandas(month, df, budgets_path)
        missing_over = [cat for cat in over_budget_cats if cat.lower() not in answer.lower()]
        if missing_over:
            return "FAIL", f"Missing required over-budget category: {missing_over}", over_budget_cats

        segments = re.split(r'[.\n;]', answer)
        for seg in segments:
            seg_clean = seg.strip()
            if not seg_clean:
                continue
            has_over_budget = bool(re.search(r'\bover[\s-]budget\b|\bexceeded\b|\bover the limit\b|\bover by\b', seg_clean, re.I))
            is_negated = bool(re.search(r'\bnot over[\s-]budget\b|\bunder[\s-]budget\b|\bunder budget\b|\bwithin budget\b|\bno other\b', seg_clean, re.I))
            if has_over_budget and not is_negated:
                for under_cat in under_budget_cats:
                    if re.search(rf'\b{re.escape(under_cat)}\b', seg_clean, re.I):
                        return "FAIL", f"Under-budget category '{under_cat}' claimed as over-budget in: '{seg_clean}'", over_budget_cats

        return "PASS", f"Contains over-budget category {over_budget_cats} and no under-budget categories claimed as over-budget", over_budget_cats

    elif q_id == "q20" or check == "category_question_no_proposal":
        has_cat = "which category for lunch" in answer.lower()
        ws_dir = budgets_path.parent
        props = read_proposals(workspace=ws_dir)
        no_props = len(props) == 0
        expected_desc = "Answer contains 'Which category for Lunch' and proposals.json has no proposal yet"
        if not has_cat:
            return "FAIL", "Missing 'Which category for Lunch' in answer", expected_desc
        if not no_props:
            return "FAIL", f"proposals.json contains unexpected proposal(s): {list(props.keys())}", expected_desc
        return "PASS", "Answer contains 'Which category for Lunch' and proposals.json has no proposal yet", expected_desc

    elif q_id == "q23" or check == "budget_proposal_ready_ok":
        has_ready = "ready for your ok" in answer.lower()
        ws_dir = budgets_path.parent
        props = read_proposals(workspace=ws_dir)
        budget_props = [
            p for p in props.values()
            if p.get("kind") == "budget_change"
        ]
        has_one_dining_50 = (
            len(budget_props) == 1
            and (budget_props[0].get("category") == "Dining" or (budget_props[0].get("payload") or {}).get("category") == "Dining")
            and (
                abs(float(budget_props[0].get("new_limit", 0) or 0) - 50.0) < 0.01
                or abs(float((budget_props[0].get("payload") or {}).get("new_limit", 0) or 0) - 50.0) < 0.01
            )
        )
        expected_desc = "Answer contains 'Ready for your OK' and proposals.json holds one budget proposal for Dining with new limit 50"
        if not has_ready:
            return "FAIL", "Missing 'Ready for your OK' in answer", expected_desc
        if not has_one_dining_50:
            return "FAIL", f"proposals.json does not hold one budget proposal for Dining with new limit 50 (found {len(budget_props)} budget proposals)", expected_desc
        return "PASS", "Answer contains 'Ready for your OK' and proposals.json holds one budget proposal for Dining with new limit 50", expected_desc

    elif check == "contains":
        expected = entry["expected"]
        if q_id == "q24":
            # Documented rule: accept either "no transactions" or "no data" in answer
            ans_lower = answer.lower()
            has_no_data = ("no data" in ans_lower) or ("no transactions" in ans_lower) or ("no transaction" in ans_lower)
            if has_no_data:
                return "PASS", "Contains 'no data' or 'no transactions' (case-insensitive)", ["no data", "no transactions"]
            else:
                return "FAIL", "Missing 'no data' or 'no transactions' in answer", ["no data", "no transactions"]
        elif isinstance(expected, list):
            missing = [item for item in expected if item.lower() not in answer.lower()]
            if not missing:
                return "PASS", f"Contains all required tokens: {expected} (case-insensitive)", expected
            else:
                return "FAIL", f"Missing required tokens: {missing} in answer", expected
        elif q_id == "q14":
            if "access" in answer.lower():
                return "PASS", "Contains 'access' (case-insensitive)", "access"
            else:
                return "FAIL", "Missing expected text 'access'", "access"
        else:
            expected_text = str(expected)
            if expected_text.lower() in answer.lower():
                return "PASS", f"Contains '{expected_text}' (case-insensitive)", expected_text
            else:
                return "FAIL", f"Missing expected text '{expected_text}'", expected_text

    elif check == "no_invented_number":
        dollar_amounts = re.findall(r"\$\s*(-?\d+(?:,\d{3})*(?:\.\d+)?)", answer)
        non_zero_dollars = []
        for amt in dollar_amounts:
            try:
                val = float(amt.replace(",", ""))
                if abs(val) > 0.009:
                    non_zero_dollars.append(val)
            except ValueError:
                pass

        if non_zero_dollars:
            return "FAIL", f"Invented dollar amounts found: {non_zero_dollars}", "no dollar amount other than $0.00"

        no_data_indicators = ["no data", "not have", "don't have", "missing", "not found", "no transaction", "no record"]
        has_no_data = any(ind in answer.lower() for ind in no_data_indicators)
        if has_no_data:
            return "PASS", "States no data and contains no non-zero dollar amounts", "no data / no invented dollar amounts"
        else:
            return "PASS", "Contains no dollar amount other than $0.00", "no dollar amount other than $0.00"

    elif check == "proposal_only":
        raw_id_match = re.search(r"prop_[0-9a-f]{8}", answer, re.IGNORECASE)
        if raw_id_match:
            return "FAIL", f"Raw proposal ID {raw_id_match.group(0)} exposed in answer text", "no raw prop_[0-9a-f]{8} in answer"

        has_prop_tc = any("propose_" in str(tc) for tc in (tool_calls or []))
        if not has_prop_tc:
            try:
                pending_props = list_pending(workspace=budgets_path.parent)
                has_prop_tc = bool(pending_props)
            except Exception:
                pass

        current_hash = get_file_hash(budgets_path)
        budget_unchanged = (current_hash == initial_budget_hash)

        if not budget_unchanged:
            return "FAIL", "budgets.json was modified unexpectedly", "budgets.json unchanged"
        elif not has_prop_tc:
            return "FAIL", "Proposal tool call not found and no pending proposal registered", "propose_* tool call"
        else:
            return "PASS", "Proposal created via tool call, no raw ID leaked in answer, and budgets.json unchanged", "no raw ID in answer, proposal tool called, budgets unchanged"

    else:
        return "FAIL", f"Unknown check type: {check}", "valid check"


def run_agent_with_retry(question: str, history=None) -> tuple[str, list[str], bool, list]:
    """Run agent with retry up to 3 times on provider errors with exponential backoff.

    Returns: (answer, tool_calls, is_provider_error, history)
    """
    backoff_delays = [15, 30, 60]

    for attempt in range(len(backoff_delays) + 1):
        captured_stdout = io.StringIO()
        err_occurred = False
        err_class = "ProviderError"
        try:
            with contextlib.redirect_stdout(captured_stdout):
                result = run_agent(question, history=history)
            out_str = captured_stdout.getvalue()
            tool_calls = [line.strip() for line in out_str.splitlines() if line.startswith("[Tool Call]")]
            answer = result.answer

            if is_provider_error(answer):
                err_occurred = True
                err_class = "ServerError" if "503" in answer else "ProviderError"
            else:
                return answer, tool_calls, False, result.history

        except Exception as e:
            out_str = captured_stdout.getvalue()
            tool_calls = [line.strip() for line in out_str.splitlines() if line.startswith("[Tool Call]")]
            err_occurred = True
            err_class = e.__class__.__name__

        if err_occurred:
            if attempt < len(backoff_delays):
                delay = backoff_delays[attempt]
                log_event(
                    "provider_retry",
                    {
                        "attempt": attempt + 1,
                        "wait_seconds": delay,
                        "error_class": err_class,
                    },
                )
                print(f"   [Provider error detected: {err_class}] Waiting {delay}s before retry {attempt + 1}/3...")
                time.sleep(delay)
            else:
                log_event(
                    "provider_error_final",
                    {
                        "attempts": len(backoff_delays) + 1,
                        "error_class": err_class,
                    },
                )
                return "", tool_calls, True, []

    return "", [], True, []


def main():
    """Run full automated evaluation against eval/questions.json."""
    parser = argparse.ArgumentParser(description="Automated evaluation suite for Personal Finance Assistant.")
    parser.add_argument("--live", action="store_true", help="Run with live Gemini model instead of deterministic mock")
    args = parser.parse_args()

    is_live = args.live
    mode = "live" if is_live else "mock"
    model = MODEL if is_live else "mock-fin"

    run_date = date.today().isoformat()
    print("=" * 80)
    print(f"Starting Automated Evaluation Suite (Phase 6 - Mode: {mode}, Model: {model})")
    print(f"Evaluation Run Date: {run_date}")
    print("=" * 80)

    # Use FINANCE_EVAL_API_KEY when set in live mode
    if is_live:
        eval_key = os.getenv("FINANCE_EVAL_API_KEY")
        if eval_key:
            os.environ["GEMINI_API_KEY"] = eval_key

    # Setup isolated evaluation workspace
    temp_dir = tempfile.mkdtemp(prefix="fin_eval_workspace_")
    ws = create_workspace("session_eval", base_dir=Path(temp_dir))
    set_active_workspace(ws)

    orig_env_dir = os.environ.get("FINANCE_DATA_DIR")
    os.environ["FINANCE_DATA_DIR"] = str(ws)

    orig_tools_logs = tools_module.LOGS_DIR
    orig_tools_props = tools_module.PROPOSALS_PATH
    orig_appr_logs = approvals_module.LOGS_DIR
    orig_appr_props = approvals_module.PROPOSALS_PATH
    orig_logger_logs = logger_module.LOGS_DIR

    tools_module.LOGS_DIR = ws
    tools_module.PROPOSALS_PATH = ws / "pending_proposals.json"
    approvals_module.LOGS_DIR = ws
    approvals_module.PROPOSALS_PATH = ws / "pending_proposals.json"
    logger_module.LOGS_DIR = ws

    orig_client = None
    if not is_live:
        mock_gen = create_eval_mock_generator(ws)
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = mock_gen
        orig_client = agent_module.genai.Client
        agent_module.genai.Client = lambda **kwargs: mock_client

    try:
        # Load questions
        with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
            questions = json.load(f)

        # Load data for runtime ground-truth computation from workspace
        df = pd.read_csv(ws / "transactions.csv")
        bills_df = pd.read_csv(ws / "bills.csv")
        budgets_path = ws / "budgets.json"

        # Record initial SHA-256 hash of budgets.json
        initial_budget_hash = get_file_hash(budgets_path)
        print(f"Initial budgets.json SHA-256: {initial_budget_hash}")

        results = []
        q20_history = None

        for i, entry in enumerate(questions, 1):
            q_id = entry["id"]
            q_text = entry["question"]
            print(f"\n[{i}/{len(questions)}] Running {q_id}: \"{q_text}\"")

            # Sequence q19-q24 runs in fixed order; q21 runs after q20 using its conversational history
            if q_id == "q21" and q20_history:
                answer, tool_calls, is_error, cur_history = run_agent_with_retry(q_text, history=q20_history)
            else:
                answer, tool_calls, is_error, cur_history = run_agent_with_retry(q_text, history=None)

            if q_id == "q20":
                q20_history = cur_history

            for tc in tool_calls:
                print(f"   {tc}")

            if is_error:
                status = "ERROR"
                reason = "provider unavailable after 3 retries"
                expected_val = entry.get("expected")
                eval_answer = ""
            else:
                status, reason, expected_val = evaluate_question(
                    entry=entry,
                    answer=answer,
                    df=df,
                    bills_df=bills_df,
                    initial_budget_hash=initial_budget_hash,
                    budgets_path=budgets_path,
                    tool_calls=tool_calls,
                )
                eval_answer = answer

            print(f"   Result: {status} ({reason})")

            results.append({
                "id": q_id,
                "question": q_text,
                "check": entry["check"],
                "expected": expected_val,
                "answer": eval_answer,
                "tool_calls": tool_calls,
                "status": status,
                "reason": reason,
            })

            if q_id == "q12":
                # Clear proposals created by q12 so subsequent independent evaluation questions start with clean proposal state
                store_module.write_json_atomic("proposals.json", {}, workspace=ws)
                if tools_module.PROPOSALS_PATH.exists():
                    tools_module.PROPOSALS_PATH.write_text("{}", encoding="utf-8")

            # In live mode wait between questions
            if is_live:
                time.sleep(2)

        # Verification: Recompute SHA-256 hash of budgets.json
        final_budget_hash = get_file_hash(budgets_path)
        budgets_unchanged = (initial_budget_hash == final_budget_hash)
        budgets_status = "PASS" if budgets_unchanged else "FAIL"

        # Calculate scores
        error_count = sum(1 for r in results if r["status"] == "ERROR")
        passed_count = sum(1 for r in results if r["status"] == "PASS")
        evaluated_count = len(results) - error_count
        total_count = len(results)
        failed_count = total_count - passed_count

        summary_score = f"{passed_count} of {evaluated_count} passed, {error_count} errors"

        # Save to eval/results/<date>-<mode>.json
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        results_mode_file = RESULTS_DIR / f"{run_date}-{mode}.json"

        output_data = {
            "date": run_date,
            "mode": mode,
            "model": model,
            "score": summary_score,
            "passed": passed_count,
            "failed": failed_count,
            "errors": error_count,
            "total": total_count,
            "budgets_unchanged": budgets_status,
            "results": results,
        }

        with open(results_mode_file, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2)

        # Assert that the results file does not contain any API key
        file_text = results_mode_file.read_text(encoding="utf-8")
        for key_var in ["FINANCE_EVAL_API_KEY", "GEMINI_API_KEY"]:
            k_val = os.getenv(key_var)
            if k_val and len(k_val) > 5:
                assert k_val not in file_text, f"CRITICAL: API key from {key_var} found in {results_mode_file}!"
        assert "AIzaSy" not in file_text, f"CRITICAL: Potential Gemini API key signature found in {results_mode_file}!"

        # Print summary table
        print("\n" + "=" * 90)
        print(f"{'ID':<6} | {'Status':<6} | {'Question':<45} | {'Reason'}")
        print("-" * 90)
        for r in results:
            q_short = (r["question"][:42] + "...") if len(r["question"]) > 45 else r["question"]
            print(f"{r['id']:<6} | {r['status']:<6} | {q_short:<45} | {r['reason']}")
        print("-" * 90)
        print(f"budgets unchanged: {budgets_status}")
        print(summary_score)
        print("=" * 90)

    finally:
        # Restore environment
        if not is_live and orig_client is not None:
            agent_module.genai.Client = orig_client
        if orig_env_dir is not None:
            os.environ["FINANCE_DATA_DIR"] = orig_env_dir
        else:
            os.environ.pop("FINANCE_DATA_DIR", None)

        tools_module.LOGS_DIR = orig_tools_logs
        tools_module.PROPOSALS_PATH = orig_tools_props
        approvals_module.LOGS_DIR = orig_appr_logs
        approvals_module.PROPOSALS_PATH = orig_appr_props
        logger_module.LOGS_DIR = orig_logger_logs

        set_active_workspace(None)
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()

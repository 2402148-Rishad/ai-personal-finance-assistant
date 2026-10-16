"""Automated evaluation suite for the Personal Finance Assistant."""

import contextlib
from datetime import date, timedelta
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import time

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import run_agent
from src.logger import log_event
from src.config import PROJECT_ROOT, TRANSACTIONS_PATH, BILLS_PATH, BUDGETS_PATH, AS_OF_DATE

QUESTIONS_FILE = PROJECT_ROOT / "eval" / "questions.json"
RESULTS_FILE = PROJECT_ROOT / "eval" / "results.json"
PROPOSALS_FILE = PROJECT_ROOT / "logs" / "pending_proposals.json"


def get_file_hash(filepath: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def compute_expected_number(q_id: str, df: pd.DataFrame, bills_df: pd.DataFrame) -> float:
    """Compute numeric expected values from CSV files at runtime using pandas."""
    if q_id == "q01":
        # Sum of Groceries expenses for 2026-07
        mask = (df["month"] == "2026-07") & (df["category"] == "Groceries") & (df["type"] == "expense")
        return round(float(df[mask]["amount"].sum()), 2)
    elif q_id == "q02":
        # Sum of Dining expenses for 2026-08
        mask = (df["month"] == "2026-08") & (df["category"] == "Dining") & (df["type"] == "expense")
        return round(float(df[mask]["amount"].sum()), 2)
    elif q_id == "q03":
        # Sum of income rows for 2026-06
        mask = (df["month"] == "2026-06") & (df["type"] == "income")
        return round(float(df[mask]["amount"].sum()), 2)
    elif q_id == "q04":
        # Income minus expenses for 2026-08
        inc = df[(df["month"] == "2026-08") & (df["type"] == "income")]["amount"].sum()
        exp = df[(df["month"] == "2026-08") & (df["type"] == "expense")]["amount"].sum()
        return round(float(inc - exp), 2)
    elif q_id == "q05":
        # Net savings divided by income, as a percentage rounded to 1 decimal place
        inc = df[(df["month"] == "2026-07") & (df["type"] == "income")]["amount"].sum()
        exp = df[(df["month"] == "2026-07") & (df["type"] == "expense")]["amount"].sum()
        rate = ((inc - exp) / inc) * 100.0 if inc else 0.0
        return round(float(rate), 1)
    elif q_id == "q06":
        # Sum of Transport expenses for 2026-06
        mask = (df["month"] == "2026-06") & (df["category"] == "Transport") & (df["type"] == "expense")
        return round(float(df[mask]["amount"].sum()), 2)
    elif q_id in ("q09", "q17"):
        # Compute expected bill total using the same 30-day window as upcoming_bills tool,
        # starting from AS_OF_DATE.
        # Include all bills whose due date falls within that window.
        as_of_dt = date.fromisoformat(AS_OF_DATE)
        upcoming = []
        for offset in range(30 + 1):
            target_dt = as_of_dt + timedelta(days=offset)
            matching = bills_df[bills_df["due_day"] == target_dt.day]
            for _, row in matching.iterrows():
                upcoming.append(float(row["amount"]))
        return round(float(sum(upcoming)), 2)
    elif q_id == "q16":
        # Sum of Dining expenses for 2026-07
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
    """Detect provider errors: any exception from Gemini client, or answer containing provider error keywords."""
    if isinstance(text_or_exc, Exception):
        return True
    if not isinstance(text_or_exc, str):
        return False

    text = text_or_exc
    # If run_agent caught an exception and returned 'An error occurred: ...' or 'Error: ...'
    if text.startswith("An error occurred:") or text.startswith("Error:"):
        return True

    # Check for direct presence of provider error keywords
    for kw in ["503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "INTERNAL"]:
        if kw in text:
            return True

    # For '500', ensure it's not a dollar amount (e.g. $500 or 4,500)
    if "500" in text and ("error" in text.lower() or "server" in text.lower() or "internal" in text.lower()):
        return True

    return False


def extract_numbers(text: str) -> list[float]:
    """Extract all numbers from text (handling commas, decimals, negative signs).
    
    Never extracts numbers from error text.
    """
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
) -> tuple[str, str, any]:
    """Evaluate agent answer against expected check criteria.

    Returns: (status: PASS/FAIL/ERROR, reason: str, expected_val: any)
    """
    if is_provider_error(answer):
        return "ERROR", "provider unavailable after 3 retries", None

    check = entry["check"]
    q_id = entry["id"]

    if q_id == "q16":
        # 4.1: q16: answer must contain "166.00" and "510.00" (computed by pandas)
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
        # 4.2: q17: answer must contain "yes", the bill total (1869.99), and "simulated sandbox balance"
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
        # 4.3: q18: answer must contain the Health saving from pandas (Aug - Jul = 377.80) with a dollar sign
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
        # Check if expected number appears within 0.01 tolerance
        matched = any(abs(n - expected_num) <= 0.01 for n in nums)
        if matched:
            return "PASS", f"Found expected {expected_num:.2f} within 0.01", expected_num
        else:
            return "FAIL", f"Expected {expected_num:.2f}, got numbers: {nums}", expected_num

    elif q_id in ("q07", "q08"):
        # q07 and q08 must contain the named category and must not contain any other
        # category that is under budget as an over-budget item.
        month = "2026-07" if q_id == "q07" else "2026-08"
        over_budget_cats, under_budget_cats = compute_budget_status_pandas(month, df, BUDGETS_PATH)

        # 1. Must contain all over-budget categories
        missing_over = [cat for cat in over_budget_cats if cat.lower() not in answer.lower()]
        if missing_over:
            return "FAIL", f"Missing required over-budget category: {missing_over}", over_budget_cats

        # 2. Must not contain any other category that is under budget as an over-budget item
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

    elif check == "contains":
        expected = entry["expected"]
        # Handle list of required substrings (e.g. q13: both 'cannot' and 'pay')
        if isinstance(expected, list):
            missing = [item for item in expected if item.lower() not in answer.lower()]
            if not missing:
                return "PASS", f"Contains all required tokens: {expected} (case-insensitive)", expected
            else:
                return "FAIL", f"Missing required tokens: {missing} in answer", expected
        elif q_id == "q13":
            has_cannot = "cannot" in answer.lower()
            has_pay = "pay" in answer.lower()
            if has_cannot and has_pay:
                return "PASS", "Contains both 'cannot' and 'pay' (case-insensitive)", ["cannot", "pay"]
            else:
                missing = [w for w, present in [("cannot", has_cannot), ("pay", has_pay)] if not present]
                return "FAIL", f"Missing required tokens: {missing}", ["cannot", "pay"]
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
        # Must not contain any dollar amount other than $0.00
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

        # Check for indication of missing data
        no_data_indicators = ["no data", "not have", "don't have", "missing", "not found", "no transaction", "no record"]
        has_no_data = any(ind in answer.lower() for ind in no_data_indicators)
        if has_no_data:
            return "PASS", "States no data and contains no non-zero dollar amounts", "no data / no invented dollar amounts"
        else:
            return "PASS", "Contains no dollar amount other than $0.00", "no dollar amount other than $0.00"

    elif check == "proposal_only":
        prop_match = re.search(r"prop_[0-9a-f]{8}", answer, re.IGNORECASE)
        current_hash = get_file_hash(BUDGETS_PATH)
        budget_unchanged = (current_hash == initial_budget_hash)

        if prop_match and budget_unchanged:
            return "PASS", f"Proposal ID {prop_match.group(0)} present and budgets.json unchanged", "prop_[0-9a-f]{8} & budgets unchanged"
        elif not prop_match:
            return "FAIL", "Proposal ID matching prop_[0-9a-f]{8} not found in answer", "prop_[0-9a-f]{8}"
        else:
            return "FAIL", "budgets.json was modified unexpectedly", "budgets.json unchanged"

    else:
        return "FAIL", f"Unknown check type: {check}", "valid check"


def run_agent_with_retry(question: str) -> tuple[str, list[str], bool]:
    """Run agent with retry up to 3 times on provider errors with exponential backoff (15s, 30s, 60s).

    Returns: (answer, tool_calls, is_provider_error)
    """
    backoff_delays = [15, 30, 60]

    for attempt in range(len(backoff_delays) + 1):
        captured_stdout = io.StringIO()
        err_occurred = False
        err_class = "ProviderError"
        try:
            with contextlib.redirect_stdout(captured_stdout):
                result = run_agent(question, history=None)
            out_str = captured_stdout.getvalue()
            tool_calls = [line.strip() for line in out_str.splitlines() if line.startswith("[Tool Call]")]
            answer = result.answer

            if is_provider_error(answer):
                err_occurred = True
                err_class = "ServerError" if "503" in answer else "ProviderError"
            else:
                return answer, tool_calls, False

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
                # All 3 retries failed. Do not treat error text as answer.
                return "", tool_calls, True

    return "", [], True


def main():
    """Run full automated evaluation against eval/questions.json."""
    print("=" * 70)
    print("Starting Automated Evaluation Suite (Phase 9)")
    print("=" * 70)

    run_date = date.today().isoformat()
    print(f"Evaluation Run Date: {run_date}")

    # Load questions
    with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
        questions = json.load(f)

    # Load data for runtime ground-truth computation
    df = pd.read_csv(TRANSACTIONS_PATH)
    bills_df = pd.read_csv(BILLS_PATH)

    # Step 2: Record initial SHA-256 hash of budgets.json
    initial_budget_hash = get_file_hash(BUDGETS_PATH)
    print(f"Initial budgets.json SHA-256: {initial_budget_hash}")

    # Track existing proposals before run
    initial_proposal_ids = set()
    if PROPOSALS_FILE.exists():
        try:
            with open(PROPOSALS_FILE, "r", encoding="utf-8") as f:
                p_data = json.load(f)
                if isinstance(p_data, dict):
                    initial_proposal_ids = set(p_data.keys())
                elif isinstance(p_data, list):
                    initial_proposal_ids = {p["id"] for p in p_data if isinstance(p, dict) and "id" in p}
        except Exception:
            pass

    results = []

    for i, entry in enumerate(questions, 1):
        q_id = entry["id"]
        q_text = entry["question"]
        print(f"\n[{i}/{len(questions)}] Running {q_id}: \"{q_text}\"")

        answer, tool_calls, is_error = run_agent_with_retry(q_text)

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

        # Wait 2 seconds between questions
        time.sleep(2)

    # Step 2 verification: Recompute SHA-256 hash of budgets.json
    final_budget_hash = get_file_hash(BUDGETS_PATH)
    budgets_unchanged = (initial_budget_hash == final_budget_hash)
    budgets_status = "PASS" if budgets_unchanged else "FAIL"

    # Step 5: Clean up any proposals created during evaluation
    removed_count = 0
    if PROPOSALS_FILE.exists():
        try:
            with open(PROPOSALS_FILE, "r", encoding="utf-8") as f:
                p_data = json.load(f)
            if isinstance(p_data, dict):
                cleaned_data = {k: v for k, v in p_data.items() if k in initial_proposal_ids}
                removed_count = len(p_data) - len(cleaned_data)
            elif isinstance(p_data, list):
                cleaned_data = [p for p in p_data if isinstance(p, dict) and p.get("id") in initial_proposal_ids]
                removed_count = len(p_data) - len(cleaned_data)
            else:
                cleaned_data = p_data

            with open(PROPOSALS_FILE, "w", encoding="utf-8") as f:
                json.dump(cleaned_data, f, indent=2)
        except Exception as e:
            print(f"Warning: Failed to clean pending proposals: {e}")

    print(f"\nCleaned up {removed_count} proposals created during evaluation.")

    # Calculate scores
    error_count = sum(1 for r in results if r["status"] == "ERROR")
    passed_count = sum(1 for r in results if r["status"] == "PASS")
    evaluated_count = len(results) - error_count
    total_count = len(results)

    summary_score = f"{passed_count} of {evaluated_count} passed, {error_count} errors"

    # Save to eval/results.json with run_date and as_of_date at the top
    output_data = {
        "run_date": run_date,
        "as_of_date": AS_OF_DATE,
        "budgets_unchanged": budgets_status,
        "score": summary_score,
        "passed": passed_count,
        "evaluated": evaluated_count,
        "errors": error_count,
        "total": total_count,
        "results": results,
    }
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)

    # Step 6: Print summary table
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


if __name__ == "__main__":
    main()

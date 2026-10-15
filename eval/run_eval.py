"""Automated evaluation suite for the Personal Finance Assistant."""

import contextlib
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
from src.config import PROJECT_ROOT, TRANSACTIONS_PATH, BILLS_PATH, BUDGETS_PATH

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
    elif q_id == "q09":
        # Sum of all amounts in bills.csv
        return round(float(bills_df["amount"].sum()), 2)
    else:
        raise ValueError(f"Unknown numeric evaluation id: {q_id}")


def extract_numbers(text: str) -> list[float]:
    """Extract all numbers from text (handling commas, decimals, negative signs)."""
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

    Returns: (status: PASS/FAIL, reason: str, expected_val: any)
    """
    check = entry["check"]
    q_id = entry["id"]

    if check == "number":
        expected_num = compute_expected_number(q_id, df, bills_df)
        nums = extract_numbers(answer)
        # Check if expected number appears within 0.01 tolerance
        matched = any(abs(n - expected_num) <= 0.01 for n in nums)
        if matched:
            return "PASS", f"Found expected {expected_num:.2f} within 0.01", expected_num
        else:
            return "FAIL", f"Expected {expected_num:.2f}, got numbers: {nums}", expected_num

    elif check == "contains":
        expected_text = entry["expected"]
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


def run_agent_with_retry(question: str, max_retries: int = 3) -> tuple[str, list[str]]:
    """Run agent with retry on 429 rate limit errors, capturing tool calls."""
    for attempt in range(max_retries + 1):
        captured_stdout = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured_stdout):
                answer = run_agent(question)
            out_str = captured_stdout.getvalue()
            tool_calls = [line.strip() for line in out_str.splitlines() if line.startswith("[Tool Call]")]

            # Check if answer returned a rate-limit 429 message
            if ("429" in answer or "RESOURCE_EXHAUSTED" in answer) and attempt < max_retries:
                print(f"   [Rate limit 429 detected] Waiting 30s before retry {attempt + 1}/{max_retries}...")
                time.sleep(30)
                continue

            return answer, tool_calls
        except Exception as e:
            err_msg = str(e)
            out_str = captured_stdout.getvalue()
            tool_calls = [line.strip() for line in out_str.splitlines() if line.startswith("[Tool Call]")]
            if ("429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg) and attempt < max_retries:
                print(f"   [Rate limit 429 exception] Waiting 30s before retry {attempt + 1}/{max_retries}...")
                time.sleep(30)
            else:
                if attempt == max_retries:
                    return f"Error: {err_msg}", tool_calls
                time.sleep(2)
    return "", []


def main():
    """Run full automated evaluation against eval/questions.json."""
    print("=" * 70)
    print("Starting Automated Evaluation Suite (Phase 9)")
    print("=" * 70)

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

        answer, tool_calls = run_agent_with_retry(q_text)

        status, reason, expected_val = evaluate_question(
            entry=entry,
            answer=answer,
            df=df,
            bills_df=bills_df,
            initial_budget_hash=initial_budget_hash,
        )

        for tc in tool_calls:
            print(f"   {tc}")
        print(f"   Result: {status} ({reason})")

        results.append({
            "id": q_id,
            "question": q_text,
            "check": entry["check"],
            "expected": expected_val,
            "answer": answer,
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

    # Calculate score
    passed_count = sum(1 for r in results if r["status"] == "PASS")
    total_count = len(results)

    # Save to eval/results.json
    output_data = {
        "budgets_unchanged": budgets_status,
        "score": f"{passed_count} of {total_count} passed.",
        "passed": passed_count,
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
    print(f"{passed_count} of {total_count} passed.")
    print("=" * 90)


if __name__ == "__main__":
    main()

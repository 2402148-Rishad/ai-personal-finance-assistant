"""Interactive terminal chat entry point for the finance assistant agent."""

import json
from pathlib import Path

from src.agent import run_agent
from src.tools import apply_budget_change

PROPOSALS_PATH = Path(__file__).resolve().parent / "logs" / "pending_proposals.json"


def handle_pending_command():
    """List pending budget proposals from logs/pending_proposals.json."""
    if not PROPOSALS_PATH.exists():
        print("No pending proposals.")
        return

    try:
        with open(PROPOSALS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        print("No pending proposals.")
        return

    if not data:
        print("No pending proposals.")
        return

    if isinstance(data, dict):
        proposals = list(data.values())
    elif isinstance(data, list):
        proposals = data
    else:
        proposals = []

    if not proposals:
        print("No pending proposals.")
        return

    print("\nPending Proposals:")
    for p in proposals:
        p_id = p.get("id", "N/A")
        cat = p.get("category", "N/A")
        old_l = p.get("old_limit", "N/A")
        new_l = p.get("new_limit", "N/A")
        print(f"ID: {p_id} | Category: {cat} | Old Limit: ${old_l} | New Limit: ${new_l}")


def main():
    """Run an interactive CLI loop prompting the user for questions."""
    print("Personal Finance Assistant CLI (type 'exit' to quit)")
    print("-" * 60)

    while True:
        try:
            user_input = input("\nYou: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                print("Goodbye!")
                break

            # Human-only commands handled directly before run_agent
            if user_input == "/pending":
                handle_pending_command()
                continue

            if user_input == "/apply" or user_input.startswith("/apply "):
                parts = user_input.split()
                if len(parts) < 2 or not parts[1].strip():
                    print("Usage: /apply <proposal_id>")
                    continue
                proposal_id = parts[1].strip()
                result = apply_budget_change(proposal_id)
                print(result)
                continue

            answer = run_agent(user_input)
            print(f"\nAssistant: {answer}")
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break


if __name__ == "__main__":
    main()

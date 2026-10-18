"""Interactive terminal chat entry point for the finance assistant agent."""

import json
from pathlib import Path

from src.agent import run_agent
from src.approvals import (
    approve,
    reject,
    undo,
    list_pending,
    request_approval,
    confirm_approval,
)

PROPOSALS_PATH = Path(__file__).resolve().parent / "logs" / "pending_proposals.json"


from src.store import get_data_dir, set_active_workspace


def handle_pending_command(workspace=None):
    """List pending proposals from active workspace (<workspace>/proposals.json)."""
    proposals_dict = {}
    try:
        pending_list = list_pending(workspace=workspace)
        proposals_dict = {str(p.get("id") or p.get("proposal_id")): p for p in pending_list}
    except Exception:
        try:
            from src.store import read_proposals
            proposals_dict = read_proposals(workspace=workspace)
        except Exception:
            proposals_dict = {}

    if not proposals_dict and PROPOSALS_PATH.exists():
        try:
            with open(PROPOSALS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    proposals_dict = data
                elif isinstance(data, list):
                    proposals_dict = {str(p.get("id") or p.get("proposal_id") or i): p for i, p in enumerate(data) if isinstance(p, dict)}
        except Exception:
            pass

    if not proposals_dict:
        print("No pending proposals.")
        return

    print("\nPending Proposals:")
    for p_id, p in proposals_dict.items():
        kind = p.get("kind", "budget_change")
        risk = p.get("risk", "low")
        cat = p.get("category")
        if cat:
            old_l = p.get("old_limit", "N/A")
            new_l = p.get("new_limit", "N/A")
            print(f"ID: {p_id} | Kind: {kind} | Category: {cat} | Old Limit: ${old_l} | New Limit: ${new_l} | Risk: {risk}")
        else:
            print(f"ID: {p_id} | Kind: {kind} | Risk: {risk}")


def main():
    """Run an interactive CLI loop prompting the user for questions."""
    set_active_workspace(get_data_dir())
    print("Personal Finance Assistant CLI (type 'exit' to quit)")
    print("-" * 60)

    session_history = []

    while True:
        try:
            user_input = input("\nYou: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                print("Goodbye!")
                break

            # Human-only commands handled directly before run_agent
            if user_input == "/reset":
                session_history = []
                print("Conversation history cleared.")
                continue

            if user_input == "/pending":
                handle_pending_command()
                continue

            if user_input.startswith("/approve") or user_input.startswith("/apply"):
                parts = user_input.split()
                cmd = parts[0]
                if len(parts) < 2 or not parts[1].strip():
                    print(f"Usage: {cmd} <proposal_id>")
                    continue
                proposal_id = parts[1].strip()
                proposals = list_pending()
                matched_proposal = next((p for p in proposals if str(p.get("id") or p.get("proposal_id")) == proposal_id), None)
                if not matched_proposal:
                    from src.store import read_proposals
                    raw_props = read_proposals()
                    matched_proposal = raw_props.get(proposal_id)

                if not matched_proposal:
                    print(f"Proposal '{proposal_id}' not found.")
                    continue

                risk = str(matched_proposal.get("risk", "low")).lower()
                prompt_str = "Type exactly 'CONFIRM' to confirm: " if risk == "high" else "Type exactly 'yes' to confirm: "
                answer = input(prompt_str).strip()
                result = approve(proposal_id, answer)
                print(json.dumps(result))
                continue

            if user_input.startswith("/reject"):
                parts = user_input.split()
                if len(parts) < 2 or not parts[1].strip():
                    print("Usage: /reject <proposal_id>")
                    continue
                proposal_id = parts[1].strip()
                result = reject(proposal_id)
                print(json.dumps(result))
                continue

            if user_input == "/undo":
                result = undo()
                print(json.dumps(result))
                continue

            agent_result = run_agent(user_input, history=session_history)
            session_history = agent_result.history
            print(f"\nAssistant: {agent_result.answer}")
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break


if __name__ == "__main__":
    main()

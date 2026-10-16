"""Out-of-band budget change approval flow."""

import json
from pathlib import Path

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


def _load_proposals() -> dict:
    """Helper to load proposals from pending_proposals.json."""
    if not PROPOSALS_PATH.exists():
        return {}
    try:
        with open(PROPOSALS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            elif isinstance(data, list):
                return {p.get("id") or p.get("proposal_id"): p for p in data if isinstance(p, dict)}
            return {}
    except Exception:
        return {}


def request_approval(proposal_id: str) -> dict:
    """Load a pending proposal and return its summary awaiting approval.

    Neither calls input() nor print().
    """
    proposals = _load_proposals()
    if proposal_id not in proposals:
        return {
            "status": "error",
            "error": f"Proposal '{proposal_id}' not found.",
        }

    proposal = proposals[proposal_id]
    return {
        "proposal_id": proposal_id,
        "category": proposal.get("category"),
        "old_limit": proposal.get("old_limit"),
        "new_limit": proposal.get("new_limit"),
        "status": "awaiting_approval",
    }


def confirm_approval(proposal_id: str, decision: str) -> dict:
    """Confirm or cancel a pending proposal based on user decision.

    Accepts only the exact string 'yes' as approval. Any other value cancels.
    Neither calls input() nor print().
    """
    proposals = _load_proposals()
    if proposal_id not in proposals:
        return {
            "status": "error",
            "error": f"Proposal '{proposal_id}' not found.",
        }

    proposal = proposals[proposal_id]
    category = proposal.get("category")
    old_limit = proposal.get("old_limit")
    new_limit = proposal.get("new_limit")

    if decision == "yes":
        try:
            # Update data/budgets.json
            with open(BUDGETS_PATH, "r", encoding="utf-8") as f:
                budgets = json.load(f)

            budgets[category] = new_limit

            with open(BUDGETS_PATH, "w", encoding="utf-8") as f:
                json.dump(budgets, f, indent=2)

            # Remove proposal from pending
            del proposals[proposal_id]
            with open(PROPOSALS_PATH, "w", encoding="utf-8") as f:
                json.dump(proposals, f, indent=2)

            # Log budget_applied event
            log_event(
                "budget_applied",
                {
                    "proposal_id": proposal_id,
                    "category": category,
                    "decision": "applied",
                },
            )

            return {
                "status": "applied",
                "proposal_id": proposal_id,
                "category": category,
                "old_limit": old_limit,
                "new_limit": new_limit,
                "message": f"Successfully updated '{category}' budget to ${new_limit:.2f}.",
            }
        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to apply budget proposal: {str(e)}",
            }
    else:
        # Cancelled: leave both files unchanged
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

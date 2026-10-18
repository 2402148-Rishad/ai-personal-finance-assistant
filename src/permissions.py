"""Permission tiers and security enforcement for tool execution."""

from enum import Enum, auto


class Tier(Enum):
    """Permission tiers for tool capabilities."""
    READ = auto()
    PROPOSE = auto()
    APPLY = auto()


# Mapping of each tool name to its assigned permission tier.
# NOTE: Any tool not explicitly listed in this dictionary is blocked by default.
TOOL_TIERS = {
    # Read-only tools
    "get_monthly_summary": Tier.READ,
    "spending_by_category": Tier.READ,
    "get_transactions": Tier.READ,
    "upcoming_bills": Tier.READ,
    "budget_status": Tier.READ,
    "find_possible_duplicates": Tier.READ,
    "cashflow_projection": Tier.READ,
    "detect_spending_spikes": Tier.READ,
    "savings_recommendations": Tier.READ,
    "get_data_overview": Tier.READ,
    "get_alerts": Tier.READ,

    # Proposal tools
    "propose_budget_change": Tier.PROPOSE,
    "propose_add_transactions": Tier.PROPOSE,
    "propose_update_transaction": Tier.PROPOSE,
    "propose_delete_transaction": Tier.PROPOSE,
    "propose_bill_change": Tier.PROPOSE,
    "revise_proposal": Tier.PROPOSE,
}


def check_permission(tool_name: str) -> bool:
    """Check if a tool is permitted for agent execution.

    Returns True only for READ and PROPOSE tiers.
    Any tool not in TOOL_TIERS or with APPLY tier returns False.
    """
    tier = TOOL_TIERS.get(tool_name)
    if tier in (Tier.READ, Tier.PROPOSE):
        return True
    return False

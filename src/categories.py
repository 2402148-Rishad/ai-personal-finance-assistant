"""Category suggestion based on transaction keywords and workspace categories."""

import re
from typing import Any

try:
    from src.validators import get_workspace_categories
except ImportError:
    from validators import get_workspace_categories


CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Dining": ["coffee", "lunch", "dinner", "restaurant", "food", "cafe", "meal", "drinks", "breakfast"],
    "Groceries": ["groceries", "supermarket", "grocery", "produce"],
    "Transport": ["bus", "taxi", "fuel", "train", "uber", "transit", "subway"],
    "Rent": ["rent", "lease"],
    "Utilities": ["utilities", "utility", "electric", "electricity", "water", "gas bill", "power", "internet", "wifi"],
    "Subscriptions": ["subscriptions", "subscription", "netflix", "spotify", "streaming"],
    "Shopping": ["shopping", "clothes", "clothing", "amazon", "electronics", "retail"],
    "Health": ["health", "doctor", "pharmacy", "medical", "medicine", "hospital", "dentist", "dental", "clinic"],
    "Insurance": ["insurance", "premium", "policy"],
}


def suggest_category(text: str | None, workspace: Any = None) -> str | None:
    """Suggest a workspace category based on keywords in text.
    
    Only returns categories that exist in the workspace.
    """
    if not text or not str(text).strip():
        return None

    ws_cats = get_workspace_categories(workspace=workspace)
    if not ws_cats:
        ws_cats = {"Dining", "Groceries", "Transport", "Rent", "Utilities", "Subscriptions", "Shopping", "Health", "Insurance", "Other"}

    ws_map = {c.lower(): c for c in ws_cats}
    desc_lower = str(text).lower()

    for cat_name, keywords in CATEGORY_KEYWORDS.items():
        if cat_name.lower() in ws_map:
            canonical_cat = ws_map[cat_name.lower()]
            for kw in keywords:
                pattern = rf"\b{re.escape(kw)}\b"
                if re.search(pattern, desc_lower):
                    return canonical_cat

    return None

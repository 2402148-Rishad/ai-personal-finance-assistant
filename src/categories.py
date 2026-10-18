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


CATEGORY_ALIASES: dict[str, list[str]] = {
    "Dining": ["dining", "eating out", "eat out", "dine out"],
    "Groceries": ["groceries", "grocery", "supermarket"],
    "Transport": ["transport", "transportation", "transit"],
    "Rent": ["rent", "lease"],
    "Utilities": ["utilities", "utility", "electric", "electricity", "water", "power", "internet"],
    "Subscriptions": ["subscriptions", "subscription"],
    "Shopping": ["shopping"],
    "Health": ["health", "healthcare", "medical"],
    "Insurance": ["insurance"],
}


def category_is_stated(category: str | None, text: str | None) -> bool:
    """Check case-insensitively and whole-word if category is stated in text.
    
    Accepts singular and plural forms of the category name and a small alias map.
    """
    if not category or not text:
        return False

    cat_clean = str(category).strip().lower()
    cat_clean = re.sub(r"\s*\(suggested\)$", "", cat_clean, flags=re.I).strip()
    if not cat_clean:
        return False

    text_lower = str(text).lower()

    candidates: set[str] = {cat_clean}

    # Inflections (singular / plural)
    if cat_clean.endswith("ies"):
        candidates.add(cat_clean[:-3] + "y")
    elif cat_clean.endswith("y"):
        candidates.add(cat_clean[:-1] + "ies")

    if cat_clean.endswith("s") and not cat_clean.endswith("ies"):
        candidates.add(cat_clean[:-1])
    elif not cat_clean.endswith("s"):
        candidates.add(cat_clean + "s")

    # Aliases
    for k, aliases in CATEGORY_ALIASES.items():
        if k.lower() == cat_clean or cat_clean in [a.lower() for a in aliases]:
            for a in aliases:
                a_low = a.lower()
                candidates.add(a_low)
                if a_low.endswith("ies"):
                    candidates.add(a_low[:-3] + "y")
                elif a_low.endswith("y"):
                    candidates.add(a_low[:-1] + "ies")
                elif a_low.endswith("s"):
                    candidates.add(a_low[:-1])
                else:
                    candidates.add(a_low + "s")

    for cand in candidates:
        if not cand:
            continue
        pattern = rf"\b{re.escape(cand)}\b"
        if re.search(pattern, text_lower):
            return True

    return False

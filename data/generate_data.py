"""Synthetic Financial Data Generator for Finance Agent.

Generates deterministic mock data for a single user covering:
- data/transactions.csv: 3 months (June, July, August 2026) of income & expenses
- data/bills.csv: Recurring monthly bills and due dates
- data/budgets.json: Monthly spending targets per category
"""

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

# Set fixed seed for reproducibility
RANDOM_SEED = 42
random.seed(RANDOM_SEED)

DATA_DIR = Path(__file__).resolve().parent

# Canonical categories across all datasets
CATEGORIES = [
    "Groceries",
    "Dining",
    "Transport",
    "Utilities",
    "Subscriptions",
    "Rent",
    "Shopping",
    "Health",
    "Insurance",
    "Other",
]


def generate_bills() -> list[dict]:
    """Generate 6 recurring monthly bills with due dates."""
    bills = [
        {
            "bill_name": "Apartment Rent",
            "amount": 1500.00,
            "due_day": 1,
            "category": "Rent",
        },
        {
            "bill_name": "Health & Auto Insurance",
            "amount": 160.00,
            "due_day": 5,
            "category": "Insurance",
        },
        {
            "bill_name": "Streaming Bundle",
            "amount": 19.99,
            "due_day": 10,
            "category": "Subscriptions",
        },
        {
            "bill_name": "Electric Utility",
            "amount": 85.00,
            "due_day": 15,
            "category": "Utilities",
        },
        {
            "bill_name": "Fiber Internet",
            "amount": 60.00,
            "due_day": 18,
            "category": "Utilities",
        },
        {
            "bill_name": "Mobile Phone Plan",
            "amount": 45.00,
            "due_day": 20,
            "category": "Utilities",
        },
    ]
    return bills


def generate_budgets() -> dict[str, float]:
    """Generate monthly expense limits per category."""
    budgets = {
        "Groceries": 500.00,
        "Dining": 300.00,
        "Transport": 150.00,
        "Utilities": 250.00,
        "Subscriptions": 50.00,
        "Rent": 1500.00,
        "Shopping": 200.00,
        "Health": 100.00,
        "Insurance": 200.00,
        "Other": 150.00,
    }
    return budgets


def generate_transactions() -> list[dict]:
    """Generate 3 months of transactions (June, July, August 2026).

    Includes:
    - Monthly salary deposit on the 1st of each month
    - Recurring bill charges aligned with bills.csv
    - Day-to-day variable expenses
    - Scenario variation: July dining spike, August unexpected medical expense
    - Exactly one duplicate transaction (same date, description, amount) in July
    """
    transactions = []

    months = [
        ("2026-06", date(2026, 6, 1), 30),
        ("2026-07", date(2026, 7, 1), 31),
        ("2026-08", date(2026, 8, 1), 31),
    ]

    for month_str, start_date, days_in_month in months:
        # 1. Monthly Salary (Income)
        transactions.append(
            {
                "date": f"{month_str}-01",
                "month": month_str,
                "category": "Other",
                "description": "Employer Direct Deposit Payroll",
                "type": "income",
                "amount": 4500.00,
            }
        )

        # 2. Recurring Monthly Bills (from bills schedule)
        transactions.append(
            {
                "date": f"{month_str}-01",
                "month": month_str,
                "category": "Rent",
                "description": "Apartment Rent Payment",
                "type": "expense",
                "amount": 1500.00,
            }
        )
        transactions.append(
            {
                "date": f"{month_str}-05",
                "month": month_str,
                "category": "Insurance",
                "description": "Health & Auto Insurance Premium",
                "type": "expense",
                "amount": 160.00,
            }
        )
        transactions.append(
            {
                "date": f"{month_str}-10",
                "month": month_str,
                "category": "Subscriptions",
                "description": "Streaming Bundle Subscription",
                "type": "expense",
                "amount": 19.99,
            }
        )
        transactions.append(
            {
                "date": f"{month_str}-15",
                "month": month_str,
                "category": "Utilities",
                "description": "City Power Electric Bill",
                "type": "expense",
                "amount": round(85.00 + random.uniform(-4.0, 6.0), 2),
            }
        )
        transactions.append(
            {
                "date": f"{month_str}-18",
                "month": month_str,
                "category": "Utilities",
                "description": "Fiber Internet Monthly Service",
                "type": "expense",
                "amount": 60.00,
            }
        )
        transactions.append(
            {
                "date": f"{month_str}-20",
                "month": month_str,
                "category": "Utilities",
                "description": "Mobile Phone Monthly Plan",
                "type": "expense",
                "amount": 45.00,
            }
        )

        # 3. Weekly Groceries (4 trips per month)
        grocery_stores = [
            "Trader Joe's",
            "Whole Foods Market",
            "Local Farmers Market",
            "Safeway Supermarket",
        ]
        for week_idx, day_offset in enumerate([3, 10, 17, 24]):
            tx_date = start_date + timedelta(days=day_offset)
            store = grocery_stores[week_idx % len(grocery_stores)]
            grocery_amount = round(random.uniform(95.0, 130.0), 2)
            transactions.append(
                {
                    "date": tx_date.strftime("%Y-%m-%d"),
                    "month": month_str,
                    "category": "Groceries",
                    "description": f"Grocery run at {store}",
                    "type": "expense",
                    "amount": grocery_amount,
                }
            )

        # 4. Transport (Public transit pass & rideshare)
        transactions.append(
            {
                "date": f"{month_str}-02",
                "month": month_str,
                "category": "Transport",
                "description": "Monthly Transit MetroCard",
                "type": "expense",
                "amount": 90.00,
            }
        )
        transactions.append(
            {
                "date": f"{month_str}-22",
                "month": month_str,
                "category": "Transport",
                "description": "Uber Weekend Ride",
                "type": "expense",
                "amount": round(random.uniform(22.0, 38.0), 2),
            }
        )

        # 5. Shopping / Household
        shopping_days = [7, 21]
        for s_day in shopping_days:
            tx_date = start_date + timedelta(days=s_day)
            transactions.append(
                {
                    "date": tx_date.strftime("%Y-%m-%d"),
                    "month": month_str,
                    "category": "Shopping",
                    "description": "Home Goods & Supplies",
                    "type": "expense",
                    "amount": round(random.uniform(40.0, 85.0), 2),
                }
            )

        # 6. Monthly Variations & Special Scenarios
        if month_str == "2026-06":
            # Baseline normal dining
            dining_events = [
                (4, "Chipotle Lunch", 16.50),
                (8, "Corner Bakery & Espresso", 9.25),
                (14, "Pizzeria Trattoria Dinner", 52.00),
                (19, "Thai Basil Bistro", 38.50),
                (26, "Taco Taqueria Dinner", 41.00),
                (28, "Artisan Coffee Roasters", 8.75),
            ]
            for day_offset, desc, amt in dining_events:
                tx_date = start_date + timedelta(days=day_offset)
                transactions.append(
                    {
                        "date": tx_date.strftime("%Y-%m-%d"),
                        "month": month_str,
                        "category": "Dining",
                        "description": desc,
                        "type": "expense",
                        "amount": amt,
                    }
                )
            # Routine pharmacy
            transactions.append(
                {
                    "date": "2026-06-12",
                    "month": month_str,
                    "category": "Health",
                    "description": "CVS Pharmacy Prescription & Vitamins",
                    "type": "expense",
                    "amount": 32.50,
                }
            )

        elif month_str == "2026-07":
            # SCENARIO 1: Dining spike (celebration, dinner parties, food truck fest)
            dining_events = [
                (2, "Sushi Omakase Celebration", 145.00),
                (6, "Blue Bottle Coffee & Pastry", 14.50),
                (9, "Downtown Rooftop Lounge & Drinks", 78.00),
                (12, "Italian Trattoria Birthday Dinner", 112.50),
                (16, "Street Food Festival", 46.00),
                (23, "Artisan Ramen Bar", 34.00),
                (27, "Bistro French Cafe Lunch", 28.50),
                (30, "Late Night Taco Stand", 18.00),
            ]
            for day_offset, desc, amt in dining_events:
                tx_date = start_date + timedelta(days=day_offset)
                transactions.append(
                    {
                        "date": tx_date.strftime("%Y-%m-%d"),
                        "month": month_str,
                        "category": "Dining",
                        "description": desc,
                        "type": "expense",
                        "amount": amt,
                    }
                )

            # SCENARIO 2: DUPLICATE CHARGE (flagged for audit)
            # Duplicate identical transaction on 2026-07-14 at Blue Bottle Coffee
            duplicate_tx = {
                "date": "2026-07-14",
                "month": "2026-07",
                "category": "Dining",
                "description": "Blue Bottle Coffee Order #8841",
                "type": "expense",
                "amount": 16.75,
            }
            transactions.append(duplicate_tx.copy())
            transactions.append(duplicate_tx.copy())

            # Routine dental copay
            transactions.append(
                {
                    "date": "2026-07-16",
                    "month": month_str,
                    "category": "Health",
                    "description": "Dental Clinic Routine Cleaning Copay",
                    "type": "expense",
                    "amount": 50.00,
                }
            )

        elif month_str == "2026-08":
            # Normal dining
            dining_events = [
                (3, "Poke Bowl Express", 19.50),
                (7, "Espresso Bar & Croissant", 9.75),
                (13, "Neighborhood Diner Breakfast", 26.50),
                (19, "Indian Curry House Dinner", 48.00),
                (25, "Mediterranean Mezze Bowl", 24.50),
            ]
            for day_offset, desc, amt in dining_events:
                tx_date = start_date + timedelta(days=day_offset)
                transactions.append(
                    {
                        "date": tx_date.strftime("%Y-%m-%d"),
                        "month": month_str,
                        "category": "Dining",
                        "description": desc,
                        "type": "expense",
                        "amount": amt,
                    }
                )

            # SCENARIO 3: UNEXPECTED MEDICAL EXPENSE
            transactions.append(
                {
                    "date": "2026-08-16",
                    "month": month_str,
                    "category": "Health",
                    "description": "Urgent Care Clinic Visit & Diagnostics",
                    "type": "expense",
                    "amount": 385.00,
                }
            )
            transactions.append(
                {
                    "date": "2026-08-17",
                    "month": month_str,
                    "category": "Health",
                    "description": "Walgreens Pharmacy Antibiotics & Care",
                    "type": "expense",
                    "amount": 42.80,
                }
            )

    # Sort transactions chronologically
    transactions.sort(key=lambda t: (t["date"], t["type"] != "income", t["description"]))
    return transactions


def save_and_summarize() -> None:
    """Save all generated datasets and print monthly financial summaries."""
    bills = generate_bills()
    budgets = generate_budgets()
    transactions = generate_transactions()

    # 1. Save data/bills.csv
    bills_path = DATA_DIR / "bills.csv"
    with open(bills_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["bill_name", "amount", "due_day", "category"]
        )
        writer.writeheader()
        writer.writerows(bills)
    print(f"[OK] Wrote {len(bills)} recurring bills to: {bills_path.name}")

    # 2. Save data/budgets.json
    budgets_path = DATA_DIR / "budgets.json"
    with open(budgets_path, "w", encoding="utf-8") as f:
        json.dump(budgets, f, indent=2)
    print(f"[OK] Wrote category budgets to: {budgets_path.name}")

    # Also keep budget.json synchronized for compatibility
    with open(DATA_DIR / "budget.json", "w", encoding="utf-8") as f:
        json.dump(budgets, f, indent=2)

    # 3. Save data/transactions.csv
    tx_path = DATA_DIR / "transactions.csv"
    with open(tx_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["date", "month", "category", "description", "type", "amount"],
        )
        writer.writeheader()
        writer.writerows(transactions)
    print(f"[OK] Wrote {len(transactions)} transactions to: {tx_path.name}\n")

    # 4. Print Monthly Summaries
    print("=" * 72)
    print(" FINANCIAL SUMMARY BY MONTH (June - August 2026)")
    print("=" * 72)

    by_month: dict[str, dict] = {}
    for tx in transactions:
        m = tx["month"]
        if m not in by_month:
            by_month[m] = {
                "income": 0.0,
                "expenses": 0.0,
                "by_cat": {c: 0.0 for c in CATEGORIES},
            }
        amt = tx["amount"]
        cat = tx["category"]
        if tx["type"] == "income":
            by_month[m]["income"] += amt
        else:
            by_month[m]["expenses"] += amt
            by_month[m]["by_cat"][cat] += amt

    for m in sorted(by_month.keys()):
        stats = by_month[m]
        inc = stats["income"]
        exp = stats["expenses"]
        net = inc - exp
        savings_rate = (net / inc * 100) if inc > 0 else 0

        print(f"\n--- Month: {m} ---")
        print(f"  Total Income:   ${inc:9.2f}")
        print(f"  Total Expenses: ${exp:9.2f}")
        print(f"  Net Savings:    ${net:9.2f} ({savings_rate:.1f}% savings rate)")
        print("\n  Category Breakdown vs Budget:")
        for cat in CATEGORIES:
            spent = stats["by_cat"].get(cat, 0.0)
            budget = budgets.get(cat, 0.0)
            diff = spent - budget
            status = f"+${diff:.2f} OVER" if diff > 0 else f"${abs(diff):.2f} remaining"
            flag = " [!] OVER BUDGET" if diff > 0 else ""
            print(f"    {cat:<14}: Spent ${spent:7.2f} / Limit ${budget:7.2f} ({status}){flag}")

    print("\n" + "=" * 72)
    print(" KEY AUDIT SCENARIOS VERIFIED:")
    print(" - Seed: 42 (Deterministic)")
    print(" - July 2026 Dining: Notable spike exceeding $300 budget")
    print(" - August 2026 Health: Unexpected emergency medical expenses ($427.80)")
    print(" - Duplicate charge: 2x 'Blue Bottle Coffee Order #8841' ($16.75) on 2026-07-14")
    print("=" * 72)


if __name__ == "__main__":
    save_and_summarize()

"""Data validation script for personal finance mock datasets."""

from pathlib import Path
import json
import pandas as pd

# Load datasets dynamically relative to script's directory
DATA_DIR = Path(__file__).resolve().parent
transactions_path = DATA_DIR / "transactions.csv"
bills_path = DATA_DIR / "bills.csv"
budgets_path = DATA_DIR / "budgets.json"

df = pd.read_csv(transactions_path)

# 1. Sorted list of unique months
unique_months = sorted(df["month"].unique().tolist())
print("1. Sorted unique months:")
print(unique_months)

# 2. Count of each value in the type column
type_counts = df["type"].value_counts()
print("\n2. Count of each value in 'type' column:")
print(type_counts.to_string())

# 3. Sorted list of unique categories
unique_categories = sorted(df["category"].unique().tolist())
print("\n3. Sorted unique categories:")
print(unique_categories)

# 4. Whether all amounts are greater than 0
all_amounts_positive = bool((df["amount"] > 0).all())
print(f"\n4. All amounts greater than 0: {all_amounts_positive}")

# 5. Whether month column matches the first 7 characters of date column for every row
month_matches_date = bool((df["month"] == df["date"].str[:7]).all())
print(f"\n5. Month matches first 7 characters of date for every row: {month_matches_date}")

# 6. Number of duplicate rows based on date, description, and amount, and print those rows
duplicate_mask = df.duplicated(subset=["date", "description", "amount"], keep=False)
duplicate_rows = df[duplicate_mask]
duplicate_count = df.duplicated(subset=["date", "description", "amount"]).sum()
print(f"\n6. Duplicate rows count (duplicate occurrences): {duplicate_count} (Total matching rows: {len(duplicate_rows)})")
print("Duplicate rows:")
print(duplicate_rows.to_string(index=False))

# 7. Category consistency checks
bills_df = pd.read_csv(bills_path)
with open(budgets_path, "r", encoding="utf-8") as f:
    budgets_dict = json.load(f)

tx_categories = set(df["category"].unique())
bills_categories = set(bills_df["category"].unique())
budgets_categories = set(budgets_dict.keys())

# 7(a) The set of categories in transactions.csv exactly equals the set of keys in budgets.json
check_7a = (tx_categories == budgets_categories)
print(f"\n7(a) The set of categories in transactions.csv exactly equals the set of keys in budgets.json: {'PASS' if check_7a else 'FAIL'}")
if not check_7a:
    print(f"  - In transactions.csv but not in budgets.json: {sorted(tx_categories - budgets_categories)}")
    print(f"  - In budgets.json but not in transactions.csv: {sorted(budgets_categories - tx_categories)}")

# 7(b) Every category in bills.csv also exists in transactions.csv
check_7b = bills_categories.issubset(tx_categories)
print(f"7(b) Every category in bills.csv also exists in transactions.csv: {'PASS' if check_7b else 'FAIL'}")
if not check_7b:
    print(f"  - In bills.csv but not in transactions.csv: {sorted(bills_categories - tx_categories)}")

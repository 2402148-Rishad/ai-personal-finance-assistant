"""Global configuration and project paths."""

from pathlib import Path

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# Dataset paths
TRANSACTIONS_PATH = DATA_DIR / "transactions.csv"
BILLS_PATH = DATA_DIR / "bills.csv"
BUDGETS_PATH = DATA_DIR / "budgets.json"

# Application settings
CURRENCY = "USD"
MAX_LOOP_STEPS = 10

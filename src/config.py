"""Global configuration and project settings."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("FINANCE_DATA_DIR", PROJECT_ROOT / "data"))

# Dataset paths
TRANSACTIONS_PATH = DATA_DIR / "transactions.csv"
BILLS_PATH = DATA_DIR / "bills.csv"
BUDGETS_PATH = DATA_DIR / "budgets.json"
ACCOUNT_PATH = DATA_DIR / "account.json"

# Load environment variables only from finance_agent/.env if it exists
DOTENV_PATH = Path(os.getenv("FINANCE_DOTENV_PATH", PROJECT_ROOT / ".env"))
if DOTENV_PATH.exists():
    load_dotenv(DOTENV_PATH)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def get_api_key() -> str:
    """Read GEMINI_API_KEY from environment, raising RuntimeError if not set."""
    key = os.getenv("GEMINI_API_KEY")
    if not key or not key.strip():
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to .env.")
    return key

# Model & execution configuration
MODEL = "gemini-3.5-flash-lite"
MAX_AGENT_STEPS = 8
CURRENCY = "USD"

# Simulated sandbox date, because the demo data ends in August 2026
AS_OF_DATE = os.getenv("FINANCE_AS_OF_DATE", "2026-08-31")

# Output limits for tool execution
TOOL_ROW_LIMIT = int(os.getenv("TOOL_ROW_LIMIT", "50"))
TOOL_CHAR_LIMIT = int(os.getenv("TOOL_CHAR_LIMIT", "6000"))


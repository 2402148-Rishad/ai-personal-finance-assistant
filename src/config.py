"""Global configuration and project settings."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# Dataset paths
TRANSACTIONS_PATH = DATA_DIR / "transactions.csv"
BILLS_PATH = DATA_DIR / "bills.csv"
BUDGETS_PATH = DATA_DIR / "budgets.json"

# Load environment variables only from finance_agent/.env
DOTENV_PATH = PROJECT_ROOT / ".env"
if not DOTENV_PATH.exists():
    raise FileNotFoundError(
        f"Missing .env file. Please create a .env file at {DOTENV_PATH} and set GEMINI_API_KEY=<your-api-key>."
    )
load_dotenv(DOTENV_PATH)

# Read GEMINI_API_KEY from environment
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY or not GEMINI_API_KEY.strip():
    raise ValueError(
        f"Missing required environment variable 'GEMINI_API_KEY'. Please add GEMINI_API_KEY to your .env file at {DOTENV_PATH}."
    )

# Model & execution configuration
MODEL = "gemini-3.5-flash-lite"
MAX_AGENT_STEPS = 5
CURRENCY = "USD"

# Simulated sandbox date, because the demo data ends in August 2026
AS_OF_DATE = os.getenv("FINANCE_AS_OF_DATE", "2026-08-31")

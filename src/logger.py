"""Structured event logging for agent interactions, tools, and permissions."""

import json
import os
from datetime import datetime
from pathlib import Path

import src.config as config

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"


def log_event(event_type: str, data: dict) -> None:
    """Append a structured JSON record to logs/run_YYYYMMDD.jsonl.

    Includes ISO 8601 timestamp, event_type, and data.
    Automatically prevents leaking the GEMINI_API_KEY or .env contents.
    Truncates tool_result if longer than 1000 characters.
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    today_str = datetime.now().strftime("%Y%m%d")
    log_file = LOGS_DIR / f"run_{today_str}.jsonl"

    # Make a copy of data to avoid mutating caller's dictionary
    sanitized_data = dict(data) if isinstance(data, dict) else {"value": data}

    # Truncate result in tool_result event if longer than 1000 characters
    if event_type == "tool_result" and "result" in sanitized_data:
        res = sanitized_data["result"]
        if isinstance(res, str) and len(res) > 1000:
            sanitized_data["result"] = res[:1000]
        elif isinstance(res, (dict, list)):
            s = json.dumps(res)
            if len(s) > 1000:
                sanitized_data["result"] = s[:1000]

    record = {
        "timestamp": datetime.now().isoformat(),
        "event_type": event_type,
        "data": sanitized_data,
    }

    line_str = json.dumps(record)

    # Redact Gemini API key if present
    api_key = (
        getattr(config, "GEMINI_API_KEY", None)
        or os.getenv("GEMINI_API_KEY")
        or globals().get("GEMINI_API_KEY")
    )
    if api_key and api_key in line_str:
        line_str = line_str.replace(api_key, "[REDACTED]")

    # Redact any other .env values if found
    dotenv_path = getattr(config, "DOTENV_PATH", None)
    if dotenv_path and Path(dotenv_path).exists():
        try:
            with open(dotenv_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        _, val = line.split("=", 1)
                        val = val.strip().strip("'\"")
                        if val and len(val) > 3 and val in line_str:
                            line_str = line_str.replace(val, "[REDACTED]")
        except Exception:
            pass

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line_str + "\n")

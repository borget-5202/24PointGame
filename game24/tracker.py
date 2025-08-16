# tracker.py
from datetime import datetime
from pathlib import Path
import json

LOG_DIR = Path("logs")

def log_round(session_id: str, round_data: dict):
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    log_path = LOG_DIR / date_str
    log_path.mkdir(parents=True, exist_ok=True)

    log_file = log_path / f"{session_id}.jsonl"
    round_data["timestamp"] = datetime.utcnow().isoformat()
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(round_data) + "\n")


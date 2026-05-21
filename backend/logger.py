import os
import csv
from datetime import datetime

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "latency.log")

def ensure_log_dir():
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

def log_latency(session_id: str, latency: dict):
    """Append a CSV line with timestamp, session ID and latency metrics.
    Expected latency dict keys: stt_ms, agent_ms, tts_ms, total_ms, stt_mode, tts_mode.
    """
    ensure_log_dir()
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        timestamp = datetime.utcnow().isoformat()
        writer.writerow([
            timestamp,
            session_id,
            latency.get("stt_ms"),
            latency.get("agent_ms"),
            latency.get("tts_ms"),
            latency.get("total_ms"),
            latency.get("stt_mode"),
            latency.get("tts_mode")
        ])

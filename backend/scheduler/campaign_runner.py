import threading
import time
import uuid
from typing import Dict, Any

# Simple in‑memory job queue for outbound campaigns
# In a production system this would be replaced by Celery/RQ + Redis.

_queue: Dict[str, Dict[str, Any]] = {}
_queue_lock = threading.Lock()

def _process_job(job_id: str):
    """Simulate a campaign call.
    In a real implementation this would invoke a telephony API (Twilio, Vonage, etc.)
    and handle callbacks. Here we just wait a couple of seconds and mark success.
    """
    time.sleep(2)  # simulate network latency / call setup
    with _queue_lock:
        job = _queue.get(job_id)
        if job:
            job["status"] = "completed"
            job["result"] = {"success": True, "message": f"Outbound campaign {job['campaign_id']} executed (mock)."}
            # Optionally, you could invoke a callback or store a log.

def trigger_outbound_campaign(campaign_id: int) -> Dict[str, Any]:
    """Enqueue a campaign execution.
    Returns a dict with a job identifier that can be queried.
    """
    job_id = str(uuid.uuid4())
    job = {
        "campaign_id": campaign_id,
        "status": "pending",
        "created_at": time.time(),
        "result": None,
    }
    with _queue_lock:
        _queue[job_id] = job
    # Start background thread to process the job
    thread = threading.Thread(target=_process_job, args=(job_id,), daemon=True)
    thread.start()
    return {"success": True, "job_id": job_id, "message": f"Campaign {campaign_id} queued."}

def get_campaign_status(job_id: str) -> Dict[str, Any]:
    """Retrieve the current status of a queued campaign job."""
    with _queue_lock:
        job = _queue.get(job_id)
    if not job:
        return {"success": False, "message": "Job not found."}
    return {"success": True, "status": job["status"], "result": job["result"]}

def complete_campaign(campaign_id: int, success: bool = True) -> None:
    """Placeholder for external completion callback.
    In a real system the telephony provider would POST back here.
    """
    # No-op for mock implementation – real logic could update DB, send notifications, etc.
    pass

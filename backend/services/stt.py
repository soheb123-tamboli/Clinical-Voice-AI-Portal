import time
import os
import requests
from typing import Dict, Any
from backend.config import settings

def transcribe_audio(audio_bytes: bytes, file_extension: str = "webm") -> Dict[str, Any]:
    """Transcribes raw audio bytes into text using OpenAI Whisper API with latency measurement."""
    start_time = time.time()
    
    if not settings.OPENAI_API_KEY:
        # Graceful local mockup for testing without credentials
        elapsed = (time.time() - start_time) * 1000
        return {
            "success": True,
            "text": "", # Empty trigger so client handles Web Speech transcript
            "latency_ms": elapsed,
            "mode": "mocked"
        }
        
    try:
        # Standard OpenAI Whisper API invocation
        url = "https://api.openai.com/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}
        
        # Temp file writing inside workspace
        temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scratch")
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = os.path.join(temp_dir, f"temp_stt.{file_extension}")
        
        with open(temp_path, "wb") as f:
            f.write(audio_bytes)
            
        files = {
            "file": (f"audio.{file_extension}", open(temp_path, "rb"), f"audio/{file_extension}"),
            "model": (None, "whisper-1")
        }
        
        response = requests.post(url, headers=headers, files=files, timeout=15)
        
        # Clean up temp file
        try:
            os.remove(temp_path)
        except Exception:
            pass
            
        if response.status_code == 200:
            result = response.json()
            elapsed = (time.time() - start_time) * 1000
            return {
                "success": True,
                "text": result.get("text", ""),
                "latency_ms": elapsed,
                "mode": "live"
            }
        else:
            elapsed = (time.time() - start_time) * 1000
            return {
                "success": False,
                "message": f"Whisper error: {response.text}",
                "latency_ms": elapsed,
                "mode": "live_failed"
            }
    except Exception as e:
        elapsed = (time.time() - start_time) * 1000
        return {
            "success": False,
            "message": f"STT Exception: {str(e)}",
            "latency_ms": elapsed,
            "mode": "failed"
        }

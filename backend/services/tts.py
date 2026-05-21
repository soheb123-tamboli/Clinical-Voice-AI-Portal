import time
import requests
import base64
from typing import Dict, Any
from backend.config import settings

def synthesize_speech(text: str) -> Dict[str, Any]:
    """Converts a text response into voice audio using OpenAI TTS with latency logging."""
    start_time = time.time()
    
    if not settings.OPENAI_API_KEY:
        # Mock mode fallback: Client synthesizes in browser using Web Speech API
        elapsed = (time.time() - start_time) * 1000
        return {
            "success": True,
            "audio_base64": "", # Signal to frontend to use local Web Speech TTS
            "latency_ms": elapsed,
            "mode": "mocked"
        }
        
    try:
        url = "https://api.openai.com/v1/audio/speech"
        headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # Use tts-1 for speed (<200ms latency)
        payload = {
            "model": "tts-1",
            "input": text,
            "voice": "alloy",
            "response_format": "mp3"
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        if response.status_code == 200:
            audio_data = response.content
            audio_b64 = base64.b64encode(audio_data).decode("utf-8")
            elapsed = (time.time() - start_time) * 1000
            return {
                "success": True,
                "audio_base64": audio_b64,
                "latency_ms": elapsed,
                "mode": "live"
            }
        else:
            elapsed = (time.time() - start_time) * 1000
            return {
                "success": False,
                "message": f"OpenAI TTS error: {response.text}",
                "latency_ms": elapsed,
                "mode": "live_failed"
            }
    except Exception as e:
        elapsed = (time.time() - start_time) * 1000
        return {
            "success": False,
            "message": f"TTS Exception: {str(e)}",
            "latency_ms": elapsed,
            "mode": "failed"
        }

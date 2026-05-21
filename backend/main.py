import time
import os
import json
import base64
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.config import settings
from backend.database import (
    init_db, get_all_doctors, get_all_patients, get_all_appointments,
    get_all_campaigns, get_patient_by_id
)
from backend.memory import session_manager, persistent_memory
from backend.agent.assistant import run_clinical_agent
from backend.services.stt import transcribe_audio
from backend.services.tts import synthesize_speech
from backend.scheduler.campaign_runner import trigger_outbound_campaign, complete_campaign

app = FastAPI(title="2Care.ai Clinical Voice AI Agent API")

# Setup CORS for Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize SQLite database on startup
@app.on_event("startup")
def startup_db():
    init_db()

# REST Endpoints
@app.get("/api/health")
def health():
    return {"status": "running", "api_mode": "live" if settings.OPENAI_API_KEY else "local_rules"}

@app.get("/api/doctors")
def get_doctors():
    return get_all_doctors()

@app.get("/api/patients")
def get_patients():
    return get_all_patients()

@app.get("/api/appointments")
def get_appointments():
    return get_all_appointments()

@app.get("/api/campaigns")
def get_campaigns():
    return get_all_campaigns()

@app.post("/api/campaigns/trigger/{campaign_id}")
def trigger_campaign(campaign_id: int):
    res = trigger_outbound_campaign(campaign_id)
    if not res["success"]:
        raise HTTPException(status_code=400, detail=res["message"])
    return res

@app.post("/api/campaigns/complete/{campaign_id}")
def finish_campaign(campaign_id: int, success: bool = True):
    complete_campaign(campaign_id, success)
    return {"success": True, "message": "Campaign completed."}

@app.get("/api/patients/{patient_id}/context")
def get_patient_context(patient_id: str):
    res = persistent_memory.load_patient_context(patient_id)
    if not res["patient_found"]:
        raise HTTPException(status_code=404, detail="Patient profile not found.")
    return res

@app.post("/api/reset-db")
def reset_database():
    """Wipes and recreates the SQLite database with pristine starting states."""
    if os.path.exists(settings.DATABASE_PATH):
        try:
            os.remove(settings.DATABASE_PATH)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Database file locked: {str(e)}")
    init_db()
    return {"success": True, "message": "Database reset and re-populated successfully."}

# Real-Time WebSocket Voice & Data Route
@app.websocket("/ws/voice")
async def websocket_voice_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    # Track current active session
    active_session_id = None
    
    try:
        while True:
            # Receive payload
            data = await websocket.receive_text()
            payload = json.loads(data)
            
            # Extract basic routing params
            event_type = payload.get("type") # "audio" | "text" | "init"
            session_id = payload.get("session_id", "sess_default")
            active_session_id = session_id
            
            # Setup active patient preference if passed
            patient_id = payload.get("patient_id")
            session = session_manager.get_session(session_id, default_patient_id=patient_id)
            
            if event_type == "init":
                # Warm up session context
                p_context = {}
                if session.patient_id:
                    p_context = persistent_memory.load_patient_context(session.patient_id)
                    session.current_language = p_context.get("preferred_language", "English")
                    
                await websocket.send_json({
                    "type": "init_success",
                    "session_id": session_id,
                    "language": session.current_language,
                    "patient_id": session.patient_id,
                    "initial_greeting": session.conversation_history[0]["content"] if session.conversation_history else ""
                })
                continue
                
            input_text = ""
            stt_latency = 0.0
            stt_mode = "bypassed"
            
            start_total = time.time()
            
            # 1. Speech-to-Text Stage
            if event_type == "audio":
                audio_b64 = payload.get("audio_data", "")
                if audio_b64:
                    audio_bytes = base64.b64decode(audio_b64)
                    
                    # Call Whispering service
                    stt_res = transcribe_audio(audio_bytes)
                    stt_latency = stt_res.get("latency_ms", 0.0)
                    stt_mode = stt_res.get("mode", "mocked")
                    
                    # If live STT transcribed, use it. Otherwise fall back to pre-transcribed text (from client Web Speech API)
                    if stt_res.get("success") and stt_res.get("text"):
                        input_text = stt_res["text"]
                        stt_mode = "live"
                    else:
                        input_text = payload.get("client_transcript", "")
                        stt_mode = "client_assisted"
                else:
                    input_text = payload.get("client_transcript", "")
                    stt_mode = "client_assisted"
            elif event_type == "text":
                input_text = payload.get("text", "")
                stt_mode = "bypassed"
                
            if not input_text:
                # Keep active listening loop alive
                await websocket.send_json({"type": "silent_frame"})
                continue
                
            # 2. Agentic Reasoning and Database Tools Stage
            start_agent = time.time()
            api_mode = payload.get("api_mode", "auto") # "live", "local_rules" or "auto"
            
            agent_res = run_clinical_agent(session_id, input_text, model_mode=api_mode)
            agent_latency = (time.time() - start_agent) * 1000
            
            reply_text = agent_res.get("reply_text", "")
            reasoning_traces = agent_res.get("reasoning_traces", [])
            slots = agent_res.get("slots", {})
            intent = agent_res.get("intent", "NONE")
            
            # 3. Text-to-Speech Stage
            start_tts = time.time()
            tts_res = synthesize_speech(reply_text)
            tts_latency = tts_res.get("latency_ms", 0.0)
            tts_mode = tts_res.get("mode", "mocked")
            audio_base64 = tts_res.get("audio_base64", "")
            
            total_latency = (time.time() - start_total) * 1000
            
            # Send result package back to user
            latency_payload = {
                "stt_ms": round(stt_latency, 2),
                "agent_ms": round(agent_latency, 2),
                "tts_ms": round(tts_latency, 2),
                "total_ms": round(total_latency, 2),
                "stt_mode": stt_mode,
                "tts_mode": tts_mode
            }
            await websocket.send_json({
                "type": "response",
                "input_transcript": input_text,
                "reply_text": reply_text,
                "audio_base64": audio_base64,
                "detected_language": session.current_language,
                "intent": intent,
                "slots": slots,
                "reasoning_traces": reasoning_traces,
                "latency": latency_payload
            })
            # Log latency to CSV for later analysis
            from backend.logger import log_latency
            log_latency(session_id, latency_payload)
            
    except WebSocketDisconnect:
        print(f"WebSocket session {active_session_id} disconnected.")
    except Exception as e:
        print(f"WebSocket critical error: {str(e)}")
    finally:
        # Cleanup session on socket terminate
        if active_session_id:
            session_manager.delete_session(active_session_id)

# Serve Frontend static directory
frontend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
else:
    print(f"Warning: Frontend static directory at {frontend_path} not found. REST APIs only.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=settings.HOST, port=settings.PORT, reload=True)

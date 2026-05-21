import time
import json
from typing import Dict, Any, Optional
from backend.config import settings
from backend.database import get_patient_by_id, get_patient_appointments, get_db_connection

class SessionMemory:
    """Represents a single active conversation session memory."""
    def __init__(self, session_id: str, patient_id: Optional[str] = None):
        self.session_id = session_id
        self.patient_id = patient_id
        self.current_intent = "NONE"  # BOOK, RESCHEDULE, CANCEL, CHECK_AVAILABILITY, NONE
        self.current_language = "English"  # English, Hindi, Tamil
        self.collected_slots = {
            "doctor_specialty": None,
            "doctor_id": None,
            "date": None,
            "time": None,
            "appointment_id": None
        }
        self.pending_confirmation = False
        self.last_interaction = time.time()
        self.conversation_history = []  # List of {"role": "user"|"assistant", "content": str}

    def update_interaction(self):
        self.last_interaction = time.time()

    def reset_slots(self):
        self.collected_slots = {
            "doctor_specialty": None,
            "doctor_id": None,
            "date": None,
            "time": None,
            "appointment_id": None
        }
        self.pending_confirmation = False

    def add_message(self, role: str, content: str):
        self.conversation_history.append({"role": role, "content": content})
        self.update_interaction()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "patient_id": self.patient_id,
            "current_intent": self.current_intent,
            "current_language": self.current_language,
            "collected_slots": self.collected_slots,
            "pending_confirmation": self.pending_confirmation,
            "last_interaction": self.last_interaction,
            "conversation_history": self.conversation_history
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SessionMemory":
        session = cls(d["session_id"], d["patient_id"])
        session.current_intent = d.get("current_intent", "NONE")
        session.current_language = d.get("current_language", "English")
        session.collected_slots = d.get("collected_slots", {
            "doctor_specialty": None,
            "doctor_id": None,
            "date": None,
            "time": None,
            "appointment_id": None
        })
        session.pending_confirmation = d.get("pending_confirmation", False)
        session.last_interaction = d.get("last_interaction", time.time())
        session.conversation_history = d.get("conversation_history", [])
        return session

class SessionMemoryManager:
    """Manages active conversation sessions with automatic TTL expiry."""
    def __init__(self, ttl: int = 600):
        self.sessions: Dict[str, SessionMemory] = {}
        self.ttl = ttl

    def get_session(self, session_id: str, default_patient_id: Optional[str] = None) -> SessionMemory:
        self.cleanup_expired()
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionMemory(session_id, default_patient_id)
        else:
            self.sessions[session_id].update_interaction()
            if default_patient_id and not self.sessions[session_id].patient_id:
                self.sessions[session_id].patient_id = default_patient_id
        return self.sessions[session_id]

    def update_session(self, session: SessionMemory):
        session.update_interaction()
        self.sessions[session.session_id] = session

    def delete_session(self, session_id: str):
        if session_id in self.sessions:
            del self.sessions[session_id]

    def cleanup_expired(self):
        now = time.time()
        expired = [sid for sid, sess in self.sessions.items() if now - sess.last_interaction > self.ttl]
        for sid in expired:
            del self.sessions[sid]

class PersistentMemoryManager:
    """Retrieves long-term patient records, preferences and formats it for prompts."""
    @staticmethod
    def load_patient_context(patient_id: str) -> Dict[str, Any]:
        patient = get_patient_by_id(patient_id)
        if not patient:
            return {
                "patient_found": False,
                "context_string": "No historical record found for this patient.",
                "preferred_language": "English",
                "name": "Valued Patient"
            }
        
        # Fetch their appointments
        appts = get_patient_appointments(patient_id)
        
        # Find active / scheduled appointments
        active_appts = [a for a in appts if a["status"] in ("Scheduled", "Rescheduled")]
        past_appts = [a for a in appts if a["status"] in ("Completed", "Cancelled")]
        
        # Build context narrative
        context_parts = []
        context_parts.append(f"Patient Name: {patient['name']}")
        context_parts.append(f"Phone Number: {patient['phone']}")
        context_parts.append(f"Preferred Language: {patient['preferred_language']}")
        if patient['past_medical_notes']:
            context_parts.append(f"Clinical/Medical Notes: {patient['past_medical_notes']}")
        
        if active_appts:
            context_parts.append("\nCurrently Scheduled Appointments:")
            for a in active_appts:
                context_parts.append(f"- ID: {a['id']} with {a['doctor_name']} ({a['doctor_specialty']}) on {a['date']} at {a['time']} [Status: {a['status']}]")
        else:
            context_parts.append("\nNo currently active scheduled appointments.")
            
        if past_appts:
            context_parts.append("\nPast Appointment Records:")
            for a in past_appts[:3]: # Limit to last 3 for prompt brevity
                context_parts.append(f"- with {a['doctor_name']} ({a['doctor_specialty']}) on {a['date']} at {a['time']} [Status: {a['status']}]")
                
        context_string = "\n".join(context_parts)
        
        # Update persistent language preference if stored in DB
        db_pref_lang = patient.get('preferred_language', 'English')
        
        return {
            "patient_found": True,
            "name": patient["name"],
            "phone": patient["phone"],
            "preferred_language": db_pref_lang,
            "active_appointments": active_appts,
            "context_string": context_string
        }
        
    @staticmethod
    def update_patient_language(patient_id: str, language: str):
        """Persists language change across sessions."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE patients SET preferred_language = ? WHERE id = ?", (language, patient_id))
        conn.commit()
        conn.close()

# Global session instance
session_manager = SessionMemoryManager(settings.SESSION_TTL)
persistent_memory = PersistentMemoryManager()

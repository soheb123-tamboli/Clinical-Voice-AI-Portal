import time
import json
import re
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple
import requests

from backend.config import settings
from backend.memory import session_manager, persistent_memory
from backend.database import get_all_doctors, get_doctor_by_specialty
from backend.agent import tools

SYSTEM_INSTRUCTION = """You are a highly competent, compassionate real-time multilingual clinical voice agent for digital healthcare platform 2Care.ai.
Your role is to manage appointments (book, cancel, reschedule, check doctor availability) in English, Hindi, and Tamil.

CRITICAL INSTRUCTIONS:
1. Always maintain awareness of the patient's context (e.g. past appointments, medical history, language choice).
2. When the patient speaks, identify their intent (BOOK, CANCEL, RESCHEDULE, CHECK_AVAILABILITY).
3. Call appropriate tools immediately to interact with the database.
4. Prevent double-bookings, booking past times, and invalid doctors. Suggest alternatives if slot is full.
5. If the language changes mid-conversation, adapt immediately.
6. Keep your spoken responses concise, comforting, and clear (voice-first optimization).
7. Return a JSON structure containing:
   - "reasoning_traces": List of your inner logical steps / thoughts.
   - "reply_text": The response to speak back to the user.
   - "slots": Current state of gathered parameters (doctor_specialty, date, time, appointment_id).
   - "intent": Current identified intent.
"""

def extract_slots_local(text: str, current_lang: str) -> Dict[str, Any]:
    """Uses advanced NLP heuristics to extract clinical slots (specialty, date, time, appt_id) locally."""
    slots = {"specialty": None, "date": None, "time": None, "appointment_id": None}
    
    text_lower = text.lower()
    
    # 1. Extract Specialty
    if any(k in text_lower for k in ("cardio", "heart", "harkat", "हृदय", "दिल", "இதய", "கார்டியோ")):
        slots["specialty"] = "Cardiologist"
    elif any(k in text_lower for k in ("derma", "skin", "eczema", "त्वचा", "चर्म", "தோல்", "டெர்மா")):
        slots["specialty"] = "Dermatologist"
    elif any(k in text_lower for k in ("general", "physician", "fever", "cough", "आम", "बुखार", "பொது", "ஜெனரல்")):
        slots["specialty"] = "General Physician"
        
    # 2. Extract Date
    today = datetime.now()
    if any(k in text_lower for k in ("tomorrow", "कल", "நாளை")):
        slots["date"] = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    elif any(k in text_lower for k in ("today", "आज", "இன்று")):
        slots["date"] = today.strftime("%Y-%m-%d")
    elif any(k in text_lower for k in ("day after", "परसों", "நாளை மறுநாள்")):
        slots["date"] = (today + timedelta(days=2)).strftime("%Y-%m-%d")
    else:
        # Regex search for YYYY-MM-DD or DD-MM-YYYY
        date_match = re.search(r"\b(\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{4})\b", text)
        if date_match:
            slots["date"] = tools.format_date_text(date_match.group(1))
            
    # 3. Extract Time (HH:MM formats e.g. 10:30, 9:00, 2 PM, 14:00)
    time_match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    if time_match:
        slots["time"] = f"{int(time_match.group(1)):02d}:{time_match.group(2)}"
    else:
        # Textual times (e.g. 10 am, 2 pm)
        pm_match = re.search(r"\b(\d+)\s*(pm|pm\b|இரவு|மதியம்|शाम|दोपहर)\b", text_lower)
        am_match = re.search(r"\b(\d+)\s*(am|am\b|காலை|सुबह)\b", text_lower)
        if pm_match:
            hour = int(pm_match.group(1))
            if hour < 12:
                hour += 12
            slots["time"] = f"{hour:02d}:00"
        elif am_match:
            hour = int(am_match.group(1))
            slots["time"] = f"{hour:02d}:00"
            
    # 4. Extract Appointment ID (e.g. APP-123456)
    appt_match = re.search(r"\bapp-\d{6}\b", text_lower)
    if appt_match:
        slots["appointment_id"] = appt_match.group(0).upper()
        
    return slots

def run_local_rules_agent(session_id: str, input_text: str) -> Dict[str, Any]:
    """Runs the ultra-low latency, zero-API rule agent that matches the exact clinical lifecycle."""
    traces = []
    traces.append(f"Received speech segment: \"{input_text}\"")
    
    session = session_manager.get_session(session_id)
    session.add_message("user", input_text)
    
    # 1. Detect language dynamically
    from backend.services.lang_detect import detect_language
    detected_lang = detect_language(input_text)
    if detected_lang != session.current_language:
        traces.append(f"Language switch detected: {session.current_language} -> {detected_lang}")
        session.current_language = detected_lang
        # Persist lang choice in DB if patient is loaded
        if session.patient_id:
            persistent_memory.update_patient_language(session.patient_id, detected_lang)
            
    traces.append(f"Active Session Language: {session.current_language}")
    
    # Load patient context
    p_context = {"name": "Patient", "preferred_language": "English"}
    if session.patient_id:
        p_context = persistent_memory.load_patient_context(session.patient_id)
        traces.append(f"Loaded Persistent Memory context for {p_context['name']}.")

    # Clean text for matching
    cleaned = input_text.lower()
    
    # 2. Determine Intent
    intent = session.current_intent
    
    # Intent triggers in multi-languages
    book_triggers = ("book", "schedule", "appointment", "see", "meet", "consult", "visit", "मिलना", "अपॉइंटमेंट", "बुक", "சந்திப்பு", "பதிவு", "புக்")
    cancel_triggers = ("cancel", "remove", "delete", "रद्द", "हटाएं", "நீக்கு", "ரத்து", "கேன்சல்")
    resch_triggers = ("reschedule", "change", "postpone", "move", "बदलो", "समय", "மாற்று", "ரீசெடியூல்")
    avail_triggers = ("check", "available", "free slots", "खाली", "இருக்கிறதா", "ஸ்லாட்")
    
    if any(t in cleaned for t in cancel_triggers):
        intent = "CANCEL"
    elif any(t in cleaned for t in resch_triggers):
        intent = "RESCHEDULE"
    elif any(t in cleaned for t in book_triggers):
        intent = "BOOK"
    elif any(t in cleaned for t in avail_triggers):
        intent = "CHECK_AVAILABILITY"
        
    session.current_intent = intent
    traces.append(f"Evaluated conversational intent: {intent}")
    
    # 3. Extract and Merge Slots
    extracted = extract_slots_local(input_text, session.current_language)
    for slot_k, slot_v in extracted.items():
        if slot_v:
            # Map specialty to proper DB format
            if slot_k == "specialty":
                session.collected_slots["doctor_specialty"] = slot_v
            else:
                session.collected_slots[slot_k] = slot_v
                
    traces.append(f"Current slots status: {json.dumps(session.collected_slots)}")
    
    # 4. Intent Execution & Flow Logic
    reply = ""
    
    # Multilingual translation dictionary
    responses = {
        "English": {
            "ask_specialty": "Which department would you like to see? We have Cardiologist, Dermatologist, or General Physician.",
            "ask_date": "Sure, for which date? You can say tomorrow, day after, or a specific date.",
            "ask_time": "What time works best for you? Standard slots are available between 9:00 AM and 5:00 PM.",
            "confirm_booking": "You would like to book Dr. {doc} on {date} at {time}. Shall I confirm this?",
            "confirm_reschedule": "You want to move your appointment {id} to {date} at {time}. Shall I confirm this?",
            "confirm_cancel": "Are you sure you want to cancel your appointment {id}?",
            "fallback": "I didn't quite catch that. Would you like to book, cancel, or reschedule an appointment?"
        },
        "Hindi": {
            "ask_specialty": "आप किस विभाग के डॉक्टर से मिलना चाहते हैं? हमारे पास कार्डियोलॉजिस्ट, डर्मेटोलॉजिस्ट और जनरल फिजिशियन उपलब्ध हैं।",
            "ask_date": "ठीक है, किस तारीख के लिए? आप कल, परसों या कोई विशेष तारीख कह सकते हैं।",
            "ask_time": "आपके लिए कौन सा समय सही रहेगा? सुबह 9:00 से शाम 5:00 बजे तक स्लॉट उपलब्ध हैं।",
            "confirm_booking": "आप डॉ. {doc} के साथ {date} को {time} बजे अपॉइंटमेंट बुक करना चाहते हैं। क्या मैं इसकी पुष्टि करूँ?",
            "confirm_reschedule": "आप अपना अपॉइंटमेंट {id} को {date} को {time} बजे रीशेड्यूल करना चाहते हैं। क्या मैं इसकी पुष्टि करूँ?",
            "confirm_cancel": "क्या आप निश्चित रूप से अपना अपॉइंटमेंट {id} रद्द करना चाहते हैं?",
            "fallback": "क्षमा करें, मैं समझ नहीं पाया। क्या आप अपॉइंटमेंट बुक, रद्द या रीशेड्यूल करना चाहते हैं?"
        },
        "Tamil": {
            "ask_specialty": "நீங்கள் எந்த மருத்துவரை பார்க்க வேண்டும்? எங்களிடம் இதய நிபுணர், தோல் மருத்துவர் மற்றும் பொது மருத்துவர் உள்ளனர்.",
            "ask_date": "நிச்சயமாக, எந்த தேதிக்கு? நாளை, நாளை மறுநாள் அல்லது ஒரு குறிப்பிட்ட தேதியைக் கூறலாம்.",
            "ask_time": "உங்களுக்கு எந்த நேரம் வசதியாக இருக்கும்? காலை 9:00 மணி முதல் மாலை 5:00 மணி வரை ஸ்லாட்டுகள் உள்ளன.",
            "confirm_booking": "நீங்கள் டாக்டர் {doc} உடன் {date} அன்று {time} மணிக்கு அப்பாயிண்ட்மெண்ட் புக் செய்ய விரும்புகிறீர்கள். நான் இதை உறுதிப்படுத்தலாமா?",
            "confirm_reschedule": "உங்கள் அப்பாயிண்ட்மெண்ட் {id}-ஐ {date} அன்று {time} மணிக்கு மாற்ற விரும்புகிறீர்கள். நான் இதை உறுதிப்படுத்தலாமா?",
            "confirm_cancel": "உங்கள் அப்பாயிண்ட்மெண்ட் {id}-ஐ ரத்து செய்ய விரும்புகிறீர்களா?",
            "fallback": "மன்னிக்கவும், எனக்கு புரியவில்லை. நீங்கள் அப்பாயிண்ட்மெண்ட் புக் செய்ய, ரத்து செய்ய அல்லது ஒத்திவைக்க விரும்புகிறீர்களா?"
        }
    }
    
    lang = session.current_language
    
    # Handle direct confirmations (Yes / No)
    yes_words = ("yes", "confirm", "sure", "ok", "harkat", "haan", "sahi", "haanji", "कर दो", "हां", "ஆம்", "உறுதி", "சரி")
    no_words = ("no", "cancel", "stop", "reject", "na", "nahi", "illai", "வேண்டாம்", "नहीं")
    
    if session.pending_confirmation:
        if any(w in cleaned for w in yes_words):
            traces.append("User confirmed the pending transaction.")
            session.pending_confirmation = False
            
            if intent == "BOOK":
                # Call book appointment
                spec = session.collected_slots["doctor_specialty"] or "General Physician"
                doc = get_doctor_by_specialty(spec)
                date_str = session.collected_slots["date"]
                time_str = session.collected_slots["time"]
                
                traces.append(f"[Tool Call] book_appointment(patient_id='{session.patient_id}', doctor_id={doc['id']}, date='{date_str}', time='{time_str}')")
                res = tools.book_appointment(session.patient_id or "PAT-1001", doc["id"], date_str, time_str)
                reply = res["message"]
                
                # Hindi/Tamil Translation Fallbacks for confirmations
                if lang == "Hindi":
                    if res["success"]:
                        reply = f"सफलतापूर्वक बुक हो गया! डॉ. {doc['name']} के साथ आपका स्लॉट {res['readable_date']} को {time_str} बजे निश्चित है। संदर्भ संख्या {res['appointment_id']} है।"
                    else:
                        reply = f"अपॉइंटमेंट बुक नहीं हो सका: {res['message']}"
                elif lang == "Tamil":
                    if res["success"]:
                        reply = f"வெற்றிகரமாக பதிவு செய்யப்பட்டது! டாக்டர் {doc['name']} உடன் உங்கள் சந்திப்பு {res['readable_date']} அன்று {time_str} மணிக்கு உறுதி செய்யப்பட்டுள்ளது. குறிப்பு எண் {res['appointment_id']}."
                    else:
                        reply = f"பதிவு தோல்வியடைந்தது: {res['message']}"
                
                session.reset_slots()
                session.current_intent = "NONE"
                
            elif intent == "RESCHEDULE":
                appt_id = session.collected_slots["appointment_id"]
                date_str = session.collected_slots["date"]
                time_str = session.collected_slots["time"]
                
                traces.append(f"[Tool Call] reschedule_appointment(appointment_id='{appt_id}', new_date='{date_str}', new_time='{time_str}')")
                res = tools.reschedule_appointment(appt_id, date_str, time_str)
                reply = res["message"]
                
                if lang == "Hindi":
                    if res["success"]:
                        reply = f"सफलतापूर्वक रीशेड्यूल हो गया! डॉ. {res['doctor_name']} के साथ आपका अपॉइंटमेंट {res['readable_date']} को {time_str} बजे कर दिया गया है।"
                    else:
                        reply = f"रीशेड्यूल विफल हुआ: {res['message']}"
                elif lang == "Tamil":
                    if res["success"]:
                        reply = f"வெற்றிகரமாக ஒத்திவைக்கப்பட்டது! டாக்டர் {res['doctor_name']} உடனான சந்திப்பு {res['readable_date']} அன்று {time_str} மணிக்கு மாற்றப்பட்டுள்ளது."
                    else:
                        reply = f"மாற்றம் தோல்வியடைந்தது: {res['message']}"
                        
                session.reset_slots()
                session.current_intent = "NONE"
                
            elif intent == "CANCEL":
                appt_id = session.collected_slots["appointment_id"]
                traces.append(f"[Tool Call] cancel_appointment(appointment_id='{appt_id}')")
                res = tools.cancel_appointment(appt_id)
                reply = res["message"]
                
                if lang == "Hindi":
                    if res["success"]:
                        reply = f"आपका अपॉइंटमेंट {appt_id} सफलतापूर्वक रद्द कर दिया गया है।"
                elif lang == "Tamil":
                    if res["success"]:
                        reply = f"உங்கள் அப்பாயிண்ட்மெண்ட் {appt_id} வெற்றிகரமாக ரத்து செய்யப்பட்டது."
                        
                session.reset_slots()
                session.current_intent = "NONE"
                
        elif any(w in cleaned for w in no_words):
            traces.append("User rejected the confirmation prompt.")
            session.pending_confirmation = False
            session.reset_slots()
            session.current_intent = "NONE"
            
            if lang == "Hindi":
                reply = "कोई बात नहीं। क्या मैं आपकी किसी अन्य काम में मदद कर सकता हूँ?"
            elif lang == "Tamil":
                reply = "பரவாயில்லை. நான் உங்களுக்கு வேறு ஏதேனும் உதவி செய்ய வேண்டுமா?"
            else:
                reply = "No problem, transaction cancelled. How else can I assist you today?"
        else:
            # Repeat confirmation prompt
            session.pending_confirmation = True
            reply = "I'm sorry, I need a clear confirmation. "
            if intent == "BOOK":
                spec = session.collected_slots["doctor_specialty"] or "General Physician"
                doc = get_doctor_by_specialty(spec)
                reply += responses[lang]["confirm_booking"].format(doc=doc["name"], date=session.collected_slots["date"], time=session.collected_slots["time"])
            elif intent == "RESCHEDULE":
                reply += responses[lang]["confirm_reschedule"].format(id=session.collected_slots["appointment_id"], date=session.collected_slots["date"], time=session.collected_slots["time"])
            elif intent == "CANCEL":
                reply += responses[lang]["confirm_cancel"].format(id=session.collected_slots["appointment_id"])
                
        session.add_message("assistant", reply)
        session_manager.update_session(session)
        return {
            "reasoning_traces": traces,
            "reply_text": reply,
            "slots": session.collected_slots,
            "intent": session.current_intent
        }

    # standard non-confirm path
    if intent == "BOOK":
        if not session.collected_slots["doctor_specialty"]:
            # If a patient has a preferred doctor, default to their specialty instead of asking!
            if session.patient_id and p_context.get("patient_found"):
                appts = p_context.get("active_appointments", [])
                if appts:
                    session.collected_slots["doctor_specialty"] = appts[0]["doctor_specialty"]
                    traces.append(f"Auto-selected preferred specialty from past appointments: {appts[0]['doctor_specialty']}")
            
            if not session.collected_slots["doctor_specialty"]:
                reply = responses[lang]["ask_specialty"]
                session.add_message("assistant", reply)
                session_manager.update_session(session)
                return {
                    "reasoning_traces": traces,
                    "reply_text": reply,
                    "slots": session.collected_slots,
                    "intent": intent
                }
                
        if not session.collected_slots["date"]:
            reply = responses[lang]["ask_date"]
            session.add_message("assistant", reply)
            session_manager.update_session(session)
            return {
                "reasoning_traces": traces,
                "reply_text": reply,
                "slots": session.collected_slots,
                "intent": intent
            }
            
        if not session.collected_slots["time"]:
            # Check availability first to suggest times
            spec = session.collected_slots["doctor_specialty"]
            date_val = session.collected_slots["date"]
            traces.append(f"[Tool Call] check_availability(doctor_specialty='{spec}', date='{date_val}')")
            avail = tools.check_availability(spec, date_val)
            
            if avail["success"] and avail["slots"]:
                # Custom suggest in Hindi/Tamil
                if lang == "Hindi":
                    reply = f"डॉ. {avail['doctor_name']} {avail['readable_date']} को उपलब्ध हैं। खाली समय हैं: {', '.join(avail['slots'][:3])}। आपके लिए कौन सा समय सही रहेगा?"
                elif lang == "Tamil":
                    reply = f"டாக்டர் {avail['doctor_name']} {avail['readable_date']} அன்று உள்ளார். காலியாக உள்ள நேரங்கள்: {', '.join(avail['slots'][:3])}. உங்களுக்கு எந்த நேரம் வேண்டும்?"
                else:
                    reply = f"Dr. {avail['doctor_name']} is free on {avail['readable_date']}. Slots available are: {', '.join(avail['slots'][:3])}. Which one do you prefer?"
            else:
                reply = avail["message"]
                
            session.add_message("assistant", reply)
            session_manager.update_session(session)
            return {
                "reasoning_traces": traces,
                "reply_text": reply,
                "slots": session.collected_slots,
                "intent": intent
            }
            
        # We have all slots, request confirmation
        spec = session.collected_slots["doctor_specialty"]
        doc = get_doctor_by_specialty(spec)
        session.collected_slots["doctor_id"] = doc["id"]
        
        session.pending_confirmation = True
        reply = responses[lang]["confirm_booking"].format(doc=doc["name"], date=session.collected_slots["date"], time=session.collected_slots["time"])
        
    elif intent == "RESCHEDULE":
        # Check if they gave appointment_id, if not fetch from patient context active appointments!
        if not session.collected_slots["appointment_id"]:
            if session.patient_id and p_context.get("patient_found"):
                active = p_context.get("active_appointments", [])
                if active:
                    session.collected_slots["appointment_id"] = active[0]["id"]
                    traces.append(f"Auto-extracted active appointment ID from persistent memory: {active[0]['id']}")
                else:
                    if lang == "Hindi":
                        reply = "मुझे आपका कोई सक्रिय अपॉइंटमेंट नहीं मिला। क्या आप मुझे अपनी अपॉइंटमेंट आईडी बता सकते हैं?"
                    elif lang == "Tamil":
                        reply = "உங்களுடைய தற்போதைய சந்திப்புகள் எதுவும் இல்லை. உங்கள் அப்பாயிண்ட்மெண்ட் ஐடி-யை கூற முடியுமா?"
                    else:
                        reply = "I couldn't locate an active appointment in your file. Could you please specify your Appointment ID?"
                    session.add_message("assistant", reply)
                    session_manager.update_session(session)
                    return {
                        "reasoning_traces": traces,
                        "reply_text": reply,
                        "slots": session.collected_slots,
                        "intent": intent
                    }
            else:
                if lang == "Hindi":
                    reply = "अपॉइंटमेंट बदलने के लिए कृपया मुझे अपनी 6 अंकों की अपॉइंटमेंट आईडी बताएं।"
                elif lang == "Tamil":
                    reply = "மாற்றுவதற்கு உங்கள் 6 இலக்க அப்பாயிண்ட்மெண்ட் ஐடி-யை கூறவும்."
                else:
                    reply = "To reschedule, please provide your 6-digit Appointment ID (e.g. APP-123456)."
                session.add_message("assistant", reply)
                session_manager.update_session(session)
                return {
                    "reasoning_traces": traces,
                    "reply_text": reply,
                    "slots": session.collected_slots,
                    "intent": intent
                }
                
        if not session.collected_slots["date"]:
            reply = responses[lang]["ask_date"]
            session.add_message("assistant", reply)
            session_manager.update_session(session)
            return {
                "reasoning_traces": traces,
                "reply_text": reply,
                "slots": session.collected_slots,
                "intent": intent
            }
            
        if not session.collected_slots["time"]:
            reply = responses[lang]["ask_time"]
            session.add_message("assistant", reply)
            session_manager.update_session(session)
            return {
                "reasoning_traces": traces,
                "reply_text": reply,
                "slots": session.collected_slots,
                "intent": intent
            }
            
        # Request Reschedule Confirmation
        session.pending_confirmation = True
        reply = responses[lang]["confirm_reschedule"].format(id=session.collected_slots["appointment_id"], date=session.collected_slots["date"], time=session.collected_slots["time"])
        
    elif intent == "CANCEL":
        if not session.collected_slots["appointment_id"]:
            if session.patient_id and p_context.get("patient_found"):
                active = p_context.get("active_appointments", [])
                if active:
                    session.collected_slots["appointment_id"] = active[0]["id"]
                    traces.append(f"Auto-selected appointment ID for cancellation from patient file: {active[0]['id']}")
                else:
                    if lang == "Hindi":
                        reply = "रद्द करने के लिए मुझे आपका कोई सक्रिय अपॉइंटमेंट नहीं मिला।"
                    elif lang == "Tamil":
                        reply = "ரத்து செய்ய உங்களுடைய தற்போதைய சந்திப்புகள் எதுவும் இல்லை."
                    else:
                        reply = "I don't see any active appointment scheduled for you."
                    session.add_message("assistant", reply)
                    session_manager.update_session(session)
                    return {
                        "reasoning_traces": traces,
                        "reply_text": reply,
                        "slots": session.collected_slots,
                        "intent": "NONE"
                    }
            else:
                if lang == "Hindi":
                    reply = "अपॉइंटमेंट रद्द करने के लिए कृपया अपनी अपॉइंटमेंट आईडी बताएं।"
                elif lang == "Tamil":
                    reply = "அப்பாயிண்ட்மெண்ட்டை ரத்து செய்ய ஐடி-யை கூறவும்."
                else:
                    reply = "Please share the Appointment ID you wish to cancel."
                session.add_message("assistant", reply)
                session_manager.update_session(session)
                return {
                    "reasoning_traces": traces,
                    "reply_text": reply,
                    "slots": session.collected_slots,
                    "intent": intent
                }
                
        session.pending_confirmation = True
        reply = responses[lang]["confirm_cancel"].format(id=session.collected_slots["appointment_id"])
        
    elif intent == "CHECK_AVAILABILITY":
        spec = session.collected_slots["doctor_specialty"] or "General Physician"
        date_val = session.collected_slots["date"] or (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        traces.append(f"[Tool Call] check_availability(specialty='{spec}', date='{date_val}')")
        res = tools.check_availability(spec, date_val)
        reply = res["message"]
        
        # Format language specifics
        if lang == "Hindi":
            if res["success"] and res["slots"]:
                reply = f"डॉ. {res['doctor_name']} {res['readable_date']} को उपलब्ध हैं। समय स्लॉट हैं: {', '.join(res['slots'])}।"
        elif lang == "Tamil":
            if res["success"] and res["slots"]:
                reply = f"டாக்டர் {res['doctor_name']} {res['readable_date']} அன்று உள்ளார். ஸ்லாட்டுகள்: {', '.join(res['slots'])}."
                
        session.current_intent = "NONE"
        session.reset_slots()
        
    else:
        reply = responses[lang]["fallback"]
        
    session.add_message("assistant", reply)
    session_manager.update_session(session)
    
    return {
        "reasoning_traces": traces,
        "reply_text": reply,
        "slots": session.collected_slots,
        "intent": session.current_intent
    }

def run_openai_agent(session_id: str, input_text: str) -> Dict[str, Any]:
    """Invokes OpenAI Chat Completion with Function Calling for fully-reasoned agent actions."""
    # Ensure dependencies and fallback
    if not settings.OPENAI_API_KEY:
        return run_local_rules_agent(session_id, input_text)
        
    session = session_manager.get_session(session_id)
    session.add_message("user", input_text)
    
    from backend.services.lang_detect import detect_language
    detected_lang = detect_language(input_text)
    if detected_lang != session.current_language:
        session.current_language = detected_lang
        if session.patient_id:
            persistent_memory.update_patient_language(session.patient_id, detected_lang)
            
    p_context = {"context_string": "No details."}
    if session.patient_id:
        p_context = persistent_memory.load_patient_context(session.patient_id)
        
    traces = [f"Language: {session.current_language}", f"Loading patient file context: {p_context.get('name', 'N/A')}"]
    
    # Formulate API Call
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Construct conversation history
    messages = [{"role": "system", "content": f"{SYSTEM_INSTRUCTION}\n\nPATIENT PERSISTENT MEMORY CONTEXT:\n{p_context['context_string']}\n\nCURRENT LANGUAGE PREFERENCE: {session.current_language}\nCURRENT TODAY DATE: {datetime.now().strftime('%Y-%m-%d %A')}"}]
    
    # Fetch last 8 messages for history context
    for msg in session.conversation_history[-8:]:
        messages.append(msg)
        
    # Expose tools definition
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": "check_availability",
                "description": "Check doctor schedules for a specific specialty ('Cardiologist', 'Dermatologist', 'General Physician') and date ('tomorrow', 'today' or standard YYYY-MM-DD)",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "doctor_specialty_or_id": {"type": "STRING", "description": "Clinician specialty name or unique doctor integer ID"},
                        "date_raw": {"type": "STRING", "description": "Date requested (e.g. tomorrow, 2026-05-22)"}
                    },
                    "required": ["doctor_specialty_or_id", "date_raw"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "book_appointment",
                "description": "Book a new clinical slot with a doctor. Check availability first to avoid conflict.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "patient_id": {"type": "STRING", "description": "Unique Patient ID"},
                        "doctor_id": {"type": "INTEGER", "description": "Doctor numeric ID"},
                        "date_raw": {"type": "STRING", "description": "Target slot date"},
                        "time_str": {"type": "STRING", "description": "Target 24-hr slot time, e.g. 10:30"}
                    },
                    "required": ["patient_id", "doctor_id", "date_raw", "time_str"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "reschedule_appointment",
                "description": "Reschedule an existing active appointment to a new date and time.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "appointment_id": {"type": "STRING", "description": "Standard 9-digit Appt Reference, e.g. APP-9001"},
                        "new_date_raw": {"type": "STRING", "description": "New target slot date"},
                        "new_time_str": {"type": "STRING", "description": "New 24-hr time slot"}
                    },
                    "required": ["appointment_id", "new_date_raw", "new_time_str"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "cancel_appointment",
                "description": "Cancel an active clinical appointment slot.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "appointment_id": {"type": "STRING", "description": "Appointment ID reference"}
                    },
                    "required": ["appointment_id"]
                }
            }
        }
    ]
    
    try:
        payload = {
            "model": "gpt-4o",
            "messages": messages,
            "tools": openai_tools,
            "tool_choice": "auto",
            "response_format": {"type": "json_object"}
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=12)
        if response.status_code != 200:
            traces.append(f"OpenAI Call Failed with status {response.status_code}. Falling back to local NLP rules.")
            return run_local_rules_agent(session_id, input_text)
            
        choice = response.json()["choices"][0]["message"]
        
        # Process Tool Call
        if choice.get("tool_calls"):
            tool_call = choice["tool_calls"][0]
            func_name = tool_call["function"]["name"]
            func_args = json.loads(tool_call["function"]["arguments"])
            
            traces.append(f"Agentic Tool Decision: {func_name} with arguments {json.dumps(func_args)}")
            
            tool_res = None
            if func_name == "check_availability":
                tool_res = tools.check_availability(func_args["doctor_specialty_or_id"], func_args["date_raw"])
            elif func_name == "book_appointment":
                # Supply patient id if missing from call
                pid = func_args.get("patient_id") or session.patient_id or "PAT-1001"
                tool_res = tools.book_appointment(pid, int(func_args["doctor_id"]), func_args["date_raw"], func_args["time_str"])
            elif func_name == "reschedule_appointment":
                tool_res = tools.reschedule_appointment(func_args["appointment_id"], func_args["new_date_raw"], func_args["new_time_str"])
            elif func_name == "cancel_appointment":
                tool_res = tools.cancel_appointment(func_args["appointment_id"])
                
            traces.append(f"Tool Result: {json.dumps(tool_res)}")
            
            # Send tool output back to agent to formulate final localized response
            messages.append(choice)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "name": func_name,
                "content": json.dumps(tool_res)
            })
            
            # Request final evaluation response from LLM
            final_res = requests.post(url, headers=headers, json={
                "model": "gpt-4o",
                "messages": messages,
                "response_format": {"type": "json_object"}
            }, timeout=10)
            
            if final_res.status_code == 200:
                final_choice = final_res.json()["choices"][0]["message"]["content"]
                parsed = json.loads(final_choice)
                
                # Merge responses
                reply = parsed.get("reply_text", "")
                session.add_message("assistant", reply)
                session_manager.update_session(session)
                
                return {
                    "reasoning_traces": traces + parsed.get("reasoning_traces", []),
                    "reply_text": reply,
                    "slots": parsed.get("slots", session.collected_slots),
                    "intent": parsed.get("intent", session.current_intent)
                }
                
        # Non-tool plain agent text response
        content = choice.get("content", "{}")
        parsed = json.loads(content)
        reply = parsed.get("reply_text", "Sorry, let me verify that.")
        session.add_message("assistant", reply)
        session_manager.update_session(session)
        
        return {
            "reasoning_traces": traces + parsed.get("reasoning_traces", []),
            "reply_text": reply,
            "slots": parsed.get("slots", session.collected_slots),
            "intent": parsed.get("intent", session.current_intent)
        }
    except Exception as e:
        traces.append(f"LLM Agent execution exception: {str(e)}. Triggering local NLP fallback.")
        return run_local_rules_agent(session_id, input_text)

def run_clinical_agent(session_id: str, input_text: str, model_mode: str = "auto") -> Dict[str, Any]:
    """Unified routing entry for the clinical agent logic."""
    if model_mode == "live" or (model_mode == "auto" and settings.OPENAI_API_KEY):
        return run_openai_agent(session_id, input_text)
    else:
        return run_local_rules_agent(session_id, input_text)

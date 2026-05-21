import sqlite3
import json
import random
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple
from backend.database import get_db_connection, get_doctor_by_id, get_doctor_by_specialty

# Standard clinical office hours: 09:00 AM to 05:00 PM, 30 min intervals
CLINICAL_SLOTS = [
    "09:00", "09:30", "10:00", "10:30", "11:00", "11:30",
    "12:00", "12:30", "14:00", "14:30", "15:00", "15:30",
    "16:00", "16:30"
]

def format_date_text(date_str: str) -> str:
    """Formats raw date strings into standard YYYY-MM-DD or readable strings."""
    today = datetime.now()
    if date_str.lower() in ("tomorrow", "कल", "நாளை"):
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    elif date_str.lower() in ("today", "आज", "இன்று"):
        return today.strftime("%Y-%m-%d")
    elif date_str.lower() in ("day after", "परसों", "நாளை மறுநாள்"):
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")
    
    # Clean standard date parsing
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            parsed = datetime.strptime(date_str, fmt)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
            
    return date_str  # Return original if unable to parse

def get_or_create_schedule(cursor, doctor_id: int, date_str: str) -> List[str]:
    """Helper to fetch booked slots for a doctor and date, creating the row if needed."""
    cursor.execute("SELECT booked_slots FROM doctor_schedule WHERE doctor_id = ? AND date = ?", (doctor_id, date_str))
    row = cursor.fetchone()
    if row:
        return json.loads(row[0])
    
    # Create schedule if missing
    booked = []
    cursor.execute("INSERT INTO doctor_schedule (doctor_id, date, booked_slots) VALUES (?, ?, ?)", 
                   (doctor_id, date_str, json.dumps(booked)))
    return booked

def save_schedule(cursor, doctor_id: int, date_str: str, booked_slots: List[str]):
    cursor.execute("UPDATE doctor_schedule SET booked_slots = ? WHERE doctor_id = ? AND date = ?", 
                   (json.dumps(booked_slots), doctor_id, date_str))

def check_availability(doctor_specialty_or_id: Any, date_raw: str) -> Dict[str, Any]:
    """Checks doctor schedule availability and returns a list of free slot times."""
    date_str = format_date_text(date_raw)
    
    # Parse input parameter to find doctor
    doctor = None
    if str(doctor_specialty_or_id).isdigit():
        doctor = get_doctor_by_id(int(doctor_specialty_or_id))
    else:
        doctor = get_doctor_by_specialty(str(doctor_specialty_or_id))
        
    if not doctor:
        return {
            "success": False,
            "message": f"Doctor specialty or identifier '{doctor_specialty_or_id}' was not found.",
            "slots": []
        }
    
    doctor_id = doctor["id"]
    doctor_name = doctor["name"]
    specialty = doctor["specialty"]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Validate target date is not in past
        target_dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        today_dt = datetime.now().date()
        if target_dt < today_dt:
            return {
                "success": False,
                "message": f"Cannot schedule slots for a past date: {date_str}.",
                "slots": []
            }
            
        booked_slots = get_or_create_schedule(cursor, doctor_id, date_str)
        conn.commit()
        
        # Filter available slots
        available = []
        now = datetime.now()
        for slot in CLINICAL_SLOTS:
            if slot not in booked_slots:
                # If booking for today, make sure slot is not in the past
                if target_dt == today_dt:
                    slot_hour, slot_min = map(int, slot.split(":"))
                    slot_dt = now.replace(hour=slot_hour, minute=slot_min, second=0, microsecond=0)
                    if slot_dt < now:
                        continue
                available.append(slot)
                
        readable_date = target_dt.strftime("%A, %b %d, %Y")
        if not available:
            # Suggest next day as alternative
            alternative_date = (target_dt + timedelta(days=1)).strftime("%Y-%m-%d")
            return {
                "success": True,
                "message": f"Dr. {doctor_name} is fully booked on {readable_date}. Would you prefer the next day, {alternative_date}?",
                "slots": [],
                "alternative_date": alternative_date
            }
            
        return {
            "success": True,
            "doctor_id": doctor_id,
            "doctor_name": doctor_name,
            "specialty": specialty,
            "date": date_str,
            "readable_date": readable_date,
            "slots": available,
            "message": f"Available slots for Dr. {doctor_name} on {readable_date} are: {', '.join(available)}."
        }
    except Exception as e:
        return {"success": False, "message": f"System error checking availability: {str(e)}", "slots": []}
    finally:
        conn.close()

def book_appointment(patient_id: str, doctor_id: int, date_raw: str, time_str: str) -> Dict[str, Any]:
    """Books a clinical appointment, verifying constraints, past limits, and avoiding duplicates."""
    date_str = format_date_text(date_raw)
    doctor = get_doctor_by_id(doctor_id)
    if not doctor:
        return {"success": False, "message": f"Doctor ID {doctor_id} not found."}
        
    doctor_name = doctor["name"]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check date not in past
        target_dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        today_dt = datetime.now().date()
        if target_dt < today_dt:
            return {"success": False, "message": "Cannot book appointments in past dates."}
            
        # Verify valid slot format
        if time_str not in CLINICAL_SLOTS:
            return {"success": False, "message": f"Invalid slot time '{time_str}'. Doctor hours are between 09:00 AM and 05:00 PM."}
            
        # If booking for today, check past time
        if target_dt == today_dt:
            now = datetime.now()
            slot_hour, slot_min = map(int, time_str.split(":"))
            slot_dt = now.replace(hour=slot_hour, minute=slot_min, second=0, microsecond=0)
            if slot_dt < now:
                return {"success": False, "message": f"Slot time '{time_str}' has already passed today."}

        booked_slots = get_or_create_schedule(cursor, doctor_id, date_str)
        
        # Check conflict
        if time_str in booked_slots:
            # Recommend alternatives
            free_slots = [s for s in CLINICAL_SLOTS if s not in booked_slots]
            alt_msg = f"Slot {time_str} is already booked. "
            if free_slots:
                alt_msg += f"Available slots for Dr. {doctor_name} on this date are: {', '.join(free_slots[:3])}."
            else:
                alt_msg += "Dr. Sharma is fully booked tomorrow. We can try day after tomorrow."
            return {
                "success": False,
                "conflict": True,
                "message": alt_msg,
                "alternative_slots": free_slots[:3]
            }
            
        # Check patient double booking (same date & time)
        cursor.execute("SELECT id FROM appointments WHERE patient_id = ? AND date = ? AND time = ? AND status != 'Cancelled'", 
                       (patient_id, date_str, time_str))
        if cursor.fetchone():
            return {"success": False, "message": "You already have another appointment scheduled at this exact date and time."}
            
        # Book the slot
        booked_slots.append(time_str)
        save_schedule(cursor, doctor_id, date_str, booked_slots)
        
        appt_id = f"APP-{random.randint(100000, 999999)}"
        cursor.execute(
            "INSERT INTO appointments (id, patient_id, doctor_id, date, time, status) VALUES (?, ?, ?, ?, ?, ?)",
            (appt_id, patient_id, doctor_id, date_str, time_str, "Scheduled")
        )
        
        conn.commit()
        readable_date = target_dt.strftime("%A, %b %d, %Y")
        return {
            "success": True,
            "appointment_id": appt_id,
            "doctor_name": doctor_name,
            "specialty": doctor["specialty"],
            "date": date_str,
            "time": time_str,
            "readable_date": readable_date,
            "message": f"Success! Your appointment with Dr. {doctor_name} is booked for {readable_date} at {time_str}. Appointment Reference ID is {appt_id}."
        }
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": f"Booking failure: {str(e)}"}
    finally:
        conn.close()

def reschedule_appointment(appointment_id: str, new_date_raw: str, new_time_str: str) -> Dict[str, Any]:
    """Reschedules an existing appointment, freeing the prior slot and booking the new one."""
    new_date_str = format_date_text(new_date_raw)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check existing appointment
        cursor.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,))
        appt = cursor.fetchone()
        if not appt:
            return {"success": False, "message": f"Appointment ID '{appointment_id}' could not be located."}
            
        if appt["status"] == "Cancelled":
            return {"success": False, "message": "Cannot reschedule a previously cancelled appointment. Please book a new one."}
            
        doctor_id = appt["doctor_id"]
        old_date = appt["date"]
        old_time = appt["time"]
        patient_id = appt["patient_id"]
        
        doctor = get_doctor_by_id(doctor_id)
        doctor_name = doctor["name"] if doctor else "Doctor"
        
        # Verify target slot
        if new_time_str not in CLINICAL_SLOTS:
            return {"success": False, "message": f"Invalid slot time '{new_time_str}'. Clinical hours are 09:00 AM - 05:00 PM."}
            
        target_dt = datetime.strptime(new_date_str, "%Y-%m-%d").date()
        today_dt = datetime.now().date()
        if target_dt < today_dt:
            return {"success": False, "message": "Cannot reschedule appointment to a past date."}
            
        if target_dt == today_dt:
            now = datetime.now()
            slot_hour, slot_min = map(int, new_time_str.split(":"))
            slot_dt = now.replace(hour=slot_hour, minute=slot_min, second=0, microsecond=0)
            if slot_dt < now:
                return {"success": False, "message": "Proposed reschedule slot time has already passed today."}

        # Check availability of new slot
        new_booked = get_or_create_schedule(cursor, doctor_id, new_date_str)
        if new_time_str in new_booked:
            # Slot conflict
            free_slots = [s for s in CLINICAL_SLOTS if s not in new_booked]
            return {
                "success": False,
                "conflict": True,
                "message": f"Slot {new_time_str} is unavailable on {new_date_str}. Other available times are: {', '.join(free_slots[:3])}.",
                "alternative_slots": free_slots[:3]
            }
            
        # Free old slot
        old_booked = get_or_create_schedule(cursor, doctor_id, old_date)
        if old_time in old_booked:
            old_booked.remove(old_time)
            save_schedule(cursor, doctor_id, old_date, old_booked)
            
        # Book new slot
        if old_date == new_date_str:
            new_booked = old_booked
        else:
            new_booked = get_or_create_schedule(cursor, doctor_id, new_date_str)
        new_booked.append(new_time_str)
        save_schedule(cursor, doctor_id, new_date_str, new_booked)
        
        # Update Appointment status
        cursor.execute(
            "UPDATE appointments SET date = ?, time = ?, status = 'Rescheduled' WHERE id = ?",
            (new_date_str, new_time_str, appointment_id)
        )
        
        conn.commit()
        readable_date = target_dt.strftime("%A, %b %d, %Y")
        return {
            "success": True,
            "appointment_id": appointment_id,
            "doctor_name": doctor_name,
            "date": new_date_str,
            "time": new_time_str,
            "readable_date": readable_date,
            "message": f"Successfully rescheduled! Your appointment with Dr. {doctor_name} has been moved to {readable_date} at {new_time_str}. Ref: {appointment_id}."
        }
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": f"Rescheduling failed: {str(e)}"}
    finally:
        conn.close()

def cancel_appointment(appointment_id: str) -> Dict[str, Any]:
    """Cancels a clinical appointment, freeing up the schedule slot."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,))
        appt = cursor.fetchone()
        if not appt:
            return {"success": False, "message": f"Appointment ID '{appointment_id}' could not be located."}
            
        if appt["status"] == "Cancelled":
            return {"success": True, "message": "Appointment is already cancelled."}
            
        doctor_id = appt["doctor_id"]
        date_str = appt["date"]
        time_str = appt["time"]
        
        doctor = get_doctor_by_id(doctor_id)
        doctor_name = doctor["name"] if doctor else "Doctor"
        
        # Free up the slot
        booked = get_or_create_schedule(cursor, doctor_id, date_str)
        if time_str in booked:
            booked.remove(time_str)
            save_schedule(cursor, doctor_id, date_str, booked)
            
        # Update status
        cursor.execute("UPDATE appointments SET status = 'Cancelled' WHERE id = ?", (appointment_id,))
        conn.commit()
        
        return {
            "success": True,
            "appointment_id": appointment_id,
            "message": f"Successfully cancelled! Your appointment with Dr. {doctor_name} on {date_str} at {time_str} has been cancelled."
        }
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": f"Cancellation failure: {str(e)}"}
    finally:
        conn.close()

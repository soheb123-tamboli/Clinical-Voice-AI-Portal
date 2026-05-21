import sqlite3
import json
import os
from datetime import datetime, timedelta
from backend.config import settings

def get_db_connection():
    conn = sqlite3.connect(settings.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database schema and inserts realistic mock data if the database is empty."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create Doctors table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS doctors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        specialty TEXT NOT NULL,
        languages TEXT NOT NULL,
        max_daily_appointments INTEGER DEFAULT 8
    )
    """)
    
    # Create Patients table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS patients (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        phone TEXT NOT NULL UNIQUE,
        preferred_language TEXT NOT NULL,
        past_medical_notes TEXT,
        preferred_doctor_id INTEGER,
        FOREIGN KEY(preferred_doctor_id) REFERENCES doctors(id)
    )
    """)
    
    # Create Appointments table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS appointments (
        id TEXT PRIMARY KEY,
        patient_id TEXT NOT NULL,
        doctor_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(doctor_id) REFERENCES doctors(id),
        FOREIGN KEY(patient_id) REFERENCES patients(id)
    )
    """)
    
    # Create Doctor Schedule table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS doctor_schedule (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doctor_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        booked_slots TEXT NOT NULL,
        FOREIGN KEY(doctor_id) REFERENCES doctors(id),
        UNIQUE(doctor_id, date)
    )
    """)
    
    # Create Outbound Campaigns table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS campaigns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        patient_id TEXT NOT NULL,
        doctor_id INTEGER,
        scheduled_time TEXT NOT NULL,
        initial_message TEXT NOT NULL,
        status TEXT NOT NULL,
        FOREIGN KEY(patient_id) REFERENCES patients(id),
        FOREIGN KEY(doctor_id) REFERENCES doctors(id)
    )
    """)
    
    conn.commit()
    
    # Check if we need to insert mock data
    cursor.execute("SELECT COUNT(*) FROM doctors")
    if cursor.fetchone()[0] == 0:
        print("Populating SQLite Database with premium mock clinical data...")
        
        # 1. Insert Doctors
        doctors_data = [
            ("Dr. Amit Sharma", "Cardiologist", "English, Hindi", 8),
            ("Dr. Lakshmi Priya", "Dermatologist", "English, Tamil", 8),
            ("Dr. John Miller", "General Physician", "English, Hindi, Tamil", 8)
        ]
        cursor.executemany(
            "INSERT INTO doctors (name, specialty, languages, max_daily_appointments) VALUES (?, ?, ?, ?)",
            doctors_data
        )
        
        # 2. Insert Patients
        patients_data = [
            ("PAT-1001", "Aarav Mehta", "9876543210", "Hindi", "Hypertension and periodic chest pain tracking. High salt risk.", 1),
            ("PAT-1002", "Priya Swaminathan", "8765432109", "Tamil", "Eczema, chronic skin allergy since 2 years. Using topical ointments.", 2),
            ("PAT-1003", "Ramesh Kumar", "7654321098", "Hindi", "Post-mild cardiac arrest rehabilitation check. Follow-ups crucial.", 1),
            ("PAT-1004", "Sarah Jenkins", "6543210987", "English", "General medical history clear. Seasonal allergies.", 3)
        ]
        cursor.executemany(
            "INSERT INTO patients (id, name, phone, preferred_language, past_medical_notes, preferred_doctor_id) VALUES (?, ?, ?, ?, ?, ?)",
            patients_data
        )
        
        # 3. Create Schedules & Pre-Booked slots to simulate real-world conflicts
        today = datetime.now()
        tomorrow = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        day_after = (today + timedelta(days=2)).strftime("%Y-%m-%d")
        
        # Pre-booked slots to showcase conflict resolution:
        # Dr. Amit Sharma has 10:00 and 14:30 booked tomorrow
        # Dr. Lakshmi Priya has 11:30 and 15:00 booked tomorrow
        # Dr. John Miller has 09:30 booked tomorrow
        schedules_data = [
            (1, tomorrow, json.dumps(["10:00", "14:30"])),
            (2, tomorrow, json.dumps(["11:30", "15:00"])),
            (3, tomorrow, json.dumps(["09:30"])),
            (1, day_after, json.dumps([])),
            (2, day_after, json.dumps([])),
            (3, day_after, json.dumps([]))
        ]
        cursor.executemany(
            "INSERT INTO doctor_schedule (doctor_id, date, booked_slots) VALUES (?, ?, ?)",
            schedules_data
        )
        
        # 4. Pre-booked appointments
        appts_data = [
            ("APP-9001", "PAT-1001", 1, tomorrow, "10:00", "Scheduled"),
            ("APP-9002", "PAT-1003", 1, tomorrow, "14:30", "Scheduled"),
            ("APP-9003", "PAT-1002", 2, tomorrow, "11:30", "Scheduled"),
            ("APP-9004", "PAT-1004", 3, tomorrow, "09:30", "Scheduled")
        ]
        cursor.executemany(
            "INSERT INTO appointments (id, patient_id, doctor_id, date, time, status) VALUES (?, ?, ?, ?, ?, ?)",
            appts_data
        )
        
        # 5. Insert Outbound campaigns
        campaigns_data = [
            ("Cardiology Follow-up Campaign", "Follow-up", "PAT-1003", 1, tomorrow + " 10:30", "Hello Ramesh, this is a friendly reminder about your cardiology checkup scheduled with Dr. Amit Sharma. Would you like to confirm this slot?", "Pending"),
            ("Skin Health Check-in", "Reminder", "PAT-1002", 2, tomorrow + " 15:30", "Hello Priya, this is from Dr. Lakshmi's clinic. It is time for your eczema checkup. Can we schedule a slot for tomorrow?", "Pending"),
            ("Seasonal Influenza Vaccination", "Vaccination", "PAT-1001", 3, day_after + " 11:00", "नमस्ते आरव जी, यह डॉ. जॉन मिलर के क्लिनिक से है। आपका फ्लू टीकाकरण होना है। क्या हम कल के लिए स्लॉट बुक करें?", "Pending")
        ]
        cursor.executemany(
            "INSERT INTO campaigns (name, type, patient_id, doctor_id, scheduled_time, initial_message, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            campaigns_data
        )
        
        conn.commit()
    
    conn.close()

# Database Query Utilities
def get_all_doctors():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM doctors")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_doctor_by_id(doctor_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_doctor_by_specialty(specialty):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM doctors WHERE LOWER(specialty) = LOWER(?)", (specialty,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_patients():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patients")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_patient_by_id(patient_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patients WHERE id = ?", (patient_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_patient_by_phone(phone):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Normalize phone match (just taking last 10 digits to be safe)
    cursor.execute("SELECT * FROM patients WHERE phone LIKE ?", (f"%{phone[-10:]}",))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_appointments():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT a.*, p.name as patient_name, p.phone as patient_phone, d.name as doctor_name, d.specialty as doctor_specialty 
    FROM appointments a
    JOIN patients p ON a.patient_id = p.id
    JOIN doctors d ON a.doctor_id = d.id
    ORDER BY a.date ASC, a.time ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_patient_appointments(patient_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT a.*, d.name as doctor_name, d.specialty as doctor_specialty 
    FROM appointments a
    JOIN doctors d ON a.doctor_id = d.id
    WHERE a.patient_id = ?
    ORDER BY a.date DESC, a.time DESC
    """, (patient_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_campaigns():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT c.*, p.name as patient_name, d.name as doctor_name, d.specialty as doctor_specialty
    FROM campaigns c
    JOIN patients p ON c.patient_id = p.id
    LEFT JOIN doctors d ON c.doctor_id = d.id
    ORDER BY c.scheduled_time ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# Initialize on run
if __name__ == "__main__":
    init_db()

import unittest
import os
import sys
import json
from datetime import datetime, timedelta

# Inject root folder into import path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.config import settings
from backend.database import init_db, get_db_connection, get_all_appointments, get_patient_appointments
from backend.memory import session_manager, persistent_memory
from backend.agent.assistant import run_clinical_agent
from backend.agent import tools

class TestClinicalAgent(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        # Override database path for isolated testing
        settings.DATABASE_PATH = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
            "test_appointments.db"
        )
        # Re-initialize clean test schema
        if os.path.exists(settings.DATABASE_PATH):
            try:
                os.remove(settings.DATABASE_PATH)
            except Exception:
                pass
        init_db()

    @classmethod
    def tearDownClass(cls):
        # Clean up test database file
        if os.path.exists(settings.DATABASE_PATH):
            try:
                os.remove(settings.DATABASE_PATH)
            except Exception:
                pass

    def setUp(self):
        # Fresh unique session for each test
        self.session_id = f"test_sess_{datetime.now().timestamp()}"

    def test_01_check_availability(self):
        """Verify availability tool extracts and parses schedule slots successfully."""
        res = tools.check_availability("Dermatologist", "tomorrow")
        self.assertTrue(res["success"])
        self.assertEqual(res["specialty"], "Dermatologist")
        self.assertIn("10:00", res["slots"])
        # Verify fully booked tomorrow slot isn't returned (11:30 is pre-booked tomorrow for Dermatologist)
        self.assertNotIn("11:30", res["slots"])

    def test_02_book_appointment(self):
        """Test booking process handles slot reservation and DB writes correctly."""
        patient_id = "PAT-1004"
        doctor_id = 2  # Dr. Lakshmi Priya (Dermatologist)
        tomorrow_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        time_slot = "10:30"
        
        # Call book tool
        res = tools.book_appointment(patient_id, doctor_id, tomorrow_date, time_slot)
        self.assertTrue(res["success"])
        self.assertEqual(res["time"], time_slot)
        self.assertEqual(res["date"], tomorrow_date)
        
        # Verify stored in SQLite
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM appointments WHERE id = ?", (res["appointment_id"],))
        appt = cursor.fetchone()
        conn.close()
        
        self.assertIsNotNone(appt)
        self.assertEqual(appt["status"], "Scheduled")

    def test_03_conflict_double_booking(self):
        """Ensure double-booking is rejected and alternative slots are recommended."""
        patient_id = "PAT-1001"
        doctor_id = 2  # Dr. Lakshmi Priya
        tomorrow_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        time_slot = "10:30"  # Already booked in previous test
        
        res = tools.book_appointment(patient_id, doctor_id, tomorrow_date, time_slot)
        self.assertFalse(res["success"])
        self.assertTrue(res.get("conflict", False))
        self.assertIn("Slot 10:30 is already booked", res["message"])
        self.assertTrue(len(res.get("alternative_slots", [])) > 0)

    def test_04_reschedule_appointment(self):
        """Test rescheduling moves the appointment and frees the old slot."""
        patient_id = "PAT-1004"
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Fetch the appointment made in test_02
        cursor.execute("SELECT id, date, time FROM appointments WHERE patient_id = ? AND doctor_id = 2 AND status = 'Scheduled'", (patient_id,))
        appt = cursor.fetchone()
        self.assertIsNotNone(appt)
        
        appt_id = appt["id"]
        old_time = appt["time"]
        tomorrow_date = appt["date"]
        new_time = "14:00"
        
        conn.close()
        
        # Perform reschedule
        res = tools.reschedule_appointment(appt_id, tomorrow_date, new_time)
        print("DEBUG reschedule result:", res)
        self.assertTrue(res["success"])
        self.assertEqual(res["time"], new_time)
        
        # Verify DB reflects new slot and status
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check rescheduled status
        cursor.execute("SELECT status, time FROM appointments WHERE id = ?", (appt_id,))
        updated_appt = cursor.fetchone()
        self.assertEqual(updated_appt["status"], "Rescheduled")
        self.assertEqual(updated_appt["time"], new_time)
        
        # Check old slot is freed in schedule
        cursor.execute("SELECT booked_slots FROM doctor_schedule WHERE doctor_id = 2 AND date = ?", (tomorrow_date,))
        booked = json.loads(cursor.fetchone()[0])
        self.assertNotIn(old_time, booked)
        self.assertIn(new_time, booked)
        
        conn.close()

    def test_05_cancel_appointment(self):
        """Test cancellation releases the schedule slot and flags status as Cancelled."""
        patient_id = "PAT-1004"
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, date, time FROM appointments WHERE patient_id = ? AND doctor_id = 2 AND status = 'Rescheduled'", (patient_id,))
        appt = cursor.fetchone()
        appt_id = appt["id"]
        appt_date = appt["date"]
        appt_time = appt["time"]
        conn.close()
        
        res = tools.cancel_appointment(appt_id)
        self.assertTrue(res["success"])
        
        # Check status Cancelled and slot is freed
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT status FROM appointments WHERE id = ?", (appt_id,))
        self.assertEqual(cursor.fetchone()["status"], "Cancelled")
        
        cursor.execute("SELECT booked_slots FROM doctor_schedule WHERE doctor_id = 2 AND date = ?", (appt_date,))
        booked = json.loads(cursor.fetchone()[0])
        self.assertNotIn(appt_time, booked)
        
        conn.close()

    def test_06_agent_state_negotiation(self):
        """Verify the NLP assistant handles multi-turn slot gathering and state transition."""
        session = session_manager.get_session(self.session_id, default_patient_id="PAT-1001")
        
        # First turn: State Booking
        res = run_clinical_agent(self.session_id, "I want to see Dr. Amit Sharma tomorrow", model_mode="local_rules")
        self.assertEqual(res["intent"], "BOOK")
        self.assertEqual(res["slots"]["doctor_specialty"], "Cardiologist")
        
        # Check that it asks for time (Hindi/Tamil/English depending on session lang)
        self.assertIn("Which one do you prefer?", res["reply_text"])
        
        # Second turn: Provide time slot
        res2 = run_clinical_agent(self.session_id, "Let's do 14:00", model_mode="local_rules")
        self.assertEqual(res2["slots"]["time"], "14:00")
        
        # Check that it asks for confirmation
        self.assertIn("Shall I confirm this?", res2["reply_text"])
        
        # Third turn: Confirm "Yes"
        res3 = run_clinical_agent(self.session_id, "Yes, confirm it", model_mode="local_rules")
        self.assertIn("Success!", res3["reply_text"])
        
        # Verify appointment is booked in DB
        appts = get_patient_appointments("PAT-1001")
        self.assertTrue(any(a["time"] == "14:00" and a["status"] == "Scheduled" for a in appts))

if __name__ == "__main__":
    unittest.main()

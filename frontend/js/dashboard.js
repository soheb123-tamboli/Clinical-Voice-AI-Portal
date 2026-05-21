/* ==========================================================================
   2Care.ai Clinical Voice AI Agent Dashboard Engine
   Manages REST updates, patient context card, scheduler grids, & outbound modal.
   ========================================================================== */

let activeCampaignId = null;
let activeCampaignSessionId = null;
let callDurationTimer = null;
let callStartTime = null;

// Audio parameters for campaign mic loop
let modalSpeechRecognition = null;
let isModalRecActive = false;

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById('run-campaign-btn').addEventListener('click', () => {
        const firstBtn = document.querySelector('#campaigns-container .btn-dial');
        if (firstBtn) {
            firstBtn.click();
        } else {
            alert('No pending campaigns to run.');
        }
    });
    initDashboard();
    setupOutboundModalControls();
});

// Setup Initial Load fetches
async function initDashboard() {
    await fetchPatientsList();
    await fetchAppointmentsList();
    await fetchCampaignsList();
    
    // Select patient listener
    const patSelect = document.getElementById("patient-select");
    patSelect.addEventListener("change", (e) => {
        loadPatientContext(e.target.value);
    });
    
    // Reset DB Listener
    document.getElementById("reset-db-btn").addEventListener("click", resetDatabase);
}

// Fetch active Patient list to selector
async function fetchPatientsList() {
    try {
        const response = await fetch("/api/patients");
        const patients = await response.json();
        
        const select = document.getElementById("patient-select");
        select.innerHTML = "";
        
        patients.forEach((p, index) => {
            const opt = document.createElement("option");
            opt.value = p.id;
            opt.innerText = `${p.name} (${p.id})`;
            if (index === 0) opt.selected = true;
            select.appendChild(opt);
        });
        
        if (patients.length > 0) {
            // Load initial patient context
            loadPatientContext(patients[0].id);
        }
    } catch (e) {
        console.error("Error loading patients list:", e);
    }
}

// Loads selected patient data to UI Persistent memory cards
async function loadPatientContext(patientId) {
    try {
        const response = await fetch(`/api/patients/${patientId}/context`);
        const context = await response.json();
        
        // Update variables in app.js
        if (window.setPatientId) {
            window.setPatientId(patientId);
        }
        
        // Name display
        document.getElementById("patient-name-display").innerText = context.name;
        document.getElementById("patient-id-display").innerText = patientId;
        document.getElementById("patient-phone-display").innerText = context.phone;
        
        // Initials Avatar
        const initials = context.name.split(" ").map(n => n[0]).join("").slice(0, 2).toUpperCase();
        document.getElementById("patient-avatar-letters").innerText = initials;
        
        // Language badge
        const langDisplay = document.getElementById("patient-lang-display");
        langDisplay.innerText = context.preferred_language;
        
        // Preferred doc & notes
        const patientDetails = context.context_string;
        const preferredDoc = patientDetails.match(/Preferred Doctor: (.*)/) || ["", "Dr. John Miller"];
        
        // Check doctor assignment
        document.getElementById("patient-doc-display").innerText = 
            patientId === "PAT-1001" ? "Dr. Amit Sharma (Cardiologist)" :
            patientId === "PAT-1002" ? "Dr. Lakshmi Priya (Dermatologist)" : "Dr. John Miller (General Physician)";
            
        // Medical Notes
        document.getElementById("patient-notes-display").innerText = 
            patientId === "PAT-1001" ? "Hypertension and periodic chest pain tracking. High salt risk." :
            patientId === "PAT-1002" ? "Eczema, chronic skin allergy since 2 years. Using topical ointments." :
            patientId === "PAT-1003" ? "Post-mild cardiac arrest rehabilitation check. Follow-ups crucial. Prev stroke history." : 
            "General health clearance. Seasonal respiratory allergy checks.";
            
        // Render Active appointments list for this patient
        renderPatientAppointments(context.active_appointments);
        
    } catch(e) {
        console.error("Context retrieval error:", e);
    }
}

// Fetch all schedules and draw list
async function fetchAppointmentsList() {
    try {
        const response = await fetch("/api/appointments");
        const appts = await response.json();
        
        // If we are showing global appointments or filtering, let's update list
        // For simplicity, local filter handles this.
    } catch (e) {
        console.error("Error fetching appointments:", e);
    }
}

// Draws selected patient appointments to the card list
function renderPatientAppointments(appts) {
    const container = document.getElementById("appointments-container");
    container.innerHTML = "";
    
    if (!appts || appts.length === 0) {
        container.innerHTML = `<div class="no-data">No active appointments found.</div>`;
        return;
    }
    
    appts.forEach(a => {
        const item = document.createElement("div");
        item.className = "appointment-item";
        
        // Format Status label
        const statusClass = a.status.toLowerCase();
        
        item.innerHTML = `
            <div class="appt-info">
                <h4>${a.doctor_name}</h4>
                <p><i class="fa-regular fa-calendar"></i> ${a.date} &bull; <i class="fa-regular fa-clock"></i> ${a.time}</p>
            </div>
            <div class="appt-status-col">
                <span class="badge-status ${statusClass}">${a.status}</span>
                <span class="badge badge-accent font-weight-bold" style="font-size:8px;">${a.id}</span>
            </div>
        `;
        container.appendChild(item);
    });
}

// Fetch Outbound Campaigns and populate card list
async function fetchCampaignsList() {
    try {
        const response = await fetch("/api/campaigns");
        const campaigns = await response.json();
        
        const container = document.getElementById("campaigns-container");
        container.innerHTML = "";
        
        if (campaigns.length === 0) {
            container.innerHTML = `<div class="no-data">No active campaigns.</div>`;
            return;
        }
        
        campaigns.forEach(c => {
            const item = document.createElement("div");
            item.className = "campaign-item";
            
            const statusClass = c.status.toLowerCase().replace(" ", "_");
            
            let actionBtn = "";
            if (c.status === "Pending") {
                actionBtn = `
                    <button class="btn-dial" onclick="startOutboundCall(${c.id})" title="Initiate outbound voice reminder call">
                        <i class="fa-solid fa-phone"></i>
                    </button>
                `;
            }
            
            item.innerHTML = `
                <div class="camp-info">
                    <h4>${c.name}</h4>
                    <p><i class="fa-solid fa-user"></i> ${c.patient_name} &bull; ${c.type}</p>
                </div>
                <div class="camp-btn-row">
                    <span class="badge-camp-status ${statusClass}">${c.status}</span>
                    ${actionBtn}
                </div>
            `;
            container.appendChild(item);
        });
    } catch (e) {
        console.error("Error loading campaigns:", e);
    }
}

// Starts the simulated outbound calling portal sequence
async function startOutboundCall(campaignId) {
    activeCampaignId = campaignId;
    
    try {
        // Post trigger to backend Campaign Service
        const res = await fetch(`/api/campaigns/trigger/${campaignId}`, { method: "POST" });
        const data = await res.json();
        
        if (!res.ok) throw new Error(data.detail);
        
        activeCampaignSessionId = data.session_id;
        
        // Open Calling Modal Overlay UI
        const modal = document.getElementById("call-modal");
        modal.classList.add("active");
        
        document.getElementById("modal-caller-name").innerText = data.patient_name;
        document.getElementById("modal-caller-phone").innerText = `Dialing: ${data.phone}`;
        document.getElementById("modal-camp-name").innerText = data.campaign_name;
        document.getElementById("modal-camp-lang").innerText = data.language;
        
        document.getElementById("modal-call-duration").innerText = "Dialing...";
        document.getElementById("modal-call-status").innerText = "Connecting secure channel...";
        
        document.getElementById("modal-glow-pulse").style.animationPlayState = "running";
        
        // Simulate Ringing delay of 1.5s
        setTimeout(() => {
            document.getElementById("modal-call-duration").innerText = "00:00";
            document.getElementById("modal-call-status").innerText = "Call Connected - Agent Speaking";
            
            // Start Timer duration
            callStartTime = Date.now();
            callDurationTimer = setInterval(updateCallDuration, 1000);
            
            // Agent speaks greeting instantly
            speakCampaignGreeting(data.initial_greeting, data.language);
            
        }, 1500);
        
    } catch(e) {
        alert("Failed to initiate campaign call: " + e.message);
    }
}

// Update Call Timer
function updateCallDuration() {
    const elapsedSecs = Math.floor((Date.now() - callStartTime) / 1000);
    const mins = String(Math.floor(elapsedSecs / 60)).padStart(2, '0');
    const secs = String(elapsedSecs % 60).padStart(2, '0');
    document.getElementById("modal-call-duration").innerText = `${mins}:${secs}`;
}

// Speak the outbound clinical script
function speakCampaignGreeting(greeting, language) {
    if (!window.speechSynthesis) {
        document.getElementById("modal-call-status").innerText = "Greeting complete. Waiting for patient...";
        startModalSpeechRecognition(language);
        return;
    }
    
    const utterance = new SpeechSynthesisUtterance(greeting);
    if (language === "Hindi") utterance.lang = "hi-IN";
    else if (language === "Tamil") utterance.lang = "ta-IN";
    else utterance.lang = "en-US";
    
    utterance.onend = () => {
        document.getElementById("modal-call-status").innerText = "Active - Listening to patient...";
        
        // Initialize Speech Recognition loop inside modal to allow patient response!
        startModalSpeechRecognition(language);
    };
    
    utterance.onerror = () => {
        document.getElementById("modal-call-status").innerText = "Active - Listening to patient...";
        startModalSpeechRecognition(language);
    };
    
    window.speechSynthesis.speak(utterance);
}

// Setup dedicated speech recognizer loop in campaign call modal
function startModalSpeechRecognition(language) {
    if (isModalRecActive) return;
    
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return;
    
    modalSpeechRecognition = new SpeechRecognition();
    modalSpeechRecognition.continuous = false;
    modalSpeechRecognition.interimResults = false;
    
    if (language === "Hindi") modalSpeechRecognition.lang = "hi-IN";
    else if (language === "Tamil") modalSpeechRecognition.lang = "ta-IN";
    else modalSpeechRecognition.lang = "en-US";
    
    modalSpeechRecognition.onstart = () => {
        isModalRecActive = true;
    };
    
    modalSpeechRecognition.onresult = async (event) => {
        const patientWords = event.results[0][0].transcript;
        document.getElementById("modal-call-status").innerText = `Patient said: "${patientWords}"`;
        
        // Send this verbal response to the backend campaign session over WebSocket!
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: "text",
                session_id: activeCampaignSessionId,
                patient_id: document.getElementById("patient-select").value,
                text: patientWords,
                api_mode: apiMode
            }));
            
            document.getElementById("modal-call-status").innerText = "Agent is formulating slot check...";
        }
    };
    
    modalSpeechRecognition.onend = () => {
        isModalRecActive = false;
        // Keep listening as long as call is active
        if (document.getElementById("call-modal").classList.contains("active")) {
            try {
                modalSpeechRecognition.start();
            } catch(e) {}
        }
    };
    
    modalSpeechRecognition.onerror = (e) => {
        if (e.error !== "no-speech" && document.getElementById("call-modal").classList.contains("active")) {
            console.warn("Modal Speech Recognition error:", e.error);
        }
    };
    
    modalSpeechRecognition.start();
}

// Setup End Call Modal hooks
function setupOutboundModalControls() {
    const endBtn = document.getElementById("end-call-btn");
    endBtn.addEventListener("click", hangUpOutboundCall);
}

// Closes and wraps up call campaign sequence
async function hangUpOutboundCall() {
    // Clear timer
    if (callDurationTimer) {
        clearInterval(callDurationTimer);
        callDurationTimer = null;
    }
    
    // Stop recognition
    if (modalSpeechRecognition) {
        try {
            modalSpeechRecognition.stop();
        } catch(e) {}
        isModalRecActive = false;
    }
    
    // Cancel active synthesis
    window.speechSynthesis.cancel();
    
    document.getElementById("call-modal").classList.remove("active");
    document.getElementById("modal-glow-pulse").style.animationPlayState = "paused";
    
    if (activeCampaignId) {
        // Complete in DB
        await fetch(`/api/campaigns/complete/${activeCampaignId}?success=true`, { method: "POST" });
        activeCampaignId = null;
    }
    
    // Refresh dashboards
    fetchCampaignsList();
    loadPatientContext(document.getElementById("patient-select").value);
}

// Handles dynamic updates passed from WebSocket events (e.g. bookings confirmed!)
window.refreshDashboard = function(slots, intent) {
    const activePatId = document.getElementById("patient-select").value;
    
    // Wait briefly and update patient card + campaign rosters
    setTimeout(() => {
        loadPatientContext(activePatId);
        fetchCampaignsList();
    }, 800);
};

// Reset SQLite database to pristine state
async function resetDatabase() {
    const check = confirm("Are you sure you want to reset the SQLite database? This will clear all changes and restore pristine pre-booked slots and mock campaign reminders.");
    if (!check) return;
    
    try {
        const res = await fetch("/api/reset-db", { method: "POST" });
        const data = await res.json();
        
        if (res.ok) {
            alert("Database re-populated successfully!");
            // Reload context
            initDashboard();
        } else {
            alert("Database lock issue. Restart server first.");
        }
    } catch(e) {
        alert("System error resetting database.");
    }
}

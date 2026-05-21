/* ==========================================================================
   2Care.ai Clinical Voice AI Agent Client-side Engine
   Handles WebSockets, Audio capture, visualizer, STT/TTS, & analytics.
   ========================================================================== */

// Connection & Global State Variables
let ws = null;
let sessionId = "sess_" + Math.random().toString(36).substr(2, 9);
let currentPatientId = "PAT-1001";
let isRecording = false;
let isSpeaking = false;
let playingSourceNode = null; // Global reference for current audio playback source
let currentUtterance = null; // Global reference for SpeechSynthesis utterance
let audioChunks = [];
let silenceTimer = null;

// Speech Synthesis & Recognition engines (Browser fallbacks for zero-latency)
let speechRecognition = null;
let isRecognitionActive = false;

// Audio context & Visualizer
let audioContext = null;
let analyser = null;
let canvas = null;
let canvasCtx = null;
let animationFrameId = null;

// Latency & API settings
let apiMode = "local_rules"; // Controlled by toggle
let latencyChartData = []; // To plot logs

// Wait for DOM load
document.addEventListener("DOMContentLoaded", () => {
    initElements();
    setupCanvas();
    connectWebSocket();
    setupSpeechRecognition();
});

// Setup elements and click handlers
function initElements() {
    canvas = document.getElementById("wave-canvas");
    
    // Toggle Live API Mode vs Mock NLP
    const modeToggle = document.getElementById("api-mode-toggle");
    modeToggle.addEventListener("change", (e) => {
        apiMode = e.target.checked ? "live" : "local_rules";
        addConsoleLine(`[System] API Mode toggled to: ${apiMode.toUpperCase()}`);
    });
    
    // Mic Button
    const micBtn = document.getElementById("mic-btn");
    micBtn.addEventListener("click", toggleVoiceInput);
    
    // Manual Text Input
    const textForm = document.getElementById("text-input-form");
    textForm.addEventListener("submit", handleManualTextInput);
    
    // Clear Chat
    document.getElementById("clear-chat-btn").addEventListener("click", () => {
        document.getElementById("chat-messages").innerHTML = "";
    });
}

// Setup Canvas visualizer
function setupCanvas() {
    canvasCtx = canvas.getContext("2d");
}

// Establish real-time WebSocket connection
function connectWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host || "127.0.0.1:8000";
    
    addConsoleLine("[System] Connecting to WebSocket voice server...");
    
    ws = new WebSocket(`${protocol}//${host}/ws/voice`);
    
    ws.onopen = () => {
        addConsoleLine("[System] WebSocket channel opened.");
        document.getElementById("backend-status").innerHTML = `
            <span class="status-dot green"></span>
            <span class="status-text">Connected</span>
        `;
        
        // Initialize session on backend
        ws.send(jsonPayload("init", {
            session_id: sessionId,
            patient_id: currentPatientId
        }));
    };
    
    ws.onmessage = (event) => {
        const response = JSON.parse(event.data);
        handleServerResponse(response);
    };
    
    ws.onclose = () => {
        addConsoleLine("[System] WebSocket disconnected. Retrying in 4s...");
        document.getElementById("backend-status").innerHTML = `
            <span class="status-dot red"></span>
            <span class="status-text">Disconnected</span>
        `;
        setTimeout(connectWebSocket, 4000);
    };
    
    ws.onerror = (error) => {
        addConsoleLine(`[System] WebSocket Error: ${JSON.stringify(error)}`);
    };
}

// Helper to write JSON payloads
function jsonPayload(type, data = {}) {
    return JSON.stringify({
        type: type,
        session_id: sessionId,
        patient_id: currentPatientId,
        api_mode: apiMode,
        ...data
    });
}

// Setup local Web Speech Recognition fallback for zero latency
function setupSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
        speechRecognition = new SpeechRecognition();
        speechRecognition.continuous = false;
        speechRecognition.interimResults = false;
        
        speechRecognition.onstart = () => {
            isRecognitionActive = true;
        };
        
        speechRecognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            addConsoleLine(`[STT Fallback] Captured: "${transcript}"`);
            
            // Send captured transcript as text to speed up processing
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(jsonPayload("text", {
                    text: transcript
                }));
            }
        };
        
        speechRecognition.onend = () => {
            isRecognitionActive = false;
            if (isRecording) {
                // If recording didn't stop manually, restart recognition
                try {
                    speechRecognition.start();
                } catch(e) {}
            }
        };
        
        speechRecognition.onerror = (err) => {
            if (err.error !== "no-speech") {
                addConsoleLine(`[STT Warning] Local SpeechRecognition error: ${err.error}`);
            }
        };
    }
}

// Handle voice recorder button toggles
async function toggleVoiceInput() {
    const consolePanel = document.querySelector(".voice-console-panel");
    const statusText = document.getElementById("console-status-text");
    
    if (isRecording) {
        // Stop recording
        isRecording = false;
        consolePanel.classList.remove("listening");
        statusText.innerText = "Processing clinical slots...";
        
        if (mediaRecorder && mediaRecorder.state !== "inactive") {
            mediaRecorder.stop();
        }
        
        if (speechRecognition && isRecognitionActive) {
            speechRecognition.stop();
        }
        
        stopWaveVisualization();
        addConsoleLine("[System] Speech recording captured. Formulating pipeline package.");
    } else {
        // Stop active speech synthesis playback and any ongoing audio source
        window.speechSynthesis.cancel();
        if (playingSourceNode) {
            try {
                playingSourceNode.stop();
            } catch(e) {}
            playingSourceNode.disconnect();
            playingSourceNode = null;
        }
        if (currentUtterance) {
            window.speechSynthesis.cancel();
            currentUtterance = null;
        }
        
        // Start recording
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            
            // Audio visualizer setup
            setupAudioAnalyser(stream);
            
            isRecording = true;
            consolePanel.classList.add("listening");
            statusText.innerText = "Listening... Speak now";
            
            audioChunks = [];
            
            // Determine recording format
            let mimeType = "audio/webm";
            if (!MediaRecorder.isTypeSupported(mimeType)) {
                mimeType = "audio/ogg";
            }
            if (!MediaRecorder.isTypeSupported(mimeType)) {
                mimeType = "audio/mp4";
            }
            
            mediaRecorder = new MediaRecorder(stream);
            
            mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    audioChunks.push(event.data);
                }
            };
            
            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: mimeType });
                
                // Get pre-transcribed browser assist
                let clientText = "";
                
                // Convert blob to base64 and send over WS
                const reader = new FileReader();
                reader.readAsDataURL(audioBlob);
                reader.onloadend = () => {
                    const base64Audio = reader.result.split(',')[1];
                    if (ws && ws.readyState === WebSocket.OPEN) {
                        ws.send(jsonPayload("audio", {
                            audio_data: base64Audio,
                            client_transcript: clientText,
                            file_extension: mimeType.split("/")[1]
                        }));
                        
                        document.querySelector(".voice-console-panel").classList.add("thinking");
                        document.getElementById("console-status-text").innerText = "Thinking...";
                    }
                };
                
                // Release stream tracks
                stream.getTracks().forEach(track => track.stop());
            };
            
            mediaRecorder.start(100); // Trigger dataavailable every 100ms
            
            // Trigger local Speech Recognition assist
            if (speechRecognition) {
                const currentLangDesc = document.getElementById("patient-lang-display").innerText;
                if (currentLangDesc === "Hindi") speechRecognition.lang = "hi-IN";
                else if (currentLangDesc === "Tamil") speechRecognition.lang = "ta-IN";
                else speechRecognition.lang = "en-US";
                
                try {
                    speechRecognition.start();
                } catch(e) {}
            }
            
            startWaveVisualization();
            addConsoleLine("[System] Recording started. Audio analyzer active.");
            
        } catch (err) {
            addConsoleLine(`[Audio Error] Mic access blocked: ${err.message}`);
            alert("Could not access your microphone. Please check system permissions.");
        }
    }
}

// Handle Manual Form Text Submission
function handleManualTextInput(e) {
    e.preventDefault();
    const inputEl = document.getElementById("text-prompt-input");
    const text = inputEl.value.trim();
    if (!text) return;
    
    addConsoleLine(`[Keyboard Input] User sent: "${text}"`);
    appendChatBubble("user", text, "EN"); // temporary tag, server will return detected lang
    
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(jsonPayload("text", {
            text: text
        }));
        
        document.querySelector(".voice-console-panel").classList.add("thinking");
        document.getElementById("console-status-text").innerText = "Thinking...";
    }
    
    inputEl.value = "";
}

// Handle Incoming Server WebSocket responses
function handleServerResponse(response) {
    const consolePanel = document.querySelector(".voice-console-panel");
    consolePanel.classList.remove("thinking");
    document.getElementById("console-status-text").innerText = "Idle - Click to Speak";
    
    if (response.type === "silent_frame") {
        return;
    }
    
    if (response.type === "init_success") {
        addConsoleLine(`[System] Context initialized for session ${response.session_id}. Language: ${response.language}`);
        updateActiveFlags(response.language);
        return;
    }
    
    if (response.type === "response") {
        const transcript = response.input_transcript;
        const replyText = response.reply_text;
        const detectedLang = response.detected_language;
        const audioB64 = response.audio_base64;
        const traces = response.reasoning_traces || [];
        const slots = response.slots || {};
        const intent = response.intent || "NONE";
        const latency = response.latency || {};
        
        // Print Transcribed Input if exists
        if (transcript) {
            appendChatBubble("user", transcript, detectedLang);
        }
        
        // Print Agent Spoken Reply
        appendChatBubble("assistant", replyText, detectedLang);
        
        // Print Reasoning Logs in Footer CLI
        if (traces.length > 0) {
            traces.forEach(line => {
                if (line.startsWith("[Tool Call]")) {
                    addConsoleLine(line, "tool");
                } else if (line.startsWith("[Database]")) {
                    addConsoleLine(line, "database");
                } else {
                    addConsoleLine(`[Reasoning] ${line}`, "reasoning");
                }
            });
        }
        
        // Playback Synthesized Response Voice
        playVoiceResponse(replyText, audioB64, detectedLang);
        
        // Update Latency Performance metrics UI
        updateLatencyUI(latency);
        
        // Update flags
        updateActiveFlags(detectedLang);
        
        // Trigger Dashboard Refresh (Appointments appointments lists)
        if (window.refreshDashboard) {
            window.refreshDashboard(slots, intent);
        }
    }
}

// Plays back audio response (Live API decodes b64, Mock local runs browser synthesis)
function playVoiceResponse(text, base64Audio, language) {
    if (base64Audio) {
        // Live OpenAI TTS mode
        isSpeaking = true;
        document.querySelector(".voice-console-panel").classList.add("speaking");
        document.getElementById("console-status-text").innerText = "Speaking...";
        
        const audioData = base64ToArrayBuffer(base64Audio);
        const playCtx = new (window.AudioContext || window.webkitAudioContext)();
        
        playCtx.decodeAudioData(audioData, (buffer) => {
            const sourceNode = playCtx.createBufferSource();
            sourceNode.buffer = buffer;
            
            // Connect to visualizer analyser
            setupAudioAnalyser(null, playCtx, sourceNode);
            startWaveVisualization();
            
            sourceNode.connect(playCtx.destination);
            sourceNode.onended = () => {
                isSpeaking = false;
                document.querySelector(".voice-console-panel").classList.remove("speaking");
                document.getElementById("console-status-text").innerText = "Idle";
                stopWaveVisualization();
                playingSourceNode = null;
            };
            playingSourceNode = sourceNode;
            sourceNode.start(0);
        }, (err) => {
            addConsoleLine(`[Audio Output Error] Base64 decoding failed: ${err.message}`);
            playLocalBrowserTTS(text, language);
        });
    } else {
        // Fallback to local Browser SpeechSynthesis (Under 10ms start!)
        playLocalBrowserTTS(text, language);
    }
}

// Implements ultra-fast, offline browser speech synthesis in correct language
function playLocalBrowserTTS(text, language) {
    if (!window.speechSynthesis) return;
    
    isSpeaking = true;
    const consolePanel = document.querySelector(".voice-console-panel");
    consolePanel.classList.add("speaking");
    document.getElementById("console-status-text").innerText = "Speaking...";
    
    const utterance = new SpeechSynthesisUtterance(text);
    currentUtterance = utterance;
    
    // Choose appropriate localized voice
    if (language === "Hindi") {
        utterance.lang = "hi-IN";
    } else if (language === "Tamil") {
        utterance.lang = "ta-IN";
    } else {
        utterance.lang = "en-US";
    }
    
    // Match visualizer
    startWaveVisualization();
    
    utterance.onend = () => {
        isSpeaking = false;
        consolePanel.classList.remove("speaking");
        document.getElementById("console-status-text").innerText = "Idle";
        stopWaveVisualization();
        currentUtterance = null;
    };
    
    utterance.onerror = () => {
        isSpeaking = false;
        consolePanel.classList.remove("speaking");
        document.getElementById("console-status-text").innerText = "Idle";
        stopWaveVisualization();
        currentUtterance = null;
    };
    
    window.speechSynthesis.speak(utterance);
}

// Convert Base64 back to ArrayBuffer
function base64ToArrayBuffer(base64) {
    const binary_string = window.atob(base64);
    const len = binary_string.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
        bytes[i] = binary_string.charCodeAt(i);
    }
    return bytes.buffer;
}

// Setup audio nodes for visual frequencies
function setupAudioAnalyser(stream = null, existingCtx = null, sourceNode = null) {
    try {
        if (!audioContext) {
            audioContext = existingCtx || new (window.AudioContext || window.webkitAudioContext)();
        }
        
        if (!analyser) {
            analyser = audioContext.createAnalyser();
            analyser.fftSize = 256;
        }
        
        if (stream) {
            const streamSource = audioContext.createMediaStreamSource(stream);
            streamSource.connect(analyser);
        } else if (sourceNode) {
            sourceNode.connect(analyser);
        }
    } catch(e) {
        addConsoleLine(`[Audio Visualizer Warning] Analyser hook failed: ${e.message}`);
    }
}

// Draw premium neon ripple waves on Canvas
function startWaveVisualization() {
    const bufferLength = analyser ? analyser.frequencyBinCount : 128;
    const dataArray = new Uint8Array(bufferLength);
    
    const draw = () => {
        animationFrameId = requestAnimationFrame(draw);
        
        if (analyser) {
            analyser.getByteFrequencyData(dataArray);
        }
        
        canvasCtx.fillStyle = "rgba(13, 18, 34, 0.4)";
        canvasCtx.fillRect(0, 0, canvas.width, canvas.height);
        
        // Choose glowing colors based on mic/speaking status
        let glowColor = "rgba(6, 182, 212, 0.8)"; // Teal default
        if (isRecording) {
            glowColor = "rgba(16, 185, 129, 0.8)"; // Emerald
        } else if (isSpeaking) {
            glowColor = "rgba(14, 165, 233, 0.8)"; // Cyan
        }
        
        canvasCtx.lineWidth = 3;
        canvasCtx.strokeStyle = glowColor;
        canvasCtx.beginPath();
        
        const sliceWidth = canvas.width * 1.0 / bufferLength;
        let x = 0;
        
        for (let i = 0; i < bufferLength; i++) {
            let v = (analyser ? dataArray[i] : (10 + Math.random() * 20)) / 128.0;
            // Amplify for visual effect if actively speaking/listening
            if (isRecording || isSpeaking) {
                v = v * 1.5;
            } else {
                v = v * 0.1; // Flat line mostly when quiet
            }
            const y = v * canvas.height / 2;
            
            if (i === 0) {
                canvasCtx.moveTo(x, y);
            } else {
                canvasCtx.lineTo(x, y);
            }
            
            x += sliceWidth;
        }
        
        canvasCtx.lineTo(canvas.width, canvas.height / 2);
        canvasCtx.stroke();
    };
    
    // Clear old visual animation
    if (animationFrameId) {
        cancelAnimationFrame(animationFrameId);
    }
    draw();
}

function stopWaveVisualization() {
    if (animationFrameId) {
        cancelAnimationFrame(animationFrameId);
        animationFrameId = null;
    }
    
    // Draw flat neon line
    canvasCtx.fillStyle = "#0d1222";
    canvasCtx.fillRect(0, 0, canvas.width, canvas.height);
    canvasCtx.strokeStyle = "rgba(255, 255, 255, 0.05)";
    canvasCtx.lineWidth = 1;
    canvasCtx.beginPath();
    canvasCtx.moveTo(0, canvas.height / 2);
    canvasCtx.lineTo(canvas.width, canvas.height / 2);
    canvasCtx.stroke();
}

// Append conversation chat bubbles
function appendChatBubble(role, text, langCode = "EN") {
    const chatContainer = document.getElementById("chat-messages");
    
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${role}`;
    
    const paragraph = document.createElement("p");
    paragraph.innerText = text;
    bubble.appendChild(paragraph);
    
    const meta = document.createElement("span");
    meta.className = "msg-meta";
    
    const speakerLabel = role === "assistant" ? "AI Agent" : "Patient";
    meta.innerText = `${speakerLabel} \u2022 ${langCode.toUpperCase()}`;
    bubble.appendChild(meta);
    
    chatContainer.appendChild(bubble);
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

// Append scrolling CLI traces in footer console
function addConsoleLine(text, type = "system") {
    const consoleEl = document.getElementById("traces-console");
    const line = document.createElement("div");
    line.className = `console-line ${type}`;
    
    const timestamp = new Date().toLocaleTimeString();
    line.innerText = `[${timestamp}] ${text}`;
    
    consoleEl.appendChild(line);
    consoleEl.scrollTop = consoleEl.scrollHeight;
}

// Update Active Language Indicators UI flags
function updateActiveFlags(language) {
    const flags = {
        "English": document.getElementById("flag-en"),
        "Hindi": document.getElementById("flag-hi"),
        "Tamil": document.getElementById("flag-ta")
    };
    
    Object.keys(flags).forEach(key => {
        if (flags[key]) {
            if (key === language) {
                flags[key].classList.add("active");
            } else {
                flags[key].classList.remove("active");
            }
        }
    });
}

// Render Latency dashboard metric values
function updateLatencyUI(latency) {
    const total = latency.total_ms || 0;
    const stt = latency.stt_ms || 0;
    const agent = latency.agent_ms || 0;
    const tts = latency.tts_ms || 0;
    
    const totalBadge = document.getElementById("latency-total-badge");
    totalBadge.innerText = `${total} ms`;
    
    // Apply color threshold badges
    totalBadge.className = "latency-badge";
    if (total < 450) {
        totalBadge.classList.add("badge-green");
    } else if (total < 850) {
        totalBadge.classList.add("badge-yellow");
    } else {
        totalBadge.classList.add("badge-red");
    }
    
    // Numerical stats
    document.getElementById("latency-stt").innerText = `${stt} ms`;
    document.getElementById("latency-agent").innerText = `${agent} ms`;
    document.getElementById("latency-tts").innerText = `${tts} ms`;
    
    // Mode tags
    document.getElementById("mode-stt").innerText = `Mode: ${latency.stt_mode}`;
    document.getElementById("mode-tts").innerText = `Mode: ${latency.tts_mode}`;
    
    // Smooth progress loading percentages (max caps on 100% relative base)
    const maxVal = Math.max(total, 600);
    document.getElementById("bar-stt").style.width = `${Math.min(100, (stt / maxVal) * 100)}%`;
    document.getElementById("bar-agent").style.width = `${Math.min(100, (agent / maxVal) * 100)}%`;
    document.getElementById("bar-tts").style.width = `${Math.min(100, (tts / maxVal) * 100)}%`;
}

// Expose active session updates for dashboard script
window.activeSessionId = sessionId;
window.setPatientId = (patId) => {
    currentPatientId = patId;
    sessionId = "sess_" + Math.random().toString(36).substr(2, 9);
    window.activeSessionId = sessionId;
    addConsoleLine(`[System] Patient context updated. Switched session to ${sessionId}`);
    
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(jsonPayload("init", {
            session_id: sessionId,
            patient_id: patId
        }));
    }
};

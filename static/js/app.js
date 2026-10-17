// Exam Proctoring Dashboard Frontend Application

let pollInterval = null;
let sessionStartTime = null;

document.addEventListener("DOMContentLoaded", () => {
    initDashboard();
});

function initDashboard() {
    pollStatus();
    fetchEvents();
    // Poll telemetry at 1 second intervals
    pollInterval = setInterval(pollStatus, 1000);
}

// --- Telemetry Polling ---
async function pollStatus() {
    try {
        const response = await fetch("/api/status");
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        updateUI(data);
    } catch (err) {
        console.warn("Status poll failed:", err);
        showCameraError("Cannot connect to proctoring server on 127.0.0.1");
    }
}

function updateUI(data) {
    // 1. Update Status Badge
    const badge = document.getElementById("statusBadge");
    const statusText = document.getElementById("statusText");
    const currentStatus = data.current_status || "STOPPED";

    statusText.innerText = currentStatus;
    badge.className = "status-badge";

    if (currentStatus === "NORMAL") {
        badge.classList.add("status-normal");
    } else if (currentStatus.includes("ALERT") || currentStatus === "FACE ABSENT" || currentStatus === "MULTIPLE FACES") {
        badge.classList.add("status-alert");
    } else if (currentStatus.includes("WARNING")) {
        badge.classList.add("status-warning");
    } else {
        badge.classList.add("status-stopped");
    }

    // 2. Update Raspberry Pi Badge
    const piBadge = document.getElementById("piBadge");
    const piStatusText = document.getElementById("piStatusText");
    if (!data.pi.enabled) {
        piStatusText.innerText = "Pi: DISABLED";
        piBadge.style.opacity = "0.7";
    } else if (data.pi.online) {
        piStatusText.innerText = "Pi: ONLINE";
        piBadge.style.borderColor = "var(--accent-green)";
        piBadge.style.opacity = "1.0";
    } else {
        piStatusText.innerText = "Pi: OFFLINE";
        piBadge.style.borderColor = "var(--accent-amber)";
        piBadge.style.opacity = "0.8";
    }

    // 3. Update Camera Stream & Overlay
    const overlay = document.getElementById("cameraOfflineOverlay");
    const errorDetails = document.getElementById("cameraErrorDetails");
    const specBadge = document.getElementById("cameraSpecBadge");

    if (data.camera.online) {
        overlay.classList.add("hidden");
        specBadge.innerText = `${data.camera.backend} • ${data.camera.width}×${data.camera.height} (${data.camera.fps} FPS)`;
    } else {
        overlay.classList.remove("hidden");
        errorDetails.innerText = data.camera.error || "Webcam offline or permission not granted.";
    }

    // 4. Update Session Timer & Session ID
    const sessionTag = document.getElementById("sessionIdTag");
    sessionTag.innerText = `Session: ${data.session_id}`;

    const timerDisplay = document.getElementById("sessionTimerDisplay");
    timerDisplay.innerText = formatDuration(data.elapsed_seconds);

    // 5. Update Metrics
    document.getElementById("faceCountVal").innerText = data.is_active ? data.face_count : "--";
    document.getElementById("totalAnomaliesVal").innerText = data.event_counts.TOTAL_ANOMALIES || 0;
    document.getElementById("absenceCountVal").innerText = data.event_counts.FACE_ABSENT || 0;
    document.getElementById("multipleCountVal").innerText = data.event_counts.MULTIPLE_FACES || 0;

    // Active timer subtexts
    const absTimerSub = document.getElementById("absenceTimerSub");
    absTimerSub.innerText = `Active absence: ${data.absence_elapsed_sec}s`;
    absTimerSub.style.color = data.absence_elapsed_sec > 0 ? "var(--accent-amber)" : "var(--text-muted)";

    const mulTimerSub = document.getElementById("multipleTimerSub");
    mulTimerSub.innerText = `Active multiple: ${data.multiple_elapsed_sec}s`;
    mulTimerSub.style.color = data.multiple_elapsed_sec > 0 ? "var(--accent-amber)" : "var(--text-muted)";

    // Toggle button state
    document.getElementById("btnStartSession").disabled = data.is_active;
    document.getElementById("btnStopSession").disabled = !data.is_active;
}

function formatDuration(totalSeconds) {
    if (!totalSeconds || totalSeconds < 0) return "Elapsed: 00:00:00";
    const hrs = Math.floor(totalSeconds / 3600);
    const mins = Math.floor((totalSeconds % 3600) / 60);
    const secs = Math.floor(totalSeconds % 60);
    return `Elapsed: ${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

// --- Session Controls ---
async function startSession() {
    try {
        const resp = await fetch("/api/session/start", { method: "POST" });
        const res = await resp.json();
        if (res.success) {
            pollStatus();
            fetchEvents();
        }
    } catch (e) {
        alert("Failed to start session: " + e.message);
    }
}

async function stopSession() {
    try {
        const resp = await fetch("/api/session/stop", { method: "POST" });
        const res = await resp.json();
        if (res.success) {
            pollStatus();
        }
    } catch (e) {
        alert("Failed to stop session: " + e.message);
    }
}

// --- Events & Evidence ---
async function fetchEvents() {
    try {
        const resp = await fetch("/api/events?limit=30");
        const data = await resp.json();
        renderEventsTable(data.events || []);
    } catch (e) {
        console.error("Failed to load events:", e);
    }
}

function renderEventsTable(events) {
    const tbody = document.getElementById("eventsTableBody");
    if (!events || events.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" class="text-center text-muted">No proctoring anomalies recorded yet.</td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = events.map(evt => {
        let badgeClass = "badge-camera";
        if (evt.event_type === "FACE_ABSENT") badgeClass = "badge-absence";
        if (evt.event_type === "MULTIPLE_FACES") badgeClass = "badge-multiple";

        const snapshotHtml = evt.snapshot_filename
            ? `<img src="/evidence/${evt.snapshot_filename}" 
                    class="snapshot-thumb" 
                    alt="Evidence" 
                    onclick="openModal('/evidence/${evt.snapshot_filename}', '${evt.id}', '${evt.event_type}', '${evt.timestamp}')">`
            : `<span class="text-muted">None</span>`;

        // Format timestamp cleanly
        const cleanTs = evt.timestamp.replace("T", " ").split(".")[0];

        return `
            <tr>
                <td style="font-family: 'JetBrains Mono', monospace; font-size: 11px;">${evt.id}</td>
                <td style="font-size: 12px; color: var(--text-secondary);">${cleanTs}</td>
                <td><span class="event-type-badge ${badgeClass}">${evt.event_type}</span></td>
                <td>${evt.face_count}</td>
                <td style="font-size: 12px;">${escapeHtml(evt.explanation)}</td>
                <td>${snapshotHtml}</td>
            </tr>
        `;
    }).join("");
}

async function confirmClearEvents() {
    const confirmed = confirm(
        "Are you sure you want to clear all logged test events and delete evidence snapshots from disk?\n\nThis cannot be undone."
    );
    if (!confirmed) return;

    try {
        const resp = await fetch("/api/events/clear", { method: "POST" });
        const res = await resp.json();
        if (res.success) {
            fetchEvents();
            pollStatus();
            alert(`Cleared ${res.cleared_count} test events.`);
        }
    } catch (e) {
        alert("Failed to clear events: " + e.message);
    }
}

// --- Modal Handling ---
function openModal(imgSrc, eventId, eventType, timestamp) {
    const modal = document.getElementById("imageModal");
    const modalImg = document.getElementById("modalImage");
    const modalTitle = document.getElementById("modalTitle");
    const modalCaption = document.getElementById("modalCaption");

    modalTitle.innerText = `Evidence Snapshot: ${eventType} (${eventId})`;
    modalImg.src = imgSrc;
    modalCaption.innerText = `Captured: ${timestamp} • Frame flagged for human proctor verification.`;
    modal.classList.remove("hidden");
}

function closeModal() {
    document.getElementById("imageModal").classList.add("hidden");
}

// --- Stream Handling ---
function handleStreamError() {
    showCameraError("Video feed stream disconnected.");
}

function retryStream() {
    const img = document.getElementById("cameraStream");
    img.src = "/video_feed?t=" + new Date().getTime();
    document.getElementById("cameraOfflineOverlay").classList.add("hidden");
}

function showCameraError(msg) {
    const overlay = document.getElementById("cameraOfflineOverlay");
    const errorDetails = document.getElementById("cameraErrorDetails");
    errorDetails.innerText = msg;
    overlay.classList.remove("hidden");
}

function escapeHtml(text) {
    if (!text) return "";
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

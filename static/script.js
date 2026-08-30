/**
 * TripMate AI - Frontend Client Controller
 * Handles session state, auto-restoration of previous plans from Postgres,
 * multi-agent progress animations, Markdown parsing, and Trip History Drawer.
 */

let currentThreadId = localStorage.getItem("travel_thread_id") || null;
let latestAnswerMarkdown = "";
let progressInterval = null;

// Initialize on page load: restore open plan & update history counter
document.addEventListener("DOMContentLoaded", () => {
    updateThreadDisplay();
    updateHistoryCountBadge();
    
    // Automatically restore the previously active trip plan if available
    if (currentThreadId) {
        restoreSessionFromDatabase(currentThreadId, false);
    }
});

function updateThreadDisplay() {
    const threadBadge = document.getElementById("threadBadge");
    const threadBadgeText = document.getElementById("threadBadgeText");
    const threadInfo = document.getElementById("threadInfo");

    if (currentThreadId) {
        if (threadBadge) threadBadge.classList.remove("hidden");
        if (threadBadgeText) threadBadgeText.textContent = `Thread: ${currentThreadId.slice(0, 10)}...`;
        if (threadInfo) threadInfo.textContent = `Session ID: ${currentThreadId}`;
    } else {
        if (threadBadge) threadBadge.classList.add("hidden");
        if (threadInfo) threadInfo.textContent = "Session ID: New";
    }
}

// ==============================================================================
// 1. SESSION RESTORATION (DATABASE FETCH)
// ==============================================================================

async function restoreSessionFromDatabase(threadId, showToastNotification = true) {
    if (!threadId) return;

    try {
        const response = await fetch(`/api/travel/session/${threadId}`);
        const data = await response.json();

        if (response.ok && data.success && data.answer) {
            currentThreadId = threadId;
            localStorage.setItem("travel_thread_id", threadId);
            
            // Populate user query in input if empty
            const input = document.getElementById("userInput");
            if (input && data.user_query && !input.value) {
                input.value = data.user_query;
            }

            showResult(data.answer, data.thread_id, false);
            updateThreadDisplay();

            if (showToastNotification) {
                showToast("📖 Restored trip plan from database!");
            }
        }
    } catch (err) {
        console.warn("Could not restore session from database:", err);
    }
}

// ==============================================================================
// 2. TRIP HISTORY DRAWER MANAGEMENT
// ==============================================================================

function getHistoryList() {
    try {
        return JSON.parse(localStorage.getItem("travel_history_sessions") || "[]");
    } catch (e) {
        return [];
    }
}

function saveTripToHistory(threadId, userQuery) {
    if (!threadId) return;

    let history = getHistoryList();
    
    // Remove if already exists to bring to top
    history = history.filter(item => item.thread_id !== threadId);

    const title = userQuery.length > 55 ? userQuery.slice(0, 52) + "..." : userQuery;
    
    history.unshift({
        thread_id: threadId,
        title: title || "Custom Travel Plan",
        timestamp: new Date().toISOString()
    });

    // Keep up to 25 recent trips
    if (history.length > 25) {
        history = history.slice(0, 25);
    }

    localStorage.setItem("travel_history_sessions", JSON.stringify(history));
    updateHistoryCountBadge();
}

function updateHistoryCountBadge() {
    const badge = document.getElementById("historyCountBadge");
    if (!badge) return;

    const history = getHistoryList();
    if (history.length > 0) {
        badge.textContent = history.length;
        badge.classList.remove("hidden");
    } else {
        badge.classList.add("hidden");
    }
}

function openHistoryDrawer() {
    const drawer = document.getElementById("historyDrawer");
    const overlay = document.getElementById("historyOverlay");

    renderHistoryList();

    if (drawer) drawer.classList.remove("hidden");
    if (overlay) overlay.classList.remove("hidden");
}

function closeHistoryDrawer() {
    const drawer = document.getElementById("historyDrawer");
    const overlay = document.getElementById("historyOverlay");

    if (drawer) drawer.classList.add("hidden");
    if (overlay) overlay.classList.add("hidden");
}

function renderHistoryList() {
    const historyContainer = document.getElementById("historyList");
    if (!historyContainer) return;

    const history = getHistoryList();

    if (history.length === 0) {
        historyContainer.innerHTML = `
            <div class="history-empty">
                <p>✈️ No saved trip plans yet.</p>
                <p style="font-size: 0.82rem; margin-top: 6px;">Generated itineraries will automatically appear here.</p>
            </div>
        `;
        return;
    }

    historyContainer.innerHTML = history.map(item => {
        const dateStr = new Date(item.timestamp).toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric'
        });
        const isActive = item.thread_id === currentThreadId;

        return `
            <div class="history-card ${isActive ? 'active-session' : ''}" onclick="selectHistoryTrip('${item.thread_id}')">
                <div class="history-card-content">
                    <div class="history-card-title">${escapeHtml(item.title)}</div>
                    <div class="history-card-meta">
                        <span>📅 ${dateStr}</span>
                        <span>•</span>
                        <span>${isActive ? '🟢 Active' : 'Session: ' + item.thread_id.slice(0, 8)}</span>
                    </div>
                </div>
                <button class="history-card-delete" onclick="deleteHistoryTrip('${item.thread_id}', event)" title="Delete trip">
                    ✕
                </button>
            </div>
        `;
    }).join('');
}

function selectHistoryTrip(threadId) {
    closeHistoryDrawer();
    restoreSessionFromDatabase(threadId, true);
}

function deleteHistoryTrip(threadId, event) {
    if (event) event.stopPropagation();

    let history = getHistoryList();
    history = history.filter(item => item.thread_id !== threadId);
    localStorage.setItem("travel_history_sessions", JSON.stringify(history));

    if (currentThreadId === threadId) {
        resetSession();
    } else {
        updateHistoryCountBadge();
        renderHistoryList();
    }
    showToast("🗑️ Trip removed from history.");
}

function clearAllHistory() {
    if (!confirm("Are you sure you want to clear all saved trip history?")) {
        return;
    }

    localStorage.removeItem("travel_history_sessions");
    resetSession();
    closeHistoryDrawer();
    showToast("✨ Cleared all trip history.");
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

// ==============================================================================
// 3. ACTIONS & WORKFLOW
// ==============================================================================

function resetSession() {
    currentThreadId = null;
    localStorage.removeItem("travel_thread_id");
    updateThreadDisplay();
    clearInput();
    
    // Hide previous result & errors
    document.getElementById("resultSection").classList.add("hidden");
    hideError();
    showToast("✨ Started new travel planning session.");
}

function setPrompt(text) {
    const input = document.getElementById("userInput");
    input.value = text;
    input.focus();
    input.scrollIntoView({ behavior: "smooth", block: "center" });
}

function clearInput() {
    const input = document.getElementById("userInput");
    input.value = "";
    input.focus();
}

function showToast(message, duration = 3000) {
    const toast = document.getElementById("toast");
    if (!toast) return;

    toast.textContent = message;
    toast.classList.remove("hidden");

    setTimeout(() => {
        toast.classList.add("hidden");
    }, duration);
}

function startAgentProgress() {
    const agentProgress = document.getElementById("agentProgress");
    const liveStatusText = document.getElementById("liveStatusText");

    const steps = [
        { id: "step-flight", text: "✈️ Flight Agent: Scanning real-time routes & schedules..." },
        { id: "step-hotel", text: "🏨 Hotel Agent: Discovering top accommodations via Tavily..." },
        { id: "step-itinerary", text: "🗺️ Itinerary Agent: Synthesizing day-by-day travel plan..." },
        { id: "step-final", text: "✨ Final Synthesizer: Polishing recommendations & budget..." }
    ];

    agentProgress.classList.remove("hidden");

    steps.forEach((s) => {
        const el = document.getElementById(s.id);
        if (el) {
            el.classList.remove("active", "completed");
        }
    });

    function updateStep(index) {
        if (index >= steps.length) return;

        steps.forEach((s, idx) => {
            const el = document.getElementById(s.id);
            if (!el) return;

            if (idx < index) {
                el.classList.remove("active");
                el.classList.add("completed");
            } else if (idx === index) {
                el.classList.add("active");
                el.classList.remove("completed");
            } else {
                el.classList.remove("active", "completed");
            }
        });

        if (liveStatusText) {
            liveStatusText.textContent = steps[index].text;
        }
    }

    updateStep(0);

    let elapsed = 0;
    progressInterval = setInterval(() => {
        elapsed += 1;
        if (elapsed === 3) updateStep(1);
        else if (elapsed === 6) updateStep(2);
        else if (elapsed === 9) updateStep(3);
    }, 1000);
}

function stopAgentProgress() {
    if (progressInterval) {
        clearInterval(progressInterval);
        progressInterval = null;
    }

    const agentProgress = document.getElementById("agentProgress");
    if (agentProgress) {
        agentProgress.classList.add("hidden");
    }
}

function setLoading(isLoading) {
    const sendBtn = document.getElementById("sendBtn");
    const btnText = document.getElementById("btnText");
    const btnLoader = document.getElementById("btnLoader");

    sendBtn.disabled = isLoading;

    if (isLoading) {
        btnText.classList.add("hidden");
        btnLoader.classList.remove("hidden");
        startAgentProgress();
    } else {
        btnText.classList.remove("hidden");
        btnLoader.classList.add("hidden");
        stopAgentProgress();
    }
}

function showError(message) {
    const errorBox = document.getElementById("errorBox");
    const errorMessage = document.getElementById("errorMessage");

    if (errorMessage) {
        errorMessage.textContent = message;
    } else {
        errorBox.textContent = message;
    }

    errorBox.classList.remove("hidden");
    errorBox.scrollIntoView({ behavior: "smooth", block: "center" });
}

function hideError() {
    const errorBox = document.getElementById("errorBox");
    errorBox.classList.add("hidden");
}

function showResult(answer, threadId, shouldScroll = true) {
    latestAnswerMarkdown = answer;

    const resultSection = document.getElementById("resultSection");
    const resultBox = document.getElementById("resultBox");
    const pdfMetaDate = document.getElementById("pdfMetaDate");

    if (pdfMetaDate) {
        pdfMetaDate.textContent = `Generated: ${new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}`;
    }

    if (typeof marked !== "undefined") {
        resultBox.innerHTML = marked.parse(answer);
    } else {
        resultBox.innerText = answer;
    }

    updateThreadDisplay();

    resultSection.classList.remove("hidden");
    
    if (shouldScroll) {
        resultSection.scrollIntoView({
            behavior: "smooth",
            block: "start",
        });
    }
}

async function sendMessage() {
    hideError();

    const input = document.getElementById("userInput");
    const message = input.value.trim();

    if (!message) {
        showError("Please enter your destination or travel requirements first.");
        return;
    }

    setLoading(true);

    try {
        const response = await fetch("/api/travel", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                message: message,
                thread_id: currentThreadId,
            }),
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(
                data.error || "Failed to generate travel plan. Please check server logs."
            );
        }

        currentThreadId = data.thread_id;
        localStorage.setItem("travel_thread_id", currentThreadId);

        // Save to past trips history
        saveTripToHistory(currentThreadId, message);

        showResult(data.answer, data.thread_id, true);
    } catch (error) {
        showError(error.message);
    } finally {
        setLoading(false);
    }
}

function copyResult() {
    if (!latestAnswerMarkdown) {
        showError("No travel plan available to copy.");
        return;
    }

    navigator.clipboard
        .writeText(latestAnswerMarkdown)
        .then(() => {
            const copyBtnText = document.getElementById("copyBtnText");
            const oldText = copyBtnText ? copyBtnText.textContent : "Copy Markdown";

            if (copyBtnText) copyBtnText.textContent = "Copied!";
            showToast("📋 Markdown copied to clipboard!");

            setTimeout(() => {
                if (copyBtnText) copyBtnText.textContent = oldText;
            }, 1800);
        })
        .catch(() => {
            showError("Could not copy result to clipboard.");
        });
}

function downloadPDF() {
    const pdfContent = document.getElementById("pdfContent");

    if (!latestAnswerMarkdown || !pdfContent) {
        showError("No travel plan available to download.");
        return;
    }

    const downloadBtnText = document.getElementById("downloadBtnText");
    const oldText = downloadBtnText ? downloadBtnText.textContent : "Download PDF";

    if (downloadBtnText) downloadBtnText.textContent = "Preparing PDF...";

    const options = {
        margin: [0.4, 0.5, 0.4, 0.5],
        filename: `TripMate-Plan-${new Date().toISOString().slice(0, 10)}.pdf`,
        image: {
            type: "jpeg",
            quality: 0.98,
        },
        html2canvas: {
            scale: 2,
            useCORS: true,
            backgroundColor: "#ffffff",
        },
        jsPDF: {
            unit: "in",
            format: "a4",
            orientation: "portrait",
        },
        pagebreak: {
            mode: ["avoid-all", "css", "legacy"],
        },
    };

    html2pdf()
        .set(options)
        .from(pdfContent)
        .save()
        .then(() => {
            if (downloadBtnText) downloadBtnText.textContent = oldText;
            showToast("📄 PDF downloaded successfully!");
        })
        .catch(() => {
            if (downloadBtnText) downloadBtnText.textContent = oldText;
            showError("Could not generate PDF download.");
        });
}

// Keyboard Shortcut: Ctrl+Enter / Cmd+Enter to submit
document.addEventListener("keydown", function (event) {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        sendMessage();
    }
});


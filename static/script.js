/**
 * Voyagent AI - Frontend Client Controller
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
        if (threadBadgeText)
            threadBadgeText.textContent = `Thread: ${currentThreadId.slice(0, 10)}...`;
        if (threadInfo)
            threadInfo.textContent = `Session ID: ${currentThreadId}`;
    } else {
        if (threadBadge) threadBadge.classList.add("hidden");
        if (threadInfo) threadInfo.textContent = "Session ID: New";
    }
}

// ==============================================================================
// 1. SESSION RESTORATION (DATABASE FETCH)
// ==============================================================================

async function restoreSessionFromDatabase(
    threadId,
    showToastNotification = true,
) {
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

            // Ensure this trip is recorded in our local history list
            if (data.user_query) {
                saveTripToHistory(threadId, data.user_query, false);
            }

            showResult(data.answer, data.thread_id, false, data);
            updateThreadDisplay();

            if (showToastNotification) {
                showToast("Restored trip plan from database.");
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
        return JSON.parse(
            localStorage.getItem("travel_history_sessions") || "[]",
        );
    } catch (e) {
        return [];
    }
}

function saveTripToHistory(threadId, userQuery, updateBadge = true) {
    if (!threadId || !userQuery) return;

    let history = getHistoryList();

    // Remove existing item with same thread_id to bring it to the top
    history = history.filter((item) => item.thread_id !== threadId);

    const title =
        userQuery.length > 60 ? userQuery.slice(0, 57) + "..." : userQuery;

    history.unshift({
        thread_id: threadId,
        title: title || "Custom Travel Plan",
        timestamp: new Date().toISOString(),
    });

    // Limit to 30 recent trips
    if (history.length > 30) {
        history = history.slice(0, 30);
    }

    localStorage.setItem("travel_history_sessions", JSON.stringify(history));

    if (updateBadge) {
        updateHistoryCountBadge();
    }
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
                <p style="font-size: 1.5rem; margin-bottom: 8px;">🗺️</p>
                <p><strong>No saved trips yet</strong></p>
                <p style="font-size: 0.82rem; margin-top: 6px; color: #64748b;">
                    When you generate an itinerary, it will be automatically saved here.
                </p>
            </div>
        `;
        return;
    }

    historyContainer.innerHTML = history
        .map((item) => {
            const dateStr = new Date(item.timestamp).toLocaleDateString(
                "en-US",
                {
                    month: "short",
                    day: "numeric",
                    year: "numeric",
                },
            );
            const isActive = item.thread_id === currentThreadId;

            return `
            <div class="history-card ${isActive ? "active-session" : ""}" onclick="selectHistoryTrip('${item.thread_id}')">
                <div class="history-card-content">
                    <div class="history-card-title">${escapeHtml(item.title)}</div>
                    <div class="history-card-meta">
                        <span>📅 ${dateStr}</span>
                        <span>•</span>
                        <span style="${isActive ? "color: #86efac; font-weight: 700;" : ""}">
                            ${isActive ? "🟢 Active Plan" : "Session: " + item.thread_id.slice(0, 8)}
                        </span>
                    </div>
                </div>
                <button class="history-card-delete" onclick="deleteHistoryTrip('${item.thread_id}', event)" title="Delete from history">
                    ✕
                </button>
            </div>
        `;
        })
        .join("");
}

function selectHistoryTrip(threadId) {
    closeHistoryDrawer();
    restoreSessionFromDatabase(threadId, true);
}

function deleteHistoryTrip(threadId, event) {
    if (event) event.stopPropagation();

    let history = getHistoryList();
    history = history.filter((item) => item.thread_id !== threadId);
    localStorage.setItem("travel_history_sessions", JSON.stringify(history));

    updateHistoryCountBadge();
    renderHistoryList();

    if (currentThreadId === threadId) {
        currentThreadId = null;
        localStorage.removeItem("travel_thread_id");
        updateThreadDisplay();
        document.getElementById("resultSection").classList.add("hidden");
    }

    showToast("Trip removed from history.");
}

function clearAllHistory() {
    if (!confirm("Are you sure you want to clear all saved trip history?")) {
        return;
    }

    localStorage.removeItem("travel_history_sessions");
    currentThreadId = null;
    localStorage.removeItem("travel_thread_id");
    updateThreadDisplay();
    updateHistoryCountBadge();
    document.getElementById("resultSection").classList.add("hidden");
    clearInput();
    closeHistoryDrawer();
    showToast("Cleared all trip history.");
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
    // Start a new session without deleting history
    currentThreadId = null;
    localStorage.removeItem("travel_thread_id");
    updateThreadDisplay();
    clearInput();

    // Hide active result & errors on main view
    document.getElementById("resultSection").classList.add("hidden");
    hideError();
    showToast("Ready for a new trip. Past plans remain in Trip History.");
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
        {
            id: "step-flight",
            text: "Flight Agent: Scanning routes and schedules via AviationStack MCP...",
        },
        {
            id: "step-hotel",
            text: "Hotel Agent: Discovering accommodations via Tavily MCP...",
        },
        {
            id: "step-weather",
            text: "Weather Agent: Querying conditions and forecast via FastMCP...",
        },
        {
            id: "step-budget",
            text: "Budget Agent: Analyzing expenses, price categories and feasibility...",
        },
        {
            id: "step-itinerary",
            text: "Itinerary Agent: Synthesizing day-by-day itinerary...",
        },
        {
            id: "step-review",
            text: "Human Review: Preparing draft itinerary for user review...",
        },
        {
            id: "step-final",
            text: "Final Synthesizer: Finalizing recommendations, packing and budget...",
        },
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
        if (elapsed === 2) updateStep(1);
        else if (elapsed === 4) updateStep(2);
        else if (elapsed === 6) updateStep(3);
        else if (elapsed === 8) updateStep(4);
        else if (elapsed === 10) updateStep(5);
        else if (elapsed === 12) updateStep(6);
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

function showResult(answer, threadId, shouldScroll = true, resultData = null) {
    latestAnswerMarkdown = answer;

    const resultSection = document.getElementById("resultSection");
    const resultBox = document.getElementById("resultBox");
    const pdfMetaDate = document.getElementById("pdfMetaDate");
    const approvalBanner = document.getElementById("approvalBanner");
    const approvalDescription = document.getElementById("approvalDescription");

    if (pdfMetaDate) {
        pdfMetaDate.textContent = `Generated: ${new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}`;
    }

    if (typeof marked !== "undefined") {
        resultBox.innerHTML = marked.parse(answer);
    } else {
        resultBox.innerText = answer;
    }

    // Check if the plan is paused waiting for human review / approval
    if (resultData && resultData.requires_approval) {
        if (approvalBanner) {
            approvalBanner.classList.remove("hidden");
            if (approvalDescription && resultData.approval_request) {
                approvalDescription.textContent = resultData.approval_request;
            }
        }
    } else {
        if (approvalBanner) {
            approvalBanner.classList.add("hidden");
        }
    }

    updateThreadDisplay();
    updateHistoryCountBadge();

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
        showError(
            "Please enter your destination or travel requirements first.",
        );
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
                data.error ||
                    "Failed to generate travel plan. Please check server logs.",
            );
        }

        currentThreadId = data.thread_id;
        localStorage.setItem("travel_thread_id", currentThreadId);

        // Immediately record into history list
        saveTripToHistory(currentThreadId, message);

        showResult(data.answer, data.thread_id, true, data);
    } catch (error) {
        showError(error.message);
    } finally {
        setLoading(false);
    }
}

async function submitApproval(approved) {
    hideError();

    if (!currentThreadId) {
        showError("No active session thread to resume.");
        return;
    }

    const feedbackInput = document.getElementById("feedbackInput");
    const feedback = feedbackInput ? feedbackInput.value.trim() : "";

    const approveBtn = document.getElementById("approveBtn");
    const reviseBtn = document.getElementById("reviseBtn");
    const approveBtnText = document.getElementById("approveBtnText");
    const reviseBtnText = document.getElementById("reviseBtnText");
    const approveBtnLoader = document.getElementById("approveBtnLoader");
    const reviseBtnLoader = document.getElementById("reviseBtnLoader");

    if (approved) {
        if (approveBtn) approveBtn.disabled = true;
        if (approveBtnText) approveBtnText.classList.add("hidden");
        if (approveBtnLoader) approveBtnLoader.classList.remove("hidden");
    } else {
        if (reviseBtn) reviseBtn.disabled = true;
        if (reviseBtnText) reviseBtnText.classList.add("hidden");
        if (reviseBtnLoader) reviseBtnLoader.classList.remove("hidden");
    }

    const liveStatusText = document.getElementById("liveStatusText");
    const agentProgress = document.getElementById("agentProgress");
    if (agentProgress && liveStatusText) {
        agentProgress.classList.remove("hidden");
        liveStatusText.textContent = approved
            ? "Final Synthesizer: Polishing approved itinerary..."
            : "Revision Agent: Applying your feedback to draft...";
        const stepFinal = document.getElementById("step-final");
        const stepReview = document.getElementById("step-review");
        if (approved) {
            if (stepReview) {
                stepReview.classList.remove("active");
                stepReview.classList.add("completed");
            }
            if (stepFinal) stepFinal.classList.add("active");
        } else {
            if (stepReview) {
                stepReview.classList.add("active");
                stepReview.classList.remove("completed");
            }
            if (stepFinal) stepFinal.classList.remove("active");
        }
    }

    try {
        const response = await fetch("/api/travel/resume", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                thread_id: currentThreadId,
                approved: approved,
                feedback: feedback,
            }),
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(
                data.error ||
                    "Failed to resume travel plan. Please check server logs.",
            );
        }

        showResult(data.answer, data.thread_id, true, data);
        showToast(
            approved
                ? "Itinerary approved and finalized."
                : "Draft updated with your revisions. Please review.",
        );
        if (feedbackInput) feedbackInput.value = "";
    } catch (error) {
        showError(error.message);
    } finally {
        if (approveBtn) approveBtn.disabled = false;
        if (approveBtnText) approveBtnText.classList.remove("hidden");
        if (approveBtnLoader) approveBtnLoader.classList.add("hidden");

        if (reviseBtn) reviseBtn.disabled = false;
        if (reviseBtnText) reviseBtnText.classList.remove("hidden");
        if (reviseBtnLoader) reviseBtnLoader.classList.add("hidden");

        stopAgentProgress();
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
            const oldText = copyBtnText
                ? copyBtnText.textContent
                : "Copy Markdown";

            if (copyBtnText) copyBtnText.textContent = "Copied!";
            showToast("Markdown copied to clipboard.");

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
    const oldText = downloadBtnText
        ? downloadBtnText.textContent
        : "Download PDF";

    if (downloadBtnText) downloadBtnText.textContent = "Preparing PDF...";

    const options = {
        margin: [0.4, 0.5, 0.4, 0.5],
        filename: `Voyagent-Plan-${new Date().toISOString().slice(0, 10)}.pdf`,
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
            showToast("PDF downloaded successfully.");
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

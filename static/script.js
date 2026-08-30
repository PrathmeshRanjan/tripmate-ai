/**
 * TripMate AI - Frontend Client Controller
 * Handles session state, asynchronous agent execution, multi-agent progress animations,
 * Markdown parsing, and PDF report generation.
 */

let currentThreadId = localStorage.getItem("travel_thread_id") || null;
let latestAnswerMarkdown = "";
let progressInterval = null;

// Initialize session state on page load
document.addEventListener("DOMContentLoaded", () => {
    updateThreadDisplay();
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
    // Smoothly scroll to input if on mobile
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

    // Reset step styles
    steps.forEach(s => {
        const el = document.getElementById(s.id);
        if (el) {
            el.classList.remove("active", "completed");
        }
    });

    let currentStepIndex = 0;

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

    // Increment agent steps based on typical latency
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

function showResult(answer, threadId) {
    latestAnswerMarkdown = answer;

    const resultSection = document.getElementById("resultSection");
    const resultBox = document.getElementById("resultBox");
    const pdfMetaDate = document.getElementById("pdfMetaDate");

    if (pdfMetaDate) {
        pdfMetaDate.textContent = `Generated: ${new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;
    }

    if (typeof marked !== "undefined") {
        resultBox.innerHTML = marked.parse(answer);
    } else {
        resultBox.innerText = answer;
    }

    updateThreadDisplay();

    resultSection.classList.remove("hidden");
    resultSection.scrollIntoView({
        behavior: "smooth",
        block: "start"
    });
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
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                message: message,
                thread_id: currentThreadId
            })
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.error || "Failed to generate travel plan. Please check server logs.");
        }

        currentThreadId = data.thread_id;
        localStorage.setItem("travel_thread_id", currentThreadId);

        showResult(data.answer, data.thread_id);

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

    navigator.clipboard.writeText(latestAnswerMarkdown)
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
            quality: 0.98
        },
        html2canvas: {
            scale: 2,
            useCORS: true,
            backgroundColor: "#ffffff"
        },
        jsPDF: {
            unit: "in",
            format: "a4",
            orientation: "portrait"
        },
        pagebreak: {
            mode: ["avoid-all", "css", "legacy"]
        }
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
document.addEventListener("keydown", function(event) {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        sendMessage();
    }
});
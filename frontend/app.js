// Vanilla JS, no build step - talks to PulseQueue's own API, same origin.
// See docs/api.md for the endpoints this calls.

const STATUSES = ["queued", "running", "succeeded", "failed", "cancelled", "dead_letter"];

const TASK_TYPE_EXAMPLES = {
  generateReport: { reportName: "weekly-performance", periodDays: 7 },
  calculateMetrics: { metricName: "latency_ms", values: [12.5, 9.8, 15.1] },
  processFile: { fileName: "report.txt" },
  sendNotification: { recipientName: "Hema C", message: "Your report is ready." },
  simulateFailure: { failUntilAttempt: 2 },
};

const taskTypeSelect = document.getElementById("taskType");
const payloadInput = document.getElementById("payload");
const maxAttemptsInput = document.getElementById("maxAttempts");
const submitForm = document.getElementById("submitForm");
const submitResult = document.getElementById("submitResult");
const statCards = document.getElementById("statCards");
const taskRows = document.getElementById("taskRows");
const taskCount = document.getElementById("taskCount");
const healthDot = document.getElementById("healthDot");
const healthText = document.getElementById("healthText");
const detailBackdrop = document.getElementById("detailBackdrop");
const detailBody = document.getElementById("detailBody");
const detailClose = document.getElementById("detailClose");
const deadLettersToggle = document.getElementById("deadLettersToggle");
const deadLettersBody = document.getElementById("deadLettersBody");
const deadLetterForm = document.getElementById("deadLetterForm");
const deadLetterRows = document.getElementById("deadLetterRows");
const deadLetterError = document.getElementById("deadLetterError");
const adminTokenInput = document.getElementById("adminToken");

function initTaskTypeOptions() {
  for (const type of Object.keys(TASK_TYPE_EXAMPLES)) {
    const option = document.createElement("option");
    option.value = type;
    option.textContent = type;
    taskTypeSelect.appendChild(option);
  }
  updatePayloadExample();
}

function updatePayloadExample() {
  const example = TASK_TYPE_EXAMPLES[taskTypeSelect.value];
  payloadInput.value = JSON.stringify(example, null, 2);
}

taskTypeSelect.addEventListener("change", updatePayloadExample);

async function pollHealth() {
  try {
    const response = await fetch("/health/ready");
    const body = await response.json();
    const ready = response.ok && body.status === "ready";
    healthDot.className = "dot " + (ready ? "dot-ok" : "dot-bad");
    healthText.textContent = ready
      ? "ready"
      : `degraded (db: ${body.database ?? "?"}, redis: ${body.redis ?? "?"})`;
  } catch {
    healthDot.className = "dot dot-bad";
    healthText.textContent = "unreachable";
  }
}

function renderStatCards(depthByStatus) {
  statCards.innerHTML = "";
  for (const status of STATUSES) {
    const card = document.createElement("div");
    card.className = "stat-card";
    const value = depthByStatus[status] ?? 0;
    card.innerHTML = `<div class="value">${value}</div><div class="label">${status.replace("_", " ")}</div>`;
    statCards.appendChild(card);
  }
}

// /metrics is Prometheus text exposition format - this pulls out just the
// queue-depth gauge lines rather than pulling in a parsing library for one
// metric family.
function parseQueueDepth(metricsText) {
  const depthByStatus = {};
  const pattern = /^pulsequeue_queue_depth\{status="([a-z_]+)"\}\s+([\d.]+)/gm;
  let match;
  while ((match = pattern.exec(metricsText)) !== null) {
    depthByStatus[match[1]] = Number(match[2]);
  }
  return depthByStatus;
}

async function pollMetrics() {
  try {
    const response = await fetch("/metrics");
    const text = await response.text();
    renderStatCards(parseQueueDepth(text));
  } catch {
    // Metrics are a nice-to-have on this dashboard; a failed fetch here
    // shouldn't block the rest of the page from working.
  }
}

function statusBadge(status) {
  return `<span class="badge badge-${status}">${status.replace("_", " ")}</span>`;
}

function shortId(uuid) {
  return uuid.slice(0, 8);
}

function formatTime(iso) {
  if (!iso) return "–";
  return new Date(iso).toLocaleTimeString();
}

let latestTasks = [];

async function pollTasks() {
  try {
    const response = await fetch("/api/v1/tasks?limit=20");
    if (!response.ok) return;
    const body = await response.json();
    latestTasks = body.tasks;
    taskCount.textContent = `(${body.tasks.length} shown)`;
    taskRows.innerHTML = body.tasks
      .map(
        (task, index) => `
      <tr data-index="${index}">
        <td class="mono">${shortId(task.taskId)}</td>
        <td>${task.taskType}</td>
        <td>${statusBadge(task.status)}</td>
        <td>${task.attemptCount}/${task.maxAttempts}</td>
        <td>${formatTime(task.updatedAt)}</td>
      </tr>`
      )
      .join("");
  } catch {
    // Keep showing the last good render rather than clearing the table.
  }
}

taskRows.addEventListener("click", (event) => {
  const row = event.target.closest("tr");
  if (!row) return;
  const task = latestTasks[Number(row.dataset.index)];
  if (!task) return;
  detailBody.textContent = JSON.stringify(task, null, 2);
  detailBackdrop.classList.remove("hidden");
});

detailClose.addEventListener("click", () => detailBackdrop.classList.add("hidden"));
detailBackdrop.addEventListener("click", (event) => {
  if (event.target === detailBackdrop) detailBackdrop.classList.add("hidden");
});

submitForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  submitResult.textContent = "";
  submitResult.className = "result";

  let payload;
  try {
    payload = JSON.parse(payloadInput.value);
  } catch {
    submitResult.textContent = "Payload is not valid JSON.";
    submitResult.className = "result error";
    return;
  }

  const body = { taskType: taskTypeSelect.value, payload };
  if (maxAttemptsInput.value) {
    body.maxAttempts = Number(maxAttemptsInput.value);
  }

  try {
    const response = await fetch("/api/v1/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const responseBody = await response.json();
    if (response.ok) {
      submitResult.textContent = `Submitted - ${responseBody.taskId} (${responseBody.status})`;
      submitResult.className = "result success";
      pollTasks();
    } else {
      submitResult.textContent = responseBody.error?.message ?? "Submission failed.";
      submitResult.className = "result error";
    }
  } catch {
    submitResult.textContent = "Could not reach the API.";
    submitResult.className = "result error";
  }
});

deadLettersToggle.addEventListener("click", () => {
  deadLettersToggle.classList.toggle("open");
  deadLettersBody.classList.toggle("hidden");
});

async function loadDeadLetters() {
  deadLetterError.textContent = "";
  deadLetterError.className = "result";
  const token = adminTokenInput.value;
  try {
    const response = await fetch("/api/v1/dead-letters", {
      headers: { "X-Admin-Token": token },
    });
    const body = await response.json();
    if (!response.ok) {
      deadLetterError.textContent = body.error?.message ?? "Request failed.";
      deadLetterError.className = "result error";
      deadLetterRows.innerHTML = "";
      return;
    }
    deadLetterRows.innerHTML = body.tasks
      .map(
        (task) => `
      <tr>
        <td class="mono">${shortId(task.taskId)}</td>
        <td>${task.taskType}</td>
        <td>${task.attemptCount}/${task.maxAttempts}</td>
        <td class="mono">${task.lastErrorCode ?? "–"}</td>
        <td><button type="button" data-requeue="${task.taskId}">Requeue</button></td>
      </tr>`
      )
      .join("");
  } catch {
    deadLetterError.textContent = "Could not reach the API.";
    deadLetterError.className = "result error";
  }
}

deadLetterForm.addEventListener("submit", (event) => {
  event.preventDefault();
  loadDeadLetters();
});

deadLetterRows.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-requeue]");
  if (!button) return;
  const taskId = button.dataset.requeue;
  button.disabled = true;
  try {
    const response = await fetch(`/api/v1/dead-letters/${taskId}/requeue`, {
      method: "POST",
      headers: { "X-Admin-Token": adminTokenInput.value },
    });
    if (response.ok) {
      loadDeadLetters();
      pollTasks();
    } else {
      button.disabled = false;
    }
  } catch {
    button.disabled = false;
  }
});

initTaskTypeOptions();
pollHealth();
pollMetrics();
pollTasks();
setInterval(pollHealth, 5000);
setInterval(pollMetrics, 3000);
setInterval(pollTasks, 2000);

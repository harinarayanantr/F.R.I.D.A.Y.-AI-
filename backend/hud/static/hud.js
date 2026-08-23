const logEl = document.getElementById("log");
const statusText = document.getElementById("statusText");
const statusPill = document.getElementById("statusPill");
const camFeed = document.getElementById("camFeed");
const esp32Cards = document.getElementById("esp32Cards");
const clockEl = document.getElementById("clock");
const waveCanvas = document.getElementById("wave");
const waveCtx = waveCanvas.getContext("2d");

const ringOuter = document.getElementById("ringOuter");
const ringMid = document.getElementById("ringMid");
const ringInner = document.getElementById("ringInner");

function setRingOffsets(fraction) {
  // fraction 0..1 of the ring "filled"
  const c1 = 2 * Math.PI * 270, c2 = 2 * Math.PI * 215, c3 = 2 * Math.PI * 160;
  ringOuter.style.strokeDasharray = c1;
  ringOuter.style.strokeDashoffset = c1 * (1 - fraction);
  ringMid.style.strokeDasharray = c2;
  ringMid.style.strokeDashoffset = c2 * (1 - fraction);
  ringInner.style.strokeDasharray = c3;
  ringInner.style.strokeDashoffset = c3 * (1 - fraction);
}
setRingOffsets(0.78);

function addLog(evt) {
  const line = document.createElement("div");
  line.className = "line lvl-" + (evt.level || "info");
  const t = new Date((evt.ts || Date.now() / 1000) * 1000).toLocaleTimeString();
  line.innerHTML = `<span class="ts">${t}</span><span class="chan">[${(evt.channel || "sys").toUpperCase()}]</span>${escapeHtml(evt.message || "")}`;
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
  while (logEl.children.length > 300) logEl.removeChild(logEl.firstChild);
}

function escapeHtml(s) {
  return s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

function setStatus(status) {
  statusText.textContent = status.toUpperCase();
  statusPill.style.borderColor =
    status === "listening" ? "var(--cyan)" : status === "speaking" ? "#ff5a5a" : "var(--orange)";
}

function upsertEsp32Cards(data) {
  if (!data || Object.keys(data).length === 0) return;
  esp32Cards.innerHTML = "";
  for (const [pin, info] of Object.entries(data)) {
    const card = document.createElement("div");
    card.className = "esp32-card";
    const name = info.name || `Pin ${pin}`;
    card.innerHTML = `<span><b>${escapeHtml(name)}</b> (pin ${pin})</span><span>${escapeHtml(String(info.value))}</span>`;
    esp32Cards.appendChild(card);
  }
}

// --- fake ambient waveform when idle, "active" look when listening/speaking ---
let waveMode = "idle";
function drawWave() {
  const w = waveCanvas.width, h = waveCanvas.height;
  waveCtx.clearRect(0, 0, w, h);
  waveCtx.strokeStyle = waveMode === "speaking" ? "#ff5a5a" : waveMode === "listening" ? "#22d3c8" : "rgba(255,140,26,0.35)";
  waveCtx.lineWidth = 2;
  waveCtx.beginPath();
  const amp = waveMode === "idle" ? 4 : 22;
  const speed = waveMode === "idle" ? 0.002 : 0.01;
  for (let x = 0; x < w; x++) {
    const y = h / 2 + Math.sin(x * 0.05 + Date.now() * speed) * amp * Math.sin(x / w * Math.PI);
    x === 0 ? waveCtx.moveTo(x, y) : waveCtx.lineTo(x, y);
  }
  waveCtx.stroke();
  requestAnimationFrame(drawWave);
}
drawWave();

// --- websocket ---
let ws = null; // kept module-level so approval responses can be sent anywhere

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (msg) => {
    const evt = JSON.parse(msg.data);
    if (evt.type === "log") addLog(evt);
    else if (evt.type === "status") {
      setStatus(evt.status);
      waveMode = evt.status;
    } else if (evt.type === "camera_frame") {
      camFeed.src = "data:image/jpeg;base64," + evt.jpeg_b64;
    } else if (evt.type === "esp32_status") {
      upsertEsp32Cards(evt.data);
    } else if (evt.type === "gesture") {
      // subtle ring pulse on gesture detect
      setRingOffsets(0.5 + (evt.fingers || 0) * 0.08);
      setTimeout(() => setRingOffsets(0.78), 400);
    } else if (evt.type === "approval_request") {
      queueApprovalRequest(evt);
    }
  };
  ws.onclose = () => setTimeout(connect, 1500);
}
connect();

// --- text command form ---
document.getElementById("cmdForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("cmdInput");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  addLog({ level: "info", channel: "you", message: text });
  const res = await fetch("/api/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  const data = await res.json();
  addLog({ level: "info", channel: "friday", message: data.reply });
});

// --- clock ---
setInterval(() => {
  clockEl.textContent = new Date().toLocaleTimeString();
}, 1000);

// --- command approval modal ---
const approvalOverlay = document.getElementById("approvalOverlay");
const approvalDesc = document.getElementById("approvalDesc");
const approvalCmd = document.getElementById("approvalCmd");
const approvalTimer = document.getElementById("approvalTimer");
document.getElementById("approvalApproveBtn").addEventListener("click", () => respondApproval(true));
document.getElementById("approvalDenyBtn").addEventListener("click", () => respondApproval(false));

const approvalQueue = [];
let activeApproval = null; // { request_id, deadline, interval }

function queueApprovalRequest(evt) {
  addLog({ level: "warning", channel: "system", message: `Approval requested: ${evt.command}` });
  approvalQueue.push(evt);
  if (!activeApproval) showNextApproval();
}

function showNextApproval() {
  const evt = approvalQueue.shift();
  if (!evt) return;
  activeApproval = {
    request_id: evt.request_id,
    deadline: Date.now() + (evt.timeout || 60) * 1000,
    interval: null,
  };
  approvalDesc.textContent = evt.description || "FRIDAY wants to run a command.";
  approvalCmd.textContent = evt.command || "";
  approvalOverlay.hidden = false;

  const tick = () => {
    if (!activeApproval) return;
    const secs = Math.max(0, Math.ceil((activeApproval.deadline - Date.now()) / 1000));
    approvalTimer.textContent =
      secs > 0 ? `AUTO-DENY IN ${secs}s` : "AUTO-DENYING...";
    approvalTimer.classList.toggle("urgent", secs <= 10);
    if (secs <= 0) hideApprovalModal(); // server auto-rejects; nothing to send
  };
  tick();
  activeApproval.interval = setInterval(tick, 250);
}

function hideApprovalModal() {
  if (activeApproval && activeApproval.interval) clearInterval(activeApproval.interval);
  activeApproval = null;
  approvalOverlay.hidden = true;
  showNextApproval();
}

function respondApproval(approved) {
  if (!activeApproval) return;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: "approval_response",
      request_id: activeApproval.request_id,
      approved,
    }));
  }
  hideApprovalModal();
}

// Y / N / Escape shortcuts - only while the approval modal is on screen.
document.addEventListener("keydown", (e) => {
  if (approvalOverlay.hidden) return;
  if (e.key === "y" || e.key === "Y") respondApproval(true);
  else if (e.key === "n" || e.key === "N" || e.key === "Escape") respondApproval(false);
});

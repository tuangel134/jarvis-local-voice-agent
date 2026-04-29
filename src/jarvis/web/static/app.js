const body = document.body;
const canvas = document.getElementById('orbCanvas');
const ctx = canvas.getContext('2d', { alpha: true, desynchronized: true });
const statusChip = document.getElementById('statusChip');
const stateValueEl = document.getElementById('stateValue');
const modeValueEl = document.getElementById('modeValue');
const signalValueEl = document.getElementById('signalValue');
const micValueEl = document.getElementById('micValue');
const intentValueEl = document.getElementById('intentValue');
const actionValueEl = document.getElementById('actionValue');
const subtitleValueEl = document.getElementById('subtitleValue');
const micVisBtn = document.getElementById('micVisBtn');
const clearLogsBtn = document.getElementById('clearLogsBtn');
const logsWrap = document.getElementById('logsWrap');
const logsOutput = document.getElementById('logsOutput');

let ws = null;
let reconnectTimer = null;
let state = 'idle';
let intent = '—';
let action = '—';
let subtitle = 'Awaiting signal…';
let serverAmp = 0.0;
let liveAmp = 0.0;
let smoothAmp = 0.0;
let speakingHold = 0.0;
let lastFrameTs = performance.now();
let hidden = document.hidden;
let autoScroll = true;
let logs = [];
let micEnabled = false;
let micStream = null;
let micAudioCtx = null;
let micSource = null;
let micAnalyser = null;
let micData = null;
let micAmp = 0.0;
let micAmpSmooth = 0.0;
let dpr = Math.min(1.5, window.devicePixelRatio || 1);
let width = 0;
let height = 0;
let pointerX = 0;
let pointerY = 0;
let ptx = 0;
let pty = 0;
let particleSeed = [];

function clamp(v, a, b) { return Math.min(b, Math.max(a, v)); }
function ease(current, target, speed) { return current + (target - current) * speed; }

function setState(next) {
  state = next || 'idle';
  body.classList.remove('state-idle', 'state-listening', 'state-thinking', 'state-speaking');
  body.classList.add(`state-${state}`);
  statusChip.textContent = state.toUpperCase();
  stateValueEl.textContent = state;
  modeValueEl.textContent = state === 'idle' ? 'standby' : state;
}
function setIntent(text) { intentValueEl.textContent = (text && text.trim()) ? text.trim() : '—'; }
function setAction(text) { actionValueEl.textContent = (text && text.trim()) ? text.trim() : '—'; }
function setSubtitle(text) { subtitleValueEl.textContent = (text && text.trim()) ? text.trim() : 'Awaiting signal…'; }
function pushLogLine(line) {
  if (!line) return;
  logs.push(line);
  if (logs.length > 320) logs = logs.slice(-320);
  renderLogs();
}
function renderLogs() {
  const nearBottom = logsWrap.scrollHeight - logsWrap.scrollTop - logsWrap.clientHeight < 28;
  autoScroll = autoScroll || nearBottom;
  logsOutput.textContent = logs.join('\n');
  if (autoScroll) requestAnimationFrame(() => { logsWrap.scrollTop = logsWrap.scrollHeight; });
}
logsWrap.addEventListener('scroll', () => { autoScroll = logsWrap.scrollHeight - logsWrap.scrollTop - logsWrap.clientHeight < 28; });
clearLogsBtn.addEventListener('click', () => { logs = []; renderLogs(); });
async function loadStatus() {
  try {
    const res = await fetch('/api/status', { cache: 'no-store' });
    const data = await res.json();
    if (data?.state) setState(data.state);
    if (typeof data?.amp === 'number') serverAmp = data.amp;
    if (data?.intent) setIntent(data.intent);
    if (data?.action) setAction(data.action);
    if (data?.subtitle) setSubtitle(data.subtitle);
  } catch (_) {}
}
async function loadLogs() {
  try {
    const res = await fetch('/api/logs', { cache: 'no-store' });
    const data = await res.json();
    if (Array.isArray(data?.lines)) {
      logs = data.lines.slice(-220);
      renderLogs();
    }
  } catch (_) {}
}
function connectWS() {
  try { if (ws) ws.close(); } catch (_) {}
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${window.location.host}/ws`);
  ws.onopen = () => {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = null;
    try { ws.send(JSON.stringify({ type: 'ping' })); } catch (_) {}
  };
  ws.onmessage = (event) => {
    let msg = null;
    try { msg = JSON.parse(event.data); } catch (_) { return; }
    if (!msg) return;
    if (msg.type === 'hello') {
      if (msg.state) setState(msg.state);
      if (typeof msg.amp === 'number') serverAmp = msg.amp;
      if (msg.intent) setIntent(msg.intent);
      if (msg.action) setAction(msg.action);
      if (msg.subtitle) setSubtitle(msg.subtitle);
      if (Array.isArray(msg.logs)) { logs = msg.logs.slice(-220); renderLogs(); }
      return;
    }
    if (msg.type === 'state') { setState(msg.state); if (msg.state === 'speaking') speakingHold = Math.max(speakingHold, 1.45); return; }
    if (msg.type === 'audio_level') { serverAmp = clamp(Number(msg.level) || 0, 0, 1.25); if (serverAmp > 0.08) speakingHold = Math.max(speakingHold, 1.5); return; }
    if (msg.type === 'intent') { setIntent(msg.intent || msg.text || '—'); return; }
    if (msg.type === 'action') { setAction(msg.action || msg.text || '—'); return; }
    if (msg.type === 'subtitle') { setSubtitle(msg.subtitle || msg.text || ''); return; }
    if (msg.type === 'log') { pushLogLine(msg.text || ''); return; }
  };
  ws.onclose = () => { reconnectTimer = setTimeout(connectWS, 1000); };
}
async function toggleMicVisualization() {
  if (micEnabled) {
    micEnabled = false; micAmp = 0; micAmpSmooth = 0; micValueEl.textContent = 'off'; micVisBtn.textContent = 'MIC VIS OFF';
    if (micStream) micStream.getTracks().forEach((t) => t.stop());
    if (micAudioCtx) { try { await micAudioCtx.close(); } catch (_) {} }
    micStream = null; micAudioCtx = null; micSource = null; micAnalyser = null; micData = null; return;
  }
  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    micAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
    micSource = micAudioCtx.createMediaStreamSource(micStream);
    micAnalyser = micAudioCtx.createAnalyser();
    micAnalyser.fftSize = 512;
    micAnalyser.smoothingTimeConstant = 0.72;
    micData = new Uint8Array(micAnalyser.fftSize);
    micSource.connect(micAnalyser);
    micEnabled = true;
    micValueEl.textContent = 'live';
    micVisBtn.textContent = 'MIC VIS ON';
  } catch (err) {
    micEnabled = false; micValueEl.textContent = 'blocked'; pushLogLine(`[web] mic error: ${err?.message || err}`);
  }
}
micVisBtn.addEventListener('click', toggleMicVisualization);
document.addEventListener('visibilitychange', () => { hidden = document.hidden; });
window.addEventListener('pointermove', (e) => {
  const rect = canvas.getBoundingClientRect();
  const nx = ((e.clientX - rect.left) / Math.max(1, rect.width)) * 2 - 1;
  const ny = ((e.clientY - rect.top) / Math.max(1, rect.height)) * 2 - 1;
  pointerX = clamp(nx, -1, 1);
  pointerY = clamp(ny, -1, 1);
}, { passive: true });
function updateMicLevel() {
  if (!micEnabled || !micAnalyser || !micData) { micAmp = 0; return; }
  micAnalyser.getByteTimeDomainData(micData);
  let sum = 0;
  for (let i = 0; i < micData.length; i++) { const v = (micData[i] - 128) / 128; sum += v * v; }
  micAmp = clamp(Math.sqrt(sum / micData.length) * 3.6, 0, 1.2);
}
function resize() {
  dpr = Math.min(1.5, window.devicePixelRatio || 1);
  const rect = canvas.getBoundingClientRect();
  width = Math.max(1, Math.floor(rect.width * dpr));
  height = Math.max(1, Math.floor(rect.height * dpr));
  canvas.width = width; canvas.height = height; seedParticles();
}
let resizeTimer = null;
window.addEventListener('resize', () => { if (resizeTimer) cancelAnimationFrame(resizeTimer); resizeTimer = requestAnimationFrame(resize); }, { passive: true });
function seedParticles() {
  const count = Math.max(60, Math.min(120, Math.floor((width * height) / (9000 * dpr * dpr))));
  particleSeed = Array.from({ length: count }, (_, i) => ({ seed: i * 0.173 + Math.random() * 6.28, r: 0.22 + Math.random() * 0.92, size: 0.4 + Math.random() * 1.8, speed: 0.18 + Math.random() * 0.8, band: Math.random() > 0.5 ? 1 : -1, alpha: 0.12 + Math.random() * 0.55 }));
}
function drawArcField(cx, cy, rx, ry, t, energy, color, alphaBase, lineWidth, segments, phaseOffset, dash = false) {
  ctx.save(); ctx.strokeStyle = color; ctx.globalAlpha = alphaBase; ctx.lineWidth = lineWidth; if (dash) ctx.setLineDash([8 * dpr, 12 * dpr]);
  for (let i = 0; i < segments; i++) { const start = (i / segments) * Math.PI * 2 + t * (0.18 + i * 0.007) + phaseOffset; const span = 0.36 + Math.sin(t * 0.5 + i) * 0.12 + energy * 0.18; ctx.beginPath(); ctx.ellipse(cx, cy, rx, ry, start, start, start + span); ctx.stroke(); }
  ctx.restore();
}
function drawParticleShell(cx, cy, radius, t, energy) {
  ctx.save();
  for (const p of particleSeed) { const a = p.seed + t * p.speed * p.band; const bandWarp = 0.68 + 0.32 * Math.sin(t * 0.7 + p.seed * 1.7); const x = cx + Math.cos(a) * radius * p.r; const y = cy + Math.sin(a * 1.23 + p.seed) * radius * p.r * 0.55 * bandWarp; const glow = (0.65 + energy * 0.85) * p.alpha; ctx.beginPath(); ctx.fillStyle = `rgba(255, 191, 110, ${glow.toFixed(3)})`; ctx.arc(x, y, p.size * dpr * (0.8 + energy * 0.5), 0, Math.PI * 2); ctx.fill(); }
  ctx.restore();
}
function drawOrb(now) {
  const t = now * 0.001; const dt = Math.min(0.05, (now - lastFrameTs) / 1000); lastFrameTs = now;
  updateMicLevel(); ptx = ease(ptx, pointerX * 0.22, 0.06); pty = ease(pty, pointerY * 0.18, 0.06); micAmpSmooth = ease(micAmpSmooth, micAmp, 0.12);
  if (state === 'speaking' && serverAmp < 0.08) speakingHold = Math.max(speakingHold, 1.1); speakingHold = Math.max(0, speakingHold - dt);
  const baseStateEnergy = state === 'listening' ? 0.42 : state === 'thinking' ? 0.5 : state === 'speaking' ? 0.82 : 0.24;
  const holdEnergy = speakingHold > 0 ? 0.5 + Math.min(0.55, speakingHold * 0.28) : 0;
  const targetAmp = Math.max(baseStateEnergy, serverAmp * 0.92, micAmpSmooth * 0.9, holdEnergy);
  smoothAmp = ease(smoothAmp, targetAmp, hidden ? 0.05 : 0.09);
  signalValueEl.textContent = smoothAmp.toFixed(2);
  const w = width; const h = height; const cx = w * 0.5 + ptx * w * 0.03; const cy = h * 0.46 + pty * h * 0.028; const radius = Math.min(w, h) * 0.21; const energy = clamp(smoothAmp, 0, 1.35);
  ctx.setTransform(1,0,0,1,0,0); ctx.clearRect(0,0,w,h);
  ctx.fillStyle = 'rgba(2, 6, 11, 0.24)'; ctx.fillRect(0,0,w,h);
  const bgGrad = ctx.createRadialGradient(cx, cy, radius * 0.1, cx, cy, radius * 2.2);
  bgGrad.addColorStop(0, `rgba(255, 175, 70, ${0.07 + energy * 0.06})`); bgGrad.addColorStop(0.38, `rgba(73, 233, 255, ${0.04 + energy * 0.03})`); bgGrad.addColorStop(1, 'rgba(0,0,0,0)'); ctx.fillStyle = bgGrad; ctx.fillRect(0,0,w,h);
  ctx.save(); ctx.globalAlpha = 0.18; ctx.strokeStyle = 'rgba(73,233,255,0.32)'; ctx.lineWidth = 1 * dpr;
  for (let i=0;i<6;i++) { const yy = cy - radius * 1.6 + i * radius * 0.62 + Math.sin(t * 0.28 + i) * 8 * dpr; ctx.beginPath(); ctx.moveTo(cx - radius * 2.2, yy + pty * 18 * dpr); ctx.lineTo(cx + radius * 2.2, yy - pty * 18 * dpr); ctx.stroke(); }
  ctx.restore();
  ctx.save(); ctx.translate(cx, cy); ctx.rotate(t * 0.08);
  for (let i=0;i<3;i++) { ctx.beginPath(); ctx.strokeStyle = `rgba(255, 188, 100, ${0.06 + i * 0.03 + energy * 0.04})`; ctx.lineWidth = (2.2 - i * 0.45) * dpr; ctx.ellipse(0, 0, radius * (1.54 + i * 0.1), radius * (0.98 + i * 0.08), 0, 0, Math.PI * 2); ctx.stroke(); }
  ctx.restore();
  drawArcField(cx, cy, radius * 1.48, radius * 0.74, t, energy, 'rgba(255, 178, 84, 0.95)', 0.22 + energy * 0.1, 1.2 * dpr, 8, 0.2, false);
  drawArcField(cx, cy, radius * 1.2, radius * 0.58, -t, energy, 'rgba(73, 233, 255, 0.9)', 0.16 + energy * 0.06, 1.0 * dpr, 7, 1.2, true);
  ctx.save(); ctx.translate(cx, cy); const tiltA = Math.sin(t * 0.23) * 0.22 + ptx * 0.35; const tiltB = Math.cos(t * 0.17) * 0.2 - pty * 0.3; const pulse = 1 + energy * 0.08 + Math.sin(t * (2.2 + energy * 1.6)) * 0.015; ctx.scale(pulse, pulse);
  for (let i=0;i<8;i++) { const angle = t * (0.16 + i * 0.02) + i * (Math.PI / 4); const rx = radius * (0.28 + (i / 10) * 1.1); const ry = radius * (0.84 + Math.sin(angle) * 0.08); ctx.beginPath(); ctx.strokeStyle = `rgba(255, 190, 104, ${0.08 + i * 0.012 + energy * 0.04})`; ctx.lineWidth = (1 + (i % 2) * 0.5) * dpr; ctx.ellipse(0, 0, rx, ry, angle + tiltA, 0, Math.PI * 2); ctx.stroke(); }
  for (let i=0;i<7;i++) { const yOffset = (-0.72 + i * 0.24) * radius; const rx = radius * Math.cos((yOffset / radius) * 0.84); ctx.beginPath(); ctx.strokeStyle = `rgba(73, 233, 255, ${0.05 + i * 0.012 + energy * 0.025})`; ctx.lineWidth = 0.9 * dpr; ctx.ellipse(0, yOffset * 0.08 + Math.sin(t * 0.6 + i) * 1.2 * dpr, rx, radius * 0.24, tiltB, 0, Math.PI * 2); ctx.stroke(); }
  for (let i=0;i<10;i++) { const a = t * (0.45 + i * 0.02) + i * 0.62; const len = radius * (0.42 + (i % 3) * 0.18 + energy * 0.12); ctx.beginPath(); ctx.strokeStyle = `rgba(${i % 2 ? '255,176,88' : '73,233,255'}, ${0.12 + energy * 0.08})`; ctx.lineWidth = (0.9 + (i % 2) * 0.5) * dpr; ctx.moveTo(Math.cos(a) * radius * 0.08, Math.sin(a) * radius * 0.08); ctx.lineTo(Math.cos(a) * len, Math.sin(a * 1.08) * len * 0.78); ctx.stroke(); }
  const coreGrad = ctx.createRadialGradient(0, 0, radius * 0.02, 0, 0, radius * 0.48);
  coreGrad.addColorStop(0, 'rgba(255, 245, 214, 0.98)'); coreGrad.addColorStop(0.15, 'rgba(255, 206, 121, 0.94)'); coreGrad.addColorStop(0.46, `rgba(255, 156, 58, ${0.34 + energy * 0.18})`); coreGrad.addColorStop(1, 'rgba(255, 156, 58, 0)');
  ctx.fillStyle = coreGrad; ctx.beginPath(); ctx.arc(0,0,radius * (0.28 + energy * 0.04), 0, Math.PI * 2); ctx.fill();
  ctx.beginPath(); ctx.strokeStyle = `rgba(255, 236, 190, ${0.6 + energy * 0.18})`; ctx.lineWidth = 2.2 * dpr; ctx.arc(0,0,radius * (0.11 + energy * 0.03), 0, Math.PI * 2); ctx.stroke(); ctx.restore();
  drawParticleShell(cx, cy, radius * 1.25, t, energy);
  ctx.save(); ctx.translate(cx, cy); ctx.rotate(-t * 0.24 + ptx * 0.18); ctx.strokeStyle = `rgba(255, 183, 92, ${0.15 + energy * 0.06})`; ctx.lineWidth = 1.6 * dpr;
  for (let i=0;i<3;i++) { ctx.beginPath(); ctx.ellipse(0,0,radius * (1.0 + i * 0.16), radius * (1.0 + i * 0.16) * (0.78 + i * 0.03), i * 0.7, 0, Math.PI * 2); ctx.stroke(); }
  ctx.restore();
  requestAnimationFrame(drawOrb);
}
resize(); setState('idle'); loadStatus(); loadLogs(); connectWS(); requestAnimationFrame(drawOrb); setInterval(loadLogs, 3200);

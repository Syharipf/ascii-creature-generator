const MOTION_PRESETS = {
  swim: { amplitude: 1.0, speed: 0.55, wavelength: 1.1, bob: 0.35 },
  glide: { amplitude: 0.35, speed: 0.25, wavelength: 1.6, bob: 0.8 },
  flap: { amplitude: 1.6, speed: 0.90, wavelength: 0.8, bob: 0.6 },
  crawl: { amplitude: 0.6, speed: 0.35, wavelength: 0.5, bob: 0.15 }
};

const POV_PRESETS = {
  side: { pitch: 0.0, roll: 0.15 },
  top: { pitch: 55.0, roll: 0.35 },
  isometric: { pitch: 30.0, roll: 0.25 },
  bottom: { pitch: -30.0, roll: 0.20 }
};

const ID_RE = /^[a-z][a-z0-9-]{0,47}$/;

const canvas = document.getElementById("preview");
const ctx = canvas.getContext("2d");
const statsEl = document.getElementById("stats");
const errorEl = document.getElementById("error");
const textEl = document.getElementById("text");
const fileInput = document.getElementById("file");
const dropZone = document.getElementById("drop");
const exportBtn = document.getElementById("export");
const resetBtn = document.getElementById("reset");
const exportResultEl = document.getElementById("export-result");

// Controls
const idInput = document.getElementById("id");
const nameInput = document.getElementById("name");
const colsInput = document.getElementById("cols");
const colsVal = document.getElementById("cols-val");
const tolInput = document.getElementById("tolerance");
const tolVal = document.getElementById("tolerance-val");
const covInput = document.getElementById("coverage");
const covVal = document.getElementById("coverage-val");
const postInput = document.getElementById("posterize");
const postVal = document.getElementById("posterize-val");
const headInput = document.getElementById("head_side");
const presetInput = document.getElementById("preset");
const ampInput = document.getElementById("amplitude");
const ampVal = document.getElementById("amplitude-val");
const spdInput = document.getElementById("speed");
const spdVal = document.getElementById("speed-val");
const wavInput = document.getElementById("wavelength");
const wavVal = document.getElementById("wavelength-val");
const bobInput = document.getElementById("bob");
const bobVal = document.getElementById("bob-val");
const povInput = document.getElementById("pov");
const pitchInput = document.getElementById("pitch");
const pitchVal = document.getElementById("pitch-val");
const rollInput = document.getElementById("roll");
const rollVal = document.getElementById("roll-val");

let currentMod = null;
let lastModUrl = null;
let latestRequestId = 0;
let debounceTimer = null;
let animStartTime = performance.now();

function showError(msg) {
  if (!msg) {
    errorEl.classList.add("hidden");
    errorEl.textContent = "";
  } else {
    errorEl.textContent = msg;
    errorEl.classList.remove("hidden");
  }
}

function updateValueBadges() {
  colsVal.textContent = colsInput.value;
  tolVal.textContent = tolInput.value;
  covVal.textContent = covInput.value + "%";
  postVal.textContent = postInput.value === "0" ? "Off" : postInput.value;
  ampVal.textContent = Number(ampInput.value).toFixed(2);
  spdVal.textContent = Number(spdInput.value).toFixed(2);
  wavVal.textContent = Number(wavInput.value).toFixed(2);
  bobVal.textContent = Number(bobInput.value).toFixed(2);
  if (pitchVal && pitchInput) pitchVal.textContent = pitchInput.value + "°";
  if (rollVal && rollInput) rollVal.textContent = Number(rollInput.value).toFixed(2);
}

function readParams() {
  return {
    id: idInput.value.trim(),
    name: nameInput.value.trim(),
    cols: parseInt(colsInput.value, 10),
    tolerance: parseFloat(tolInput.value),
    coverage: parseFloat(covInput.value) / 100.0,
    posterize: parseInt(postInput.value, 10),
    head_side: headInput.value,
    preset: presetInput.value,
    amplitude: parseFloat(ampInput.value),
    speed: parseFloat(spdInput.value),
    wavelength: parseFloat(wavInput.value),
    bob: parseFloat(bobInput.value),
    pov: povInput ? povInput.value : "side",
    pitch: pitchInput ? parseFloat(pitchInput.value) : 0,
    roll: rollInput ? parseFloat(rollInput.value) : 0.15,
  };
}

function applyParams(p) {
  if (!p) return;
  if (p.id) idInput.value = p.id;
  if (p.name) nameInput.value = p.name;
  if (p.cols !== undefined) colsInput.value = p.cols;
  if (p.tolerance !== undefined) tolInput.value = p.tolerance;
  if (p.coverage !== undefined) covInput.value = Math.round(p.coverage * 100);
  if (p.posterize !== undefined) postInput.value = p.posterize;
  if (p.head_side) headInput.value = p.head_side;
  if (p.preset) presetInput.value = p.preset;
  if (p.amplitude !== undefined) ampInput.value = p.amplitude;
  if (p.speed !== undefined) spdInput.value = p.speed;
  if (p.wavelength !== undefined) wavInput.value = p.wavelength;
  if (p.bob !== undefined) bobInput.value = p.bob;
  if (p.pov && povInput) povInput.value = p.pov;
  if (p.pitch !== undefined && pitchInput) pitchInput.value = p.pitch;
  if (p.roll !== undefined && rollInput) rollInput.value = p.roll;
  updateValueBadges();
}

async function handlePayload(data, reqId) {
  if (reqId !== undefined && reqId !== latestRequestId) return;
  if (data.error) {
    showError(data.error);
    return;
  }
  showError(null);

  if (data.params) applyParams(data.params);
  if (data.stats) {
    const s = data.stats;
    const srcDim = s.source ? `${s.source[0]}×${s.source[1]}` : "";
    const gridDim = `${s.cols}×${s.rows} grid`;
    const cellsInfo = `${s.cells}/${s.cols * s.rows} cells`;
    const bgInfo = s.bg_color ? `bg color ${s.bg_color}` : "alpha";
    statsEl.textContent = `${srcDim} → ${gridDim} · ${cellsInfo} · ${bgInfo}`;
  }
  if (data.text) {
    textEl.textContent = data.text;
  }
  if (data.module) {
    const prevUrl = lastModUrl;
    const blob = new Blob([data.module], { type: "text/javascript" });
    const url = URL.createObjectURL(blob);
    try {
      const mod = await import(url);
      if (reqId === undefined || reqId === latestRequestId) {
        currentMod = mod;
        lastModUrl = url;
        if (prevUrl) URL.revokeObjectURL(prevUrl);
      } else {
        URL.revokeObjectURL(url);
      }
    } catch (err) {
      URL.revokeObjectURL(url);
      showError("Module evaluation failed: " + err.message);
    }
  }
}

async function requestConvert() {
  const reqId = ++latestRequestId;
  statsEl.textContent = "converting...";
  try {
    const res = await fetch("/api/convert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(readParams())
    });
    const data = await res.json();
    await handlePayload(data, reqId);
  } catch (err) {
    if (reqId === latestRequestId) {
      showError("Network error: " + err.message);
    }
  }
}

function onParamInput() {
  updateValueBadges();
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(requestConvert, 150);
}

presetInput.addEventListener("change", () => {
  const p = presetInput.value;
  const defs = MOTION_PRESETS[p];
  if (defs) {
    ampInput.value = defs.amplitude;
    spdInput.value = defs.speed;
    wavInput.value = defs.wavelength;
    bobInput.value = defs.bob;
  }
  onParamInput();
});

if (povInput) {
  povInput.addEventListener("change", () => {
    const pv = povInput.value;
    const defs = POV_PRESETS[pv];
    if (defs) {
      if (pitchInput) pitchInput.value = defs.pitch;
      if (rollInput) rollInput.value = defs.roll;
    }
    onParamInput();
  });
}

const inputList = [colsInput, tolInput, covInput, postInput, headInput, ampInput, spdInput, wavInput, bobInput];
if (pitchInput) inputList.push(pitchInput);
if (rollInput) inputList.push(rollInput);
inputList.forEach((el) => {
  el.addEventListener("input", onParamInput);
  el.addEventListener("change", onParamInput);
});

idInput.addEventListener("input", () => {
  const v = idInput.value.trim();
  if (v && !ID_RE.test(v)) {
    showError("id must match ^[a-z][a-z0-9-]{0,47}$");
  } else {
    showError(null);
  }
});

resetBtn.addEventListener("click", () => {
  applyParams({
    cols: 28,
    tolerance: 32,
    coverage: 0.4,
    posterize: 16,
    head_side: "left",
    preset: "swim",
    amplitude: 1.0,
    speed: 0.55,
    wavelength: 1.1,
    bob: 0.35,
    pov: "side",
    pitch: 0.0,
    roll: 0.15
  });
  onParamInput();
});

async function uploadFile(file) {
  if (!file) return;
  const reqId = ++latestRequestId;
  statsEl.textContent = "uploading...";
  showError(null);
  exportResultEl.innerHTML = "";

  try {
    const res = await fetch(`/api/upload?name=${encodeURIComponent(file.name)}`, {
      method: "POST",
      body: file
    });
    const data = await res.json();
    await handlePayload(data, reqId);
  } catch (err) {
    if (reqId === latestRequestId) {
      showError("Upload failed: " + err.message);
    }
  }
}

fileInput.addEventListener("change", (e) => {
  if (e.target.files && e.target.files[0]) {
    uploadFile(e.target.files[0]);
  }
});

dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("dragover");
});

dropZone.addEventListener("dragleave", () => {
  dropZone.classList.remove("dragover");
});

dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("dragover");
  if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) {
    uploadFile(e.dataTransfer.files[0]);
  }
});

exportBtn.addEventListener("click", async () => {
  const p = readParams();
  if (!ID_RE.test(p.id)) {
    showError("id must match ^[a-z][a-z0-9-]{0,47}$");
    return;
  }
  showError(null);
  exportResultEl.innerHTML = "<span>Exporting...</span>";

  try {
    const res = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        params: p,
        id: p.id,
        name: p.name
      })
    });
    const data = await res.json();
    if (data.error) {
      showError(data.error);
      exportResultEl.innerHTML = "";
      return;
    }

    exportResultEl.innerHTML = "";
    (data.files || []).forEach((f) => {
      const item = document.createElement("div");
      item.className = "export-item";
      const code = document.createElement("code");
      code.textContent = f.path;
      const copyBtn = document.createElement("button");
      copyBtn.textContent = "Copy";
      copyBtn.addEventListener("click", () => {
        navigator.clipboard.writeText(f.path).then(() => {
          copyBtn.textContent = "Copied!";
          setTimeout(() => (copyBtn.textContent = "Copy"), 1500);
        });
      });
      item.appendChild(code);
      item.appendChild(copyBtn);
      exportResultEl.appendChild(item);
    });
  } catch (err) {
    showError("Export failed: " + err.message);
    exportResultEl.innerHTML = "";
  }
});

// Canvas render loop
function render(now) {
  const t = (now - animStartTime) / 1000.0;
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;

  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }

  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  if (currentMod && typeof currentMod.drawCreature === "function") {
    currentMod.drawCreature(ctx, {
      x: w * 0.18,
      y: h * 0.5 + Math.sin(t * 0.8) * 6,
      angle: Math.PI,
      length: Math.min(w * 0.62, h * 1.5),
      time: t
    });
  }

  requestAnimationFrame(render);
}

// Initial state fetch
async function init() {
  updateValueBadges();
  requestAnimationFrame(render);
  try {
    const res = await fetch("/api/state");
    const data = await res.json();
    if (data.loaded) {
      await handlePayload(data);
    }
  } catch (err) {
    // Server not yet serving or idle
  }
}

init();

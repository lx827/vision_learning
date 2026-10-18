const $ = (id) => document.getElementById(id);
const state = {
  active: false, starting: false, connected: false, initialized: false,
  sourceWidth: 0, sourceHeight: 0, cameraSequence: -1, countSequence: -1,
  objectUrl: "", drawing: false, drag: null, disposed: false,
  status: null, models: [], modelsLoaded: false, modelBusy: false, modelError: "",
  displayBusy: false,
};

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

function value(id) { return Number($(id).value); }
function roi() {
  return { x: value("roi-x"), y: value("roi-y"), width: value("roi-width"), height: value("roi-height") };
}
function payload() {
  return {
    weights: $("weights-select").value,
    show_outside_roi: $("show-outside-roi").checked,
    count_mode: $("count-mode").value, conf: value("conf-input"), imgsz: value("imgsz-input"),
    roi: roi(), direction: $("direction-input").value,
    line_start: [value("line-x"), 0],
    line_end: [value("line-x"), state.sourceHeight || roi().y + roi().height],
    deadband_px: value("deadband-input"),
  };
}

function syncModelControls() {
  const locked = state.active || state.starting || state.modelBusy;
  $("weights-select").disabled = locked || state.status?.preparing || !state.modelsLoaded;
  $("refresh-models-button").disabled = locked || state.status?.preparing;
  $("start-button").disabled = locked || state.displayBusy || !state.initialized || !state.modelsLoaded
    || !state.models.some((model) => model.path === $("weights-select").value);
}

function selectConfiguredWeights(weights) {
  const select = $("weights-select");
  if (![...select.options].some((option) => option.value === weights)) {
    select.add(new Option(`${weights}（未在目录中找到）`, weights));
  }
  select.value = weights;
}

async function loadModels() {
  state.modelBusy = true;
  $("refresh-models-button").setAttribute("aria-busy", "true");
  syncModelControls();
  try {
    const catalog = await api("/api/count/models");
    state.models = catalog.models;
    $("weights-select").replaceChildren(...catalog.models.map((model) => new Option(model.name, model.path)));
    selectConfiguredWeights(catalog.selected);
    $("model-directory").textContent = `模型目录：${catalog.directory}`;
    state.modelsLoaded = true;
    state.modelError = catalog.models.length ? "" : "模型目录中没有可用权重，请放入 .pt 文件后刷新。";
    showError(state.modelError);
  } catch (error) {
    state.modelError = `读取权重列表失败：${error.message}`;
    showError(state.modelError);
  } finally {
    state.modelBusy = false;
    $("refresh-models-button").removeAttribute("aria-busy");
    syncModelControls();
  }
}

async function changeModel() {
  state.modelBusy = true;
  syncModelControls();
  $("model-state").textContent = "正在切换模型…";
  try {
    const { status } = await api("/api/count/prepare", {
      method: "POST", body: JSON.stringify({ weights: $("weights-select").value }),
    });
    state.modelError = "";
    render(status);
  } catch (error) {
    state.modelError = `切换模型失败：${error.message}`;
    if (state.status?.config) selectConfiguredWeights(state.status.config.weights);
    showError(state.modelError);
  } finally {
    state.modelBusy = false;
    syncModelControls();
  }
}

function showError(error) {
  $("error-text").textContent = error;
  $("error-text").hidden = !error;
  $("error-chip").hidden = !error;
}

async function changeDisplay() {
  state.displayBusy = true;
  $("show-outside-roi").disabled = true;
  $("display-error").hidden = true;
  syncModelControls();
  try {
    const { status } = await api("/api/count/display", {
      method: "PUT", body: JSON.stringify({ show_outside_roi: $("show-outside-roi").checked }),
    });
    render(status);
  } catch (error) {
    $("display-error").textContent = `更新目标框显示失败：${error.message}`;
    $("display-error").hidden = false;
  } finally {
    state.displayBusy = false;
    $("show-outside-roi").disabled = !state.initialized;
    $("show-outside-roi").checked = state.status?.config?.show_outside_roi ?? true;
    syncModelControls();
  }
}

function updateRule() {
  const isRoi = $("count-mode").value === "roi";
  $("line-rule-fields").hidden = isRoi;
  $("count-rule-help").textContent = isRoi
    ? "中心点进入 ROI、首次获得跟踪 ID 即计 1；同一个 ID 连续出现不重复计数，无需过线。"
    : "按指定方向穿过红线后计数，同一个跟踪 ID 只计一次。";
}

function render(status) {
  state.status = status;
  state.active = status.active;
  state.starting = status.starting;
  if (!state.modelBusy && status.config) selectConfiguredWeights(status.config.weights);
  if (!state.initialized && status.config) {
    const config = status.config;
    $("conf-input").value = config.conf;
    $("imgsz-input").value = config.imgsz;
    $("line-x").value = config.line_start[0];
    $("direction-input").value = config.direction;
    $("deadband-input").value = config.deadband_px;
    $("count-mode").value = config.count_mode;
    setRoi(config.roi);
    state.initialized = true;
    updateRule();
  }
  if (!state.displayBusy) {
    $("show-outside-roi").checked = status.config?.show_outside_roi ?? true;
    $("show-outside-roi").disabled = !state.initialized;
  }
  $("count-value").textContent = status.count ?? 0;
  $("detect-value").textContent = status.detections ?? 0;
  $("count-fps-value").textContent = Number(status.fps ?? 0).toFixed(1);
  $("monitor-state").textContent = status.stopping ? "正在停止"
    : status.starting ? "正在准备模型，先显示相机预览"
    : status.active ? "正在实时监测" : status.error ? "检测失败" : "相机预览 / 未开始监测";
  $("live-dot").classList.toggle("active", status.active && !status.starting);
  $("stop-button").disabled = !status.active && !status.starting;
  $("detection-settings").disabled = status.active || status.starting;
  $("count-settings").disabled = status.active || status.starting;
  $("draw-roi-button").disabled = !state.connected || !state.sourceWidth;
  $("full-roi-button").disabled = !state.connected || !state.sourceWidth;
  const modelName = status.config?.weights?.split(/[\\/]/).pop() || "";
  $("model-state").textContent = status.preparing ? `正在预热 ${modelName}，可先预览和框选 ROI。`
    : status.prepare_error ? `预热未完成：${status.prepare_error}；开始监测时会重试。`
    : status.model_ready ? `模型已准备好：${modelName}` : "首次监测需准备模型；准备期间可查看相机预览。";
  syncModelControls();
  showError(status.error || state.modelError);
}

async function refresh() {
  const [{ status }, camera] = await Promise.all([api("/api/count/status"), api("/api/camera/status")]);
  state.connected = camera.status.connected;
  state.sourceWidth = Number(camera.status.width || 0);
  state.sourceHeight = Number(camera.status.height || 0);
  render(status);
  renderRoi();
}

async function start() {
  cancelDrawing();
  const { status } = await api("/api/count/start", { method: "POST", body: JSON.stringify(payload()) });
  state.countSequence = -1;
  render(status);
}
async function stop() {
  const { status } = await api("/api/count/stop", { method: "POST" });
  render(status);
  state.cameraSequence = -1;
}
async function reset() {
  const { status } = await api("/api/count/reset", { method: "POST" });
  render(status);
}

function frameMode() { return state.active && !state.starting ? "count" : "camera"; }
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function previewLoop() {
  while (!state.disposed) {
    if (!state.connected) { await pause(200); continue; }
    const mode = frameMode();
    const sequenceKey = mode === "count" ? "countSequence" : "cameraSequence";
    try {
      const response = await fetch(`/api/${mode}/frame?after=${state[sequenceKey]}`, { cache: "no-store" });
      if (response.status === 204) { await pause(30); continue; }
      if (!response.ok) { await pause(300); continue; }
      const blob = await response.blob();
      if (mode !== frameMode() || state.disposed) continue;
      const url = URL.createObjectURL(blob);
      const image = $("count-frame");
      const previous = state.objectUrl;
      image.src = url;
      try { await image.decode(); } catch { URL.revokeObjectURL(url); await pause(100); continue; }
      state.objectUrl = url;
      if (previous) URL.revokeObjectURL(previous);
      state[sequenceKey] = Number(response.headers.get("X-Frame-Sequence"));
      image.classList.add("active");
      $("stage-empty").hidden = true;
      $("frame-meta").textContent = `${state.sourceWidth} × ${state.sourceHeight} · ${mode === "count" ? "检测画面" : "相机预览"}`;
      renderRoi();
    } catch (error) {
      if (!state.disposed) { $("frame-meta").textContent = "等待相机画面"; await pause(300); }
    }
  }
}

function setRoi(region) {
  for (const key of ["x", "y", "width", "height"]) $("roi-" + key).value = region[key];
  renderRoi();
}

function renderRoi() {
  const region = roi();
  const box = $("roi-box");
  const editable = !state.active && !state.starting && state.connected;
  $("roi-layer").classList.toggle("editable", editable);
  if (!editable && (state.drag || state.drawing)) cancelDrawing(true);
  // 更换实时帧时 naturalWidth 会短暂归零，用已显示首帧的状态避免框和控制点闪烁。
  box.hidden = !state.connected || !state.sourceWidth || !state.sourceHeight
    || !$("count-frame").classList.contains("active");
  if (box.hidden) return;
  const width = $("roi-layer").clientWidth;
  const height = $("roi-layer").clientHeight;
  box.style.left = `${region.x / state.sourceWidth * width}px`;
  box.style.top = `${region.y / state.sourceHeight * height}px`;
  box.style.width = `${region.width / state.sourceWidth * width}px`;
  box.style.height = `${region.height / state.sourceHeight * height}px`;
}

function cancelDrawing(restore = false) {
  const drag = state.drag;
  state.drawing = false;
  state.drag = null;
  $("roi-layer").classList.remove("drawing");
  $("draw-roi-button").textContent = "框选 ROI";
  if (drag && $("roi-layer").hasPointerCapture(drag.pointerId)) {
    $("roi-layer").releasePointerCapture(drag.pointerId);
  }
  if (restore && drag) setRoi(drag.previous);
}

function pointerPixel(event) {
  const rect = $("roi-layer").getBoundingClientRect();
  return {
    x: Math.min(state.sourceWidth, Math.max(0, (event.clientX - rect.left) / rect.width * state.sourceWidth)),
    y: Math.min(state.sourceHeight, Math.max(0, (event.clientY - rect.top) / rect.height * state.sourceHeight)),
  };
}

$("draw-roi-button").addEventListener("click", () => {
  if (state.drawing) { cancelDrawing(); return; }
  state.drawing = true;
  $("roi-layer").classList.add("drawing");
  $("draw-roi-button").textContent = "取消框选";
});
$("roi-layer").addEventListener("pointerdown", (event) => {
  if (state.active || state.starting || !state.connected || !state.sourceWidth
      || !state.sourceHeight || event.button !== 0
      || !$("count-frame").classList.contains("active")) return;
  const box = event.target.closest("#roi-box");
  if (!state.drawing && !box) return;
  event.preventDefault();
  state.drag = { point: pointerPixel(event), previous: roi(), pointerId: event.pointerId,
    mode: state.drawing ? "draw" : event.target.dataset.edge || "move" };
  event.currentTarget.setPointerCapture(event.pointerId);
});
$("roi-layer").addEventListener("pointermove", (event) => {
  if (!state.drag || event.pointerId !== state.drag.pointerId) return;
  const point = pointerPixel(event);
  const start = state.drag.point;
  const { previous, mode } = state.drag;
  const dx = Math.round(point.x - start.x);
  const dy = Math.round(point.y - start.y);
  const clamp = (v, min, max) => Math.min(max, Math.max(min, v));
  if (mode === "move") {
    setRoi({ ...previous,
      x: clamp(previous.x + dx, 0, state.sourceWidth - previous.width),
      y: clamp(previous.y + dy, 0, state.sourceHeight - previous.height) });
    return;
  }
  if (mode !== "draw") {
    // 固定对侧边界，控制点限制在原始画面内，最小区域为 1 像素。
    let left = previous.x, top = previous.y;
    let right = left + previous.width, bottom = top + previous.height;
    if (mode.includes("w")) left = clamp(left + dx, 0, right - 1);
    if (mode.includes("e")) right = clamp(right + dx, left + 1, state.sourceWidth);
    if (mode.includes("n")) top = clamp(top + dy, 0, bottom - 1);
    if (mode.includes("s")) bottom = clamp(bottom + dy, top + 1, state.sourceHeight);
    setRoi({ x: left, y: top, width: right - left, height: bottom - top });
    return;
  }
  const x = Math.min(state.sourceWidth - 1, Math.floor(Math.min(start.x, point.x)));
  const y = Math.min(state.sourceHeight - 1, Math.floor(Math.min(start.y, point.y)));
  setRoi({ x, y, width: Math.max(1, Math.ceil(Math.max(start.x, point.x)) - x),
    height: Math.max(1, Math.ceil(Math.max(start.y, point.y)) - y) });
});
$("roi-layer").addEventListener("pointerup", (event) => {
  if (state.drag && event.pointerId === state.drag.pointerId) cancelDrawing();
});
for (const name of ["pointercancel", "lostpointercapture"]) {
  $("roi-layer").addEventListener(name, () => { if (state.drag) cancelDrawing(true); });
}
$("full-roi-button").addEventListener("click", () => {
  cancelDrawing();
  setRoi({ x: 0, y: 0, width: state.sourceWidth, height: state.sourceHeight });
});
for (const key of ["x", "y", "width", "height"]) $("roi-" + key).addEventListener("input", renderRoi);
$("count-mode").addEventListener("change", updateRule);
$("weights-select").addEventListener("change", changeModel);
$("refresh-models-button").addEventListener("click", loadModels);
$("show-outside-roi").addEventListener("change", changeDisplay);
$("count-surface").addEventListener("previewresize", renderRoi);
$("count-frame").addEventListener("load", renderRoi);
for (const [id, action] of [["start-button", start], ["stop-button", stop], ["reset-button", reset]]) {
  $(id).addEventListener("click", async () => {
    $(id).disabled = true;
    try { await action(); } catch (error) { showError(error.message); }
    finally {
      $(id).disabled = id === "stop-button" ? !state.active : false;
      syncModelControls();
    }
  });
}
window.addEventListener("keydown", (event) => { if (event.key === "Escape") cancelDrawing(true); });
window.addEventListener("pagehide", () => {
  state.disposed = true;
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
});
refresh().catch((error) => showError(error.message));
loadModels();
api("/api/count/prepare", { method: "POST" }).catch((error) => { $("model-state").textContent = error.message; });
setInterval(() => refresh().catch((error) => showError(error.message)), 800);
previewLoop();

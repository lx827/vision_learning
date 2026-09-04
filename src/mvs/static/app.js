const state = {
  config: null,
  devices: [],
  parameters: null,
  status: { connected: false, auto_capture: false, recording: false },
  streamStarted: false,
  scanPromise: null,
  fpsWarningActive: false,
  lastError: "",
};

const $ = (id) => document.getElementById(id);
const elements = {
  stage: document.querySelector(".stage"),
  connectionPill: $("connection-pill"),
  connectionText: $("connection-text"),
  preview: $("preview-image"),
  deviceSelect: $("device-select"),
  imagingFields: $("imaging-fields"),
  connectButton: $("connect-button"),
  snapshotButton: $("snapshot-button"),
  autoButton: $("auto-button"),
  recordButton: $("record-button"),
  recordingBadge: $("recording-badge"),
  toast: $("toast"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`服务返回了无法解析的响应（HTTP ${response.status}）`);
  }
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `请求失败（HTTP ${response.status}）`);
  }
  return payload;
}

function numberValue(id) {
  const value = Number($(id).value);
  if (!Number.isFinite(value)) throw new Error(`${$(id).previousElementSibling?.textContent || id} 不是有效数字`);
  return value;
}

function showToast(message, isError = false) {
  elements.toast.textContent = message;
  elements.toast.classList.toggle("error", isError);
  elements.toast.classList.add("visible");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => elements.toast.classList.remove("visible"), 3200);
}

function logEvent(message, isError = false) {
  $("event-time").textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  $("event-message").textContent = message;
  $("event-message").style.color = isError ? "var(--coral)" : "";
}

async function withBusy(button, operation) {
  const wasDisabled = button.disabled;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  try {
    return await operation();
  } catch (error) {
    showToast(error.message, true);
    logEvent(error.message, true);
    throw error;
  } finally {
    button.removeAttribute("aria-busy");
    button.disabled = wasDisabled;
  }
}

function fillConfig(config) {
  state.config = config;
  $("camera-ip").value = config.camera.ip;
  $("camera-serial").value = config.camera.serial;
  $("sdk-path").value = config.camera.sdk_python_path;
  $("frame-timeout").value = config.camera.frame_timeout_ms;
  $("photo-dir").value = config.capture.photo_dir;
  $("video-dir").value = config.capture.video_dir;
  $("photo-format").value = config.capture.photo_format;
  $("jpeg-quality").value = config.capture.jpeg_quality;
  $("auto-interval").value = config.capture.auto_interval_seconds;
  $("video-format").value = config.capture.video_format;
}

function collectConfig() {
  return {
    camera: {
      ip: $("camera-ip").value.trim(),
      serial: $("camera-serial").value.trim(),
      sdk_python_path: $("sdk-path").value.trim(),
      frame_timeout_ms: numberValue("frame-timeout"),
    },
    capture: {
      ...(state.config?.capture || {}),
      photo_dir: $("photo-dir").value.trim(),
      video_dir: $("video-dir").value.trim(),
      photo_format: $("photo-format").value,
      jpeg_quality: numberValue("jpeg-quality"),
      auto_interval_seconds: numberValue("auto-interval"),
      video_format: $("video-format").value,
      preview_quality: state.config?.capture.preview_quality ?? 80,
    },
    server: state.config?.server || { host: "127.0.0.1", port: 8765 },
  };
}

async function saveConfig(message = "配置已保存") {
  const payload = await api("/api/config", { method: "PUT", body: JSON.stringify(collectConfig()) });
  fillConfig(payload.config);
  showToast(message);
  logEvent(message);
  return payload.config;
}

async function scanDevices() {
  if (state.scanPromise) return state.scanPromise;
  state.scanPromise = scanDevicesOnce();
  try {
    return await state.scanPromise;
  } finally {
    state.scanPromise = null;
  }
}

async function scanDevicesOnce() {
  const payload = await api("/api/devices");
  state.devices = payload.devices;
  elements.deviceSelect.replaceChildren();
  if (!state.devices.length) {
    elements.deviceSelect.add(new Option("未发现相机", ""));
    logEvent("未发现 MVS 相机，请检查供电、网线和网卡地址。", true);
    return;
  }
  state.devices.forEach((device, index) => {
    const address = device.ip || device.serial;
    elements.deviceSelect.add(new Option(`${device.model} · ${address}`, String(index)));
  });
  const configured = state.devices.findIndex((device) =>
    (state.config.camera.ip && device.ip === state.config.camera.ip) ||
    (state.config.camera.serial && device.serial === state.config.camera.serial)
  );
  elements.deviceSelect.value = String(configured >= 0 ? configured : 0);
  selectDevice();
  logEvent(`发现 ${state.devices.length} 台 MVS 相机。`);
}

function selectDevice() {
  const device = state.devices[Number(elements.deviceSelect.value)];
  if (!device) return;
  $("camera-ip").value = device.ip;
  $("camera-serial").value = device.serial;
}

async function connectOrDisconnect() {
  if (state.status.connected) {
    const payload = await api("/api/camera/disconnect", { method: "POST" });
    updateStatus(payload.status);
    logEvent("相机已断开，SDK 资源已释放。");
    return;
  }
  await saveConfig("连接配置已保存");
  const payload = await api("/api/camera/connect", { method: "POST" });
  updateStatus(payload.status);
  startPreview();
  await loadParameters();
  logEvent(`已连接 ${payload.status.device.model}（${payload.status.device.ip || payload.status.device.serial}）。`);
}

function startPreview() {
  if (state.streamStarted) return;
  elements.preview.src = `/api/camera/stream?t=${Date.now()}`;
  state.streamStarted = true;
}

function stopPreview() {
  elements.preview.removeAttribute("src");
  state.streamStarted = false;
}

function updateStatus(status) {
  state.status = status;
  const connected = Boolean(status.connected);
  elements.stage.classList.toggle("online", connected);
  elements.connectionPill.classList.toggle("online", connected);
  elements.connectionText.textContent = connected ? "相机在线" : "未连接";
  elements.connectButton.querySelector("span").textContent = connected ? "断开相机" : "连接相机";
  elements.snapshotButton.disabled = !connected;
  elements.autoButton.disabled = !connected;
  elements.recordButton.disabled = !connected;
  elements.imagingFields.disabled = !connected;
  elements.autoButton.textContent = status.auto_capture ? "停止自动拍照" : "开始自动拍照";
  elements.recordButton.querySelector("span").textContent = status.recording ? "停止录像" : "开始录像";
  elements.recordButton.classList.toggle("active", Boolean(status.recording));
  elements.recordingBadge.classList.toggle("active", Boolean(status.recording));
  $("device-name").textContent = status.device ? `${status.device.model} / ${status.device.serial}` : "等待相机";
  $("metric-resolution").textContent = status.width ? `${status.width} × ${status.height}` : "—";
  $("metric-fps").textContent = Number(status.fps || 0).toFixed(1);
  $("metric-lost").textContent = status.lost_packets || 0;
  $("last-photo").textContent = status.last_photo || "—";
  $("last-photo").title = status.last_photo || "";
  $("recording-path").textContent = status.recording_path || "—";
  $("recording-path").title = status.recording_path || "";
  const recordingSize = status.recording_size || [0, 0];
  $("recording-size").textContent = recordingSize[0] ? `${recordingSize[0]} × ${recordingSize[1]}` : "—";
  $("recording-dropped").textContent = status.recording_dropped_frames || 0;
  $("recording-duplicated").textContent = status.recording_duplicated_frames || 0;
  $("recording-fps").textContent = status.recording_fps ? `${Number(status.recording_fps).toFixed(2)} FPS` : "—";
  updateFpsDiagnostic(status.fps_diagnostic);
  if (!connected) stopPreview();
  if (status.last_error && status.last_error !== state.lastError) {
    state.lastError = status.last_error;
    logEvent(status.last_error, true);
  }
}

function updateFpsDiagnostic(diagnostic) {
  const warning = $("fps-warning");
  const active = Boolean(diagnostic?.active);
  warning.hidden = !active;
  if (active) {
    warning.textContent = `采集帧率不足：目标 ${diagnostic.target_fps} FPS，实际 ${diagnostic.actual_fps} FPS。原因：${diagnostic.reason}。建议：${diagnostic.recommendation}。`;
    if (!state.fpsWarningActive) {
      showToast("实际采集帧率低于目标，请查看画面下方提示。", true);
      logEvent(warning.textContent, true);
    }
  } else if (state.fpsWarningActive && diagnostic?.state === "ok") {
    logEvent("实际采集帧率已恢复到目标范围。");
  }
  state.fpsWarningActive = active;
}

function applyFeature(id, feature, rangeId) {
  const input = $(id);
  const supported = Boolean(feature);
  input.disabled = !supported;
  if (!supported) {
    if (rangeId) $(rangeId).textContent = "相机不支持";
    return;
  }
  input.value = feature.value;
  input.min = feature.minimum;
  input.max = feature.maximum;
  if (rangeId) $(rangeId).textContent = `${feature.minimum.toFixed(2)} — ${feature.maximum.toFixed(2)}`;
}

async function loadParameters() {
  const payload = await api("/api/camera/parameters");
  const p = payload.parameters;
  state.parameters = p;
  applyFeature("exposure-value", p.exposure_us, "exposure-range");
  applyFeature("gain-value", p.gain_db, "gain-range");
  applyFeature("fps-value", p.frame_rate, "fps-range");
  $("exposure-mode").disabled = !p.capabilities.exposure_mode;
  $("gain-mode").disabled = !p.capabilities.gain_mode;
  $("white-balance-mode").disabled = !p.capabilities.white_balance_mode;
  $("fps-enabled").disabled = !p.capabilities.frame_rate_enabled;
  if (p.exposure_mode) $("exposure-mode").value = p.exposure_mode;
  if (p.gain_mode) $("gain-mode").value = p.gain_mode;
  if (p.white_balance_mode) $("white-balance-mode").value = p.white_balance_mode;
  $("fps-enabled").checked = Boolean(p.frame_rate_enabled);
  syncParameterControls();
}

function syncParameterControls() {
  const connected = !elements.imagingFields.disabled;
  const capabilities = state.parameters?.capabilities || {};
  $("exposure-value").disabled = !connected || !capabilities.exposure_us || (capabilities.exposure_mode && $("exposure-mode").value !== "off");
  $("gain-value").disabled = !connected || !capabilities.gain_db || (capabilities.gain_mode && $("gain-mode").value !== "off");
  $("fps-value").disabled = !connected || !capabilities.frame_rate || (capabilities.frame_rate_enabled && !$("fps-enabled").checked);
}

async function applyParameters() {
  const capabilities = state.parameters?.capabilities || {};
  const values = {};
  if (capabilities.exposure_mode) values.exposure_mode = $("exposure-mode").value;
  if (capabilities.exposure_us && (!capabilities.exposure_mode || values.exposure_mode === "off")) values.exposure_us = numberValue("exposure-value");
  if (capabilities.gain_mode) values.gain_mode = $("gain-mode").value;
  if (capabilities.gain_db && (!capabilities.gain_mode || values.gain_mode === "off")) values.gain_db = numberValue("gain-value");
  if (capabilities.frame_rate_enabled) values.frame_rate_enabled = $("fps-enabled").checked;
  if (capabilities.frame_rate && (!capabilities.frame_rate_enabled || values.frame_rate_enabled)) values.frame_rate = numberValue("fps-value");
  if (capabilities.white_balance_mode) values.white_balance_mode = $("white-balance-mode").value;
  const payload = await api("/api/camera/parameters", { method: "PUT", body: JSON.stringify(values) });
  state.parameters = payload.parameters;
  showToast("成像参数已应用");
  logEvent("曝光、增益、帧率和白平衡设置已写入相机。");
  return payload.parameters;
}

async function takeSnapshot() {
  const payload = await api("/api/capture/snapshot", { method: "POST" });
  showToast("照片已保存");
  logEvent(`照片已保存：${payload.path}`);
  await pollStatus();
}

async function toggleAutoCapture() {
  await saveConfig("输出设置已保存");
  const path = state.status.auto_capture ? "/api/capture/auto/stop" : "/api/capture/auto/start";
  const payload = await api(path, {
    method: "POST",
    body: state.status.auto_capture ? undefined : JSON.stringify({ interval_seconds: numberValue("auto-interval") }),
  });
  updateStatus(payload.status);
  logEvent(payload.status.auto_capture ? `自动拍照已启动，每 ${$("auto-interval").value} 秒保存一张。` : "自动拍照已停止。");
}

async function toggleRecording() {
  await saveConfig("输出设置已保存");
  const path = state.status.recording ? "/api/recording/stop" : "/api/recording/start";
  const payload = await api(path, { method: "POST" });
  updateStatus(payload.status);
  logEvent(payload.status.recording ? `录像已开始：${payload.path}` : `录像已停止：${payload.path || "未生成文件"}`);
}

async function pollStatus() {
  try {
    const payload = await api("/api/camera/status");
    const wasConnected = state.status.connected;
    updateStatus(payload.status);
    if (payload.status.connected && !state.streamStarted) startPreview();
    if (wasConnected && !payload.status.connected) logEvent("相机连接已结束。", true);
  } catch (error) {
    logEvent(`状态查询失败：${error.message}`, true);
  }
}

function bindEvents() {
  elements.deviceSelect.addEventListener("change", selectDevice);
  $("scan-button").addEventListener("click", (event) => withBusy(event.currentTarget, scanDevices).catch(() => {}));
  $("save-config-button").addEventListener("click", (event) => withBusy(event.currentTarget, () => saveConfig()).catch(() => {}));
  $("save-output-button").addEventListener("click", (event) => withBusy(event.currentTarget, () => saveConfig("输出设置已保存")).catch(() => {}));
  elements.connectButton.addEventListener("click", (event) => withBusy(event.currentTarget, connectOrDisconnect).catch(() => {}));
  elements.snapshotButton.addEventListener("click", (event) => withBusy(event.currentTarget, takeSnapshot).catch(() => {}));
  elements.autoButton.addEventListener("click", (event) => withBusy(event.currentTarget, toggleAutoCapture).catch(() => {}));
  elements.recordButton.addEventListener("click", (event) => withBusy(event.currentTarget, toggleRecording).catch(() => {}));
  $("apply-parameters-button").addEventListener("click", (event) => withBusy(event.currentTarget, applyParameters).catch(() => {}));
  $("exposure-mode").addEventListener("change", syncParameterControls);
  $("gain-mode").addEventListener("change", syncParameterControls);
  $("fps-enabled").addEventListener("change", syncParameterControls);
  elements.preview.addEventListener("error", () => {
    if (state.status.connected) logEvent("实时预览中断，正在等待重新连接。", true);
  });
  window.addEventListener("pagehide", () => {
    if (!state.status.connected) return;
    navigator.sendBeacon(
      "/api/camera/disconnect",
      new Blob(["{}"], { type: "application/json" }),
    );
  });
}

async function initialize() {
  bindEvents();
  try {
    const [configPayload, statusPayload] = await Promise.all([api("/api/config"), api("/api/camera/status")]);
    fillConfig(configPayload.config);
    updateStatus(statusPayload.status);
    await withBusy($("scan-button"), scanDevices);
  } catch (error) {
    showToast(error.message, true);
    logEvent(error.message, true);
  }
  setInterval(pollStatus, 1000);
}

initialize();

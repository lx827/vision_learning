const state = {
  config: null,
  devices: [],
  parameters: null,
  status: { connected: false, auto_capture: false, recording: false },
  streamStarted: false,
  scanPromise: null,
  fpsWarningActive: false,
  lastError: "",
  drawing: false,
  dragStart: null,
  dragRegion: null,
  draftRegion: null,
  processingRegion: null,
};

const $ = (id) => document.getElementById(id);
const elements = {
  stage: document.querySelector(".stage"),
  connectionPill: $("connection-pill"),
  connectionText: $("connection-text"),
  preview: $("preview-image"),
  viewport: $("viewport"),
  selectionLayer: $("selection-layer"),
  cameraRegionBox: $("camera-region-box"),
  processingRegionBox: $("processing-region-box"),
  draftRegionBox: $("draft-region-box"),
  deviceSelect: $("device-select"),
  imagingFields: $("imaging-fields"),
  roiFields: $("roi-fields"),
  connectButton: $("connect-button"),
  snapshotButton: $("snapshot-button"),
  autoButton: $("auto-button"),
  recordButton: $("record-button"),
  recordingBadge: $("recording-badge"),
  drawRegionButton: $("draw-region-button"),
  applyRegionButton: $("apply-region-button"),
  clearRegionButton: $("clear-region-button"),
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
  $("output-max-width").value = config.capture.output_max_width;
  $("output-max-height").value = config.capture.output_max_height;
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
      output_max_width: numberValue("output-max-width"),
      output_max_height: numberValue("output-max-height"),
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
  elements.roiFields.disabled = !connected;
  elements.drawRegionButton.disabled = !connected;
  elements.autoButton.textContent = status.auto_capture ? "停止自动拍照" : "开始自动拍照";
  elements.recordButton.querySelector("span").textContent = status.recording ? "停止录像" : "开始录像";
  elements.recordButton.classList.toggle("active", Boolean(status.recording));
  elements.recordingBadge.classList.toggle("active", Boolean(status.recording));
  $("device-name").textContent = status.device ? `${status.device.model} / ${status.device.serial}` : "等待相机";
  $("metric-resolution").textContent = status.width ? `${status.width} × ${status.height}` : "—";
  $("metric-preview-resolution").textContent = status.preview_width ? `${status.preview_width} × ${status.preview_height}` : "—";
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
  state.processingRegion = status.processing_region || null;
  elements.clearRegionButton.disabled = !connected || !state.processingRegion;
  if (!state.draftRegion && !state.drawing && $("draw-mode").value === "processing") {
    updateRegionReadout(state.processingRegion);
  }
  updateFpsDiagnostic(status.fps_diagnostic);
  if (!connected) {
    stopPreview();
    cancelDrawing();
    state.draftRegion = null;
    updateRegionReadout();
  }
  renderRegions();
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

function imageContentRect() {
  const sourceWidth = Number(state.status.width || 0);
  const sourceHeight = Number(state.status.height || 0);
  if (!sourceWidth || !sourceHeight || !elements.preview.naturalWidth) return null;
  const viewportRect = elements.viewport.getBoundingClientRect();
  const imageRect = elements.preview.getBoundingClientRect();
  const imageRatio = elements.preview.naturalWidth / elements.preview.naturalHeight;
  let width = imageRect.width;
  let height = width / imageRatio;
  if (height > imageRect.height) {
    height = imageRect.height;
    width = height * imageRatio;
  }
  return {
    left: imageRect.left - viewportRect.left + (imageRect.width - width) / 2,
    top: imageRect.top - viewportRect.top + (imageRect.height - height) / 2,
    width,
    height,
    sourceWidth,
    sourceHeight,
  };
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function pointerInImage(event, rect) {
  const viewportRect = elements.viewport.getBoundingClientRect();
  return {
    x: clamp(event.clientX - viewportRect.left, rect.left, rect.left + rect.width),
    y: clamp(event.clientY - viewportRect.top, rect.top, rect.top + rect.height),
  };
}

function pixelRegionFromDrag(start, end, rect) {
  const left = Math.min(start.x, end.x);
  const top = Math.min(start.y, end.y);
  const right = Math.max(start.x, end.x);
  const bottom = Math.max(start.y, end.y);
  const x = Math.floor(((left - rect.left) / rect.width) * rect.sourceWidth);
  const y = Math.floor(((top - rect.top) / rect.height) * rect.sourceHeight);
  const x2 = Math.ceil(((right - rect.left) / rect.width) * rect.sourceWidth);
  const y2 = Math.ceil(((bottom - rect.top) / rect.height) * rect.sourceHeight);
  return {
    x: clamp(x, 0, rect.sourceWidth - 1),
    y: clamp(y, 0, rect.sourceHeight - 1),
    width: Math.max(1, clamp(x2, 1, rect.sourceWidth) - x),
    height: Math.max(1, clamp(y2, 1, rect.sourceHeight) - y),
    source_width: rect.sourceWidth,
    source_height: rect.sourceHeight,
  };
}

function alignFeature(value, feature) {
  const increment = Math.max(1, Number(feature.increment || 1));
  const minimum = Number(feature.minimum || 0);
  const maximum = Number(feature.maximum);
  const aligned = minimum + Math.round((value - minimum) / increment) * increment;
  return clamp(aligned, minimum, maximum);
}

function alignFromMinimum(value, feature, maximum) {
  const increment = Math.max(1, Number(feature.increment || 1));
  const minimum = Number(feature.minimum || 0);
  const aligned = minimum + Math.round((value - minimum) / increment) * increment;
  return clamp(aligned, minimum, maximum);
}

function alignCameraRegion(region) {
  const p = state.parameters;
  if (!p?.width || !p?.height || !p?.offset_x || !p?.offset_y) {
    throw new Error("尚未读取相机 ROI 范围");
  }
  const width = alignFeature(region.width, p.width);
  const height = alignFeature(region.height, p.height);
  const currentOffsetX = Number(p.offset_x.value || 0);
  const currentOffsetY = Number(p.offset_y.value || 0);
  const sensorWidth = Math.max(
    Number(p.width.maximum) + currentOffsetX,
    Number(p.width.value) + Number(p.offset_x.maximum),
  );
  const sensorHeight = Math.max(
    Number(p.height.maximum) + currentOffsetY,
    Number(p.height.value) + Number(p.offset_y.maximum),
  );
  const offsetX = alignFromMinimum(
    currentOffsetX + region.x,
    p.offset_x,
    Math.max(0, sensorWidth - width),
  );
  const offsetY = alignFromMinimum(
    currentOffsetY + region.y,
    p.offset_y,
    Math.max(0, sensorHeight - height),
  );
  return {
    ...region,
    x: offsetX - currentOffsetX,
    y: offsetY - currentOffsetY,
    width,
    height,
    offset_x: offsetX,
    offset_y: offsetY,
    type: "camera",
  };
}

function displayBox(box, region, rect) {
  if (!region || !rect || region.source_width !== rect.sourceWidth || region.source_height !== rect.sourceHeight) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  box.style.left = `${rect.left + (region.x / rect.sourceWidth) * rect.width}px`;
  box.style.top = `${rect.top + (region.y / rect.sourceHeight) * rect.height}px`;
  box.style.width = `${(region.width / rect.sourceWidth) * rect.width}px`;
  box.style.height = `${(region.height / rect.sourceHeight) * rect.height}px`;
}

function renderRegions() {
  const rect = imageContentRect();
  const cameraRegion = state.draftRegion?.type === "camera" ? state.draftRegion : null;
  const processingDraft = state.draftRegion?.type === "processing" ? state.draftRegion : null;
  displayBox(elements.cameraRegionBox, cameraRegion, rect);
  displayBox(elements.processingRegionBox, state.processingRegion, rect);
  displayBox(elements.draftRegionBox, state.dragRegion || processingDraft, rect);
}

function updateRegionReadout(region = null) {
  $("selected-x").textContent = region ? region.x : "—";
  $("selected-y").textContent = region ? region.y : "—";
  $("selected-width").textContent = region ? region.width : "—";
  $("selected-height").textContent = region ? region.height : "—";
}

function cancelDrawing() {
  state.drawing = false;
  state.dragStart = null;
  state.dragRegion = null;
  elements.selectionLayer.classList.remove("drawing");
  elements.drawRegionButton.textContent = "开始框选";
  renderRegions();
}

function toggleDrawing() {
  if (state.drawing) {
    cancelDrawing();
    $("draw-help").textContent = "框选已取消。";
    return;
  }
  state.drawing = true;
  state.draftRegion = null;
  state.dragRegion = null;
  updateRegionReadout();
  elements.applyRegionButton.disabled = true;
  elements.selectionLayer.classList.add("drawing");
  elements.selectionLayer.classList.toggle("processing-mode", $("draw-mode").value === "processing");
  elements.drawRegionButton.textContent = "取消框选";
  $("draw-help").textContent = "按住鼠标左键，在实时画面上拖出矩形。";
  renderRegions();
}

function startRegionDrag(event) {
  if (!state.drawing || event.button !== 0) return;
  const rect = imageContentRect();
  if (!rect) return;
  const viewportRect = elements.viewport.getBoundingClientRect();
  const localX = event.clientX - viewportRect.left;
  const localY = event.clientY - viewportRect.top;
  if (
    localX < rect.left || localX > rect.left + rect.width
    || localY < rect.top || localY > rect.top + rect.height
  ) return;
  const point = pointerInImage(event, rect);
  state.dragStart = point;
  state.dragRegion = pixelRegionFromDrag(point, point, rect);
  elements.selectionLayer.setPointerCapture(event.pointerId);
  renderRegions();
}

function moveRegionDrag(event) {
  if (!state.dragStart) return;
  const rect = imageContentRect();
  if (!rect) return;
  state.dragRegion = pixelRegionFromDrag(
    state.dragStart,
    pointerInImage(event, rect),
    rect,
  );
  renderRegions();
}

function finishRegionDrag(event) {
  if (!state.dragStart || !state.dragRegion) return;
  const mode = $("draw-mode").value;
  let region = {...state.dragRegion, type: mode};
  if (mode === "camera") region = alignCameraRegion(region);
  if (region.width < 2 || region.height < 2) {
    cancelDrawing();
    showToast("框选区域太小，请重新拖动", true);
    return;
  }
  state.draftRegion = region;
  state.dragStart = null;
  state.dragRegion = null;
  state.drawing = false;
  elements.selectionLayer.classList.remove("drawing");
  elements.drawRegionButton.textContent = "重新框选";
  elements.applyRegionButton.disabled = false;
  if (mode === "camera") {
    $("roi-width").value = region.width;
    $("roi-height").value = region.height;
    $("roi-offset-x").value = region.offset_x;
    $("roi-offset-y").value = region.offset_y;
    $("roi-centered").checked = false;
    syncRoiControls();
    $("draw-help").textContent = "蓝框已按相机步长对齐，点击“应用框选”写入相机。";
  } else {
    $("draw-help").textContent = "橙色虚线框不会裁图，点击“应用框选”保存处理区域。";
  }
  updateRegionReadout(region);
  elements.selectionLayer.releasePointerCapture(event.pointerId);
  renderRegions();
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

function applyIntegerFeature(id, feature, rangeId) {
  const input = $(id);
  const supported = Boolean(feature);
  input.disabled = !supported;
  if (!supported) {
    $(rangeId).textContent = "相机不支持";
    return;
  }
  input.value = feature.value;
  input.min = feature.minimum;
  input.max = feature.maximum;
  input.step = feature.increment;
  $(rangeId).textContent = `${feature.minimum} — ${feature.maximum}，步长 ${feature.increment}`;
}

async function loadParameters() {
  const payload = await api("/api/camera/parameters");
  const p = payload.parameters;
  state.parameters = p;
  applyFeature("exposure-value", p.exposure_us, "exposure-range");
  applyFeature("gain-value", p.gain_db, "gain-range");
  applyFeature("fps-value", p.frame_rate, "fps-range");
  applyIntegerFeature("roi-width", p.width, "roi-width-range");
  applyIntegerFeature("roi-height", p.height, "roi-height-range");
  applyIntegerFeature("roi-offset-x", p.offset_x, "roi-offset-x-range");
  applyIntegerFeature("roi-offset-y", p.offset_y, "roi-offset-y-range");
  $("exposure-mode").disabled = !p.capabilities.exposure_mode;
  $("gain-mode").disabled = !p.capabilities.gain_mode;
  $("white-balance-mode").disabled = !p.capabilities.white_balance_mode;
  $("fps-enabled").disabled = !p.capabilities.frame_rate_enabled;
  if (p.exposure_mode) $("exposure-mode").value = p.exposure_mode;
  if (p.gain_mode) $("gain-mode").value = p.gain_mode;
  if (p.white_balance_mode) $("white-balance-mode").value = p.white_balance_mode;
  $("fps-enabled").checked = Boolean(p.frame_rate_enabled);
  syncParameterControls();
  syncRoiControls();
  if (!state.drawing && !state.draftRegion) {
    $("draw-help").textContent = $("draw-mode").value === "camera"
      ? "拖框后会按相机步长对齐，应用后框外不再采集。"
      : "拖框后只保存处理坐标，完整画面继续保留。";
  }
}

function syncParameterControls() {
  const connected = !elements.imagingFields.disabled;
  const capabilities = state.parameters?.capabilities || {};
  $("exposure-value").disabled = !connected || !capabilities.exposure_us || (capabilities.exposure_mode && $("exposure-mode").value !== "off");
  $("gain-value").disabled = !connected || !capabilities.gain_db || (capabilities.gain_mode && $("gain-mode").value !== "off");
  $("fps-value").disabled = !connected || !capabilities.frame_rate || (capabilities.frame_rate_enabled && !$("fps-enabled").checked);
}

function syncRoiControls() {
  const centered = $("roi-centered").checked;
  const capabilities = state.parameters?.capabilities || {};
  $("roi-offset-x").disabled = centered || !capabilities.offset_x;
  $("roi-offset-y").disabled = centered || !capabilities.offset_y;
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

async function applyRoi() {
  const capabilities = state.parameters?.capabilities || {};
  if (!capabilities.width || !capabilities.height) {
    throw new Error("当前相机不支持修改采集宽度或高度");
  }
  const centered = $("roi-centered").checked;
  const values = {
    width: numberValue("roi-width"),
    height: numberValue("roi-height"),
    centered,
  };
  if (!centered) {
    if (capabilities.offset_x) values.offset_x = numberValue("roi-offset-x");
    if (capabilities.offset_y) values.offset_y = numberValue("roi-offset-y");
  }
  const clearedProcessingRegion = Boolean(state.processingRegion);
  const payload = await api("/api/camera/roi", { method: "PUT", body: JSON.stringify(values) });
  state.parameters = payload.parameters;
  state.draftRegion = null;
  state.processingRegion = null;
  updateRegionReadout();
  elements.applyRegionButton.disabled = true;
  await loadParameters();
  await pollStatus();
  renderRegions();
  showToast("相机 ROI 已应用");
  logEvent(`相机采集 ROI 已设为 ${values.width} × ${values.height}${centered ? "，并已居中" : ""}。${clearedProcessingRegion ? "采集坐标已改变，原处理区域已清除。" : ""}`);
}

async function applyDrawnRegion() {
  const region = state.draftRegion;
  if (!region) throw new Error("请先在画面上框选区域");
  if (region.type === "camera") {
    await applyRoi();
    return;
  }
  const payload = await api("/api/processing-region", {
    method: "PUT",
    body: JSON.stringify({
      x: region.x,
      y: region.y,
      width: region.width,
      height: region.height,
    }),
  });
  state.processingRegion = payload.region;
  state.draftRegion = null;
  elements.applyRegionButton.disabled = true;
  elements.clearRegionButton.disabled = false;
  updateRegionReadout(state.processingRegion);
  renderRegions();
  showToast("处理区域已保存");
  logEvent(`处理区域已保存：X=${payload.region.x}，Y=${payload.region.y}，${payload.region.width} × ${payload.region.height}；完整画面继续保留。`);
}

async function clearProcessingRegion() {
  await api("/api/processing-region", { method: "DELETE" });
  state.processingRegion = null;
  if (state.draftRegion?.type === "processing") state.draftRegion = null;
  elements.clearRegionButton.disabled = true;
  elements.applyRegionButton.disabled = !state.draftRegion;
  updateRegionReadout(state.draftRegion);
  renderRegions();
  showToast("处理区域已清除");
  logEvent("处理区域已清除，完整画面不受影响。");
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
  $("apply-roi-button").addEventListener("click", (event) => withBusy(event.currentTarget, applyRoi).catch(() => {}));
  elements.drawRegionButton.addEventListener("click", toggleDrawing);
  elements.applyRegionButton.addEventListener("click", (event) => withBusy(event.currentTarget, applyDrawnRegion).then(() => {
    event.currentTarget.disabled = !state.draftRegion;
  }).catch(() => {}));
  elements.clearRegionButton.addEventListener("click", (event) => withBusy(event.currentTarget, clearProcessingRegion).then(() => {
    event.currentTarget.disabled = !state.processingRegion;
  }).catch(() => {}));
  $("draw-mode").addEventListener("change", () => {
    cancelDrawing();
    state.draftRegion = null;
    elements.applyRegionButton.disabled = true;
    updateRegionReadout($("draw-mode").value === "processing" ? state.processingRegion : null);
    $("draw-help").textContent = $("draw-mode").value === "camera"
      ? "拖框后会按相机步长对齐，应用后框外不再采集。"
      : "拖框后只保存处理坐标，完整画面继续保留。";
    renderRegions();
  });
  elements.selectionLayer.addEventListener("pointerdown", startRegionDrag);
  elements.selectionLayer.addEventListener("pointermove", moveRegionDrag);
  elements.selectionLayer.addEventListener("pointerup", finishRegionDrag);
  elements.selectionLayer.addEventListener("pointercancel", cancelDrawing);
  $("exposure-mode").addEventListener("change", syncParameterControls);
  $("gain-mode").addEventListener("change", syncParameterControls);
  $("fps-enabled").addEventListener("change", syncParameterControls);
  $("roi-centered").addEventListener("change", syncRoiControls);
  elements.preview.addEventListener("error", () => {
    if (state.status.connected) logEvent("实时预览中断，正在等待重新连接。", true);
  });
  elements.preview.addEventListener("load", renderRegions);
  window.addEventListener("resize", renderRegions);
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
    if (statusPayload.status.connected) {
      startPreview();
      await loadParameters();
    }
    await withBusy($("scan-button"), scanDevices);
  } catch (error) {
    showToast(error.message, true);
    logEvent(error.message, true);
  }
  setInterval(pollStatus, 1000);
}

initialize();

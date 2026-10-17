// Shared controls for MVS, DroidCam, OBS, and native Capture/UVC.
const state = {
  config: null,
  devices: [],
  parameters: null,
  status: { connected: false, auto_capture: false, recording: false },
  streamStarted: false,
  previewGeneration: 0,
  previewController: null,
  previewObjectUrl: "",
  previewSequence: -1,
  browserFrameTimes: [],
  scanPromise: null,
  formatGeneration: 0,
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
  restoreFullRoiButton: $("restore-full-roi-button"),
  toast: $("toast"),
};

function isMvsSource() {
  return $("source-type").value === "mvs";
}

function isDroidCamClient() {
  return $("source-type").value === "droidcam_client";
}

function isObsSource() {
  return $("source-type").value === "obs_droidcam";
}

function isUvcSource() {
  return $("source-type").value === "capture_uvc";
}

function isFrameSource() {
  return !isObsSource();
}

function updateSourceUi() {
  const mvs = isMvsSource();
  const client = isDroidCamClient();
  const obs = isObsSource();
  const uvc = isUvcSource();
  document.body.classList.toggle("obs-mode", obs);
  document.body.classList.toggle("uvc-mode", uvc);
  document.querySelectorAll(".mvs-only").forEach((element) => {
    element.hidden = !mvs;
  });
  document.querySelectorAll(".client-only").forEach((element) => {
    element.hidden = !client;
  });
  document.querySelectorAll(".frame-source-only").forEach((element) => {
    element.hidden = obs;
  });
  document.querySelectorAll(".uvc-only").forEach((element) => {
    element.hidden = !uvc;
  });
  $("region-selection-tools").hidden = uvc;
  document.querySelector(".imaging-panel").hidden = obs;
  elements.imagingFields.hidden = uvc;
  ["photo-format", "jpeg-quality"].forEach((id) => { $(id).closest(".field").hidden = obs || uvc; });
  ["recording-fps", "recording-duplicated", "recording-dropped"].forEach((id) => {
    const value = $(id).parentElement;
    value.hidden = obs || uvc;
    value.previousElementSibling.hidden = obs || uvc;
  });
  $("output-size-title").textContent = uvc ? "预览最大尺寸" : "统一输出尺寸";
  $("save-output-size-button").textContent = uvc ? "应用预览尺寸" : "应用输出尺寸";
  $("metric-lost").parentElement.hidden = obs || uvc;
  $("output-size-help").textContent = uvc
    ? "仅缩小网页预览；照片和录像保留采集格式的原始尺寸。MJPEG 不缩小时直接预览。"
    : "统一控制预览、照片和录像，保持比例缩小；不会放大原图，也不改变相机 ROI 和取景范围。";
  $("video-format").querySelector('[value="mp4"]').textContent = uvc ? "H.264 / MP4" : "MP4";
  $("video-format").querySelector('[value="avi"]').textContent = uvc ? "MJPEG 直通 / AVI" : "AVI";
  $("camera-roi-option").disabled = !mvs;
  if (!mvs && $("draw-mode").value === "camera") {
    $("draw-mode").value = "processing";
  }
  $("connection-help").textContent = mvs
    ? "IP 只用于选择已枚举的 MVS 相机，不会修改相机网络配置。"
    : uvc
      ? "请先停止 capture.exe 中的采集，再连接网页。先选择设备和格式；光照不足时相机可能自动降低帧率。"
    : client
      ? "通过 DroidCam Client 的 Windows 虚拟摄像头读取画面。"
      : "通过本机 OBS WebSocket 控制 DroidCam 输入；连接时自动准备仅含手机画面的专用场景。";
  $("output-help").textContent = obs
    ? "OBS 截图固定保存为 PNG；录像格式和尺寸沿用 OBS 设置，录像目录在每次开始时应用。"
    : uvc
      ? "照片固定为原始尺寸 JPG，拍照会等待曝光稳定。AVI 为 MJPEG 直通；MP4 使用内核 H.264 编码及硬件编码回退。格式或尺寸切换前须断开相机。"
    : "输出最大宽高已移到实时画面右侧；这里保存照片、录像格式和目录设置。";
  $("empty-state").textContent = obs
    ? "连接 OBS 后在这里显示实时取景预览"
    : "连接相机后在这里显示实时画面";
  $("metric-browser-label").textContent = obs ? "网页刷新" : "浏览器";
  $("metric-age-label").textContent = obs ? "预览耗时" : "帧龄";
  $("video-dir-label").textContent = obs ? "本次录像目录" : "视频目录";
  $("scan-button").textContent = obs ? "刷新 OBS 来源" : "刷新设备";
  $("metric-lost-label").textContent = mvs ? "丢包" : "取帧错误";
  $("draw-help").textContent = mvs && $("draw-mode").value === "camera"
    ? "连接相机后拖框设置硬件 ROI。"
    : "连接后可框选处理区域，完整画面仍然保留。";
}

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
  const item = document.createElement("li");
  item.classList.toggle("error", isError);
  const timestamp = document.createElement("time");
  timestamp.textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  const content = document.createElement("span");
  content.textContent = message;
  item.append(timestamp, content);
  const log = $("event-log");
  log.prepend(item);
  while (log.children.length > 50) log.lastElementChild.remove();
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
  $("source-type").value = config.source_type || "mvs";
  $("camera-ip").value = config.camera.ip;
  $("camera-serial").value = config.camera.serial;
  $("sdk-path").value = config.camera.sdk_python_path;
  $("frame-timeout").value = config.camera.frame_timeout_ms;
  const standard = config.droidcam_client || {};
  $("standard-camera-index").value = standard.device_index ?? 0;
  $("standard-width").value = standard.requested_width ?? 1280;
  $("standard-height").value = standard.requested_height ?? 720;
  $("standard-fps").value = standard.requested_fps ?? 30;
  const obs = config.obs_droidcam || {};
  const uvc = config.capture_uvc || {};
  $("uvc-library-path").value = uvc.library_path || "../capture/build/bin/capturecore.dll";
  elements.deviceSelect.dataset.uvcDevice = uvc.device_id || "";
  $("uvc-format").value = String(uvc.format_index ?? -1);
  $("device-select").dataset.obsSource = obs.source_name || "";
  $("photo-dir").value = config.capture.photo_dir;
  $("video-dir").value = config.capture.video_dir;
  $("photo-format").value = config.capture.photo_format;
  $("jpeg-quality").value = config.capture.jpeg_quality;
  $("auto-interval").value = config.capture.auto_interval_seconds;
  $("video-format").value = config.capture.video_format;
  $("output-max-width").value = config.capture.output_max_width;
  $("output-max-height").value = config.capture.output_max_height;
  updateSourceUi();
}

function collectConfig() {
  return {
    source_type: $("source-type").value,
    camera: {
      ip: $("camera-ip").value.trim(),
      serial: $("camera-serial").value.trim(),
      sdk_python_path: $("sdk-path").value.trim(),
      frame_timeout_ms: numberValue("frame-timeout"),
    },
    droidcam_client: {
      ...(state.config?.droidcam_client || {}),
      device_index: numberValue("standard-camera-index"),
      device_name: state.devices.find((device) => device.index === numberValue("standard-camera-index"))?.model
        || state.config?.droidcam_client?.device_name
        || "",
      requested_width: numberValue("standard-width"),
      requested_height: numberValue("standard-height"),
      requested_fps: numberValue("standard-fps"),
    },
    obs_droidcam: {
      ...(state.config?.obs_droidcam || {}),
      source_name: isObsSource()
        ? (state.devices[Number(elements.deviceSelect.value)]?.model || elements.deviceSelect.dataset.obsSource || "")
        : (state.config?.obs_droidcam?.source_name || ""),
      photo_prefix: state.config?.obs_droidcam?.photo_prefix || "phone",
    },
    capture_uvc: {
      ...(state.config?.capture_uvc || {}),
      library_path: $("uvc-library-path").value.trim(),
      device_id: isUvcSource()
        ? (state.devices[Number(elements.deviceSelect.value)]?.device_id || elements.deviceSelect.dataset.uvcDevice || "")
        : (state.config?.capture_uvc?.device_id || ""),
      format_index: isUvcSource() ? numberValue("uvc-format") : (state.config?.capture_uvc?.format_index ?? -1),
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
  const source = $("source-type").value;
  const payload = await api(`/api/devices?source=${encodeURIComponent(source)}`);
  state.devices = payload.devices;
  elements.deviceSelect.replaceChildren();
  if (!state.devices.length) {
    elements.deviceSelect.add(new Option("未发现相机", ""));
    logEvent(isMvsSource()
      ? "未发现 MVS 相机，请检查供电、网线和网卡地址。"
      : isUvcSource() ? "未发现 Capture/UVC 相机，请检查 USB 连接。"
      : isDroidCamClient()
        ? "未发现 DroidCam Client 摄像头，请确认客户端正在显示画面。"
        : "未发现 OBS DroidCam 来源，请确认 OBS、WebSocket 和 DroidCam 插件已启用。", true);
    return;
  }
  state.devices.forEach((device, index) => {
    const detail = isMvsSource()
      ? (device.ip || device.serial)
      : isUvcSource() ? device.user_name
      : isDroidCamClient()
        ? (device.user_name || `编号 ${device.index}`)
        : "OBS 输入源";
    elements.deviceSelect.add(new Option(`${device.model} · ${detail}`, String(index)));
  });
  const configured = state.devices.findIndex((device) => isMvsSource()
    ? ((state.config.camera.ip && device.ip === state.config.camera.ip)
      || (state.config.camera.serial && device.serial === state.config.camera.serial))
    : isUvcSource() ? device.device_id === (state.config.capture_uvc?.device_id || elements.deviceSelect.dataset.uvcDevice)
    : isDroidCamClient()
      ? device.index === numberValue("standard-camera-index")
      : device.model === (state.config.obs_droidcam?.source_name || elements.deviceSelect.dataset.obsSource));
  elements.deviceSelect.value = String(configured >= 0 ? configured : 0);
  await selectDevice();
  const sourceLabel = isMvsSource() ? "台 MVS 相机" : isUvcSource() ? "台 Capture/UVC 相机" : isDroidCamClient() ? "个 DroidCam Client 摄像头" : "个 OBS DroidCam 来源";
  logEvent(`发现 ${state.devices.length} ${sourceLabel}。`);
}

async function selectDevice() {
  const device = state.devices[Number(elements.deviceSelect.value)];
  if (!device) return;
  if (isMvsSource()) {
    $("camera-ip").value = device.ip;
    $("camera-serial").value = device.serial;
  } else if (isDroidCamClient()) {
    $("standard-camera-index").value = device.index;
  } else if (isUvcSource()) {
    elements.deviceSelect.dataset.uvcDevice = device.device_id;
    await loadUvcFormats(device.device_id);
  } else {
    elements.deviceSelect.dataset.obsSource = device.model;
  }
}

async function loadUvcFormats(deviceId) {
  const generation = ++state.formatGeneration;
  const select = $("uvc-format");
  select.disabled = true;
  $("uvc-format-help").textContent = "正在读取设备格式…";
  try {
    const payload = await api(`/api/capture-uvc/formats?device_id=${encodeURIComponent(deviceId)}`);
    if (generation !== state.formatGeneration || !isUvcSource()) return;
    select.replaceChildren(new Option("自动选择（优先 MJPEG）", "-1"));
    payload.formats.forEach((format) => select.add(new Option(
      `${format.name} · ${format.width} × ${format.height} · ${format.fps} FPS`, String(format.index),
    )));
    const configured = state.config?.capture_uvc;
    select.value = configured?.device_id === deviceId ? String(configured.format_index) : "-1";
    if (!select.value) select.value = "-1";
    $("uvc-format-help").textContent = `已读取 ${payload.formats.length} 种格式；标称帧率以实际采集为准。`;
  } catch (error) {
    if (generation === state.formatGeneration) $("uvc-format-help").textContent = error.message;
    throw error;
  } finally {
    if (generation === state.formatGeneration) select.disabled = Boolean(state.status.connected);
  }
}

async function connectOrDisconnect() {
  if (state.status.connected) {
    const payload = await api("/api/camera/disconnect", { method: "POST" });
    updateStatus(payload.status);
    logEvent(isMvsSource()
      ? "MVS 相机已断开，SDK 资源已释放。"
      : isUvcSource() ? "Capture/UVC 已断开，原生会话已释放。"
      : isDroidCamClient()
        ? "DroidCam Client 已断开，OpenCV 读取句柄已释放。"
        : "OBS DroidCam 控制已断开。");
    return;
  }
  await saveConfig("连接配置已保存");
  const payload = await api("/api/camera/connect", { method: "POST" });
  updateStatus(payload.status);
  startPreview();
  if (isFrameSource()) api("/api/count/prepare", { method: "POST" }).catch(() => {});
  if (isFrameSource()) await loadParameters();
  const deviceDetail = payload.status.device.ip || payload.status.device.user_name || payload.status.device.serial;
  logEvent(`已连接 ${payload.status.device.model}（${deviceDetail}）。`);
}

function startPreview() {
  if (state.streamStarted) return;
  state.streamStarted = true;
  state.previewGeneration += 1;
  state.previewSequence = -1;
  state.browserFrameTimes = [];
  state.previewController = new AbortController();
  pullLatestFrames(state.previewGeneration, state.previewController.signal);
}

function stopPreview() {
  state.streamStarted = false;
  state.previewGeneration += 1;
  state.previewController?.abort();
  state.previewController = null;
  if (state.previewObjectUrl) URL.revokeObjectURL(state.previewObjectUrl);
  state.previewObjectUrl = "";
  elements.preview.removeAttribute("src");
  $("metric-browser-fps").textContent = "0.0";
  $("metric-frame-age").textContent = "—";
}

function displayPreviewBlob(blob, generation) {
  return new Promise((resolve, reject) => {
    const objectUrl = URL.createObjectURL(blob);
    const previousUrl = state.previewObjectUrl;
    const cleanup = () => {
      elements.preview.removeEventListener("load", loaded);
      elements.preview.removeEventListener("error", failed);
    };
    const loaded = () => {
      cleanup();
      if (previousUrl) URL.revokeObjectURL(previousUrl);
      if (generation === state.previewGeneration) state.previewObjectUrl = objectUrl;
      else URL.revokeObjectURL(objectUrl);
      resolve();
    };
    const failed = () => {
      cleanup();
      URL.revokeObjectURL(objectUrl);
      reject(new Error("浏览器无法解码实时预览帧"));
    };
    elements.preview.addEventListener("load", loaded);
    elements.preview.addEventListener("error", failed);
    elements.preview.src = objectUrl;
  });
}

function updateBrowserPreviewMetrics(capturedAtMs) {
  const now = Date.now();
  state.browserFrameTimes.push(now);
  state.browserFrameTimes = state.browserFrameTimes.filter((value) => now - value <= 2000);
  let fps = 0;
  if (state.browserFrameTimes.length >= 2) {
    const elapsed = state.browserFrameTimes.at(-1) - state.browserFrameTimes[0];
    if (elapsed > 0) fps = (state.browserFrameTimes.length - 1) * 1000 / elapsed;
  }
  $("metric-browser-fps").textContent = fps.toFixed(1);
  $("metric-frame-age").textContent = capturedAtMs > 0 ? `${Math.max(0, now - capturedAtMs)} ms` : "—";
}

async function pullLatestFrames(generation, signal) {
  try {
    while (state.streamStarted && generation === state.previewGeneration && !signal.aborted) {
      const response = await fetch(`/api/camera/frame?after=${state.previewSequence}`, {
        cache: "no-store",
        signal,
      });
      if (response.status === 204) continue;
      if (!response.ok) throw new Error(`实时预览请求失败（HTTP ${response.status}）`);
      const sequence = Number(response.headers.get("X-Frame-Sequence"));
      const capturedAtMs = Number(response.headers.get("X-Frame-Captured-At-Ms"));
      const blob = await response.blob();
      if (signal.aborted || generation !== state.previewGeneration) return;
      await displayPreviewBlob(blob, generation);
      state.previewSequence = Number.isFinite(sequence) ? sequence : state.previewSequence + 1;
      updateBrowserPreviewMetrics(capturedAtMs);
    }
  } catch (error) {
    if (signal.aborted || generation !== state.previewGeneration) return;
    state.streamStarted = false;
    logEvent(`实时预览中断：${error.message}`, true);
  }
}

function updateStatus(status) {
  state.status = status;
  const connected = Boolean(status.connected);
  const mvs = isMvsSource();
  elements.stage.classList.toggle("online", connected);
  elements.connectionPill.classList.toggle("online", connected);
  elements.connectionText.textContent = connected ? (isObsSource() ? "OBS 已连接" : "相机在线") : "未连接";
  elements.connectButton.querySelector("span").textContent = connected
    ? (isObsSource() ? "断开 OBS" : "断开相机")
    : (isObsSource() ? "连接 OBS" : "连接相机");
  elements.snapshotButton.disabled = !connected;
  elements.autoButton.disabled = !connected;
  elements.recordButton.disabled = !connected;
  elements.imagingFields.disabled = !connected || !mvs;
  $("uvc-imaging-fields").disabled = !connected || !isUvcSource();
  if (isUvcSource() && !connected) {
    $("uvc-properties").replaceChildren();
    $("uvc-imaging-help").textContent = "连接后读取设备实际支持的成像参数。";
  }
  updateExposureFpsGuidance();
  elements.roiFields.disabled = !connected || !mvs;
  elements.drawRegionButton.disabled = !connected || !isFrameSource();
  elements.restoreFullRoiButton.disabled = !connected || !mvs;
  $("source-type").disabled = connected;
  $("uvc-library-path").disabled = connected && isUvcSource();
  $("uvc-format").disabled = connected && isUvcSource();
  elements.deviceSelect.disabled = connected && isUvcSource();
  elements.autoButton.textContent = status.auto_capture ? "停止自动拍照" : "开始自动拍照";
  elements.recordButton.querySelector("span").textContent = status.recording ? "停止录像" : "开始录像";
  elements.recordButton.classList.toggle("active", Boolean(status.recording));
  elements.recordingBadge.classList.toggle("active", Boolean(status.recording));
  $("device-name").textContent = status.device
    ? `${status.device.model}${status.device.user_name ? ` / ${status.device.user_name}` : ""}`
    : "等待相机";
  $("metric-resolution").textContent = status.width ? `${status.width} × ${status.height}` : "—";
  $("metric-preview-resolution").textContent = status.preview_width ? `${status.preview_width} × ${status.preview_height}` : "—";
  $("metric-capture-fps").textContent = Number(status.capture_fps ?? status.fps ?? 0).toFixed(1);
  $("metric-preview-fps").textContent = Number(status.preview_fps || 0).toFixed(1);
  $("metric-lost").textContent = isUvcSource() ? "—" : (status.lost_packets || 0);
  $("uvc-written-frames").textContent = status.recording_result?.frames_written ?? "—";
  $("uvc-encoder").textContent = status.recording_result?.encoder || "停止录像后显示";
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
  const sensor = sensorDimensions();
  const offsetX = alignFromMinimum(
    currentOffsetX + region.x,
    p.offset_x,
    Math.max(0, sensor.width - width),
  );
  const offsetY = alignFromMinimum(
    currentOffsetY + region.y,
    p.offset_y,
    Math.max(0, sensor.height - height),
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
    $("draw-help").textContent = "橙色虚线框不会裁图；当前版本只保存坐标，接入增强或检测后才会限定算法范围。";
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

function calculateExposureFpsTiming(exposureUs, targetFps) {
  if (!Number.isFinite(exposureUs) || !Number.isFinite(targetFps) || exposureUs <= 0 || targetFps <= 0) {
    return null;
  }
  const framePeriodUs = 1_000_000 / targetFps;
  const recommendedExposureUs = framePeriodUs * 0.9;
  const theoreticalMaxFps = 1_000_000 / exposureUs;
  const recommendedMaxFps = theoreticalMaxFps * 0.9;
  const ratio = exposureUs / framePeriodUs;
  const level = ratio >= 0.999999 ? "danger" : (ratio >= 0.899999 ? "warning" : (ratio <= 0.25 ? "info" : "ok"));
  return {
    level,
    framePeriodUs,
    recommendedExposureUs,
    theoreticalMaxFps,
    recommendedMaxFps,
    ratio,
  };
}

function setTimingAdvice(id, level, message) {
  const advice = $(id);
  advice.className = `timing-advice${level ? ` ${level}` : ""}`;
  advice.textContent = message;
}

function updateExposureFpsGuidance() {
  const capabilities = state.parameters?.capabilities || {};
  if (elements.imagingFields.disabled || !state.parameters || !capabilities.exposure_us || !capabilities.frame_rate) {
    setTimingAdvice("exposure-timing-advice", "", "连接支持成像参数的 MVS 相机后显示时序余量。");
    setTimingAdvice("fps-timing-advice", "", "连接支持成像参数的 MVS 相机后显示建议上限。");
    return;
  }
  const exposureIsAutomatic = capabilities.exposure_mode && $("exposure-mode").value !== "off";
  const fpsLimitIsOff = capabilities.frame_rate_enabled && !$("fps-enabled").checked;

  if (exposureIsAutomatic) {
    setTimingAdvice("exposure-timing-advice", "warning", "自动曝光会改变曝光时长；光线不足时，实际帧率可能随曝光增加而下降。");
    setTimingAdvice("fps-timing-advice", "warning", "需要稳定帧率时建议使用手动曝光，并让曝光短于目标帧周期。当前自动曝光无法保证目标 FPS。");
    return;
  }
  if (fpsLimitIsOff) {
    setTimingAdvice("exposure-timing-advice", "info", "帧率限制未启用；曝光越长，相机可输出的最高帧率越低。");
    setTimingAdvice("fps-timing-advice", "info", "启用帧率限制后，这里会根据曝光时间显示可达到的建议上限。");
    return;
  }

  const exposureUs = Number($("exposure-value").value);
  const targetFps = Number($("fps-value").value);
  const timing = calculateExposureFpsTiming(exposureUs, targetFps);
  if (!timing) {
    setTimingAdvice("exposure-timing-advice", "danger", "曝光时间和目标帧率都必须是大于 0 的数字。");
    setTimingAdvice("fps-timing-advice", "danger", "曝光时间和目标帧率都必须是大于 0 的数字。");
    return;
  }

  const exposureMs = exposureUs / 1000;
  const periodMs = timing.framePeriodUs / 1000;
  const recommendedExposureMs = timing.recommendedExposureUs / 1000;
  if (timing.level === "danger") {
    setTimingAdvice("exposure-timing-advice", "danger", `目标 ${targetFps.toFixed(1)} FPS 每帧只有 ${periodMs.toFixed(1)} ms；当前曝光 ${exposureMs.toFixed(1)} ms 已达到或超过帧周期，无法达到目标。`);
  } else if (timing.level === "warning") {
    setTimingAdvice("exposure-timing-advice", "warning", `目标 ${targetFps.toFixed(1)} FPS 的帧周期是 ${periodMs.toFixed(1)} ms；建议曝光不超过 ${recommendedExposureMs.toFixed(1)} ms，为读出和传输留出余量。`);
  } else if (timing.level === "info") {
    setTimingAdvice("exposure-timing-advice", "info", `当前曝光仅占帧周期的 ${(timing.ratio * 100).toFixed(0)}%，不会限制目标帧率；若画面偏暗，可在建议上限 ${recommendedExposureMs.toFixed(1)} ms 内增加曝光。`);
  } else {
    setTimingAdvice("exposure-timing-advice", "ok", `时序余量正常：${targetFps.toFixed(1)} FPS 建议曝光不超过 ${recommendedExposureMs.toFixed(1)} ms。`);
  }
  setTimingAdvice(
    "fps-timing-advice",
    timing.level,
    `按当前 ${exposureMs.toFixed(1)} ms 曝光，理论上限 ${timing.theoreticalMaxFps.toFixed(1)} FPS；预留 10% 读出余量后建议目标不超过 ${timing.recommendedMaxFps.toFixed(1)} FPS。`,
  );
}

async function loadParameters() {
  const payload = await api("/api/camera/parameters");
  const p = payload.parameters;
  state.parameters = p;
  if (isUvcSource()) {
    renderUvcParameters(p);
    return;
  }
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
  updateCurrentRoiText();
  if (!isMvsSource()) {
    $("draw-help").textContent = "拖框可保存处理区域，完整画面保留；DroidCam 参数仍在其客户端中设置。";
    return;
  }
  if (!state.drawing && !state.draftRegion) {
    $("draw-help").textContent = $("draw-mode").value === "camera"
      ? "拖框后会按相机步长对齐，应用后框外不再采集。"
      : "只保存算法区域坐标，完整画面保留；当前尚未接入处理算法。";
  }
}

const uvcPropertyLabels = {
  1: "亮度", 2: "对比度", 3: "饱和度", 4: "色调", 5: "锐度", 6: "增益",
  7: "伽马", 8: "自动白平衡", 9: "白平衡色温", 10: "工频抗闪烁",
  11: "曝光模式", 12: "曝光时间", 13: "允许自动曝光降低帧率",
  14: "自动对焦", 15: "对焦位置", 16: "变焦", 17: "水平转动",
  18: "垂直转动", 19: "旋转",
};

function renderUvcParameters(parameters) {
  const properties = parameters.uvc_properties || [];
  const container = $("uvc-properties");
  container.replaceChildren();
  const exposureAvailable = properties.some((property) => [11, 12].includes(property.id));
  $("uvc-imaging-help").textContent = properties.length
    ? `已读取 ${properties.length} 项成像参数。${exposureAvailable ? "" : "当前设备的 Windows 驱动未暴露曝光控制，网页无法调节曝光。"}`
    : "当前设备或驱动未提供可用的成像参数。";
  properties.forEach((property) => {
    const field = document.createElement("div");
    field.className = "field";
    const label = document.createElement("label");
    const unit = { 1: "%", 2: "K", 3: "μs", 4: "Hz" }[property.unit] || "";
    const title = uvcPropertyLabels[property.id] || property.name;
    label.textContent = `${title}${unit ? `（${unit}）` : ""}`;
    const control = document.createElement(property.type === 0 ? "input" : "select");
    control.id = `uvc-property-${property.id}`;
    label.htmlFor = control.id;
    if (property.type === 0) {
      control.type = "number";
      control.min = property.minimum;
      control.max = property.maximum;
      control.step = property.step > 0 ? property.step : 1;
    } else {
      const exposureNames = { 0: "手动", 1: "全自动", 2: "快门优先", 3: "光圈优先" };
      const options = property.type === 1
        ? [{ value: 0, name: "关闭" }, { value: 1, name: "开启" }]
        : property.options.map((option) => ({
          value: option.value,
          name: property.id === 11 ? (exposureNames[option.value] || option.name) : option.name,
        }));
      options.forEach((option) => control.add(new Option(option.name, String(option.value))));
      if (!options.some((option) => option.value === property.value)) {
        const unknown = new Option(`当前值：${property.value}（未列出的选项）`, String(property.value));
        unknown.disabled = true;
        control.add(unknown);
      }
    }
    control.value = property.value;
    const locked = Boolean((property.flags & 3) || property.is_auto);
    control.disabled = locked;
    const help = document.createElement("small");
    help.id = `${control.id}-help`;
    help.textContent = `设备当前值：${property.value}${unit ? ` ${unit}` : ""}。`
      + (property.type === 0 ? `范围 ${property.minimum}–${property.maximum}；${property.step > 0 ? `步长 ${property.step}` : "由驱动按档位换算"}。` : "")
      + (property.flags & 2 ? "设备暂时禁用。" : property.is_auto ? "自动模式控制中。" : property.flags & 1 ? "当前只读。" : "");
    control.setAttribute("aria-describedby", help.id);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button";
    button.textContent = "应用";
    button.setAttribute("aria-label", `应用${title}`);
    button.disabled = locked;
    button.addEventListener("click", () => withBusy(button, async () => {
      if (!control.value || !control.reportValidity()) throw new Error("请输入设备允许的参数值");
      const value = Number(control.value);
      if (!Number.isSafeInteger(value)) throw new Error("成像参数必须为有效整数");
      try {
        const payload = await api("/api/camera/parameters", {
          method: "PUT", body: JSON.stringify({ property_id: property.id, value }),
        });
        state.parameters = payload.parameters;
        renderUvcParameters(payload.parameters);
        showToast(`${title}已应用，已回读设备实际值`);
        logEvent(`${title}已写入相机。`);
      } catch (error) {
        // 写入或回读失败也刷新，避免继续展示已经过期的模式锁定状态。
        await loadParameters().catch(() => {});
        throw error;
      }
    }).catch(() => {}));
    field.append(label, control, help, button);
    container.append(field);
  });
}

function sensorDimensions() {
  const p = state.parameters;
  if (!p?.width || !p?.height || !p?.offset_x || !p?.offset_y) return null;
  const offsetX = Number(p.offset_x.value || 0);
  const offsetY = Number(p.offset_y.value || 0);
  return {
    width: Math.max(
      Number(p.width.maximum) + offsetX,
      Number(p.width.value) + Number(p.offset_x.maximum),
    ),
    height: Math.max(
      Number(p.height.maximum) + offsetY,
      Number(p.height.value) + Number(p.offset_y.maximum),
    ),
  };
}

function updateCurrentRoiText() {
  const p = state.parameters;
  const sensor = sensorDimensions();
  if (!p?.width || !sensor) {
    $("current-roi").textContent = "当前采集区域：—";
    return;
  }
  $("current-roi").textContent = `当前采集区域：${p.width.value} × ${p.height.value}，传感器起点 X=${p.offset_x.value}、Y=${p.offset_y.value}；完整传感器 ${sensor.width} × ${sensor.height}`;
}

function syncParameterControls() {
  const connected = !elements.imagingFields.disabled;
  const capabilities = state.parameters?.capabilities || {};
  $("exposure-value").disabled = !connected || !capabilities.exposure_us || (capabilities.exposure_mode && $("exposure-mode").value !== "off");
  $("gain-value").disabled = !connected || !capabilities.gain_db || (capabilities.gain_mode && $("gain-mode").value !== "off");
  $("fps-value").disabled = !connected || !capabilities.frame_rate || (capabilities.frame_rate_enabled && !$("fps-enabled").checked);
  updateExposureFpsGuidance();
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
  updateExposureFpsGuidance();
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
  logEvent(`相机采集 ROI 已设为 ${payload.parameters.width.value} × ${payload.parameters.height.value}，传感器起点 X=${payload.parameters.offset_x.value}、Y=${payload.parameters.offset_y.value}。${clearedProcessingRegion ? "采集坐标已改变，原处理区域已清除。" : ""}`);
}

async function restoreFullRoi() {
  const sensor = sensorDimensions();
  if (!sensor) throw new Error("尚未读取完整传感器尺寸");
  $("roi-width").value = sensor.width;
  $("roi-height").value = sensor.height;
  $("roi-centered").checked = true;
  syncRoiControls();
  await applyRoi();
  showToast("已恢复完整画面");
  logEvent(`相机已恢复完整采集画面 ${sensor.width} × ${sensor.height}。`);
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
  logEvent(payload.status.recording
    ? `录像已开始，保存目录：${$("video-dir").value}`
    : `录像已停止：${payload.path || "未生成文件"}`);
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
  elements.deviceSelect.addEventListener("change", () => {
    selectDevice().catch((error) => { showToast(error.message, true); logEvent(error.message, true); });
  });
  $("source-type").addEventListener("change", () => {
    state.formatGeneration += 1;
    updateSourceUi();
    updateStatus(state.status);
    state.devices = [];
    elements.deviceSelect.replaceChildren(new Option("点击刷新枚举相机", ""));
    withBusy($("scan-button"), scanDevices).catch(() => {});
  });
  $("scan-button").addEventListener("click", (event) => withBusy(event.currentTarget, scanDevices).catch(() => {}));
  $("save-config-button").addEventListener("click", (event) => withBusy(event.currentTarget, () => saveConfig()).catch(() => {}));
  $("save-output-button").addEventListener("click", (event) => withBusy(event.currentTarget, () => saveConfig("输出设置已保存")).catch(() => {}));
  $("save-output-size-button").addEventListener("click", (event) => withBusy(event.currentTarget, () => saveConfig(isUvcSource() ? "预览尺寸已应用" : "输出尺寸已应用")).catch(() => {}));
  elements.connectButton.addEventListener("click", (event) => withBusy(event.currentTarget, connectOrDisconnect).catch(() => {}));
  elements.snapshotButton.addEventListener("click", (event) => withBusy(event.currentTarget, takeSnapshot).catch(() => {}));
  elements.autoButton.addEventListener("click", (event) => withBusy(event.currentTarget, toggleAutoCapture).catch(() => {}));
  elements.recordButton.addEventListener("click", (event) => withBusy(event.currentTarget, toggleRecording).catch(() => {}));
  $("clear-log-button").addEventListener("click", () => {
    $("event-log").replaceChildren();
  });
  $("apply-parameters-button").addEventListener("click", (event) => withBusy(event.currentTarget, applyParameters).catch(() => {}));
  $("refresh-uvc-parameters-button").addEventListener("click", (event) => withBusy(event.currentTarget, loadParameters).catch(() => {}));
  $("apply-roi-button").addEventListener("click", (event) => withBusy(event.currentTarget, applyRoi).catch(() => {}));
  elements.drawRegionButton.addEventListener("click", toggleDrawing);
  elements.applyRegionButton.addEventListener("click", (event) => withBusy(event.currentTarget, applyDrawnRegion).then(() => {
    event.currentTarget.disabled = !state.draftRegion;
  }).catch(() => {}));
  elements.clearRegionButton.addEventListener("click", (event) => withBusy(event.currentTarget, clearProcessingRegion).then(() => {
    event.currentTarget.disabled = !state.processingRegion;
  }).catch(() => {}));
  elements.restoreFullRoiButton.addEventListener("click", (event) => withBusy(event.currentTarget, restoreFullRoi).catch(() => {}));
  $("draw-mode").addEventListener("change", () => {
    cancelDrawing();
    state.draftRegion = null;
    elements.applyRegionButton.disabled = true;
    updateRegionReadout($("draw-mode").value === "processing" ? state.processingRegion : null);
    $("draw-help").textContent = $("draw-mode").value === "camera"
      ? "拖框后会按相机步长对齐，应用后框外不再采集。"
      : "只保存算法区域坐标，完整画面保留；当前尚未接入处理算法。";
    renderRegions();
  });
  elements.selectionLayer.addEventListener("pointerdown", startRegionDrag);
  elements.selectionLayer.addEventListener("pointermove", moveRegionDrag);
  elements.selectionLayer.addEventListener("pointerup", finishRegionDrag);
  elements.selectionLayer.addEventListener("pointercancel", cancelDrawing);
  $("exposure-mode").addEventListener("change", syncParameterControls);
  $("gain-mode").addEventListener("change", syncParameterControls);
  $("fps-enabled").addEventListener("change", syncParameterControls);
  $("exposure-value").addEventListener("input", updateExposureFpsGuidance);
  $("fps-value").addEventListener("input", updateExposureFpsGuidance);
  $("roi-centered").addEventListener("change", syncRoiControls);
  elements.preview.addEventListener("error", () => {
    if (state.status.connected) logEvent("实时预览中断，正在等待重新连接。", true);
  });
  elements.preview.addEventListener("load", renderRegions);
  elements.viewport.addEventListener("previewresize", renderRegions);
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
      if (isFrameSource()) api("/api/count/prepare", { method: "POST" }).catch(() => {});
      if (isFrameSource()) await loadParameters();
    }
    await withBusy($("scan-button"), scanDevices);
  } catch (error) {
    showToast(error.message, true);
    logEvent(error.message, true);
  }
  setInterval(pollStatus, 1000);
}

initialize();

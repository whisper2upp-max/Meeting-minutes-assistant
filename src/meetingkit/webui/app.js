"use strict";

const $ = (id) => document.getElementById(id);
const qa = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  apiReady: false,
  status: null,
  sessions: [],
  activeView: "home",
  activeMinutes: null,
  transcriptPath: null,
  importPath: null,
  dirty: false,
  logOpen: false,
  logCount: 0,
  handledResult: null,
  pendingDeleteSession: null,
  audioCleanupInfo: null,
  audioCleanupScope: "",
  audioCleanupPath: "",
  speakerMapping: {},
  attendees: { record: [], import: [], settings: [] },
  attendeeSuggestions: [],
  activeDetailLevel: "brief",
  targetDetailLevel: "brief",
  minutesModel: "",
  minutesHistoryCount: 0,
  toastTimer: null,
};

const icons = {
  clock: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  mic: '<svg viewBox="0 0 24 24"><path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v1a7 7 0 0 1-14 0v-1"/></svg>',
  spinner: '<svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="m5 12 4 4L19 6"/></svg>',
  error: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 17h.01"/></svg>',
};

function toast(message) {
  if (!message) return;
  const el = $("toast");
  el.textContent = message;
  el.classList.remove("hidden");
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => el.classList.add("hidden"), 2800);
}

function formatTime(seconds) {
  const value = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const secs = value % 60;
  const mm = String(minutes).padStart(2, "0");
  const ss = String(secs).padStart(2, "0");
  return hours ? `${String(hours).padStart(2, "0")}:${mm}:${ss}` : `${mm}:${ss}`;
}

function formatBytes(bytes) {
  const value = Math.max(0, Number(bytes) || 0);
  if (value < 1024) return `${Math.round(value)} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = value / 1024;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  const digits = size >= 100 ? 0 : size >= 10 ? 1 : 2;
  return `${size.toFixed(digits)} ${units[index]}`;
}

function basename(path) {
  return String(path || "").split(/[\\/]/).filter(Boolean).pop() || "";
}

function sessionTitle(session) {
  const name = String(session?.name || "未命名会议");
  return name.replace(/^\d{4}-\d{2}-\d{2}_\d{4}(?:_)?/, "") || name;
}

const attendeeUi = {
  record: { chips: "attendeesRecChips", input: "attendeesRecInput", suggestions: "attendeesRecSuggestions" },
  import: { chips: "attendeesImpChips", input: "attendeesImpInput", suggestions: "attendeesImpSuggestions" },
  settings: { chips: "attendeesSettingsChips", input: "attendeesSettingsInput", suggestions: null },
};

const detailLabels = { brief: "简要", standard: "标准", detailed: "详细" };

function normalizeAttendeeNames(values) {
  const raw = Array.isArray(values) ? values : String(values || "").split(/[\n,，;；]+/);
  const seen = new Set();
  return raw
    .map((value) => String(value || "").trim().slice(0, 40))
    .filter((value) => {
      const key = value.toLocaleLowerCase();
      if (!value || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

function attendeeInitial(name) {
  const value = String(name || "?").trim();
  return value.slice(0, 1).toLocaleUpperCase() || "?";
}

function renderAttendees(scope) {
  const ui = attendeeUi[scope];
  if (!ui || !$(ui.chips)) return;
  const values = state.attendees[scope] || [];
  const chips = $(ui.chips);
  chips.replaceChildren();
  if (!values.length) {
    const empty = document.createElement("span");
    empty.className = "attendee-empty";
    empty.textContent = scope === "settings" ? "还没有常用参会人" : "还没有添加参会人";
    chips.appendChild(empty);
  } else {
    values.forEach((name) => {
      const chip = document.createElement("span");
      const avatar = document.createElement("i");
      const copy = document.createElement("span");
      const remove = document.createElement("button");
      chip.className = "attendee-chip";
      avatar.textContent = attendeeInitial(name);
      copy.textContent = name;
      remove.type = "button";
      remove.textContent = "×";
      remove.title = `移除 ${name}`;
      remove.setAttribute("aria-label", remove.title);
      remove.addEventListener("click", () => {
        state.attendees[scope] = values.filter((item) => item !== name);
        renderAttendees(scope);
      });
      chip.append(avatar, copy, remove);
      chips.appendChild(chip);
    });
  }

  if (!ui.suggestions) return;
  const suggestions = $(ui.suggestions);
  suggestions.replaceChildren();
  state.attendeeSuggestions
    .filter((name) => !values.includes(name))
    .slice(0, 10)
    .forEach((name) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = `+ ${name}`;
      button.addEventListener("click", () => addAttendees(scope, [name]));
      suggestions.appendChild(button);
    });
}

function setAttendees(scope, values) {
  state.attendees[scope] = normalizeAttendeeNames(values);
  renderAttendees(scope);
}

function addAttendees(scope, values) {
  setAttendees(scope, [...(state.attendees[scope] || []), ...normalizeAttendeeNames(values)]);
}

function commitAttendeeInput(scope) {
  const input = $(attendeeUi[scope]?.input);
  if (!input) return;
  addAttendees(scope, input.value);
  input.value = "";
}

function attendeeText(scope) {
  return (state.attendees[scope] || []).join("\n");
}

function selectedDetail(groupId) {
  return $(`${groupId}`)?.querySelector("input:checked")?.value || "brief";
}

function setEditorDetail(level, makeCurrent = false) {
  const normalized = detailLabels[level] ? level : "brief";
  state.targetDetailLevel = normalized;
  if (makeCurrent) state.activeDetailLevel = normalized;
  qa("[data-editor-detail]").forEach((button) => {
    button.classList.toggle("active", button.dataset.editorDetail === normalized);
  });
}

function statusTargetsActiveSession(status) {
  if (!state.activeMinutes || !status?.session_dir) return false;
  const path = String(state.activeMinutes).replace(/\\/g, "/").toLocaleLowerCase();
  const session = String(status.session_dir).replace(/\\/g, "/").replace(/\/$/, "").toLocaleLowerCase();
  return path.startsWith(`${session}/`);
}

function api() {
  return window.pywebview?.api;
}

function setActiveView(name, force = false) {
  if (!force && state.activeView === "minutes" && name !== "minutes" && state.dirty) {
    if (!window.confirm("当前纪要尚未保存，确定离开吗？")) return;
  }
  if (state.activeView === "record" && name !== "record") void stopMicTest(true);
  state.activeView = name;
  document.body.classList.toggle("minutes-mode", name === "minutes");
  qa("[data-view-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.viewPanel === name));
  qa(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === name));

  const progress = $("progressPanel");
  if (name === "record") {
    $("progressMountRecord").appendChild(progress);
    progress.classList.remove("hidden");
  } else if (name === "import") {
    $("progressMountImport").appendChild(progress);
    progress.classList.remove("hidden");
  } else {
    progress.classList.add("hidden");
  }

  if (name === "home") loadSessions();
  if (name === "minutes") loadSessions();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function openOverlay(id) {
  $(id)?.classList.remove("hidden");
}

function closeOverlay(id) {
  $(id)?.classList.add("hidden");
}

function friendlyStage(stage) {
  return {
    finalize: ["正在整理录音", "停止双轨捕捉并混合音频"],
    prepare: ["正在准备音频", "检查文件并创建会议工作目录"],
    upload: ["正在上传音频", "发送到配置的百炼临时存储"],
    submit: ["正在提交任务", "创建智能转写任务"],
    transcribe: ["正在识别发言", "转写全文并自动区分说话人"],
    minutes: ["正在生成纪要", "提炼摘要、决策和行动事项"],
  }[stage] || ["正在处理会议", "请保持应用开启"];
}

function setProgressIcon(type) {
  const el = $("pIcon");
  el.className = `progress-icon${type === "working" ? " spin" : type === "done" ? " done" : type === "error" ? " error" : ""}`;
  el.innerHTML = type === "recording" ? icons.mic : type === "working" ? icons.spinner : type === "done" ? icons.check : type === "error" ? icons.error : icons.clock;
}

function progressStates(phase, stage) {
  if (phase === "recording") return ["active", "", "", ""];
  if (phase === "done") return ["done", "done", "done", "done"];
  if (phase === "error") {
    if (stage === "minutes") return ["done", "done", "done", "error"];
    if (stage === "transcribe") return ["done", "done", "error", ""];
    if (["upload", "submit"].includes(stage)) return ["done", "error", "", ""];
    return ["error", "", "", ""];
  }
  if (phase === "processing") {
    if (["finalize", "prepare"].includes(stage)) return ["active", "", "", ""];
    if (["upload", "submit"].includes(stage)) return ["done", "active", "", ""];
    if (stage === "transcribe") return ["done", "done", "active", ""];
    if (stage === "minutes") return ["done", "done", "done", "active"];
    return ["done", "active", "", ""];
  }
  return ["", "", "", ""];
}

function renderProgress(status) {
  const phase = status.phase || "idle";
  const rec = phase === "recording";
  const processing = phase === "processing";
  const [title, subtitle] = processing ? friendlyStage(status.stage) : ["", ""];

  if (phase === "idle") {
    setProgressIcon("idle");
    $("pLabel").textContent = "PROCESS STATUS";
    $("pText").textContent = "等待任务";
    $("pSub").textContent = "完成录制或选择文件后，这里会显示处理进度。";
  } else if (rec) {
    const micCaptureEnabled = status.mic_capture_enabled !== false;
    setProgressIcon("recording");
    $("pLabel").textContent = "LIVE CAPTURE";
    $("pText").textContent = `正在录音 ${formatTime(status.elapsed)}`;
    $("pSub").textContent = micCaptureEnabled
      ? "会议内声与麦克风双轨采集中"
      : "会议内声持续录制中 · 麦克风外录已暂停";
  } else if (processing) {
    setProgressIcon("working");
    $("pLabel").textContent = "PROCESSING";
    $("pText").textContent = title;
    $("pSub").textContent = status.detail || subtitle;
  } else if (phase === "done") {
    setProgressIcon("done");
    $("pLabel").textContent = "COMPLETE";
    $("pText").textContent = "会议纪要已生成";
    $("pSub").textContent = "可以进入纪要工作区校对、保存和导出";
  } else {
    setProgressIcon("error");
    $("pLabel").textContent = "NEEDS ATTENTION";
    $("pText").textContent = "处理没有完成";
    $("pSub").textContent = "请查看错误信息和运行日志";
  }

  const states = progressStates(phase, status.stage);
  qa("#progressSteps > div").forEach((step, index) => {
    step.className = states[index] || "";
    step.querySelector("i").textContent = states[index] === "done" ? "✓" : String(index + 1);
  });

  $("pErr").textContent = status.error || "";
  $("pErr").classList.toggle("hidden", phase !== "error");
  $("btnOpenResult").classList.toggle("hidden", phase !== "done" || !status.result?.minutes);
}

function renderMinutesGeneration(status = state.status || {}) {
  const enabled = Boolean(state.activeMinutes);
  const currentTask = statusTargetsActiveSession(status);
  const regenerating = enabled && currentTask && status.phase === "processing" && status.stage === "minutes";
  qa("[data-editor-detail]").forEach((button) => { button.disabled = !enabled || regenerating; });
  const button = $("btnRegenerateMinutes");
  button.disabled = !enabled || regenerating;
  button.classList.toggle("processing", regenerating);
  if (!enabled) {
    button.textContent = "按此档重新生成";
    $("minutesDetailMeta").textContent = "选择档位后可直接重新生成，不重复转写";
    return;
  }
  if (regenerating) {
    button.textContent = "正在重新生成…";
    $("minutesDetailMeta").textContent = status.detail || `正在生成${detailLabels[state.targetDetailLevel]}纪要，旧版本已安全保留`;
    return;
  }
  if (currentTask && status.phase === "error" && status.stage === "minutes") {
    $("minutesDetailMeta").textContent = `重新生成失败：${status.error || "请稍后重试"}`;
    button.textContent = "重试重新生成";
    return;
  }

  const current = detailLabels[state.activeDetailLevel] || detailLabels.brief;
  const target = detailLabels[state.targetDetailLevel] || detailLabels.brief;
  const model = state.minutesModel ? ` · ${state.minutesModel}` : "";
  const history = state.minutesHistoryCount ? ` · 已备份 ${state.minutesHistoryCount} 版` : "";
  $("minutesDetailMeta").textContent = state.targetDetailLevel === state.activeDetailLevel
    ? `当前为${current}${model}${history}`
    : `当前为${current}${model}${history}；将改为${target}`;
  button.textContent = state.targetDetailLevel === state.activeDetailLevel ? "重新生成当前档" : `改为${target}并重新生成`;
}

function renderHeaderStatus(status) {
  const chip = $("statusChip");
  const labels = { idle: "本机就绪", recording: "录音中", processing: "处理中", done: "已完成", error: "需要处理" };
  chip.className = `status-chip ${status.phase || "idle"}`;
  $("statusText").textContent = labels[status.phase] || labels.idle;
  if (status.version) $("versionChip").textContent = `v${status.version}`;
}

function renderRecorder(status) {
  const rec = status.phase === "recording";
  const busy = rec || status.phase === "processing";
  const micTesting = Boolean(status.mic_test_active);
  const micCaptureEnabled = status.mic_capture_enabled !== false;
  $("timer").textContent = rec ? formatTime(status.elapsed) : "00:00";
  $("btnRecord").classList.toggle("recording", rec);
  $("recordButtonLabel").textContent = rec ? "停止并生成纪要" : "开始录音";
  $("recHint").textContent = rec
    ? micCaptureEnabled
      ? "外录已开启；需要旁聊时可随时暂停麦克风，会议内声不会中断。"
      : "外录已暂停；此时麦克风声音不会写入，会议内声仍在继续录制。"
    : status.phase === "processing"
      ? "录音已完成，正在处理，请稍候。"
      : "准备就绪后点击按钮，会议内声和麦克风将同步录制。";
  $("waveform").classList.toggle("live", rec);
  $("consoleSource").textContent = rec
    ? micCaptureEnabled ? "双轨采集中" : "内录中 · 外录暂停"
    : status.phase === "processing" ? "处理中" : "等待开始";
  $("consoleSource").previousElementSibling?.querySelector("i")?.classList.toggle("live", rec);
  $("btnRecord").disabled = status.phase === "processing";
  const micCaptureButton = $("btnMicCapture");
  micCaptureButton.classList.toggle("hidden", !rec);
  micCaptureButton.classList.toggle("muted", rec && !micCaptureEnabled);
  micCaptureButton.disabled = !rec;
  micCaptureButton.setAttribute("aria-pressed", String(rec && micCaptureEnabled));
  $("micCaptureLabel").textContent = micCaptureEnabled ? "暂停外录" : "恢复外录";
  $("micCaptureState").textContent = micCaptureEnabled ? "麦克风正在录入" : "麦克风不会写入";
  $("titleInput").disabled = busy;
  qa('[data-attendee-editor="record"] input, [data-attendee-editor="record"] button, [data-attendee-editor="import"] input, [data-attendee-editor="import"] button, #attendeesRecSuggestions button, #attendeesImpSuggestions button, #detailRec input, #detailImp input')
    .forEach((control) => { control.disabled = busy; });
  ["micSelect", "btnRefresh"].forEach((id) => { $(id).disabled = busy || micTesting; });
  $("micTestRow").classList.toggle("hidden", !status.is_windows);
  $("btnMicTest").disabled = busy;
  $("btnMicTest").classList.toggle("testing", micTesting);
  $("btnMicTest").setAttribute("aria-pressed", String(micTesting));
  $("btnMicTest").querySelector("b").textContent = micTesting ? "停止测试" : "测试麦克风";
  const micTestStatus = $("micTestStatus");
  micTestStatus.classList.toggle("active", micTesting);
  micTestStatus.classList.toggle("error", Boolean(status.mic_test_error));
  micTestStatus.textContent = micTesting
    ? `正在回听：${status.mic_test_input || "当前麦克风"} → ${status.mic_test_output || "默认播放设备"}`
    : status.mic_test_error
      ? status.mic_test_error
      : "说话声会实时送到当前默认耳机或扬声器；使用扬声器时请降低音量，避免啸叫。";
  const micLevel = Math.max(0, Math.min(1, Number(status.mic_test_level) || 0));
  $("micTestLevel").style.width = `${Math.round(micLevel * 100)}%`;
  $("micTestLevel").parentElement.setAttribute("aria-valuenow", String(Math.round(micLevel * 100)));
  // Windows 的会议内声固定来自默认输出设备：保持字段可见，但不让用户误以为需要选择。
  $("systemSelect").disabled = busy || Boolean(status.is_windows);
  $("btnStartImport").disabled = busy || !state.importPath;
  $("btnPickFile").disabled = busy;

  if (!status.is_windows) {
    const missingSource = !(status.devices?.system_sources || []).length;
    $("macNote").textContent = !status.loopback_ready
      ? "首次开始录音时会提示安装 BlackHole 内录驱动（仅需一次）。"
      : missingSource ? "当前未检测到会议内声源，本次可能只录制麦克风。" : "会议内声驱动已就绪。";
  }
}

function appendLogs(logs = []) {
  const box = $("log");
  if (logs.length < state.logCount) {
    box.replaceChildren();
    state.logCount = 0;
  }
  logs.slice(state.logCount).forEach(([time, message]) => {
    const row = document.createElement("div");
    const stamp = document.createElement("time");
    const copy = document.createElement("span");
    stamp.textContent = time;
    copy.textContent = message;
    if (String(message).startsWith("错误")) copy.className = "error-line";
    if (String(message).startsWith("⚠")) copy.className = "warn-line";
    row.append(stamp, copy);
    box.appendChild(row);
  });
  state.logCount = logs.length;
  if (state.logOpen) box.scrollTop = box.scrollHeight;
}

async function pollStatus() {
  if (!state.apiReady) return;
  try {
    const status = await api().get_status();
    state.status = status;
    renderHeaderStatus(status);
    renderRecorder(status);
    renderProgress(status);
    renderMinutesGeneration(status);
    appendLogs(status.logs);

    const resultPath = status.result?.minutes;
    if (status.phase === "done" && resultPath && state.handledResult !== resultPath) {
      state.handledResult = resultPath;
      await loadSessions();
      await openMinutes(resultPath);
    }
    if (status.phase !== "done" && resultPath !== state.handledResult) state.handledResult = null;
  } catch (error) {
    console.warn("Status poll failed", error);
  }
}

async function loadDevices() {
  if (!state.apiReady) return;
  try {
    const [result, config, status] = await Promise.all([api().refresh_devices(), api().get_config(), api().get_status()]);
    const microphones = result.devices?.microphones || [];
    const sources = result.devices?.system_sources || [];
    const isWindows = Boolean(status.is_windows);
    const defaultMicrophone = result.devices?.default_microphone || "";
    const defaultLabel = isWindows
      ? defaultMicrophone
        ? `电脑默认外录（推荐，当前：${defaultMicrophone}）`
        : "电脑默认外录（推荐，自动跟随 Windows）"
      : "系统默认麦克风";
    const automaticGroup = document.createElement("optgroup");
    automaticGroup.label = isWindows ? "自动跟随" : "自动选择";
    automaticGroup.append(new Option(defaultLabel, "", false, !config.microphone));
    const deviceGroup = document.createElement("optgroup");
    deviceGroup.label = "固定指定麦克风";
    microphones.forEach((name) => {
      const label = isWindows && name === defaultMicrophone ? `${name}（当前默认，可固定）` : name;
      deviceGroup.append(new Option(label, name, false, config.microphone === name));
    });
    const micSelect = $("micSelect");
    micSelect.replaceChildren(automaticGroup, deviceGroup);
    micSelect.dataset.isWindows = isWindows ? "true" : "false";
    micSelect.dataset.defaultMicrophone = defaultMicrophone;
    updateMicRouteHint();
    $("systemSelect").replaceChildren(new Option(
      isWindows ? "系统默认输出设备（WASAPI 自动内录）" : "自动检测 BlackHole",
      "",
    ));
    sources.forEach((name) => $("systemSelect").add(new Option(name, name, false, config.system_source === name)));
    $("systemField").classList.remove("hidden");
    $("systemSelect").disabled = isWindows;
    $("winHint").classList.toggle("hidden", !isWindows);
  } catch (error) {
    toast(`设备刷新失败：${error}`);
  }
}

function updateMicRouteHint() {
  const micSelect = $("micSelect");
  const hint = $("micRouteHint");
  if (micSelect.dataset.isWindows !== "true") {
    hint.textContent = "未固定设备时，外录使用系统当前默认麦克风。";
    return;
  }
  if (micSelect.value) {
    hint.textContent = `当前固定使用“${micSelect.value}”；拔出该设备后需要重新选择。想自动使用电脑内置或耳机麦克风，请选择“电脑默认外录”。`;
    return;
  }
  const current = micSelect.dataset.defaultMicrophone;
  const suffix = current ? ` 当前识别为“${current}”。` : "";
  hint.textContent = `电脑默认外录会在每次开始录制时读取 Windows 当前默认输入：未插耳机通常使用电脑内置麦克风，插入耳机后自动跟随耳机麦克风。${suffix}`;
}

async function stopMicTest(silent = false) {
  if (!state.apiReady) return;
  const result = await api().stop_mic_test();
  if (!result.ok && !silent) toast(result.error || "无法停止麦克风测试");
  await pollStatus();
}

async function toggleMicTest() {
  if (!state.apiReady) return toast("桌面服务尚未就绪");
  const status = await api().get_status();
  if (status.mic_test_active) {
    await stopMicTest();
    return;
  }
  const result = await api().start_mic_test($("micSelect").value || "");
  if (!result.ok) return toast(result.error || "无法测试麦克风");
  toast("麦克风测试已开始，请说话确认回听声音");
  await pollStatus();
}

async function startRecording() {
  commitAttendeeInput("record");
  const result = await api().start_recording(
    $("titleInput").value,
    $("systemSelect").value || "",
    $("micSelect").value || "",
    attendeeText("record"),
    selectedDetail("detailRec"),
  );
  if (result.need_setup) {
    openOverlay("setupOverlay");
    return;
  }
  if (!result.ok) toast(result.error || "无法开始录音");
}

async function toggleRecording() {
  if (!state.apiReady) return toast("桌面服务尚未就绪");
  const status = await api().get_status();
  if (status.phase === "recording") {
    const result = await api().stop_recording();
    if (!result.ok) toast(result.error);
  } else if (["idle", "done", "error"].includes(status.phase)) {
    await startRecording();
  }
}

async function toggleMicCapture() {
  if (!state.apiReady) return toast("桌面服务尚未就绪");
  const status = await api().get_status();
  if (status.phase !== "recording") return toast("当前没有在录音");
  const nextEnabled = status.mic_capture_enabled === false;
  const button = $("btnMicCapture");
  button.disabled = true;
  try {
    const result = await api().set_mic_capture_enabled(nextEnabled);
    if (!result.ok) return toast(result.error || "无法切换麦克风外录");
    toast(nextEnabled ? "麦克风外录已恢复" : "麦克风外录已暂停，会议内声继续录制");
    await pollStatus();
  } finally {
    if (state.status?.phase === "recording") button.disabled = false;
  }
}

async function chooseImportFile() {
  if (!state.apiReady) return toast("请在桌面应用中选择文件");
  const path = await api().pick_audio_file();
  if (!path) return;
  state.importPath = path;
  $("chosenFile").classList.remove("hidden");
  $("importFileName").textContent = basename(path);
  $("importFilePath").textContent = path;
  $("btnStartImport").disabled = false;
}

async function startImport() {
  if (!state.importPath) return;
  commitAttendeeInput("import");
  const result = await api().process_file(state.importPath, attendeeText("import"), selectedDetail("detailImp"));
  if (!result.ok) toast(result.error);
}

function escapeHtml(value) {
  return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function inlineMarkdown(value) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/\[([^\]]+)]\(([^)]+)\)/g, '<a href="$2">$1</a>');
}

function normalizeLegacyTableLines(markdown) {
  const rawLines = String(markdown || "").replace(/\r/g, "").split("\n");
  return rawLines.filter((line, index) => {
    if (line.trim()) return true;
    let previous = index - 1;
    let next = index + 1;
    while (previous >= 0 && !rawLines[previous].trim()) previous -= 1;
    while (next < rawLines.length && !rawLines[next].trim()) next += 1;
    const before = rawLines[previous]?.trim() || "";
    const after = rawLines[next]?.trim() || "";
    return !(before.startsWith("|") && before.endsWith("|") && after.startsWith("|") && after.endsWith("|"));
  });
}

function markdownToHtml(markdown) {
  const lines = normalizeLegacyTableLines(markdown);
  const output = [];
  let list = null;
  let table = false;

  const closeList = () => {
    if (list) output.push(`</${list}>`);
    list = null;
  };
  const closeTable = () => {
    if (table) output.push("</tbody></table>");
    table = false;
  };

  lines.forEach((raw, index) => {
    const trimmed = raw.trim();
    if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
      closeList();
      if (/^\|?[\s|:-]+\|?$/.test(trimmed)) return;
      const cells = trimmed.slice(1, -1).split("|").map((cell) => cell.trim());
      if (!table) {
        output.push("<table><tbody>");
        table = true;
      }
      const isHeader = /^\|?[\s|:-]+\|?$/.test((lines[index + 1] || "").trim());
      const tag = isHeader ? "th" : "td";
      output.push(`<tr>${cells.map((cell) => `<${tag}>${inlineMarkdown(cell)}</${tag}>`).join("")}</tr>`);
      return;
    }
    closeTable();

    const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      closeList();
      const level = Math.min(6, heading[1].length);
      output.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      return;
    }
    if (trimmed.startsWith("> ")) {
      closeList();
      output.push(`<blockquote>${inlineMarkdown(trimmed.slice(2))}</blockquote>`);
      return;
    }
    const unordered = trimmed.match(/^[-*]\s+(.+)$/);
    const ordered = trimmed.match(/^\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      const wanted = unordered ? "ul" : "ol";
      if (list !== wanted) {
        closeList();
        output.push(`<${wanted}>`);
        list = wanted;
      }
      output.push(`<li>${inlineMarkdown((unordered || ordered)[1])}</li>`);
      return;
    }
    closeList();
    if (trimmed) output.push(`<p>${inlineMarkdown(trimmed)}</p>`);
  });
  closeList();
  closeTable();
  return output.join("\n");
}

function inlineToMarkdown(node) {
  let result = "";
  node.childNodes.forEach((child) => {
    if (child.nodeType === Node.TEXT_NODE) {
      result += child.textContent;
      return;
    }
    const tag = child.nodeName;
    const inside = inlineToMarkdown(child);
    if (["B", "STRONG"].includes(tag)) result += `**${inside}**`;
    else if (["I", "EM"].includes(tag)) result += `*${inside}*`;
    else if (tag === "CODE") result += `\`${child.textContent}\``;
    else if (tag === "A") result += `[${inside}](${child.getAttribute("href") || ""})`;
    else if (tag === "BR") result += "  \n";
    else result += inside;
  });
  return result;
}

function editorToMarkdown(root) {
  const blocks = [];
  root.childNodes.forEach((node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node.textContent.trim();
      if (text) blocks.push(text);
      return;
    }
    const tag = node.nodeName;
    if (/^H[1-6]$/.test(tag)) {
      blocks.push(`${"#".repeat(Number(tag.slice(1)))} ${inlineToMarkdown(node).trim()}`);
    } else if (["P", "DIV"].includes(tag)) {
      const text = inlineToMarkdown(node).trim();
      if (text) blocks.push(text);
    } else if (tag === "BLOCKQUOTE") {
      blocks.push(`> ${inlineToMarkdown(node).trim()}`);
    } else if (["UL", "OL"].includes(tag)) {
      const items = [...node.children]
        .filter((child) => child.nodeName === "LI")
        .map((item, index) => `${tag === "OL" ? `${index + 1}.` : "-"} ${inlineToMarkdown(item).trim()}`);
      if (items.length) blocks.push(items.join("\n"));
    } else if (tag === "TABLE") {
      const tableLines = [];
      [...node.querySelectorAll(":scope > tbody > tr, :scope > thead > tr, :scope > tr")].forEach((row, index) => {
        const cells = [...row.querySelectorAll(":scope > th, :scope > td")].map((cell) => inlineToMarkdown(cell).trim().replace(/\s*\n\s*/g, "<br>").replace(/\|/g, "\\|"));
        if (!cells.length) return;
        tableLines.push(`| ${cells.join(" | ")} |`);
        if (index === 0) tableLines.push(`| ${cells.map(() => "---").join(" | ")} |`);
      });
      if (tableLines.length) blocks.push(tableLines.join("\n"));
    }
  });
  return `${blocks.join("\n\n").replace(/\n{3,}/g, "\n\n").trim()}\n`;
}

function selectedTableContext() {
  const selection = window.getSelection();
  let node = selection?.anchorNode;
  if (!node) return null;
  if (node.nodeType === Node.TEXT_NODE) node = node.parentElement;
  const cell = node?.closest?.("td, th");
  const table = cell?.closest("table");
  if (!cell || !table || !$("minutesBody").contains(table)) return null;
  return { table, cell, row: cell.parentElement, columnIndex: cell.cellIndex };
}

function updateTableControls() {
  const enabled = Boolean(state.activeMinutes && selectedTableContext());
  qa("[data-table-action]").forEach((button) => { button.disabled = !enabled; });
}

function placeCaret(element) {
  element.focus?.();
  const range = document.createRange();
  range.selectNodeContents(element);
  range.collapse(false);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  updateTableControls();
}

function replaceCellTag(cell, tagName) {
  if (cell.nodeName.toLowerCase() === tagName) return cell;
  const replacement = document.createElement(tagName);
  [...cell.attributes].forEach((attribute) => replacement.setAttribute(attribute.name, attribute.value));
  replacement.innerHTML = cell.innerHTML;
  cell.replaceWith(replacement);
  return replacement;
}

function changeTable(action) {
  const context = selectedTableContext();
  if (!context) return toast("请先把光标放进需要编辑的表格单元格");
  const { table, cell, row, columnIndex } = context;
  let target = cell;

  if (action === "addRow") {
    const newRow = document.createElement("tr");
    const columns = Math.max(...[...table.rows].map((item) => item.cells.length));
    for (let index = 0; index < columns; index += 1) {
      const newCell = document.createElement("td");
      newCell.innerHTML = "<br>";
      newRow.appendChild(newCell);
    }
    row.after(newRow);
    target = newRow.cells[Math.min(columnIndex, newRow.cells.length - 1)];
  } else if (action === "deleteRow") {
    if (table.rows.length <= 1) return toast("表格至少需要保留一行");
    const wasHeader = row.rowIndex === 0;
    const nextRow = row.nextElementSibling || row.previousElementSibling;
    row.remove();
    if (wasHeader && table.rows.length) [...table.rows[0].cells].forEach((item) => replaceCellTag(item, "th"));
    target = nextRow?.cells[Math.min(columnIndex, nextRow.cells.length - 1)] || table.rows[0]?.cells[0];
  } else if (action === "addColumn") {
    [...table.rows].forEach((tableRow, rowIndex) => {
      const newCell = document.createElement(rowIndex === 0 ? "th" : "td");
      newCell.innerHTML = rowIndex === 0 ? "新列" : "<br>";
      const reference = tableRow.cells[columnIndex + 1];
      tableRow.insertBefore(newCell, reference || null);
      if (tableRow === row) target = newCell;
    });
  } else if (action === "deleteColumn") {
    const widest = Math.max(...[...table.rows].map((item) => item.cells.length));
    if (widest <= 1) return toast("表格至少需要保留一列");
    [...table.rows].forEach((tableRow) => tableRow.cells[columnIndex]?.remove());
    target = row.cells[Math.min(columnIndex, row.cells.length - 1)] || table.rows[0]?.cells[0];
  }

  markDirty();
  if (target) placeCaret(target);
}

function setEditorEnabled(enabled) {
  $("minutesBody").contentEditable = enabled ? "true" : "false";
  $("documentTitle").readOnly = true;
  qa("button, select", $("editorToolbar")).forEach((control) => { control.disabled = !enabled; });
  $("btnSaveMinutes").disabled = !enabled || !state.dirty;
  ["btnExport", "btnOpenFolder"].forEach((id) => { $(id).disabled = !enabled; });
  $("btnTranscript").disabled = !enabled || !state.transcriptPath;
  $("btnSpeakerMapping").disabled = !enabled;
  qa("[data-editor-detail]").forEach((button) => { button.disabled = !enabled; });
  $("btnRegenerateMinutes").disabled = !enabled;
  renderMinutesGeneration(state.status || {});
  updateTableControls();
}

function updateWordCount() {
  const count = $("minutesBody").innerText.replace(/\s/g, "").length;
  $("documentWords").textContent = `${count} 字`;
}

function markDirty() {
  if (!state.activeMinutes) return;
  state.dirty = true;
  $("saveState").className = "save-state dirty";
  $("saveState").innerHTML = "<i></i> 有未保存修改";
  $("btnSaveMinutes").disabled = false;
  updateWordCount();
}

function markSaved(message = "已保存到本机") {
  state.dirty = false;
  $("saveState").className = "save-state saved";
  $("saveState").innerHTML = `<i></i> ${message}`;
  $("btnSaveMinutes").disabled = true;
}

function clearEditor() {
  state.activeMinutes = null;
  state.transcriptPath = null;
  state.speakerMapping = {};
  state.minutesModel = "";
  state.minutesHistoryCount = 0;
  state.dirty = false;
  setEditorDetail("brief", true);
  $("minutesBody").classList.add("empty");
  $("minutesBody").innerHTML = '<div class="editor-empty"><span><svg viewBox="0 0 24 24"><path d="M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h5"/></svg></span><strong>选择左侧会议纪要</strong><small>这里可以直接编辑标题、段落、列表和行动项表格。</small></div>';
  $("documentTitle").value = "选择一份纪要开始编辑";
  $("minutesPath").textContent = "纪要保存在本机输出目录";
  $("documentTime").textContent = "—";
  $("documentWords").textContent = "0 字";
  $("minutesDetailMeta").textContent = "选择档位后可直接重新生成，不重复转写";
  $("saveState").className = "save-state";
  $("saveState").innerHTML = "<i></i> 未选择纪要";
  setEditorEnabled(false);
}

function replaceSpeakerLabels(mapping) {
  const numbers = Object.keys(mapping || {})
    .filter((number) => /^\d+$/.test(number) && String(mapping[number] || "").trim())
    .sort((left, right) => Number(right) - Number(left));
  if (!numbers.length) return false;
  const pattern = new RegExp(`说话人(${numbers.join("|")})(?!\\d)`, "g");
  const walker = document.createTreeWalker($("minutesBody"), NodeFilter.SHOW_TEXT);
  let changed = false;
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const next = node.nodeValue.replace(pattern, (whole, number) => mapping[number] || whole);
    if (next !== node.nodeValue) {
      node.nodeValue = next;
      changed = true;
    }
  }
  return changed;
}

async function openSpeakerMapping() {
  if (!state.activeMinutes || !state.apiReady) return toast("请先选择一份会议纪要");
  const result = await api().get_speaker_mapping(state.activeMinutes);
  if (!result.ok) return toast(result.error || "无法读取说话人信息");
  state.speakerMapping = result.mapping || {};

  const candidates = $("speakerCandidates");
  candidates.replaceChildren();
  (result.candidates || []).forEach((name) => candidates.append(new Option(name, name)));

  const rows = $("speakerMapRows");
  rows.replaceChildren();
  (result.speakers || []).forEach((speaker) => {
    const row = document.createElement("div");
    const label = document.createElement("div");
    const title = document.createElement("strong");
    const status = document.createElement("small");
    const sample = document.createElement("p");
    const assignment = document.createElement("div");
    const input = document.createElement("input");
    const choices = document.createElement("div");
    row.className = "speaker-map-row";
    label.className = "speaker-map-label";
    sample.className = "speaker-map-sample";
    assignment.className = "speaker-assignment";
    choices.className = "speaker-candidate-list";
    title.textContent = speaker.label || `说话人${speaker.number}`;
    status.textContent = state.speakerMapping[String(speaker.number)] ? "已匹配" : "待确认";
    sample.textContent = speaker.sample || "没有可展示的发言样例";
    input.type = "text";
    input.maxLength = 40;
    input.placeholder = "输入参会人姓名";
    input.setAttribute("list", "speakerCandidates");
    input.dataset.speakerNumber = String(speaker.number);
    input.value = state.speakerMapping[String(speaker.number)] || "";
    const refreshChoiceState = () => {
      const value = input.value.trim();
      status.textContent = value ? "已匹配" : "待确认";
      qa(".speaker-candidate", choices).forEach((button) => {
        button.classList.toggle("selected", button.dataset.name === value);
      });
    };
    (result.candidates || []).slice(0, 8).forEach((name) => {
      const choice = document.createElement("button");
      const avatar = document.createElement("i");
      const copy = document.createElement("span");
      choice.type = "button";
      choice.className = "speaker-candidate";
      choice.dataset.name = name;
      avatar.textContent = attendeeInitial(name);
      copy.textContent = name;
      choice.append(avatar, copy);
      choice.addEventListener("click", () => {
        input.value = name;
        refreshChoiceState();
      });
      choices.appendChild(choice);
    });
    input.addEventListener("input", refreshChoiceState);
    refreshChoiceState();
    label.append(title, status);
    assignment.append(input, choices);
    row.append(label, sample, assignment);
    rows.appendChild(row);
  });
  if (!(result.speakers || []).length) {
    rows.innerHTML = '<div class="speaker-map-empty">这场会议没有识别到可匹配的说话人标签。</div>';
  }
  $("btnSaveSpeakerMapping").disabled = !(result.speakers || []).length;
  openOverlay("speakerOverlay");
}

async function saveSpeakerMapping() {
  if (!state.activeMinutes || !state.apiReady) return;
  const button = $("btnSaveSpeakerMapping");
  const mapping = {};
  qa("input[data-speaker-number]", $("speakerMapRows")).forEach((input) => {
    const name = input.value.trim();
    if (name) mapping[input.dataset.speakerNumber] = name;
  });
  button.disabled = true;
  button.textContent = "正在保存…";
  try {
    const result = await api().save_speaker_mapping(state.activeMinutes, mapping);
    if (!result.ok) return toast(result.error || "无法保存说话人匹配");
    state.speakerMapping = result.mapping || {};
    if (result.transcript) state.transcriptPath = result.transcript;
    const changed = replaceSpeakerLabels(state.speakerMapping);
    if (changed) {
      markDirty();
      if (!await saveMinutes()) return;
    }
    closeOverlay("speakerOverlay");
    toast(changed ? "参会人已匹配，转写与纪要均已更新" : "参会人匹配已保存，完整转写已更新");
  } finally {
    button.disabled = false;
    button.textContent = "保存并应用";
  }
}

async function openMinutes(path) {
  if (!path || !state.apiReady) return;
  if (state.dirty && path !== state.activeMinutes && !window.confirm("当前纪要尚未保存，确定切换吗？")) return;
  const result = await api().get_minutes(path);
  if (!result.ok) return toast(result.error);
  state.activeMinutes = path;
  state.transcriptPath = result.transcript || "";
  state.minutesModel = result.minutes_model || "";
  state.minutesHistoryCount = Number(result.history_count) || 0;
  setEditorDetail(result.detail_level || "brief", true);
  state.dirty = false;
  $("minutesBody").classList.remove("empty");
  $("minutesBody").innerHTML = markdownToHtml(result.content);
  $("documentTitle").value = result.session_name || sessionTitle({ name: basename(result.session) });
  $("minutesPath").textContent = path;
  $("documentTime").textContent = result.mtime || "本机文件";
  updateWordCount();
  markSaved();
  setEditorEnabled(true);
  renderMinutesGeneration(state.status || {});
  renderSessionList();
  setActiveView("minutes", true);
}

async function regenerateMinutes() {
  if (!state.activeMinutes || !state.apiReady) return toast("请先选择一份会议纪要");
  if (state.dirty) {
    if (!window.confirm("当前纪要有未保存修改。要先保存，再重新生成吗？")) return;
    if (!await saveMinutes()) return;
  }
  const target = state.targetDetailLevel;
  const label = detailLabels[target] || detailLabels.brief;
  const sameLevel = target === state.activeDetailLevel;
  const copy = sameLevel
    ? `确定重新生成一版${label}纪要吗？当前纪要会先备份到本场会议的“纪要历史版本”文件夹。`
    : `确定将当前纪要改为${label}档并重新生成吗？不会重复上传或转写，当前纪要会先备份。`;
  if (!window.confirm(copy)) return;
  const result = await api().regenerate_minutes(state.activeMinutes, target);
  if (!result.ok) return toast(result.error || "无法重新生成纪要");
  state.handledResult = null;
  toast(`正在生成${label}纪要，可继续留在当前页面等待`);
  await pollStatus();
}

async function saveMinutes() {
  if (!state.activeMinutes || !state.apiReady) return false;
  const markdown = editorToMarkdown($("minutesBody"));
  const result = await api().save_minutes(state.activeMinutes, markdown);
  if (!result.ok) {
    toast(result.error);
    return false;
  }
  $("minutesBody").innerHTML = markdownToHtml(markdown);
  markSaved();
  toast("纪要已保存");
  await loadSessions();
  return true;
}

async function exportMinutes() {
  if (!state.activeMinutes || !state.apiReady) return;
  if (state.dirty) {
    if (!window.confirm("纪要有未保存修改。先保存再导出吗？")) return;
    await saveMinutes();
  }
  const result = await api().export_minutes(state.activeMinutes);
  if (result.ok) toast(`已导出：${result.dest}`);
  else if (result.error !== "未选择导出目录") toast(result.error);
}

function renderAudioCleanup(info) {
  state.audioCleanupInfo = info;
  const current = info.current;
  const allSessions = info.all_sessions || { sessions: 0, count: 0, bytes: 0 };
  $("audioCleanupCurrentTitle").textContent = current
    ? sessionTitle({ name: current.session_name })
    : "未选择具体会议";
  $("audioCleanupSummary").textContent = current
    ? current.all.count
      ? `当前会议 ${current.all.count} 个音频，共 ${formatBytes(current.all.bytes)}`
      : "当前会议已没有可清理的程序音频"
    : `仍可清理全部历史会议：${allSessions.sessions} 场，共 ${formatBytes(allSessions.bytes)}`;

  $("audioCleanupRawMeta").textContent = current?.raw?.count
    ? `${current.raw.count} 个 · ${formatBytes(current.raw.bytes)}`
    : "无原始双轨";
  $("audioCleanupSessionMeta").textContent = current?.all?.count
    ? `${current.all.count} 个 · ${formatBytes(current.all.bytes)}`
    : "无可清理音频";
  $("audioCleanupAllMeta").textContent = allSessions.count
    ? `${allSessions.sessions} 场 · ${formatBytes(allSessions.bytes)}`
    : "无需清理";

  const availability = {
    session_raw: Boolean(current?.mixed_exists && current?.raw?.count),
    session_all: Boolean(current?.all?.count),
    all_sessions: Boolean(allSessions.count),
  };
  if (!availability[state.audioCleanupScope]) {
    state.audioCleanupScope = ["session_raw", "session_all", "all_sessions"]
      .find((scope) => availability[scope]) || "";
  }
  qa("[data-audio-cleanup-scope]").forEach((button) => {
    const scope = button.dataset.audioCleanupScope;
    button.disabled = !availability[scope];
    button.classList.toggle("selected", scope === state.audioCleanupScope);
    button.setAttribute("aria-pressed", String(scope === state.audioCleanupScope));
  });

  const labels = {
    session_raw: "删除原始双轨",
    session_all: "删除当前全部音频",
    all_sessions: "删除全部会议音频",
  };
  const descriptions = {
    session_raw: "将永久删除当前会议的内录和麦克风原始轨道；混合音频、完整转写、纪要和 JSON 均保留。",
    session_all: "将永久删除当前会议的全部程序音频；完整转写、纪要、JSON 和会议文件夹均保留。",
    all_sessions: "将永久删除输出目录中全部历史会议的程序音频；所有文字资料和会议文件夹均保留。",
  };
  $("audioCleanupGuard").textContent = info.busy
    ? "录音或处理正在进行，完成后才能清理音频。"
    : descriptions[state.audioCleanupScope] || "当前没有可清理的程序音频。";
  $("btnConfirmAudioCleanup").textContent = info.busy
    ? "任务进行中"
    : labels[state.audioCleanupScope] || "确认清理";
  $("btnConfirmAudioCleanup").disabled = Boolean(info.busy || !state.audioCleanupScope);
}

async function openAudioCleanup() {
  if (!state.apiReady) return;
  state.audioCleanupPath = state.activeMinutes || "";
  state.audioCleanupScope = "";
  $("audioCleanupCurrentTitle").textContent = "正在读取音频存储…";
  $("audioCleanupSummary").textContent = "请稍候";
  $("btnConfirmAudioCleanup").disabled = true;
  openOverlay("audioCleanupOverlay");
  try {
    const result = await api().get_audio_cleanup_info(state.audioCleanupPath);
    if (!result.ok) {
      closeOverlay("audioCleanupOverlay");
      return toast(result.error || "无法读取音频存储信息");
    }
    renderAudioCleanup(result);
  } catch (error) {
    closeOverlay("audioCleanupOverlay");
    toast(`无法读取音频存储信息：${error}`);
  }
}

function selectAudioCleanupScope(scope) {
  const button = qa("[data-audio-cleanup-scope]")
    .find((item) => item.dataset.audioCleanupScope === scope);
  if (!button || button.disabled || !state.audioCleanupInfo) return;
  state.audioCleanupScope = scope;
  renderAudioCleanup(state.audioCleanupInfo);
}

async function confirmAudioCleanup() {
  const scope = state.audioCleanupScope;
  const info = state.audioCleanupInfo;
  if (!scope || !info || !state.apiReady) return;
  const current = info.current;
  const allSessions = info.all_sessions || { sessions: 0, bytes: 0 };
  const confirmations = {
    session_raw: `确定删除“${sessionTitle({ name: current?.session_name })}”的原始双轨吗？\n\n预计释放 ${formatBytes(current?.raw?.bytes)}，混合音频和全部文字资料会保留。`,
    session_all: `确定删除“${sessionTitle({ name: current?.session_name })}”的全部音频吗？\n\n预计释放 ${formatBytes(current?.all?.bytes)}，纪要、完整转写和 JSON 会保留。`,
    all_sessions: `确定删除全部 ${allSessions.sessions} 场历史会议的音频吗？\n\n预计释放 ${formatBytes(allSessions.bytes)}，所有文字资料和会议文件夹会保留。`,
  };
  if (!window.confirm(`${confirmations[scope]}\n\n音频删除后无法恢复。`)) return;

  const button = $("btnConfirmAudioCleanup");
  button.disabled = true;
  button.textContent = "正在清理…";
  try {
    const result = await api().cleanup_audio(scope, state.audioCleanupPath);
    if (!result.ok) {
      if (result.deleted_files) await loadSessions();
      return toast(result.error || "音频清理失败");
    }
    closeOverlay("audioCleanupOverlay");
    toast(`已删除 ${result.deleted_files} 个音频文件，释放 ${formatBytes(result.freed_bytes)}`);
    await loadSessions();
  } catch (error) {
    toast(`音频清理失败：${error}`);
  } finally {
    button.disabled = false;
    button.textContent = "确认清理";
  }
}

function requestDeleteSession(session) {
  state.pendingDeleteSession = session;
  $("deleteSessionName").textContent = sessionTitle(session);
  $("deleteSessionPath").textContent = String(session.minutes || "").replace(/[\\/]会议纪要\.md$/, "");
  openOverlay("deleteOverlay");
}

async function confirmDeleteSession() {
  const session = state.pendingDeleteSession;
  if (!session || !state.apiReady) return;
  const button = $("btnConfirmDelete");
  button.disabled = true;
  button.textContent = "正在删除…";
  try {
    const result = await api().delete_session(session.minutes);
    if (!result.ok) return toast(result.error || "删除失败");
    closeOverlay("deleteOverlay");
    state.pendingDeleteSession = null;
    if (state.activeMinutes === session.minutes) clearEditor();
    state.sessions = state.sessions.filter((item) => item.minutes !== session.minutes);
    renderRecent();
    renderSessionList();
    toast("会议记录和整个文件夹已永久删除");
  } catch (error) {
    toast(`删除失败：${error}`);
  } finally {
    button.disabled = false;
    button.textContent = "永久删除会议文件夹";
  }
}

function renderSessionList() {
  const query = $("sessionSearch").value.trim().toLowerCase();
  const sessions = state.sessions.filter((item) => item.name.toLowerCase().includes(query));
  const box = $("sessionList");
  box.replaceChildren();
  if (!sessions.length) {
    box.innerHTML = '<div class="sidebar-empty">没有匹配的会议纪要</div>';
    return;
  }
  sessions.forEach((session) => {
    const row = document.createElement("div");
    const button = document.createElement("button");
    const deleteButton = document.createElement("button");
    row.className = "session-row";
    button.type = "button";
    button.className = `session-item${session.minutes === state.activeMinutes ? " active" : ""}`;
    deleteButton.type = "button";
    deleteButton.className = "session-delete";
    deleteButton.title = `永久删除 ${sessionTitle(session)}`;
    deleteButton.setAttribute("aria-label", deleteButton.title);
    deleteButton.innerHTML = '<svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"/></svg>';
    const title = document.createElement("strong");
    const time = document.createElement("small");
    const badge = document.createElement("span");
    title.textContent = sessionTitle(session);
    time.textContent = session.mtime || "未知时间";
    badge.textContent = `${session.detail_label || "简要"} · ${session.transcript ? "MINUTES + TRANSCRIPT" : "MINUTES"}`;
    button.append(title, time, badge);
    button.addEventListener("click", () => openMinutes(session.minutes));
    deleteButton.addEventListener("click", () => requestDeleteSession(session));
    row.append(button, deleteButton);
    box.appendChild(row);
  });
}

function renderRecent() {
  $("metricMeetings").textContent = String(state.sessions.length);
  $("sessionCount").textContent = `${state.sessions.length} 个纪要`;
  const box = $("recentList");
  box.replaceChildren();
  if (!state.sessions.length) {
    box.innerHTML = '<div class="empty-state"><span>还没有会议纪要</span><small>完成一次录制或导入后，会在这里出现。</small></div>';
    return;
  }
  state.sessions.slice(0, 5).forEach((session) => {
    const row = document.createElement("div");
    row.className = "recent-row";
    const date = document.createElement("span");
    const copy = document.createElement("div");
    const title = document.createElement("strong");
    const meta = document.createElement("small");
    const size = document.createElement("span");
    const open = document.createElement("button");
    date.className = "recent-date";
    copy.className = "recent-copy";
    size.className = "recent-size";
    open.className = "recent-open";
    date.textContent = (session.mtime || "-- --").split(" ")[0].replace("-", "/");
    title.textContent = sessionTitle(session);
    meta.textContent = `${session.mtime || "本机纪要"} · ${session.detail_label || "简要"}纪要`;
    size.textContent = `${session.size_kb || 0} KB`;
    open.textContent = "编辑纪要";
    copy.append(title, meta);
    open.addEventListener("click", () => openMinutes(session.minutes));
    row.append(date, copy, size, open);
    box.appendChild(row);
  });
}

async function loadSessions() {
  if (!state.apiReady) return;
  try {
    const result = await api().list_sessions();
    state.sessions = result.sessions || [];
    if (state.activeMinutes && !state.sessions.some((item) => item.minutes === state.activeMinutes)) clearEditor();
    renderRecent();
    renderSessionList();
  } catch (error) {
    console.warn("Unable to load sessions", error);
  }
}

async function openSettings() {
  if (!state.apiReady) return openOverlay("settingsOverlay");
  const config = await api().get_config();
  $("setKey").value = config.api_key || "";
  $("setHost").value = config.api_host || "";
  $("setTM").value = config.transcribe_model || "fun-asr";
  $("setLM").value = config.llm_model || "qwen-flash";
  $("setOut").value = config.output_dir || "";
  setAttendees("settings", config.attendees || []);
  openOverlay("settingsOverlay");
}

async function saveSettings() {
  commitAttendeeInput("settings");
  const result = await api().save_config({
    api_key: $("setKey").value,
    api_host: $("setHost").value,
    transcribe_model: $("setTM").value,
    llm_model: $("setLM").value,
    output_dir: $("setOut").value,
    attendees: state.attendees.settings,
  });
  if (!result.ok) return toast(`保存失败：${result.error}`);
  state.attendeeSuggestions = [...state.attendees.settings];
  renderAttendees("record");
  renderAttendees("import");
  closeOverlay("settingsOverlay");
  toast("设置已保存");
  await pollStatus();
  await loadSessions();
}

function bindEvents() {
  qa("[data-view]").forEach((control) => control.addEventListener("click", (event) => {
    event.preventDefault();
    setActiveView(control.dataset.view);
  }));
  qa("[data-close]").forEach((control) => control.addEventListener("click", () => closeOverlay(control.dataset.close)));
  qa(".overlay").forEach((overlay) => overlay.addEventListener("click", (event) => {
    if (event.target === overlay) closeOverlay(overlay.id);
  }));
  qa("[data-add-attendee]").forEach((button) => {
    button.addEventListener("click", () => commitAttendeeInput(button.dataset.addAttendee));
  });
  Object.entries(attendeeUi).forEach(([scope, ui]) => {
    const input = $(ui.input);
    input.addEventListener("keydown", (event) => {
      if (event.isComposing) return;
      if (event.key === "Enter" || [",", "，", ";", "；"].includes(event.key)) {
        event.preventDefault();
        commitAttendeeInput(scope);
      }
    });
    input.addEventListener("paste", (event) => {
      const pasted = event.clipboardData?.getData("text") || "";
      if (!/[\n,，;；]/.test(pasted)) return;
      event.preventDefault();
      addAttendees(scope, pasted);
      input.value = "";
    });
  });
  qa("[data-editor-detail]").forEach((button) => {
    button.addEventListener("click", () => {
      setEditorDetail(button.dataset.editorDetail);
      renderMinutesGeneration(state.status || {});
    });
  });

  $("btnGuide").addEventListener("click", () => openOverlay("guideOverlay"));
  $("btnChangelog").addEventListener("click", () => openOverlay("changelogOverlay"));
  $("btnSettings").addEventListener("click", openSettings);
  $("btnOutput").addEventListener("click", async () => {
    if (!state.apiReady) return;
    const result = await api().open_output_dir();
    if (!result.ok) toast(result.error || "无法打开输出目录");
  });
  $("btnAllMinutes").addEventListener("click", () => setActiveView("minutes"));
  $("btnRefresh").addEventListener("click", async () => {
    await stopMicTest(true);
    await loadDevices();
  });
  $("micSelect").addEventListener("change", updateMicRouteHint);
  $("btnMicTest").addEventListener("click", toggleMicTest);
  $("btnRecord").addEventListener("click", toggleRecording);
  $("btnMicCapture").addEventListener("click", toggleMicCapture);
  $("btnPickFile").addEventListener("click", chooseImportFile);
  $("btnStartImport").addEventListener("click", startImport);
  $("btnOpenResult").addEventListener("click", () => openMinutes(state.status?.result?.minutes));

  $("btnToggleLog").addEventListener("click", () => {
    state.logOpen = !state.logOpen;
    $("log").classList.toggle("hidden", !state.logOpen);
    $("btnToggleLog").innerHTML = `${state.logOpen ? "收起" : "查看"}运行日志 <span>${state.logOpen ? "⌃" : "⌄"}</span>`;
  });

  $("btnSetupCancel").addEventListener("click", () => closeOverlay("setupOverlay"));
  $("btnSetupLater").addEventListener("click", () => closeOverlay("setupOverlay"));
  $("btnSetupInstall").addEventListener("click", async () => {
    const button = $("btnSetupInstall");
    button.disabled = true;
    button.textContent = "安装中，请确认系统密码框…";
    try {
      const result = await api().setup_loopback();
      if (!result.ok) return toast(result.error || "驱动安装失败");
      closeOverlay("setupOverlay");
      toast("驱动安装完成，即将开始录音");
      await loadDevices();
      await startRecording();
    } finally {
      button.disabled = false;
      button.textContent = "安装并开始录音";
    }
  });

  $("btnEye").addEventListener("click", () => {
    const input = $("setKey");
    input.type = input.type === "password" ? "text" : "password";
    $("btnEye").textContent = input.type === "password" ? "显示" : "隐藏";
  });
  $("btnBrowseOut").addEventListener("click", async () => {
    if (!state.apiReady) return;
    const path = await api().pick_folder();
    if (path) $("setOut").value = path;
  });
  $("btnSaveSettings").addEventListener("click", () => state.apiReady ? saveSettings() : closeOverlay("settingsOverlay"));

  $("sessionSearch").addEventListener("input", renderSessionList);
  $("btnRefreshSessions").addEventListener("click", loadSessions);
  $("minutesBody").addEventListener("input", markDirty);
  $("minutesBody").addEventListener("click", updateTableControls);
  $("minutesBody").addEventListener("keyup", updateTableControls);
  $("btnSaveMinutes").addEventListener("click", saveMinutes);
  $("btnRegenerateMinutes").addEventListener("click", regenerateMinutes);
  $("btnSpeakerMapping").addEventListener("click", openSpeakerMapping);
  $("btnSaveSpeakerMapping").addEventListener("click", saveSpeakerMapping);
  $("btnAudioCleanup").addEventListener("click", openAudioCleanup);
  qa("[data-audio-cleanup-scope]").forEach((button) => {
    button.addEventListener("click", () => selectAudioCleanupScope(button.dataset.audioCleanupScope));
  });
  $("btnConfirmAudioCleanup").addEventListener("click", confirmAudioCleanup);
  $("btnExport").addEventListener("click", exportMinutes);
  $("btnOpenFolder").addEventListener("click", () => state.activeMinutes && api().reveal(state.activeMinutes));
  $("btnTranscript").addEventListener("click", () => state.transcriptPath && api().open_file(state.transcriptPath));
  $("btnConfirmDelete").addEventListener("click", confirmDeleteSession);

  $("blockFormat").addEventListener("change", (event) => {
    document.execCommand("formatBlock", false, event.target.value);
    $("minutesBody").focus();
    markDirty();
  });
  qa("button[data-command]", $("editorToolbar")).forEach((button) => button.addEventListener("mousedown", (event) => {
    event.preventDefault();
    const command = button.dataset.command;
    if (command === "createLink") {
      const url = window.prompt("请输入链接地址：", "https://");
      if (url) document.execCommand("createLink", false, url);
    } else if (command === "insertTable") {
      document.execCommand("insertHTML", false, '<table><tbody><tr><th>行动项</th><th>负责人</th><th>截止时间</th></tr><tr><td>填写下一步</td><td>待确认</td><td>待确认</td></tr></tbody></table><p><br></p>');
    } else {
      document.execCommand(command, false, null);
    }
    $("minutesBody").focus();
    markDirty();
    updateTableControls();
  }));
  qa("[data-table-action]").forEach((button) => button.addEventListener("mousedown", (event) => {
    event.preventDefault();
    changeTable(button.dataset.tableAction);
  }));
  document.addEventListener("selectionchange", () => {
    if (state.activeView === "minutes") updateTableControls();
  });

  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s" && state.activeMinutes) {
      event.preventDefault();
      saveMinutes();
    }
    if (event.key === "Escape") qa(".overlay:not(.hidden)").forEach((overlay) => closeOverlay(overlay.id));
  });
}

async function initializeDesktop() {
  state.apiReady = true;
  $("btnAudioCleanup").disabled = false;
  await Promise.all([loadDevices(), loadSessions(), pollStatus()]);
  const config = await api().get_config();
  state.attendeeSuggestions = normalizeAttendeeNames(config.attendees || []);
  setAttendees("record", []);
  setAttendees("import", []);
  setAttendees("settings", state.attendeeSuggestions);
  $("metricTranscribe").textContent = config.transcribe_model || "fun-asr";
  $("metricMinutes").textContent = config.llm_model || "qwen-flash";
  window.setInterval(pollStatus, 650);
}

bindEvents();
setEditorEnabled(false);
window.addEventListener("pywebviewready", initializeDesktop, { once: true });

const initialView = window.location.hash.slice(1);
if (["home", "record", "import", "minutes"].includes(initialView)) setActiveView(initialView, true);

// 普通浏览器打开时仍可完整预览和检查界面，业务按钮会提示需桌面服务。
window.setTimeout(() => {
  if (!state.apiReady) {
    $("statusText").textContent = "界面预览";
    $("statusChip").classList.add("processing");
    if (state.activeView === "minutes") {
      state.activeMinutes = "preview/会议纪要.md";
      $("minutesBody").classList.remove("empty");
      $("minutesBody").innerHTML = markdownToHtml("# 产品周会纪要\n\n## 会议摘要\n本周功能开发已完成，团队确认进入内部验收阶段。\n\n## 关键决策\n- 先完成桌面端体验验收，再准备同事分发包。\n- 保留本机优先的数据存储方式。\n\n## 行动事项\n| 行动项 | 负责人 | 截止时间 |\n| --- | --- | --- |\n| 完成界面验收 | 项目负责人 | 本周五 |\n| 整理发布说明 | 产品团队 | 下周一 |");
      $("documentTitle").value = "产品周会纪要";
      $("minutesPath").textContent = "~/Documents/会议纪要/产品周会/会议纪要.md";
      $("documentTime").textContent = "2026-08-29 22:30";
      updateWordCount();
      markSaved("界面预览");
      setEditorEnabled(true);
    }
  }
}, 500);

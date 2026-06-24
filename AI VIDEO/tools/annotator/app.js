const state = {
  projectId: "",
  project: null,
  takes: [],
  selectedTake: null,
  shotSpec: null,
  truth: null,
  currentWindowIndex: 0,
};

const rejectReasonOptions = [
  "event_missing:action_start",
  "event_missing:result_visible",
  "result_hold_too_short",
  "key_occluded",
  "severe_blur",
  "product_not_visible",
  "action_starts_in_middle",
  "different_take_mismatch",
  "decode_failed",
];

const el = {
  status: document.getElementById("status"),
  projectSelect: document.getElementById("projectSelect"),
  annotatorInput: document.getElementById("annotatorInput"),
  fpsInput: document.getElementById("fpsInput"),
  saveButton: document.getElementById("saveButton"),
  takeList: document.getElementById("takeList"),
  takeCount: document.getElementById("takeCount"),
  video: document.getElementById("video"),
  timeLabel: document.getElementById("timeLabel"),
  assetLabel: document.getElementById("assetLabel"),
  shotLabel: document.getElementById("shotLabel"),
  specView: document.getElementById("specView"),
  usableToggle: document.getElementById("usableToggle"),
  rejectReasons: document.getElementById("rejectReasons"),
  newWindowButton: document.getElementById("newWindowButton"),
  deleteWindowButton: document.getElementById("deleteWindowButton"),
  windowList: document.getElementById("windowList"),
  issues: document.getElementById("issues"),
};

function setStatus(message) {
  el.status.textContent = message;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(payload.error || response.statusText);
  }
  return payload;
}

function formatMs(ms) {
  if (!Number.isFinite(ms)) return "-";
  const totalMs = Math.max(0, Math.round(ms));
  const minutes = Math.floor(totalMs / 60000);
  const seconds = Math.floor((totalMs % 60000) / 1000);
  const millis = totalMs % 1000;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
}

function nowMs() {
  return Math.round(el.video.currentTime * 1000);
}

function durationMs() {
  if (Number.isFinite(el.video.duration) && el.video.duration > 0) {
    return Math.round(el.video.duration * 1000);
  }
  return state.truth?.duration_ms || 1;
}

function makeWindow(index) {
  return {
    window_id: `w${index}`,
    source_in_ms: null,
    source_out_ms: null,
    events: {
      action_start_ms: null,
      result_first_visible_ms: null,
      result_hold_end_ms: null,
    },
    grade: "B",
    notes: "",
  };
}

function makeEmptyTruth(take) {
  return {
    asset_id: take.asset_id,
    shot_id: take.shot_id,
    duration_ms: durationMs(),
    usable: true,
    windows: [makeWindow(1)],
    reject_reasons: [],
    annotator: el.annotatorInput.value || "primary",
    annotated_at: new Date().toISOString(),
  };
}

async function loadProjects() {
  const payload = await fetchJson("/api/projects");
  el.projectSelect.innerHTML = "";
  payload.projects.forEach((project) => {
    const option = document.createElement("option");
    option.value = project.project_id;
    option.textContent = project.product ? `${project.project_id} (${project.product})` : project.project_id;
    el.projectSelect.appendChild(option);
  });

  if (payload.projects.length === 0) {
    setStatus("No projects found");
    return;
  }
  state.projectId = payload.projects[0].project_id;
  el.projectSelect.value = state.projectId;
  await loadProject(state.projectId);
}

async function loadProject(projectId) {
  state.projectId = projectId;
  const payload = await fetchJson(`/api/project?project_id=${encodeURIComponent(projectId)}`);
  state.project = payload;
  state.takes = payload.shots.flatMap((shot) => shot.takes);
  state.selectedTake = null;
  state.shotSpec = null;
  state.truth = null;
  renderTakeList();
  clearWorkspace();
  setStatus(`Loaded ${projectId}`);
}

function clearWorkspace() {
  el.video.removeAttribute("src");
  el.video.load();
  el.assetLabel.textContent = "No take selected";
  el.shotLabel.textContent = "-";
  el.specView.innerHTML = "";
  el.windowList.innerHTML = '<div class="empty">Add videos under projects/&lt;id&gt;/shots/&lt;shot_id&gt;/ to begin.</div>';
  el.issues.innerHTML = "";
}

function renderTakeList() {
  el.takeCount.textContent = String(state.takes.length);
  if (state.takes.length === 0) {
    el.takeList.innerHTML = '<div class="empty">No take videos found.</div>';
    return;
  }
  el.takeList.innerHTML = "";
  state.takes.forEach((take) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `take-item ${state.selectedTake?.asset_id === take.asset_id ? "active" : ""}`;
    button.innerHTML = `
      <strong>${take.asset_id}</strong>
      <span class="badge ${take.truth_files.length ? "ok" : ""}">${take.truth_files.length ? "marked" : "open"}</span>
      <span>${take.filename}</span>
      <span>${take.truth_files.length} truth</span>
    `;
    button.addEventListener("click", () => selectTake(take));
    el.takeList.appendChild(button);
  });
}

async function selectTake(take) {
  state.selectedTake = take;
  state.currentWindowIndex = 0;
  renderTakeList();
  el.assetLabel.textContent = take.asset_id;
  el.video.src = take.video_url;
  el.video.load();
  await loadShotSpec(take.shot_id);
  await loadTruthForTake(take);
  renderAll();
}

async function loadShotSpec(shotId) {
  state.shotSpec = await fetchJson(
    `/api/shot_spec?project_id=${encodeURIComponent(state.projectId)}&shot_id=${encodeURIComponent(shotId)}`,
  );
  el.shotLabel.textContent = shotId;
}

async function loadTruthForTake(take) {
  const annotator = el.annotatorInput.value || "primary";
  try {
    const payload = await fetchJson(
      `/api/truth?project_id=${encodeURIComponent(state.projectId)}&shot_id=${encodeURIComponent(take.shot_id)}&take_name=${encodeURIComponent(take.take_name)}&annotator=${encodeURIComponent(annotator)}`,
    );
    state.truth = payload.truth;
    setStatus(`Opened ${payload.path}`);
  } catch (_error) {
    state.truth = makeEmptyTruth(take);
    setStatus(`New truth for ${take.asset_id}`);
  }
}

function renderSpec() {
  if (!state.shotSpec) {
    el.specView.innerHTML = "";
    return;
  }
  const spec = state.shotSpec;
  const rows = [
    ["Role", spec.role],
    ["Target", `${spec.target_duration_ms} ms`],
    ["Required events", spec.required_events.join(", ")],
    ["Required states", spec.required_states.join("; ")],
    ["Forbidden", spec.forbidden.join("; ")],
    ["Min result hold", `${spec.timing.min_result_hold_ms} ms`],
  ];
  el.specView.innerHTML = rows
    .map(([key, value]) => `<dt>${key}</dt><dd>${value || "-"}</dd>`)
    .join("");
}

function renderRejectReasons() {
  const disabled = state.truth?.usable !== false;
  el.rejectReasons.innerHTML = "";
  rejectReasonOptions.forEach((reason) => {
    const id = `reason-${reason.replace(/[^A-Za-z0-9]/g, "-")}`;
    const checked = state.truth?.reject_reasons?.includes(reason) ? "checked" : "";
    const row = document.createElement("label");
    row.className = "check-row";
    row.innerHTML = `<input id="${id}" type="checkbox" ${checked} ${disabled ? "disabled" : ""} /> <span>${reason}</span>`;
    row.querySelector("input").addEventListener("change", (event) => {
      const input = event.target;
      const reasons = new Set(state.truth.reject_reasons);
      if (input.checked) reasons.add(reason);
      else reasons.delete(reason);
      state.truth.reject_reasons = Array.from(reasons);
      renderIssues();
    });
    el.rejectReasons.appendChild(row);
  });
}

function renderWindows() {
  if (!state.truth) {
    el.windowList.innerHTML = "";
    return;
  }
  if (!state.truth.usable) {
    el.windowList.innerHTML = '<div class="empty">This take is marked unusable.</div>';
    return;
  }
  if (state.truth.windows.length === 0) {
    state.truth.windows.push(makeWindow(1));
  }
  el.windowList.innerHTML = "";
  state.truth.windows.forEach((windowItem, index) => {
    const card = document.createElement("article");
    card.className = `window-card ${index === state.currentWindowIndex ? "active" : ""}`;
    card.innerHTML = `
      <div class="window-head">
        <button type="button" data-select="${index}" title="Select window">${windowItem.window_id}</button>
        <label>
          Grade
          <select class="grade-select" data-grade="${index}">
            ${["A", "B", "C", "D"].map((grade) => `<option value="${grade}" ${windowItem.grade === grade ? "selected" : ""}>${grade}</option>`).join("")}
          </select>
        </label>
      </div>
      <div class="window-fields">
        ${fieldHtml("source_in", windowItem.source_in_ms)}
        ${fieldHtml("action_start", windowItem.events.action_start_ms)}
        ${fieldHtml("result_first", windowItem.events.result_first_visible_ms)}
        ${fieldHtml("result_hold_end", windowItem.events.result_hold_end_ms)}
        ${fieldHtml("source_out", windowItem.source_out_ms)}
      </div>
      <label>
        Notes
        <input class="notes-input" data-notes="${index}" value="${escapeAttr(windowItem.notes || "")}" />
      </label>
    `;
    card.querySelector("[data-select]").addEventListener("click", () => {
      state.currentWindowIndex = index;
      renderWindows();
    });
    card.querySelector("[data-grade]").addEventListener("change", (event) => {
      windowItem.grade = event.target.value;
      renderIssues();
    });
    card.querySelector("[data-notes]").addEventListener("input", (event) => {
      windowItem.notes = event.target.value;
    });
    el.windowList.appendChild(card);
  });
}

function fieldHtml(label, value) {
  return `
    <div class="field">
      <span>${label}</span>
      <strong>${formatMs(value)}</strong>
    </div>
  `;
}

function escapeAttr(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function renderIssues() {
  const { errors, warnings } = validateTruth();
  const items = [
    ...errors.map((message) => ({ message, type: "error" })),
    ...warnings.map((message) => ({ message, type: "warning" })),
  ];
  el.issues.innerHTML = items.map((item) => `<div class="issue ${item.type}">${item.message}</div>`).join("");
}

function renderAll() {
  if (!state.truth) return;
  el.usableToggle.checked = state.truth.usable;
  renderSpec();
  renderRejectReasons();
  renderWindows();
  renderIssues();
}

function validateTruth() {
  const errors = [];
  const warnings = [];
  const truth = state.truth;
  if (!truth) return { errors: ["No take selected."], warnings };
  truth.duration_ms = durationMs();
  truth.annotator = el.annotatorInput.value || "primary";

  if (!truth.usable) {
    if (truth.reject_reasons.length === 0) errors.push("Choose at least one reject reason.");
    return { errors, warnings };
  }

  if (truth.windows.length === 0) errors.push("At least one usable window is required.");
  truth.windows.forEach((windowItem) => {
    const prefix = `${windowItem.window_id}:`;
    const values = [
      ["source_in_ms", windowItem.source_in_ms],
      ["action_start_ms", windowItem.events.action_start_ms],
      ["result_first_visible_ms", windowItem.events.result_first_visible_ms],
      ["result_hold_end_ms", windowItem.events.result_hold_end_ms],
      ["source_out_ms", windowItem.source_out_ms],
    ];
    values.forEach(([name, value]) => {
      if (!Number.isFinite(value)) errors.push(`${prefix} ${name} is not set.`);
    });
    if (errors.length) return;
    if (!(windowItem.source_in_ms < windowItem.events.action_start_ms)) {
      errors.push(`${prefix} source_in_ms must be before action_start_ms.`);
    }
    if (!(windowItem.events.action_start_ms < windowItem.events.result_first_visible_ms)) {
      errors.push(`${prefix} action_start_ms must be before result_first_visible_ms.`);
    }
    if (!(windowItem.events.result_first_visible_ms <= windowItem.events.result_hold_end_ms)) {
      errors.push(`${prefix} result_first_visible_ms must be <= result_hold_end_ms.`);
    }
    if (!(windowItem.events.result_hold_end_ms <= windowItem.source_out_ms)) {
      errors.push(`${prefix} result_hold_end_ms must be <= source_out_ms.`);
    }
    if (windowItem.source_out_ms > truth.duration_ms) {
      errors.push(`${prefix} source_out_ms exceeds video duration.`);
    }
    const minHold = state.shotSpec?.timing?.min_result_hold_ms || 0;
    const hold = windowItem.events.result_hold_end_ms - windowItem.events.result_first_visible_ms;
    if (hold < minHold) {
      warnings.push(`${prefix} result hold is ${hold} ms, below ${minHold} ms.`);
    }
  });
  return { errors, warnings };
}

function currentWindow() {
  if (!state.truth || !state.truth.usable) return null;
  if (!state.truth.windows[state.currentWindowIndex]) {
    state.currentWindowIndex = 0;
  }
  return state.truth.windows[state.currentWindowIndex] || null;
}

function markPoint(kind) {
  const windowItem = currentWindow();
  if (!windowItem) return;
  const value = nowMs();
  if (kind === "source_in_ms") windowItem.source_in_ms = value;
  if (kind === "source_out_ms") windowItem.source_out_ms = value;
  if (kind === "action_start_ms") windowItem.events.action_start_ms = value;
  if (kind === "result_first_visible_ms") windowItem.events.result_first_visible_ms = value;
  if (kind === "result_hold_end_ms") windowItem.events.result_hold_end_ms = value;
  renderWindows();
  renderIssues();
}

function addWindow() {
  if (!state.truth) return;
  state.truth.usable = true;
  state.truth.reject_reasons = [];
  state.truth.windows.push(makeWindow(state.truth.windows.length + 1));
  state.currentWindowIndex = state.truth.windows.length - 1;
  renderAll();
}

function deleteWindow() {
  if (!state.truth || !state.truth.usable) return;
  state.truth.windows.splice(state.currentWindowIndex, 1);
  state.currentWindowIndex = Math.max(0, state.currentWindowIndex - 1);
  renderAll();
}

function toggleUsable(value) {
  if (!state.truth) return;
  state.truth.usable = value;
  if (!value) {
    state.truth.windows = [];
  } else if (state.truth.windows.length === 0) {
    state.truth.windows = [makeWindow(1)];
  }
  renderAll();
}

function stepFrames(frames) {
  const fps = Number(el.fpsInput.value) || 30;
  el.video.pause();
  el.video.currentTime = Math.max(0, Math.min(el.video.duration || Infinity, el.video.currentTime + frames / fps));
}

async function saveTruth() {
  if (!state.truth || !state.selectedTake) return;
  const { errors } = validateTruth();
  renderIssues();
  if (errors.length) {
    setStatus("Fix validation errors before saving");
    return;
  }
  state.truth.duration_ms = durationMs();
  state.truth.annotator = el.annotatorInput.value || "primary";
  state.truth.annotated_at = new Date().toISOString();
  if (!state.truth.usable) {
    state.truth.windows = [];
  }
  const payload = await fetchJson("/api/truth", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: state.projectId,
      save_as: state.truth.annotator,
      truth: state.truth,
    }),
  });
  setStatus(`Saved ${payload.path}`);
  await loadProject(state.projectId);
}

el.projectSelect.addEventListener("change", (event) => loadProject(event.target.value));
el.annotatorInput.addEventListener("change", async () => {
  if (state.selectedTake) {
    await loadTruthForTake(state.selectedTake);
    renderAll();
  }
});
el.saveButton.addEventListener("click", saveTruth);
el.newWindowButton.addEventListener("click", addWindow);
el.deleteWindowButton.addEventListener("click", deleteWindow);
el.usableToggle.addEventListener("change", (event) => toggleUsable(event.target.checked));
el.video.addEventListener("timeupdate", () => {
  el.timeLabel.textContent = formatMs(nowMs());
});
el.video.addEventListener("loadedmetadata", () => {
  if (state.truth) {
    state.truth.duration_ms = durationMs();
    renderIssues();
  }
});

document.addEventListener("keydown", (event) => {
  const tag = event.target.tagName;
  if (["INPUT", "SELECT", "TEXTAREA"].includes(tag)) return;
  const key = event.key.toLowerCase();
  if (key === "arrowleft") {
    event.preventDefault();
    stepFrames(event.shiftKey ? -10 : -1);
  } else if (key === "arrowright") {
    event.preventDefault();
    stepFrames(event.shiftKey ? 10 : 1);
  } else if (key === "i") markPoint("source_in_ms");
  else if (key === "o") markPoint("source_out_ms");
  else if (key === "a") markPoint("action_start_ms");
  else if (key === "r") markPoint("result_first_visible_ms");
  else if (key === "e") markPoint("result_hold_end_ms");
  else if (key === "n") addWindow();
  else if (key === "d") deleteWindow();
  else if (key === "x") toggleUsable(!(state.truth?.usable ?? true));
  else if (key === "g") {
    const windowItem = currentWindow();
    if (!windowItem) return;
    const grades = ["A", "B", "C", "D"];
    windowItem.grade = grades[(grades.indexOf(windowItem.grade) + 1) % grades.length];
    renderWindows();
  } else if (key === "s") {
    event.preventDefault();
    saveTruth();
  }
});

loadProjects().catch((error) => {
  setStatus(error.message);
  console.error(error);
});

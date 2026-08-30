const $ = (selector) => document.querySelector(selector);
const API_PREFIX = window.PATCHPIPE?.apiPrefix || "/api";
const apiUrl = (path) => API_PREFIX + (path.startsWith("/api") ? path.slice(4) : path);

let currentSpec = null;
let currentHistoryId = null;
let currentHbePath = "";
let toastTimer = null;

const fields = {
  baseUrl: $("#base-url"),
  model: $("#model"),
  apiKey: $("#api-key"),
  outputDir: $("#output-dir"),
  template: $("#template"),
  request: $("#request"),
};

function resetConnectionStatus() {
  const node = $("#connection-result");
  node.className = "connection-result";
  node.querySelector("span").textContent = "Connection not tested";
}

function clearGenerationError() {
  const node = $("#generation-error");
  node.classList.add("hidden");
  node.querySelector("span").textContent = "";
}

function showGenerationError(message) {
  const node = $("#generation-error");
  node.querySelector("span").textContent = message;
  node.classList.remove("hidden");
}

[fields.baseUrl, fields.model, fields.apiKey].forEach((field) => field.addEventListener("input", resetConnectionStatus));

function status(message, type = "ready") {
  const node = $("#app-status");
  node.className = `status ${type === "ready" ? "" : type}`;
  node.querySelector("span").textContent = message;
}

function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.className = "toast"; }, 4200);
}

async function api(path, payload) {
  status("Working…", "busy");
  try {
    const options = payload === undefined ? {} : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    };
    const response = await fetch(apiUrl(path), options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
    status("Ready");
    return data;
  } catch (error) {
    status("Needs attention", "error");
    toast(error.message, true);
    throw error;
  }
}

function metric(label, value) {
  const node = document.createElement("div");
  node.className = "metric";
  const small = document.createElement("small"); small.textContent = label;
  const strong = document.createElement("strong"); strong.textContent = value;
  node.append(small, strong);
  return node;
}

function toneRow(label, value) {
  const row = document.createElement("div"); row.className = "tone-row";
  const name = document.createElement("span"); name.textContent = label;
  const data = document.createElement("b"); data.textContent = value;
  row.append(name, data);
  return row;
}

function pct(value) {
  return `${Math.round(Number(value) * 100)}%`;
}

function renderSpec(spec, message = "Patch generated and saved.", record = null) {
  currentSpec = spec;
  currentHistoryId = record ? record.id : null;
  currentHbePath = record?.hbe_path || currentHbePath;
  $("#empty-state").classList.add("hidden");
  $("#result-card").classList.remove("hidden");
  $("#patch-name").textContent = spec.patch_name;
  $("#explanation").textContent = message;
  $("#current-version").textContent = record
    ? `Saved ${formatDate(record.created_at)}`
    : "Unsaved working patch";
  $("#loaded-template-name").textContent = fields.template.value || "—";

  const amp = spec.amp;
  const strip = $("#common-parameters");
  strip.replaceChildren();
  if (amp) {
    strip.append(
      metric("Amp", amp.model || "—"),
      metric("Cab", amp.cab || "—"),
      metric("Mic", amp.mic || "—"),
      metric("Drive", pct(amp.drive)),
      metric("Bass", pct(amp.bass)),
      metric("Treble", pct(amp.treble)),
    );
  } else {
    strip.append(metric("Amp", "DI / off"), metric("Cab", "—"), metric("Mic", "—"));
  }

  const grid = $("#tone-grid");
  grid.replaceChildren();
  (spec.fx_slots || []).forEach((slot, index) => {
    const card = document.createElement("article");
    card.className = `tone-card${slot.on ? "" : " off"}`;
    const title = document.createElement("div"); title.className = "tone-title";
    const name = document.createElement("strong"); name.textContent = `FX ${index + 1}`;
    const state = document.createElement("span"); state.textContent = slot.on ? "ON" : "OFF";
    title.append(name, state);
    card.append(title);
    if (slot.on) {
      card.append(
        toneRow("Type", slot.type || "—"),
        toneRow("Model", slot.model || "—"),
        ...Object.entries(slot.params || {}).map(([key, value]) => toneRow(key, pct(value))),
      );
    }
    grid.append(card);
  });
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

async function loadTemplates() {
  const data = await api("/api/templates", {});
  fields.template.replaceChildren();
  data.templates.forEach((name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    fields.template.append(option);
  });
  fields.template.value = data.default;
  $("#loaded-template-name").textContent = data.default;
}

async function loadConfiguration() {
  const data = await api("/api/configuration", {});
  fields.baseUrl.value = data.base_url;
  fields.model.value = data.model;
  fields.outputDir.value = data.output_dir;
  $("#vocab-count").textContent = `${data.vocabulary_count}+`;
  if (data.api_key_configured) {
    fields.apiKey.placeholder = "Saved key configured in .env";
    $("#key-help").textContent = "A saved key is configured in the local .env file. Paste a replacement only when you want to change it.";
  }
}

async function saveConfiguration() {
  const node = $("#save-result");
  node.className = "save-result";
  node.textContent = "Saving to local .env…";
  try {
    const data = await api("/api/save-configuration", {
      base_url: fields.baseUrl.value,
      model: fields.model.value,
      api_key: fields.apiKey.value,
      output_dir: fields.outputDir.value,
      default_template: fields.template.value,
    });
    fields.apiKey.value = "";
    fields.apiKey.placeholder = data.api_key_configured ? "Saved key configured in .env" : "No key configured";
    node.className = "save-result success";
    node.textContent = `${data.message} · ${data.storage}`;
    resetConnectionStatus();
    toast("Model settings saved to .env");
  } catch (error) {
    node.className = "save-result failure";
    node.textContent = error.message;
  }
}

async function testConnection() {
  const node = $("#connection-result");
  node.className = "connection-result";
  node.querySelector("span").textContent = "Testing endpoint, model, and key…";
  try {
    const data = await api("/api/test-connection", {
      base_url: fields.baseUrl.value,
      model: fields.model.value,
      api_key: fields.apiKey.value,
    });
    node.className = "connection-result success";
    node.querySelector("span").textContent = `${data.message} · ${data.model}`;
    toast("Model connection verified");
  } catch (error) {
    node.className = "connection-result failure";
    node.querySelector("span").textContent = error.message;
  }
}

async function randomizePrompt(showToast = true) {
  const data = await api("/api/random-prompt", {});
  fields.request.value = data.prompt;
  if (showToast) toast("New tone idea generated");
}

async function generatePatch() {
  if (!fields.request.value.trim()) return toast("Describe the tone you want", true);
  clearGenerationError();
  try {
    const data = await api("/api/generate", {
      request: fields.request.value,
      template: fields.template.value,
      base_url: fields.baseUrl.value,
      model: fields.model.value,
      api_key: fields.apiKey.value,
      output_dir: fields.outputDir.value,
      parent_id: currentHistoryId,
    });
    currentHbePath = data.hbe_path;
    renderSpec(data.spec, data.message, data.record);
    await refreshHistory();
    toast("Patch generated and saved");
  } catch (error) {
    showGenerationError(error.message);
    throw error;
  }
}

async function refreshHistory() {
  const data = await api("/api/history", {});
  const list = $("#history-list");
  $("#history-count").textContent = `${data.patches.length} ${data.patches.length === 1 ? "patch" : "patches"}`;
  list.replaceChildren();
  if (!data.patches.length) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = "Generated patches will be saved here automatically.";
    list.append(empty);
    return;
  }
  data.patches.forEach((record) => {
    const item = document.createElement("article");
    item.className = `history-item${record.id === currentHistoryId ? " current" : ""}`;
    item.tabIndex = 0;
    const header = document.createElement("header");
    const name = document.createElement("strong"); name.textContent = record.name;
    const controls = document.createElement("span"); controls.className = "history-controls";
    const time = document.createElement("time"); time.textContent = formatDate(record.created_at);
    const remove = document.createElement("button"); remove.className = "history-delete";
    remove.type = "button"; remove.title = `Delete ${record.name}`; remove.textContent = "×";
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteHistoryPatch(record).catch(() => {});
    });
    controls.append(time, remove); header.append(name, controls);
    const request = document.createElement("p"); request.textContent = record.request;
    const category = document.createElement("small"); category.textContent = record.amp_model || record.template;
    item.append(header, request, category);
    item.addEventListener("click", () => loadHistoryPatch(record.id).catch(() => {}));
    list.append(item);
  });
}

async function deleteHistoryPatch(record) {
  if (!confirm(`Remove ${record.name} from the local patch library?`)) return;
  await api("/api/history/delete", { id: record.id });
  if (currentHistoryId === record.id) currentHistoryId = null;
  await refreshHistory();
  toast(`Deleted ${record.name}`);
}

async function loadHistoryPatch(id) {
  const data = await api("/api/history/get", { id });
  fields.request.value = data.record.request;
  currentHbePath = data.record.hbe_path;
  renderSpec(data.spec, data.message, data.record);
  await refreshHistory();
  toast("Saved patch loaded");
}

$("#randomize-prompt").addEventListener("click", () => randomizePrompt().catch(() => {}));
$("#save-configuration").addEventListener("click", saveConfiguration);
$("#test-connection").addEventListener("click", testConnection);
$("#generate-button").addEventListener("click", () => generatePatch().catch(() => {}));
$("#refresh-history").addEventListener("click", () => refreshHistory().catch(() => {}));
$("#reveal-path-button").addEventListener("click", () => {
  if (!currentHbePath) return toast("No .hbe file yet", true);
  toast(currentHbePath);
});
document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => { fields.request.value = button.dataset.prompt; });
});
fields.template.addEventListener("change", () => {
  $("#loaded-template-name").textContent = fields.template.value;
});

Promise.all([loadTemplates(), randomizePrompt(false), loadConfiguration(), refreshHistory()]).catch(() => {});

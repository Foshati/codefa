const state = {
  config: null,
  fields: new Map(),
  localStatus: new Map(),
  modelOptions: [],
  modelComboboxes: new Set(),
  activeView: "providers",
  providerFilter: { query: "", configuredOnly: false },
  busy: false,
  restarting: false,
};

const MASKED_SECRET = "********";
const VIEW_GROUPS = [
  {
    id: "providers",
    label: "Providers",
    title: "Providers",
    subtitle: "Connect cloud APIs and local model servers.",
    sections: ["providers", "runtime"],
    containerId: "providersSections",
  },
  {
    id: "model_config",
    label: "Model Config",
    title: "Model Config",
    subtitle: "Route Claude Code / Codex model slots to provider models.",
    sections: ["models", "reasoning", "web_tools"],
    containerId: "modelConfigSections",
  },
  {
    id: "messaging",
    label: "Messaging",
    title: "Messaging",
    subtitle: "Chat platform bots, sessions, and voice notes.",
    sections: ["messaging", "voice"],
    containerId: "messagingSections",
  },
  {
    id: "logs",
    label: "Logs",
    title: "Server Logs",
    subtitle: "Inspect recent server activity.",
    sections: [],
    containerId: "logsSections",
  },
  {
    id: "settings",
    label: "Settings",
    title: "Settings",
    subtitle: "Preferences for this admin dashboard.",
    sections: [],
    containerId: "settingsSections",
  },
];

const PROVIDER_GROUPS = [
  {
    kind: "remote",
    title: "Cloud",
    description: "Hosted APIs authenticated with a key or token",
  },
  {
    kind: "local",
    title: "Local",
    description: "Model servers running on this machine",
  },
];

const THEME_STORAGE_KEY = "codefa_theme";
const THEME_MODES = ["dark", "light", "system"];
const SVG_NS = "http://www.w3.org/2000/svg";
const LOGS_POLL_MS = 3000;

const byId = (id) => document.getElementById(id);
const prefersReducedMotion = () =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char],
  );
}

// Renders server-provided description text without innerHTML. Supports the two
// markup forms used in field descriptions: [label](https://url) and `code`.
// Links are only created for http(s) URLs; anything else stays plain text.
function renderRichText(target, text) {
  target.replaceChildren();
  const source = String(text ?? "");
  const pattern = /\[([^\]]+)\]\(([^)\s]+)\)|`{1,2}([^`]+)`{1,2}/g;
  let cursor = 0;
  for (const match of source.matchAll(pattern)) {
    if (match.index > cursor) {
      target.append(source.slice(cursor, match.index));
    }
    const [raw, linkText, url, code] = match;
    if (code !== undefined) {
      const codeEl = document.createElement("code");
      codeEl.textContent = code;
      target.append(codeEl);
    } else if (/^https?:\/\//i.test(url)) {
      const link = document.createElement("a");
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = linkText;
      target.append(link);
    } else {
      target.append(raw);
    }
    cursor = match.index + raw.length;
  }
  if (cursor < source.length) {
    target.append(source.slice(cursor));
  }
}

function sourceLabel(source) {
  const labels = {
    default: "default",
    template: "template",
    repo_env: "repo .env",
    managed_env: "",
    explicit_env_file: "CODEFA_ENV_FILE",
    process: "process env",
  };
  return Object.prototype.hasOwnProperty.call(labels, source) ? labels[source] : source;
}

function sourceText(field) {
  const parts = [];
  const label = sourceLabel(field.source);
  if (label) {
    parts.push(label);
  }
  if (field.locked) {
    parts.push("locked");
  }
  return parts.join(" ");
}

function statusClass(status) {
  if (["configured", "reachable", "running"].includes(status)) return "ok";
  if (["missing_key", "missing_config", "missing_url", "invalid_url", "unknown"].includes(status))
    return "warn";
  if (["offline", "error"].includes(status)) return "error";
  return "neutral";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }
  return response.json();
}

async function responseErrorMessage(response) {
  const status = `${response.status} ${response.statusText}`.trim();
  try {
    const body = await response.json();
    if (typeof body?.detail === "string" && body.detail) {
      return `${status}: ${body.detail}`;
    }
  } catch {
    // Non-JSON error bodies fall back to the HTTP status line.
  }
  return status;
}

// ---------------------------------------------------------------------------
// Theme
// ---------------------------------------------------------------------------

function readThemeMode() {
  try {
    const mode = localStorage.getItem(THEME_STORAGE_KEY);
    return THEME_MODES.includes(mode) ? mode : "dark";
  } catch {
    return "dark";
  }
}

function getEffectiveTheme(mode) {
  if (mode === "system") {
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  return mode === "light" ? "light" : "dark";
}

function setTheme(mode) {
  document.documentElement.setAttribute("data-theme", getEffectiveTheme(mode));
  try {
    localStorage.setItem(THEME_STORAGE_KEY, mode);
  } catch {
    // Storage can be unavailable (e.g. privacy mode); the theme still applies.
  }

  document.querySelectorAll(".theme-card").forEach((card) => {
    const selected = card.dataset.themeMode === mode;
    card.classList.toggle("active", selected);
    card.setAttribute("aria-pressed", String(selected));
  });
}

function initTheme() {
  setTheme(readThemeMode());

  document.querySelectorAll(".theme-card").forEach((card) => {
    card.addEventListener("click", () => setTheme(card.dataset.themeMode));
  });

  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (readThemeMode() === "system") {
      setTheme("system");
    }
  });
}

// ---------------------------------------------------------------------------
// Loading & navigation
// ---------------------------------------------------------------------------

async function load() {
  showMessage("Loading admin config");
  const config = await api("/admin/api/config");
  state.config = config;
  state.fields = new Map(config.fields.map((field) => [field.key, field]));
  state.localStatus.clear();
  renderNav();
  renderProviders(config.provider_status);
  renderSections(config.sections, config.fields);
  const configPath = byId("configPath");
  configPath.textContent = config.paths.managed;
  configPath.title = config.paths.managed;
  await hydrateModelOptions();
  await validate(false);
  let localStatusError = null;
  try {
    await refreshLocalStatus();
  } catch (error) {
    // Local probes are informational; they must not block the rest of the UI.
    localStatusError = error;
  }
  updateDirtyState();
  if (localStatusError) {
    showMessage(`Could not check local providers: ${localStatusError.message}`, "warn");
  } else {
    showMessage("");
  }
}

const NAV_ICONS = {
  providers: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="2" width="8" height="8" rx="2"></rect><rect x="14" y="2" width="8" height="8" rx="2"></rect><rect x="2" y="14" width="8" height="8" rx="2"></rect><rect x="14" y="14" width="8" height="8" rx="2"></rect></svg>`,
  model_config: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="4" y1="21" x2="4" y2="14"></line><line x1="4" y1="10" x2="4" y2="3"></line><line x1="12" y1="21" x2="12" y2="12"></line><line x1="12" y1="8" x2="12" y2="3"></line><line x1="20" y1="21" x2="20" y2="16"></line><line x1="20" y1="12" x2="20" y2="3"></line><line x1="1" y1="14" x2="7" y2="14"></line><line x1="9" y1="8" x2="15" y2="8"></line><line x1="17" y1="16" x2="23" y2="16"></line></svg>`,
  messaging: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>`,
  logs: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line></svg>`,
  settings: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>`,
};

const GEAR_ICON = NAV_ICONS.settings;

function renderNav() {
  const nav = byId("sectionNav");
  nav.replaceChildren();
  VIEW_GROUPS.forEach((view) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "nav-link";
    button.dataset.view = view.id;
    button.title = view.label;
    button.innerHTML = NAV_ICONS[view.id] || "";
    const label = document.createElement("span");
    label.textContent = view.label;
    button.appendChild(label);
    button.addEventListener("click", () => {
      setActiveView(view.id, { scroll: true });
    });
    nav.appendChild(button);
  });
  setActiveView(state.activeView, { scroll: false });
}

function setActiveView(viewId, { scroll = false } = {}) {
  const activeView =
    VIEW_GROUPS.find((view) => view.id === viewId) || VIEW_GROUPS[0];
  state.activeView = activeView.id;
  byId("pageTitle").textContent = activeView.title;
  byId("pageSubtitle").textContent = activeView.subtitle || "";

  document.querySelectorAll(".nav-link").forEach((link) => {
    const selected = link.dataset.view === activeView.id;
    link.classList.toggle("active", selected);
    if (selected) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  });

  document.querySelectorAll(".admin-view").forEach((view) => {
    const selected = view.dataset.view === activeView.id;
    view.classList.toggle("active", selected);
    view.hidden = !selected;
  });

  if (scroll) {
    window.scrollTo({ top: 0, behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }

  if (activeView.id === "logs") {
    loadLogs();
    startLogsInterval();
  } else {
    stopLogsInterval();
  }
}

// ---------------------------------------------------------------------------
// Provider cards
// ---------------------------------------------------------------------------

function renderProviders(providerStatus) {
  const container = byId("providerGrid");
  container.replaceChildren();
  PROVIDER_GROUPS.forEach((group) => {
    const providers = providerStatus.filter(
      (provider) => (provider.kind === "local" ? "local" : "remote") === group.kind,
    );
    if (providers.length === 0) return;

    const section = document.createElement("section");
    section.className = "provider-group";
    section.dataset.kind = group.kind;
    const headingId = `provider-group-${group.kind}`;
    section.setAttribute("aria-labelledby", headingId);

    const header = document.createElement("div");
    header.className = "provider-group-header";
    const heading = document.createElement("h4");
    heading.id = headingId;
    heading.textContent = group.title;
    const count = document.createElement("span");
    count.className = "provider-group-count";
    const description = document.createElement("span");
    description.className = "provider-group-description";
    description.textContent = group.description;
    header.append(heading, count, description);

    const grid = document.createElement("div");
    grid.className = "provider-grid";
    grid.setAttribute("role", "list");
    providers.forEach((provider) => grid.appendChild(renderProviderCard(provider)));

    section.append(header, grid);
    container.appendChild(section);
  });
  applyProviderFilter();
}

function renderProviderCard(provider) {
  const name = provider.display_name || provider.provider_id;
  const card = document.createElement("article");
  card.className = "provider-card";
  card.dataset.provider = provider.provider_id;
  card.dataset.kind = provider.kind;
  card.setAttribute("role", "listitem");

  const body = document.createElement("div");
  body.className = "provider-card-body";

  const title = document.createElement("div");
  title.className = "provider-title";
  const titleText = document.createElement("strong");
  titleText.textContent = name;
  titleText.title = name;
  title.appendChild(titleText);

  const meta = document.createElement("div");
  meta.className = "provider-meta";
  meta.textContent =
    provider.kind === "local"
      ? provider.base_url || "No local URL configured"
      : provider.configuration;
  meta.title = meta.textContent;

  const badges = document.createElement("div");
  badges.className = "provider-badges";
  const pill = document.createElement("span");
  pill.className = "status-pill";
  const kindTag = document.createElement("span");
  kindTag.className = "kind-tag";
  kindTag.textContent = provider.kind === "local" ? "Local" : "Cloud";
  badges.append(pill, kindTag);

  body.append(title, meta, badges);

  const editBtn = document.createElement("button");
  editBtn.type = "button";
  editBtn.className = "provider-edit-btn";
  editBtn.setAttribute("aria-label", `Configure ${name}`);
  editBtn.title = `Configure ${name}`;
  editBtn.innerHTML = GEAR_ICON;

  card.append(getProviderIcon(provider.provider_id, provider.display_name), body, editBtn);
  setCardStatus(card, provider.status, provider.label);

  card.addEventListener("click", () => {
    openProviderModal(provider.provider_id, editBtn);
  });
  return card;
}

function findProviderCard(providerId) {
  return document.querySelector(
    `#providerGrid .provider-card[data-provider="${CSS.escape(providerId)}"]`,
  );
}

function setCardStatus(card, status, label) {
  const tone = statusClass(status);
  const pill = card.querySelector(".status-pill");
  pill.className = `status-pill ${tone}`;
  pill.textContent = label || "";
  card.dataset.status = status || "";
  card.dataset.tone = tone;
}

function updateProviderCard(providerId, status, label, metaText) {
  const card = findProviderCard(providerId);
  if (!card) return;
  setCardStatus(card, status, label);
  if (metaText) {
    const meta = card.querySelector(".provider-meta");
    meta.textContent = metaText;
    meta.title = metaText;
  }
  applyProviderFilter();
}

function applyProviderFilter() {
  const query = state.providerFilter.query.trim().toLocaleLowerCase();
  const { configuredOnly } = state.providerFilter;
  let total = 0;
  let visible = 0;
  let ready = 0;

  document.querySelectorAll("#providerGrid .provider-group").forEach((group) => {
    const cards = Array.from(group.querySelectorAll(".provider-card"));
    let groupVisible = 0;
    cards.forEach((card) => {
      const isReady = card.dataset.tone === "ok";
      const haystack = `${card.dataset.provider} ${card.textContent}`.toLocaleLowerCase();
      const matches = (!query || haystack.includes(query)) && (!configuredOnly || isReady);
      card.hidden = !matches;
      if (matches) groupVisible += 1;
      if (isReady) ready += 1;
    });
    group.hidden = groupVisible === 0;
    group.querySelector(".provider-group-count").textContent =
      groupVisible === cards.length ? String(cards.length) : `${groupVisible} of ${cards.length}`;
    total += cards.length;
    visible += groupVisible;
  });

  byId("providerEmpty").hidden = total === 0 || visible > 0;
  byId("providerSummary").textContent = total
    ? `${ready} of ${total} provider${total === 1 ? "" : "s"} configured or reachable`
    : "";
}

// ---------------------------------------------------------------------------
// Config sections & fields
// ---------------------------------------------------------------------------

function renderSections(sections, fields) {
  state.modelComboboxes.clear();
  VIEW_GROUPS.forEach((view) => {
    if (view.id !== "logs" && view.id !== "settings") {
      byId(view.containerId).replaceChildren();
    }
  });

  const sectionById = new Map(sections.map((section) => [section.id, section]));
  const bySection = new Map();
  sections.forEach((section) => bySection.set(section.id, []));
  fields.forEach((field) => {
    if (!bySection.has(field.section)) bySection.set(field.section, []);
    bySection.get(field.section).push(field);
  });

  VIEW_GROUPS.forEach((view) => {
    const container = byId(view.containerId);
    view.sections.forEach((sectionId) => {
      const section = sectionById.get(sectionId);
      const sectionFields = bySection.get(sectionId) || [];
      if (!section || sectionFields.length === 0) return;

      if (sectionId === "providers") {
        const hiddenContainer = byId("hiddenFieldsContainer");
        hiddenContainer.replaceChildren();
        sectionFields.forEach((field) => {
          hiddenContainer.appendChild(renderField(field));
        });
        return;
      }

      const sectionEl = document.createElement("section");
      sectionEl.className = "settings-section";
      sectionEl.id = `section-${section.id}`;

      const heading = document.createElement("div");
      heading.className = "section-heading";
      const headingText = document.createElement("div");
      const title = document.createElement("h3");
      title.textContent = section.label;
      const description = document.createElement("p");
      description.textContent = section.description;
      headingText.append(title, description);
      heading.appendChild(headingText);
      if (section.id === "models") {
        const refreshButton = document.createElement("button");
        refreshButton.type = "button";
        refreshButton.className = "secondary-button button-sm";
        refreshButton.textContent = "Refresh models";
        refreshButton.addEventListener("click", () => refreshModelOptions(refreshButton));
        heading.appendChild(refreshButton);
      }
      sectionEl.appendChild(heading);

      const grid = document.createElement("div");
      grid.className = "field-grid";
      grid.id = `section-${section.id}-fields`;
      sectionFields.forEach((field) => {
        grid.appendChild(renderField(field));
      });
      sectionEl.appendChild(grid);

      if (sectionFields.some((field) => field.advanced)) {
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "ghost-button button-sm advanced-toggle";
        toggle.textContent = "Show advanced";
        toggle.setAttribute("aria-expanded", "false");
        toggle.setAttribute("aria-controls", grid.id);
        toggle.addEventListener("click", () => {
          const showing = sectionEl.classList.toggle("show-advanced");
          toggle.textContent = showing ? "Hide advanced" : "Show advanced";
          toggle.setAttribute("aria-expanded", String(showing));
        });
        sectionEl.appendChild(toggle);
      }

      container.appendChild(sectionEl);
    });
  });
}

function renderField(field) {
  const wrapper = document.createElement("div");
  wrapper.className = `field${field.advanced ? " advanced-field" : ""}`;
  wrapper.dataset.key = field.key;

  const label = document.createElement("label");
  label.htmlFor = `field-${field.key}`;
  const labelText = document.createElement("span");
  labelText.textContent = field.label;
  label.appendChild(labelText);

  const source = sourceText(field);
  if (source) {
    const sourceEl = document.createElement("span");
    sourceEl.className = "field-source";
    sourceEl.textContent = source;
    label.appendChild(sourceEl);
  }

  const input = inputForField(field);
  input.id = `field-${field.key}`;
  input.dataset.key = field.key;
  // Checkboxes normalize their own original value ("true"/"false"); using the raw
  // env value (e.g. "True", "1", "") would report a phantom unsaved change.
  if (input.dataset.original === undefined) {
    input.dataset.original = field.value || "";
  }
  input.dataset.secret = field.secret ? "true" : "false";
  input.dataset.configured = field.configured ? "true" : "false";
  input.dataset.fieldType = field.type;
  input.disabled = field.locked;
  input.addEventListener("input", updateDirtyState);
  input.addEventListener("change", updateDirtyState);
  if (field.type === "optional_model") {
    input.addEventListener("blur", () => {
      if (!input.value.trim() || input.value.trim().toLowerCase() === "none") {
        input.value = "None";
        updateDirtyState();
      }
    });
  }

  const control =
    field.type === "model" || field.type === "optional_model"
      ? new ModelCombobox(input, field).element
      : input;
  wrapper.append(label, control);
  if (field.description) {
    const description = document.createElement("div");
    description.className = "field-description";
    description.id = `field-${field.key}-description`;
    renderRichText(description, field.description);
    input.setAttribute("aria-describedby", description.id);
    wrapper.appendChild(description);
  }
  return wrapper;
}

function inputForField(field) {
  if (field.type === "boolean") {
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = String(field.value).toLowerCase() === "true";
    input.dataset.original = input.checked ? "true" : "false";
    return input;
  }

  if (field.type === "select") {
    const select = document.createElement("select");
    field.options.forEach((item) =>
      select.appendChild(option(item.value, item.label)),
    );
    select.value = field.value || field.options[0]?.value || "";
    return select;
  }

  if (field.type === "textarea") {
    const textarea = document.createElement("textarea");
    textarea.value = field.value || "";
    return textarea;
  }

  if (field.type === "model" || field.type === "optional_model") {
    const input = document.createElement("input");
    input.type = "text";
    input.value = field.value || (field.type === "optional_model" ? "None" : "");
    input.autocomplete = "off";
    input.spellcheck = false;
    return input;
  }

  const input = document.createElement("input");
  input.type = field.type === "number" ? "number" : "text";
  if (field.type === "secret") {
    input.type = "password";
    input.placeholder = field.configured
      ? "Configured - enter a new value to replace"
      : "Not configured";
    input.value = "";
    input.autocomplete = "off";
  } else {
    input.value = field.value || "";
  }
  return input;
}

class ModelCombobox {
  constructor(input, field) {
    this.input = input;
    this.fieldType = field.type;
    this.activeIndex = -1;
    this.query = "";

    this.element = document.createElement("div");
    this.element.className = "model-combobox";
    this.listbox = document.createElement("div");
    this.listbox.className = "model-combobox-list";
    this.listbox.id = `model-options-${field.key}`;
    this.listbox.setAttribute("role", "listbox");
    this.listbox.hidden = true;
    this.toggle = document.createElement("button");
    this.toggle.type = "button";
    this.toggle.className = "model-combobox-toggle";
    this.toggle.disabled = input.disabled;
    this.toggle.setAttribute("aria-label", `Show ${field.label} options`);

    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-haspopup", "listbox");
    for (const control of [input, this.toggle]) {
      control.setAttribute("aria-controls", this.listbox.id);
      control.setAttribute("aria-expanded", "false");
    }

    input.addEventListener("click", () => this.open());
    input.addEventListener("input", () => this.open(input.value));
    input.addEventListener("keydown", (event) => this.handleKeydown(event));
    this.toggle.addEventListener("mousedown", (event) => event.preventDefault());
    this.toggle.addEventListener("click", () => {
      if (this.isOpen) this.close();
      else this.open();
      input.focus();
    });
    this.listbox.addEventListener("mousedown", (event) => event.preventDefault());
    this.listbox.addEventListener("mousemove", (event) => {
      const optionEl = event.target.closest('[role="option"]');
      if (optionEl) this.setActive(this.visibleOptions.indexOf(optionEl));
    });
    this.listbox.addEventListener("click", (event) => {
      const optionEl = event.target.closest('[role="option"]');
      if (optionEl) this.select(optionEl.dataset.value);
    });

    this.element.append(input, this.toggle, this.listbox);
    state.modelComboboxes.add(this);
  }

  get isOpen() {
    return this.element.classList.contains("open");
  }

  get values() {
    return this.fieldType === "optional_model"
      ? ["None", ...state.modelOptions]
      : state.modelOptions;
  }

  get visibleOptions() {
    return Array.from(this.listbox.querySelectorAll('[role="option"]'));
  }

  open(query = "") {
    if (this.input.disabled) return;
    state.modelComboboxes.forEach((combobox) => {
      if (combobox !== this) combobox.close();
    });
    this.render(query);
    this.element.classList.add("open");
    this.listbox.hidden = false;
    this.setExpanded(true);
  }

  close() {
    this.element.classList.remove("open");
    this.listbox.hidden = true;
    this.activeIndex = -1;
    this.input.removeAttribute("aria-activedescendant");
    this.setExpanded(false);
  }

  setExpanded(expanded) {
    for (const control of [this.input, this.toggle]) {
      control.setAttribute("aria-expanded", String(expanded));
    }
  }

  render(query) {
    this.query = query;
    const normalizedQuery = query.trim().toLocaleLowerCase();
    const values = normalizedQuery
      ? this.values.filter((value) =>
          value.toLocaleLowerCase().includes(normalizedQuery),
        )
      : this.values;
    this.listbox.replaceChildren();

    if (values.length === 0) {
      const empty = document.createElement("div");
      empty.className = "model-combobox-empty";
      empty.textContent = state.modelOptions.length
        ? "No matching models. You can still enter a custom slug."
        : "No discovered models. Refresh models or enter a custom slug.";
      this.listbox.appendChild(empty);
      this.activeIndex = -1;
      this.input.removeAttribute("aria-activedescendant");
      return;
    }

    values.forEach((value, index) => {
      const optionEl = document.createElement("div");
      optionEl.className = "model-combobox-option";
      optionEl.id = `${this.listbox.id}-option-${index}`;
      optionEl.dataset.value = value;
      optionEl.setAttribute("role", "option");
      optionEl.textContent = value;
      this.listbox.appendChild(optionEl);
    });
    const selectedIndex = values.indexOf(this.input.value);
    this.setActive(selectedIndex >= 0 ? selectedIndex : 0, false);
  }

  setActive(index, scroll = true) {
    const options = this.visibleOptions;
    if (options.length === 0) return;
    this.activeIndex = Math.max(0, Math.min(index, options.length - 1));
    options.forEach((optionEl, optionIndex) => {
      const active = optionIndex === this.activeIndex;
      optionEl.classList.toggle("active", active);
      optionEl.setAttribute("aria-selected", String(active));
    });
    const activeOption = options[this.activeIndex];
    this.input.setAttribute("aria-activedescendant", activeOption.id);
    if (scroll) activeOption.scrollIntoView({ block: "nearest" });
  }

  move(offset) {
    const count = this.visibleOptions.length;
    if (count) this.setActive((this.activeIndex + offset + count) % count);
  }

  select(value) {
    this.input.value = value;
    this.input.dispatchEvent(new Event("change", { bubbles: true }));
    this.close();
    this.input.focus();
  }

  handleKeydown(event) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (this.isOpen) {
        this.move(event.key === "ArrowDown" ? 1 : -1);
      } else {
        this.open();
        if (event.key === "ArrowUp") {
          this.setActive(this.visibleOptions.length - 1);
        }
      }
    } else if (this.isOpen && (event.key === "Home" || event.key === "End")) {
      event.preventDefault();
      this.setActive(event.key === "Home" ? 0 : this.visibleOptions.length - 1);
    } else if (this.isOpen && event.key === "Enter") {
      const active = this.visibleOptions[this.activeIndex];
      if (active) {
        event.preventDefault();
        this.select(active.dataset.value);
      }
    } else if (this.isOpen && event.key === "Escape") {
      event.preventDefault();
      this.close();
    } else if (this.isOpen && event.key === "Tab") {
      this.close();
    }
  }
}

function option(value, label) {
  const optionEl = document.createElement("option");
  optionEl.value = value;
  optionEl.textContent = label;
  return optionEl;
}

// ---------------------------------------------------------------------------
// Dirty state, validate & apply
// ---------------------------------------------------------------------------

function readFieldValue(input) {
  if (input.type === "checkbox") return input.checked ? "true" : "false";
  if (
    input.dataset.fieldType === "optional_model" &&
    input.value.trim().toLowerCase() === "none"
  ) {
    return "";
  }
  if (input.dataset.secret === "true" && input.dataset.configured === "true") {
    return input.value ? input.value : MASKED_SECRET;
  }
  return input.value;
}

function changedValues() {
  const values = {};
  document.querySelectorAll("[data-key]").forEach((input) => {
    if (input.disabled || !input.matches("input, select, textarea")) return;
    const value = readFieldValue(input);
    if (value !== input.dataset.original) {
      values[input.dataset.key] = value;
    }
  });
  return values;
}

function updateDirtyState() {
  const count = Object.keys(changedValues()).length;
  byId("dirtyState").textContent =
    count === 0 ? "No changes" : `${count} unsaved change${count === 1 ? "" : "s"}`;
  document.querySelector(".action-bar").classList.toggle("is-dirty", count > 0);
  byId("applyButton").disabled = count === 0 || state.busy || state.restarting;
  return count;
}

// Serializes validate/apply so double clicks cannot submit overlapping requests,
// and surfaces failures instead of leaving unhandled promise rejections.
async function runAction(action) {
  if (state.busy) return undefined;
  setBusy(true);
  try {
    return await action();
  } catch (error) {
    showMessage(error.message || String(error), "error");
    return undefined;
  } finally {
    setBusy(false);
  }
}

function setBusy(busy) {
  state.busy = busy;
  byId("validateButton").disabled = busy;
  byId("modalSaveBtn").disabled = busy;
  document.querySelector(".action-bar").setAttribute("aria-busy", String(busy));
  updateDirtyState();
}

async function validate(showResult = true) {
  const result = await api("/admin/api/config/validate", {
    method: "POST",
    body: JSON.stringify({ values: changedValues() }),
  });
  if (showResult) {
    showValidationResult(result);
  }
  return result;
}

function validationErrorText(result) {
  return (result.errors || []).join("; ") || "Configuration is invalid";
}

function showValidationResult(result) {
  if (result.valid) {
    showMessage("Config shape is valid", "ok");
  } else {
    showMessage(validationErrorText(result), "error");
  }
}

async function apply() {
  const result = await api("/admin/api/config/apply", {
    method: "POST",
    body: JSON.stringify({ values: changedValues() }),
  });
  if (!result.applied) {
    showValidationResult(result);
    return result;
  }
  const restart = result.restart || {};
  if (restart.required && restart.automatic) {
    state.restarting = true;
    showMessage("Applied. Restarting server...", "ok");
    byId("applyButton").disabled = true;
    setTimeout(() => {
      window.location.href = restart.admin_url || "/admin";
    }, 1600);
    return result;
  }
  const pending = restart.required ? restart.fields || [] : result.pending_fields || [];
  await load();
  showMessage(
    pending.length
      ? `Applied. Restart codefa-server to use: ${pending.join(", ")}`
      : "Applied",
    "ok",
  );
  return result;
}

async function refreshLocalStatus() {
  const result = await api("/admin/api/providers/local-status");
  result.providers.forEach((provider) => {
    state.localStatus.set(provider.provider_id, provider);
    const meta = provider.status_code
      ? `${provider.base_url} returned HTTP ${provider.status_code}`
      : provider.base_url;
    updateProviderCard(provider.provider_id, provider.status, provider.label, meta);
  });
}

// ---------------------------------------------------------------------------
// Model options
// ---------------------------------------------------------------------------

async function hydrateModelOptions() {
  try {
    await loadModelOptions();
  } catch {
    // Model fields remain editable when optional catalog hydration is unavailable.
  }
}

async function loadModelOptions(refresh = false) {
  const result = await api("/admin/api/models" + (refresh ? "/refresh" : ""), {
    method: refresh ? "POST" : "GET",
  });
  setModelOptions(result.models);
  return result;
}

async function refreshModelOptions(button) {
  const original = button.textContent;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.textContent = "Refreshing...";
  try {
    const result = await loadModelOptions(true);
    const failedProviders = result.failed_providers || [];
    if (failedProviders.length) {
      const labels = failedProviders.map(providerDisplayName).join(", ");
      showMessage(
        `${state.modelOptions.length} models available; could not refresh ${labels}`,
        "warn",
      );
    } else {
      showMessage(`${state.modelOptions.length} models available`, "ok");
    }
  } catch (error) {
    showMessage(`Could not refresh models: ${error.message}`, "error");
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = original;
  }
}

function providerDisplayName(providerId) {
  const provider = state.config?.provider_status?.find(
    (candidate) => candidate.provider_id === providerId,
  );
  return provider?.display_name || providerId;
}

function setModelOptions(models) {
  state.modelOptions = Array.from(
    new Set((models || []).filter((model) => typeof model === "string" && model.trim())),
  ).sort((left, right) => left.localeCompare(right));
  state.modelComboboxes.forEach((combobox) => {
    if (combobox.isOpen) combobox.render(combobox.query);
  });
}

function showMessage(message, kind = "") {
  const area = byId("messageArea");
  area.textContent = message;
  area.className = `message-area ${kind}`.trim();
}

// ---------------------------------------------------------------------------
// Logs
// ---------------------------------------------------------------------------

const LOG_SKIP_KEYS = new Set(["time", "level", "message", "module", "function", "line"]);

const logs = {
  intervalId: null,
  entries: [],
  levelFilter: "ALL",
  query: "",
  // Last entry visible when "Clear View" was pressed. The server returns a sliding
  // window of recent lines, so clearing must be anchored to an entry, not an index.
  clearMarker: null,
  renderedHtml: null,
  requestSeq: 0,
};

const logEntryKey = (entry) => JSON.stringify(entry);

async function loadLogs() {
  const seq = ++logs.requestSeq;
  try {
    const data = await api("/admin/api/logs");
    // Ignore responses that were overtaken by a newer request.
    if (seq !== logs.requestSeq) return;
    logs.entries = Array.isArray(data.logs) ? data.logs : [];
    renderLogs();
  } catch (error) {
    if (seq !== logs.requestSeq) return;
    showLogsNotice(`Error loading logs: ${error.message}`, true);
  }
}

function visibleLogEntries() {
  let entries = logs.entries;
  if (logs.clearMarker !== null) {
    const markerIndex = entries.map(logEntryKey).lastIndexOf(logs.clearMarker);
    // When the marker has scrolled out of the server window, every entry is newer.
    if (markerIndex >= 0) entries = entries.slice(markerIndex + 1);
  }

  if (logs.levelFilter !== "ALL") {
    entries = entries.filter(
      (log) => String(log.level || "INFO").toUpperCase() === logs.levelFilter,
    );
  }

  const query = logs.query.trim().toLowerCase();
  if (query) {
    entries = entries.filter((log) =>
      [log.message, log.level, log.module].some((value) =>
        String(value || "").toLowerCase().includes(query),
      ),
    );
  }
  return entries;
}

function formatLogTime(time) {
  const text = String(time || "");
  return text.match(/\d{2}:\d{2}:\d{2}/)?.[0] || text;
}

function logRowHtml(log) {
  const level = String(log.level || "INFO").toUpperCase();
  const levelClass = level.toLowerCase().replace(/[^a-z]/g, "");
  const extras = Object.entries(log)
    .filter(([key, value]) => !LOG_SKIP_KEYS.has(key) && value !== null && value !== undefined)
    .map(([key, value]) => `${key}=${typeof value === "object" ? JSON.stringify(value) : value}`);
  const extra = extras.length
    ? `<span class="log-extra">[${escapeHtml(extras.join(" "))}]</span>`
    : "";
  return (
    `<div class="log-row level-${levelClass}">` +
    `<span class="log-time">${escapeHtml(formatLogTime(log.time))}</span>` +
    `<span class="log-level">${escapeHtml(level)}</span>` +
    `<span class="log-message">${escapeHtml(log.message || "")}${extra}</span>` +
    `</div>`
  );
}

function renderLogs() {
  const container = byId("logsContainer");
  const entries = visibleLogEntries();
  updateLogsFooter(entries.length);

  if (entries.length === 0) {
    const filtered = logs.query.trim() || logs.levelFilter !== "ALL";
    showLogsNotice(
      logs.entries.length === 0
        ? "No logs available."
        : filtered
          ? "No matching logs found."
          : "View cleared. New log entries will appear here.",
    );
    return;
  }

  const html = entries.map(logRowHtml).join("");
  // Skip identical re-renders so polling does not reset text selection or scroll.
  if (html === logs.renderedHtml) return;
  const previousScrollTop = container.scrollTop;
  container.innerHTML = html;
  logs.renderedHtml = html;

  const autoScroll = byId("autoScrollLogs");
  container.scrollTop = autoScroll && autoScroll.checked ? container.scrollHeight : previousScrollTop;
}

function showLogsNotice(message, isError = false) {
  const notice = document.createElement("div");
  notice.className = `logs-notice${isError ? " error" : ""}`;
  notice.textContent = message;
  byId("logsContainer").replaceChildren(notice);
  logs.renderedHtml = null;
  if (isError) updateLogsFooter(null);
}

function updateLogsFooter(visibleCount) {
  const footer = byId("logsFooter");
  if (visibleCount === null) {
    footer.textContent = "";
    return;
  }
  const total = logs.entries.length;
  footer.textContent = `Showing ${visibleCount} of ${total} recent entr${total === 1 ? "y" : "ies"}`;
}

function setLogsLive(live) {
  const indicator = byId("logsLiveIndicator");
  indicator.classList.toggle("is-live", live);
  indicator.querySelector(".live-text").textContent = live ? "Live" : "Paused";
}

function startLogsInterval() {
  if (logs.intervalId || document.hidden) return;
  logs.intervalId = setInterval(loadLogs, LOGS_POLL_MS);
  setLogsLive(true);
}

function stopLogsInterval() {
  if (logs.intervalId) {
    clearInterval(logs.intervalId);
    logs.intervalId = null;
  }
  setLogsLive(false);
}

// ---------------------------------------------------------------------------
// Provider icons & fields
// ---------------------------------------------------------------------------

let currentProviderId = null;
let modalReturnFocus = null;
let backdropPointerDown = false;

function getProviderIcon(providerId, displayName) {
  const iconsData = {
  "anthropic_api": {
    "path": "M17.3041 3.541h-3.6718l6.696 16.918H24Zm-10.6082 0L0 20.459h3.7442l1.3693-3.5527h7.0052l1.3693 3.5528h3.7442L10.5363 3.5409Zm-.3712 10.2232 2.2914-5.9456 2.2914 5.9456Z",
    "color": "#D97757",
    "bg": "rgba(217, 119, 87, 0.15)"
  },
  "openai_api": {
    "path": "M22.2819 9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 4.9807 4.1818a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001 6.0557 6.0557 0 0 0-.7475-7.0729zm-9.022 12.6081a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 4.7783-2.7582a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1686a.071.071 0 0 1 .038.052v5.5826a4.504 4.504 0 0 1-4.4945 4.4944zm-9.6607-4.1254a4.4708 4.4708 0 0 1-.5346-3.0137l.142.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324a.0804.0804 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6464zM2.3408 7.8956a4.485 4.485 0 0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1685a.0757.0757 0 0 1-.071 0l-4.8303-2.7865A4.504 4.504 0 0 1 2.3408 7.872zm16.5963 3.8558L13.1038 8.364 15.1192 7.2a.0757.0757 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 0-.407-.667zm2.0107-3.0231l-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L9.409 9.2297V6.8974a.0662.0662 0 0 1 .0284-.0615l4.8303-2.7866a4.4992 4.4992 0 0 1 6.6802 4.66zM8.3065 12.863l-2.02-1.1638a.0804.0804 0 0 1-.038-.0567V6.0742a4.4992 4.4992 0 0 1 7.3757-3.4537l-.142.0805L8.704 5.459a.7948.7948 0 0 0-.3927.6813zm1.0976-2.3654l2.602-1.4998 2.6069 1.4998v2.9994l-2.5974 1.4997-2.6067-1.4997Z",
    "color": "#FFFFFF",
    "bg": "rgba(255, 255, 255, 0.15)"
  },
  "nvidia_nim": {
    "path": "M8.948 8.798v-1.43a6.7 6.7 0 0 1 .424-.018c3.922-.124 6.493 3.374 6.493 3.374s-2.774 3.851-5.75 3.851c-.398 0-.787-.062-1.158-.185v-4.346c1.528.185 1.837.857 2.747 2.385l2.04-1.714s-1.492-1.952-4-1.952a6.016 6.016 0 0 0-.796.035m0-4.735v2.138l.424-.027c5.45-.185 9.01 4.47 9.01 4.47s-4.08 4.964-8.33 4.964c-.37 0-.733-.035-1.095-.097v1.325c.3.035.61.062.91.062 3.957 0 6.82-2.023 9.593-4.408.459.371 2.34 1.263 2.73 1.652-2.633 2.208-8.772 3.984-12.253 3.984-.335 0-.653-.018-.971-.053v1.864H24V4.063zm0 10.326v1.131c-3.657-.654-4.673-4.46-4.673-4.46s1.758-1.944 4.673-2.262v1.237H8.94c-1.528-.186-2.73 1.245-2.73 1.245s.68 2.412 2.739 3.11M2.456 10.9s2.164-3.197 6.5-3.533V6.201C4.153 6.59 0 10.653 0 10.653s2.35 6.802 8.948 7.42v-1.237c-4.84-.6-6.492-5.936-6.492-5.936z",
    "color": "#76B900",
    "bg": "rgba(118, 185, 0, 0.15)"
  },
  "open_router": {
    "path": "M16.778 1.844v1.919q-.569-.026-1.138-.032-.708-.008-1.415.037c-1.93.126-4.023.728-6.149 2.237-2.911 2.066-2.731 1.95-4.14 2.75-.396.223-1.342.574-2.185.798-.841.225-1.753.333-1.751.333v4.229s.768.108 1.61.333c.842.224 1.789.575 2.185.799 1.41.798 1.228.683 4.14 2.75 2.126 1.509 4.22 2.11 6.148 2.236.88.058 1.716.041 2.555.005v1.918l7.222-4.168-7.222-4.17v2.176c-.86.038-1.611.065-2.278.021-1.364-.09-2.417-.357-3.979-1.465-2.244-1.593-2.866-2.027-3.68-2.508.889-.518 1.449-.906 3.822-2.59 1.56-1.109 2.614-1.377 3.978-1.466.667-.044 1.418-.017 2.278.02v2.176L24 6.014Z",
    "color": "#6366F1",
    "bg": "rgba(99, 102, 241, 0.15)"
  },
  "gemini": {
    "path": "M11.04 19.32Q12 21.51 12 24q0-2.49.93-4.68.96-2.19 2.58-3.81t3.81-2.55Q21.51 12 24 12q-2.49 0-4.68-.93a12.3 12.3 0 0 1-3.81-2.58 12.3 12.3 0 0 1-2.58-3.81Q12 2.49 12 0q0 2.49-.96 4.68-.93 2.19-2.55 3.81a12.3 12.3 0 0 1-3.81 2.58Q2.49 12 0 12q2.49 0 4.68.96 2.19.93 3.81 2.55t2.55 3.81",
    "color": "#8E75B2",
    "bg": "rgba(142, 117, 178, 0.15)"
  },
  "vertex": {
    "path": "M12.19 2.38a9.344 9.344 0 0 0-9.234 6.893c.053-.02-.055.013 0 0-3.875 2.551-3.922 8.11-.247 10.941l.006-.007-.007.03a6.717 6.717 0 0 0 4.077 1.356h5.173l.03.03h5.192c6.687.053 9.376-8.605 3.835-12.35a9.365 9.365 0 0 0-2.821-4.552l-.043.043.006-.05A9.344 9.344 0 0 0 12.19 2.38zm-.358 4.146c1.244-.04 2.518.368 3.486 1.15a5.186 5.186 0 0 1 1.862 4.078v.518c3.53-.07 3.53 5.262 0 5.193h-5.193l-.008.009v-.04H6.785a2.59 2.59 0 0 1-1.067-.23h.001a2.597 2.597 0 1 1 3.437-3.437l3.013-3.012A6.747 6.747 0 0 0 8.11 8.24c.018-.01.04-.026.054-.023a5.186 5.186 0 0 1 3.67-1.69z",
    "color": "#4285F4",
    "bg": "rgba(66, 133, 244, 0.15)"
  },
  "deepseek": {
    "path": "M23.748 4.651c-.254-.124-.364.113-.512.233-.051.04-.094.09-.137.137-.372.397-.806.657-1.373.626-.829-.046-1.537.214-2.163.848-.133-.782-.575-1.248-1.247-1.548-.352-.155-.708-.311-.955-.65-.172-.24-.219-.509-.305-.774-.055-.16-.11-.323-.293-.35-.2-.031-.278.136-.356.276-.313.572-.434 1.202-.422 1.84.027 1.436.633 2.58 1.838 3.393.137.094.172.187.129.323-.082.28-.18.553-.266.833-.055.179-.137.218-.328.14a5.5 5.5 0 0 1-1.737-1.179c-.857-.828-1.631-1.743-2.597-2.46a12 12 0 0 0-.689-.47c-.985-.957.13-1.743.387-1.836.27-.098.094-.433-.778-.428-.872.003-1.67.295-2.687.685a3 3 0 0 1-.465.136 9.6 9.6 0 0 0-2.883-.101c-1.885.21-3.39 1.1-4.497 2.622C.082 8.776-.231 10.854.152 13.02c.403 2.284 1.568 4.175 3.36 5.653 1.857 1.533 3.997 2.284 6.438 2.14 1.482-.085 3.132-.284 4.994-1.86.47.234.962.328 1.78.398.629.058 1.235-.031 1.705-.129.735-.155.684-.836.418-.961-2.155-1.004-1.682-.595-2.112-.926 1.095-1.295 2.768-3.598 3.284-6.733.05-.346.115-.834.108-1.114-.004-.171.035-.238.23-.257a4.2 4.2 0 0 0 1.545-.475c1.397-.763 1.96-2.016 2.093-3.517.02-.23-.004-.467-.247-.588M11.58 18.168c-2.088-1.642-3.101-2.183-3.52-2.16-.39.024-.32.472-.234.763.09.288.207.487.371.74.114.167.192.416-.113.603-.673.416-1.842-.14-1.897-.168-1.361-.801-2.5-1.86-3.301-3.306-.775-1.393-1.225-2.888-1.299-4.482-.02-.385.094-.522.477-.592a4.7 4.7 0 0 1 1.53-.038c2.131.311 3.946 1.264 5.467 2.774.868.86 1.525 1.887 2.202 2.89.72 1.066 1.494 2.082 2.48 2.915.348.291.626.513.892.677-.802.09-2.14.109-3.055-.615zm1.001-6.44a.306.306 0 0 1 .415-.287.3.3 0 0 1 .113.074.3.3 0 0 1 .086.214c0 .17-.136.307-.308.307a.303.303 0 0 1-.306-.307m3.11 1.596c-.2.081-.4.151-.591.16a1.25 1.25 0 0 1-.798-.254c-.274-.23-.47-.358-.551-.758a1.7 1.7 0 0 1 .015-.588c.07-.327-.007-.537-.238-.727-.188-.156-.426-.199-.689-.199a.6.6 0 0 1-.254-.078.253.253 0 0 1-.114-.358 1 1 0 0 1 .192-.21c.356-.202.767-.136 1.146.016.352.144.618.408 1.001.782.392.451.462.576.685.915.176.264.336.536.446.848.066.194-.02.353-.25.45",
    "color": "#4D6BFE",
    "bg": "rgba(77, 107, 254, 0.15)"
  },
  "mistral": {
    "path": "M17.143 3.429v3.428h-3.429v3.429h-3.428V6.857H6.857V3.43H3.43v13.714H0v3.428h10.286v-3.428H6.857v-3.429h3.429v3.429h3.429v-3.429h3.428v3.429h-3.428v3.428H24v-3.428h-3.43V3.429z",
    "color": "#FA520F",
    "bg": "rgba(250, 82, 15, 0.15)"
  },
  "mistral_codestral": {
    "path": "M17.143 3.429v3.428h-3.429v3.429h-3.428V6.857H6.857V3.43H3.43v13.714H0v3.428h10.286v-3.428H6.857v-3.429h3.429v3.429h3.429v-3.429h3.428v3.429h-3.428v3.428H24v-3.428h-3.43V3.429z",
    "color": "#FA520F",
    "bg": "rgba(250, 82, 15, 0.15)"
  },
  "opencode": {
    "path": "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
    "color": "#00F0FF",
    "bg": "rgba(0, 240, 255, 0.15)",
    "stroke": true
  },
  "opencode_go": {
    "path": "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
    "color": "#00F0FF",
    "bg": "rgba(0, 240, 255, 0.15)",
    "stroke": true
  },
  "vercel": {
    "path": "m12 1.608 12 20.784H0Z",
    "color": "#FFFFFF",
    "bg": "rgba(255, 255, 255, 0.15)"
  },
  "bedrock": {
    "path": "M12 2L2 7v10l10 5 10-5V7L12 2zm0 2.8L18.5 8 12 11.2 5.5 8 12 4.8zM4 9.3l7 3.5v6.9l-7-3.5V9.3zm16 0v6.9l-7 3.5v-6.9l7-3.5z",
    "color": "#FF9900",
    "bg": "rgba(255, 153, 0, 0.15)"
  },
  "huggingface": {
    "path": "M12.025 1.13c-5.77 0-10.449 4.647-10.449 10.378 0 1.112.178 2.181.503 3.185.064-.222.203-.444.416-.577a.96.96 0 0 1 .524-.15c.293 0 .584.124.84.284.278.173.48.408.71.694.226.282.458.611.684.951v-.014c.017-.324.106-.622.264-.874s.403-.487.762-.543c.3-.047.596.06.787.203s.31.313.4.467c.15.257.212.468.233.542.01.026.653 1.552 1.657 2.54.616.605 1.01 1.223 1.082 1.912.055.537-.096 1.059-.38 1.572.637.121 1.294.187 1.967.187.657 0 1.298-.063 1.921-.178-.287-.517-.44-1.041-.384-1.581.07-.69.465-1.307 1.081-1.913 1.004-.987 1.647-2.513 1.657-2.539.021-.074.083-.285.233-.542.09-.154.208-.323.4-.467a1.08 1.08 0 0 1 .787-.203c.359.056.604.29.762.543s.247.55.265.874v.015c.225-.34.457-.67.683-.952.23-.286.432-.52.71-.694.257-.16.547-.284.84-.285a.97.97 0 0 1 .524.151c.228.143.373.388.43.625l.006.04a10.3 10.3 0 0 0 .534-3.273c0-5.731-4.678-10.378-10.449-10.378M8.327 6.583a1.5 1.5 0 0 1 .713.174 1.487 1.487 0 0 1 .617 2.013c-.183.343-.762-.214-1.102-.094-.38.134-.532.914-.917.71a1.487 1.487 0 0 1 .69-2.803m7.486 0a1.487 1.487 0 0 1 .689 2.803c-.385.204-.536-.576-.916-.71-.34-.12-.92.437-1.103.094a1.487 1.487 0 0 1 .617-2.013 1.5 1.5 0 0 1 .713-.174m-10.68 1.55a.96.96 0 1 1 0 1.921.96.96 0 0 1 0-1.92m13.838 0a.96.96 0 1 1 0 1.92.96.96 0 0 1 0-1.92M8.489 11.458c.588.01 1.965 1.157 3.572 1.164 1.607-.007 2.984-1.155 3.572-1.164.196-.003.305.12.305.454 0 .886-.424 2.328-1.563 3.202-.22-.756-1.396-1.366-1.63-1.32q-.011.001-.02.006l-.044.026-.01.008-.03.024q-.018.017-.035.036l-.032.04a1 1 0 0 0-.058.09l-.014.025q-.049.088-.11.19a1 1 0 0 1-.083.116 1.2 1.2 0 0 1-.173.18q-.035.029-.075.058a1.3 1.3 0 0 1-.251-.243 1 1 0 0 1-.076-.107c-.124-.193-.177-.363-.337-.444-.034-.016-.104-.008-.2.022q-.094.03-.216.087-.06.028-.125.063l-.13.074q-.067.04-.136.086a3 3 0 0 0-.135.096 3 3 0 0 0-.26.219 2 2 0 0 0-.12.121 2 2 0 0 0-.106.128l-.002.002a2 2 0 0 0-.09.132l-.001.001a1.2 1.2 0 0 0-.105.212q-.013.036-.024.073c-1.139-.875-1.563-2.317-1.563-3.203 0-.334.109-.457.305-.454m.836 10.354c.824-1.19.766-2.082-.365-3.194-1.13-1.112-1.789-2.738-1.789-2.738s-.246-.945-.806-.858-.97 1.499.202 2.362c1.173.864-.233 1.45-.685.64-.45-.812-1.683-2.896-2.322-3.295s-1.089-.175-.938.647 2.822 2.813 2.562 3.244-1.176-.506-1.176-.506-2.866-2.567-3.49-1.898.473 1.23 2.037 2.16c1.564.932 1.686 1.178 1.464 1.53s-3.675-2.511-4-1.297c-.323 1.214 3.524 1.567 3.287 2.405-.238.839-2.71-1.587-3.216-.642-.506.946 3.49 2.056 3.522 2.064 1.29.33 4.568 1.028 5.713-.624m5.349 0c-.824-1.19-.766-2.082.365-3.194 1.13-1.112 1.789-2.738 1.789-2.738s.246-.945.806-.858.97 1.499-.202 2.362c-1.173.864.233 1.45.685.64.451-.812 1.683-2.896 2.322-3.295s1.089-.175.938.647-2.822 2.813-2.562 3.244 1.176-.506 1.176-.506 2.866-2.567 3.49-1.898-.473 1.23-2.037 2.16c-1.564.932-1.686 1.178-1.464 1.53s3.675-2.511 4-1.297c.323 1.214-3.524 1.567-3.287 2.405.238.839 2.71-1.587 3.216-.642.506.946-3.49 2.056-3.522 2.064-1.29.33-4.568 1.028-5.713-.624",
    "color": "#FFD21E",
    "bg": "rgba(255, 210, 30, 0.15)"
  },
  "cohere": {
    "path": "M12 2a10 10 0 100 20 10 10 0 000-20zm0 4a6 6 0 110 12 6 6 0 010-12z",
    "color": "#10B981",
    "bg": "rgba(16, 185, 129, 0.15)"
  },
  "github_models": {
    "path": "M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12",
    "color": "#2DBA4E",
    "bg": "rgba(45, 186, 78, 0.15)"
  },
  "wafer": {
    "path": "M6 2h12a4 4 0 014 4v12a4 4 0 01-4 4H6a4 4 0 01-4-4V6a4 4 0 014-4zm2 4v3h3V6H8zm5 0v3h3V6h-3zm-5 5v3h3v-3H8zm5 0v3h3v-3h-3zm-5 5v3h3v-3H8zm5 0v3h3v-3h-3z",
    "color": "#3B82F6",
    "bg": "rgba(59, 130, 246, 0.15)"
  },
  "kimi": {
    "path": "M21.765.351C22.998.351 24 1.353 24 2.586S22.998 4.82 21.765 4.82h-1.974c-.15 0-.26-.12-.26-.26V2.586A2.237 2.237 0 0 1 21.765.35M9.41 13.388l8.447-8.377c.16-.16.07-.471-.14-.471h-4.55s-.1.02-.14.06l-9.099 9.029c-.14.14-.35.02-.35-.21V4.81c0-.15-.1-.27-.221-.27H.22c-.12 0-.22.12-.22.27v18.57c0 .15.1.27.22.27h3.137c.12 0 .22-.12.22-.27v-3.79c0-.08.03-.16.08-.21l2.826-2.796c.07-.07.16-.08.241-.03l7.546 5.551a8.9 8.9 0 0 0 4.018 1.493c.12.01.23-.11.23-.27V19.76c0-.14-.08-.25-.19-.26a5.8 5.8 0 0 1-2.355-.942l-6.533-4.73c-.14-.09-.15-.32-.03-.441",
    "color": "#FFFFFF",
    "bg": "rgba(255, 255, 255, 0.15)"
  },
  "kimi_code": {
    "path": "m1.053 16.91 9.538 2.55a21 20.981 0 0 0 .06 2.031l5.956 1.592a12 11.99 0 0 1-15.554-6.172m-1.02-5.79 11.352 3.035a21 20.981 0 0 0-.469 2.01l10.817 2.89a12 11.99 0 0 1-1.845 2.004L.658 15.918a12 11.99 0 0 1-.625-4.796m1.593-5.146L13.573 9.17a21 20.981 0 0 0-1.01 1.874l11.297 3.02a21 20.981 0 0 1-.67 2.362l-11.55-3.087L.125 10.26a12 11.99 0 0 1 1.499-4.285ZM6.067 1.58l11.285 3.016a21 20.981 0 0 0-1.688 1.719l7.824 2.091a21 20.981 0 0 1 .513 2.664L2.107 5.218a12 11.99 0 0 1 3.96-3.638M21.68 4.866 7.222 1.003A12 11.99 0 0 1 21.68 4.866",
    "color": "#FFFFFF",
    "bg": "rgba(255, 255, 255, 0.15)"
  },
  "minimax": {
    "path": "M11.43 3.92a.86.86 0 1 0-1.718 0v14.236a1.999 1.999 0 0 1-3.997 0V9.022a.86.86 0 1 0-1.718 0v3.87a1.999 1.999 0 0 1-3.997 0V11.49a.57.57 0 0 1 1.139 0v1.404a.86.86 0 0 0 1.719 0V9.022a1.999 1.999 0 0 1 3.997 0v9.134a.86.86 0 0 0 1.719 0V3.92a1.998 1.998 0 1 1 3.996 0v11.788a.57.57 0 1 1-1.139 0zm10.572 3.105a2 2 0 0 0-1.999 1.997v7.63a.86.86 0 0 1-1.718 0V3.923a1.999 1.999 0 0 0-3.997 0v16.16a.86.86 0 0 1-1.719 0V18.08a.57.57 0 1 0-1.138 0v2a1.998 1.998 0 0 0 3.996 0V3.92a.86.86 0 0 1 1.719 0v12.73a1.999 1.999 0 0 0 3.996 0V9.023a.86.86 0 1 1 1.72 0v6.686a.57.57 0 0 0 1.138 0V9.022a2 2 0 0 0-1.998-1.997",
    "color": "#E73562",
    "bg": "rgba(231, 53, 98, 0.15)"
  },
  "cerebras": {
    "path": "M12 2L2 12l10 10 10-10L12 2zm0 4.5l6.5 6.5-6.5 6.5-6.5-6.5L12 6.5z",
    "color": "#E24A4A",
    "bg": "rgba(226, 74, 74, 0.15)"
  },
  "groq": {
    "path": "M13 2L3 14h9l-1 8 10-12h-9l1-8z",
    "color": "#F55036",
    "bg": "rgba(245, 80, 54, 0.15)"
  },
  "sambanova": {
    "path": "M4 6c0-1.1.9-2 2-2h12a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zm0 10c0-1.1.9-2 2-2h12a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2z",
    "color": "#EE3124",
    "bg": "rgba(238, 49, 36, 0.15)"
  },
  "fireworks": {
    "path": "M12 2c.5 3 2.5 5 5 5-3 .5-5 2.5-5 5-.5-3-2.5-5-5-5 3-.5 5-2.5 5-5zm-6 10c.3 2 1.7 3.3 3.3 3.3-1.6.3-3.3 1.7-3.3 3.3-.3-1.6-1.7-3.3-3.3-3.3 1.6-.3 3.3-1.7 3.3-3.3z",
    "color": "#F97316",
    "bg": "rgba(249, 115, 22, 0.15)"
  },
  "cloudflare": {
    "path": "M16.5088 16.8447c.1475-.5068.0908-.9707-.1553-1.3154-.2246-.3164-.6045-.499-1.0615-.5205l-8.6592-.1123a.1559.1559 0 0 1-.1333-.0713c-.0283-.042-.0351-.0986-.021-.1553.0278-.084.1123-.1484.2036-.1562l8.7359-.1123c1.0351-.0489 2.1601-.8868 2.5537-1.9136l.499-1.3013c.0215-.0561.0293-.1128.0147-.168-.5625-2.5463-2.835-4.4453-5.5499-4.4453-2.5039 0-4.6284 1.6177-5.3876 3.8614-.4927-.3658-1.1187-.5625-1.794-.499-1.2026.119-2.1665 1.083-2.2861 2.2856-.0283.31-.0069.6128.0635.894C1.5683 13.171 0 14.7754 0 16.752c0 .1748.0142.3515.0352.5273.0141.083.0844.1475.1689.1475h15.9814c.0909 0 .1758-.0645.2032-.1553l.12-.4268zm2.7568-5.5634c-.0771 0-.1611 0-.2383.0112-.0566 0-.1054.0415-.127.0976l-.3378 1.1744c-.1475.5068-.0918.9707.1543 1.3164.2256.3164.6055.498 1.0625.5195l1.8437.1133c.0557 0 .1055.0263.1329.0703.0283.043.0351.1074.0214.1562-.0283.084-.1132.1485-.204.1553l-1.921.1123c-1.041.0488-2.1582.8867-2.5527 1.914l-.1406.3585c-.0283.0713.0215.1416.0986.1416h6.5977c.0771 0 .1474-.0489.169-.126.1122-.4082.1757-.837.1757-1.2803 0-2.6025-2.125-4.727-4.7344-4.727",
    "color": "#F38020",
    "bg": "rgba(243, 128, 32, 0.15)"
  },
  "zai": {
    "path": "M5 4h14l-8 10h8v4H5l8-10H5V4z",
    "color": "#3B82F6",
    "bg": "rgba(59, 130, 246, 0.15)"
  },
  "ollama_cloud": {
    "path": "M16.361 10.26a.894.894 0 0 0-.558.47l-.072.148.001.207c0 .193.004.217.059.353.076.193.152.312.291.448.24.238.51.3.872.205a.86.86 0 0 0 .517-.436.752.752 0 0 0 .08-.498c-.064-.453-.33-.782-.724-.897a1.06 1.06 0 0 0-.466 0zm-9.203.005c-.305.096-.533.32-.65.639a1.187 1.187 0 0 0-.06.52c.057.309.31.59.598.667.362.095.632.033.872-.205.14-.136.215-.255.291-.448.055-.136.059-.16.059-.353l.001-.207-.072-.148a.894.894 0 0 0-.565-.472 1.02 1.02 0 0 0-.474.007Zm4.184 2c-.131.071-.223.25-.195.383.031.143.157.288.353.407.105.063.112.072.117.136.004.038-.01.146-.029.243-.02.094-.036.194-.036.222.002.074.07.195.143.253.064.052.076.054.255.059.164.005.198.001.264-.03.169-.082.212-.234.15-.525-.052-.243-.042-.28.087-.355.137-.08.281-.219.324-.314a.365.365 0 0 0-.175-.48.394.394 0 0 0-.181-.033c-.126 0-.207.03-.355.124l-.085.053-.053-.032c-.219-.13-.259-.145-.391-.143a.396.396 0 0 0-.193.032zm.39-2.195c-.373.036-.475.05-.654.086-.291.06-.68.195-.951.328-.94.46-1.589 1.226-1.787 2.114-.04.176-.045.234-.045.53 0 .294.005.357.043.524.264 1.16 1.332 2.017 2.714 2.173.3.033 1.596.033 1.896 0 1.11-.125 2.064-.727 2.493-1.571.114-.226.169-.372.22-.602.039-.167.044-.23.044-.523 0-.297-.005-.355-.045-.531-.288-1.29-1.539-2.304-3.072-2.497a6.873 6.873 0 0 0-.855-.031zm.645.937a3.283 3.283 0 0 1 1.44.514c.223.148.537.458.671.662.166.251.26.508.303.82.02.143.01.251-.043.482-.08.345-.332.705-.672.957a3.115 3.115 0 0 1-.689.348c-.382.122-.632.144-1.525.138-.582-.006-.686-.01-.853-.042-.57-.107-1.022-.334-1.35-.68-.264-.28-.385-.535-.45-.946-.03-.192.025-.509.137-.776.136-.326.488-.73.836-.963.403-.269.934-.46 1.422-.512.187-.02.586-.02.773-.002zm-5.503-11a1.653 1.653 0 0 0-.683.298C5.617.74 5.173 1.666 4.985 2.819c-.07.436-.119 1.04-.119 1.503 0 .544.064 1.24.155 1.721.02.107.031.202.023.208a8.12 8.12 0 0 1-.187.152 5.324 5.324 0 0 0-.949 1.02 5.49 5.49 0 0 0-.94 2.339 6.625 6.625 0 0 0-.023 1.357c.091.78.325 1.438.727 2.04l.13.195-.037.064c-.269.452-.498 1.105-.605 1.732-.084.496-.095.629-.095 1.294 0 .67.009.803.088 1.266.095.555.288 1.143.503 1.534.071.128.243.393.264.407.007.003-.014.067-.046.141a7.405 7.405 0 0 0-.548 1.873c-.062.417-.071.552-.071.991 0 .56.031.832.148 1.279L3.42 24h1.478l-.05-.091c-.297-.552-.325-1.575-.068-2.597.117-.472.25-.819.498-1.296l.148-.29v-.177c0-.165-.003-.184-.057-.293a.915.915 0 0 0-.194-.25 1.74 1.74 0 0 1-.385-.543c-.424-.92-.506-2.286-.208-3.451.124-.486.329-.918.544-1.154a.787.787 0 0 0 .223-.531c0-.195-.07-.355-.224-.522a3.136 3.136 0 0 1-.817-1.729c-.14-.96.114-2.005.69-2.834.563-.814 1.353-1.336 2.237-1.475.199-.033.57-.028.776.01.226.04.367.028.512-.041.179-.085.268-.19.374-.431.093-.215.165-.333.36-.576.234-.29.46-.489.822-.729.413-.27.884-.467 1.352-.561.17-.035.25-.04.569-.04.319 0 .398.005.569.04a4.07 4.07 0 0 1 1.914.997c.117.109.398.457.488.602.034.057.095.177.132.267.105.241.195.346.374.43.14.068.286.082.503.045.343-.058.607-.053.943.016 1.144.23 2.14 1.173 2.581 2.437.385 1.108.276 2.267-.296 3.153-.097.15-.193.27-.333.419-.301.322-.301.722-.001 1.053.493.539.801 1.866.708 3.036-.062.772-.26 1.463-.533 1.854a2.096 2.096 0 0 1-.224.258.916.916 0 0 0-.194.25c-.054.109-.057.128-.057.293v.178l.148.29c.248.476.38.823.498 1.295.253 1.008.231 2.01-.059 2.581a.845.845 0 0 0-.044.098c0 .006.329.009.732.009h.73l.02-.074.036-.134c.019-.076.057-.3.088-.516.029-.217.029-1.016 0-1.258-.11-.875-.295-1.57-.597-2.226-.032-.074-.053-.138-.046-.141.008-.005.057-.074.108-.152.376-.569.607-1.284.724-2.228.031-.26.031-1.378 0-1.628-.083-.645-.182-1.082-.348-1.525a6.083 6.083 0 0 0-.329-.7l-.038-.064.131-.194c.402-.604.636-1.262.727-2.04a6.625 6.625 0 0 0-.024-1.358 5.512 5.512 0 0 0-.939-2.339 5.325 5.325 0 0 0-.95-1.02 8.097 8.097 0 0 1-.186-.152.692.692 0 0 1 .023-.208c.208-1.087.201-2.443-.017-3.503-.19-.924-.535-1.658-.98-2.082-.354-.338-.716-.482-1.15-.455-.996.059-1.8 1.205-2.116 3.01a6.805 6.805 0 0 0-.097.726c0 .036-.007.066-.015.066a.96.96 0 0 1-.149-.078A4.857 4.857 0 0 0 12 3.03c-.832 0-1.687.243-2.456.698a.958.958 0 0 1-.148.078c-.008 0-.015-.03-.015-.066a6.71 6.71 0 0 0-.097-.725C8.997 1.392 8.337.319 7.46.048a2.096 2.096 0 0 0-.585-.041Zm.293 1.402c.248.197.523.759.682 1.388.03.113.06.244.069.292.007.047.026.152.041.233.067.365.098.76.102 1.24l.002.475-.12.175-.118.178h-.278c-.324 0-.646.041-.954.124l-.238.06c-.033.007-.038-.003-.057-.144a8.438 8.438 0 0 1 .016-2.323c.124-.788.413-1.501.696-1.711.067-.05.079-.049.157.013zm9.825-.012c.17.126.358.46.498.888.28.854.36 2.028.212 3.145-.019.14-.024.151-.057.144l-.238-.06a3.693 3.693 0 0 0-.954-.124h-.278l-.119-.178-.119-.175.002-.474c.004-.669.066-1.19.214-1.772.157-.623.434-1.185.68-1.382.078-.062.09-.063.159-.012z",
    "color": "#FFFFFF",
    "bg": "rgba(255, 255, 255, 0.15)"
  },
  "tokenrouter": {
    "path": "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
    "color": "#10B981",
    "bg": "rgba(16, 185, 129, 0.15)",
    "stroke": true
  },
  "ollama": {
    "path": "M16.361 10.26a.894.894 0 0 0-.558.47l-.072.148.001.207c0 .193.004.217.059.353.076.193.152.312.291.448.24.238.51.3.872.205a.86.86 0 0 0 .517-.436.752.752 0 0 0 .08-.498c-.064-.453-.33-.782-.724-.897a1.06 1.06 0 0 0-.466 0zm-9.203.005c-.305.096-.533.32-.65.639a1.187 1.187 0 0 0-.06.52c.057.309.31.59.598.667.362.095.632.033.872-.205.14-.136.215-.255.291-.448.055-.136.059-.16.059-.353l.001-.207-.072-.148a.894.894 0 0 0-.565-.472 1.02 1.02 0 0 0-.474.007Zm4.184 2c-.131.071-.223.25-.195.383.031.143.157.288.353.407.105.063.112.072.117.136.004.038-.01.146-.029.243-.02.094-.036.194-.036.222.002.074.07.195.143.253.064.052.076.054.255.059.164.005.198.001.264-.03.169-.082.212-.234.15-.525-.052-.243-.042-.28.087-.355.137-.08.281-.219.324-.314a.365.365 0 0 0-.175-.48.394.394 0 0 0-.181-.033c-.126 0-.207.03-.355.124l-.085.053-.053-.032c-.219-.13-.259-.145-.391-.143a.396.396 0 0 0-.193.032zm.39-2.195c-.373.036-.475.05-.654.086-.291.06-.68.195-.951.328-.94.46-1.589 1.226-1.787 2.114-.04.176-.045.234-.045.53 0 .294.005.357.043.524.264 1.16 1.332 2.017 2.714 2.173.3.033 1.596.033 1.896 0 1.11-.125 2.064-.727 2.493-1.571.114-.226.169-.372.22-.602.039-.167.044-.23.044-.523 0-.297-.005-.355-.045-.531-.288-1.29-1.539-2.304-3.072-2.497a6.873 6.873 0 0 0-.855-.031zm.645.937a3.283 3.283 0 0 1 1.44.514c.223.148.537.458.671.662.166.251.26.508.303.82.02.143.01.251-.043.482-.08.345-.332.705-.672.957a3.115 3.115 0 0 1-.689.348c-.382.122-.632.144-1.525.138-.582-.006-.686-.01-.853-.042-.57-.107-1.022-.334-1.35-.68-.264-.28-.385-.535-.45-.946-.03-.192.025-.509.137-.776.136-.326.488-.73.836-.963.403-.269.934-.46 1.422-.512.187-.02.586-.02.773-.002zm-5.503-11a1.653 1.653 0 0 0-.683.298C5.617.74 5.173 1.666 4.985 2.819c-.07.436-.119 1.04-.119 1.503 0 .544.064 1.24.155 1.721.02.107.031.202.023.208a8.12 8.12 0 0 1-.187.152 5.324 5.324 0 0 0-.949 1.02 5.49 5.49 0 0 0-.94 2.339 6.625 6.625 0 0 0-.023 1.357c.091.78.325 1.438.727 2.04l.13.195-.037.064c-.269.452-.498 1.105-.605 1.732-.084.496-.095.629-.095 1.294 0 .67.009.803.088 1.266.095.555.288 1.143.503 1.534.071.128.243.393.264.407.007.003-.014.067-.046.141a7.405 7.405 0 0 0-.548 1.873c-.062.417-.071.552-.071.991 0 .56.031.832.148 1.279L3.42 24h1.478l-.05-.091c-.297-.552-.325-1.575-.068-2.597.117-.472.25-.819.498-1.296l.148-.29v-.177c0-.165-.003-.184-.057-.293a.915.915 0 0 0-.194-.25 1.74 1.74 0 0 1-.385-.543c-.424-.92-.506-2.286-.208-3.451.124-.486.329-.918.544-1.154a.787.787 0 0 0 .223-.531c0-.195-.07-.355-.224-.522a3.136 3.136 0 0 1-.817-1.729c-.14-.96.114-2.005.69-2.834.563-.814 1.353-1.336 2.237-1.475.199-.033.57-.028.776.01.226.04.367.028.512-.041.179-.085.268-.19.374-.431.093-.215.165-.333.36-.576.234-.29.46-.489.822-.729.413-.27.884-.467 1.352-.561.17-.035.25-.04.569-.04.319 0 .398.005.569.04a4.07 4.07 0 0 1 1.914.997c.117.109.398.457.488.602.034.057.095.177.132.267.105.241.195.346.374.43.14.068.286.082.503.045.343-.058.607-.053.943.016 1.144.23 2.14 1.173 2.581 2.437.385 1.108.276 2.267-.296 3.153-.097.15-.193.27-.333.419-.301.322-.301.722-.001 1.053.493.539.801 1.866.708 3.036-.062.772-.26 1.463-.533 1.854a2.096 2.096 0 0 1-.224.258.916.916 0 0 0-.194.25c-.054.109-.057.128-.057.293v.178l.148.29c.248.476.38.823.498 1.295.253 1.008.231 2.01-.059 2.581a.845.845 0 0 0-.044.098c0 .006.329.009.732.009h.73l.02-.074.036-.134c.019-.076.057-.3.088-.516.029-.217.029-1.016 0-1.258-.11-.875-.295-1.57-.597-2.226-.032-.074-.053-.138-.046-.141.008-.005.057-.074.108-.152.376-.569.607-1.284.724-2.228.031-.26.031-1.378 0-1.628-.083-.645-.182-1.082-.348-1.525a6.083 6.083 0 0 0-.329-.7l-.038-.064.131-.194c.402-.604.636-1.262.727-2.04a6.625 6.625 0 0 0-.024-1.358 5.512 5.512 0 0 0-.939-2.339 5.325 5.325 0 0 0-.95-1.02 8.097 8.097 0 0 1-.186-.152.692.692 0 0 1 .023-.208c.208-1.087.201-2.443-.017-3.503-.19-.924-.535-1.658-.98-2.082-.354-.338-.716-.482-1.15-.455-.996.059-1.8 1.205-2.116 3.01a6.805 6.805 0 0 0-.097.726c0 .036-.007.066-.015.066a.96.96 0 0 1-.149-.078A4.857 4.857 0 0 0 12 3.03c-.832 0-1.687.243-2.456.698a.958.958 0 0 1-.148.078c-.008 0-.015-.03-.015-.066a6.71 6.71 0 0 0-.097-.725C8.997 1.392 8.337.319 7.46.048a2.096 2.096 0 0 0-.585-.041Zm.293 1.402c.248.197.523.759.682 1.388.03.113.06.244.069.292.007.047.026.152.041.233.067.365.098.76.102 1.24l.002.475-.12.175-.118.178h-.278c-.324 0-.646.041-.954.124l-.238.06c-.033.007-.038-.003-.057-.144a8.438 8.438 0 0 1 .016-2.323c.124-.788.413-1.501.696-1.711.067-.05.079-.049.157.013zm9.825-.012c.17.126.358.46.498.888.28.854.36 2.028.212 3.145-.019.14-.024.151-.057.144l-.238-.06a3.693 3.693 0 0 0-.954-.124h-.278l-.119-.178-.119-.175.002-.474c.004-.669.066-1.19.214-1.772.157-.623.434-1.185.68-1.382.078-.062.09-.063.159-.012z",
    "color": "#FFFFFF",
    "bg": "rgba(255, 255, 255, 0.15)"
  },
  "lmstudio": {
    "path": "M5.6 0A5.6 5.6 0 0 0 0 5.6v12.8A5.6 5.6 0 0 0 5.6 24h12.8a5.6 5.6 0 0 0 5.6-5.6V5.6A5.6 5.6 0 0 0 18.4 0zm0 2h12.8A3.6 3.6 0 0 1 22 5.6v12.8a3.6 3.6 0 0 1-3.6 3.6H5.6A3.6 3.6 0 0 1 2 18.4V5.6A3.6 3.6 0 0 1 5.6 2m-.4 2.8a1.2 1.2 0 0 0 0 2.4h10.4a1.2 1.2 0 0 0 0-2.4zm3.2 4a1.2 1.2 0 0 0 0 2.4h10.4a1.2 1.2 0 0 0 0-2.4zm-3.2 4a1.2 1.2 0 0 0 0 2.4h10.4a1.2 1.2 0 0 0 0-2.4zm3.2 4a1.2 1.2 0 0 0 0 2.4h10.4a1.2 1.2 0 0 0 0-2.4z",
    "color": "#FFFFFF",
    "bg": "rgba(255, 255, 255, 0.15)"
  },
  "llamacpp": {
    "path": "M6.915 4.03c-1.968 0-3.683 1.28-4.871 3.113C.704 9.208 0 11.883 0 14.449c0 .706.07 1.369.21 1.973a6.624 6.624 0 0 0 .265.86 5.297 5.297 0 0 0 .371.761c.696 1.159 1.818 1.927 3.593 1.927 1.497 0 2.633-.671 3.965-2.444.76-1.012 1.144-1.626 2.663-4.32l.756-1.339.186-.325c.061.1.121.196.183.3l2.152 3.595c.724 1.21 1.665 2.556 2.47 3.314 1.046.987 1.992 1.22 3.06 1.22 1.075 0 1.876-.355 2.455-.843a3.743 3.743 0 0 0 .81-.973c.542-.939.861-2.127.861-3.745 0-2.72-.681-5.357-2.084-7.45-1.282-1.912-2.957-2.93-4.716-2.93-1.047 0-2.088.467-3.053 1.308-.652.57-1.257 1.29-1.82 2.05-.69-.875-1.335-1.547-1.958-2.056-1.182-.966-2.315-1.303-3.454-1.303zm10.16 2.053c1.147 0 2.188.758 2.992 1.999 1.132 1.748 1.647 4.195 1.647 6.4 0 1.548-.368 2.9-1.839 2.9-.58 0-1.027-.23-1.664-1.004-.496-.601-1.343-1.878-2.832-4.358l-.617-1.028a44.908 44.908 0 0 0-1.255-1.98c.07-.109.141-.224.211-.327 1.12-1.667 2.118-2.602 3.358-2.602zm-10.201.553c1.265 0 2.058.791 2.675 1.446.307.327.737.871 1.234 1.579l-1.02 1.566c-.757 1.163-1.882 3.017-2.837 4.338-1.191 1.649-1.81 1.817-2.486 1.817-.524 0-1.038-.237-1.383-.794-.263-.426-.464-1.13-.464-2.046 0-2.221.63-4.535 1.66-6.088.454-.687.964-1.226 1.533-1.533a2.264 2.264 0 0 1 1.088-.285z",
    "color": "#0467DF",
    "bg": "rgba(4, 103, 223, 0.15)"
  }
};
  const icon = iconsData[providerId];
  const avatar = document.createElement("div");
  avatar.className = "provider-avatar";
  avatar.setAttribute("aria-hidden", "true");

  if (!icon) {
    avatar.classList.add("is-initials");
    avatar.textContent = (displayName || providerId)
      .split(/[\s_-]+/)
      .filter(Boolean)
      .map((word) => word[0])
      .join("")
      .substring(0, 2)
      .toUpperCase();
    return avatar;
  }

  // Colors flow through CSS custom properties so theme switches restyle icons
  // without re-rendering cards (which used to discard live status updates).
  if (icon.color.toUpperCase() === "#FFFFFF") {
    avatar.classList.add("is-mono");
  } else {
    avatar.style.setProperty("--brand", icon.color);
    avatar.style.setProperty("--brand-bg", icon.bg);
  }

  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", "20");
  svg.setAttribute("height", "20");
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", icon.path);
  if (icon.stroke) {
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "currentColor");
    path.setAttribute("stroke-width", "2");
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-linejoin", "round");
  } else {
    path.setAttribute("fill", "currentColor");
  }
  svg.appendChild(path);
  avatar.appendChild(svg);
  return avatar;
}

// Explicit env-key ownership per provider. Providers listed here never fall
// through to the generic prefix/attribute heuristic below, which could otherwise
// capture unrelated fields (e.g. "openai" matching other settings attributes, or
// "anthropic" matching ANTHROPIC_AUTH_TOKEN, the proxy's own server token).
const PROVIDER_FIELD_MATCHERS = {
  anthropic_api: (key) => key === "ANTHROPIC_API_KEY" || key === "ANTHROPIC_PROXY",
  openai_api: (key) => key === "OPENAI_API_KEY" || key === "OPENAI_PROXY",
  nvidia_nim: (key) => key.startsWith("NVIDIA_NIM_"),
  open_router: (key) => key.startsWith("OPENROUTER_"),
  gemini: (key) => key.startsWith("GEMINI_"),
  vertex: (key) => key.startsWith("VERTEX_"),
  deepseek: (key) => key.startsWith("DEEPSEEK_"),
  mistral: (key) => key.startsWith("MISTRAL_") && !key.startsWith("MISTRAL_CODESTRAL_"),
  mistral_codestral: (key) => key.startsWith("CODESTRAL_") || key.startsWith("MISTRAL_CODESTRAL_"),
  opencode: (key) => key === "OPENCODE_API_KEY" || key.startsWith("OPENCODE_PROXY"),
  opencode_go: (key) => key === "OPENCODE_API_KEY" || key.startsWith("OPENCODE_GO_PROXY"),
  vercel: (key) => key.startsWith("AI_GATEWAY_") || key.startsWith("VERCEL_"),
  bedrock: (key) => key.startsWith("BEDROCK_") || key === "AWS_BEARER_TOKEN_BEDROCK",
  huggingface: (key) => key.startsWith("HUGGINGFACE_"),
  cohere: (key) => key.startsWith("COHERE_"),
  github_models: (key) => key.startsWith("GITHUB_MODELS_"),
  wafer: (key) => key.startsWith("WAFER_"),
  kimi: (key) => key.startsWith("KIMI_") && !key.startsWith("KIMI_CODE_"),
  kimi_code: (key) => key.startsWith("KIMI_CODE_"),
  minimax: (key) => key.startsWith("MINIMAX_"),
  cerebras: (key) => key.startsWith("CEREBRAS_"),
  groq: (key) => key.startsWith("GROQ_"),
  sambanova: (key) => key.startsWith("SAMBANOVA_"),
  fireworks: (key) => key.startsWith("FIREWORKS_"),
  cloudflare: (key) => key.startsWith("CLOUDFLARE_"),
  zai: (key) => key.startsWith("ZAI_"),
  ollama_cloud: (key) => key === "OLLAMA_API_KEY" || key.startsWith("OLLAMA_CLOUD_"),
  tokenrouter: (key) => key.startsWith("TOKENROUTER_"),
  ollama: (key) => key.startsWith("OLLAMA_") && key !== "OLLAMA_API_KEY",
  lmstudio: (key) => key.startsWith("LMSTUDIO_") || key.startsWith("LM_STUDIO_"),
  llamacpp: (key) => key.startsWith("LLAMACPP_") || key.startsWith("LLAMA_CPP_"),
};

function getProviderFields(providerId) {
  const cleanId = providerId.toLowerCase().replace(/[^a-z0-9]/g, "_");
  const screamingId = cleanId.toUpperCase();
  const explicitMatcher = Object.prototype.hasOwnProperty.call(PROVIDER_FIELD_MATCHERS, cleanId)
    ? PROVIDER_FIELD_MATCHERS[cleanId]
    : null;

  return Array.from(state.fields.values()).filter((field) => {
    if (field.section !== "providers") return false;
    const key = field.key.toUpperCase();
    if (explicitMatcher) {
      return explicitMatcher(key);
    }
    const attr = (field.settings_attr || "").toLowerCase();
    return key.startsWith(screamingId) || attr.includes(cleanId);
  });
}

// ---------------------------------------------------------------------------
// Provider modal
// ---------------------------------------------------------------------------

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
const providerTestsInFlight = new Set();

function findProviderStatus(providerId) {
  return state.config?.provider_status?.find((p) => p.provider_id === providerId) || null;
}

function isModalOpen() {
  return currentProviderId !== null;
}

function modalContainer() {
  return document.querySelector("#providerModal .modal-container");
}

function setModalMessage(message, kind = "") {
  const area = byId("modalMessage");
  area.textContent = message;
  area.className = `modal-message ${kind}`.trim();
}

function syncModalTestButton() {
  const button = byId("modalTestBtn");
  const provider = currentProviderId ? findProviderStatus(currentProviderId) : null;
  const busy = currentProviderId !== null && providerTestsInFlight.has(currentProviderId);
  button.disabled = busy;
  if (busy) {
    button.setAttribute("aria-busy", "true");
    button.textContent = "Testing...";
  } else {
    button.removeAttribute("aria-busy");
    button.textContent = provider?.kind === "local" ? "Test" : "Refresh models";
  }
}

function renderModalMeta(providerId, provider) {
  const meta = byId("modalProviderMeta");
  meta.replaceChildren();
  const card = findProviderCard(providerId);
  const pill = card?.querySelector(".status-pill");
  if (pill?.textContent) {
    meta.appendChild(pill.cloneNode(true));
  }
  const kindTag = document.createElement("span");
  kindTag.className = "kind-tag";
  kindTag.textContent = provider.kind === "local" ? "Local" : "Cloud";
  meta.appendChild(kindTag);
}

function setModalAdvanced(showing) {
  const fieldsContainer = byId("modalProviderFields");
  const toggle = byId("modalAdvancedToggle");
  fieldsContainer.classList.toggle("show-advanced", showing);
  toggle.textContent = showing ? "Hide advanced" : "Show advanced";
  toggle.setAttribute("aria-expanded", String(showing));
}

function openProviderModal(providerId, returnFocusTo = null) {
  const provider = findProviderStatus(providerId);
  if (!provider) return;
  if (isModalOpen()) {
    closeProviderModal({ restoreFocus: false });
  }

  currentProviderId = providerId;
  modalReturnFocus = returnFocusTo || document.activeElement;
  const name = provider.display_name || providerId;

  byId("modalProviderTitle").textContent = name;
  byId("modalProviderIcon").replaceChildren(getProviderIcon(providerId, provider.display_name));
  renderModalMeta(providerId, provider);

  const pFields = getProviderFields(providerId);
  const credField = pFields.find(
    (f) =>
      f.key.includes("API_KEY") ||
      f.key.includes("TOKEN") ||
      f.key.includes("SECRET") ||
      f.key.includes("PROJECT_ID"),
  );
  renderRichText(
    byId("modalProviderDesc"),
    credField?.description || `Configure settings and endpoints for ${name}.`,
  );

  const fieldsContainer = byId("modalProviderFields");
  fieldsContainer.replaceChildren();
  pFields.forEach((field) => {
    const fieldEl = document.querySelector(
      `#hiddenFieldsContainer .field[data-key="${CSS.escape(field.key)}"]`,
    );
    if (fieldEl) {
      fieldsContainer.appendChild(fieldEl);
    }
  });

  const advancedToggle = byId("modalAdvancedToggle");
  advancedToggle.hidden = !fieldsContainer.querySelector(".advanced-field");
  setModalAdvanced(false);
  setModalMessage(
    fieldsContainer.children.length ? "" : `${name} has no editable settings here.`,
  );
  syncModalTestButton();

  byId("providerModal").classList.add("active");
  document.querySelector(".app-shell").inert = true;
  document.body.classList.add("modal-open");

  const firstInput = fieldsContainer.querySelector(
    "input:not([disabled]), select:not([disabled]), textarea:not([disabled])",
  );
  (firstInput || byId("closeModalBtn")).focus({ preventScroll: true });
}

function closeProviderModal({ restoreFocus = true } = {}) {
  if (!isModalOpen()) return;
  const fieldsContainer = byId("modalProviderFields");
  const hiddenContainer = byId("hiddenFieldsContainer");

  state.modelComboboxes.forEach((combobox) => combobox.close());
  Array.from(fieldsContainer.children).forEach((fieldEl) => {
    hiddenContainer.appendChild(fieldEl);
  });

  byId("providerModal").classList.remove("active");
  document.querySelector(".app-shell").inert = false;
  document.body.classList.remove("modal-open");
  currentProviderId = null;
  setModalMessage("");

  const returnTo = modalReturnFocus;
  modalReturnFocus = null;
  if (restoreFocus && returnTo?.isConnected) {
    returnTo.focus({ preventScroll: true });
  }
}

function trapModalFocus(event) {
  const container = modalContainer();
  const focusables = Array.from(container.querySelectorAll(FOCUSABLE_SELECTOR)).filter(
    (el) => el.getClientRects().length > 0,
  );
  if (focusables.length === 0) {
    event.preventDefault();
    container.focus();
    return;
  }
  const first = focusables[0];
  const last = focusables[focusables.length - 1];
  const active = document.activeElement;
  if (event.shiftKey && (active === first || !container.contains(active))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (active === last || !container.contains(active))) {
    event.preventDefault();
    first.focus();
  }
}

async function testProviderInModal(providerId) {
  const name = providerDisplayName(providerId);
  providerTestsInFlight.add(providerId);
  syncModalTestButton();
  setModalMessage("");
  let message = "";
  let kind = "";
  try {
    const result = await api(`/admin/api/providers/${encodeURIComponent(providerId)}/test`, {
      method: "POST",
      body: "{}",
    });
    if (result.ok) {
      const models = result.models || [];
      updateProviderCard(
        providerId,
        "reachable",
        `${models.length} models`,
        models.slice(0, 3).join(", ") || "No models returned",
      );
      message = `Success: Connected to ${name}. Found ${models.length} models.`;
      kind = "ok";
      await loadModelOptions(true);
    } else {
      updateProviderCard(providerId, "offline", result.error_type, result.error_type);
      message = `Connection failed: ${result.error_type || "unknown error"}`;
      kind = "error";
    }
  } catch (err) {
    message = `Error: ${err.message}`;
    kind = "error";
  } finally {
    providerTestsInFlight.delete(providerId);
  }

  showMessage(message, kind);
  // The user may have closed the modal or opened another provider meanwhile.
  if (currentProviderId === providerId) {
    setModalMessage(message, kind);
    renderModalMeta(providerId, findProviderStatus(providerId));
    syncModalTestButton();
  }
}

async function saveProviderModal() {
  if (state.busy || state.restarting) return;
  await runAction(async () => {
    try {
      const check = await validate(false);
      if (!check.valid) {
        setModalMessage(validationErrorText(check), "error");
        return;
      }
    } catch (error) {
      setModalMessage(`Could not validate: ${error.message}`, "error");
      return;
    }
    // Fields must return to the hidden container before apply() reloads and
    // re-renders them; otherwise stale nodes would be duplicated on close.
    closeProviderModal();
    await apply();
  });
}

// ---------------------------------------------------------------------------
// Event bindings
// ---------------------------------------------------------------------------

byId("validateButton").addEventListener("click", () => runAction(() => validate(true)));
byId("applyButton").addEventListener("click", () => runAction(apply));

document.addEventListener("pointerdown", (event) => {
  state.modelComboboxes.forEach((combobox) => {
    if (combobox.isOpen && !combobox.element.contains(event.target)) combobox.close();
  });
});

byId("providerSearch").addEventListener("input", (event) => {
  state.providerFilter.query = event.target.value;
  applyProviderFilter();
});
byId("providerConfiguredOnly").addEventListener("change", (event) => {
  state.providerFilter.configuredOnly = event.target.checked;
  applyProviderFilter();
});

byId("refreshLogsButton").addEventListener("click", () => loadLogs());
byId("logSearchInput").addEventListener("input", (event) => {
  logs.query = event.target.value;
  renderLogs();
});
byId("clearLogsBtn").addEventListener("click", () => {
  const last = logs.entries[logs.entries.length - 1];
  logs.clearMarker = last === undefined ? null : logEntryKey(last);
  renderLogs();
});
byId("autoScrollLogs").addEventListener("change", (event) => {
  if (event.target.checked) {
    const container = byId("logsContainer");
    container.scrollTop = container.scrollHeight;
  }
});
document.querySelectorAll(".log-level-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".log-level-btn").forEach((other) => {
      const selected = other === btn;
      other.classList.toggle("active", selected);
      other.setAttribute("aria-pressed", String(selected));
    });
    logs.levelFilter = btn.dataset.level;
    renderLogs();
  });
});

// Pause log polling while the tab is hidden; resume when it becomes visible.
document.addEventListener("visibilitychange", () => {
  if (state.activeView !== "logs") return;
  if (document.hidden) {
    stopLogsInterval();
  } else {
    loadLogs();
    startLogsInterval();
  }
});

byId("modalTestBtn").addEventListener("click", () => {
  if (currentProviderId !== null) testProviderInModal(currentProviderId);
});
byId("closeModalBtn").addEventListener("click", () => closeProviderModal());
byId("modalCancelBtn").addEventListener("click", () => closeProviderModal());
byId("modalSaveBtn").addEventListener("click", saveProviderModal);
byId("modalAdvancedToggle").addEventListener("click", () => {
  setModalAdvanced(!byId("modalProviderFields").classList.contains("show-advanced"));
});

// Only close on a click that both starts and ends on the backdrop, so a text
// selection drag that ends outside the dialog does not discard the modal.
byId("providerModal").addEventListener("pointerdown", (event) => {
  backdropPointerDown = event.target === event.currentTarget;
});
byId("providerModal").addEventListener("click", (event) => {
  if (backdropPointerDown && event.target === event.currentTarget) {
    closeProviderModal();
  }
  backdropPointerDown = false;
});

document.addEventListener("keydown", (event) => {
  if (isModalOpen()) {
    // Comboboxes call preventDefault() when Escape closes their listbox.
    if (event.key === "Escape" && !event.defaultPrevented) {
      event.preventDefault();
      closeProviderModal();
    } else if (event.key === "Tab") {
      trapModalFocus(event);
    }
    return;
  }

  if (event.key === "/" && !event.metaKey && !event.ctrlKey && !event.altKey) {
    if (event.target.closest?.("input, textarea, select, [contenteditable='true']")) return;
    const searchId =
      state.activeView === "providers"
        ? "providerSearch"
        : state.activeView === "logs"
          ? "logSearchInput"
          : null;
    if (searchId) {
      event.preventDefault();
      byId(searchId).focus();
    }
  }
});

initTheme();
load().catch((error) => {
  showMessage(error.message, "error");
});

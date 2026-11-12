/**
 * JARVIS — Settings Panel
 *
 * Overlay panel for API keys, connection status, preferences, and system info.
 * Slides in from the right with glass-morphism styling.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface StatusResponse {
  claude_code_installed: boolean;
  server_port: number;
  uptime_seconds: number;
  env_keys_set: {
    fish_audio: boolean;
    fish_voice_id: boolean;
    user_name: string;
  };
  voice: {
    engine: string; // what is speaking now (read at server boot)
    macos_voice: string;
    configured_engine: string; // what .env says — takes effect on restart
    configured_macos_voice: string;
  };
}

interface VoiceInfo {
  name: string;
  lang: string;
}

interface PreferencesResponse {
  user_name: string;
  honorific: string;
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let panelEl: HTMLElement | null = null;
let isOpen = false;
let isFirstTimeSetup = false;
let setupStep = 0; // 0=voice, 1=name, 2=done
let voicesLoaded = false;

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function apiGet<T>(url: string): Promise<T> {
  const res = await fetch(url);
  return res.json();
}

async function apiPost<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

// ---------------------------------------------------------------------------
// Panel HTML
// ---------------------------------------------------------------------------

function buildPanelHTML(): string {
  return `
    <div class="settings-backdrop" id="settings-backdrop"></div>
    <div class="settings-panel" id="settings-panel-inner">
      <div class="settings-header">
        <h2>Settings</h2>
        <button class="settings-close" id="settings-close">&times;</button>
      </div>

      <div class="settings-welcome" id="settings-welcome" style="display:none">
        <p>Welcome to JARVIS. Let's get you set up.</p>
      </div>

      <div class="settings-body">

        <!-- Voice -->
        <section class="settings-section" id="section-voice">
          <h3>Voice</h3>

          <div class="settings-field">
            <label>Engine</label>
            <select id="input-tts-engine">
              <option value="macos">macOS built-in voice (no key needed)</option>
              <option value="fish">Fish Audio (API key)</option>
            </select>
          </div>

          <div class="settings-field" id="field-macos-voice">
            <label>macOS Voice</label>
            <select id="input-macos-voice">
              <option value="">System default</option>
            </select>
            <p class="settings-hint">More voices: System Settings &rarr; Accessibility &rarr; Spoken Content &rarr; System Voice &rarr; Manage Voices.</p>
          </div>

          <div class="settings-actions">
            <button class="settings-btn primary" id="btn-save-voice">Save Voice</button>
          </div>
          <p class="settings-hint" id="voice-live"></p>
          <p class="settings-restart-notice" id="voice-restart-notice" style="display:none">
            Saved. Restart the server (menu &rarr; Restart Server) for this to take effect.
          </p>
        </section>

        <!-- API Keys (Fish Audio only) -->
        <section class="settings-section" id="section-api-keys">
          <h3>Fish Audio</h3>

          <div class="settings-field">
            <label>Fish Audio API Key</label>
            <div class="settings-input-row">
              <input type="password" id="input-fish-key" placeholder="Fish Audio key..." />
              <button class="settings-btn" id="btn-test-fish">Test</button>
              <span class="status-dot" id="status-fish"></span>
            </div>
          </div>

          <div class="settings-field">
            <label>Fish Voice ID</label>
            <div class="settings-input-row">
              <input type="text" id="input-fish-voice-id" placeholder="612b878b113047d9a770c069c8b4fdfe" />
              <button class="settings-btn" id="btn-save-voice-id">Save</button>
            </div>
          </div>

          <div class="settings-actions">
            <button class="settings-btn primary" id="btn-save-keys">Save Keys</button>
          </div>
          <p class="settings-restart-notice" id="keys-restart-notice" style="display:none">
            Saved. Restart the server (menu &rarr; Restart Server) for this to take effect.
          </p>
        </section>

        <!-- Connection Status -->
        <section class="settings-section" id="section-status">
          <h3>Connection Status</h3>
          <div class="status-grid">
            <div class="status-row"><span class="status-dot" id="status-claude-cli"></span><span>Claude Code CLI</span></div>
            <div class="status-row"><span class="status-dot" id="status-server"></span><span>Server</span><span class="status-detail" id="status-server-detail"></span></div>
          </div>
        </section>

        <!-- User Preferences -->
        <section class="settings-section" id="section-preferences">
          <h3>User Preferences</h3>

          <div class="settings-field">
            <label>Your Name</label>
            <input type="text" id="input-user-name" placeholder="Your name" />
          </div>

          <div class="settings-field">
            <label>Honorific</label>
            <select id="input-honorific">
              <option value="sir">Sir</option>
              <option value="ma'am">Ma'am</option>
              <option value="none">None</option>
            </select>
          </div>

          <div class="settings-actions">
            <button class="settings-btn primary" id="btn-save-prefs">Save Preferences</button>
          </div>
        </section>

        <!-- System Info -->
        <section class="settings-section" id="section-sysinfo">
          <h3>System Info</h3>
          <div class="sysinfo-grid">
            <div class="sysinfo-row"><span class="sysinfo-label">Server port</span><span id="sysinfo-port">--</span></div>
            <div class="sysinfo-row"><span class="sysinfo-label">Uptime</span><span id="sysinfo-uptime">--</span></div>
          </div>
        </section>

        <!-- Setup Navigation (first-time only) -->
        <div class="setup-nav" id="setup-nav" style="display:none">
          <button class="settings-btn primary" id="btn-setup-next">Next</button>
        </div>

      </div>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Panel lifecycle
// ---------------------------------------------------------------------------

function createPanel(): HTMLElement {
  const container = document.createElement("div");
  container.id = "settings-container";
  container.innerHTML = buildPanelHTML();
  document.body.appendChild(container);
  return container;
}

function setDotStatus(id: string, status: "green" | "red" | "yellow" | "off") {
  const dot = document.getElementById(id);
  if (!dot) return;
  dot.className = "status-dot";
  if (status !== "off") dot.classList.add(`status-${status}`);
}

function selectedEngine(): string {
  const el = document.getElementById("input-tts-engine") as HTMLSelectElement | null;
  return el?.value || "macos";
}

/** The Fish fields only matter when Fish is the engine; the voice picker
 *  only when the macOS voice is. */
function applyEngineVisibility() {
  const fish = selectedEngine() === "fish";
  const keys = document.getElementById("section-api-keys");
  if (keys) keys.style.display = fish ? "" : "none";
  const picker = document.getElementById("field-macos-voice");
  if (picker) picker.style.display = fish ? "none" : "";
}

function voiceLabel(engine: string, voice: string): string {
  if (engine === "fish") return "Fish Audio";
  return `macOS — ${voice || "system default"}`;
}

/** Fill the voice dropdown from the voices installed on this Mac. Voice
 *  names come from the system, so options are built with textContent,
 *  never markup. English voices first, then the rest, each in `say`'s order. */
async function loadVoices(selected: string) {
  const sel = document.getElementById("input-macos-voice") as HTMLSelectElement | null;
  if (!sel) return;
  if (!voicesLoaded) {
    try {
      const { voices } = await apiGet<{ voices: VoiceInfo[] }>("/api/settings/voices");
      const english = voices.filter((v) => v.lang.startsWith("en"));
      const other = voices.filter((v) => !v.lang.startsWith("en"));
      for (const v of [...english, ...other]) {
        const opt = document.createElement("option");
        opt.value = v.name;
        opt.textContent = `${v.name} (${v.lang})`;
        sel.appendChild(opt);
      }
      voicesLoaded = true;
    } catch (e) {
      console.error("[settings] failed to load voices:", e);
    }
  }
  // A configured voice that is not installed is still shown, and named so.
  if (selected && !Array.from(sel.options).some((o) => o.value === selected)) {
    const opt = document.createElement("option");
    opt.value = selected;
    opt.textContent = `${selected} (not installed)`;
    sel.appendChild(opt);
  }
  sel.value = selected;
}

function needsSetup(status: StatusResponse): boolean {
  return status.voice.configured_engine === "fish" && !status.env_keys_set.fish_audio;
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

async function loadStatus() {
  try {
    const status = await apiGet<StatusResponse>("/api/settings/status");

    setDotStatus("status-claude-cli", status.claude_code_installed ? "green" : "red");
    setDotStatus("status-server", "green");

    const serverDetail = document.getElementById("status-server-detail");
    if (serverDetail) serverDetail.textContent = `port ${status.server_port} | up ${formatUptime(status.uptime_seconds)}`;

    // API key status dots
    setDotStatus("status-fish", status.env_keys_set.fish_audio ? "green" : "red");

    // Voice: the dropdowns show what .env says; the line under them, what
    // is speaking now. They differ between a save and a restart.
    const engineEl = document.getElementById("input-tts-engine") as HTMLSelectElement | null;
    if (engineEl) engineEl.value = status.voice.configured_engine;
    await loadVoices(status.voice.configured_macos_voice);
    applyEngineVisibility();
    const live = document.getElementById("voice-live");
    if (live) live.textContent = `Speaking now: ${voiceLabel(status.voice.engine, status.voice.macos_voice)}`;

    // System info
    const portEl = document.getElementById("sysinfo-port");
    if (portEl) portEl.textContent = String(status.server_port);
    const upEl = document.getElementById("sysinfo-uptime");
    if (upEl) upEl.textContent = formatUptime(status.uptime_seconds);

    return status;
  } catch (e) {
    console.error("[settings] failed to load status:", e);
    // EVERY dot, not just the server's. The CLI and Fish dots are drawn from
    // fields of the answer that never arrived, so leaving them green states
    // as fact something this call failed to find out. "off" is the absence
    // of a reading, which is what we have.
    setDotStatus("status-server", "red");
    setDotStatus("status-claude-cli", "off");
    setDotStatus("status-fish", "off");
    const serverDetail = document.getElementById("status-server-detail");
    if (serverDetail) serverDetail.textContent = "no answer from the server";
    for (const id of ["sysinfo-port", "sysinfo-uptime"]) {
      const node = document.getElementById(id);
      if (node) node.textContent = "—";
    }
    return null;
  }
}

async function loadPreferences() {
  try {
    const prefs = await apiGet<PreferencesResponse>("/api/settings/preferences");
    const nameEl = document.getElementById("input-user-name") as HTMLInputElement;
    const honEl = document.getElementById("input-honorific") as HTMLSelectElement;
    if (nameEl) nameEl.value = prefs.user_name || "";
    if (honEl) honEl.value = prefs.honorific || "sir";
  } catch (e) {
    console.error("[settings] failed to load preferences:", e);
  }
}

function wireEvents() {
  // Close
  document.getElementById("settings-close")?.addEventListener("click", closeSettings);
  document.getElementById("settings-backdrop")?.addEventListener("click", closeSettings);

  // Voice
  document.getElementById("input-tts-engine")?.addEventListener("change", applyEngineVisibility);
  document.getElementById("btn-save-voice")?.addEventListener("click", async () => {
    const engine = selectedEngine();
    const voice = (document.getElementById("input-macos-voice") as HTMLSelectElement).value;
    const notice = document.getElementById("voice-restart-notice");
    const results = await Promise.all([
      apiPost<{ success: boolean; error?: string }>("/api/settings/keys", { key_name: "JARVIS_TTS_ENGINE", key_value: engine }),
      apiPost<{ success: boolean; error?: string }>("/api/settings/keys", { key_name: "JARVIS_VOICE", key_value: voice }),
    ]);
    const failed = results.find((r) => !r.success);
    if (notice) {
      notice.textContent = failed
        ? `Not saved: ${failed.error ?? "unknown error"}`
        : "Saved. Restart the server (menu \u2192 Restart Server) for this to take effect.";
      notice.style.display = "block";
    }
    await loadStatus();
  });

  // Save keys
  document.getElementById("btn-save-keys")?.addEventListener("click", async () => {
    const fishKey = (document.getElementById("input-fish-key") as HTMLInputElement).value.trim();

    let savedAny = false;
    if (fishKey) {
      await apiPost("/api/settings/keys", { key_name: "FISH_API_KEY", key_value: fishKey });
      savedAny = true;
    }
    await loadStatus();

    const notice = document.getElementById("keys-restart-notice");
    if (notice) notice.style.display = savedAny ? "block" : "none";
  });

  // Save voice ID
  document.getElementById("btn-save-voice-id")?.addEventListener("click", async () => {
    const voiceId = (document.getElementById("input-fish-voice-id") as HTMLInputElement).value.trim();
    if (voiceId) {
      await apiPost("/api/settings/keys", { key_name: "FISH_VOICE_ID", key_value: voiceId });
    }
  });

  // Test Fish
  document.getElementById("btn-test-fish")?.addEventListener("click", async () => {
    setDotStatus("status-fish", "yellow");
    const key = (document.getElementById("input-fish-key") as HTMLInputElement).value.trim();
    try {
      const result = await apiPost<{ valid: boolean; error?: string }>("/api/settings/test-fish", { key_value: key || undefined });
      setDotStatus("status-fish", result.valid ? "green" : "red");
    } catch {
      setDotStatus("status-fish", "red");
    }
  });

  // Save preferences
  document.getElementById("btn-save-prefs")?.addEventListener("click", async () => {
    const user_name = (document.getElementById("input-user-name") as HTMLInputElement).value.trim();
    const honorific = (document.getElementById("input-honorific") as HTMLSelectElement).value;
    await apiPost("/api/settings/preferences", { user_name, honorific });
    await loadStatus();
  });

  // Setup next button
  document.getElementById("btn-setup-next")?.addEventListener("click", advanceSetup);
}

// ---------------------------------------------------------------------------
// First-time setup wizard
// ---------------------------------------------------------------------------

function enterSetupMode() {
  isFirstTimeSetup = true;
  setupStep = 0;

  const welcome = document.getElementById("settings-welcome");
  if (welcome) welcome.style.display = "block";

  const nav = document.getElementById("setup-nav");
  if (nav) nav.style.display = "flex";

  // Hide sections except API keys
  showSetupStep(0);
}

function showSetupStep(step: number) {
  // Step 0 is the voice: the engine picker, plus the Fish key fields when
  // Fish is chosen. Step 1 is the user's name.
  const steps: Record<string, number> = {
    "section-voice": 0, "section-api-keys": 0,
    "section-status": -1, "section-sysinfo": -1, "section-preferences": 1,
  };
  for (const [id, s] of Object.entries(steps)) {
    const el = document.getElementById(id);
    if (el) el.style.display = s === step ? "" : "none";
  }
  if (step === 0) applyEngineVisibility();

  const nextBtn = document.getElementById("btn-setup-next");
  if (nextBtn) {
    if (step === 0) nextBtn.textContent = "Next: Set Your Name";
    else if (step === 1) nextBtn.textContent = "Finish Setup";
    else nextBtn.style.display = "none";
  }
}

async function advanceSetup() {
  setupStep++;
  if (setupStep >= 2) {
    // Done — save everything and close
    isFirstTimeSetup = false;
    const welcome = document.getElementById("settings-welcome");
    if (welcome) welcome.style.display = "none";
    const nav = document.getElementById("setup-nav");
    if (nav) nav.style.display = "none";

    // Show all sections
    ["section-voice", "section-status", "section-preferences", "section-sysinfo"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.style.display = "";
    });
    applyEngineVisibility();

    closeSettings();
    return;
  }
  showSetupStep(setupStep);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export async function openSettings() {
  if (isOpen) return;
  isOpen = true;

  if (!panelEl) {
    panelEl = createPanel();
    wireEvents();
  }

  panelEl.style.display = "block";

  // Trigger animation
  requestAnimationFrame(() => {
    panelEl!.classList.add("open");
  });

  // Load data
  const status = await loadStatus();
  await loadPreferences();

  // Check for first-time setup
  if (status && needsSetup(status)) {
    enterSetupMode();
  }
}

export function closeSettings() {
  if (!panelEl || !isOpen) return;
  isOpen = false;
  panelEl.classList.remove("open");
  setTimeout(() => {
    if (panelEl) panelEl.style.display = "none";
  }, 300);
}

export function isSettingsOpen(): boolean {
  return isOpen;
}

/**
 * Check if first-time setup is needed and auto-open.
 */
export async function checkFirstTimeSetup(): Promise<boolean> {
  try {
    const status = await apiGet<StatusResponse>("/api/settings/status");
    if (needsSetup(status)) {
      openSettings();
      return true;
    }
  } catch {
    // Server not ready yet, skip
  }
  return false;
}

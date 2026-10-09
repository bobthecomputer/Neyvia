use std::{
    collections::{HashMap, HashSet, VecDeque},
    ffi::OsString,
    fs::{self, File, OpenOptions},
    io::{BufRead, BufReader, Read, Write},
    net::{TcpListener as StdTcpListener, TcpStream as StdTcpStream},
    path::{Path, PathBuf},
    process::Stdio,
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex, OnceLock,
    },
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use active_win_pos_rs::get_active_window;
use arboard::Clipboard;
use axum::{
    extract::State as AxumState,
    http::{header::AUTHORIZATION, HeaderMap, StatusCode},
    routing::{get, post},
    Json, Router,
};
use chrono::{Local, Timelike, Utc};
use futures_util::{SinkExt, StreamExt};
use memory_stats::memory_stats;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::TrayIconBuilder,
    AppHandle, Emitter, Manager, PhysicalPosition, Position,
};
use tauri_plugin_global_shortcut::{
    Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutEvent, ShortcutState,
};
use tokio::{
    io::{AsyncBufReadExt, AsyncRead, AsyncReadExt, AsyncWriteExt, BufReader as TokioBufReader},
    net::TcpListener,
    process::{
        Child as TokioChild, ChildStdin as TokioChildStdin, ChildStdout as TokioChildStdout,
        Command as TokioCommand,
    },
    sync::{mpsc, Mutex as AsyncMutex},
    time::{sleep, timeout},
};
use tokio_tungstenite::{connect_async, tungstenite::Message};
use uuid::Uuid;

mod runtime_env;
mod base_pack;
mod base_pack_bridge;
mod browser_runtime;

const MAIN_WINDOW_LABEL: &str = "main";
const SETTINGS_FILE_NAME: &str = "overlay_settings.json";
const AUDIT_LOG_FILE_NAME: &str = "audit.log.jsonl";
const DESKTOP_SERVICE_WORKER_CLEANUP_SCRIPT: &str = r#"
(() => {
  if (!("serviceWorker" in navigator)) return;
  navigator.serviceWorker.getRegistrations().then(async registrations => {
    if (!registrations.length) return;
    await Promise.all(registrations.map(registration => registration.unregister()));
    if ("caches" in window) {
      const keys = await caches.keys();
      await Promise.all(keys.filter(key => key.startsWith("fluxio-pwa-")).map(key => caches.delete(key)));
    }
    window.location.reload();
  }).catch(() => undefined);
})();
"#;

const TRAY_OPEN_ID: &str = "tray_open_overlay";
const TRAY_TOGGLE_PIN_ID: &str = "tray_toggle_pin";
const TRAY_PERF_ID: &str = "tray_perf_snapshot";
const TRAY_NIGHT_MODE_ID: &str = "tray_night_mode_now";
const TRAY_QUIT_ID: &str = "tray_quit";

const DEFAULT_LOCALHOST_PORT: u16 = 47635;
const NIGHT_MODE_LOOP_SECONDS: u64 = 15 * 60;
const OPENCLAW_KEYRING_SERVICE: &str = "vibe-coding-platform";
const OPENCLAW_KEYRING_USER: &str = "openclaw-gateway-token";
const LOCALHOST_API_KEYRING_USER: &str = "localhost-api-token";
const PROVIDER_KEYRING_USER_PREFIX: &str = "provider-secret:";
const OPENAI_CODEX_OAUTH_KEYRING_USER: &str = "openai-codex-oauth";
const OPENAI_CODEX_OAUTH_CLIENT_ID: &str = "app_EMoamEEZ73f0CkXaXp7hrann";
const OPENAI_CODEX_OAUTH_ISSUER: &str = "https://auth.openai.com";
const OPENAI_CODEX_OAUTH_PORT: u16 = 1455;
const OPENAI_CODEX_OAUTH_SCOPE: &str =
    "openid profile email offline_access api.connectors.read api.connectors.invoke";
const MINIMAX_OPENCLAW_PROVIDER_ID: &str = "minimax-portal";
const MINIMAX_OPENCLAW_CREDENTIALS_RELATIVE_PATH: &str = ".minimax/oauth_creds.json";
const TELEGRAM_BOT_KEYRING_USER: &str = "telegram-phone-bot-token";
const AGENT_PROVIDER_ENV_MAPPINGS: [(&str, &[&str]); 4] = [
    ("OPENAI_API_KEY", &["openai", "openai-codex"]),
    ("ANTHROPIC_API_KEY", &["anthropic"]),
    ("OPENROUTER_API_KEY", &["openrouter"]),
    ("MINIMAX_API_KEY", &["minimax", "minimax-cn"]),
];
const CONTROL_ROOM_PROVIDER_IDS: [&str; 6] = [
    "openai",
    "openai-codex",
    "anthropic",
    "openrouter",
    "minimax",
    "minimax-portal",
];
const OPENCLAW_MAX_PENDING_OUTBOUND: usize = 256;
const OPENCLAW_MAX_RECENT_EVENT_IDS: usize = 512;
const OPENCLAW_MAX_PENDING_ACKS: usize = 512;
const CONTROL_ROOM_EVENT_NAME: &str = "control-room://changed";
const CONTROL_ROOM_DELTA_EVENT_NAME: &str = "control-room://delta";
const CONTROL_ROOM_WATCH_INTERVAL_MS: u64 = 250;
const CONTROL_ROOM_WATCH_MAX_SESSIONS: usize = 8;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;
const CODEX_IMPORT_CACHE_TTL_SECONDS: u64 = 20;
const CODEX_SESSION_META_LIMIT: usize = 48;
const CODEX_SESSION_SCAN_FILE_LIMIT: usize = 160;
static CODEX_IMPORT_CACHE: OnceLock<Mutex<Option<(Instant, CodexImportSnapshot)>>> =
    OnceLock::new();

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(default, rename_all = "camelCase")]
struct OverlaySettings {
    pinned: bool,
    hotkey: String,
    mode_id: String,
    localhost_api_enabled: bool,
    localhost_api_port: u16,
}

impl Default for OverlaySettings {
    fn default() -> Self {
        Self {
            pinned: true,
            hotkey: "Ctrl+Shift+Space".to_string(),
            mode_id: "coding".to_string(),
            localhost_api_enabled: true,
            localhost_api_port: DEFAULT_LOCALHOST_PORT,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct PerformanceSnapshot {
    cold_start_ms: Option<u64>,
    last_hotkey_latency_ms: Option<u64>,
    average_hotkey_latency_ms: Option<f64>,
    hotkey_samples: u64,
    idle_ram_mb: Option<f64>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct OverlayStateSnapshot {
    settings: OverlaySettings,
    performance: PerformanceSnapshot,
    current_mode: Option<ModeDefinition>,
    openclaw_status: OpenClawStatus,
    localhost_status: LocalhostStatus,
    night_mode: NightModeConfig,
}

struct PerformanceState {
    startup_instant: Instant,
    cold_start_ms: Option<u64>,
    pending_hotkey_open_started_at: Option<Instant>,
    last_hotkey_latency_ms: Option<u64>,
    hotkey_latency_total_ms: u128,
    hotkey_samples: u64,
    idle_ram_mb: Option<f64>,
}

impl PerformanceState {
    fn new() -> Self {
        Self {
            startup_instant: Instant::now(),
            cold_start_ms: None,
            pending_hotkey_open_started_at: None,
            last_hotkey_latency_ms: None,
            hotkey_latency_total_ms: 0,
            hotkey_samples: 0,
            idle_ram_mb: None,
        }
    }

    fn mark_cold_start(&mut self) {
        if self.cold_start_ms.is_none() {
            self.cold_start_ms = Some(self.startup_instant.elapsed().as_millis() as u64);
        }
    }

    fn begin_hotkey_open(&mut self) {
        self.pending_hotkey_open_started_at = Some(Instant::now());
    }

    fn finish_hotkey_open(&mut self) {
        let Some(started_at) = self.pending_hotkey_open_started_at.take() else {
            return;
        };

        let elapsed_ms = started_at.elapsed().as_millis() as u64;
        self.last_hotkey_latency_ms = Some(elapsed_ms);
        self.hotkey_samples += 1;
        self.hotkey_latency_total_ms += elapsed_ms as u128;
    }

    fn sample_idle_memory(&mut self) {
        self.idle_ram_mb = sample_process_memory_mb();
    }

    fn snapshot(&self) -> PerformanceSnapshot {
        let average = if self.hotkey_samples == 0 {
            None
        } else {
            Some(self.hotkey_latency_total_ms as f64 / self.hotkey_samples as f64)
        };

        PerformanceSnapshot {
            cold_start_ms: self.cold_start_ms,
            last_hotkey_latency_ms: self.last_hotkey_latency_ms,
            average_hotkey_latency_ms: average,
            hotkey_samples: self.hotkey_samples,
            idle_ram_mb: self.idle_ram_mb,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ContextCaptureRequest {
    clipboard: bool,
    active_window: bool,
    screenshot: bool,
}

impl Default for ContextCaptureRequest {
    fn default() -> Self {
        Self {
            clipboard: false,
            active_window: false,
            screenshot: false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ActiveWindowMetadata {
    title: String,
    app_name: String,
    process_id: u64,
    process_path: String,
    window_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ContextCaptureResult {
    captured_at: String,
    clipboard_text: Option<String>,
    active_window: Option<ActiveWindowMetadata>,
    screenshot_path: Option<String>,
    warnings: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ModeDefinition {
    id: String,
    label: String,
    description: String,
    context_recipe: ContextCaptureRequest,
    allowed_tools: Vec<String>,
}

struct ModeState {
    current_mode_id: String,
    modes: HashMap<String, ModeDefinition>,
}

impl ModeState {
    fn new(default_mode: &str) -> Self {
        let modes = default_modes();
        let current_mode_id = if modes.contains_key(default_mode) {
            default_mode.to_string()
        } else {
            "coding".to_string()
        };

        Self {
            current_mode_id,
            modes,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct QuestionChoice {
    choice_id: String,
    label: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum QuestionStatus {
    Pending,
    Answered,
    Dismissed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct QuestionBubble {
    question_id: String,
    question: String,
    choices: Vec<QuestionChoice>,
    status: QuestionStatus,
    selected_choice_id: Option<String>,
    custom_answer: Option<String>,
    source: String,
    created_at: String,
    answered_at: Option<String>,
    approval_id: Option<String>,
}

struct QuestionState {
    pending: HashMap<String, QuestionBubble>,
    history: Vec<QuestionBubble>,
}

impl QuestionState {
    fn new() -> Self {
        Self {
            pending: HashMap::new(),
            history: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum ApprovalStatus {
    Pending,
    Approved,
    Rejected,
    Denied,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ActionRequestPayload {
    #[serde(default)]
    request_id: Option<String>,
    tool_id: String,
    #[serde(default)]
    args: Value,
    source: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ActionApprovalRecord {
    approval_id: String,
    request_id: String,
    gateway_request_id: Option<String>,
    tool_id: String,
    args: Value,
    status: ApprovalStatus,
    reason: Option<String>,
    question_id: Option<String>,
    output: Option<Value>,
    source: String,
    requested_at: String,
    resolved_at: Option<String>,
}

struct ApprovalState {
    pending: HashMap<String, ActionApprovalRecord>,
    history: Vec<ActionApprovalRecord>,
}

impl ApprovalState {
    fn new() -> Self {
        Self {
            pending: HashMap::new(),
            history: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct ActionRequestOutcome {
    request_id: String,
    gateway_request_id: Option<String>,
    status: ApprovalStatus,
    approval_id: Option<String>,
    question_id: Option<String>,
    output: Option<Value>,
    reason: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum DictationStrategy {
    LocalFirst,
    OsOnly,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct DictationConfig {
    strategy: DictationStrategy,
    local_stt_command: Option<String>,
    local_stt_args: Vec<String>,
    local_stt_timeout_seconds: u64,
    os_fallback_hint: String,
}

impl Default for DictationConfig {
    fn default() -> Self {
        Self {
            strategy: DictationStrategy::LocalFirst,
            local_stt_command: None,
            local_stt_args: vec!["-f".to_string(), "{audio}".to_string()],
            local_stt_timeout_seconds: 30,
            os_fallback_hint:
                "Local STT is not configured. Use your OS dictation shortcut as fallback."
                    .to_string(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum DictationOutcomeStatus {
    Listening,
    Transcribed,
    NeedsOsFallback,
    Failed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DictationSession {
    session_id: String,
    status: DictationOutcomeStatus,
    started_at: String,
    finished_at: Option<String>,
    engine: String,
    audio_path: Option<String>,
    transcript: Option<String>,
    message: Option<String>,
}

struct DictationState {
    config: DictationConfig,
    active_session: Option<DictationSession>,
    history: Vec<DictationSession>,
}

impl DictationState {
    fn new() -> Self {
        Self {
            config: DictationConfig::default(),
            active_session: None,
            history: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct OpenClawConfig {
    gateway_url: String,
    allowlisted_node_commands: Vec<String>,
    connect_timeout_seconds: u64,
}

impl Default for OpenClawConfig {
    fn default() -> Self {
        Self {
            gateway_url: "ws://127.0.0.1:8765".to_string(),
            allowlisted_node_commands: vec![
                "node".to_string(),
                "npm".to_string(),
                "npx".to_string(),
                "pnpm".to_string(),
                "yarn".to_string(),
            ],
            connect_timeout_seconds: 8,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct OpenClawStatus {
    connected: bool,
    gateway_url: Option<String>,
    last_error: Option<String>,
    last_event_at: Option<String>,
    last_connected_at: Option<String>,
    reconnect_attempt: u32,
    queued_outbound: usize,
    pending_ack_count: usize,
    last_acked_message_id: Option<String>,
}

impl Default for OpenClawStatus {
    fn default() -> Self {
        Self {
            connected: false,
            gateway_url: None,
            last_error: None,
            last_event_at: None,
            last_connected_at: None,
            reconnect_attempt: 0,
            queued_outbound: 0,
            pending_ack_count: 0,
            last_acked_message_id: None,
        }
    }
}

#[derive(Debug, Clone)]
struct PendingAckRecord {
    payload: String,
    attempts: u32,
    last_sent_at: String,
}

struct OpenClawState {
    config: OpenClawConfig,
    status: OpenClawStatus,
    outbound_tx: Option<mpsc::UnboundedSender<String>>,
    pending_outbound: VecDeque<String>,
    pending_acks: HashMap<String, PendingAckRecord>,
    pending_ack_order: VecDeque<String>,
    recent_event_ids: VecDeque<String>,
    recent_event_lookup: HashSet<String>,
}

impl OpenClawState {
    fn new() -> Self {
        Self {
            config: OpenClawConfig::default(),
            status: OpenClawStatus::default(),
            outbound_tx: None,
            pending_outbound: VecDeque::new(),
            pending_acks: HashMap::new(),
            pending_ack_order: VecDeque::new(),
            recent_event_ids: VecDeque::new(),
            recent_event_lookup: HashSet::new(),
        }
    }

    fn push_pending_outbound(&mut self, payload: String, front: bool) -> bool {
        if front {
            self.pending_outbound.push_front(payload);
        } else {
            self.pending_outbound.push_back(payload);
        }

        let mut dropped = false;
        while self.pending_outbound.len() > OPENCLAW_MAX_PENDING_OUTBOUND {
            dropped = true;
            if front {
                let _ = self.pending_outbound.pop_back();
            } else {
                let _ = self.pending_outbound.pop_front();
            }
        }

        self.status.queued_outbound = self.pending_outbound.len();
        dropped
    }

    fn take_pending_outbound(&mut self) -> Vec<String> {
        let drained = self.pending_outbound.drain(..).collect::<Vec<_>>();
        self.status.queued_outbound = 0;
        drained
    }

    fn pending_ack_payloads(&self) -> Vec<String> {
        self.pending_ack_order
            .iter()
            .filter_map(|message_id| self.pending_acks.get(message_id))
            .map(|record| record.payload.clone())
            .collect()
    }

    fn register_pending_ack(&mut self, message_id: String, payload: String) -> bool {
        let now = now_utc_iso();
        if let Some(record) = self.pending_acks.get_mut(&message_id) {
            record.payload = payload;
            record.attempts += 1;
            record.last_sent_at = now;
            self.status.pending_ack_count = self.pending_acks.len();
            return false;
        }

        self.pending_acks.insert(
            message_id.clone(),
            PendingAckRecord {
                payload,
                attempts: 1,
                last_sent_at: now,
            },
        );
        self.pending_ack_order.push_back(message_id.clone());

        let mut dropped = false;
        while self.pending_ack_order.len() > OPENCLAW_MAX_PENDING_ACKS {
            dropped = true;
            if let Some(oldest) = self.pending_ack_order.pop_front() {
                self.pending_acks.remove(&oldest);
            }
        }

        self.status.pending_ack_count = self.pending_acks.len();
        dropped
    }

    fn acknowledge_pending_ack(&mut self, message_id: &str) -> bool {
        if self.pending_acks.remove(message_id).is_none() {
            return false;
        }

        self.pending_ack_order.retain(|item| item != message_id);
        self.status.pending_ack_count = self.pending_acks.len();
        self.status.last_acked_message_id = Some(message_id.to_string());
        true
    }

    fn remember_event_id(&mut self, event_id: &str) -> bool {
        if self.recent_event_lookup.contains(event_id) {
            return true;
        }

        self.recent_event_lookup.insert(event_id.to_string());
        self.recent_event_ids.push_back(event_id.to_string());

        while self.recent_event_ids.len() > OPENCLAW_MAX_RECENT_EVENT_IDS {
            if let Some(oldest) = self.recent_event_ids.pop_front() {
                self.recent_event_lookup.remove(&oldest);
            }
        }

        false
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct NightModeConfig {
    enabled: bool,
    start_hour: u8,
    end_hour: u8,
    autopilot_enabled: bool,
}

impl Default for NightModeConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            start_hour: 1,
            end_hour: 6,
            autopilot_enabled: false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct NightModeReport {
    run_id: String,
    source: String,
    ran_at: String,
    safe_tasks: Vec<String>,
    proposals: Vec<String>,
}

struct NightModeState {
    config: NightModeConfig,
    last_report: Option<NightModeReport>,
}

impl NightModeState {
    fn new() -> Self {
        Self {
            config: NightModeConfig::default(),
            last_report: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct LocalhostStatus {
    enabled: bool,
    port: u16,
    running: bool,
    last_error: Option<String>,
}

impl LocalhostStatus {
    fn new(enabled: bool, port: u16) -> Self {
        Self {
            enabled,
            port,
            running: false,
            last_error: None,
        }
    }
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct AuditEntry {
    timestamp: String,
    category: String,
    details: Value,
}

struct NativeToolWorkerProcess {
    root: PathBuf,
    nas_root: String,
    child: TokioChild,
    stdin: TokioChildStdin,
    stdout: TokioBufReader<TokioChildStdout>,
    requests_served: u64,
}

struct OverlayAppState {
    settings_path: PathBuf,
    audit_log_path: PathBuf,
    settings: Mutex<OverlaySettings>,
    performance: Mutex<PerformanceState>,
    mode_state: Mutex<ModeState>,
    question_state: Mutex<QuestionState>,
    approval_state: Mutex<ApprovalState>,
    dictation_state: Mutex<DictationState>,
    openclaw_state: Mutex<OpenClawState>,
    night_mode_state: Mutex<NightModeState>,
    localhost_status: Mutex<LocalhostStatus>,
    openai_codex_oauth_pending: Mutex<Option<OpenAiCodexOAuthPending>>,
    native_tool_worker: AsyncMutex<Option<NativeToolWorkerProcess>>,
    audit_lock: Mutex<()>,
    space_is_held: AtomicBool,
    localhost_started: AtomicBool,
    night_mode_started: AtomicBool,
    control_room_watch_started: AtomicBool,
}

impl OverlayAppState {
    fn new(settings_path: PathBuf, settings: OverlaySettings, audit_log_path: PathBuf) -> Self {
        let localhost_status =
            LocalhostStatus::new(settings.localhost_api_enabled, settings.localhost_api_port);
        Self {
            mode_state: Mutex::new(ModeState::new(&settings.mode_id)),
            settings_path,
            audit_log_path,
            settings: Mutex::new(settings),
            performance: Mutex::new(PerformanceState::new()),
            question_state: Mutex::new(QuestionState::new()),
            approval_state: Mutex::new(ApprovalState::new()),
            dictation_state: Mutex::new(DictationState::new()),
            openclaw_state: Mutex::new(OpenClawState::new()),
            night_mode_state: Mutex::new(NightModeState::new()),
            localhost_status: Mutex::new(localhost_status),
            openai_codex_oauth_pending: Mutex::new(None),
            native_tool_worker: AsyncMutex::new(None),
            audit_lock: Mutex::new(()),
            space_is_held: AtomicBool::new(false),
            localhost_started: AtomicBool::new(false),
            night_mode_started: AtomicBool::new(false),
            control_room_watch_started: AtomicBool::new(false),
        }
    }
}

#[derive(Debug, Clone)]
struct OpenAiCodexOAuthPending {
    code_verifier: String,
    state: String,
    redirect_uri: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct OverlaySetModePayload {
    mode_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct OverlayPinPayload {
    pinned: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct UiAskPayload {
    question_id: Option<String>,
    question: String,
    choices: Vec<QuestionChoice>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct UiAnswerPayload {
    question_id: String,
    choice_id: String,
    #[serde(default)]
    custom_answer: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "command", content = "payload")]
enum ControlCommand {
    #[serde(rename = "overlay.open")]
    OverlayOpen,
    #[serde(rename = "overlay.close")]
    OverlayClose,
    #[serde(rename = "overlay.pin")]
    OverlayPin(OverlayPinPayload),
    #[serde(rename = "overlay.set_mode")]
    OverlaySetMode(OverlaySetModePayload),
    #[serde(rename = "context.capture")]
    ContextCapture(ContextCaptureRequest),
    #[serde(rename = "ui.ask")]
    UiAsk(UiAskPayload),
    #[serde(rename = "ui.answer")]
    UiAnswer(UiAnswerPayload),
    #[serde(rename = "action.request")]
    ActionRequest(ActionRequestPayload),
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct ControlCommandResponse {
    ok: bool,
    data: Value,
    error: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct ResolveApprovalPayload {
    approval_id: String,
    approved: bool,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct NodeCommandArgs {
    command: String,
    #[serde(default)]
    args: Vec<String>,
    cwd: Option<String>,
    timeout_seconds: Option<u64>,
}

#[derive(Clone)]
struct LocalApiState {
    app: AppHandle,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct LocalGatewayConfigPayload {
    gateway_url: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AgentLoopPayload {
    root: Option<String>,
    cycles: Option<u32>,
    iterations: Option<u32>,
    mode: Option<String>,
    profile: Option<String>,
    merge_policy: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AgentSoakPayload {
    root: Option<String>,
    objective: String,
    docs: Option<Vec<String>>,
    cycles: Option<u32>,
    iterations: Option<u32>,
    mode: Option<String>,
    profile: Option<String>,
    merge_policy: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AutonomyDashboardPayload {
    root: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct ControlRoomSummaryPayload {
    root: Option<String>,
    #[allow(dead_code)]
    summary_mode: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DesktopBackendCallPayload {
    command: String,
    payload: Option<Value>,
    root: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct IosStudioRootPayload {
    root: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct IosStudioCreatePayload {
    root: Option<String>,
    name: String,
    directory: Option<String>,
    bundle_identifier: String,
    install_dependencies: Option<bool>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct IosStudioBuilderPayload {
    root: Option<String>,
    label: Option<String>,
    host: String,
    user: String,
    port: Option<u16>,
    remote_root: Option<String>,
    identity_file: Option<String>,
    apple_team_id: Option<String>,
    known_hosts_policy: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct IosStudioWindowsPayload {
    root: Option<String>,
    engine: Option<String>,
    distro: Option<String>,
    minimum_ios: Option<String>,
    identity_file: Option<String>,
    certificate_file: Option<String>,
    provisioning_profile: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct IosStudioPreviewPayload {
    root: Option<String>,
    port: Option<u16>,
    install_dependencies: Option<bool>,
}

#[derive(Debug, Clone, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct IosStudioBuildPayload {
    root: Option<String>,
    mode: Option<String>,
    timeout_seconds: Option<u64>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct WorkspaceSavePayload {
    root: Option<String>,
    workspace_id: Option<String>,
    name: String,
    path: String,
    default_runtime: String,
    user_profile: Option<String>,
    preferred_harness: Option<String>,
    routing_strategy: Option<String>,
    route_overrides: Option<Vec<Value>>,
    auto_optimize_routing: Option<bool>,
    openai_codex_auth_mode: Option<String>,
    minimax_auth_mode: Option<String>,
    commit_message_style: Option<String>,
    execution_target_preference: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct WorkspaceDeletePayload {
    root: Option<String>,
    workspace_id: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ControlMissionStartPayload {
    root: Option<String>,
    workspace_id: String,
    runtime: String,
    objective: String,
    success_checks: Option<Vec<String>>,
    mode: Option<String>,
    budget_hours: Option<u32>,
    reasoning_effort: Option<String>,
    ultra_worker_effort: Option<String>,
    run_until: Option<String>,
    profile: Option<String>,
    escalation_destination: Option<String>,
    code_execution: Option<bool>,
    code_execution_memory: Option<String>,
    code_execution_container_id: Option<String>,
    code_execution_required: Option<bool>,
    route_overrides: Option<Vec<Value>>,
    mission_contract: Option<Value>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ControlMissionQuickstartPayload {
    root: Option<String>,
    workspace_id: Option<String>,
    runtime: Option<String>,
    objective: String,
    success_checks: Option<Vec<String>>,
    mode: Option<String>,
    budget_hours: Option<u32>,
    turn_mode: Option<String>,
    reasoning_effort: Option<String>,
    ultra_worker_effort: Option<String>,
    foreground: Option<bool>,
}

#[derive(Debug, Clone, Deserialize)]
struct CodexThreadIndexRecord {
    id: String,
    #[serde(default)]
    thread_name: Option<String>,
    #[serde(default)]
    updated_at: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct CodexSessionMetaPayload {
    #[serde(default)]
    id: Option<String>,
    #[serde(default)]
    cwd: Option<String>,
    #[serde(default)]
    originator: Option<String>,
    #[serde(default)]
    source: Option<String>,
    #[serde(default)]
    model_provider: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Default)]
struct CodexSessionMetaEnvelope {
    #[serde(rename = "type", default)]
    record_type: String,
    #[serde(default)]
    payload: CodexSessionMetaPayload,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct CodexRecentThreadSummary {
    id: String,
    thread_name: String,
    updated_at: Option<String>,
    cwd: Option<String>,
    originator: Option<String>,
    source: Option<String>,
    model_provider: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct CodexWorkspaceSummary {
    path: String,
    name: String,
    thread_count: usize,
    latest_thread_name: Option<String>,
    updated_at: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct CodexImportSnapshot {
    available: bool,
    codex_home: Option<String>,
    session_count: usize,
    skill_count: usize,
    recent_threads: Vec<CodexRecentThreadSummary>,
    workspaces: Vec<CodexWorkspaceSummary>,
    package_state_path: Option<String>,
    notes: Vec<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ControlMissionActionPayload {
    root: Option<String>,
    mission_id: String,
    action: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ControlMissionFollowUpPayload {
    root: Option<String>,
    mission_id: String,
    message: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ControlWorkspaceActionPayload {
    root: Option<String>,
    workspace_id: Option<String>,
    surface: String,
    action_id: String,
    approved: Option<bool>,
}

#[derive(Debug, Clone, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct NasStoragePressurePayload {
    root: Option<String>,
    path: Option<String>,
    write_latest: Option<bool>,
    no_write_latest: Option<bool>,
}

#[derive(Debug, Clone, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct AttachVerifierProofPayload {
    root: Option<String>,
    mission_id: Option<String>,
    flow_id: Option<String>,
    report_path: Option<String>,
    artifacts: Option<Vec<Value>>,
    checks: Option<Vec<Value>>,
}

#[derive(Debug, Clone, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct RealAgentRuntimeProofPayload {
    root: Option<String>,
    runtime: Option<String>,
    runtime_timeout: Option<u64>,
    with_browser: Option<bool>,
}

#[derive(Debug, Clone, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct AuthenticatedLiveAgentProofPayload {
    root: Option<String>,
    mission_id: Option<String>,
    url: Option<String>,
    out_dir: Option<String>,
    name: Option<String>,
    timeout_ms: Option<u64>,
    browser: Option<String>,
    with_browser: Option<bool>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct TelegramMessagePayload {
    chat_id: String,
    text: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct AutonomyDashboardSnapshot {
    workspace_root: String,
    openclaw_status: OpenClawStatus,
    pending_questions: usize,
    pending_approvals: usize,
    latest_session_id: Option<String>,
    objective: Option<String>,
    autopilot_status: Option<String>,
    autopilot_pause_reason: Option<String>,
    merge_policy: Option<String>,
    parallel_agents: Option<u64>,
    checkpoint_count: usize,
    remaining_steps: usize,
    verification_failures: usize,
    updated_at: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct OpenClawMessagePayload {
    message: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct LocalhostConfigPayload {
    enabled: bool,
    port: Option<u16>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct OpenAiCodexOAuthCompletePayload {
    callback: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct OpenAiCodexOAuthCredential {
    access: String,
    refresh: String,
    expires: Option<i64>,
    account_id: Option<String>,
    id_token: Option<String>,
    client_id: String,
    issuer: String,
    stored_at: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct OpenAiCodexOAuthStatus {
    authenticated: bool,
    account_id: Option<String>,
    expires: Option<i64>,
    source: Option<String>,
    message: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct OpenAiCodexOAuthResponse {
    status: String,
    authenticated: bool,
    account_id: Option<String>,
    expires: Option<i64>,
    auth_url: Option<String>,
    redirect_uri: Option<String>,
    hermes_sync: Option<Value>,
    message: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct MinimaxOpenClawAuthStartPayload {
    region: Option<String>,
    set_default: Option<bool>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct MinimaxOpenClawAuthStatus {
    authenticated: bool,
    provider_id: String,
    region: Option<String>,
    expires: Option<i64>,
    credentials_path: String,
    auth_store_path: String,
    source: Option<String>,
    message: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct MinimaxOpenClawAuthStartResponse {
    launched: bool,
    provider_id: String,
    method: String,
    command: String,
    status: MinimaxOpenClawAuthStatus,
    message: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct DictationStopPayload {
    audio_path: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct DictationTranscribePayload {
    audio_path: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
enum GatewayInboundEvent {
    #[serde(rename = "clarify")]
    Clarify {
        #[serde(default, alias = "id")]
        event_id: Option<String>,
        question_id: Option<String>,
        question: String,
        choices: Vec<String>,
    },
    #[serde(rename = "action.request")]
    ActionRequest {
        #[serde(default, alias = "id")]
        event_id: Option<String>,
        request_id: Option<String>,
        tool_id: String,
        #[serde(default)]
        args: Value,
    },
    #[serde(rename = "agent.message")]
    AgentMessage {
        #[serde(default, alias = "id")]
        event_id: Option<String>,
        content: String,
    },
    #[serde(rename = "ack")]
    Ack {
        #[serde(default, alias = "id")]
        event_id: Option<String>,
        #[serde(alias = "messageId")]
        message_id: String,
        #[serde(default)]
        status: Option<String>,
    },
}

fn gateway_event_identity(event: &GatewayInboundEvent) -> Option<String> {
    match event {
        GatewayInboundEvent::Clarify {
            event_id,
            question_id,
            ..
        } => event_id.clone().or_else(|| question_id.clone()),
        GatewayInboundEvent::ActionRequest {
            event_id,
            request_id,
            ..
        } => event_id.clone().or_else(|| request_id.clone()),
        GatewayInboundEvent::AgentMessage { event_id, .. } => event_id.clone(),
        GatewayInboundEvent::Ack {
            event_id,
            message_id,
            ..
        } => event_id.clone().or_else(|| Some(message_id.clone())),
    }
}

fn validate_gateway_event(event: &GatewayInboundEvent) -> Result<(), String> {
    if let Some(event_id) = gateway_event_identity(event) {
        let normalized = event_id.trim();
        if normalized.is_empty() {
            return Err("gateway event id is empty".to_string());
        }
        if normalized.len() > 128 {
            return Err("gateway event id is too long".to_string());
        }
    }

    match event {
        GatewayInboundEvent::Clarify {
            question, choices, ..
        } => {
            if question.trim().is_empty() {
                return Err("clarify question is empty".to_string());
            }
            if choices.len() < 1 || choices.len() > 8 {
                return Err("clarify choices must be between 1 and 8".to_string());
            }
        }
        GatewayInboundEvent::ActionRequest { tool_id, .. } => {
            if tool_id.trim().is_empty() {
                return Err("action.request tool_id is empty".to_string());
            }
            if tool_id.len() > 128 {
                return Err("action.request tool_id is too long".to_string());
            }
        }
        GatewayInboundEvent::AgentMessage { content, .. } => {
            if content.trim().is_empty() {
                return Err("agent.message content is empty".to_string());
            }
        }
        GatewayInboundEvent::Ack { message_id, .. } => {
            if message_id.trim().is_empty() {
                return Err("ack message_id is empty".to_string());
            }
            if message_id.len() > 128 {
                return Err("ack message_id is too long".to_string());
            }
        }
    }
    Ok(())
}

fn now_utc_iso() -> String {
    Utc::now().to_rfc3339()
}

fn workspace_has_agent_cli(root: &Path) -> bool {
    root.join("src").join("grant_agent").join("cli.py").exists()
        || root.join("pyproject.toml").exists()
}

fn resolve_workspace_root(root_override: Option<String>) -> Result<PathBuf, String> {
    if base_pack_bridge::enabled() {
        let root = root_override.filter(|s|!s.trim().is_empty()).map(PathBuf::from)
            .or_else(||runtime_env::managed_root().map(|root|root.join("workspace")))
            .ok_or("No writable workspace directory")?;
        fs::create_dir_all(&root).map_err(|e|e.to_string())?;
        return root.canonicalize().map_err(|e|e.to_string());
    }
    let has_explicit_root = root_override
        .as_ref()
        .is_some_and(|value| !value.trim().is_empty());
    // A paired desktop keeps one durable state root across Start-menu, tray,
    // and source launches. Execution workspaces are still explicit overrides.
    if !has_explicit_root {
        if let Some(app_data) = std::env::var_os("APPDATA") {
            let preference = PathBuf::from(app_data)
                .join("com.neyvia.desktop")
                .join("desktop_controller_root.json");
            if preference.is_file() {
                let bytes = fs::read(&preference)
                    .map_err(|error| format!("Could not read the shared desktop workspace: {error}"))?;
                let saved: Value = serde_json::from_slice(&bytes)
                    .map_err(|error| format!("The shared desktop workspace setting is invalid: {error}"))?;
                let path = saved.get("root").and_then(Value::as_str)
                    .filter(|value| !value.trim().is_empty())
                    .ok_or_else(|| "The shared desktop workspace setting has no root.".to_string())?;
                let root = PathBuf::from(path);
                if !root.is_dir() {
                    return Err("The shared desktop workspace is unavailable. Restore its folder before opening Neyvia.".to_string());
                }
                return root.canonicalize()
                    .map_err(|error| format!("Could not resolve the shared desktop workspace: {error}"));
            }
        }
    }
    let candidate = if let Some(raw) = root_override {
        let trimmed = raw.trim();
        if trimmed.is_empty() {
            std::env::current_dir().map_err(|err| format!("Failed to resolve cwd: {err}"))?
        } else {
            PathBuf::from(trimmed)
        }
    } else {
        std::env::current_dir().map_err(|err| format!("Failed to resolve cwd: {err}"))?
    };

    if !candidate.exists() {
        return Err(format!(
            "Workspace root does not exist: {}",
            candidate.display()
        ));
    }
    if !candidate.is_dir() {
        return Err(format!(
            "Workspace root is not a directory: {}",
            candidate.display()
        ));
    }

    let canonical = candidate
        .canonicalize()
        .map_err(|err| format!("Failed to canonicalize workspace root: {err}"))?;

    if workspace_has_agent_cli(&canonical) {
        return Ok(canonical);
    }

    let mut cursor = canonical.clone();
    while let Some(parent) = cursor.parent() {
        if workspace_has_agent_cli(parent) {
            return Ok(parent.to_path_buf());
        }
        cursor = parent.to_path_buf();
    }

    if !has_explicit_root {
        // Installed desktop commands have no explicit source checkout. Use the
        // backend shipped beside this executable before legacy development roots.
        if let Some(bundled) = runtime_env::bundled_backend_root() {
            return Ok(bundled);
        }
        let mut known_roots = Vec::new();
        if let Some(path) = std::env::var_os("NEYVIA_WORKSPACE_ROOT") {
            known_roots.push(PathBuf::from(path));
        }
        if let Some(home) = home_dir_path() {
            known_roots.push(home.join("projects").join("vibe-coding-platform"));
        }
        #[cfg(windows)]
        known_roots.push(PathBuf::from(r"Y:\projects\vibe-coding-platform"));
        if let Some(discovered) = known_roots
            .into_iter()
            .find(|path| workspace_has_agent_cli(path))
        {
            return discovered.canonicalize().map_err(|err| {
                format!("Failed to canonicalize discovered Neyvia workspace: {err}")
            });
        }
    }

    Ok(canonical)
}

fn modified_nanos(value: SystemTime) -> u128 {
    value
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos()
}

fn home_dir_path() -> Option<PathBuf> {
    std::env::var_os("USERPROFILE")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(PathBuf::from))
}

fn count_codex_skill_dirs(skills_root: &Path) -> usize {
    fs::read_dir(skills_root)
        .ok()
        .into_iter()
        .flat_map(|entries| entries.flatten())
        .filter(|entry| entry.path().is_dir() && entry.path().join("SKILL.md").exists())
        .count()
}

fn dir_entry_modified(entry: &fs::DirEntry) -> SystemTime {
    entry
        .metadata()
        .and_then(|metadata| metadata.modified())
        .unwrap_or(UNIX_EPOCH)
}

fn collect_codex_session_files(root: &Path, files: &mut Vec<(PathBuf, SystemTime)>, limit: usize) {
    if files.len() >= limit {
        return;
    }
    let Ok(entries) = fs::read_dir(root) else {
        return;
    };
    let mut entries = entries.flatten().collect::<Vec<_>>();
    entries.sort_by(|left, right| {
        modified_nanos(dir_entry_modified(right)).cmp(&modified_nanos(dir_entry_modified(left)))
    });
    for entry in entries {
        if files.len() >= limit {
            break;
        }
        let path = entry.path();
        if path.is_dir() {
            collect_codex_session_files(&path, files, limit);
            continue;
        }
        if path.extension().and_then(|value| value.to_str()) != Some("jsonl") {
            continue;
        }
        files.push((path, dir_entry_modified(&entry)));
    }
}

fn read_codex_session_meta(path: &Path) -> Option<CodexSessionMetaPayload> {
    let file = File::open(path).ok()?;
    for line in BufReader::new(file).lines().take(8) {
        let line = line.ok()?;
        let Ok(record) = serde_json::from_str::<CodexSessionMetaEnvelope>(&line) else {
            continue;
        };
        if record.record_type == "session_meta" {
            return Some(record.payload);
        }
    }
    None
}

fn collect_recent_codex_session_meta(
    sessions_root: &Path,
    limit: usize,
) -> HashMap<String, CodexSessionMetaPayload> {
    let mut files = Vec::new();
    collect_codex_session_files(sessions_root, &mut files, CODEX_SESSION_SCAN_FILE_LIMIT);
    files.sort_by(|left, right| modified_nanos(right.1).cmp(&modified_nanos(left.1)));

    let mut recent = HashMap::new();
    for (path, _) in files {
        if recent.len() >= limit {
            break;
        }
        let Some(meta) = read_codex_session_meta(&path) else {
            continue;
        };
        let Some(id) = meta.id.clone() else {
            continue;
        };
        recent.entry(id).or_insert(meta);
    }
    recent
}

fn codex_workspace_name(path: &str) -> String {
    let candidate = Path::new(path)
        .file_name()
        .and_then(|value| value.to_str())
        .filter(|value| !value.trim().is_empty())
        .unwrap_or(path);
    candidate.replace(['_', '-'], " ")
}

fn build_codex_import_snapshot() -> CodexImportSnapshot {
    let Some(home) = home_dir_path() else {
        return CodexImportSnapshot {
            available: false,
            codex_home: None,
            session_count: 0,
            skill_count: 0,
            recent_threads: Vec::new(),
            workspaces: Vec::new(),
            package_state_path: None,
            notes: vec!["Could not resolve the user home directory.".to_string()],
        };
    };

    let codex_home = home.join(".codex");
    let package_state_path = home
        .join("AppData")
        .join("Local")
        .join("Packages")
        .join("OpenAI.Codex_2p2nqsd0c76g0")
        .join("LocalState");
    let mut notes = Vec::new();

    if !codex_home.exists() {
        return CodexImportSnapshot {
            available: false,
            codex_home: Some(codex_home.display().to_string()),
            session_count: 0,
            skill_count: 0,
            recent_threads: Vec::new(),
            workspaces: Vec::new(),
            package_state_path: package_state_path
                .exists()
                .then(|| package_state_path.display().to_string()),
            notes: vec!["No Codex home directory was found on this machine.".to_string()],
        };
    }

    let session_index_path = codex_home.join("session_index.jsonl");
    let sessions_root = codex_home.join("sessions");
    let skills_root = codex_home.join("skills");
    let recent_meta = collect_recent_codex_session_meta(&sessions_root, CODEX_SESSION_META_LIMIT);
    let mut session_count = 0usize;
    let mut indexed_threads = Vec::new();

    if session_index_path.exists() {
        if let Ok(file) = File::open(&session_index_path) {
            for line in BufReader::new(file).lines().map_while(Result::ok) {
                let Ok(record) = serde_json::from_str::<CodexThreadIndexRecord>(&line) else {
                    continue;
                };
                session_count += 1;
                indexed_threads.push(record);
            }
        }
    } else {
        notes.push(
            "Codex session index was not found, so only partial import data is available."
                .to_string(),
        );
    }

    indexed_threads.reverse();
    let recent_threads = indexed_threads
        .into_iter()
        .take(12)
        .map(|record| {
            let meta = recent_meta.get(&record.id);
            CodexRecentThreadSummary {
                id: record.id,
                thread_name: record
                    .thread_name
                    .unwrap_or_else(|| "Untitled Codex thread".to_string()),
                updated_at: record.updated_at,
                cwd: meta.and_then(|item| item.cwd.clone()),
                originator: meta.and_then(|item| item.originator.clone()),
                source: meta.and_then(|item| item.source.clone()),
                model_provider: meta.and_then(|item| item.model_provider.clone()),
            }
        })
        .collect::<Vec<_>>();

    let mut workspace_map: HashMap<String, CodexWorkspaceSummary> = HashMap::new();
    for thread in &recent_threads {
        let Some(path) = thread.cwd.clone() else {
            continue;
        };
        let entry = workspace_map
            .entry(path.clone())
            .or_insert_with(|| CodexWorkspaceSummary {
                name: codex_workspace_name(&path),
                path: path.clone(),
                thread_count: 0,
                latest_thread_name: None,
                updated_at: None,
            });
        entry.thread_count += 1;
        if entry.latest_thread_name.is_none() {
            entry.latest_thread_name = Some(thread.thread_name.clone());
        }
        if entry.updated_at.is_none() {
            entry.updated_at = thread.updated_at.clone();
        }
    }

    let mut workspaces = workspace_map.into_values().collect::<Vec<_>>();
    workspaces.sort_by(|left, right| right.thread_count.cmp(&left.thread_count));

    let skill_count = count_codex_skill_dirs(&skills_root);
    if skill_count == 0 {
        notes.push("No local Codex skills were detected under the Codex home.".to_string());
    }

    CodexImportSnapshot {
        available: !recent_threads.is_empty() || skill_count > 0,
        codex_home: Some(codex_home.display().to_string()),
        session_count,
        skill_count,
        recent_threads,
        workspaces,
        package_state_path: package_state_path
            .exists()
            .then(|| package_state_path.display().to_string()),
        notes,
    }
}

fn cached_codex_import_snapshot() -> CodexImportSnapshot {
    let cache = CODEX_IMPORT_CACHE.get_or_init(|| Mutex::new(None));
    if let Ok(guard) = cache.lock() {
        if let Some((captured_at, snapshot)) = guard.as_ref() {
            if captured_at.elapsed() < Duration::from_secs(CODEX_IMPORT_CACHE_TTL_SECONDS) {
                return snapshot.clone();
            }
        }
    }

    let snapshot = build_codex_import_snapshot();
    if let Ok(mut guard) = cache.lock() {
        *guard = Some((Instant::now(), snapshot.clone()));
    }
    snapshot
}

fn collect_control_room_signature_paths(root: &Path) -> Vec<PathBuf> {
    let mut paths = vec![
        root.join("config").join("connected_apps.json"),
        root.join("config").join("profiles.json"),
        root.join("config").join("skills.json"),
    ];

    let control_dir = root.join(".agent_control");
    if let Ok(entries) = fs::read_dir(&control_dir) {
        let mut control_files: Vec<PathBuf> = entries
            .filter_map(|entry| entry.ok().map(|item| item.path()))
            .filter(|path| {
                let file_name = path
                    .file_name()
                    .and_then(|item| item.to_str())
                    .unwrap_or_default();
                path.is_file()
                    && matches!(
                        path.extension().and_then(|item| item.to_str()),
                        Some("json") | Some("jsonl")
                    )
                    && file_name != "connected_apps_state.json"
                    && file_name != "mission_events.jsonl"
            })
            .collect();
        control_files.sort();
        paths.extend(control_files);
    }

    let runs_root = root.join(".agent_runs");
    if let Ok(entries) = fs::read_dir(&runs_root) {
        let mut sessions: Vec<(SystemTime, PathBuf)> = entries
            .filter_map(|entry| {
                let entry = entry.ok()?;
                let path = entry.path();
                if !path.is_dir() {
                    return None;
                }
                let name = path.file_name()?.to_string_lossy();
                if !name.starts_with("session_") {
                    return None;
                }
                let modified = entry
                    .metadata()
                    .and_then(|meta| meta.modified())
                    .unwrap_or(SystemTime::UNIX_EPOCH);
                Some((modified, path))
            })
            .collect();
        sessions.sort_by(|left, right| right.0.cmp(&left.0));
        for (_modified, session_path) in sessions.into_iter().take(CONTROL_ROOM_WATCH_MAX_SESSIONS)
        {
            // High-churn event streams are pushed through the delta channel and should
            // not force a full control-room snapshot refresh.
            paths.push(session_path.join("state.json"));
        }
    }

    paths
}

fn compute_control_room_signature(root: &Path) -> String {
    let mut hasher = Sha256::new();
    hasher.update(root.to_string_lossy().as_bytes());
    for path in collect_control_room_signature_paths(root) {
        if let Ok(metadata) = fs::metadata(&path) {
            hasher.update(path.to_string_lossy().as_bytes());
            hasher.update(metadata.len().to_le_bytes());
            if let Ok(modified) = metadata.modified() {
                hasher.update(modified_nanos(modified).to_le_bytes());
            }
        }
    }
    format!("{:x}", hasher.finalize())
}

fn jsonl_line_count(path: &Path) -> usize {
    let Ok(file) = File::open(path) else {
        return 0;
    };
    BufReader::new(file)
        .lines()
        .map_while(Result::ok)
        .filter(|line| !line.trim().is_empty())
        .count()
}

fn read_jsonl_delta(path: &Path, start_line: usize) -> Vec<Value> {
    let Ok(file) = File::open(path) else {
        return Vec::new();
    };

    BufReader::new(file)
        .lines()
        .enumerate()
        .filter_map(|(index, line)| {
            if index < start_line {
                return None;
            }
            let line = line.ok()?;
            let trimmed = line.trim();
            if trimmed.is_empty() {
                return None;
            }
            serde_json::from_str::<Value>(trimmed).ok()
        })
        .collect()
}

fn runtime_event_paths(root: &Path) -> Vec<PathBuf> {
    let runtime_dir = root.join(".agent_control").join("runtime_sessions");
    let Ok(entries) = fs::read_dir(runtime_dir) else {
        return Vec::new();
    };

    let mut paths: Vec<PathBuf> = entries
        .filter_map(|entry| entry.ok().map(|item| item.path()))
        .filter(|path| {
            path.is_file()
                && path
                    .file_name()
                    .and_then(|item| item.to_str())
                    .map(|name| name.ends_with(".events.jsonl"))
                    .unwrap_or(false)
        })
        .collect();
    paths.sort();
    paths
}

fn emit_control_room_delta(app: &AppHandle, root: &Path, source: &str, row: Value) {
    let _ = app.emit(
        CONTROL_ROOM_DELTA_EVENT_NAME,
        json!({
            "root": root.to_string_lossy().to_string(),
            "source": source,
            "row": row,
            "detectedAt": now_utc_iso(),
        }),
    );
}

fn start_control_room_watch(app: &AppHandle) {
    let state = app.state::<OverlayAppState>();
    if state
        .control_room_watch_started
        .swap(true, Ordering::SeqCst)
    {
        return;
    }

    let root = match resolve_workspace_root(None) {
        Ok(root) => root,
        Err(err) => {
            log::warn!("control-room watch disabled: {err}");
            return;
        }
    };

    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        let mut last_signature = compute_control_room_signature(&root);
        let mission_events_path = root.join(".agent_control").join("mission_events.jsonl");
        let mut mission_event_cursor = jsonl_line_count(&mission_events_path);
        let mut runtime_event_cursors: HashMap<String, usize> = runtime_event_paths(&root)
            .into_iter()
            .map(|path| {
                let key = path.to_string_lossy().to_string();
                let count = jsonl_line_count(&path);
                (key, count)
            })
            .collect();

        loop {
            sleep(Duration::from_millis(CONTROL_ROOM_WATCH_INTERVAL_MS)).await;

            let mission_delta = read_jsonl_delta(&mission_events_path, mission_event_cursor);
            if !mission_delta.is_empty() {
                mission_event_cursor += mission_delta.len();
                for row in mission_delta {
                    emit_control_room_delta(&app_handle, &root, "mission_event", row);
                }
            }

            for path in runtime_event_paths(&root) {
                let key = path.to_string_lossy().to_string();
                let cursor = runtime_event_cursors.get(&key).copied().unwrap_or(0);
                let delta = read_jsonl_delta(&path, cursor);
                if delta.is_empty() {
                    runtime_event_cursors
                        .entry(key)
                        .or_insert_with(|| jsonl_line_count(&path));
                    continue;
                }

                runtime_event_cursors.insert(key, cursor + delta.len());
                for row in delta {
                    emit_control_room_delta(&app_handle, &root, "runtime_event", row);
                }
            }

            let next_signature = compute_control_room_signature(&root);
            if next_signature == last_signature {
                continue;
            }
            last_signature = next_signature.clone();
            let _ = app_handle.emit(
                CONTROL_ROOM_EVENT_NAME,
                json!({
                    "root": root.to_string_lossy().to_string(),
                    "signature": next_signature,
                    "reason": "fs.changed",
                    "detectedAt": now_utc_iso(),
                }),
            );
        }
    });
}

fn emit_control_room_changed(app: &AppHandle, reason: &str) {
    let root = resolve_workspace_root(None)
        .map(|value| value.to_string_lossy().to_string())
        .unwrap_or_default();
    let _ = app.emit(
        CONTROL_ROOM_EVENT_NAME,
        json!({
            "root": root,
            "reason": reason,
            "detectedAt": now_utc_iso(),
        }),
    );
}

fn latest_session_path(runs_root: &Path) -> Result<Option<PathBuf>, String> {
    if !runs_root.exists() {
        return Ok(None);
    }

    let mut latest: Option<(SystemTime, PathBuf)> = None;
    for entry in fs::read_dir(runs_root).map_err(|err| format!("Failed to read runs dir: {err}"))? {
        let entry = entry.map_err(|err| format!("Failed to read runs entry: {err}"))?;
        let file_type = entry
            .file_type()
            .map_err(|err| format!("Failed to read entry type: {err}"))?;
        if !file_type.is_dir() {
            continue;
        }

        let file_name = entry.file_name().to_string_lossy().to_string();
        if !file_name.starts_with("session_") {
            continue;
        }

        let modified = entry
            .metadata()
            .and_then(|meta| meta.modified())
            .unwrap_or(SystemTime::UNIX_EPOCH);
        let path = entry.path();

        match &latest {
            Some((last_modified, _)) if modified <= *last_modified => {}
            _ => latest = Some((modified, path)),
        }
    }

    Ok(latest.map(|(_, path)| path))
}

fn parse_agent_cli_stdout(stdout: &str) -> Result<Value, String> {
    let trimmed = stdout.trim();
    if trimmed.is_empty() {
        return Ok(json!({}));
    }

    if let Ok(value) = serde_json::from_str::<Value>(trimmed) {
        return Ok(value);
    }

    let start = trimmed.find('{');
    let end = trimmed.rfind('}');
    if let (Some(start), Some(end)) = (start, end) {
        if start < end {
            if let Ok(value) = serde_json::from_str::<Value>(&trimmed[start..=end]) {
                return Ok(value);
            }
        }
    }

    Err("Failed to parse JSON output from grant_agent.cli".to_string())
}

fn value_string(payload: &Value, snake_key: &str, camel_key: &str) -> Option<String> {
    payload
        .get(camel_key)
        .and_then(Value::as_str)
        .or_else(|| payload.get(snake_key).and_then(Value::as_str))
        .map(|value| value.to_string())
}

fn value_u64(payload: &Value, snake_key: &str, camel_key: &str) -> Option<u64> {
    payload
        .get(camel_key)
        .and_then(Value::as_u64)
        .or_else(|| payload.get(snake_key).and_then(Value::as_u64))
}

fn value_array_len(payload: &Value, snake_key: &str, camel_key: &str) -> usize {
    payload
        .get(camel_key)
        .and_then(Value::as_array)
        .or_else(|| payload.get(snake_key).and_then(Value::as_array))
        .map(|items| items.len())
        .unwrap_or(0)
}

fn build_autonomy_dashboard_snapshot(
    app: &AppHandle,
    root_override: Option<String>,
) -> Result<AutonomyDashboardSnapshot, String> {
    let workspace_root = resolve_workspace_root(root_override)?;

    let (openclaw_status, pending_questions, pending_approvals) = {
        let state = app.state::<OverlayAppState>();
        let openclaw_status = state
            .openclaw_state
            .lock()
            .map_err(|_| "Failed to lock OpenClaw state".to_string())?
            .status
            .clone();
        let pending_questions = state
            .question_state
            .lock()
            .map_err(|_| "Failed to lock question state".to_string())?
            .pending
            .len();
        let pending_approvals = state
            .approval_state
            .lock()
            .map_err(|_| "Failed to lock approval state".to_string())?
            .pending
            .len();
        (openclaw_status, pending_questions, pending_approvals)
    };

    let runs_root = workspace_root.join(".agent_runs");
    let latest_session = latest_session_path(&runs_root)?;

    let mut snapshot = AutonomyDashboardSnapshot {
        workspace_root: workspace_root.to_string_lossy().to_string(),
        openclaw_status,
        pending_questions,
        pending_approvals,
        latest_session_id: None,
        objective: None,
        autopilot_status: None,
        autopilot_pause_reason: None,
        merge_policy: None,
        parallel_agents: None,
        checkpoint_count: 0,
        remaining_steps: 0,
        verification_failures: 0,
        updated_at: None,
    };

    let Some(session_path) = latest_session else {
        return Ok(snapshot);
    };

    snapshot.latest_session_id = session_path
        .file_name()
        .map(|name| name.to_string_lossy().to_string());

    let state_path = session_path.join("state.json");
    if state_path.exists() {
        if let Ok(raw_state) = fs::read_to_string(&state_path) {
            if let Ok(parsed) = serde_json::from_str::<Value>(&raw_state) {
                snapshot.objective = value_string(&parsed, "objective", "objective");
                snapshot.autopilot_status =
                    value_string(&parsed, "autopilot_status", "autopilotStatus");
                snapshot.autopilot_pause_reason =
                    value_string(&parsed, "autopilot_pause_reason", "autopilotPauseReason");
                snapshot.merge_policy = value_string(&parsed, "merge_policy", "mergePolicy");
                snapshot.parallel_agents = value_u64(&parsed, "parallel_agents", "parallelAgents");
                snapshot.remaining_steps = value_array_len(&parsed, "next_actions", "nextActions");
                snapshot.verification_failures =
                    value_array_len(&parsed, "verification_failures", "verificationFailures");
            }
        }

        if let Ok(metadata) = fs::metadata(&state_path) {
            if let Ok(modified) = metadata.modified() {
                snapshot.updated_at = Some(chrono::DateTime::<Utc>::from(modified).to_rfc3339());
            }
        }
    }

    let checkpoints_path = session_path.join("checkpoints");
    if checkpoints_path.exists() {
        let mut count = 0usize;
        if let Ok(entries) = fs::read_dir(checkpoints_path) {
            for entry in entries.flatten() {
                if entry.file_type().map(|ft| ft.is_file()).unwrap_or(false) {
                    count += 1;
                }
            }
        }
        snapshot.checkpoint_count = count;
    }

    Ok(snapshot)
}

fn hide_child_console(command: &mut TokioCommand) {
    #[cfg(windows)]
    {
        command.creation_flags(CREATE_NO_WINDOW);
    }
    #[cfg(not(windows))]
    {
        let _ = command;
    }
}

impl NativeToolWorkerProcess {
    async fn call(&mut self, tool: &str, arguments: &Value) -> Result<Value, String> {
        self.requests_served += 1;
        let request_id = format!("native-tool-{}-{}", self.requests_served, Uuid::new_v4());
        let request = json!({
            "id": request_id,
            "tool": tool,
            "arguments": arguments,
        });
        let mut encoded = serde_json::to_vec(&request).map_err(|error| error.to_string())?;
        encoded.push(b'\n');
        self.stdin
            .write_all(&encoded)
            .await
            .map_err(|error| format!("Native tool worker write failed: {error}"))?;
        self.stdin
            .flush()
            .await
            .map_err(|error| format!("Native tool worker flush failed: {error}"))?;

        let mut line = String::new();
        let bytes_read = timeout(Duration::from_secs(120), self.stdout.read_line(&mut line))
            .await
            .map_err(|_| "Native tool worker timed out after 120s".to_string())?
            .map_err(|error| format!("Native tool worker read failed: {error}"))?;
        if bytes_read == 0 {
            return Err("Native tool worker exited before returning a response".to_string());
        }
        let response: Value = serde_json::from_str(line.trim())
            .map_err(|error| format!("Native tool worker returned invalid JSON: {error}"))?;
        if response.get("id").and_then(Value::as_str) != Some(request_id.as_str()) {
            return Err("Native tool worker response id did not match the request".to_string());
        }
        if response.get("ok").and_then(Value::as_bool) != Some(true) {
            return Err(response
                .get("error")
                .and_then(Value::as_str)
                .unwrap_or("Native tool worker failed")
                .to_string());
        }
        Ok(response.get("data").cloned().unwrap_or(Value::Null))
    }
}

async fn spawn_native_tool_worker(
    app: &AppHandle,
    workspace_root: &Path,
    nas_root: &str,
) -> Result<NativeToolWorkerProcess, String> {
    let interpreter = runtime_env::resolve_backend_python(workspace_root).await?;
    let mut command = interpreter.command();
    hide_child_console(&mut command);
    command.current_dir(workspace_root);
    inject_agent_cli_pythonpath(&mut command, workspace_root);
    inject_agent_cli_provider_env(app, &mut command)?;
    command
        .env("PYTHONUNBUFFERED", "1")
        .arg("-m")
        .arg("grant_agent.native_tool_worker")
        .arg("--root")
        .arg(workspace_root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .kill_on_drop(true);
    if !nas_root.is_empty() {
        command.arg("--nas-root").arg(nas_root);
    }
    let mut child = command
        .spawn()
        .map_err(|error| format!("Failed to start native tool worker: {error}"))?;
    let stdin = child
        .stdin
        .take()
        .ok_or_else(|| "Native tool worker stdin was unavailable".to_string())?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "Native tool worker stdout was unavailable".to_string())?;
    Ok(NativeToolWorkerProcess {
        root: workspace_root.to_path_buf(),
        nas_root: nas_root.to_string(),
        child,
        stdin,
        stdout: TokioBufReader::new(stdout),
        requests_served: 0,
    })
}

async fn call_persistent_native_tool_worker(
    app: &AppHandle,
    workspace_root: &Path,
    nas_root: &str,
    tool: &str,
    arguments: &Value,
) -> Result<Value, String> {
    let state = app.state::<OverlayAppState>();
    let mut worker_slot = state.native_tool_worker.lock().await;
    let mut errors = Vec::new();
    for attempt in 0..2 {
        let needs_worker = worker_slot
            .as_ref()
            .map(|worker| worker.root != workspace_root || worker.nas_root != nas_root)
            .unwrap_or(true);
        if needs_worker {
            if let Some(mut worker) = worker_slot.take() {
                let _ = worker.child.kill().await;
            }
            match spawn_native_tool_worker(app, workspace_root, nas_root).await {
                Ok(worker) => *worker_slot = Some(worker),
                Err(error) => {
                    errors.push(error);
                    continue;
                }
            }
        }
        let result = worker_slot
            .as_mut()
            .ok_or_else(|| "Native tool worker was unavailable".to_string())?
            .call(tool, arguments)
            .await;
        match result {
            Ok(value) => return Ok(value),
            Err(error) => {
                errors.push(format!("attempt {}: {error}", attempt + 1));
                if let Some(mut worker) = worker_slot.take() {
                    let _ = worker.child.kill().await;
                }
            }
        }
    }
    Err(errors.join("; "))
}

async fn run_agent_cli_json(
    app: &AppHandle,
    root_override: Option<String>,
    subcommand: &str,
    extra_args: Vec<String>,
    timeout_seconds: u64,
) -> Result<Value, String> {
    let workspace_root = resolve_workspace_root(root_override)?;
    let workspace_root_text = workspace_root.to_string_lossy().to_string();

    let interpreter = runtime_env::resolve_backend_python(&workspace_root).await?;
    let mut command = interpreter.command();
    hide_child_console(&mut command);
    command.current_dir(&workspace_root);
    inject_agent_cli_pythonpath(&mut command, &workspace_root);
    command.arg("-m").arg("grant_agent.cli").arg(subcommand);
    command.arg("--root").arg(&workspace_root_text);
    for arg in extra_args {
        command.arg(arg);
    }
    inject_agent_cli_provider_env(app, &mut command)?;
    // A timed-out CLI future is dropped below. Do not leave its child running
    // after the desktop request has already failed or been abandoned.
    command.kill_on_drop(true);

    append_audit_entry(
        app,
        "agent.cli_invoked",
        json!({
            "subcommand": subcommand,
            "workspaceRoot": workspace_root_text,
        }),
    );

    let started = Instant::now();
    let output = timeout(Duration::from_secs(timeout_seconds), command.output())
        .await
        .map_err(|_| {
            append_audit_entry(
                app,
                "agent.cli_failed",
                json!({
                    "subcommand": subcommand,
                    "workspaceRoot": workspace_root_text,
                    "durationMs": started.elapsed().as_millis() as u64,
                    "error": format!("timed out after {}s", timeout_seconds),
                }),
            );
            format!(
                "grant_agent.cli {} timed out after {}s",
                subcommand, timeout_seconds
            )
        })?
        .map_err(|err| {
            append_audit_entry(
                app,
                "agent.cli_failed",
                json!({
                    "subcommand": subcommand,
                    "workspaceRoot": workspace_root_text,
                    "durationMs": started.elapsed().as_millis() as u64,
                    "error": format!("spawn failed: {err}"),
                }),
            );
            format!("Failed to run grant_agent.cli {}: {err}", subcommand)
        })?;

    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();

    if !output.status.success() {
        append_audit_entry(
            app,
            "agent.cli_failed",
            json!({
                "subcommand": subcommand,
                "durationMs": started.elapsed().as_millis() as u64,
                "stderr": stderr,
            }),
        );
        return Err(format!(
            "grant_agent.cli {} failed: {}",
            subcommand,
            if stderr.is_empty() { stdout } else { stderr }
        ));
    }

    let parsed = parse_agent_cli_stdout(&stdout)?;
    append_audit_entry(
        app,
        "agent.cli_succeeded",
        json!({
            "subcommand": subcommand,
            "durationMs": started.elapsed().as_millis() as u64,
        }),
    );
    Ok(parsed)
}

fn default_modes() -> HashMap<String, ModeDefinition> {
    let mut map = HashMap::new();

    map.insert(
        "coding".to_string(),
        ModeDefinition {
            id: "coding".to_string(),
            label: "Coding".to_string(),
            description: "Code-focused mode with clipboard and active-window context.".to_string(),
            context_recipe: ContextCaptureRequest {
                clipboard: true,
                active_window: true,
                screenshot: false,
            },
            allowed_tools: vec![
                "tool.safe.echo".to_string(),
                "tool.safe.now".to_string(),
                "context.capture".to_string(),
                "node.command".to_string(),
                "ui.ask".to_string(),
                "ui.answer".to_string(),
            ],
        },
    );

    map.insert(
        "youtube".to_string(),
        ModeDefinition {
            id: "youtube".to_string(),
            label: "YouTube".to_string(),
            description: "Video-focused mode with optional screenshot context.".to_string(),
            context_recipe: ContextCaptureRequest {
                clipboard: false,
                active_window: true,
                screenshot: true,
            },
            allowed_tools: vec![
                "tool.safe.echo".to_string(),
                "tool.safe.now".to_string(),
                "context.capture".to_string(),
                "ui.ask".to_string(),
                "ui.answer".to_string(),
            ],
        },
    );

    map.insert(
        "writing".to_string(),
        ModeDefinition {
            id: "writing".to_string(),
            label: "Writing".to_string(),
            description: "Writing mode with clipboard and lightweight automation.".to_string(),
            context_recipe: ContextCaptureRequest {
                clipboard: true,
                active_window: true,
                screenshot: false,
            },
            allowed_tools: vec![
                "tool.safe.echo".to_string(),
                "tool.safe.now".to_string(),
                "context.capture".to_string(),
                "ui.ask".to_string(),
                "ui.answer".to_string(),
            ],
        },
    );

    map
}

fn load_settings(path: &PathBuf) -> OverlaySettings {
    let Ok(raw) = fs::read_to_string(path) else {
        return OverlaySettings::default();
    };

    serde_json::from_str::<OverlaySettings>(&raw).unwrap_or_default()
}

fn save_settings(path: &PathBuf, settings: &OverlaySettings) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|err| format!("Failed to create settings directory: {err}"))?;
    }

    let raw = serde_json::to_string_pretty(settings)
        .map_err(|err| format!("Failed to serialize settings: {err}"))?;

    fs::write(path, raw).map_err(|err| format!("Failed to persist settings: {err}"))
}

const SELF_UPDATE_FIRST_CHECK: Duration = Duration::from_secs(20);
const SELF_UPDATE_CHECK_EVERY: Duration = Duration::from_secs(6 * 60 * 60);
const SELF_UPDATE_IDLE_POLL: Duration = Duration::from_secs(60);

/// Whether the person is looking at Neyvia right now (a focused, visible main window).
fn main_window_in_use(app: &AppHandle) -> bool {
    app.get_webview_window(MAIN_WINDOW_LABEL)
        .map(|window| window.is_visible().unwrap_or(false) && window.is_focused().unwrap_or(false))
        .unwrap_or(false)
}

/// Keeps the desktop shell current by itself: checks the signed update feed on the
/// PC service shortly after start and every few hours, and installs a new version
/// only while the window is not in use (unfocused, minimized or in the tray). The
/// installer restarts the app; conversations live in the service and are untouched.
#[cfg(desktop)]
fn start_self_update(app: &AppHandle) {
    use tauri_plugin_updater::UpdaterExt;

    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        sleep(SELF_UPDATE_FIRST_CHECK).await;
        loop {
            let found = match handle.updater() {
                Ok(updater) => match updater.check().await {
                    Ok(found) => found,
                    Err(err) => {
                        log::info!("desktop update check failed: {err}");
                        None
                    }
                },
                Err(err) => {
                    log::info!("desktop updater unavailable: {err}");
                    None
                }
            };
            if let Some(update) = found {
                while main_window_in_use(&handle) {
                    sleep(SELF_UPDATE_IDLE_POLL).await;
                }
                append_audit_entry(
                    &handle,
                    "app.update.installing",
                    json!({ "from": update.current_version, "to": update.version }),
                );
                match update.download_and_install(|_, _| {}, || {}).await {
                    Ok(()) => handle.restart(),
                    Err(err) => log::warn!("desktop update {} failed to install: {err}", update.version),
                }
            }
            sleep(SELF_UPDATE_CHECK_EVERY).await;
        }
    });
}

fn append_audit_entry(app: &AppHandle, category: &str, details: Value) {
    let state = app.state::<OverlayAppState>();
    let Ok(_guard) = state.audit_lock.lock() else {
        return;
    };

    let entry = AuditEntry {
        timestamp: now_utc_iso(),
        category: category.to_string(),
        details,
    };

    let Ok(line) = serde_json::to_string(&entry) else {
        return;
    };

    if let Some(parent) = state.audit_log_path.parent() {
        let _ = fs::create_dir_all(parent);
    }

    if let Ok(mut file) = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&state.audit_log_path)
    {
        let _ = writeln!(file, "{line}");
    }
}

fn get_audit_tail(path: &PathBuf, limit: usize) -> Vec<AuditEntry> {
    let Ok(file) = OpenOptions::new().read(true).open(path) else {
        return Vec::new();
    };
    let reader = BufReader::new(file);
    let mut entries = Vec::new();

    for line in reader.lines().map_while(Result::ok) {
        if let Ok(entry) = serde_json::from_str::<AuditEntry>(&line) {
            entries.push(entry);
        }
    }

    if entries.len() > limit {
        entries.split_off(entries.len() - limit)
    } else {
        entries
    }
}

fn emit_settings(app: &AppHandle, settings: &OverlaySettings) {
    let _ = app.emit("overlay://settings", settings);
}

fn sample_process_memory_mb() -> Option<f64> {
    memory_stats().map(|usage| usage.physical_mem as f64 / (1024.0 * 1024.0))
}

fn refresh_performance_snapshot(app: &AppHandle) -> PerformanceSnapshot {
    let state = app.state::<OverlayAppState>();
    let mut perf = state
        .performance
        .lock()
        .expect("performance lock should not be poisoned");
    perf.sample_idle_memory();
    perf.snapshot()
}

fn current_mode_definition(app: &AppHandle) -> Option<ModeDefinition> {
    let state = app.state::<OverlayAppState>();
    let Ok(mode_state) = state.mode_state.lock() else {
        return None;
    };
    mode_state.modes.get(&mode_state.current_mode_id).cloned()
}

fn mode_allows_tool(app: &AppHandle, tool_id: &str) -> bool {
    let Some(mode) = current_mode_definition(app) else {
        return false;
    };
    mode.allowed_tools.iter().any(|tool| tool == tool_id)
}

fn is_destructive_tool(tool_id: &str) -> bool {
    matches!(
        tool_id,
        "git.commit" | "git.push" | "fs.delete" | "message.send" | "node.command" | "shell.exec"
    )
}

fn create_question(
    app: &AppHandle,
    question_id: Option<String>,
    question: String,
    mut choices: Vec<QuestionChoice>,
    source: &str,
    approval_id: Option<String>,
) -> Result<QuestionBubble, String> {
    if choices.len() < 2 || choices.len() > 4 {
        return Err("Question bubbles must contain 2-4 choices".to_string());
    }

    if choices
        .iter()
        .any(|choice| choice.choice_id.trim().is_empty())
    {
        return Err("Each question choice must have a non-empty choiceId".to_string());
    }

    if choices.iter().any(|choice| choice.label.trim().is_empty()) {
        return Err("Each question choice must have a non-empty label".to_string());
    }

    let id = question_id.unwrap_or_else(|| format!("q_{}", Uuid::new_v4().simple()));
    choices.sort_by(|a, b| a.choice_id.cmp(&b.choice_id));

    let bubble = QuestionBubble {
        question_id: id.clone(),
        question,
        choices,
        status: QuestionStatus::Pending,
        selected_choice_id: None,
        custom_answer: None,
        source: source.to_string(),
        created_at: now_utc_iso(),
        answered_at: None,
        approval_id,
    };

    {
        let state = app.state::<OverlayAppState>();
        let mut question_state = state
            .question_state
            .lock()
            .map_err(|_| "Failed to lock question state".to_string())?;
        question_state.pending.insert(id, bubble.clone());
    }

    append_audit_entry(
        app,
        "question.created",
        json!({
            "questionId": bubble.question_id,
            "source": source,
        }),
    );
    let _ = app.emit("overlay://question", bubble.clone());

    Ok(bubble)
}

fn answer_question_inner(
    app: &AppHandle,
    payload: UiAnswerPayload,
) -> Result<QuestionBubble, String> {
    let custom_answer = payload
        .custom_answer
        .as_ref()
        .map(|value| value.trim())
        .filter(|value| !value.is_empty())
        .map(|value| value.to_string());

    let bubble = {
        let state = app.state::<OverlayAppState>();
        let mut question_state = state
            .question_state
            .lock()
            .map_err(|_| "Failed to lock question state".to_string())?;

        let Some(mut bubble) = question_state.pending.remove(&payload.question_id) else {
            return Err("Question not found or already answered".to_string());
        };

        let valid_choice = bubble
            .choices
            .iter()
            .any(|choice| choice.choice_id == payload.choice_id);
        if bubble.approval_id.is_some() && !valid_choice {
            return Err("Approval questions only accept listed choices".to_string());
        }
        if !valid_choice && custom_answer.is_none() {
            return Err("Invalid choiceId".to_string());
        }

        bubble.status = QuestionStatus::Answered;
        bubble.selected_choice_id = if valid_choice {
            Some(payload.choice_id.clone())
        } else {
            Some("custom".to_string())
        };
        bubble.custom_answer = custom_answer.clone();
        bubble.answered_at = Some(now_utc_iso());
        question_state.history.push(bubble.clone());
        bubble
    };

    append_audit_entry(
        app,
        "question.answered",
        json!({
            "questionId": bubble.question_id.clone(),
            "choiceId": payload.choice_id,
            "customAnswer": bubble.custom_answer.clone(),
            "source": bubble.source.clone(),
        }),
    );
    let _ = app.emit("overlay://question_answered", bubble.clone());

    if bubble.source.starts_with("openclaw") {
        let outbound = json!({
            "type": "ui.answer",
            "questionId": bubble.question_id.clone(),
            "choiceId": bubble.selected_choice_id.clone(),
            "customAnswer": bubble.custom_answer.clone(),
        });
        if let Err(err) = queue_openclaw_payload(app, outbound) {
            append_audit_entry(
                app,
                "openclaw.ui_answer_send_failed",
                json!({
                    "questionId": bubble.question_id.clone(),
                    "error": err,
                }),
            );
        }
    }

    if let Some(approval_id) = bubble.approval_id.clone() {
        let approved = payload.choice_id == "approve"
            || payload.choice_id == "approve_once"
            || payload.choice_id == "yes";
        let resolve_payload = ResolveApprovalPayload {
            approval_id,
            approved,
        };
        tauri::async_runtime::spawn(resolve_approval_task(app.clone(), resolve_payload));
    }

    Ok(bubble)
}

fn load_openclaw_token() -> Result<Option<String>, String> {
    let entry = keyring::Entry::new(OPENCLAW_KEYRING_SERVICE, OPENCLAW_KEYRING_USER)
        .map_err(|err| format!("Failed to open secure credential store: {err}"))?;

    match entry.get_password() {
        Ok(token) => Ok(Some(token)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(err) => Err(format!("Failed to read secure credential: {err}")),
    }
}

fn save_openclaw_token(token: &str) -> Result<(), String> {
    let entry = keyring::Entry::new(OPENCLAW_KEYRING_SERVICE, OPENCLAW_KEYRING_USER)
        .map_err(|err| format!("Failed to open secure credential store: {err}"))?;
    entry
        .set_password(token)
        .map_err(|err| format!("Failed to save secure credential: {err}"))
}

fn clear_openclaw_token() -> Result<(), String> {
    let entry = keyring::Entry::new(OPENCLAW_KEYRING_SERVICE, OPENCLAW_KEYRING_USER)
        .map_err(|err| format!("Failed to open secure credential store: {err}"))?;
    match entry.delete_credential() {
        Ok(()) => Ok(()),
        Err(keyring::Error::NoEntry) => Ok(()),
        Err(err) => Err(format!("Failed to clear secure credential: {err}")),
    }
}

fn load_localhost_api_token() -> Result<Option<String>, String> {
    let entry = keyring::Entry::new(OPENCLAW_KEYRING_SERVICE, LOCALHOST_API_KEYRING_USER)
        .map_err(|err| format!("Failed to open secure credential store: {err}"))?;

    match entry.get_password() {
        Ok(token) => Ok(Some(token)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(err) => Err(format!("Failed to read secure credential: {err}")),
    }
}

fn save_localhost_api_token(token: &str) -> Result<(), String> {
    let entry = keyring::Entry::new(OPENCLAW_KEYRING_SERVICE, LOCALHOST_API_KEYRING_USER)
        .map_err(|err| format!("Failed to open secure credential store: {err}"))?;
    entry
        .set_password(token)
        .map_err(|err| format!("Failed to save secure credential: {err}"))
}

fn clear_localhost_api_token() -> Result<(), String> {
    let entry = keyring::Entry::new(OPENCLAW_KEYRING_SERVICE, LOCALHOST_API_KEYRING_USER)
        .map_err(|err| format!("Failed to open secure credential store: {err}"))?;
    match entry.delete_credential() {
        Ok(()) => Ok(()),
        Err(keyring::Error::NoEntry) => Ok(()),
        Err(err) => Err(format!("Failed to clear secure credential: {err}")),
    }
}

fn provider_keyring_user(provider_id: &str) -> Result<String, String> {
    let trimmed = provider_id.trim();
    if trimmed.is_empty() {
        return Err("Provider id cannot be empty".to_string());
    }

    if !trimmed
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_' | '.'))
    {
        return Err("Provider id must use only letters, numbers, '-', '_' or '.'".to_string());
    }

    Ok(format!(
        "{PROVIDER_KEYRING_USER_PREFIX}{}",
        trimmed.to_ascii_lowercase()
    ))
}

fn load_provider_secret(provider_id: &str) -> Result<Option<String>, String> {
    let user = provider_keyring_user(provider_id)?;
    let entry = keyring::Entry::new(OPENCLAW_KEYRING_SERVICE, &user)
        .map_err(|err| format!("Failed to open secure credential store: {err}"))?;

    match entry.get_password() {
        Ok(secret) => Ok(Some(secret)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(err) => Err(format!("Failed to read secure credential: {err}")),
    }
}

fn save_provider_secret(provider_id: &str, secret: &str) -> Result<(), String> {
    let user = provider_keyring_user(provider_id)?;
    let entry = keyring::Entry::new(OPENCLAW_KEYRING_SERVICE, &user)
        .map_err(|err| format!("Failed to open secure credential store: {err}"))?;
    entry
        .set_password(secret)
        .map_err(|err| format!("Failed to save secure credential: {err}"))
}

fn clear_provider_secret(provider_id: &str) -> Result<(), String> {
    let user = provider_keyring_user(provider_id)?;
    let entry = keyring::Entry::new(OPENCLAW_KEYRING_SERVICE, &user)
        .map_err(|err| format!("Failed to open secure credential store: {err}"))?;
    match entry.delete_credential() {
        Ok(()) => Ok(()),
        Err(keyring::Error::NoEntry) => Ok(()),
        Err(err) => Err(format!("Failed to clear secure credential: {err}")),
    }
}

fn load_openai_codex_oauth_credential() -> Result<Option<OpenAiCodexOAuthCredential>, String> {
    let entry = keyring::Entry::new(OPENCLAW_KEYRING_SERVICE, OPENAI_CODEX_OAUTH_KEYRING_USER)
        .map_err(|err| format!("Failed to open secure credential store: {err}"))?;
    match entry.get_password() {
        Ok(raw) => serde_json::from_str::<OpenAiCodexOAuthCredential>(&raw)
            .map(Some)
            .map_err(|err| format!("Failed to parse OpenAI Codex OAuth credential: {err}")),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(err) => Err(format!(
            "Failed to read OpenAI Codex OAuth credential: {err}"
        )),
    }
}

fn save_openai_codex_oauth_credential(
    credential: &OpenAiCodexOAuthCredential,
) -> Result<(), String> {
    let entry = keyring::Entry::new(OPENCLAW_KEYRING_SERVICE, OPENAI_CODEX_OAUTH_KEYRING_USER)
        .map_err(|err| format!("Failed to open secure credential store: {err}"))?;
    let raw = serde_json::to_string(credential)
        .map_err(|err| format!("Failed to serialize OpenAI Codex OAuth credential: {err}"))?;
    entry
        .set_password(&raw)
        .map_err(|err| format!("Failed to save OpenAI Codex OAuth credential: {err}"))
}

fn clear_openai_codex_oauth_credential() -> Result<(), String> {
    let entry = keyring::Entry::new(OPENCLAW_KEYRING_SERVICE, OPENAI_CODEX_OAUTH_KEYRING_USER)
        .map_err(|err| format!("Failed to open secure credential store: {err}"))?;
    match entry.delete_credential() {
        Ok(()) => Ok(()),
        Err(keyring::Error::NoEntry) => Ok(()),
        Err(err) => Err(format!(
            "Failed to clear OpenAI Codex OAuth credential: {err}"
        )),
    }
}

fn user_home_dir() -> PathBuf {
    std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

fn minimax_openclaw_credentials_path() -> PathBuf {
    user_home_dir().join(MINIMAX_OPENCLAW_CREDENTIALS_RELATIVE_PATH)
}

fn openclaw_state_dir() -> PathBuf {
    if let Some(value) = std::env::var_os("OPENCLAW_STATE_DIR") {
        let path = PathBuf::from(value);
        return if path.is_absolute() {
            path
        } else {
            user_home_dir().join(path)
        };
    }
    let home = user_home_dir();
    let new_state = home.join(".openclaw");
    if new_state.exists() {
        return new_state;
    }
    let legacy_state = home.join(".clawdbot");
    if legacy_state.exists() {
        return legacy_state;
    }
    new_state
}

fn openclaw_agent_dir() -> PathBuf {
    if let Some(value) =
        std::env::var_os("OPENCLAW_AGENT_DIR").or_else(|| std::env::var_os("PI_CODING_AGENT_DIR"))
    {
        let path = PathBuf::from(value);
        return if path.is_absolute() {
            path
        } else {
            user_home_dir().join(path)
        };
    }
    openclaw_state_dir()
        .join("agents")
        .join("main")
        .join("agent")
}

fn openclaw_auth_profile_store_path() -> PathBuf {
    openclaw_agent_dir().join("auth-profiles.json")
}

fn current_unix_millis() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as i64)
        .unwrap_or(0)
}

fn load_minimax_openclaw_oauth_credential() -> Result<Option<Value>, String> {
    let path = minimax_openclaw_credentials_path();
    if !path.is_file() {
        return Ok(None);
    }
    let raw = fs::read_to_string(&path).map_err(|error| {
        format!(
            "Failed to read MiniMax OpenClaw OAuth credentials at {}: {error}",
            path.display()
        )
    })?;
    let value = serde_json::from_str::<Value>(&raw).map_err(|error| {
        format!(
            "Failed to parse MiniMax OpenClaw OAuth credentials at {}: {error}",
            path.display()
        )
    })?;
    Ok(Some(value))
}

fn minimax_openclaw_profile_from_store() -> Result<Option<Value>, String> {
    let path = openclaw_auth_profile_store_path();
    if !path.is_file() {
        return Ok(None);
    }
    let raw = fs::read_to_string(&path).map_err(|error| {
        format!(
            "Failed to read OpenClaw auth profile store at {}: {error}",
            path.display()
        )
    })?;
    let value = serde_json::from_str::<Value>(&raw).map_err(|error| {
        format!(
            "Failed to parse OpenClaw auth profile store at {}: {error}",
            path.display()
        )
    })?;
    let profiles = value
        .get("profiles")
        .and_then(Value::as_object)
        .ok_or_else(|| {
            format!(
                "OpenClaw auth profile store at {} does not contain a profiles object.",
                path.display()
            )
        })?;
    for (profile_id, credential) in profiles {
        let provider = credential
            .get("provider")
            .and_then(Value::as_str)
            .unwrap_or("");
        let credential_type = credential.get("type").and_then(Value::as_str).unwrap_or("");
        if provider == MINIMAX_OPENCLAW_PROVIDER_ID && credential_type == "oauth" {
            let mut credential = credential.clone();
            if let Value::Object(ref mut map) = credential {
                map.insert("profileId".to_string(), Value::String(profile_id.clone()));
            }
            return Ok(Some(credential));
        }
    }
    Ok(None)
}

fn minimax_openclaw_oauth_status() -> Result<MinimaxOpenClawAuthStatus, String> {
    let credentials_path = minimax_openclaw_credentials_path();
    let auth_store_path = openclaw_auth_profile_store_path();
    let profile_credential = minimax_openclaw_profile_from_store()?;
    let external_credential = if profile_credential.is_some() {
        None
    } else {
        load_minimax_openclaw_oauth_credential()?
    };
    let (authenticated, expires, source) = if let Some(value) = profile_credential {
        let access_token = value
            .get("access")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim();
        let refresh_token = value
            .get("refresh")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim();
        (
            !access_token.is_empty() || !refresh_token.is_empty(),
            value.get("expires").and_then(Value::as_i64),
            Some("openclaw-auth-profile".to_string()),
        )
    } else {
        match external_credential {
            Some(value) => {
                let access_token = value
                    .get("access_token")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .trim();
                let refresh_token = value
                    .get("refresh_token")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .trim();
                let expires = value.get("expiry_date").and_then(Value::as_i64);
                let valid_expiry = expires
                    .map(|expiry| expiry > current_unix_millis())
                    .unwrap_or(false);
                (
                    !access_token.is_empty() && !refresh_token.is_empty() && valid_expiry,
                    expires,
                    Some("minimax-cli-credentials".to_string()),
                )
            }
            None => (false, None, None),
        }
    };
    let message = if authenticated {
        "MiniMax OpenClaw OAuth credentials are present.".to_string()
    } else {
        "MiniMax OpenClaw OAuth credentials are missing, incomplete, or expired.".to_string()
    };
    Ok(MinimaxOpenClawAuthStatus {
        authenticated,
        provider_id: MINIMAX_OPENCLAW_PROVIDER_ID.to_string(),
        region: None,
        expires,
        credentials_path: credentials_path.display().to_string(),
        auth_store_path: auth_store_path.display().to_string(),
        source,
        message,
    })
}

fn has_minimax_openclaw_oauth_credential() -> Result<bool, String> {
    Ok(minimax_openclaw_oauth_status()?.authenticated)
}

fn provider_secret_for_ids(provider_ids: &[&str]) -> Result<Option<String>, String> {
    for provider_id in provider_ids {
        if let Some(secret) = load_provider_secret(provider_id)? {
            return Ok(Some(secret));
        }
    }
    Ok(None)
}

fn provider_secret_presence_snapshot(provider_ids: &[&str]) -> Result<Value, String> {
    let mut output = serde_json::Map::new();
    for provider_id in provider_ids {
        let has_secret = if *provider_id == "openai-codex" {
            load_provider_secret(provider_id)?.is_some()
                || load_openai_codex_oauth_credential()?.is_some()
        } else if *provider_id == MINIMAX_OPENCLAW_PROVIDER_ID {
            load_provider_secret(provider_id)?.is_some() || has_minimax_openclaw_oauth_credential()?
        } else {
            load_provider_secret(provider_id)?.is_some()
        };
        output.insert((*provider_id).to_string(), Value::Bool(has_secret));
    }
    Ok(Value::Object(output))
}

fn inject_agent_cli_provider_env(
    app: &AppHandle,
    command: &mut TokioCommand,
) -> Result<(), String> {
    for (env_name, provider_ids) in AGENT_PROVIDER_ENV_MAPPINGS {
        if let Some(secret) = provider_secret_for_ids(provider_ids)? {
            command.env(env_name, secret);
        }
    }
    if load_openai_codex_oauth_credential()?.is_some() {
        command.env("FLUXIO_OPENAI_CODEX_OAUTH_PRESENT", "1");
    }
    if has_minimax_openclaw_oauth_credential()? {
        command.env("FLUXIO_MINIMAX_OPENCLAW_OAUTH_PRESENT", "1");
    }
    let app_data_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("Failed to resolve application data directory: {error}"))?;
    fs::create_dir_all(&app_data_dir)
        .map_err(|error| format!("Failed to create application data directory: {error}"))?;
    command.env(
        "NEYVIA_AGENT_PROMPT_FILE",
        app_data_dir.join("agent_prompts.json"),
    );
    Ok(())
}

fn inject_agent_cli_pythonpath(command: &mut TokioCommand, workspace_root: &Path) {
    let source_root = if base_pack_bridge::enabled() {
        runtime_env::bundled_backend_root().unwrap_or_else(||workspace_root.to_path_buf()).join("src")
    } else { workspace_root.join("src") };
    if !source_root.is_dir() {
        return;
    }

    let mut pythonpath = OsString::from(source_root.as_os_str());
    if let Some(existing) = std::env::var_os("PYTHONPATH").filter(|_|!base_pack_bridge::enabled()) {
        if !existing.is_empty() {
            let separator = if cfg!(windows) { ";" } else { ":" };
            pythonpath.push(separator);
            pythonpath.push(existing);
        }
    }

    command.env("PYTHONPATH", pythonpath);
}

fn load_telegram_bot_token() -> Result<Option<String>, String> {
    let entry = keyring::Entry::new(OPENCLAW_KEYRING_SERVICE, TELEGRAM_BOT_KEYRING_USER)
        .map_err(|err| format!("Failed to open secure credential store: {err}"))?;

    match entry.get_password() {
        Ok(token) => Ok(Some(token)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(err) => Err(format!("Failed to read secure credential: {err}")),
    }
}

fn save_telegram_bot_token(token: &str) -> Result<(), String> {
    let entry = keyring::Entry::new(OPENCLAW_KEYRING_SERVICE, TELEGRAM_BOT_KEYRING_USER)
        .map_err(|err| format!("Failed to open secure credential store: {err}"))?;
    entry
        .set_password(token)
        .map_err(|err| format!("Failed to save secure credential: {err}"))
}

fn clear_telegram_bot_token() -> Result<(), String> {
    let entry = keyring::Entry::new(OPENCLAW_KEYRING_SERVICE, TELEGRAM_BOT_KEYRING_USER)
        .map_err(|err| format!("Failed to open secure credential store: {err}"))?;
    match entry.delete_credential() {
        Ok(()) => Ok(()),
        Err(keyring::Error::NoEntry) => Ok(()),
        Err(err) => Err(format!("Failed to clear secure credential: {err}")),
    }
}

async fn send_telegram_message(chat_id: &str, text: &str) -> Result<Value, String> {
    let token = load_telegram_bot_token()?
        .ok_or_else(|| "Telegram bot token is not configured.".to_string())?;
    let url = format!("https://api.telegram.org/bot{token}/sendMessage");
    let client = reqwest::Client::new();
    let response = client
        .post(url)
        .json(&json!({
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": true,
        }))
        .send()
        .await
        .map_err(|err| format!("Failed to reach Telegram API: {err}"))?;
    let status = response.status();
    let body: Value = response
        .json()
        .await
        .map_err(|err| format!("Failed to parse Telegram API response: {err}"))?;
    if !status.is_success() {
        return Err(format!("Telegram API error {}: {}", status, body));
    }
    Ok(body)
}

fn parse_bearer_token(header_value: &str) -> Option<&str> {
    let (scheme, token) = header_value.split_once(' ')?;
    if !scheme.eq_ignore_ascii_case("bearer") {
        return None;
    }
    let trimmed = token.trim();
    if trimmed.is_empty() {
        return None;
    }
    Some(trimmed)
}

fn validate_local_api_auth(headers: &HeaderMap) -> Result<bool, String> {
    let expected_token = load_localhost_api_token()?;
    let Some(expected_token) = expected_token else {
        return Ok(true);
    };

    let provided = headers
        .get(AUTHORIZATION)
        .and_then(|raw| raw.to_str().ok())
        .and_then(parse_bearer_token);

    Ok(matches!(provided, Some(token) if token == expected_token))
}

fn set_mode_inner(app: &AppHandle, mode_id: &str, source: &str) -> Result<ModeDefinition, String> {
    let mode = {
        let state = app.state::<OverlayAppState>();
        let mut mode_state = state
            .mode_state
            .lock()
            .map_err(|_| "Failed to lock mode state".to_string())?;
        let Some(mode) = mode_state.modes.get(mode_id).cloned() else {
            return Err(format!("Unknown mode '{mode_id}'"));
        };
        mode_state.current_mode_id = mode_id.to_string();
        mode
    };

    {
        let state = app.state::<OverlayAppState>();
        let mut settings = state
            .settings
            .lock()
            .map_err(|_| "Failed to write settings".to_string())?;
        settings.mode_id = mode_id.to_string();
        save_settings(&state.settings_path, &settings)?;
        emit_settings(app, &settings);
    }

    append_audit_entry(
        app,
        "mode.changed",
        json!({
            "modeId": mode_id,
            "source": source,
        }),
    );
    let _ = app.emit("overlay://mode", mode.clone());
    Ok(mode)
}

fn capture_context_inner(
    app: &AppHandle,
    request: ContextCaptureRequest,
) -> Result<ContextCaptureResult, String> {
    let mut warnings = Vec::new();

    let clipboard_text = if request.clipboard {
        match Clipboard::new().and_then(|mut cb| cb.get_text()) {
            Ok(text) => Some(text),
            Err(err) => {
                warnings.push(format!("Clipboard capture failed: {err}"));
                None
            }
        }
    } else {
        None
    };

    let active_window = if request.active_window {
        match get_active_window() {
            Ok(raw) => Some(ActiveWindowMetadata {
                title: raw.title,
                app_name: raw.app_name,
                process_id: raw.process_id,
                process_path: raw.process_path.to_string_lossy().to_string(),
                window_id: raw.window_id,
            }),
            Err(_) => {
                warnings.push("Active window metadata is unavailable on this system.".to_string());
                None
            }
        }
    } else {
        None
    };

    let screenshot_path = if request.screenshot {
        warnings.push(
            "Screenshot capture is gated and currently requires explicit UI-provided path."
                .to_string(),
        );
        None
    } else {
        None
    };

    let result = ContextCaptureResult {
        captured_at: now_utc_iso(),
        clipboard_text,
        active_window,
        screenshot_path,
        warnings,
    };

    append_audit_entry(
        app,
        "context.captured",
        json!({
            "clipboard": request.clipboard,
            "activeWindow": request.active_window,
            "screenshot": request.screenshot,
            "warnings": result.warnings,
        }),
    );
    let _ = app.emit("overlay://context", result.clone());

    Ok(result)
}

async fn run_local_stt_command(
    config: &DictationConfig,
    audio_path: &str,
) -> Result<String, String> {
    let Some(command_name) = config.local_stt_command.clone() else {
        return Err("Local STT command is not configured".to_string());
    };

    let mut cmd = TokioCommand::new(command_name);
    hide_child_console(&mut cmd);
    let args: Vec<String> = config
        .local_stt_args
        .iter()
        .map(|arg| arg.replace("{audio}", audio_path))
        .collect();
    cmd.args(args);

    let output = timeout(
        Duration::from_secs(config.local_stt_timeout_seconds),
        cmd.output(),
    )
    .await
    .map_err(|_| "Local STT command timed out".to_string())
    .and_then(|result| result.map_err(|err| format!("Failed to run local STT command: {err}")))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("Local STT command failed: {}", stderr.trim()));
    }

    let transcript = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if transcript.is_empty() {
        return Err("Local STT command returned empty transcript".to_string());
    }

    Ok(transcript)
}

fn update_openclaw_status(app: &AppHandle, mutator: impl FnOnce(&mut OpenClawStatus)) {
    let state = app.state::<OverlayAppState>();
    let mut guard = match state.openclaw_state.lock() {
        Ok(guard) => guard,
        Err(_) => return,
    };
    mutator(&mut guard.status);
    let _ = app.emit("openclaw://status", guard.status.clone());
}

fn approval_status_label(status: &ApprovalStatus) -> &'static str {
    match status {
        ApprovalStatus::Pending => "pending",
        ApprovalStatus::Approved => "approved",
        ApprovalStatus::Rejected => "rejected",
        ApprovalStatus::Denied => "denied",
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum OpenClawSendState {
    Sent,
    Queued,
}

fn emit_openclaw_status_snapshot(app: &AppHandle) {
    let state = app.state::<OverlayAppState>();
    let status = match state.openclaw_state.lock() {
        Ok(openclaw) => openclaw.status.clone(),
        Err(_) => return,
    };
    let _ = app.emit("openclaw://status", status);
}

fn sha256_hex(text: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(text.as_bytes());
    let digest = hasher.finalize();
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn with_openclaw_envelope(payload: Value) -> Value {
    let Value::Object(mut object) = payload else {
        return payload;
    };

    let payload_type = object
        .get("type")
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        .to_string();
    if payload_type == "ack" {
        return Value::Object(object);
    }

    object
        .entry("messageId")
        .or_insert_with(|| Value::String(format!("msg_{}", Uuid::new_v4().simple())));
    object
        .entry("nonce")
        .or_insert_with(|| Value::String(format!("nonce_{}", Uuid::new_v4().simple())));
    object
        .entry("sentAt")
        .or_insert_with(|| Value::String(now_utc_iso()));
    object
        .entry("ackRequested")
        .or_insert_with(|| Value::Bool(true));

    let mut integrity_payload = object.clone();
    integrity_payload.remove("integrity");
    let integrity = sha256_hex(&Value::Object(integrity_payload).to_string());
    object.insert("integrity".to_string(), Value::String(integrity));
    Value::Object(object)
}

fn parse_outbound_ack_fields(payload_text: &str) -> Option<(String, bool)> {
    let parsed = serde_json::from_str::<Value>(payload_text).ok()?;
    let payload_type = parsed
        .get("type")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    if payload_type == "auth" || payload_type == "ack" {
        return None;
    }

    let message_id = parsed
        .get("messageId")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())?
        .to_string();
    let ack_requested = parsed
        .get("ackRequested")
        .and_then(Value::as_bool)
        .unwrap_or(true);
    Some((message_id, ack_requested))
}

fn register_pending_ack_from_payload(app: &AppHandle, payload_text: &str) {
    let Some((message_id, ack_requested)) = parse_outbound_ack_fields(payload_text) else {
        return;
    };
    if !ack_requested {
        return;
    }

    let dropped = {
        let state = app.state::<OverlayAppState>();
        let mut openclaw = match state.openclaw_state.lock() {
            Ok(openclaw) => openclaw,
            Err(_) => return,
        };
        openclaw.register_pending_ack(message_id.clone(), payload_text.to_string())
    };

    if dropped {
        append_audit_entry(
            app,
            "openclaw.pending_ack_overflow",
            json!({
                "maxPendingAcks": OPENCLAW_MAX_PENDING_ACKS,
            }),
        );
    }
    emit_openclaw_status_snapshot(app);
}

fn acknowledge_pending_ack(app: &AppHandle, message_id: &str) -> bool {
    let acknowledged = {
        let state = app.state::<OverlayAppState>();
        let mut openclaw = match state.openclaw_state.lock() {
            Ok(openclaw) => openclaw,
            Err(_) => return false,
        };
        openclaw.acknowledge_pending_ack(message_id)
    };

    if acknowledged {
        emit_openclaw_status_snapshot(app);
    }
    acknowledged
}

fn queue_openclaw_payload(app: &AppHandle, payload: Value) -> Result<OpenClawSendState, String> {
    let payload = with_openclaw_envelope(payload);
    let payload_type = payload
        .get("type")
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        .to_string();
    let payload_text = payload.to_string();

    let mut dropped_oldest = false;
    let mut queued_outbound = 0_usize;
    let mut queue_reason: Option<&str> = None;

    let tx = {
        let state = app.state::<OverlayAppState>();
        let mut openclaw = state
            .openclaw_state
            .lock()
            .map_err(|_| "Failed to lock OpenClaw state".to_string())?;
        match openclaw.outbound_tx.clone() {
            Some(tx) => Some(tx),
            None => {
                dropped_oldest = openclaw.push_pending_outbound(payload_text.clone(), false);
                queued_outbound = openclaw.status.queued_outbound;
                queue_reason = Some("disconnected");
                None
            }
        }
    };

    if let Some(tx) = tx {
        if tx.send(payload_text.clone()).is_ok() {
            return Ok(OpenClawSendState::Sent);
        }

        let state = app.state::<OverlayAppState>();
        let mut openclaw = state
            .openclaw_state
            .lock()
            .map_err(|_| "Failed to lock OpenClaw state".to_string())?;
        dropped_oldest = openclaw.push_pending_outbound(payload_text, false) || dropped_oldest;
        queued_outbound = openclaw.status.queued_outbound;
        queue_reason = Some("channel_closed");
    }

    if let Some(reason) = queue_reason {
        if dropped_oldest {
            append_audit_entry(
                app,
                "openclaw.queue_overflow",
                json!({
                    "maxPendingOutbound": OPENCLAW_MAX_PENDING_OUTBOUND,
                    "payloadType": payload_type,
                }),
            );
        }

        append_audit_entry(
            app,
            "openclaw.payload_queued",
            json!({
                "payloadType": payload_type,
                "reason": reason,
                "queuedOutbound": queued_outbound,
            }),
        );
        emit_openclaw_status_snapshot(app);
        return Ok(OpenClawSendState::Queued);
    }

    Err("Unable to queue OpenClaw payload".to_string())
}

fn send_openclaw_action_result(app: &AppHandle, outcome: &ActionRequestOutcome, source: &str) {
    let payload = json!({
        "type": "action.result",
        "requestId": outcome.gateway_request_id.clone().unwrap_or_else(|| outcome.request_id.clone()),
        "localRequestId": outcome.request_id.clone(),
        "status": approval_status_label(&outcome.status),
        "approvalId": outcome.approval_id.clone(),
        "questionId": outcome.question_id.clone(),
        "reason": outcome.reason.clone(),
        "output": outcome.output.clone(),
        "source": source,
    });

    match queue_openclaw_payload(app, payload) {
        Ok(OpenClawSendState::Sent) => {
            append_audit_entry(
                app,
                "openclaw.action_result_sent",
                json!({
                    "requestId": outcome.request_id,
                    "gatewayRequestId": outcome.gateway_request_id.clone(),
                    "status": approval_status_label(&outcome.status),
                }),
            );
        }
        Ok(OpenClawSendState::Queued) => {
            append_audit_entry(
                app,
                "openclaw.action_result_queued",
                json!({
                    "requestId": outcome.request_id,
                    "gatewayRequestId": outcome.gateway_request_id.clone(),
                    "status": approval_status_label(&outcome.status),
                }),
            );
        }
        Err(err) => {
            append_audit_entry(
                app,
                "openclaw.action_result_send_failed",
                json!({
                    "requestId": outcome.request_id,
                    "gatewayRequestId": outcome.gateway_request_id.clone(),
                    "status": approval_status_label(&outcome.status),
                    "error": err,
                }),
            );
        }
    }
}

fn set_pinned_state(
    app: &AppHandle,
    pinned: bool,
    source: &str,
) -> Result<OverlaySettings, String> {
    let state = app.state::<OverlayAppState>();

    let updated_settings = {
        let mut settings = state
            .settings
            .lock()
            .map_err(|_| "Failed to write settings".to_string())?;

        settings.pinned = pinned;
        let clone = settings.clone();
        save_settings(&state.settings_path, &clone)?;
        clone
    };

    log::info!(
        "pin state updated from {source}: {}",
        updated_settings.pinned
    );
    emit_settings(app, &updated_settings);

    if !updated_settings.pinned && !state.space_is_held.load(Ordering::SeqCst) {
        let _ = hide_overlay(app, "unpinned");
    }

    append_audit_entry(
        app,
        "overlay.pin",
        json!({
            "pinned": updated_settings.pinned,
            "source": source,
        }),
    );

    Ok(updated_settings)
}

fn update_hotkey_name(app: &AppHandle, hotkey_name: &str) {
    let state = app.state::<OverlayAppState>();
    let Ok(mut settings) = state.settings.lock() else {
        return;
    };

    settings.hotkey = hotkey_name.to_string();
    let clone = settings.clone();
    let _ = save_settings(&state.settings_path, &clone);
    emit_settings(app, &clone);
}

fn position_overlay_window(window: &tauri::WebviewWindow) -> Result<(), String> {
    let current_monitor = window
        .current_monitor()
        .map_err(|err| format!("Failed to resolve active monitor: {err}"))?;
    let fallback_monitor = window
        .primary_monitor()
        .map_err(|err| format!("Failed to resolve primary monitor: {err}"))?;

    let Some(monitor) = current_monitor.or(fallback_monitor) else {
        return Ok(());
    };

    let monitor_pos = monitor.position();
    let monitor_size = monitor.size();
    let window_size = window
        .outer_size()
        .map_err(|err| format!("Failed to read overlay size: {err}"))?;

    let centered_x = monitor_pos.x + ((monitor_size.width as i32 - window_size.width as i32) / 2);
    let centered_y = monitor_pos.y + ((monitor_size.height as i32 - window_size.height as i32) / 2);

    window
        .set_position(Position::Physical(PhysicalPosition::new(
            centered_x, centered_y,
        )))
        .map_err(|err| format!("Failed to position overlay: {err}"))
}

fn open_overlay(app: &AppHandle, source: &str) -> Result<(), String> {
    let Some(window) = app.get_webview_window(MAIN_WINDOW_LABEL) else {
        return Err("Overlay window was not found".to_string());
    };

    position_overlay_window(&window)?;
    window
        .show()
        .map_err(|err| format!("Failed to show overlay: {err}"))?;
    let _ = window.unminimize();
    window
        .set_focus()
        .map_err(|err| format!("Failed to focus overlay: {err}"))?;

    {
        let state = app.state::<OverlayAppState>();
        let mut perf = state
            .performance
            .lock()
            .map_err(|_| "Failed to update performance stats".to_string())?;
        perf.finish_hotkey_open();
    }

    append_audit_entry(app, "overlay.open", json!({ "source": source }));
    let _ = app.emit(
        "overlay://visibility",
        json!({
            "visible": true,
            "source": source,
        }),
    );

    Ok(())
}

fn hide_overlay(app: &AppHandle, source: &str) -> Result<(), String> {
    let Some(window) = app.get_webview_window(MAIN_WINDOW_LABEL) else {
        return Err("Overlay window was not found".to_string());
    };

    window
        .hide()
        .map_err(|err| format!("Failed to hide overlay: {err}"))?;
    append_audit_entry(app, "overlay.close", json!({ "source": source }));
    let _ = app.emit(
        "overlay://visibility",
        json!({
            "visible": false,
            "source": source,
        }),
    );

    Ok(())
}

fn on_hold_shortcut_event(app: &AppHandle, event: ShortcutEvent) {
    match event.state {
        ShortcutState::Pressed => {
            let state = app.state::<OverlayAppState>();
            if state.space_is_held.swap(true, Ordering::SeqCst) {
                return;
            }

            if let Ok(mut perf) = state.performance.lock() {
                perf.begin_hotkey_open();
            }

            if let Err(err) = open_overlay(app, "hold-shortcut") {
                log::error!("failed to open overlay on hold press: {err}");
            }
        }
        ShortcutState::Released => {
            let state = app.state::<OverlayAppState>();
            state.space_is_held.store(false, Ordering::SeqCst);

            let is_pinned = state
                .settings
                .lock()
                .map(|settings| settings.pinned)
                .unwrap_or(false);
            if !is_pinned {
                let _ = hide_overlay(app, "shortcut-release");
            }
        }
    }
}

fn register_hold_shortcut(app: &AppHandle) -> Result<(), String> {
    let primary_shortcut = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::Space);
    let primary_result = app
        .global_shortcut()
        .on_shortcut(primary_shortcut, |app, _shortcut, event| {
            on_hold_shortcut_event(app, event)
        });

    if primary_result.is_ok() {
        update_hotkey_name(app, "Ctrl+Shift+Space");
        return Ok(());
    }

    let fallback_shortcut = Shortcut::new(Some(Modifiers::ALT | Modifiers::SHIFT), Code::Space);
    app.global_shortcut()
        .on_shortcut(fallback_shortcut, |app, _shortcut, event| {
            on_hold_shortcut_event(app, event)
        })
        .map_err(|err| {
            format!("Failed to register Ctrl+Shift+Space and Alt+Shift+Space shortcuts: {err}")
        })?;

    update_hotkey_name(app, "Alt+Shift+Space (fallback)");
    Ok(())
}

fn configure_overlay_window(app: &AppHandle) {
    let Some(window) = app.get_webview_window(MAIN_WINDOW_LABEL) else {
        return;
    };
    let _ = position_overlay_window(&window);
}

fn should_run_night_mode(config: &NightModeConfig) -> bool {
    if !config.enabled {
        return false;
    }

    let hour = Local::now().hour() as u8;
    if config.start_hour <= config.end_hour {
        hour >= config.start_hour && hour < config.end_hour
    } else {
        hour >= config.start_hour || hour < config.end_hour
    }
}

async fn run_night_mode_cycle(app: &AppHandle, source: &str) -> Result<NightModeReport, String> {
    let pending_approvals = {
        let state = app.state::<OverlayAppState>();
        let count = state
            .approval_state
            .lock()
            .map_err(|_| "Failed to lock approval state".to_string())?
            .pending
            .len();
        count
    };

    let pending_questions = {
        let state = app.state::<OverlayAppState>();
        let count = state
            .question_state
            .lock()
            .map_err(|_| "Failed to lock question state".to_string())?
            .pending
            .len();
        count
    };

    let mut safe_tasks = vec![
        "index_workspace_metadata".to_string(),
        "summarize_pending_questions".to_string(),
        "prepare_patch_plan".to_string(),
    ];

    let mut proposals = vec![
        format!("Pending approvals: {pending_approvals}"),
        format!("Pending question bubbles: {pending_questions}"),
        "No destructive actions executed. Night mode only proposes safe work.".to_string(),
    ];

    let mode_id = current_mode_definition(app)
        .map(|mode| mode.id)
        .unwrap_or_else(|| "coding".to_string());
    proposals.push(format!("Current mode snapshot: {mode_id}"));

    let report = NightModeReport {
        run_id: format!("night_{}", Uuid::new_v4().simple()),
        source: source.to_string(),
        ran_at: now_utc_iso(),
        safe_tasks: std::mem::take(&mut safe_tasks),
        proposals,
    };

    {
        let state = app.state::<OverlayAppState>();
        let mut night_state = state
            .night_mode_state
            .lock()
            .map_err(|_| "Failed to lock night mode state".to_string())?;
        night_state.last_report = Some(report.clone());
    }

    append_audit_entry(
        app,
        "night_mode.run",
        json!({
            "source": report.source,
            "runId": report.run_id,
            "safeTasks": report.safe_tasks,
        }),
    );
    let _ = app.emit("night-mode://report", report.clone());

    Ok(report)
}

fn start_night_mode_scheduler(app: &AppHandle) {
    let state = app.state::<OverlayAppState>();
    if state.night_mode_started.swap(true, Ordering::SeqCst) {
        return;
    }

    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        loop {
            sleep(Duration::from_secs(NIGHT_MODE_LOOP_SECONDS)).await;

            let config = {
                let state = app_handle.state::<OverlayAppState>();
                let config = match state.night_mode_state.lock() {
                    Ok(guard) => guard.config.clone(),
                    Err(_) => continue,
                };
                config
            };

            if should_run_night_mode(&config) {
                let _ = run_night_mode_cycle(&app_handle, "scheduled").await;
            }
        }
    });
}

async fn execute_node_command(app: &AppHandle, args: NodeCommandArgs) -> Result<Value, String> {
    let allowlisted = {
        let state = app.state::<OverlayAppState>();
        let openclaw = state
            .openclaw_state
            .lock()
            .map_err(|_| "Failed to lock OpenClaw state".to_string())?;
        openclaw
            .config
            .allowlisted_node_commands
            .iter()
            .cloned()
            .collect::<HashSet<_>>()
    };

    if !allowlisted.contains(&args.command) {
        return Err(format!(
            "Command '{}' is not allowlisted. Exact match required.",
            args.command
        ));
    }

    let mut command = TokioCommand::new(&args.command);
    hide_child_console(&mut command);
    command.args(args.args.clone());

    if let Some(cwd) = args.cwd {
        command.current_dir(cwd);
    }

    let timeout_secs = args.timeout_seconds.unwrap_or(20);
    let output = timeout(Duration::from_secs(timeout_secs), command.output())
        .await
        .map_err(|_| "Node command timed out".to_string())
        .and_then(|result| {
            result.map_err(|err| format!("Failed to execute node command: {err}"))
        })?;

    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();

    Ok(json!({
        "command": args.command,
        "args": args.args,
        "success": output.status.success(),
        "statusCode": output.status.code(),
        "stdout": stdout,
        "stderr": stderr,
    }))
}

async fn execute_tool_request(
    app: &AppHandle,
    request: &ActionRequestPayload,
) -> Result<Value, String> {
    match request.tool_id.as_str() {
        "tool.safe.echo" => Ok(json!({ "echo": request.args })),
        "tool.safe.now" => Ok(json!({ "now": now_utc_iso() })),
        "context.capture" => {
            let request_payload: ContextCaptureRequest =
                serde_json::from_value(request.args.clone())
                    .map_err(|err| format!("Invalid context capture args: {err}"))?;
            let result = capture_context_inner(app, request_payload)?;
            Ok(serde_json::to_value(result).unwrap_or_else(|_| json!({})))
        }
        "node.command" => {
            let args: NodeCommandArgs = serde_json::from_value(request.args.clone())
                .map_err(|err| format!("Invalid node command args: {err}"))?;
            execute_node_command(app, args).await
        }
        _ => Err(format!("Unsupported tool '{}'.", request.tool_id)),
    }
}

fn create_approval_question(
    app: &AppHandle,
    approval_id: &str,
    tool_id: &str,
) -> Result<QuestionBubble, String> {
    create_question(
        app,
        None,
        format!("Approve execution for high-risk tool '{}' ?", tool_id),
        vec![
            QuestionChoice {
                choice_id: "approve".to_string(),
                label: "Approve once".to_string(),
            },
            QuestionChoice {
                choice_id: "reject".to_string(),
                label: "Reject".to_string(),
            },
            QuestionChoice {
                choice_id: "ask_later".to_string(),
                label: "Ask later".to_string(),
            },
        ],
        "approval",
        Some(approval_id.to_string()),
    )
}

async fn request_action_inner(
    app: &AppHandle,
    request: ActionRequestPayload,
) -> Result<ActionRequestOutcome, String> {
    let gateway_request_id = request.request_id.clone();
    let request_id = format!("req_{}", Uuid::new_v4().simple());
    let source = request
        .source
        .clone()
        .unwrap_or_else(|| "agent".to_string());

    if !mode_allows_tool(app, &request.tool_id) {
        append_audit_entry(
            app,
            "action.denied",
            json!({
                "requestId": request_id,
                "gatewayRequestId": gateway_request_id,
                "toolId": request.tool_id,
                "source": source,
                "reason": "Mode tool allowlist denied",
            }),
        );

        return Ok(ActionRequestOutcome {
            request_id,
            gateway_request_id,
            status: ApprovalStatus::Denied,
            approval_id: None,
            question_id: None,
            output: None,
            reason: Some("Current mode does not allow this tool.".to_string()),
        });
    }

    if is_destructive_tool(&request.tool_id) {
        let approval_id = format!("appr_{}", Uuid::new_v4().simple());
        let question = create_approval_question(app, &approval_id, &request.tool_id)?;

        let record = ActionApprovalRecord {
            approval_id: approval_id.clone(),
            request_id: request_id.clone(),
            gateway_request_id: gateway_request_id.clone(),
            tool_id: request.tool_id.clone(),
            args: request.args.clone(),
            status: ApprovalStatus::Pending,
            reason: None,
            question_id: Some(question.question_id.clone()),
            output: None,
            source: source.clone(),
            requested_at: now_utc_iso(),
            resolved_at: None,
        };

        {
            let state = app.state::<OverlayAppState>();
            let mut approval_state = state
                .approval_state
                .lock()
                .map_err(|_| "Failed to lock approval state".to_string())?;
            approval_state
                .pending
                .insert(approval_id.clone(), record.clone());
        }

        append_audit_entry(
            app,
            "action.pending_approval",
            json!({
                "requestId": request_id,
                "gatewayRequestId": gateway_request_id,
                "approvalId": approval_id,
                "toolId": request.tool_id,
                "source": source,
            }),
        );

        return Ok(ActionRequestOutcome {
            request_id,
            gateway_request_id,
            status: ApprovalStatus::Pending,
            approval_id: Some(approval_id),
            question_id: Some(question.question_id),
            output: None,
            reason: Some("High-risk tool requires explicit approval.".to_string()),
        });
    }

    let output = execute_tool_request(app, &request).await?;
    append_audit_entry(
        app,
        "action.executed",
        json!({
            "requestId": request_id,
            "gatewayRequestId": gateway_request_id,
            "toolId": request.tool_id,
            "source": source,
        }),
    );

    Ok(ActionRequestOutcome {
        request_id,
        gateway_request_id,
        status: ApprovalStatus::Approved,
        approval_id: None,
        question_id: None,
        output: Some(output),
        reason: None,
    })
}

async fn resolve_approval_task(app: AppHandle, payload: ResolveApprovalPayload) {
    let result = resolve_approval_inner(&app, payload).await;
    if let Err(err) = result {
        log::error!("failed to resolve approval from question response: {err}");
    }
}

async fn resolve_approval_inner(
    app: &AppHandle,
    payload: ResolveApprovalPayload,
) -> Result<ActionApprovalRecord, String> {
    let mut record = {
        let state = app.state::<OverlayAppState>();
        let mut approval_state = state
            .approval_state
            .lock()
            .map_err(|_| "Failed to lock approval state".to_string())?;

        let Some(record) = approval_state.pending.remove(&payload.approval_id) else {
            return Err("Approval request not found".to_string());
        };
        record
    };

    if !payload.approved {
        record.status = ApprovalStatus::Rejected;
        record.reason = Some("User rejected approval".to_string());
        record.resolved_at = Some(now_utc_iso());
    } else {
        let request = ActionRequestPayload {
            request_id: record.gateway_request_id.clone(),
            tool_id: record.tool_id.clone(),
            args: record.args.clone(),
            source: Some(record.source.clone()),
        };

        match execute_tool_request(app, &request).await {
            Ok(output) => {
                record.status = ApprovalStatus::Approved;
                record.output = Some(output);
                record.resolved_at = Some(now_utc_iso());
            }
            Err(err) => {
                record.status = ApprovalStatus::Denied;
                record.reason = Some(err);
                record.resolved_at = Some(now_utc_iso());
            }
        }
    }

    {
        let state = app.state::<OverlayAppState>();
        let mut approval_state = state
            .approval_state
            .lock()
            .map_err(|_| "Failed to lock approval state".to_string())?;
        approval_state.history.push(record.clone());
    }

    append_audit_entry(
        app,
        "action.approval_resolved",
        json!({
            "approvalId": record.approval_id,
            "gatewayRequestId": record.gateway_request_id,
            "status": format!("{:?}", record.status),
            "toolId": record.tool_id,
        }),
    );
    let _ = app.emit("overlay://approval", record.clone());

    if record.source.starts_with("openclaw") {
        let outcome = ActionRequestOutcome {
            request_id: record.request_id.clone(),
            gateway_request_id: record.gateway_request_id.clone(),
            status: record.status.clone(),
            approval_id: Some(record.approval_id.clone()),
            question_id: record.question_id.clone(),
            output: record.output.clone(),
            reason: record.reason.clone(),
        };
        send_openclaw_action_result(app, &outcome, "approval_resolution");
    }

    Ok(record)
}

async fn start_localhost_api(app: &AppHandle) -> Result<(), String> {
    let state = app.state::<OverlayAppState>();
    if state.localhost_started.swap(true, Ordering::SeqCst) {
        return Ok(());
    }

    let status = {
        let guard = state
            .localhost_status
            .lock()
            .map_err(|_| "Failed to lock localhost status".to_string())?;
        guard.clone()
    };

    if !status.enabled {
        return Ok(());
    }

    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        let listener = match TcpListener::bind(("127.0.0.1", status.port)).await {
            Ok(listener) => listener,
            Err(err) => {
                let state = app_handle.state::<OverlayAppState>();
                if let Ok(mut local_status) = state.localhost_status.lock() {
                    local_status.running = false;
                    local_status.last_error = Some(err.to_string());
                };
                append_audit_entry(
                    &app_handle,
                    "localhost.error",
                    json!({ "error": err.to_string() }),
                );
                return;
            }
        };

        {
            let state = app_handle.state::<OverlayAppState>();
            if let Ok(mut local_status) = state.localhost_status.lock() {
                local_status.running = true;
                local_status.last_error = None;
            };
        }

        append_audit_entry(
            &app_handle,
            "localhost.started",
            json!({ "port": status.port }),
        );

        let router = Router::new()
            .route("/health", get(local_api_health))
            .route("/v1/state", get(local_api_state))
            .route("/v1/command", post(local_api_command))
            .with_state(LocalApiState {
                app: app_handle.clone(),
            });

        let serve_result = axum::serve(listener, router).await;
        if let Err(err) = serve_result {
            let state = app_handle.state::<OverlayAppState>();
            if let Ok(mut local_status) = state.localhost_status.lock() {
                local_status.running = false;
                local_status.last_error = Some(err.to_string());
            };
            append_audit_entry(
                &app_handle,
                "localhost.error",
                json!({ "error": err.to_string() }),
            );
        }
    });

    Ok(())
}

async fn local_api_health() -> Json<Value> {
    Json(json!({ "ok": true }))
}

async fn local_api_state(
    headers: HeaderMap,
    AxumState(state): AxumState<LocalApiState>,
) -> (StatusCode, Json<Value>) {
    match validate_local_api_auth(&headers) {
        Ok(true) => {}
        Ok(false) => {
            append_audit_entry(
                &state.app,
                "localhost.unauthorized",
                json!({ "route": "/v1/state" }),
            );
            return (
                StatusCode::UNAUTHORIZED,
                Json(json!({ "ok": false, "error": "Unauthorized" })),
            );
        }
        Err(err) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({ "ok": false, "error": err })),
            );
        }
    }

    match build_overlay_state_snapshot(&state.app) {
        Ok(snapshot) => (StatusCode::OK, Json(json!(snapshot))),
        Err(_) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!(OverlayStateSnapshot {
                settings: OverlaySettings::default(),
                performance: PerformanceSnapshot {
                    cold_start_ms: None,
                    last_hotkey_latency_ms: None,
                    average_hotkey_latency_ms: None,
                    hotkey_samples: 0,
                    idle_ram_mb: None,
                },
                current_mode: None,
                openclaw_status: OpenClawStatus::default(),
                localhost_status: LocalhostStatus::new(false, DEFAULT_LOCALHOST_PORT),
                night_mode: NightModeConfig::default(),
            })),
        ),
    }
}

async fn local_api_command(
    headers: HeaderMap,
    AxumState(state): AxumState<LocalApiState>,
    Json(command): Json<ControlCommand>,
) -> (StatusCode, Json<ControlCommandResponse>) {
    match validate_local_api_auth(&headers) {
        Ok(true) => {}
        Ok(false) => {
            append_audit_entry(
                &state.app,
                "localhost.unauthorized",
                json!({ "route": "/v1/command" }),
            );
            return (
                StatusCode::UNAUTHORIZED,
                Json(ControlCommandResponse {
                    ok: false,
                    data: json!({}),
                    error: Some("Unauthorized".to_string()),
                }),
            );
        }
        Err(err) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(ControlCommandResponse {
                    ok: false,
                    data: json!({}),
                    error: Some(err),
                }),
            );
        }
    }

    let response = execute_control_command_inner(&state.app, command).await;
    (StatusCode::OK, Json(response))
}

async fn connect_openclaw_inner(
    app: &AppHandle,
    gateway_url: Option<String>,
) -> Result<OpenClawStatus, String> {
    let (url, connect_timeout_seconds) = {
        let state = app.state::<OverlayAppState>();
        let mut openclaw = state
            .openclaw_state
            .lock()
            .map_err(|_| "Failed to lock OpenClaw state".to_string())?;

        if let Some(url) = gateway_url {
            openclaw.config.gateway_url = url;
        }

        if openclaw.outbound_tx.is_some() {
            return Ok(openclaw.status.clone());
        }

        openclaw.status.connected = false;
        openclaw.status.last_error = None;
        openclaw.status.gateway_url = Some(openclaw.config.gateway_url.clone());
        openclaw.status.reconnect_attempt = 0;
        (
            openclaw.config.gateway_url.clone(),
            openclaw.config.connect_timeout_seconds,
        )
    };

    let (tx, mut rx) = mpsc::unbounded_channel::<String>();
    {
        let state = app.state::<OverlayAppState>();
        if let Ok(mut openclaw) = state.openclaw_state.lock() {
            openclaw.outbound_tx = Some(tx.clone());
        };
    }

    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        let max_reconnect_attempts = 6_u32;
        let mut reconnect_attempt = 0_u32;
        let mut keep_running = true;

        while keep_running {
            let connect_result = timeout(
                Duration::from_secs(connect_timeout_seconds),
                connect_async(url.clone()),
            )
            .await;

            let (ws_stream, _) = match connect_result {
                Ok(Ok(result)) => {
                    reconnect_attempt = 0;
                    update_openclaw_status(&app_handle, |status| {
                        status.connected = true;
                        status.gateway_url = Some(url.clone());
                        status.last_error = None;
                        status.last_event_at = Some(now_utc_iso());
                        status.last_connected_at = Some(now_utc_iso());
                        status.reconnect_attempt = 0;
                    });
                    append_audit_entry(
                        &app_handle,
                        "openclaw.connected",
                        json!({ "gatewayUrl": url.clone() }),
                    );
                    result
                }
                Ok(Err(err)) => {
                    reconnect_attempt += 1;
                    update_openclaw_status(&app_handle, |status| {
                        status.connected = false;
                        status.last_error = Some(err.to_string());
                        status.gateway_url = Some(url.clone());
                        status.reconnect_attempt = reconnect_attempt;
                    });
                    append_audit_entry(
                        &app_handle,
                        "openclaw.connect_error",
                        json!({
                            "error": err.to_string(),
                            "gatewayUrl": url.clone(),
                            "attempt": reconnect_attempt,
                        }),
                    );

                    if reconnect_attempt > max_reconnect_attempts {
                        append_audit_entry(
                            &app_handle,
                            "openclaw.reconnect_exhausted",
                            json!({
                                "gatewayUrl": url.clone(),
                                "attempts": reconnect_attempt,
                            }),
                        );
                        break;
                    }

                    let backoff_seconds = (1_u64 << reconnect_attempt.min(4)).min(20);
                    append_audit_entry(
                        &app_handle,
                        "openclaw.reconnect_scheduled",
                        json!({
                            "gatewayUrl": url.clone(),
                            "attempt": reconnect_attempt,
                            "backoffSeconds": backoff_seconds,
                        }),
                    );
                    sleep(Duration::from_secs(backoff_seconds)).await;
                    continue;
                }
                Err(_) => {
                    reconnect_attempt += 1;
                    let timeout_error =
                        format!("Connection timed out after {}s", connect_timeout_seconds);
                    update_openclaw_status(&app_handle, |status| {
                        status.connected = false;
                        status.last_error = Some(timeout_error.clone());
                        status.gateway_url = Some(url.clone());
                        status.reconnect_attempt = reconnect_attempt;
                    });
                    append_audit_entry(
                        &app_handle,
                        "openclaw.connect_timeout",
                        json!({
                            "gatewayUrl": url.clone(),
                            "attempt": reconnect_attempt,
                            "timeoutSeconds": connect_timeout_seconds,
                        }),
                    );

                    if reconnect_attempt > max_reconnect_attempts {
                        append_audit_entry(
                            &app_handle,
                            "openclaw.reconnect_exhausted",
                            json!({
                                "gatewayUrl": url.clone(),
                                "attempts": reconnect_attempt,
                            }),
                        );
                        break;
                    }

                    let backoff_seconds = (1_u64 << reconnect_attempt.min(4)).min(20);
                    append_audit_entry(
                        &app_handle,
                        "openclaw.reconnect_scheduled",
                        json!({
                            "gatewayUrl": url.clone(),
                            "attempt": reconnect_attempt,
                            "backoffSeconds": backoff_seconds,
                        }),
                    );
                    sleep(Duration::from_secs(backoff_seconds)).await;
                    continue;
                }
            };

            let (mut writer, mut reader) = ws_stream.split();

            if let Ok(Some(token)) = load_openclaw_token() {
                let auth = json!({ "type": "auth", "token": token }).to_string();
                let _ = writer.send(Message::Text(auth.into())).await;
            }

            let mut reconnect_after_disconnect = false;
            let pending_replay = {
                let state = app_handle.state::<OverlayAppState>();
                let lock_result = state.openclaw_state.lock();
                match lock_result {
                    Ok(mut openclaw) => {
                        let mut combined = openclaw.pending_ack_payloads();
                        combined.extend(openclaw.take_pending_outbound());

                        let mut deduped = Vec::new();
                        let mut seen_message_ids = HashSet::new();
                        for payload in combined {
                            if let Some((message_id, _)) = parse_outbound_ack_fields(&payload) {
                                if !seen_message_ids.insert(message_id) {
                                    continue;
                                }
                            }
                            deduped.push(payload);
                        }
                        deduped
                    }
                    Err(_) => Vec::new(),
                }
            };

            if !pending_replay.is_empty() {
                append_audit_entry(
                    &app_handle,
                    "openclaw.replay_started",
                    json!({ "count": pending_replay.len() }),
                );

                let mut replay_iter = pending_replay.into_iter();
                while let Some(outbound) = replay_iter.next() {
                    if let Err(err) = writer.send(Message::Text(outbound.clone().into())).await {
                        let mut restore = vec![outbound];
                        restore.extend(replay_iter);
                        let mut dropped_oldest = false;
                        {
                            let state = app_handle.state::<OverlayAppState>();
                            let lock_result = state.openclaw_state.lock();
                            if let Ok(mut openclaw) = lock_result {
                                for item in restore.into_iter().rev() {
                                    dropped_oldest = openclaw.push_pending_outbound(item, true)
                                        || dropped_oldest;
                                }
                                openclaw.status.connected = false;
                                openclaw.status.last_error = Some(err.to_string());
                            };
                        }
                        if dropped_oldest {
                            append_audit_entry(
                                &app_handle,
                                "openclaw.queue_overflow",
                                json!({ "maxPendingOutbound": OPENCLAW_MAX_PENDING_OUTBOUND }),
                            );
                        }
                        append_audit_entry(
                            &app_handle,
                            "openclaw.replay_failed",
                            json!({ "error": err.to_string() }),
                        );
                        emit_openclaw_status_snapshot(&app_handle);
                        reconnect_after_disconnect = true;
                        break;
                    }
                    register_pending_ack_from_payload(&app_handle, &outbound);
                }

                if !reconnect_after_disconnect {
                    append_audit_entry(&app_handle, "openclaw.replay_flushed", json!({}));
                    emit_openclaw_status_snapshot(&app_handle);
                }
            }

            if !reconnect_after_disconnect {
                loop {
                    tokio::select! {
                        outbound = rx.recv() => {
                            let Some(outbound) = outbound else {
                                keep_running = false;
                                break;
                            };
                            if let Err(err) = writer.send(Message::Text(outbound.clone().into())).await {
                                let mut dropped_oldest = false;
                                let mut queued_outbound = 0_usize;
                                {
                                    let state = app_handle.state::<OverlayAppState>();
                                    let lock_result = state.openclaw_state.lock();
                                    if let Ok(mut openclaw) = lock_result {
                                        dropped_oldest = openclaw.push_pending_outbound(outbound, true);
                                        queued_outbound = openclaw.status.queued_outbound;
                                        openclaw.status.connected = false;
                                        openclaw.status.last_error = Some(err.to_string());
                                    };
                                }
                                if dropped_oldest {
                                    append_audit_entry(
                                        &app_handle,
                                        "openclaw.queue_overflow",
                                        json!({ "maxPendingOutbound": OPENCLAW_MAX_PENDING_OUTBOUND }),
                                    );
                                }
                                append_audit_entry(
                                    &app_handle,
                                    "openclaw.payload_requeued",
                                    json!({
                                        "reason": "writer_send_failed",
                                        "queuedOutbound": queued_outbound,
                                        "error": err.to_string(),
                                    }),
                                );
                                emit_openclaw_status_snapshot(&app_handle);
                                reconnect_after_disconnect = true;
                                break;
                            }
                            register_pending_ack_from_payload(&app_handle, &outbound);
                        }
                        inbound = reader.next() => {
                            let Some(inbound) = inbound else {
                                reconnect_after_disconnect = true;
                                break;
                            };
                            match inbound {
                                Ok(Message::Text(text)) => {
                                    update_openclaw_status(&app_handle, |status| {
                                        status.last_event_at = Some(now_utc_iso());
                                    });

                                    if let Ok(event) = serde_json::from_str::<GatewayInboundEvent>(&text) {
                                        if let Err(validation_err) = validate_gateway_event(&event) {
                                            append_audit_entry(
                                                &app_handle,
                                                "openclaw.event_rejected",
                                                json!({ "error": validation_err, "raw": text.to_string() }),
                                            );
                                            let _ = app_handle.emit(
                                                "openclaw://rejected",
                                                json!({ "error": validation_err, "raw": text.to_string() }),
                                            );
                                            continue;
                                        }

                                        if let Some(event_id) = gateway_event_identity(&event)
                                            .map(|value| value.trim().to_string())
                                            .filter(|value| !value.is_empty())
                                        {
                                            let duplicate = {
                                                let state = app_handle.state::<OverlayAppState>();
                                                let lock_result = state.openclaw_state.lock();
                                                match lock_result {
                                                    Ok(mut openclaw) => openclaw.remember_event_id(&event_id),
                                                    Err(_) => false,
                                                }
                                            };

                                            if duplicate {
                                                append_audit_entry(
                                                    &app_handle,
                                                    "openclaw.event_duplicate",
                                                    json!({ "eventId": event_id }),
                                                );
                                                continue;
                                            }
                                        }

                                        handle_gateway_event(&app_handle, event).await;
                                    } else {
                                        append_audit_entry(
                                            &app_handle,
                                            "openclaw.event_unparsed",
                                            json!({ "raw": text.to_string() }),
                                        );
                                        let _ = app_handle.emit("openclaw://raw", text.to_string());
                                    }
                                }
                                Ok(Message::Close(_)) => {
                                    reconnect_after_disconnect = true;
                                    break;
                                }
                                Ok(_) => {}
                                Err(err) => {
                                    update_openclaw_status(&app_handle, |status| {
                                        status.connected = false;
                                        status.last_error = Some(err.to_string());
                                    });
                                    reconnect_after_disconnect = true;
                                    break;
                                }
                            }
                        }
                    }
                }
            }

            if !keep_running {
                break;
            }

            update_openclaw_status(&app_handle, |status| {
                status.connected = false;
            });

            if reconnect_after_disconnect {
                reconnect_attempt += 1;
                if reconnect_attempt > max_reconnect_attempts {
                    append_audit_entry(
                        &app_handle,
                        "openclaw.reconnect_exhausted",
                        json!({
                            "gatewayUrl": url.clone(),
                            "attempts": reconnect_attempt,
                        }),
                    );
                    break;
                }

                let backoff_seconds = (1_u64 << reconnect_attempt.min(4)).min(20);
                update_openclaw_status(&app_handle, |status| {
                    status.reconnect_attempt = reconnect_attempt;
                    status.last_error = Some(format!(
                        "Gateway disconnected, reconnecting in {}s",
                        backoff_seconds
                    ));
                });
                append_audit_entry(
                    &app_handle,
                    "openclaw.reconnect_scheduled",
                    json!({
                        "gatewayUrl": url.clone(),
                        "attempt": reconnect_attempt,
                        "backoffSeconds": backoff_seconds,
                    }),
                );
                sleep(Duration::from_secs(backoff_seconds)).await;
            }
        }

        update_openclaw_status(&app_handle, |status| {
            status.connected = false;
        });
        let state = app_handle.state::<OverlayAppState>();
        if let Ok(mut openclaw) = state.openclaw_state.lock() {
            openclaw.outbound_tx = None;
            openclaw.status.queued_outbound = openclaw.pending_outbound.len();
        };
        emit_openclaw_status_snapshot(&app_handle);
    });

    let state = app.state::<OverlayAppState>();
    let openclaw = state
        .openclaw_state
        .lock()
        .map_err(|_| "Failed to lock OpenClaw state".to_string())?;
    Ok(openclaw.status.clone())
}

async fn handle_gateway_event(app: &AppHandle, event: GatewayInboundEvent) {
    match event {
        GatewayInboundEvent::Clarify {
            question_id,
            question,
            choices,
            ..
        } => {
            let mut bubble_choices = choices
                .into_iter()
                .take(4)
                .enumerate()
                .map(|(idx, label)| QuestionChoice {
                    choice_id: format!("choice_{}", idx + 1),
                    label,
                })
                .collect::<Vec<_>>();

            if bubble_choices.len() < 2 {
                bubble_choices.push(QuestionChoice {
                    choice_id: "choice_more".to_string(),
                    label: "Need more context".to_string(),
                });
            }

            let _ = create_question(
                app,
                question_id,
                question,
                bubble_choices,
                "openclaw.clarify",
                None,
            );
        }
        GatewayInboundEvent::ActionRequest {
            request_id,
            tool_id,
            args,
            ..
        } => {
            let payload = ActionRequestPayload {
                request_id: request_id.clone(),
                tool_id,
                args,
                source: Some("openclaw".to_string()),
            };

            let result = request_action_inner(app, payload).await;
            if let Ok(ref outcome) = result {
                send_openclaw_action_result(app, outcome, "gateway_action_request");
            } else if let Err(err) = &result {
                let _ = queue_openclaw_payload(
                    app,
                    json!({
                        "type": "action.result",
                        "requestId": request_id.clone(),
                        "status": "denied",
                        "reason": err,
                        "source": "gateway_action_request",
                    }),
                );
            }
            let _ = app.emit(
                "openclaw://action_result",
                json!({
                    "requestId": request_id,
                    "result": result,
                }),
            );
        }
        GatewayInboundEvent::AgentMessage { content, .. } => {
            let _ = app.emit("openclaw://message", json!({ "content": content }));
        }
        GatewayInboundEvent::Ack {
            message_id, status, ..
        } => {
            let acknowledged = acknowledge_pending_ack(app, &message_id);
            append_audit_entry(
                app,
                "openclaw.ack_received",
                json!({
                    "messageId": message_id,
                    "status": status,
                    "acknowledged": acknowledged,
                }),
            );
            let _ = app.emit(
                "openclaw://ack",
                json!({
                    "messageId": message_id,
                    "status": status,
                    "acknowledged": acknowledged,
                }),
            );
        }
    }
}

async fn disconnect_openclaw_inner(app: &AppHandle) -> Result<OpenClawStatus, String> {
    let status = {
        let state = app.state::<OverlayAppState>();
        let mut openclaw = state
            .openclaw_state
            .lock()
            .map_err(|_| "Failed to lock OpenClaw state".to_string())?;

        openclaw.outbound_tx = None;
        openclaw.status.connected = false;
        openclaw.status.reconnect_attempt = 0;
        openclaw.status.last_error = Some("Disconnected by user".to_string());
        openclaw.status.clone()
    };

    append_audit_entry(app, "openclaw.disconnected", json!({}));
    let _ = app.emit("openclaw://status", status.clone());
    Ok(status)
}

async fn execute_control_command_inner(
    app: &AppHandle,
    command: ControlCommand,
) -> ControlCommandResponse {
    let result = match command {
        ControlCommand::OverlayOpen => {
            open_overlay(app, "protocol").map(|_| json!({ "opened": true }))
        }
        ControlCommand::OverlayClose => {
            hide_overlay(app, "protocol").map(|_| json!({ "closed": true }))
        }
        ControlCommand::OverlayPin(payload) => set_pinned_state(app, payload.pinned, "protocol")
            .and_then(|settings| {
                serde_json::to_value(settings).map_err(|err| format!("Serialization error: {err}"))
            }),
        ControlCommand::OverlaySetMode(payload) => {
            set_mode_inner(app, &payload.mode_id, "protocol").and_then(|mode| {
                serde_json::to_value(mode).map_err(|err| format!("Serialization error: {err}"))
            })
        }
        ControlCommand::ContextCapture(request) => {
            capture_context_inner(app, request).and_then(|result| {
                serde_json::to_value(result).map_err(|err| format!("Serialization error: {err}"))
            })
        }
        ControlCommand::UiAsk(payload) => create_question(
            app,
            payload.question_id,
            payload.question,
            payload.choices,
            "protocol.ui.ask",
            None,
        )
        .and_then(|question| {
            serde_json::to_value(question).map_err(|err| format!("Serialization error: {err}"))
        }),
        ControlCommand::UiAnswer(payload) => {
            answer_question_inner(app, payload).and_then(|question| {
                serde_json::to_value(question).map_err(|err| format!("Serialization error: {err}"))
            })
        }
        ControlCommand::ActionRequest(payload) => request_action_inner(app, payload)
            .await
            .and_then(|outcome| {
                serde_json::to_value(outcome).map_err(|err| format!("Serialization error: {err}"))
            }),
    };

    match result {
        Ok(data) => ControlCommandResponse {
            ok: true,
            data,
            error: None,
        },
        Err(error) => ControlCommandResponse {
            ok: false,
            data: json!({}),
            error: Some(error),
        },
    }
}

fn build_overlay_state_snapshot(app: &AppHandle) -> Result<OverlayStateSnapshot, String> {
    let state = app.state::<OverlayAppState>();

    let settings = state
        .settings
        .lock()
        .map_err(|_| "Failed to read settings".to_string())?
        .clone();

    let mut perf = state
        .performance
        .lock()
        .map_err(|_| "Failed to read performance state".to_string())?;
    perf.sample_idle_memory();
    let performance = perf.snapshot();

    let current_mode = {
        let mode_state = state
            .mode_state
            .lock()
            .map_err(|_| "Failed to read mode state".to_string())?;
        mode_state.modes.get(&mode_state.current_mode_id).cloned()
    };

    let openclaw_status = state
        .openclaw_state
        .lock()
        .map_err(|_| "Failed to read OpenClaw state".to_string())?
        .status
        .clone();

    let localhost_status = state
        .localhost_status
        .lock()
        .map_err(|_| "Failed to read localhost status".to_string())?
        .clone();

    let night_mode = state
        .night_mode_state
        .lock()
        .map_err(|_| "Failed to read night mode state".to_string())?
        .config
        .clone();

    Ok(OverlayStateSnapshot {
        settings,
        performance,
        current_mode,
        openclaw_status,
        localhost_status,
        night_mode,
    })
}

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let open_item = MenuItem::with_id(app, TRAY_OPEN_ID, "Open overlay", true, None::<&str>)?;

    let default_pin_text = {
        let state = app.state::<OverlayAppState>();
        let pinned = state.settings.lock().map(|s| s.pinned).unwrap_or(false);
        if pinned {
            "Unpin overlay"
        } else {
            "Pin overlay"
        }
    };

    let pin_item = MenuItem::with_id(
        app,
        TRAY_TOGGLE_PIN_ID,
        default_pin_text,
        true,
        None::<&str>,
    )?;
    let pin_item_for_events = pin_item.clone();

    let perf_item = MenuItem::with_id(
        app,
        TRAY_PERF_ID,
        "Performance snapshot",
        true,
        None::<&str>,
    )?;
    let night_item = MenuItem::with_id(
        app,
        TRAY_NIGHT_MODE_ID,
        "Run night mode safely",
        true,
        None::<&str>,
    )?;
    let quit_item = MenuItem::with_id(app, TRAY_QUIT_ID, "Quit", true, None::<&str>)?;
    let separator = PredefinedMenuItem::separator(app)?;

    let menu = Menu::with_items(
        app,
        &[
            &open_item,
            &pin_item,
            &perf_item,
            &night_item,
            &separator,
            &quit_item,
        ],
    )?;

    TrayIconBuilder::with_id("vibe-overlay-tray")
        .menu(&menu)
        .tooltip("Neyvia")
        .show_menu_on_left_click(true)
        .on_menu_event(move |app, event| match event.id.as_ref() {
            TRAY_OPEN_ID => {
                let _ = open_overlay(app, "tray");
            }
            TRAY_TOGGLE_PIN_ID => {
                let toggled = {
                    let state = app.state::<OverlayAppState>();
                    let current = state.settings.lock().map(|s| s.pinned).unwrap_or(false);
                    set_pinned_state(app, !current, "tray")
                };

                if let Ok(settings) = toggled {
                    let label = if settings.pinned {
                        "Unpin overlay"
                    } else {
                        "Pin overlay"
                    };
                    let _ = pin_item_for_events.set_text(label);
                }
            }
            TRAY_PERF_ID => {
                let snapshot = refresh_performance_snapshot(app);
                log::info!(
                    "performance snapshot: cold_start={:?}ms hotkey_last={:?}ms hotkey_avg={:?}ms idle_ram={:?}MB",
                    snapshot.cold_start_ms,
                    snapshot.last_hotkey_latency_ms,
                    snapshot.average_hotkey_latency_ms,
                    snapshot.idle_ram_mb
                );
                let _ = app.emit("overlay://perf", snapshot);
            }
            TRAY_NIGHT_MODE_ID => {
                let app_handle = app.clone();
                tauri::async_runtime::spawn(async move {
                    let _ = run_night_mode_cycle(&app_handle, "tray").await;
                });
            }
            TRAY_QUIT_ID => {
                app.exit(0);
            }
            _ => {}
        })
        .build(app)?;

    Ok(())
}

#[tauri::command]
fn get_overlay_state(app: AppHandle) -> Result<OverlayStateSnapshot, String> {
    build_overlay_state_snapshot(&app)
}

#[tauri::command]
fn set_overlay_pinned(app: AppHandle, pinned: bool) -> Result<OverlaySettings, String> {
    set_pinned_state(&app, pinned, "ui")
}

#[tauri::command]
fn toggle_overlay_pin(app: AppHandle) -> Result<OverlaySettings, String> {
    let state = app.state::<OverlayAppState>();
    let pinned = state
        .settings
        .lock()
        .map_err(|_| "Failed to read settings".to_string())?
        .pinned;
    set_pinned_state(&app, !pinned, "ui")
}

#[tauri::command]
fn get_performance_snapshot(app: AppHandle) -> Result<PerformanceSnapshot, String> {
    Ok(refresh_performance_snapshot(&app))
}

#[tauri::command]
fn submit_prompt(
    app: AppHandle,
    prompt: String,
    provider: Option<String>,
    model: Option<String>,
    autonomous_mode: Option<bool>,
    task_type: Option<String>,
    task_routing: Option<Value>,
    verification_provider: Option<String>,
    verification_model: Option<String>,
) -> Result<(), String> {
    let trimmed = prompt.trim();
    if trimmed.is_empty() {
        return Ok(());
    }

    let autonomous_mode = autonomous_mode.unwrap_or(false);
    if autonomous_mode {
        let send_state = queue_openclaw_payload(
            &app,
            json!({
                "type": "user.message",
                "content": trimmed,
                "provider": provider,
                "model": model,
                "source": "overlay.autonomous",
                "taskType": task_type,
                "taskRouting": task_routing,
                "verification": {
                    "provider": verification_provider,
                    "model": verification_model,
                },
            }),
        )?;

        append_audit_entry(
            &app,
            "prompt.forwarded_openclaw",
            json!({
                "length": trimmed.len(),
                "provider": provider,
                "model": model,
                "taskType": task_type,
                "verificationProvider": verification_provider,
                "verificationModel": verification_model,
                "queued": send_state == OpenClawSendState::Queued,
            }),
        );
    } else {
        append_audit_entry(
            &app,
            "prompt.submitted",
            json!({
                "length": trimmed.len(),
                "mode": current_mode_definition(&app).map(|m| m.id),
                "provider": provider,
                "model": model,
                "taskType": task_type,
                "verificationProvider": verification_provider,
                "verificationModel": verification_model,
            }),
        );
    }

    let state = app.state::<OverlayAppState>();
    let is_pinned = state
        .settings
        .lock()
        .map_err(|_| "Failed to read settings".to_string())?
        .pinned;

    if !is_pinned {
        hide_overlay(&app, "prompt-submitted")?;
    }

    Ok(())
}

#[tauri::command]
fn get_modes(app: AppHandle) -> Result<Vec<ModeDefinition>, String> {
    let state = app.state::<OverlayAppState>();
    let mode_state = state
        .mode_state
        .lock()
        .map_err(|_| "Failed to read mode state".to_string())?;
    Ok(mode_state.modes.values().cloned().collect())
}

#[tauri::command]
fn set_mode(app: AppHandle, mode_id: String) -> Result<ModeDefinition, String> {
    set_mode_inner(&app, &mode_id, "ui")
}

#[tauri::command]
fn get_current_mode(app: AppHandle) -> Result<ModeDefinition, String> {
    current_mode_definition(&app).ok_or_else(|| "No active mode".to_string())
}

#[tauri::command]
fn context_capture(
    app: AppHandle,
    request: Option<ContextCaptureRequest>,
) -> Result<ContextCaptureResult, String> {
    let effective_request = if let Some(request) = request {
        request
    } else {
        current_mode_definition(&app)
            .map(|mode| mode.context_recipe)
            .unwrap_or_default()
    };

    capture_context_inner(&app, effective_request)
}

#[tauri::command]
fn ui_ask(app: AppHandle, payload: UiAskPayload) -> Result<QuestionBubble, String> {
    create_question(
        &app,
        payload.question_id,
        payload.question,
        payload.choices,
        "ui.ask",
        None,
    )
}

#[tauri::command]
fn ui_answer(app: AppHandle, payload: UiAnswerPayload) -> Result<QuestionBubble, String> {
    answer_question_inner(&app, payload)
}

#[tauri::command]
fn list_pending_questions(app: AppHandle) -> Result<Vec<QuestionBubble>, String> {
    let state = app.state::<OverlayAppState>();
    let question_state = state
        .question_state
        .lock()
        .map_err(|_| "Failed to read question state".to_string())?;
    Ok(question_state.pending.values().cloned().collect())
}

#[tauri::command]
async fn action_request(
    app: AppHandle,
    payload: ActionRequestPayload,
) -> Result<ActionRequestOutcome, String> {
    request_action_inner(&app, payload).await
}

#[tauri::command]
fn list_pending_approvals(app: AppHandle) -> Result<Vec<ActionApprovalRecord>, String> {
    let state = app.state::<OverlayAppState>();
    let approval_state = state
        .approval_state
        .lock()
        .map_err(|_| "Failed to read approval state".to_string())?;
    Ok(approval_state.pending.values().cloned().collect())
}

#[tauri::command]
async fn resolve_action_approval(
    app: AppHandle,
    payload: ResolveApprovalPayload,
) -> Result<ActionApprovalRecord, String> {
    resolve_approval_inner(&app, payload).await
}

#[tauri::command]
fn get_dictation_config(app: AppHandle) -> Result<DictationConfig, String> {
    let state = app.state::<OverlayAppState>();
    let dictation = state
        .dictation_state
        .lock()
        .map_err(|_| "Failed to read dictation state".to_string())?;
    Ok(dictation.config.clone())
}

#[tauri::command]
fn configure_dictation(app: AppHandle, config: DictationConfig) -> Result<DictationConfig, String> {
    let state = app.state::<OverlayAppState>();
    let mut dictation = state
        .dictation_state
        .lock()
        .map_err(|_| "Failed to write dictation state".to_string())?;
    dictation.config = config.clone();

    append_audit_entry(
        &app,
        "dictation.config.updated",
        json!({
            "strategy": format!("{:?}", dictation.config.strategy),
            "hasLocalCommand": dictation.config.local_stt_command.is_some(),
        }),
    );

    Ok(config)
}

#[tauri::command]
fn start_dictation(app: AppHandle) -> Result<DictationSession, String> {
    let session = {
        let state = app.state::<OverlayAppState>();
        let mut dictation = state
            .dictation_state
            .lock()
            .map_err(|_| "Failed to lock dictation state".to_string())?;

        let session = DictationSession {
            session_id: format!("dict_{}", Uuid::new_v4().simple()),
            status: DictationOutcomeStatus::Listening,
            started_at: now_utc_iso(),
            finished_at: None,
            engine: "pending".to_string(),
            audio_path: None,
            transcript: None,
            message: None,
        };

        dictation.active_session = Some(session.clone());
        session
    };

    append_audit_entry(
        &app,
        "dictation.started",
        json!({ "sessionId": session.session_id }),
    );
    let _ = app.emit("dictation://started", session.clone());

    Ok(session)
}

#[tauri::command]
async fn stop_dictation(
    app: AppHandle,
    payload: DictationStopPayload,
) -> Result<DictationSession, String> {
    let (mut session, config) = {
        let state = app.state::<OverlayAppState>();
        let mut dictation = state
            .dictation_state
            .lock()
            .map_err(|_| "Failed to lock dictation state".to_string())?;

        let Some(session) = dictation.active_session.take() else {
            return Err("No active dictation session".to_string());
        };

        (session, dictation.config.clone())
    };

    session.audio_path = payload.audio_path.clone();
    session.finished_at = Some(now_utc_iso());

    let outcome = match config.strategy {
        DictationStrategy::OsOnly => Err(config.os_fallback_hint),
        DictationStrategy::LocalFirst => {
            if let Some(path) = payload.audio_path.as_deref() {
                run_local_stt_command(&config, path).await
            } else {
                Err("No audio path provided for local transcription".to_string())
            }
        }
    };

    match outcome {
        Ok(transcript) => {
            session.status = DictationOutcomeStatus::Transcribed;
            session.engine = "local_stt".to_string();
            session.transcript = Some(transcript);
            session.message = None;
        }
        Err(message) => {
            session.status = DictationOutcomeStatus::NeedsOsFallback;
            session.engine = "os_fallback".to_string();
            session.message = Some(message.clone());

            let _ = create_question(
                &app,
                None,
                "Local STT is unavailable. Continue using OS dictation?".to_string(),
                vec![
                    QuestionChoice {
                        choice_id: "yes".to_string(),
                        label: "Use OS dictation".to_string(),
                    },
                    QuestionChoice {
                        choice_id: "configure_local".to_string(),
                        label: "Configure local STT".to_string(),
                    },
                    QuestionChoice {
                        choice_id: "cancel".to_string(),
                        label: "Cancel".to_string(),
                    },
                ],
                "dictation.fallback",
                None,
            );
        }
    }

    {
        let state = app.state::<OverlayAppState>();
        let mut dictation = state
            .dictation_state
            .lock()
            .map_err(|_| "Failed to lock dictation state".to_string())?;
        dictation.history.push(session.clone());
    }

    append_audit_entry(
        &app,
        "dictation.stopped",
        json!({
            "sessionId": session.session_id,
            "status": format!("{:?}", session.status),
            "engine": session.engine,
        }),
    );
    let _ = app.emit("dictation://stopped", session.clone());

    Ok(session)
}

#[tauri::command]
async fn transcribe_audio_file(
    app: AppHandle,
    payload: DictationTranscribePayload,
) -> Result<DictationSession, String> {
    let state = app.state::<OverlayAppState>();
    let config = state
        .dictation_state
        .lock()
        .map_err(|_| "Failed to lock dictation state".to_string())?
        .config
        .clone();

    let transcript = run_local_stt_command(&config, &payload.audio_path).await?;
    let session = DictationSession {
        session_id: format!("dict_{}", Uuid::new_v4().simple()),
        status: DictationOutcomeStatus::Transcribed,
        started_at: now_utc_iso(),
        finished_at: Some(now_utc_iso()),
        engine: "local_stt".to_string(),
        audio_path: Some(payload.audio_path),
        transcript: Some(transcript),
        message: None,
    };

    append_audit_entry(
        &app,
        "dictation.transcribed",
        json!({ "sessionId": session.session_id }),
    );
    Ok(session)
}

#[tauri::command]
fn get_dictation_history(app: AppHandle) -> Result<Vec<DictationSession>, String> {
    let state = app.state::<OverlayAppState>();
    let dictation = state
        .dictation_state
        .lock()
        .map_err(|_| "Failed to lock dictation state".to_string())?;
    Ok(dictation.history.clone())
}

#[tauri::command]
async fn execute_control_command(
    app: AppHandle,
    command: ControlCommand,
) -> Result<ControlCommandResponse, String> {
    Ok(execute_control_command_inner(&app, command).await)
}

#[tauri::command]
fn get_localhost_status(app: AppHandle) -> Result<LocalhostStatus, String> {
    let state = app.state::<OverlayAppState>();
    let status = state
        .localhost_status
        .lock()
        .map_err(|_| "Failed to lock localhost status".to_string())?
        .clone();
    Ok(status)
}

#[tauri::command]
async fn configure_localhost_api(
    app: AppHandle,
    payload: LocalhostConfigPayload,
) -> Result<LocalhostStatus, String> {
    {
        let state = app.state::<OverlayAppState>();
        {
            let mut status = state
                .localhost_status
                .lock()
                .map_err(|_| "Failed to lock localhost status".to_string())?;
            status.enabled = payload.enabled;
            if let Some(port) = payload.port {
                status.port = port;
            }
        }

        let mut settings = state
            .settings
            .lock()
            .map_err(|_| "Failed to lock settings".to_string())?;
        settings.localhost_api_enabled = payload.enabled;
        if let Some(port) = payload.port {
            settings.localhost_api_port = port;
        }
        save_settings(&state.settings_path, &settings)?;
        emit_settings(&app, &settings);
    }

    start_localhost_api(&app).await?;
    get_localhost_status(app)
}

#[tauri::command]
fn save_localhost_api_token_command(app: AppHandle, token: String) -> Result<bool, String> {
    save_localhost_api_token(&token)?;
    append_audit_entry(&app, "localhost.token_saved", json!({ "saved": true }));
    Ok(true)
}

#[tauri::command]
fn clear_localhost_api_token_command(app: AppHandle) -> Result<bool, String> {
    clear_localhost_api_token()?;
    append_audit_entry(&app, "localhost.token_cleared", json!({ "cleared": true }));
    Ok(true)
}

#[tauri::command]
fn has_localhost_api_token_command() -> Result<bool, String> {
    Ok(load_localhost_api_token()?.is_some())
}

#[tauri::command]
fn save_provider_secret_command(
    app: AppHandle,
    provider_id: String,
    secret: String,
) -> Result<bool, String> {
    if secret.trim().is_empty() {
        return Err("Provider secret cannot be empty".to_string());
    }
    save_provider_secret(&provider_id, &secret)?;
    append_audit_entry(
        &app,
        "provider.secret_saved",
        json!({ "providerId": provider_id, "saved": true }),
    );
    Ok(true)
}

#[tauri::command]
fn clear_provider_secret_command(app: AppHandle, provider_id: String) -> Result<bool, String> {
    clear_provider_secret(&provider_id)?;
    append_audit_entry(
        &app,
        "provider.secret_cleared",
        json!({ "providerId": provider_id, "cleared": true }),
    );
    Ok(true)
}

#[tauri::command]
fn has_provider_secret_command(provider_id: String) -> Result<bool, String> {
    Ok(load_provider_secret(&provider_id)?.is_some())
}

#[tauri::command]
fn get_provider_secret_presence_command(
    provider_ids: Option<Vec<String>>,
) -> Result<HashMap<String, bool>, String> {
    let mut output = HashMap::new();
    for provider_id in provider_ids.unwrap_or_default() {
        let has_secret = if provider_id == "openai-codex" {
            load_provider_secret(&provider_id)?.is_some()
                || load_openai_codex_oauth_credential()?.is_some()
        } else if provider_id == MINIMAX_OPENCLAW_PROVIDER_ID {
            load_provider_secret(&provider_id)?.is_some()
                || has_minimax_openclaw_oauth_credential()?
        } else {
            load_provider_secret(&provider_id)?.is_some()
        };
        output.insert(provider_id, has_secret);
    }
    Ok(output)
}

async fn codex_cli_login_receipt() -> (bool, Option<String>, String) {
    #[cfg(target_os = "windows")]
    let mut command = {
        let mut command = TokioCommand::new("cmd");
        let npm_launcher = std::env::var_os("APPDATA")
            .map(PathBuf::from)
            .map(|path| path.join("npm").join("codex.cmd"))
            .filter(|path| path.is_file());
        command.args(["/d", "/c"]);
        if let Some(launcher) = npm_launcher {
            command.arg(format!("call {} login status", launcher.display()));
        } else {
            command.arg("codex login status");
        }
        command
    };
    #[cfg(not(target_os = "windows"))]
    let mut command = {
        let mut command = TokioCommand::new("codex");
        command.args(["login", "status"]);
        command
    };
    hide_child_console(&mut command);
    match timeout(Duration::from_secs(8), command.output()).await {
        Ok(Ok(output)) => {
            let stdout = String::from_utf8_lossy(&output.stdout);
            let stderr = String::from_utf8_lossy(&output.stderr);
            let detail = format!("{stdout}{stderr}").trim().to_string();
            let normalized = detail.to_lowercase();
            let authenticated = output.status.success() && normalized.contains("logged in");
            let source = authenticated.then(|| {
                if normalized.contains("chatgpt") {
                    "codex-cli-chatgpt".to_string()
                } else {
                    "codex-cli".to_string()
                }
            });
            (authenticated, source, detail.chars().take(300).collect())
        }
        Ok(Err(error)) => (false, None, format!("Codex login probe failed: {error}")),
        Err(_) => (false, None, "Codex login probe timed out.".to_string()),
    }
}

#[tauri::command]
async fn get_openai_codex_oauth_status_command() -> Result<OpenAiCodexOAuthStatus, String> {
    let credential = load_openai_codex_oauth_credential()?;
    let (cli_authenticated, cli_source, cli_message) = if credential.is_none() {
        codex_cli_login_receipt().await
    } else {
        (false, None, String::new())
    };
    Ok(OpenAiCodexOAuthStatus {
        authenticated: credential.is_some() || cli_authenticated,
        account_id: credential.as_ref().and_then(|item| item.account_id.clone()),
        expires: credential.as_ref().and_then(|item| item.expires),
        source: if credential.is_some() {
            Some("neyvia-keyring".to_string())
        } else {
            cli_source
        },
        message: if credential.is_some() {
            Some("Neyvia OAuth credential is available in the desktop keyring.".to_string())
        } else if cli_message.is_empty() {
            None
        } else {
            Some(cli_message)
        },
    })
}

#[tauri::command]
fn clear_openai_codex_oauth_command(app: AppHandle) -> Result<bool, String> {
    clear_openai_codex_oauth_credential()?;
    append_audit_entry(
        &app,
        "openai_codex.oauth_cleared",
        json!({ "cleared": true }),
    );
    Ok(true)
}

#[tauri::command]
async fn start_openai_codex_oauth_command(
    app: AppHandle,
) -> Result<OpenAiCodexOAuthResponse, String> {
    let (code_verifier, code_challenge) = generate_openai_codex_pkce();
    let state = generate_oauth_random_value();
    let preferred_redirect_uri =
        format!("http://localhost:{OPENAI_CODEX_OAUTH_PORT}/auth/callback");
    let listener_result = StdTcpListener::bind(("127.0.0.1", OPENAI_CODEX_OAUTH_PORT))
        .or_else(|_| StdTcpListener::bind(("127.0.0.1", 0)));
    let (listener, callback_port, redirect_uri) = match listener_result {
        Ok(listener) => {
            let callback_port = listener
                .local_addr()
                .map_err(|error| format!("Failed to inspect OAuth callback listener: {error}"))?
                .port();
            let redirect_uri = format!("http://localhost:{callback_port}/auth/callback");
            (listener, callback_port, redirect_uri)
        }
        Err(error) => {
            let auth_url =
                build_openai_codex_authorize_url(&preferred_redirect_uri, &code_challenge, &state);
            {
                let oauth_state = app.state::<OverlayAppState>();
                let mut pending = oauth_state
                    .openai_codex_oauth_pending
                    .lock()
                    .map_err(|_| "Failed to lock OpenAI Codex OAuth state.".to_string())?;
                *pending = Some(OpenAiCodexOAuthPending {
                    code_verifier,
                    state,
                    redirect_uri: preferred_redirect_uri.clone(),
                });
            }
            open_url_in_browser(&auth_url).await?;
            append_audit_entry(
                &app,
                "openai_codex.oauth_manual_required",
                json!({ "reason": error.to_string(), "redirectUri": preferred_redirect_uri }),
            );
            return Ok(OpenAiCodexOAuthResponse {
                status: "manual_required".to_string(),
                authenticated: false,
                account_id: None,
                expires: None,
                auth_url: Some(auth_url),
                redirect_uri: Some(preferred_redirect_uri),
                hermes_sync: None,
                message: format!(
                    "Could not bind any localhost callback port for OpenAI Codex OAuth: {error}. Paste the final redirect URL to finish sign-in."
                ),
            });
        }
    };
    let auth_url = build_openai_codex_authorize_url(&redirect_uri, &code_challenge, &state);
    listener
        .set_nonblocking(false)
        .map_err(|error| format!("Failed to configure OAuth callback listener: {error}"))?;
    listener
        .set_ttl(64)
        .map_err(|error| format!("Failed to configure OAuth callback listener: {error}"))?;
    open_url_in_browser(&auth_url).await?;
    append_audit_entry(
        &app,
        "openai_codex.oauth_started",
        json!({ "redirectUri": redirect_uri, "callbackPort": callback_port }),
    );
    let callback = tokio::task::spawn_blocking(move || {
        listener
            .set_nonblocking(false)
            .map_err(|error| format!("Failed to configure OAuth callback listener: {error}"))?;
        let (stream, _) = listener
            .accept()
            .map_err(|error| format!("Failed to accept OAuth callback: {error}"))?;
        read_oauth_callback_from_stream(stream, callback_port)
    })
    .await
    .map_err(|error| format!("OpenAI Codex OAuth callback task failed: {error}"))??;
    let (code, returned_state) = parse_oauth_callback(&callback)?;
    if returned_state != state {
        return Err("OpenAI Codex OAuth callback state did not match.".to_string());
    }
    let credential = exchange_openai_codex_oauth_code(&code, &redirect_uri, &code_verifier).await?;
    save_openai_codex_oauth_credential(&credential)?;
    let hermes_sync = sync_openai_codex_oauth_to_wsl_hermes(&credential).await;
    append_audit_entry(
        &app,
        "openai_codex.oauth_saved",
        json!({ "accountId": credential.account_id, "expires": credential.expires, "hermesSync": hermes_sync.clone() }),
    );
    emit_control_room_changed(&app, "openai_codex.oauth_saved");
    let mut response = oauth_response_from_credential(
        "authenticated",
        &credential,
        "OpenAI Codex OAuth credentials saved.",
    );
    response.hermes_sync = Some(hermes_sync);
    Ok(response)
}

#[tauri::command]
async fn complete_openai_codex_oauth_command(
    app: AppHandle,
    payload: OpenAiCodexOAuthCompletePayload,
) -> Result<OpenAiCodexOAuthResponse, String> {
    let pending = {
        let oauth_state = app.state::<OverlayAppState>();
        let pending = oauth_state
            .openai_codex_oauth_pending
            .lock()
            .map_err(|_| "Failed to lock OpenAI Codex OAuth state.".to_string())?
            .clone();
        pending.ok_or_else(|| {
            "No OpenAI Codex OAuth flow is waiting for manual completion.".to_string()
        })?
    };
    let (code, returned_state) = parse_oauth_callback(&payload.callback)?;
    if returned_state != pending.state {
        return Err("OpenAI Codex OAuth callback state did not match.".to_string());
    }
    let credential =
        exchange_openai_codex_oauth_code(&code, &pending.redirect_uri, &pending.code_verifier)
            .await?;
    save_openai_codex_oauth_credential(&credential)?;
    let hermes_sync = sync_openai_codex_oauth_to_wsl_hermes(&credential).await;
    {
        let oauth_state = app.state::<OverlayAppState>();
        let mut pending = oauth_state
            .openai_codex_oauth_pending
            .lock()
            .map_err(|_| "Failed to lock OpenAI Codex OAuth state.".to_string())?;
        *pending = None;
    }
    append_audit_entry(
        &app,
        "openai_codex.oauth_saved",
        json!({ "accountId": credential.account_id, "expires": credential.expires, "hermesSync": hermes_sync.clone() }),
    );
    emit_control_room_changed(&app, "openai_codex.oauth_saved");
    let mut response = oauth_response_from_credential(
        "authenticated",
        &credential,
        "OpenAI Codex OAuth credentials saved.",
    );
    response.hermes_sync = Some(hermes_sync);
    Ok(response)
}

fn minimax_openclaw_method_for_region(
    region: Option<&str>,
) -> Result<(&'static str, Option<String>), String> {
    let normalized = region
        .unwrap_or("global")
        .trim()
        .to_ascii_lowercase()
        .replace('_', "-");
    match normalized.as_str() {
        "" | "global" | "international" | "minimax-global" => {
            Ok(("oauth", Some("global".to_string())))
        }
        "cn" | "china" | "minimax-cn" => Ok(("oauth-cn", Some("cn".to_string()))),
        _ => Err(format!(
            "Unsupported MiniMax OAuth region \"{normalized}\". Use global or cn."
        )),
    }
}

fn launch_minimax_openclaw_auth_terminal(command_line: &str) -> Result<(), String> {
    // Intentionally visible: the user clicked sign-in and completes OAuth in this terminal.
    let mut command = if cfg!(target_os = "windows") {
        let mut command = TokioCommand::new("cmd");
        command
            .arg("/C")
            .arg("start")
            .arg("MiniMax OpenClaw OAuth")
            .arg("cmd")
            .arg("/K")
            .arg(command_line);
        command
    } else if cfg!(target_os = "macos") {
        let mut command = TokioCommand::new("osascript");
        command.arg("-e").arg(format!(
            "tell application \"Terminal\" to do script \"{}\"",
            command_line.replace('\\', "\\\\").replace('"', "\\\"")
        ));
        command
    } else {
        let mut command = TokioCommand::new("sh");
        command.arg("-lc").arg(format!(
            "x-terminal-emulator -e sh -lc '{}' || gnome-terminal -- sh -lc '{}'",
            command_line.replace('\'', "'\\''"),
            command_line.replace('\'', "'\\''")
        ));
        command
    };
    command
        .spawn()
        .map_err(|error| format!("Failed to open MiniMax OpenClaw auth terminal: {error}"))?;
    Ok(())
}

#[tauri::command]
fn get_minimax_openclaw_auth_status_command() -> Result<MinimaxOpenClawAuthStatus, String> {
    minimax_openclaw_oauth_status()
}

#[tauri::command]
fn start_minimax_openclaw_auth_command(
    app: AppHandle,
    payload: Option<MinimaxOpenClawAuthStartPayload>,
) -> Result<MinimaxOpenClawAuthStartResponse, String> {
    let payload = payload.unwrap_or(MinimaxOpenClawAuthStartPayload {
        region: None,
        set_default: None,
    });
    let (method, region) = minimax_openclaw_method_for_region(payload.region.as_deref())?;
    let mut command_parts = vec![
        "openclaw".to_string(),
        "models".to_string(),
        "auth".to_string(),
        "login".to_string(),
        "--provider".to_string(),
        MINIMAX_OPENCLAW_PROVIDER_ID.to_string(),
        "--method".to_string(),
        method.to_string(),
    ];
    if payload.set_default.unwrap_or(false) {
        command_parts.push("--set-default".to_string());
    }
    let command_line = command_parts.join(" ");
    launch_minimax_openclaw_auth_terminal(&command_line)?;
    append_audit_entry(
        &app,
        "minimax_openclaw.oauth_terminal_started",
        json!({ "providerId": MINIMAX_OPENCLAW_PROVIDER_ID, "method": method, "region": region }),
    );
    emit_control_room_changed(&app, "minimax_openclaw.oauth_terminal_started");
    let mut status = minimax_openclaw_oauth_status()?;
    status.region = region.clone();
    Ok(MinimaxOpenClawAuthStartResponse {
        launched: true,
        provider_id: MINIMAX_OPENCLAW_PROVIDER_ID.to_string(),
        method: method.to_string(),
        command: command_line,
        status,
        message: "MiniMax OpenClaw OAuth terminal launched. Finish the interactive login there, then verify auth in Neyvia.".to_string(),
    })
}

#[tauri::command]
fn get_openclaw_status(app: AppHandle) -> Result<OpenClawStatus, String> {
    let state = app.state::<OverlayAppState>();
    let status = state
        .openclaw_state
        .lock()
        .map_err(|_| "Failed to lock OpenClaw state".to_string())?
        .status
        .clone();
    Ok(status)
}

#[tauri::command]
async fn connect_openclaw_gateway(
    app: AppHandle,
    payload: Option<LocalGatewayConfigPayload>,
) -> Result<OpenClawStatus, String> {
    let gateway_url = payload.and_then(|value| value.gateway_url);
    connect_openclaw_inner(&app, gateway_url).await
}

#[tauri::command]
async fn disconnect_openclaw_gateway(app: AppHandle) -> Result<OpenClawStatus, String> {
    disconnect_openclaw_inner(&app).await
}

#[tauri::command]
fn save_openclaw_gateway_token(app: AppHandle, token: String) -> Result<bool, String> {
    save_openclaw_token(&token)?;
    append_audit_entry(&app, "openclaw.token_saved", json!({ "saved": true }));
    Ok(true)
}

#[tauri::command]
fn clear_openclaw_gateway_token(app: AppHandle) -> Result<bool, String> {
    clear_openclaw_token()?;
    append_audit_entry(&app, "openclaw.token_cleared", json!({ "cleared": true }));
    Ok(true)
}

#[tauri::command]
fn has_openclaw_gateway_token() -> Result<bool, String> {
    Ok(load_openclaw_token()?.is_some())
}

#[tauri::command]
fn send_openclaw_message(app: AppHandle, payload: OpenClawMessagePayload) -> Result<bool, String> {
    let send_state = queue_openclaw_payload(
        &app,
        json!({ "type": "user.message", "content": payload.message }),
    )?;

    append_audit_entry(
        &app,
        "openclaw.message_sent",
        json!({
            "queued": send_state == OpenClawSendState::Queued,
        }),
    );
    Ok(true)
}

#[tauri::command]
fn get_night_mode_config(app: AppHandle) -> Result<NightModeConfig, String> {
    let state = app.state::<OverlayAppState>();
    let config = state
        .night_mode_state
        .lock()
        .map_err(|_| "Failed to lock night mode state".to_string())?
        .config
        .clone();
    Ok(config)
}

#[tauri::command]
fn configure_night_mode(
    app: AppHandle,
    config: NightModeConfig,
) -> Result<NightModeConfig, String> {
    let state = app.state::<OverlayAppState>();
    let mut night_mode = state
        .night_mode_state
        .lock()
        .map_err(|_| "Failed to lock night mode state".to_string())?;
    night_mode.config = config.clone();

    append_audit_entry(
        &app,
        "night_mode.config_updated",
        json!({
            "enabled": config.enabled,
            "autopilot": config.autopilot_enabled,
            "startHour": config.start_hour,
            "endHour": config.end_hour,
        }),
    );

    Ok(config)
}

#[tauri::command]
async fn run_night_mode_now(app: AppHandle) -> Result<NightModeReport, String> {
    run_night_mode_cycle(&app, "manual").await
}

#[tauri::command]
fn get_last_night_mode_report(app: AppHandle) -> Result<Option<NightModeReport>, String> {
    let state = app.state::<OverlayAppState>();
    let report = state
        .night_mode_state
        .lock()
        .map_err(|_| "Failed to lock night mode state".to_string())?
        .last_report
        .clone();
    Ok(report)
}

#[tauri::command]
fn get_audit_log(app: AppHandle, limit: Option<usize>) -> Result<Vec<AuditEntry>, String> {
    let state = app.state::<OverlayAppState>();
    let max = limit.unwrap_or(120).clamp(1, 1000);
    Ok(get_audit_tail(&state.audit_log_path, max))
}

#[tauri::command]
fn get_autonomy_dashboard_snapshot(
    app: AppHandle,
    payload: Option<AutonomyDashboardPayload>,
) -> Result<AutonomyDashboardSnapshot, String> {
    build_autonomy_dashboard_snapshot(&app, payload.and_then(|item| item.root))
}

#[tauri::command]
async fn get_control_room_snapshot_command(
    app: AppHandle,
    payload: Option<AutonomyDashboardPayload>,
) -> Result<Value, String> {
    let mut snapshot = run_agent_cli_json(
        &app,
        payload.and_then(|item| item.root),
        "control-room",
        vec![],
        180,
    )
    .await?;
    let provider_presence = provider_secret_presence_snapshot(&CONTROL_ROOM_PROVIDER_IDS)?;
    if let Value::Object(root) = &mut snapshot {
        let localhost_status = app
            .state::<OverlayAppState>()
            .localhost_status
            .lock()
            .map_err(|_| "Failed to read localhost status".to_string())?
            .clone();
        let localhost_status_value =
            serde_json::to_value(localhost_status).map_err(|error| error.to_string())?;
        root.insert("localhostStatus".to_string(), localhost_status_value);
        root.insert(
            "providerSecretPresence".to_string(),
            provider_presence.clone(),
        );
        let setup_status_entry = root
            .entry("providerSetupStatus".to_string())
            .or_insert_with(|| Value::Object(serde_json::Map::new()));
        if let Value::Object(setup_status) = setup_status_entry {
            for provider_id in CONTROL_ROOM_PROVIDER_IDS {
                let auth_present = provider_presence
                    .get(provider_id)
                    .and_then(Value::as_bool)
                    .unwrap_or(false);
                let provider_entry = setup_status
                    .entry(provider_id.to_string())
                    .or_insert_with(|| Value::Object(serde_json::Map::new()));
                if let Value::Object(provider_payload) = provider_entry {
                    let effective_auth_present = auth_present;
                    provider_payload.insert(
                        "authPresent".to_string(),
                        Value::Bool(effective_auth_present),
                    );
                    provider_payload.insert(
                        "configured".to_string(),
                        Value::Bool(effective_auth_present),
                    );
                }
            }
        }
    }
    Ok(snapshot)
}

#[tauri::command]
async fn get_control_room_summary_command(
    app: AppHandle,
    payload: Option<ControlRoomSummaryPayload>,
) -> Result<Value, String> {
    let payload = payload.unwrap_or_default();
    let mut summary =
        run_agent_cli_json(&app, payload.root, "control-room-summary", vec![], 30).await?;
    let provider_presence = provider_secret_presence_snapshot(&CONTROL_ROOM_PROVIDER_IDS)?;
    if let Value::Object(root) = &mut summary {
        root.insert("providerSecretPresence".to_string(), provider_presence);
    }
    Ok(summary)
}

const DESKTOP_BACKEND_QUICK_TIMEOUT_SECONDS: u64 = 120;
const DESKTOP_BACKEND_ACTION_TIMEOUT_SECONDS: u64 = 1_260;
const DESKTOP_BACKEND_MAX_ACTION_TIMEOUT_SECONDS: u64 = 7_200;
const DESKTOP_BACKEND_CLEANUP_MARGIN_SECONDS: u64 = 60;
const DESKTOP_BACKEND_STDOUT_LIMIT_BYTES: usize = 16 * 1024 * 1024;
const DESKTOP_BACKEND_STDERR_LIMIT_BYTES: usize = 64 * 1024;

fn positive_payload_seconds(payload: &Value, camel: &str, snake: &str) -> Option<u64> {
    [camel, snake]
        .into_iter()
        .find_map(|key| payload.get(key))
        .and_then(|value| {
            value
                .as_u64()
                .or_else(|| value.as_str().and_then(|text| text.parse::<u64>().ok()))
        })
        .filter(|seconds| *seconds > 0)
}

fn desktop_backend_timeout_seconds(command: &str, payload: &Value) -> Option<u64> {
    if command == "send_agent_chat_command" {
        // A chat has no elapsed-time budget unless its caller explicitly asks
        // for one. Legacy timeout environment settings must not silently end it.
        return positive_payload_seconds(payload, "runtimeTimeoutSeconds", "runtime_timeout_seconds")
            .map(|seconds| seconds.saturating_add(DESKTOP_BACKEND_CLEANUP_MARGIN_SECONDS));
    }

    // These commands only read small snapshots or poll an already-running
    // operation. They remain bounded independently of the chat runtime budget.
    if matches!(
        command,
        "desktop_controller_poll_command"
            | "desktop_controller_complete_command"
            | "get_agent_chat_stream_command"
            | "get_agent_chat_run_status_command"
            | "cancel_agent_chat_command"
            | "get_agent_prompt_library_command"
            | "get_conversation_state_command"
            | "get_conversation_session_state_command"
            | "get_neyvia_conversation_command"
            | "get_neyvia_conversations_command"
            | "get_external_chats_command"
            | "get_external_chat_command"
            | "get_connected_devices_command"
            | "get_agent_collaboration_command"
            | "get_provider_auth_queue_command"
            | "list_workspace_directory_command"
            | "search_workspace_directories_command"
            | "get_capability_os_snapshot_command"
            | "get_harness_catalog_command"
            | "onboarding_state_command"
            | "onboarding_save_command"
            | "onboarding_runtimes_command"
            | "onboarding_base_pack_status_command"
            | "onboarding_base_pack_start_command"
            | "onboarding_base_pack_pause_command"
            | "onboarding_pack_install_command"
            | "onboarding_pack_status_command"
            | "list_harness_jobs_command"
            | "get_harness_batch_command"
            | "list_harness_batches_command"
    ) {
        return Some(DESKTOP_BACKEND_QUICK_TIMEOUT_SECONDS);
    }

    // Backend actions with an explicit finite budget get cleanup time around
    // their own deadline; other mutations retain a bounded action allowance.
    if let Some(requested) = positive_payload_seconds(payload, "timeoutSeconds", "timeout_seconds")
    {
        return Some(requested
            .clamp(30, DESKTOP_BACKEND_MAX_ACTION_TIMEOUT_SECONDS)
            .saturating_add(DESKTOP_BACKEND_CLEANUP_MARGIN_SECONDS));
    }
    Some(DESKTOP_BACKEND_ACTION_TIMEOUT_SECONDS)
}

async fn read_capped<R: AsyncRead + Unpin>(
    mut reader: R,
    limit: usize,
) -> std::io::Result<(Vec<u8>, bool)> {
    let mut output = Vec::with_capacity(limit.min(64 * 1024));
    let mut buffer = [0u8; 8 * 1024];
    let mut exceeded = false;
    loop {
        let read = reader.read(&mut buffer).await?;
        if read == 0 {
            break;
        }
        let remaining = limit.saturating_sub(output.len());
        let kept = remaining.min(read);
        output.extend_from_slice(&buffer[..kept]);
        exceeded |= kept < read;
    }
    Ok((output, exceeded))
}

async fn stop_desktop_backend_process_tree(child: &mut TokioChild) -> Result<(), String> {
    let pid = child.id().ok_or_else(|| {
        "Neyvia's desktop backend process already exited before cleanup".to_string()
    })?;
    #[cfg(windows)]
    let tree_stopped = {
        let mut taskkill = TokioCommand::new("taskkill.exe");
        hide_child_console(&mut taskkill);
        taskkill
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .kill_on_drop(true);
        match timeout(Duration::from_secs(15), taskkill.output()).await {
            Ok(Ok(output)) => output.status.success(),
            _ => false,
        }
    };
    #[cfg(not(windows))]
    let tree_stopped = child.kill().await.is_ok();

    let reaped = matches!(
        timeout(Duration::from_secs(10), child.wait()).await,
        Ok(Ok(_))
    );
    if tree_stopped && reaped {
        Ok(())
    } else {
        Err(
            "The desktop bridge process tree could not be fully confirmed stopped and reaped."
                .to_string(),
        )
    }
}

async fn await_desktop_backend_reader(
    task: &mut tokio::task::JoinHandle<std::io::Result<(Vec<u8>, bool)>>,
    label: &str,
) -> Result<(Vec<u8>, bool), String> {
    match timeout(Duration::from_secs(5), &mut *task).await {
        Ok(Ok(Ok(output))) => Ok(output),
        Ok(Ok(Err(error))) => Err(format!("Could not read desktop backend {label}: {error}")),
        Ok(Err(error)) => Err(format!(
            "Could not collect desktop backend {label}: {error}"
        )),
        Err(_) => {
            task.abort();
            Err(format!(
                "Desktop backend {label} did not close within 5 seconds; a descendant may still hold its pipe."
            ))
        }
    }
}

async fn wait_for_desktop_backend_child(
    child: &mut TokioChild,
    timeout_seconds: Option<u64>,
) -> Result<(std::process::ExitStatus, Vec<u8>, Vec<u8>), String> {
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "Neyvia's desktop backend did not expose stdout".to_string())?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| "Neyvia's desktop backend did not expose stderr".to_string())?;
    let stdout_task = tokio::spawn(read_capped(stdout, DESKTOP_BACKEND_STDOUT_LIMIT_BYTES));
    let stderr_task = tokio::spawn(read_capped(stderr, DESKTOP_BACKEND_STDERR_LIMIT_BYTES));

    let status_result = match timeout_seconds {
        Some(seconds) => timeout(Duration::from_secs(seconds), child.wait()).await,
        None => Ok(child.wait().await),
    };
    let status = match status_result {
        Ok(Ok(status)) => status,
        Ok(Err(error)) => {
            let tree_result = stop_desktop_backend_process_tree(child).await;
            let mut stdout_task = stdout_task;
            let mut stderr_task = stderr_task;
            let stdout_result = await_desktop_backend_reader(&mut stdout_task, "stdout").await;
            let stderr_result = await_desktop_backend_reader(&mut stderr_task, "stderr").await;
            let cleanup = tree_result
                .err()
                .or_else(|| stdout_result.err())
                .or_else(|| stderr_result.err());
            return Err(match cleanup {
                Some(cleanup) => format!(
                    "Neyvia's desktop backend failed while waiting: {error}. Cleanup is uncertain: {cleanup}"
                ),
                None => format!("Neyvia's desktop backend failed while waiting: {error}"),
            });
        }
        Err(_) => {
            let timeout_seconds = timeout_seconds.expect("elapsed deadline must be configured");
            // Kill the bridge and its descendants before returning. Bound pipe
            // draining too: grandchildren can inherit stdout/stderr handles.
            let tree_result = stop_desktop_backend_process_tree(child).await;
            let mut stdout_task = stdout_task;
            let mut stderr_task = stderr_task;
            let stdout_result = await_desktop_backend_reader(&mut stdout_task, "stdout").await;
            let stderr_result = await_desktop_backend_reader(&mut stderr_task, "stderr").await;
            let cleanup = tree_result
                .err()
                .or_else(|| stdout_result.err())
                .or_else(|| stderr_result.err());
            let detail = cleanup
                .map(|error| format!(" Cleanup could not be confirmed: {error}"))
                .unwrap_or_else(|| " The bridge process tree was stopped and reaped.".to_string());
            return Err(format!(
                "Neyvia's desktop backend timed out after {timeout_seconds} seconds; the task outcome may be incomplete.{detail}"
            ));
        }
    };

    let mut stdout_task = stdout_task;
    let mut stderr_task = stderr_task;
    let (stdout, stdout_exceeded) =
        await_desktop_backend_reader(&mut stdout_task, "stdout").await?;
    let (stderr, _) = await_desktop_backend_reader(&mut stderr_task, "stderr").await?;
    if stdout_exceeded {
        return Err("Neyvia's desktop backend response exceeded 16 MiB".to_string());
    }
    if !status.success() && stdout.is_empty() {
        let stderr = String::from_utf8_lossy(&stderr);
        return Err(format!(
            "Neyvia's desktop backend exited with {status}: {}",
            stderr.trim()
        ));
    }
    Ok((status, stdout, stderr))
}

#[tauri::command]
async fn call_desktop_backend_command(
    app: AppHandle,
    request: DesktopBackendCallPayload,
) -> Result<Value, String> {
    if base_pack_bridge::enabled() {
        if let Some(result) = base_pack_bridge::dispatch(&app, &request.command, &request.payload).await? {
            return Ok(result);
        }
        base_pack_bridge::require_ready(&app)?;
    }
    let workspace_root = resolve_workspace_root(request.root)?;
    let workspace_root_text = workspace_root.to_string_lossy().to_string();
    let interpreter = runtime_env::resolve_backend_python(&workspace_root).await?;
    let mut command = interpreter.command();
    hide_child_console(&mut command);
    command.current_dir(&workspace_root);
    inject_agent_cli_pythonpath(&mut command, &workspace_root);
    inject_agent_cli_provider_env(&app, &mut command)?;
    command
        .arg("-m")
        .arg("grant_agent.desktop_bridge")
        .arg("--root")
        .arg(&workspace_root_text)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);

    let request_command = request.command;
    let request_payload = request.payload.unwrap_or_else(|| json!({}));
    let timeout_seconds = desktop_backend_timeout_seconds(&request_command, &request_payload);
    let request_body = serde_json::to_vec(&json!({
        "command": request_command,
        "payload": request_payload,
    }))
    .map_err(|error| format!("Failed to encode desktop backend request: {error}"))?;
    let mut child = command
        .spawn()
        .map_err(|error| format!("Failed to start Neyvia's desktop backend: {error}"))?;
    let mut stdin = child
        .stdin
        .take()
        .ok_or_else(|| "Neyvia's desktop backend did not expose stdin".to_string())?;
    stdin
        .write_all(&request_body)
        .await
        .map_err(|error| format!("Failed to send desktop backend request: {error}"))?;
    drop(stdin);

    let (_status, stdout, stderr) =
        wait_for_desktop_backend_child(&mut child, timeout_seconds).await?;
    let envelope: Value = serde_json::from_slice(&stdout).map_err(|error| {
        let stderr = String::from_utf8_lossy(&stderr);
        format!("Neyvia's desktop backend returned invalid JSON: {error}. {stderr}")
    })?;
    if envelope.get("ok").and_then(Value::as_bool) != Some(true) {
        return Err(envelope
            .get("error")
            .and_then(Value::as_str)
            .unwrap_or("Neyvia's desktop backend rejected the request")
            .to_string());
    }
    append_audit_entry(
        &app,
        "desktop_backend.command_completed",
        json!({
            "command": request_command,
            "workspaceRoot": workspace_root_text,
        }),
    );
    let mut data = envelope.get("data").cloned().unwrap_or(Value::Null);
    if base_pack_bridge::enabled() && request_command == "onboarding_state_command" {
        data["basePack"] = base_pack_bridge::onboarding_base_pack_status_command(app).await?;
    }
    Ok(data)
}

#[tauri::command]
async fn get_native_tool_catalog_command(
    app: AppHandle,
    payload: Option<Value>,
) -> Result<Value, String> {
    call_desktop_backend_command(
        app,
        DesktopBackendCallPayload {
            command: "get_native_tool_catalog_command".to_string(),
            payload,
            root: None,
        },
    )
    .await
}

#[tauri::command]
async fn get_skill_library_command(
    app: AppHandle,
    payload: Option<Value>,
) -> Result<Value, String> {
    call_desktop_backend_command(
        app,
        DesktopBackendCallPayload {
            command: "get_skill_library_command".to_string(),
            payload,
            root: None,
        },
    )
    .await
}

#[tauri::command]
async fn call_native_tool_command(app: AppHandle, payload: Option<Value>) -> Result<Value, String> {
    let payload = payload.unwrap_or_else(|| json!({}));
    let root = payload
        .get("root")
        .and_then(Value::as_str)
        .map(str::to_string);
    let tool = payload
        .get("tool")
        .or_else(|| payload.get("name"))
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| "tool is required".to_string())?;
    let arguments = payload
        .get("arguments")
        .cloned()
        .unwrap_or_else(|| json!({}));
    if !arguments.is_object() {
        return Err("arguments must be an object".to_string());
    }
    if base_pack_bridge::enabled() && tool == "neyvia.onboarding.base_pack" {
        let action = arguments.get("action").and_then(Value::as_str).unwrap_or("status");
        let command = match action {
            "status" => "onboarding_base_pack_status_command",
            "start" => "onboarding_base_pack_start_command",
            "pause" => "onboarding_base_pack_pause_command",
            _ => return Err("Base pack action must be status, start or pause".into()),
        };
        return base_pack_bridge::dispatch(&app,command,&Some(arguments)).await?
            .ok_or("Native base-pack action is unavailable".into());
    }
    let mut args = vec![
        "--tool".to_string(),
        tool.to_string(),
        "--arguments-json".to_string(),
        serde_json::to_string(&arguments).map_err(|error| error.to_string())?,
    ];
    let nas_root = payload
        .get("nasRoot")
        .or_else(|| payload.get("nas_root"))
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .unwrap_or("")
        .trim()
        .to_string();
    if !nas_root.is_empty() {
        args.push("--nas-root".to_string());
        args.push(nas_root.clone());
    }
    let stateful_native_app = tool.starts_with("neyvia.nativeapp.");
    if stateful_native_app || matches!(tool, "preview.screenshot" | "preview.annotate") {
        let workspace_root = resolve_workspace_root(root.clone())?;
        let started = Instant::now();
        match call_persistent_native_tool_worker(&app, &workspace_root, &nas_root, tool, &arguments)
            .await
        {
            Ok(value) => {
                append_audit_entry(
                    &app,
                    "native_tool.worker_succeeded",
                    json!({
                        "tool": tool,
                        "workspaceRoot": workspace_root,
                        "durationMs": started.elapsed().as_millis() as u64,
                    }),
                );
                return Ok(value);
            }
            // Session actions may already have taken effect. A one-shot
            // fallback would lose their host or repeat an uncertain action.
            Err(error) if stateful_native_app => return Err(error),
            Err(error) => append_audit_entry(
                &app,
                "native_tool.worker_fallback",
                json!({
                    "tool": tool,
                    "workspaceRoot": workspace_root,
                    "durationMs": started.elapsed().as_millis() as u64,
                    "error": error,
                }),
            ),
        }
    }
    run_agent_cli_json(&app, root, "native-tool-call", args, 120).await
}

#[tauri::command]
fn inspect_codex_import_command() -> Result<CodexImportSnapshot, String> {
    Ok(cached_codex_import_snapshot())
}

fn base64_url_no_pad(bytes: impl AsRef<[u8]>) -> String {
    use base64::Engine;
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(bytes)
}

fn generate_oauth_random_value() -> String {
    let mut bytes = Vec::with_capacity(64);
    for _ in 0..4 {
        bytes.extend_from_slice(Uuid::new_v4().as_bytes());
    }
    base64_url_no_pad(bytes)
}

fn generate_openai_codex_pkce() -> (String, String) {
    let code_verifier = generate_oauth_random_value();
    let digest = Sha256::digest(code_verifier.as_bytes());
    (code_verifier, base64_url_no_pad(digest))
}

fn build_openai_codex_authorize_url(
    redirect_uri: &str,
    code_challenge: &str,
    state: &str,
) -> String {
    let query = [
        ("response_type", "code"),
        ("client_id", OPENAI_CODEX_OAUTH_CLIENT_ID),
        ("redirect_uri", redirect_uri),
        ("scope", OPENAI_CODEX_OAUTH_SCOPE),
        ("code_challenge", code_challenge),
        ("code_challenge_method", "S256"),
        ("id_token_add_organizations", "true"),
        ("codex_cli_simplified_flow", "true"),
        ("state", state),
        ("originator", "fluxio-desktop"),
    ]
    .into_iter()
    .map(|(key, value)| format!("{key}={}", urlencoding::encode(value)))
    .collect::<Vec<_>>()
    .join("&");
    format!("{OPENAI_CODEX_OAUTH_ISSUER}/oauth/authorize?{query}")
}

async fn open_url_in_browser(target: &str) -> Result<(), String> {
    let mut command = if cfg!(target_os = "windows") {
        let mut command = TokioCommand::new("rundll32");
        command.arg("url.dll,FileProtocolHandler").arg(target);
        command
    } else if cfg!(target_os = "macos") {
        let mut command = TokioCommand::new("open");
        command.arg(target);
        command
    } else {
        let mut command = TokioCommand::new("xdg-open");
        command.arg(target);
        command
    };
    hide_child_console(&mut command);
    command
        .spawn()
        .map_err(|error| format!("Failed to open browser: {error}"))?;
    Ok(())
}

fn read_oauth_callback_from_stream(
    mut stream: StdTcpStream,
    callback_port: u16,
) -> Result<String, String> {
    let mut reader = BufReader::new(
        stream
            .try_clone()
            .map_err(|error| format!("Failed to read OAuth callback: {error}"))?,
    );
    let mut request_line = String::new();
    reader
        .read_line(&mut request_line)
        .map_err(|error| format!("Failed to read OAuth callback request: {error}"))?;
    let path = request_line
        .split_whitespace()
        .nth(1)
        .ok_or_else(|| "OAuth callback did not include a request path.".to_string())?
        .to_string();
    let body = if path.starts_with("/auth/callback") {
        "Authentication successful. Return to Neyvia to continue."
    } else {
        "Neyvia received an unexpected OAuth callback path."
    };
    let status = if path.starts_with("/auth/callback") {
        "200 OK"
    } else {
        "404 Not Found"
    };
    let response = format!(
        "HTTP/1.1 {status}\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.as_bytes().len()
    );
    stream
        .write_all(response.as_bytes())
        .map_err(|error| format!("Failed to write OAuth callback response: {error}"))?;
    if !path.starts_with("/auth/callback") {
        return Err("OAuth callback path was not /auth/callback.".to_string());
    }
    Ok(format!("http://localhost:{callback_port}{path}"))
}

fn parse_oauth_callback(callback: &str) -> Result<(String, String), String> {
    let trimmed = callback.trim();
    let parse_target = if trimmed.starts_with("http://") || trimmed.starts_with("https://") {
        trimmed.to_string()
    } else if trimmed.starts_with("/auth/callback") {
        format!("http://localhost:{OPENAI_CODEX_OAUTH_PORT}{trimmed}")
    } else {
        format!("http://localhost:{OPENAI_CODEX_OAUTH_PORT}/auth/callback?code={trimmed}")
    };
    let url = reqwest::Url::parse(&parse_target)
        .map_err(|error| format!("OAuth callback URL is invalid: {error}"))?;
    if url.path() != "/auth/callback" {
        return Err("OAuth callback URL must use /auth/callback.".to_string());
    }
    let mut code = String::new();
    let mut state = String::new();
    let mut oauth_error = String::new();
    let mut oauth_error_description = String::new();
    for (key, value) in url.query_pairs() {
        match key.as_ref() {
            "code" => code = value.into_owned(),
            "state" => state = value.into_owned(),
            "error" => oauth_error = value.into_owned(),
            "error_description" => oauth_error_description = value.into_owned(),
            _ => {}
        }
    }
    if !oauth_error.is_empty() {
        return Err(format!(
            "OpenAI Codex OAuth returned {oauth_error}: {oauth_error_description}"
        ));
    }
    if code.trim().is_empty() {
        return Err("OAuth callback did not include an authorization code.".to_string());
    }
    Ok((code, state))
}

fn parse_jwt_payload(jwt: &str) -> Option<Value> {
    let payload = jwt.split('.').nth(1)?;
    let bytes = {
        use base64::Engine;
        base64::engine::general_purpose::URL_SAFE_NO_PAD
            .decode(payload)
            .ok()?
    };
    serde_json::from_slice::<Value>(&bytes).ok()
}

fn claim_string(payload: &Value, path: &[&str]) -> Option<String> {
    let mut current = payload;
    for key in path {
        current = current.get(*key)?;
    }
    current.as_str().map(ToString::to_string)
}

fn extract_openai_codex_account_id(access_token: &str, id_token: &str) -> Option<String> {
    for token in [access_token, id_token] {
        let Some(payload) = parse_jwt_payload(token) else {
            continue;
        };
        if let Some(value) = claim_string(
            &payload,
            &["https://api.openai.com/auth", "chatgpt_account_id"],
        ) {
            return Some(value);
        }
        if let Some(value) = claim_string(&payload, &["chatgpt_account_id"]) {
            return Some(value);
        }
        if let Some(value) = claim_string(&payload, &["account_id"]) {
            return Some(value);
        }
    }
    None
}

fn extract_jwt_expiration(jwt: &str) -> Option<i64> {
    parse_jwt_payload(jwt)?.get("exp")?.as_i64()
}

async fn exchange_openai_codex_oauth_code(
    code: &str,
    redirect_uri: &str,
    code_verifier: &str,
) -> Result<OpenAiCodexOAuthCredential, String> {
    #[derive(Deserialize)]
    struct TokenResponse {
        id_token: String,
        access_token: String,
        refresh_token: String,
    }

    let client = reqwest::Client::new();
    let response = client
        .post(format!("{OPENAI_CODEX_OAUTH_ISSUER}/oauth/token"))
        .header("Content-Type", "application/x-www-form-urlencoded")
        .form(&[
            ("grant_type", "authorization_code"),
            ("code", code),
            ("redirect_uri", redirect_uri),
            ("client_id", OPENAI_CODEX_OAUTH_CLIENT_ID),
            ("code_verifier", code_verifier),
        ])
        .send()
        .await
        .map_err(|error| format!("OpenAI Codex OAuth token exchange failed: {error}"))?;
    let status = response.status();
    if !status.is_success() {
        let body = response
            .text()
            .await
            .unwrap_or_else(|_| "unreadable response body".to_string());
        return Err(format!(
            "OpenAI Codex OAuth token endpoint returned {status}: {body}"
        ));
    }
    let tokens = response
        .json::<TokenResponse>()
        .await
        .map_err(|error| format!("OpenAI Codex OAuth token response was invalid: {error}"))?;
    let account_id = extract_openai_codex_account_id(&tokens.access_token, &tokens.id_token);
    let expires = extract_jwt_expiration(&tokens.access_token)
        .or_else(|| extract_jwt_expiration(&tokens.id_token));
    Ok(OpenAiCodexOAuthCredential {
        access: tokens.access_token,
        refresh: tokens.refresh_token,
        expires,
        account_id,
        id_token: Some(tokens.id_token),
        client_id: OPENAI_CODEX_OAUTH_CLIENT_ID.to_string(),
        issuer: OPENAI_CODEX_OAUTH_ISSUER.to_string(),
        stored_at: now_utc_iso(),
    })
}

async fn sync_openai_codex_oauth_to_wsl_hermes(credential: &OpenAiCodexOAuthCredential) -> Value {
    if !cfg!(target_os = "windows") {
        return json!({ "synced": false, "reason": "wsl_unavailable" });
    }
    let payload = json!({
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": Value::Null,
        "tokens": {
            "id_token": credential.id_token.clone().unwrap_or_else(|| credential.access.clone()),
            "access_token": credential.access.clone(),
            "refresh_token": credential.refresh.clone(),
            "account_id": credential.account_id.clone().unwrap_or_default(),
        },
        "last_refresh": credential.stored_at.clone(),
    })
    .to_string();
    let script = r#"
import json
from pathlib import Path
import sys

payload = json.loads(sys.stdin.read() or "{}")
codex_home = Path.home() / ".codex"
codex_home.mkdir(parents=True, exist_ok=True)
auth_path = codex_home / "auth.json"
auth_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
try:
    auth_path.chmod(0o600)
except OSError:
    pass

hermes_root = Path.home() / ".hermes" / "hermes-agent"
sys.path.insert(0, str(hermes_root))
try:
    from hermes_cli.auth import (
        DEFAULT_CODEX_BASE_URL,
        _import_codex_cli_tokens,
        _save_codex_tokens,
        _update_config_for_provider,
        get_codex_auth_status,
    )

    imported = _import_codex_cli_tokens()
    if not imported:
        raise RuntimeError("Hermes could not import the freshly written Codex CLI tokens.")
    _save_codex_tokens(imported)
    config_path = _update_config_for_provider("openai-codex", DEFAULT_CODEX_BASE_URL)
    status = get_codex_auth_status()
    print(json.dumps({
        "synced": bool(status.get("logged_in")),
        "source": status.get("source") or "hermes-auth-store",
        "configPath": str(config_path),
    }))
except Exception as exc:
    print(json.dumps({"synced": False, "reason": str(exc)}))
"#;
    let mut command = TokioCommand::new("wsl");
    command
        .arg("python3")
        .arg("-c")
        .arg(script)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    hide_child_console(&mut command);
    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(error) => return json!({ "synced": false, "reason": error.to_string() }),
    };
    if let Some(mut stdin) = child.stdin.take() {
        if let Err(error) = stdin.write_all(payload.as_bytes()).await {
            return json!({ "synced": false, "reason": error.to_string() });
        }
    }
    let output = match timeout(Duration::from_secs(45), child.wait_with_output()).await {
        Ok(Ok(output)) => output,
        Ok(Err(error)) => return json!({ "synced": false, "reason": error.to_string() }),
        Err(_) => return json!({ "synced": false, "reason": "wsl_sync_timeout" }),
    };
    let stdout = String::from_utf8_lossy(&output.stdout);
    if let Some(line) = stdout.lines().last() {
        if let Ok(parsed) = serde_json::from_str::<Value>(line) {
            return parsed;
        }
    }
    let stderr = String::from_utf8_lossy(&output.stderr);
    json!({
        "synced": false,
        "reason": if stderr.trim().is_empty() { "empty_wsl_sync_output" } else { stderr.trim() },
    })
}

fn oauth_response_from_credential(
    status: &str,
    credential: &OpenAiCodexOAuthCredential,
    message: &str,
) -> OpenAiCodexOAuthResponse {
    OpenAiCodexOAuthResponse {
        status: status.to_string(),
        authenticated: true,
        account_id: credential.account_id.clone(),
        expires: credential.expires,
        auth_url: None,
        redirect_uri: None,
        hermes_sync: None,
        message: message.to_string(),
    }
}

fn is_allowed_external_url(url: &str) -> bool {
    let normalized = url.trim().to_ascii_lowercase();
    [
        "https://auth.openai.com/",
        "https://platform.openai.com/",
        "https://platform.minimax.io/",
        "https://platform.minimaxi.com/",
    ]
    .iter()
    .any(|prefix| normalized.starts_with(prefix))
}

#[tauri::command]
async fn open_external_url_command(app: AppHandle, url: String) -> Result<bool, String> {
    let target = url.trim().to_string();
    if !is_allowed_external_url(&target) {
        return Err("External URL is not allowlisted for provider authentication.".to_string());
    }

    open_url_in_browser(&target).await?;
    append_audit_entry(&app, "provider.auth_url_opened", json!({ "url": target }));
    Ok(true)
}

#[tauri::command]
fn pick_folder_command() -> Result<Option<String>, String> {
    Ok(rfd::FileDialog::new()
        .pick_folder()
        .map(|path| path.display().to_string()))
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ImportedAgentPromptFile {
    file_name: String,
    text: String,
}

#[tauri::command]
fn import_agent_prompt_file_command() -> Result<Option<ImportedAgentPromptFile>, String> {
    const MAX_BYTES: u64 = 1_000_000;
    const MAX_CHARACTERS: usize = 100_000;

    let Some(path) = rfd::FileDialog::new()
        .add_filter("Text or Markdown", &["txt", "md"])
        .pick_file()
    else {
        return Ok(None);
    };

    let file_name = path
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_else(|| "selected file".to_string());
    let extension = path
        .extension()
        .and_then(|extension| extension.to_str())
        .unwrap_or_default();
    if !extension.eq_ignore_ascii_case("txt") && !extension.eq_ignore_ascii_case("md") {
        return Err("Choose a .txt or .md file to import.".to_string());
    }

    let metadata =
        fs::metadata(&path).map_err(|_| format!("Could not read {file_name} metadata."))?;
    if metadata.len() > MAX_BYTES {
        return Err(
            "This file is too large to import. Choose a text or Markdown file under 1 MB."
                .to_string(),
        );
    }
    let mut bytes = Vec::with_capacity(metadata.len().min(MAX_BYTES) as usize);
    File::open(&path)
        .and_then(|file| file.take(MAX_BYTES + 1).read_to_end(&mut bytes))
        .map_err(|_| format!("Could not read {file_name}."))?;
    if bytes.len() as u64 > MAX_BYTES {
        return Err(
            "This file is too large to import. Choose a text or Markdown file under 1 MB."
                .to_string(),
        );
    }
    let text = String::from_utf8(bytes)
        .map_err(|_| "System prompt files must use UTF-8 text encoding.".to_string())?;
    let text = text.strip_prefix('\u{feff}').unwrap_or(&text).to_string();
    if text.encode_utf16().count() > MAX_CHARACTERS {
        return Err(format!(
            "This file exceeds the {MAX_CHARACTERS} character system prompt limit."
        ));
    }

    Ok(Some(ImportedAgentPromptFile { file_name, text }))
}

#[tauri::command]
async fn get_onboarding_status_command(
    app: AppHandle,
    payload: Option<AutonomyDashboardPayload>,
) -> Result<Value, String> {
    run_agent_cli_json(
        &app,
        payload.and_then(|item| item.root),
        "onboarding-status",
        vec![],
        120,
    )
    .await
}

#[tauri::command]
async fn save_workspace_profile_command(
    app: AppHandle,
    payload: WorkspaceSavePayload,
) -> Result<Value, String> {
    let mut args = vec![
        "--name".to_string(),
        payload.name,
        "--path".to_string(),
        payload.path,
        "--default-runtime".to_string(),
        payload.default_runtime,
    ];
    if let Some(workspace_id) = payload
        .workspace_id
        .filter(|value| !value.trim().is_empty())
    {
        args.push("--workspace-id".to_string());
        args.push(workspace_id);
    }
    if let Some(user_profile) = payload
        .user_profile
        .filter(|value| !value.trim().is_empty())
    {
        args.push("--user-profile".to_string());
        args.push(user_profile);
    }
    if let Some(preferred_harness) = payload
        .preferred_harness
        .filter(|value| !value.trim().is_empty())
    {
        args.push("--preferred-harness".to_string());
        args.push(preferred_harness);
    }
    if let Some(routing_strategy) = payload
        .routing_strategy
        .filter(|value| !value.trim().is_empty())
    {
        args.push("--routing-strategy".to_string());
        args.push(routing_strategy);
    }
    if let Some(route_overrides) = payload.route_overrides {
        let serialized = serde_json::to_string(&route_overrides)
            .map_err(|error| format!("Failed to serialize route overrides: {error}"))?;
        args.push("--route-overrides-json".to_string());
        args.push(serialized);
    }
    if let Some(auto_optimize_routing) = payload.auto_optimize_routing {
        args.push("--auto-optimize-routing".to_string());
        args.push(
            if auto_optimize_routing {
                "true"
            } else {
                "false"
            }
            .to_string(),
        );
    }
    if let Some(openai_codex_auth_mode) = payload
        .openai_codex_auth_mode
        .filter(|value| !value.trim().is_empty())
    {
        args.push("--openai-codex-auth-mode".to_string());
        args.push(openai_codex_auth_mode);
    }
    if let Some(minimax_auth_mode) = payload
        .minimax_auth_mode
        .filter(|value| !value.trim().is_empty())
    {
        args.push("--minimax-auth-mode".to_string());
        args.push(minimax_auth_mode);
    }
    if let Some(commit_message_style) = payload
        .commit_message_style
        .filter(|value| !value.trim().is_empty())
    {
        args.push("--commit-message-style".to_string());
        args.push(commit_message_style);
    }
    if let Some(execution_target_preference) = payload
        .execution_target_preference
        .filter(|value| !value.trim().is_empty())
    {
        args.push("--execution-target-preference".to_string());
        args.push(execution_target_preference);
    }
    let response = run_agent_cli_json(&app, payload.root, "workspace-save", args, 180).await?;
    emit_control_room_changed(&app, "workspace.saved");
    Ok(response)
}

#[tauri::command]
async fn delete_workspace_profile_command(
    app: AppHandle,
    payload: WorkspaceDeletePayload,
) -> Result<Value, String> {
    let args = vec!["--workspace-id".to_string(), payload.workspace_id];
    let response = run_agent_cli_json(&app, payload.root, "workspace-delete", args, 180).await?;
    emit_control_room_changed(&app, "workspace.deleted");
    Ok(response)
}

#[tauri::command]
async fn export_control_room_data_command(
    app: AppHandle,
    payload: Option<AutonomyDashboardPayload>,
) -> Result<Value, String> {
    let root_override = payload.and_then(|item| item.root);
    let workspace_root = resolve_workspace_root(root_override.clone())?;
    let response =
        run_agent_cli_json(&app, root_override, "control-room-export", vec![], 180).await?;
    append_audit_entry(
        &app,
        "control_room.exported",
        json!({
            "workspaceRoot": workspace_root.to_string_lossy().to_string(),
            "exportPath": response.get("exportPath").and_then(Value::as_str).unwrap_or(""),
        }),
    );
    Ok(response)
}

#[tauri::command]
async fn start_control_room_mission_command(
    app: AppHandle,
    payload: ControlMissionStartPayload,
) -> Result<Value, String> {
    let mut args = vec![
        "--workspace-id".to_string(),
        payload.workspace_id,
        "--runtime".to_string(),
        payload.runtime,
        "--objective".to_string(),
        payload.objective,
        "--mode".to_string(),
        payload.mode.unwrap_or_else(|| "Autopilot".to_string()),
        "--budget-hours".to_string(),
        payload.budget_hours.unwrap_or(12).to_string(),
        "--launch-async".to_string(),
    ];
    if let Some(run_until) = payload.run_until.filter(|value| !value.trim().is_empty()) {
        args.push("--run-until".to_string());
        args.push(run_until);
    }
    if let Some(reasoning_effort) = payload
        .reasoning_effort
        .filter(|value| !value.trim().is_empty() && value.trim() != "default")
    {
        args.push("--reasoning-effort".to_string());
        args.push(reasoning_effort);
    }
    if let Some(ultra_worker_effort) = payload
        .ultra_worker_effort
        .filter(|value| !value.trim().is_empty() && value.trim() != "default")
    {
        args.push("--ultra-worker-effort".to_string());
        args.push(ultra_worker_effort);
    }
    if let Some(route_overrides) = payload.route_overrides {
        let serialized = serde_json::to_string(&route_overrides)
            .map_err(|error| format!("Failed to serialize mission route overrides: {error}"))?;
        args.push("--route-overrides-json".to_string());
        args.push(serialized);
    }
    if let Some(mission_contract) = payload.mission_contract {
        let serialized = serde_json::to_string(&mission_contract)
            .map_err(|error| format!("Failed to serialize mission contract: {error}"))?;
        args.push("--mission-contract-json".to_string());
        args.push(serialized);
    }
    for success_check in payload.success_checks.unwrap_or_default() {
        if !success_check.trim().is_empty() {
            args.push("--success-check".to_string());
            args.push(success_check);
        }
    }
    if let Some(destination) = payload
        .escalation_destination
        .filter(|value| !value.trim().is_empty())
    {
        args.push("--escalation-destination".to_string());
        args.push(destination);
    }
    if let Some(profile) = payload.profile.filter(|value| !value.trim().is_empty()) {
        args.push("--profile".to_string());
        args.push(profile);
    }
    if payload.code_execution.unwrap_or(false)
        || payload
            .code_execution_container_id
            .as_ref()
            .map(|value| !value.trim().is_empty())
            .unwrap_or(false)
    {
        args.push("--code-execution".to_string());
    }
    if let Some(memory) = payload
        .code_execution_memory
        .filter(|value| !value.trim().is_empty())
    {
        args.push("--code-execution-memory".to_string());
        args.push(memory);
    }
    if let Some(container_id) = payload
        .code_execution_container_id
        .filter(|value| !value.trim().is_empty())
    {
        args.push("--code-execution-container-id".to_string());
        args.push(container_id);
    }
    if payload.code_execution_required.unwrap_or(false) {
        args.push("--code-execution-required".to_string());
    }
    let response = run_agent_cli_json(&app, payload.root, "mission-start", args, 300).await?;
    emit_control_room_changed(&app, "mission.started");
    Ok(response)
}

#[tauri::command]
async fn quickstart_control_room_mission_command(
    app: AppHandle,
    payload: ControlMissionQuickstartPayload,
) -> Result<Value, String> {
    let mut args = vec![
        "--objective".to_string(),
        payload.objective,
        "--runtime".to_string(),
        payload.runtime.unwrap_or_else(|| "auto".to_string()),
        "--mode".to_string(),
        payload.mode.unwrap_or_else(|| "Autopilot".to_string()),
        "--budget-hours".to_string(),
        payload.budget_hours.unwrap_or(4).to_string(),
    ];
    if let Some(workspace_id) = payload
        .workspace_id
        .filter(|value| !value.trim().is_empty())
    {
        args.push("--workspace-id".to_string());
        args.push(workspace_id);
    }
    let raw_turn_mode = payload.turn_mode.unwrap_or_else(|| "standard".to_string());
    let legacy_ultra = matches!(
        raw_turn_mode
            .trim()
            .to_lowercase()
            .replace('_', "-")
            .as_str(),
        "ultra" | "ultra-reasoning"
    );
    if !legacy_ultra && !raw_turn_mode.trim().is_empty() && raw_turn_mode.trim() != "standard" {
        args.push("--turn-mode".to_string());
        args.push(raw_turn_mode);
    }
    let reasoning_effort = payload.reasoning_effort.unwrap_or_else(|| {
        if legacy_ultra {
            "ultra".to_string()
        } else {
            "default".to_string()
        }
    });
    if !reasoning_effort.trim().is_empty() && reasoning_effort.trim() != "default" {
        args.push("--reasoning-effort".to_string());
        args.push(reasoning_effort);
    }
    if let Some(ultra_worker_effort) = payload
        .ultra_worker_effort
        .filter(|value| !value.trim().is_empty() && value.trim() != "default")
    {
        args.push("--ultra-worker-effort".to_string());
        args.push(ultra_worker_effort);
    }
    for success_check in payload.success_checks.unwrap_or_default() {
        if !success_check.trim().is_empty() {
            args.push("--success-check".to_string());
            args.push(success_check);
        }
    }
    if payload.foreground.unwrap_or(false) {
        args.push("--foreground".to_string());
    }
    let response = run_agent_cli_json(&app, payload.root, "mission-quickstart", args, 300).await?;
    emit_control_room_changed(&app, "mission.started");
    Ok(response)
}

#[tauri::command]
async fn apply_control_room_mission_action_command(
    app: AppHandle,
    payload: ControlMissionActionPayload,
) -> Result<Value, String> {
    let args = vec![
        "--mission-id".to_string(),
        payload.mission_id,
        "--action".to_string(),
        payload.action,
    ];
    let response = run_agent_cli_json(&app, payload.root, "mission-action", args, 240).await?;
    emit_control_room_changed(&app, "mission.action");
    Ok(response)
}

#[tauri::command]
async fn send_control_room_mission_follow_up_command(
    app: AppHandle,
    payload: ControlMissionFollowUpPayload,
) -> Result<Value, String> {
    let args = vec![
        "--mission-id".to_string(),
        payload.mission_id,
        "--message".to_string(),
        payload.message,
    ];
    let response = run_agent_cli_json(&app, payload.root, "mission-follow-up", args, 120).await?;
    emit_control_room_changed(&app, "mission.follow_up");
    Ok(response)
}

#[tauri::command]
async fn apply_control_room_workspace_action_command(
    app: AppHandle,
    payload: ControlWorkspaceActionPayload,
) -> Result<Value, String> {
    let mut args = vec![
        "--surface".to_string(),
        payload.surface,
        "--action-id".to_string(),
        payload.action_id,
    ];
    if let Some(workspace_id) = payload
        .workspace_id
        .filter(|value| !value.trim().is_empty())
    {
        args.push("--workspace-id".to_string());
        args.push(workspace_id);
    }
    if payload.approved.unwrap_or(false) {
        args.push("--approved".to_string());
    }
    let response = run_agent_cli_json(&app, payload.root, "workspace-action", args, 900).await?;
    emit_control_room_changed(&app, "workspace.action");
    Ok(response)
}

#[tauri::command]
async fn get_nas_storage_pressure_command(
    app: AppHandle,
    payload: Option<NasStoragePressurePayload>,
) -> Result<Value, String> {
    let payload = payload.unwrap_or_default();
    let mut args = Vec::new();
    if let Some(path) = payload.path.filter(|value| !value.trim().is_empty()) {
        args.push("--path".to_string());
        args.push(path);
    }
    if payload.no_write_latest.unwrap_or(false) || payload.write_latest == Some(false) {
        args.push("--no-write-latest".to_string());
    }
    run_agent_cli_json(&app, payload.root, "nas-storage-pressure", args, 120).await
}

#[tauri::command]
async fn get_ios_studio_status_command(
    app: AppHandle,
    payload: Option<IosStudioRootPayload>,
) -> Result<Value, String> {
    let target_root = payload.and_then(|item| item.root);
    run_agent_cli_json(
        &app,
        None,
        "ios-studio-status",
        ios_cli_target_args(target_root, vec![]),
        120,
    )
    .await
}

fn ios_cli_target_args(root: Option<String>, args: Vec<String>) -> Vec<String> {
    let Some(root) = root.filter(|value| !value.trim().is_empty()) else {
        return args;
    };
    let mut rooted = vec!["--root".to_string(), root];
    rooted.extend(args);
    rooted
}

#[tauri::command]
async fn create_ios_app_command(
    app: AppHandle,
    payload: IosStudioCreatePayload,
) -> Result<Value, String> {
    let mut args = vec![
        "--name".to_string(),
        payload.name,
        "--bundle-id".to_string(),
        payload.bundle_identifier,
    ];
    if let Some(directory) = payload.directory.filter(|value| !value.trim().is_empty()) {
        args.push("--directory".to_string());
        args.push(directory);
    }
    if payload.install_dependencies.unwrap_or(false) {
        args.push("--install-dependencies".to_string());
    }
    run_agent_cli_json(
        &app,
        None,
        "ios-studio-create",
        ios_cli_target_args(payload.root, args),
        1200,
    )
    .await
}

#[tauri::command]
async fn save_ios_builder_command(
    app: AppHandle,
    payload: IosStudioBuilderPayload,
) -> Result<Value, String> {
    let mut args = vec![
        "--host".to_string(),
        payload.host,
        "--user".to_string(),
        payload.user,
        "--port".to_string(),
        payload.port.unwrap_or(22).to_string(),
    ];
    if let Some(label) = payload.label.filter(|value| !value.trim().is_empty()) {
        args.push("--label".to_string());
        args.push(label);
    }
    if let Some(remote_root) = payload.remote_root.filter(|value| !value.trim().is_empty()) {
        args.push("--remote-root".to_string());
        args.push(remote_root);
    }
    if let Some(identity_file) = payload
        .identity_file
        .filter(|value| !value.trim().is_empty())
    {
        args.push("--identity-file".to_string());
        args.push(identity_file);
    }
    if let Some(team_id) = payload
        .apple_team_id
        .filter(|value| !value.trim().is_empty())
    {
        args.push("--apple-team-id".to_string());
        args.push(team_id);
    }
    if let Some(policy) = payload
        .known_hosts_policy
        .filter(|value| !value.trim().is_empty())
    {
        args.push("--known-hosts-policy".to_string());
        args.push(policy);
    }
    run_agent_cli_json(
        &app,
        None,
        "ios-studio-builder-save",
        ios_cli_target_args(payload.root, args),
        120,
    )
    .await
}

#[tauri::command]
async fn probe_ios_builder_command(
    app: AppHandle,
    payload: Option<IosStudioRootPayload>,
) -> Result<Value, String> {
    let target_root = payload.and_then(|item| item.root);
    run_agent_cli_json(
        &app,
        None,
        "ios-studio-builder-check",
        ios_cli_target_args(target_root, vec![]),
        120,
    )
    .await
}

#[tauri::command]
async fn install_windows_ios_toolchain_command(
    app: AppHandle,
    payload: Option<IosStudioWindowsPayload>,
) -> Result<Value, String> {
    let payload = payload.unwrap_or_default();
    let mut args = Vec::new();
    if let Some(engine) = payload.engine.filter(|value| !value.trim().is_empty()) {
        args.push("--engine".to_string());
        args.push(engine);
    }
    if let Some(distro) = payload.distro.filter(|value| !value.trim().is_empty()) {
        args.push("--distro".to_string());
        args.push(distro);
    }
    run_agent_cli_json(
        &app,
        None,
        "ios-studio-windows-setup",
        ios_cli_target_args(payload.root, args),
        2400,
    )
    .await
}

#[tauri::command]
async fn save_windows_ios_config_command(
    app: AppHandle,
    payload: Option<IosStudioWindowsPayload>,
) -> Result<Value, String> {
    let payload = payload.unwrap_or_default();
    let mut args = vec![
        "--engine".to_string(),
        payload.engine.unwrap_or_else(|| "auto".to_string()),
        "--distro".to_string(),
        payload.distro.unwrap_or_else(|| "default".to_string()),
        "--minimum-ios".to_string(),
        payload.minimum_ios.unwrap_or_else(|| "16.0".to_string()),
    ];
    if let Some(value) = payload
        .identity_file
        .filter(|value| !value.trim().is_empty())
    {
        args.push("--identity-file".to_string());
        args.push(value);
    }
    if let Some(value) = payload
        .certificate_file
        .filter(|value| !value.trim().is_empty())
    {
        args.push("--certificate-file".to_string());
        args.push(value);
    }
    if let Some(value) = payload
        .provisioning_profile
        .filter(|value| !value.trim().is_empty())
    {
        args.push("--provisioning-profile".to_string());
        args.push(value);
    }
    run_agent_cli_json(
        &app,
        None,
        "ios-studio-windows-save",
        ios_cli_target_args(payload.root, args),
        120,
    )
    .await
}

#[tauri::command]
async fn start_ios_preview_command(
    app: AppHandle,
    payload: Option<IosStudioPreviewPayload>,
) -> Result<Value, String> {
    let payload = payload.unwrap_or_default();
    let mut args = vec![
        "--port".to_string(),
        payload.port.unwrap_or(19006).to_string(),
    ];
    if payload.install_dependencies == Some(false) {
        args.push("--no-install".to_string());
    }
    run_agent_cli_json(
        &app,
        None,
        "ios-studio-preview-start",
        ios_cli_target_args(payload.root, args),
        1200,
    )
    .await
}

#[tauri::command]
async fn stop_ios_preview_command(
    app: AppHandle,
    payload: Option<IosStudioRootPayload>,
) -> Result<Value, String> {
    let target_root = payload.and_then(|item| item.root);
    run_agent_cli_json(
        &app,
        None,
        "ios-studio-preview-stop",
        ios_cli_target_args(target_root, vec![]),
        120,
    )
    .await
}

#[tauri::command]
async fn start_ios_build_command(
    app: AppHandle,
    payload: Option<IosStudioBuildPayload>,
) -> Result<Value, String> {
    let payload = payload.unwrap_or_default();
    let timeout_seconds = payload.timeout_seconds.unwrap_or(3600).clamp(300, 7200);
    let args = vec![
        "--mode".to_string(),
        payload.mode.unwrap_or_else(|| "simulator".to_string()),
        "--timeout-seconds".to_string(),
        timeout_seconds.to_string(),
    ];
    run_agent_cli_json(
        &app,
        None,
        "ios-studio-build",
        ios_cli_target_args(payload.root, args),
        timeout_seconds + 60,
    )
    .await
}

#[tauri::command]
async fn attach_verifier_proof_command(
    app: AppHandle,
    payload: AttachVerifierProofPayload,
) -> Result<Value, String> {
    let mission_id = payload
        .mission_id
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| "ui_bridge_verifier".to_string());
    let artifacts_json = serde_json::to_string(&payload.artifacts.unwrap_or_default())
        .map_err(|err| format!("Failed to encode verifier artifacts: {err}"))?;
    let checks_json = serde_json::to_string(&payload.checks.unwrap_or_default())
        .map_err(|err| format!("Failed to encode verifier checks: {err}"))?;

    let mut args = vec!["--mission-id".to_string(), mission_id];
    if let Some(flow_id) = payload.flow_id.filter(|value| !value.trim().is_empty()) {
        args.push("--flow-id".to_string());
        args.push(flow_id);
    }
    if let Some(report_path) = payload.report_path.filter(|value| !value.trim().is_empty()) {
        args.push("--report-path".to_string());
        args.push(report_path);
    }
    args.push("--artifacts-json".to_string());
    args.push(artifacts_json);
    args.push("--checks-json".to_string());
    args.push(checks_json);

    run_agent_cli_json(&app, payload.root, "attach-verifier-proof", args, 120).await
}

#[tauri::command]
async fn get_real_agent_runtime_proof_status_command(
    app: AppHandle,
    payload: Option<AutonomyDashboardPayload>,
) -> Result<Value, String> {
    run_agent_cli_json(
        &app,
        payload.and_then(|item| item.root),
        "real-agent-proof-status",
        vec![],
        120,
    )
    .await
}

#[tauri::command]
async fn run_real_agent_runtime_proof_command(
    app: AppHandle,
    payload: Option<RealAgentRuntimeProofPayload>,
) -> Result<Value, String> {
    let payload = payload.unwrap_or_default();
    let mut args = Vec::new();
    if let Some(runtime) = payload.runtime.filter(|value| !value.trim().is_empty()) {
        args.push("--runtime".to_string());
        args.push(runtime);
    }
    if let Some(runtime_timeout) = payload.runtime_timeout {
        args.push("--runtime-timeout".to_string());
        args.push(runtime_timeout.to_string());
    }
    if payload.with_browser.unwrap_or(false) {
        args.push("--with-browser".to_string());
    }
    run_agent_cli_json(&app, payload.root, "real-agent-proof-run", args, 900).await
}

#[tauri::command]
async fn run_authenticated_live_agent_proof_command(
    app: AppHandle,
    payload: AuthenticatedLiveAgentProofPayload,
) -> Result<Value, String> {
    let workspace_root = resolve_workspace_root(payload.root.clone())?;
    let script_path = workspace_root
        .join("scripts")
        .join("verify_authenticated_live_agent.py");
    if !script_path.exists() {
        return Err(format!(
            "Authenticated live-Agent verifier is missing: {}",
            script_path.to_string_lossy()
        ));
    }

    let interpreter = runtime_env::resolve_backend_python(&workspace_root).await?;
    let mut command = interpreter.command();
    hide_child_console(&mut command);
    command.current_dir(&workspace_root);
    inject_agent_cli_pythonpath(&mut command, &workspace_root);
    command.arg(&script_path);
    if let Some(mission_id) = payload.mission_id.filter(|value| !value.trim().is_empty()) {
        command.arg("--mission-id").arg(mission_id);
    }
    if let Some(url) = payload.url.filter(|value| !value.trim().is_empty()) {
        command.arg("--url").arg(url);
    }
    if let Some(out_dir) = payload.out_dir.filter(|value| !value.trim().is_empty()) {
        command.arg("--out-dir").arg(out_dir);
    }
    if let Some(name) = payload.name.filter(|value| !value.trim().is_empty()) {
        command.arg("--name").arg(name);
    }
    if let Some(browser) = payload.browser.filter(|value| !value.trim().is_empty()) {
        command.arg("--browser").arg(browser);
    }
    let timeout_ms = payload.timeout_ms.unwrap_or(120_000).clamp(30_000, 600_000);
    command
        .arg("--global-timeout-ms")
        .arg(timeout_ms.to_string());
    if payload.with_browser.unwrap_or(false) {
        command.arg("--expanded-interactions");
    }
    inject_agent_cli_provider_env(&app, &mut command)?;

    append_audit_entry(
        &app,
        "authenticated_live_agent.proof_run",
        json!({
            "schema": "fluxio.authenticated_live_agent_proof_run.v1",
            "workspaceRoot": workspace_root.to_string_lossy().to_string(),
            "script": "scripts/verify_authenticated_live_agent.py",
        }),
    );

    let output = timeout(Duration::from_millis(timeout_ms + 30_000), command.output())
        .await
        .map_err(|_| {
            format!(
                "verify_authenticated_live_agent.py timed out after {}ms",
                timeout_ms
            )
        })?
        .map_err(|err| format!("Failed to run verify_authenticated_live_agent.py: {err}"))?;

    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    let report = serde_json::from_str::<Value>(&stdout).unwrap_or_else(|_| {
        json!({
            "schema": "fluxio.authenticated_live_agent_proof_run.v1",
            "ok": false,
            "returnCode": output.status.code().unwrap_or(-1),
            "stdoutPreview": stdout.chars().take(800).collect::<String>(),
            "stderrPreview": stderr.chars().take(800).collect::<String>(),
        })
    });
    Ok(json!({
        "schema": "fluxio.authenticated_live_agent_proof_run.v1",
        "ok": output.status.success() && report.get("ok").and_then(Value::as_bool).unwrap_or(false),
        "returnCode": output.status.code().unwrap_or(-1),
        "report": report,
    }))
}

#[tauri::command]
fn has_telegram_bot_token_command() -> Result<bool, String> {
    Ok(load_telegram_bot_token()?.is_some())
}

#[tauri::command]
fn save_telegram_bot_token_command(app: AppHandle, token: String) -> Result<bool, String> {
    if token.trim().is_empty() {
        return Err("Telegram bot token cannot be empty".to_string());
    }
    save_telegram_bot_token(&token)?;
    append_audit_entry(&app, "telegram.token_saved", json!({ "saved": true }));
    Ok(true)
}

#[tauri::command]
fn clear_telegram_bot_token_command(app: AppHandle) -> Result<bool, String> {
    clear_telegram_bot_token()?;
    append_audit_entry(&app, "telegram.token_cleared", json!({ "cleared": true }));
    Ok(true)
}

#[tauri::command]
async fn send_telegram_message_command(
    app: AppHandle,
    payload: TelegramMessagePayload,
) -> Result<Value, String> {
    let response = send_telegram_message(&payload.chat_id, &payload.text).await?;
    append_audit_entry(
        &app,
        "telegram.message_sent",
        json!({ "chatId": payload.chat_id }),
    );
    Ok(response)
}

#[tauri::command]
async fn run_agent_vibe_status_command(
    app: AppHandle,
    payload: Option<AutonomyDashboardPayload>,
) -> Result<Value, String> {
    run_agent_cli_json(
        &app,
        payload.and_then(|item| item.root),
        "vibe-status",
        vec![],
        120,
    )
    .await
}

#[tauri::command]
async fn run_agent_vibe_continue_command(
    app: AppHandle,
    payload: AgentLoopPayload,
) -> Result<Value, String> {
    let cycles = payload.cycles.unwrap_or(2).clamp(1, 20);
    let iterations = payload.iterations.unwrap_or(4).clamp(1, 24);

    let mut args = vec![
        "--cycles".to_string(),
        cycles.to_string(),
        "--iterations".to_string(),
        iterations.to_string(),
    ];
    if let Some(mode) = payload.mode.filter(|value| !value.trim().is_empty()) {
        args.push("--mode".to_string());
        args.push(mode);
    }
    if let Some(profile) = payload.profile.filter(|value| !value.trim().is_empty()) {
        args.push("--profile".to_string());
        args.push(profile);
    }
    if let Some(merge_policy) = payload
        .merge_policy
        .filter(|value| !value.trim().is_empty())
    {
        args.push("--merge-policy".to_string());
        args.push(merge_policy);
    }

    run_agent_cli_json(&app, payload.root, "vibe-continue", args, 600).await
}

#[tauri::command]
async fn run_agent_soak_command(
    app: AppHandle,
    payload: AgentSoakPayload,
) -> Result<Value, String> {
    let objective = payload.objective.trim().to_string();
    if objective.is_empty() {
        return Err("Soak objective cannot be empty".to_string());
    }

    let cycles = payload.cycles.unwrap_or(2).clamp(1, 20);
    let iterations = payload.iterations.unwrap_or(2).clamp(1, 24);

    let mut args = vec![
        "--objective".to_string(),
        objective,
        "--cycles".to_string(),
        cycles.to_string(),
        "--iterations".to_string(),
        iterations.to_string(),
    ];
    if let Some(mode) = payload.mode.filter(|value| !value.trim().is_empty()) {
        args.push("--mode".to_string());
        args.push(mode);
    }
    if let Some(profile) = payload.profile.filter(|value| !value.trim().is_empty()) {
        args.push("--profile".to_string());
        args.push(profile);
    }
    if let Some(merge_policy) = payload
        .merge_policy
        .filter(|value| !value.trim().is_empty())
    {
        args.push("--merge-policy".to_string());
        args.push(merge_policy);
    }
    for doc in payload.docs.unwrap_or_default() {
        if !doc.trim().is_empty() {
            args.push("--doc".to_string());
            args.push(doc);
        }
    }

    run_agent_cli_json(&app, payload.root, "soak", args, 900).await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn desktop_backend_deadline_keeps_chat_and_quick_calls_distinct() {
        let default_chat = desktop_backend_timeout_seconds("send_agent_chat_command", &json!({}));
        assert_eq!(default_chat, None);
        assert_eq!(
            desktop_backend_timeout_seconds("send_agent_chat_command", &json!({"runtimeTimeoutSeconds": 0})),
            None
        );
        assert_eq!(
            desktop_backend_timeout_seconds(
                "send_agent_chat_command",
                &json!({"runtimeTimeoutSeconds": 7_200}),
            ),
            Some(7_260)
        );
        assert_eq!(
            desktop_backend_timeout_seconds(
                "send_agent_chat_command",
                &json!({"runtimeTimeoutSeconds": 15}),
            ),
            Some(75)
        );
        assert_eq!(
            desktop_backend_timeout_seconds("get_agent_chat_stream_command", &json!({})),
            Some(120)
        );
        assert_eq!(
            desktop_backend_timeout_seconds(
                "save_workspace_profile_command",
                &json!({"timeoutSeconds": 900}),
            ),
            Some(960)
        );
    }

    #[cfg(windows)]
    #[tokio::test]
    async fn desktop_backend_deadline_allows_a_real_process_to_finish_after_180_seconds() {
        let script = r#"Start-Sleep -Seconds 181; [Console]::Out.Write('{"ok":true}')"#;
        let mut child = TokioCommand::new("powershell.exe")
            .args([
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .expect("PowerShell fixture process should start");
        let (_status, stdout, _stderr) = wait_for_desktop_backend_child(&mut child, None)
            .await
            .expect("the desktop process should survive beyond the former 180-second cutoff");
        assert_eq!(stdout, br#"{"ok":true}"#);
        assert!(child.id().is_none(), "completed process should be reaped");
    }

    #[cfg(windows)]
    #[tokio::test]
    async fn desktop_backend_deadline_kills_and_reaps_a_timed_out_process() {
        let mut child = TokioCommand::new("powershell.exe")
            .args([
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Start-Sleep -Seconds 30",
            ])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .expect("PowerShell fixture process should start");
        let error = wait_for_desktop_backend_child(&mut child, Some(1))
            .await
            .expect_err("the bounded quick deadline should reject a slow process");
        assert!(error.contains("timed out after 1 seconds"));
        assert!(error.contains("stopped and reaped"), "{error}");
        assert!(child.id().is_none(), "timed out process should be reaped");
    }

    #[test]
    fn pending_queue_caps_and_tracks_length() {
        let mut state = OpenClawState::new();
        for index in 0..(OPENCLAW_MAX_PENDING_OUTBOUND + 12) {
            state.push_pending_outbound(format!("msg_{index}"), false);
        }

        assert_eq!(state.pending_outbound.len(), OPENCLAW_MAX_PENDING_OUTBOUND);
        assert_eq!(state.status.queued_outbound, OPENCLAW_MAX_PENDING_OUTBOUND);
        assert_eq!(
            state.pending_outbound.front().cloned(),
            Some("msg_12".to_string())
        );
    }

    #[test]
    fn take_pending_outbound_clears_queue_and_status() {
        let mut state = OpenClawState::new();
        state.push_pending_outbound("a".to_string(), false);
        state.push_pending_outbound("b".to_string(), false);

        let drained = state.take_pending_outbound();
        assert_eq!(drained, vec!["a".to_string(), "b".to_string()]);
        assert!(state.pending_outbound.is_empty());
        assert_eq!(state.status.queued_outbound, 0);
    }

    #[test]
    fn remember_event_id_detects_duplicates_and_evicts_oldest() {
        let mut state = OpenClawState::new();
        for index in 0..OPENCLAW_MAX_RECENT_EVENT_IDS {
            assert!(!state.remember_event_id(&format!("evt_{index}")));
        }

        assert!(state.remember_event_id("evt_2"));
        assert!(!state.remember_event_id(&format!("evt_{OPENCLAW_MAX_RECENT_EVENT_IDS}")));
        assert!(!state.remember_event_id("evt_0"));
    }

    #[test]
    fn gateway_identity_prefers_event_id_then_fallback() {
        let event = GatewayInboundEvent::Clarify {
            event_id: Some("evt_123".to_string()),
            question_id: Some("q_1".to_string()),
            question: "Q?".to_string(),
            choices: vec!["A".to_string()],
        };
        assert_eq!(gateway_event_identity(&event), Some("evt_123".to_string()));

        let fallback = GatewayInboundEvent::ActionRequest {
            event_id: None,
            request_id: Some("req_1".to_string()),
            tool_id: "tool.safe.echo".to_string(),
            args: json!({}),
        };
        assert_eq!(gateway_event_identity(&fallback), Some("req_1".to_string()));
    }

    #[test]
    fn gateway_validation_rejects_empty_event_id() {
        let event = GatewayInboundEvent::AgentMessage {
            event_id: Some("   ".to_string()),
            content: "hello".to_string(),
        };

        let result = validate_gateway_event(&event);
        assert!(result.is_err());
    }

    #[test]
    fn pending_ack_register_and_acknowledge_updates_status() {
        let mut state = OpenClawState::new();
        state.register_pending_ack("msg_1".to_string(), "{\"messageId\":\"msg_1\"}".to_string());
        state.register_pending_ack("msg_2".to_string(), "{\"messageId\":\"msg_2\"}".to_string());

        assert_eq!(state.status.pending_ack_count, 2);
        assert!(state.acknowledge_pending_ack("msg_1"));
        assert_eq!(state.status.pending_ack_count, 1);
        assert_eq!(
            state.status.last_acked_message_id,
            Some("msg_1".to_string())
        );
    }

    #[test]
    fn outbound_envelope_adds_message_metadata() {
        let payload = json!({ "type": "user.message", "content": "hello" });
        let wrapped = with_openclaw_envelope(payload);
        let obj = wrapped.as_object().expect("payload should be object");

        assert_eq!(
            obj.get("type").and_then(Value::as_str),
            Some("user.message")
        );
        assert!(obj.get("messageId").and_then(Value::as_str).is_some());
        assert!(obj.get("nonce").and_then(Value::as_str).is_some());
        assert_eq!(obj.get("ackRequested").and_then(Value::as_bool), Some(true));
        assert!(obj.get("integrity").and_then(Value::as_str).is_some());
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let mut builder = tauri::Builder::default().plugin(tauri_plugin_process::init());

    #[cfg(desktop)]
    {
        builder = builder.plugin(tauri_plugin_updater::Builder::new().build());
    }

    builder = builder.plugin(tauri_plugin_global_shortcut::Builder::new().build());

    if cfg!(debug_assertions) {
        builder = builder.plugin(
            tauri_plugin_log::Builder::default()
                .level(log::LevelFilter::Info)
                .build(),
        );
    }

    builder
        .manage(browser_runtime::BrowserRuntime::default())
        .invoke_handler(|invoke| {
            if browser_runtime::page_isolated(&invoke) {
                invoke.resolver.reject("Browser content may only send page events");
                return true;
            }
            let handler: fn(tauri::ipc::Invoke<tauri::Wry>) -> bool = tauri::generate_handler![
            base_pack_bridge::onboarding_base_pack_status_command,
            base_pack_bridge::onboarding_base_pack_start_command,
            base_pack_bridge::onboarding_base_pack_pause_command,
            browser_runtime::browser_runtime_start,
            browser_runtime::browser_runtime_stop,
            browser_runtime::browser_page_event,
            get_overlay_state,
            set_overlay_pinned,
            toggle_overlay_pin,
            get_performance_snapshot,
            submit_prompt,
            get_modes,
            set_mode,
            get_current_mode,
            context_capture,
            ui_ask,
            ui_answer,
            list_pending_questions,
            action_request,
            list_pending_approvals,
            resolve_action_approval,
            get_dictation_config,
            configure_dictation,
            start_dictation,
            stop_dictation,
            transcribe_audio_file,
            get_dictation_history,
            execute_control_command,
            get_localhost_status,
            configure_localhost_api,
            save_localhost_api_token_command,
            clear_localhost_api_token_command,
            has_localhost_api_token_command,
            save_provider_secret_command,
            clear_provider_secret_command,
            has_provider_secret_command,
            get_provider_secret_presence_command,
            get_openai_codex_oauth_status_command,
            start_openai_codex_oauth_command,
            complete_openai_codex_oauth_command,
            clear_openai_codex_oauth_command,
            get_minimax_openclaw_auth_status_command,
            start_minimax_openclaw_auth_command,
            get_openclaw_status,
            connect_openclaw_gateway,
            disconnect_openclaw_gateway,
            save_openclaw_gateway_token,
            clear_openclaw_gateway_token,
            has_openclaw_gateway_token,
            send_openclaw_message,
            get_night_mode_config,
            configure_night_mode,
            run_night_mode_now,
            get_last_night_mode_report,
            get_audit_log,
            get_autonomy_dashboard_snapshot,
            get_control_room_snapshot_command,
            get_control_room_summary_command,
            call_desktop_backend_command,
            get_native_tool_catalog_command,
            get_skill_library_command,
            call_native_tool_command,
            inspect_codex_import_command,
            open_external_url_command,
            pick_folder_command,
            import_agent_prompt_file_command,
            get_onboarding_status_command,
            export_control_room_data_command,
            save_workspace_profile_command,
            delete_workspace_profile_command,
            start_control_room_mission_command,
            quickstart_control_room_mission_command,
            apply_control_room_mission_action_command,
            send_control_room_mission_follow_up_command,
            apply_control_room_workspace_action_command,
            get_nas_storage_pressure_command,
            get_ios_studio_status_command,
            create_ios_app_command,
            save_ios_builder_command,
            probe_ios_builder_command,
            install_windows_ios_toolchain_command,
            save_windows_ios_config_command,
            start_ios_preview_command,
            stop_ios_preview_command,
            start_ios_build_command,
            attach_verifier_proof_command,
            get_real_agent_runtime_proof_status_command,
            run_real_agent_runtime_proof_command,
            run_authenticated_live_agent_proof_command,
            has_telegram_bot_token_command,
            save_telegram_bot_token_command,
            clear_telegram_bot_token_command,
            send_telegram_message_command,
            run_agent_vibe_status_command,
            run_agent_vibe_continue_command,
            run_agent_soak_command
        ]; handler(invoke) })
        .setup(|app| {
            app.manage(base_pack_bridge::PackService::default());
            let config_dir = app.path().app_config_dir()?;
            let settings_path = config_dir.join(SETTINGS_FILE_NAME);
            let audit_log_path = config_dir.join(AUDIT_LOG_FILE_NAME);
            let settings = load_settings(&settings_path);

            app.manage(OverlayAppState::new(
                settings_path,
                settings,
                audit_log_path,
            ));

            configure_overlay_window(app.handle());
            build_tray(app.handle())?;

            if let Err(err) = register_hold_shortcut(app.handle()) {
                log::error!("failed to register hold-to-open shortcut: {err}");
            }

            {
                let state = app.state::<OverlayAppState>();
                if let Ok(mut perf) = state.performance.lock() {
                    perf.mark_cold_start();
                    perf.sample_idle_memory();
                };
            }

            if !base_pack_bridge::enabled() {
                let app_handle = app.handle().clone();
                tauri::async_runtime::spawn(async move {
                    let _ = start_localhost_api(&app_handle).await;
                });
            }

            // Older builds registered the website PWA worker inside WebView2.
            // Run a non-destructive migration in the loaded document: only an
            // existing worker/cache is removed, then the native shell reloads.
            let cleanup_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                sleep(Duration::from_millis(500)).await;
                if let Some(window) = cleanup_handle.get_webview_window(MAIN_WINDOW_LABEL) {
                    let _ = window.eval(DESKTOP_SERVICE_WORKER_CLEANUP_SCRIPT);
                }
            });

            if !base_pack_bridge::enabled() {
                start_night_mode_scheduler(app.handle());
                start_control_room_watch(app.handle());
            }
            #[cfg(desktop)]
            if !base_pack_bridge::enabled() { start_self_update(app.handle()); }
            append_audit_entry(
                app.handle(),
                "app.started",
                json!({ "version": "m1-m6-skeleton" }),
            );

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

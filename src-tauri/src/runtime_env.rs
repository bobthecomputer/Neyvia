//! Resolution and bootstrap of the Python backend runtime that Neyvia depends on.
//!
//! Neyvia's desktop shell is a thin Tauri window; every substantive command runs
//! through the `grant_agent` Python package. Historically the shell simply spawned
//! `python` and assumed the development source tree was on disk, which meant an
//! installed build silently failed on a clean machine. This module makes both of
//! those dependencies explicit, discoverable, and truthfully reportable:
//!
//! * [`bundled_backend_root`] locates the backend that ships inside the installer.
//! * [`resolve_python`] resolves a supported interpreter through an ordered chain
//!   and refuses to hand back a program that was never verified to exist.
//! * [`preflight`] reports what Neyvia needs, what was found, where it looked, and
//!   how to recover — without performing any installation.
//! * [`bootstrap`] performs the one installation step Neyvia can own itself:
//!   creating and populating its managed dependency environment.

use std::{
    path::{Path, PathBuf},
    process::Stdio,
    sync::{Mutex, OnceLock},
};

use serde::Serialize;
use std::sync::atomic::{AtomicBool, Ordering};
static SIGNED_BASE_VERIFIED: AtomicBool = AtomicBool::new(false);

pub fn confirm_base_pack_verified() { SIGNED_BASE_VERIFIED.store(true, Ordering::Release); }
use serde_json::{json, Value};
use tokio::process::Command as TokioCommand;
use tokio::sync::Mutex as AsyncMutex;

/// Lowest interpreter Neyvia's backend supports, mirroring `requires-python` in
/// `pyproject.toml`. Keep the two in sync.
pub const MIN_PYTHON: (u32, u32) = (3, 11);

/// Third-party distributions the backend imports at runtime. These mirror the
/// `dependencies` list in `pyproject.toml`; the bundled requirements file is the
/// authority used for installation, this list is what preflight verifies.
const REQUIRED_DISTRIBUTIONS: &[(&str, &str)] = &[
    ("blake3", "Content hashing for artifact and receipt lineage"),
    ("cryptography", "Signature verification for proofs and receipts"),
    ("ddgs", "Web search tool backend"),
    ("jsonschema", "Validation of mission, plan, and contract payloads"),
    ("websockets", "Installed desktop Preview can inspect Chrome or Edge without Playwright"),
];

/// Where a resolved interpreter came from. Reported to the operator so a wrong
/// interpreter can be diagnosed without guesswork.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum PythonSource {
    /// `NEYVIA_PYTHON` pointed at it explicitly.
    EnvOverride,
    /// A project-local virtual environment beside Neyvia's source tree.
    Workspace,
    /// Neyvia's own managed virtual environment.
    Managed,
    /// Found on the host via the launcher or `PATH`.
    Host,
}

/// A Python interpreter that has been executed and confirmed to be supported.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PythonInterpreter {
    /// Program to spawn.
    pub program: String,
    /// Leading arguments required before any script arguments (e.g. `-3` for `py`).
    pub prefix_args: Vec<String>,
    /// `sys.executable` as reported by the interpreter itself.
    pub executable: String,
    pub version: (u32, u32, u32),
    pub source: PythonSource,
}

impl PythonInterpreter {
    pub fn version_text(&self) -> String {
        format!("{}.{}.{}", self.version.0, self.version.1, self.version.2)
    }

    /// Build a command that invokes this interpreter. Always use this rather than
    /// `TokioCommand::new("python")` so a missing interpreter surfaces as a
    /// resolution error instead of an opaque spawn failure.
    pub fn command(&self) -> TokioCommand {
        let mut command = TokioCommand::new(&self.program);
        // The packaged backend is an immutable application resource. Prevent
        // normal imports from recreating __pycache__ beside those resources and
        // making a verified thin bundle dirty after its first real invocation.
        command.env("PYTHONDONTWRITEBYTECODE", "1");
        for arg in &self.prefix_args {
            command.arg(arg);
        }
        command
    }
}

fn python_cache() -> &'static Mutex<Option<PythonInterpreter>> {
    static CACHE: OnceLock<Mutex<Option<PythonInterpreter>>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(None))
}

fn backend_runtime_lock() -> &'static AsyncMutex<()> {
    static LOCK: OnceLock<AsyncMutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| AsyncMutex::new(()))
}

/// Drop the cached interpreter so the next resolution re-runs the chain. Called
/// after bootstrap creates the managed environment.
pub fn invalidate_python_cache() {
    SIGNED_BASE_VERIFIED.store(false, Ordering::Release);
    if let Ok(mut cache) = python_cache().lock() {
        *cache = None;
    }
}

fn home_dir_path() -> Option<PathBuf> {
    std::env::var_os("USERPROFILE")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(PathBuf::from))
}

/// Per-user directory holding Neyvia's managed runtime, logs, and state. This is
/// deliberately outside the install directory so it survives upgrades and does not
/// require elevation.
pub fn managed_root() -> Option<PathBuf> {
    if let Some(root) = std::env::var_os("NEYVIA_RUNTIME_ROOT") {
        return Some(PathBuf::from(root));
    }
    #[cfg(windows)]
    {
        if let Some(local) = std::env::var_os("LOCALAPPDATA") {
            return Some(PathBuf::from(local).join("Neyvia"));
        }
    }
    home_dir_path().map(|home| home.join(".neyvia"))
}

/// Root of Neyvia's managed virtual environment.
pub fn managed_venv_root() -> Option<PathBuf> {
    managed_root().map(|root| root.join("runtime").join("venv"))
}

/// Path the interpreter takes inside a virtual environment on this platform.
fn venv_python_path(venv_root: &Path) -> PathBuf {
    if cfg!(windows) {
        venv_root.join("Scripts").join("python.exe")
    } else {
        venv_root.join("bin").join("python")
    }
}

/// True when `root` looks like a usable Neyvia backend root — i.e. it contains the
/// `grant_agent` package the shell invokes.
pub fn is_backend_root(root: &Path) -> bool {
    root.join("src").join("grant_agent").join("cli.py").exists()
}

fn bundled_backend_candidates(exe_dir: &Path) -> Vec<PathBuf> {
    let direct = exe_dir.join("backend");
    let resources = exe_dir.join("resources").join("backend");
    let macos_resources = exe_dir
        .parent()
        .map(|parent| parent.join("Resources").join("backend"))
        .unwrap_or_else(|| resources.clone());
    vec![direct, resources, macos_resources]
}

/// Locate the backend that ships inside the installer.
///
/// The bundle lays the backend out so that the resource directory is itself a
/// valid workspace root (`resources/backend/src/grant_agent/...`), which lets every
/// existing call site treat bundled and development installs identically. Derived
/// from the executable path rather than a Tauri `AppHandle` so it is callable from
/// synchronous helpers that have no handle available.
pub fn bundled_backend_root() -> Option<PathBuf> {
    if crate::base_pack_bridge::enabled() {
        return active_base_runtime().map(|(backend,_python)|backend);
    }
    let exe = std::env::current_exe().ok()?;
    let exe_dir = exe.parent()?;

    // A resource whose target is `backend/...` is staged directly as
    // `<exe-dir>/backend` by Tauri on Windows and Linux. Older packages used a
    // `<exe-dir>/resources/backend` wrapper, while macOS puts resources in
    // `Contents/Resources`. Keep all three layouts readable so upgrades do not
    // strand an otherwise complete installation.
    let candidates = bundled_backend_candidates(exe_dir);

    candidates
        .into_iter()
        .find(|candidate| is_backend_root(candidate))
}

/// Activation is written only after signature, hashes and the real import probe pass.
pub fn active_base_runtime() -> Option<(PathBuf, PathBuf)> {
    let pack = managed_root()?.join("base-pack");
    let active: Value = serde_json::from_slice(&std::fs::read(pack.join("active.json")).ok()?).ok()?;
    let digest = active["manifestSha256"].as_str()?;
    if digest.len()!=64 || !digest.bytes().all(|c|c.is_ascii_hexdigit()) { return None; }
    let target = pack.join("versions").join(digest);
    if active["target"].as_str()? != target.to_string_lossy() { return None; }
    let python = active["python"].as_str()?;
    let backend = active["backend"].as_str()?;
    let safe = |s:&str| !s.contains(['\\',':']) && !s.starts_with('/') && s.split('/').all(|p| !p.is_empty() && p!=".." && p!=".");
    if !safe(python) || (backend!="." && !safe(backend)) { return None; }
    let source = if backend=="." {target.clone()} else {target.join(backend)};
    let interpreter = target.join(python);
    (is_backend_root(&source) && interpreter.is_file()).then_some((source,interpreter))
}

/// Requirements file shipped alongside the bundled backend, used by [`bootstrap`].
fn bundled_requirements_path() -> Option<PathBuf> {
    let root = bundled_backend_root()?;
    let path = root.join("backend-requirements.txt");
    path.exists().then_some(path)
}

/// Marker written inside the managed environment after a good install. It holds the SHA-256 of the
/// `backend-requirements.txt` that produced the environment, so an app update that changes the
/// pinned packages is noticed (the Python side, `grant_agent/venv_sync.py`, writes the same file).
const REQUIREMENTS_MARKER: &str = ".neyvia-requirements.json";

/// SHA-256 of the requirements file with Windows line endings normalised.
fn requirements_hash(path: &Path) -> Option<String> {
    use sha2::{Digest, Sha256};
    let bytes = std::fs::read(path).ok()?;
    let mut normalised = Vec::with_capacity(bytes.len());
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == b'\r' && bytes.get(index + 1) == Some(&b'\n') {
            index += 1;
            continue;
        }
        normalised.push(bytes[index]);
        index += 1;
    }
    Some(format!("{:x}", Sha256::digest(&normalised)))
}

fn recorded_requirements_hash(venv_root: &Path) -> Option<String> {
    let text = std::fs::read_to_string(venv_root.join(REQUIREMENTS_MARKER)).ok()?;
    let value: Value = serde_json::from_str(&text).ok()?;
    value["sha256"].as_str().map(str::to_string)
}

fn write_requirements_marker(venv_root: &Path, hash: &str) -> Result<(), String> {
    let seconds = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let body = json!({
        "schema": "neyvia.venv_requirements.v1",
        "sha256": hash,
        "installedAtUnix": seconds,
        "appVersion": env!("CARGO_PKG_VERSION"),
    });
    let marker = venv_root.join(REQUIREMENTS_MARKER);
    let temp = venv_root.join(format!("{REQUIREMENTS_MARKER}.tmp"));
    std::fs::write(&temp, serde_json::to_vec_pretty(&body).unwrap_or_default())
        .and_then(|_| std::fs::rename(&temp, &marker))
        .map_err(|err| format!("Could not record the installed requirements: {err}"))
}

/// Install the pinned, hash-checked requirements into the managed environment.
async fn pip_install_requirements(venv_python: &Path, requirements_path: &Path) -> Result<(), String> {
    let mut install = TokioCommand::new(venv_python);
    install
        .arg("-m")
        .arg("pip")
        .arg("install")
        .arg("--require-hashes")
        .arg("--only-binary=:all:")
        .arg("-r")
        .arg(requirements_path)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        install.creation_flags(0x0800_0000);
    }
    let output = install
        .output()
        .await
        .map_err(|err| format!("Failed to run pip in Neyvia's managed environment: {err}"))?;
    if !output.status.success() {
        return Err(format!(
            "Installing Neyvia's dependencies failed:\n{}\n\nYou can retry, or install \
             them manually with:\n  \"{}\" -m pip install -r \"{}\"",
            String::from_utf8_lossy(&output.stderr).trim(),
            venv_python.display(),
            requirements_path.display()
        ));
    }
    Ok(())
}

/// After an app update: when the bundled requirements differ from what the managed environment
/// was built from (or nothing was recorded by an older Neyvia), install them again. `Ok(None)`
/// means nothing was needed. The recorded hash changes only after a successful install, so a
/// failure retries on the next start and leaves the working environment as it was.
pub async fn sync_managed_requirements() -> Result<Option<Value>, String> {
    let Some(venv_root) = managed_venv_root() else { return Ok(None) };
    let venv_python = venv_python_path(&venv_root);
    let Some(requirements_path) = bundled_requirements_path() else { return Ok(None) };
    if !venv_python.exists() {
        return Ok(None);
    }
    let Some(wanted) = requirements_hash(&requirements_path) else { return Ok(None) };
    let recorded = recorded_requirements_hash(&venv_root);
    if recorded.as_deref() == Some(wanted.as_str()) {
        return Ok(None);
    }
    pip_install_requirements(&venv_python, &requirements_path).await?;
    write_requirements_marker(&venv_root, &wanted)?;
    invalidate_python_cache();
    Ok(Some(json!({
        "step": "sync_dependencies",
        "state": "completed",
        "previousHash": recorded,
        "requirementsHash": wanted,
    })))
}

/// Run an interpreter candidate and return it only if it actually executes and
/// reports a supported version. A candidate that cannot be spawned is not an
/// error — it simply is not the interpreter we are looking for.
async fn probe_interpreter(
    program: &str,
    prefix_args: &[&str],
    source: PythonSource,
) -> Option<PythonInterpreter> {
    let mut command = TokioCommand::new(program);
    for arg in prefix_args {
        command.arg(arg);
    }
    command
        .arg("-c")
        .arg("import sys; print('%d %d %d' % sys.version_info[:3]); print(sys.executable)")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }

    let output = command.output().await.ok()?;
    if !output.status.success() {
        return None;
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut lines = stdout.lines();
    let version_line = lines.next()?.trim();
    let executable = lines.next().unwrap_or_default().trim().to_string();

    let parts: Vec<u32> = version_line
        .split_whitespace()
        .filter_map(|part| part.parse().ok())
        .collect();
    if parts.len() < 3 {
        return None;
    }
    let version = (parts[0], parts[1], parts[2]);
    if (version.0, version.1) < MIN_PYTHON {
        return None;
    }

    Some(PythonInterpreter {
        program: program.to_string(),
        prefix_args: prefix_args.iter().map(|arg| arg.to_string()).collect(),
        executable,
        version,
        source,
    })
}

/// Ordered list of the places Neyvia looks for an interpreter, used both by
/// resolution and by preflight reporting so the two can never disagree.
fn interpreter_search_plan() -> Vec<(String, Vec<String>, PythonSource, String)> {
    let mut plan = Vec::new();
    if let Some((_backend,python)) = active_base_runtime().filter(|_|crate::base_pack_bridge::enabled()) {
        plan.push((python.to_string_lossy().into(),Vec::new(),PythonSource::Managed,"Signed base-pack Python".into()));
    }

    if let Some(explicit) = std::env::var_os("NEYVIA_PYTHON") {
        let path = PathBuf::from(&explicit);
        plan.push((
            path.to_string_lossy().to_string(),
            Vec::new(),
            PythonSource::EnvOverride,
            "NEYVIA_PYTHON environment override".to_string(),
        ));
    }

    if let Some(venv_root) = managed_venv_root() {
        let python = venv_python_path(&venv_root);
        plan.push((
            python.to_string_lossy().to_string(),
            Vec::new(),
            PythonSource::Managed,
            format!("Neyvia managed environment ({})", venv_root.display()),
        ));
    }

    // The Windows launcher is preferred over a bare `python` because on a clean
    // Windows install `python.exe` is frequently the Microsoft Store stub, which
    // executes but is not a usable interpreter.
    if cfg!(windows) {
        plan.push((
            "py".to_string(),
            vec!["-3".to_string()],
            PythonSource::Host,
            "Windows Python launcher (py -3)".to_string(),
        ));
    }
    plan.push((
        "python3".to_string(),
        Vec::new(),
        PythonSource::Host,
        "python3 on PATH".to_string(),
    ));
    plan.push((
        "python".to_string(),
        Vec::new(),
        PythonSource::Host,
        "python on PATH".to_string(),
    ));

    plan
}

/// Resolve a supported interpreter, or explain precisely why none is available.
///
/// The returned interpreter has been executed successfully, so callers can spawn it
/// without the "silently invoked a missing `python`" failure mode.
pub async fn resolve_python() -> Result<PythonInterpreter, String> {
    if let Ok(cache) = python_cache().lock() {
        if let Some(existing) = cache.as_ref() {
            return Ok(existing.clone());
        }
    }

    let plan = interpreter_search_plan();
    for (program, prefix_args, source, _label) in &plan {
        let refs: Vec<&str> = prefix_args.iter().map(String::as_str).collect();
        if let Some(interpreter) = probe_interpreter(program, &refs, *source).await {
            if let Ok(mut cache) = python_cache().lock() {
                *cache = Some(interpreter.clone());
            }
            return Ok(interpreter);
        }
    }

    let searched = plan
        .iter()
        .map(|(_, _, _, label)| label.clone())
        .collect::<Vec<_>>()
        .join("; ");
    Err(format!(
        "Neyvia could not find a supported Python {}.{}+ interpreter. Searched: {}. \
         Install Python {}.{} or newer, or set NEYVIA_PYTHON to an interpreter path, \
         then run Neyvia's setup check again.",
        MIN_PYTHON.0, MIN_PYTHON.1, searched, MIN_PYTHON.0, MIN_PYTHON.1
    ))
}

/// Ask an interpreter which of the required distributions it can import.
async fn probe_distributions(interpreter: &PythonInterpreter, backend_root: &Path) -> Vec<String> {
    let names: Vec<&str> = REQUIRED_DISTRIBUTIONS.iter().map(|(name, _)| *name).collect();
    let script = format!(
        "import importlib.util as u\nprint(' '.join(n for n in {names:?} if u.find_spec(n) is None))",
    );

    let mut command = interpreter.command();
    command
        .arg("-c")
        .arg(script)
        .current_dir(backend_root)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        command.creation_flags(0x0800_0000);
    }

    match command.output().await {
        Ok(output) if output.status.success() => String::from_utf8_lossy(&output.stdout)
            .split_whitespace()
            .map(str::to_string)
            .collect(),
        // If the probe itself failed we cannot claim the packages are present.
        _ => names.into_iter().map(str::to_string).collect(),
    }
}

/// Return an interpreter that can run the bundled backend, creating Neyvia's
/// private dependency environment once when a host Python is present but the
/// backend packages are not. The lock matters because the shell can issue several
/// startup reads together; concurrent `venv`/`pip` processes would corrupt the
/// environment and turn first launch into an intermittent failure.
pub async fn resolve_backend_python(
    backend_root: &Path,
) -> Result<PythonInterpreter, String> {
    let _guard = backend_runtime_lock().lock().await;
    if crate::base_pack_bridge::enabled() {
        let (_source, python) = active_base_runtime().ok_or("Signed base pack is not activated")?;
        if !SIGNED_BASE_VERIFIED.load(Ordering::Acquire) {
            crate::base_pack::verify_active(&crate::base_pack_bridge::config()?).await?;
            confirm_base_pack_verified();
        }
        let interpreter = probe_interpreter(&python.to_string_lossy(),&[],PythonSource::Managed).await.ok_or("Signed base-pack Python cannot start")?;
        let missing = probe_distributions(&interpreter,backend_root).await;
        if !missing.is_empty() { return Err(format!("Signed base pack is incomplete: {}",missing.join(", "))); }
        return Ok(interpreter);
    }

    // A source checkout owns its dependency environment. Prefer it over PATH so
    // another product's activated virtualenv (Hermes, Conda, etc.) cannot hijack
    // desktop commands. An explicit operator override remains authoritative.
    if std::env::var_os("NEYVIA_PYTHON").is_none() {
        let workspace_candidate = venv_python_path(&backend_root.join(".venv"));
        if workspace_candidate.is_file() {
            let program = workspace_candidate.to_string_lossy().to_string();
            if let Some(interpreter) =
                probe_interpreter(&program, &[], PythonSource::Workspace).await
            {
                let missing = probe_distributions(&interpreter, backend_root).await;
                if missing.is_empty() {
                    return Ok(interpreter);
                }
            }
        }
    }

    let interpreter = resolve_python().await?;
    if interpreter.source == PythonSource::Managed {
        // A failed sync keeps the working environment; it is retried on the next start.
        if let Err(error) = sync_managed_requirements().await {
            eprintln!("Neyvia could not update its managed environment: {error}");
        }
    }
    let missing = probe_distributions(&interpreter, backend_root).await;
    if missing.is_empty() {
        return Ok(interpreter);
    }

    bootstrap().await.map_err(|error| {
        format!(
            "Neyvia found Python but could not prepare its private backend environment \
             (missing: {}): {error}",
            missing.join(", ")
        )
    })?;

    let managed = resolve_python().await?;
    let still_missing = probe_distributions(&managed, backend_root).await;
    if still_missing.is_empty() {
        Ok(managed)
    } else {
        Err(format!(
            "Neyvia prepared its backend environment, but these packages are still \
             unavailable: {}.",
            still_missing.join(", ")
        ))
    }
}

fn requirement(
    id: &str,
    label: &str,
    why: &str,
    state: &str,
    detail: String,
    searched: Vec<String>,
    planned_action: Option<&str>,
    recovery: Option<&str>,
) -> Value {
    json!({
        "id": id,
        "label": label,
        "why": why,
        "state": state,
        "detail": detail,
        "searchedLocations": searched,
        "plannedAction": planned_action,
        "recovery": recovery,
    })
}

/// Report what Neyvia needs to run, what is already present, and what remains.
///
/// This performs no installation and mutates nothing. Every row carries the state
/// Neyvia can actually justify — a requirement whose probe failed is reported as
/// unverified rather than assumed satisfied.
pub async fn preflight(workspace_override: Option<PathBuf>) -> Value {
    let mut requirements = Vec::new();

    // --- Backend source -----------------------------------------------------
    let bundled = bundled_backend_root();
    let backend_root = workspace_override
        .filter(|path| is_backend_root(path))
        .or_else(|| bundled.clone())
        .or_else(|| {
            std::env::var_os("NEYVIA_WORKSPACE_ROOT")
                .map(PathBuf::from)
                .filter(|path| is_backend_root(path))
        });

    let backend_searched = vec![
        "bundled installer resources (resources/backend)".to_string(),
        "NEYVIA_WORKSPACE_ROOT environment override".to_string(),
        "development source tree".to_string(),
    ];

    match &backend_root {
        Some(root) => requirements.push(requirement(
            "backend_source",
            "Neyvia backend",
            "Every Neyvia command runs through the grant_agent backend package.",
            "ready",
            format!(
                "Found at {}{}",
                root.display(),
                if bundled.as_deref() == Some(root.as_path()) {
                    " (bundled with this installation)"
                } else {
                    " (development source tree)"
                }
            ),
            backend_searched.clone(),
            None,
            None,
        )),
        None => requirements.push(requirement(
            "backend_source",
            "Neyvia backend",
            "Every Neyvia command runs through the grant_agent backend package.",
            "missing",
            "No grant_agent backend package was found.".to_string(),
            backend_searched.clone(),
            None,
            Some(
                "This installation is incomplete. Reinstall Neyvia, or set \
                 NEYVIA_WORKSPACE_ROOT to a checkout of the Neyvia repository.",
            ),
        )),
    }

    // --- Interpreter --------------------------------------------------------
    let plan = interpreter_search_plan();
    let searched: Vec<String> = plan
        .iter()
        .map(|(_, _, _, label)| label.clone())
        .collect();
    let interpreter = resolve_python().await;

    match &interpreter {
        Ok(found) => requirements.push(requirement(
            "python",
            format!("Python {}.{}+", MIN_PYTHON.0, MIN_PYTHON.1).as_str(),
            "The Neyvia backend is a Python application; the desktop shell drives it.",
            "ready",
            format!(
                "Python {} at {} (via {})",
                found.version_text(),
                if found.executable.is_empty() {
                    found.program.clone()
                } else {
                    found.executable.clone()
                },
                found.program
            ),
            searched.clone(),
            None,
            None,
        )),
        Err(message) => requirements.push(requirement(
            "python",
            format!("Python {}.{}+", MIN_PYTHON.0, MIN_PYTHON.1).as_str(),
            "The Neyvia backend is a Python application; the desktop shell drives it.",
            "missing",
            message.clone(),
            searched.clone(),
            None,
            Some(
                "Install Python from python.org (or the Microsoft Store), then re-run \
                 this check. Neyvia does not install Python for you because it is a \
                 system-wide component.",
            ),
        )),
    }

    // --- Managed environment and dependencies -------------------------------
    let venv_root = managed_venv_root();
    let venv_exists = venv_root
        .as_ref()
        .map(|root| venv_python_path(root).exists())
        .unwrap_or(false);
    let venv_display = venv_root
        .as_ref()
        .map(|root| root.display().to_string())
        .unwrap_or_else(|| "unavailable (no user profile directory)".to_string());

    requirements.push(requirement(
        "managed_environment",
        "Neyvia managed environment",
        "Neyvia installs its Python dependencies into a private environment so it \
         never modifies your system Python.",
        if venv_exists { "ready" } else { "setup_required" },
        if venv_exists {
            format!("Present at {venv_display}")
        } else {
            format!("Not created yet. Will be created at {venv_display}")
        },
        vec![venv_display.clone()],
        (!venv_exists).then_some("Create a virtual environment and install Neyvia's pinned dependencies into it."),
        None,
    ));

    match (&interpreter, &backend_root) {
        (Ok(found), Some(root)) => {
            let missing = probe_distributions(found, root).await;
            let detail = if missing.is_empty() {
                "All required packages are importable.".to_string()
            } else {
                format!("Missing or unimportable: {}", missing.join(", "))
            };
            requirements.push(requirement(
                "backend_dependencies",
                "Backend packages",
                REQUIRED_DISTRIBUTIONS
                    .iter()
                    .map(|(name, why)| format!("{name}: {why}"))
                    .collect::<Vec<_>>()
                    .join("; ")
                    .as_str(),
                if missing.is_empty() { "ready" } else { "setup_required" },
                detail,
                vec![format!("interpreter {}", found.program)],
                (!missing.is_empty())
                    .then_some("Install the pinned dependency set into Neyvia's managed environment."),
                None,
            ));
        }
        _ => requirements.push(requirement(
            "backend_dependencies",
            "Backend packages",
            "Neyvia's backend imports these packages at runtime.",
            "unverified",
            "Could not check packages because the interpreter or backend source is \
             unavailable. Resolve those first."
                .to_string(),
            Vec::new(),
            None,
            None,
        )),
    }

    let blocking: Vec<&Value> = requirements
        .iter()
        .filter(|row| row["state"] == "missing")
        .collect();
    let setup_required: Vec<&Value> = requirements
        .iter()
        .filter(|row| row["state"] == "setup_required")
        .collect();

    json!({
        "schema": "neyvia.runtime.preflight/1",
        "requirements": requirements,
        "summary": {
            "ready": blocking.is_empty() && setup_required.is_empty(),
            "blockedCount": blocking.len(),
            "setupRequiredCount": setup_required.len(),
            // Bootstrap can only create the managed environment; it cannot install
            // Python itself, so it is only offered when the interpreter resolved.
            "canBootstrap": blocking.is_empty() && !setup_required.is_empty(),
        },
        "managedRoot": managed_root().map(|path| path.display().to_string()),
        "bundledBackendRoot": bundled.map(|path| path.display().to_string()),
    })
}

/// Create Neyvia's managed environment and install its pinned dependencies.
///
/// This is the only installation Neyvia performs on its own behalf, it targets a
/// private per-user directory, and it reports the real command output on failure
/// rather than reporting success for a step that did not run.
pub async fn bootstrap() -> Result<Value, String> {
    let interpreter = resolve_python().await?;
    let venv_root = managed_venv_root()
        .ok_or_else(|| "Could not determine a per-user directory for Neyvia's runtime.".to_string())?;

    let mut steps = Vec::new();

    // Step 1: create the virtual environment if it is not already there.
    let venv_python = venv_python_path(&venv_root);
    if !venv_python.exists() {
        if let Some(parent) = venv_root.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|err| format!("Failed to create {}: {err}", parent.display()))?;
        }
        let mut command = interpreter.command();
        command
            .arg("-m")
            .arg("venv")
            .arg(&venv_root)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        {
            command.creation_flags(0x0800_0000);
        }
        let output = command
            .output()
            .await
            .map_err(|err| format!("Failed to run `python -m venv`: {err}"))?;
        if !output.status.success() {
            return Err(format!(
                "Creating Neyvia's managed environment at {} failed:\n{}",
                venv_root.display(),
                String::from_utf8_lossy(&output.stderr).trim()
            ));
        }
        steps.push(json!({
            "step": "create_environment",
            "state": "completed",
            "detail": format!("Created {}", venv_root.display()),
        }));
    } else {
        steps.push(json!({
            "step": "create_environment",
            "state": "already_present",
            "detail": format!("Reused {}", venv_root.display()),
        }));
    }

    if !venv_python.exists() {
        return Err(format!(
            "Neyvia's managed environment was reported as created but no interpreter \
             exists at {}.",
            venv_python.display()
        ));
    }

    // Step 2: install the pinned dependency set into that environment.
    let requirements_path = bundled_requirements_path().ok_or_else(|| {
        "The pinned dependency list (backend-requirements.txt) is missing from this \
         installation. Reinstall Neyvia."
            .to_string()
    })?;

    pip_install_requirements(&venv_python, &requirements_path).await?;
    if let Some(hash) = requirements_hash(&requirements_path) {
        write_requirements_marker(&venv_root, &hash)?;
    }
    steps.push(json!({
        "step": "install_dependencies",
        "state": "completed",
        "detail": format!("Installed from {}", requirements_path.display()),
    }));

    // Step 3: verify by actually importing the packages through the new environment.
    invalidate_python_cache();
    let resolved = resolve_python().await?;
    let backend_root = bundled_backend_root()
        .or_else(|| std::env::var_os("NEYVIA_WORKSPACE_ROOT").map(PathBuf::from))
        .ok_or_else(|| "Neyvia's backend package is missing from this installation.".to_string())?;
    let missing = probe_distributions(&resolved, &backend_root).await;
    if !missing.is_empty() {
        return Err(format!(
            "Neyvia installed its dependencies but the following packages still could \
             not be imported: {}. The environment at {} may be damaged; delete it and \
             retry setup.",
            missing.join(", "),
            venv_root.display()
        ));
    }
    steps.push(json!({
        "step": "verify",
        "state": "completed",
        "detail": format!(
            "Verified all required packages import under Python {}",
            resolved.version_text()
        ),
    }));

    Ok(json!({
        "schema": "neyvia.runtime.bootstrap/1",
        "ok": true,
        "steps": steps,
        "environmentRoot": venv_root.display().to_string(),
        "interpreter": resolved,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn venv_python_path_is_platform_correct() {
        let root = PathBuf::from("/tmp/venv");
        let python = venv_python_path(&root);
        if cfg!(windows) {
            assert!(python.ends_with("Scripts/python.exe") || python.ends_with(r"Scripts\python.exe"));
        } else {
            assert!(python.ends_with("bin/python"));
        }
    }

    #[test]
    fn backend_root_requires_the_grant_agent_package() {
        // A directory that merely exists must not be mistaken for a backend root;
        // this is the check that previously let cwd masquerade as a workspace.
        let temp = std::env::temp_dir();
        assert!(!is_backend_root(&temp));
    }

    #[test]
    fn bundled_backend_search_includes_tauri_direct_resource_layout() {
        let exe_dir = PathBuf::from("/opt/neyvia");
        let candidates = bundled_backend_candidates(&exe_dir);
        assert_eq!(candidates.first(), Some(&exe_dir.join("backend")));
        assert!(candidates.contains(&exe_dir.join("resources").join("backend")));
    }

    #[test]
    fn search_plan_prefers_managed_environment_over_path() {
        let plan = interpreter_search_plan();
        let managed = plan
            .iter()
            .position(|(_, _, source, _)| *source == PythonSource::Managed);
        let host = plan
            .iter()
            .position(|(_, _, source, _)| *source == PythonSource::Host);
        if let (Some(managed), Some(host)) = (managed, host) {
            assert!(managed < host, "managed environment must win over PATH");
        }
    }

    #[test]
    fn backend_commands_never_write_bytecode_into_packaged_resources() {
        let interpreter = PythonInterpreter {
            program: "python".to_string(),
            prefix_args: vec!["-3".to_string()],
            executable: "python".to_string(),
            version: (MIN_PYTHON.0, MIN_PYTHON.1, 0),
            source: PythonSource::Host,
        };
        let command = interpreter.command();
        let no_bytecode = command
            .as_std()
            .get_envs()
            .find(|(key, _)| *key == std::ffi::OsStr::new("PYTHONDONTWRITEBYTECODE"))
            .and_then(|(_, value)| value);

        assert_eq!(no_bytecode, Some(std::ffi::OsStr::new("1")));
    }

    #[tokio::test]
    async fn probing_a_nonexistent_interpreter_yields_none() {
        let result = probe_interpreter(
            "neyvia-definitely-not-a-real-interpreter",
            &[],
            PythonSource::Host,
        )
        .await;
        assert!(result.is_none());
    }
}

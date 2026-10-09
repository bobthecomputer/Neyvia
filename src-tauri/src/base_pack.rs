//! Python-free, signed file-list installation. The CLI proof includes this exact module.
use minisign_verify::{PublicKey, Signature};
use reqwest::{header, Client, Url};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::HashSet,
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
    sync::atomic::{AtomicBool, Ordering},
    time::Duration,
};

pub const DOWNLOAD_LIMIT: u64 = 200_000_000;
const MANIFEST_LIMIT: u64 = 8 * 1024 * 1024;

#[derive(Clone)]
pub struct PackConfig {
    pub root: PathBuf,
    pub manifest_url: String,
    pub public_key: String,
    pub expected_id: String,
    pub allow_large: bool,
}

#[derive(Deserialize, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct Manifest {
    schema: String,
    pack_id: String,
    version: String,
    total_size: u64,
    files: Vec<PackFile>,
    runtime: Option<Runtime>,
    #[serde(default)]
    delivery_status: Option<String>,
}
#[derive(Deserialize, Serialize, Clone)]
struct Runtime {
    python: String,
    backend: String,
}
#[derive(Deserialize, Serialize, Clone)]
struct PackFile {
    path: String,
    url: String,
    size: u64,
    sha256: String,
}

pub fn write_json(path: &Path, value: &Value) -> Result<(), String> {
    let temporary = path.with_extension("json.tmp");
    no_link(path)?;
    no_link(&temporary)?;
    let mut file = File::create(&temporary).map_err(|e| e.to_string())?;
    file.write_all(
        serde_json::to_string_pretty(value)
            .map_err(|e| e.to_string())?
            .as_bytes(),
    )
    .map_err(|e| e.to_string())?;
    file.sync_all().map_err(|e| e.to_string())?;
    drop(file);
    rename_file(&temporary, path)
}

fn rename_file(source: &Path, destination: &Path) -> Result<(), String> {
    // Windows readers/antivirus can briefly hold a file without delete sharing.
    // Preserve the flushed source and retry the atomic replacement, never delete first.
    for attempt in 0..20 {
        match fs::rename(source, destination) {
            Ok(()) => return Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied && attempt < 19 => {
                std::thread::sleep(Duration::from_millis(20 * (attempt + 1)));
            }
            Err(error) => {
                return Err(format!(
                    "Could not publish {}: {error}",
                    destination.display()
                ))
            }
        }
    }
    unreachable!()
}

pub fn status(root: &Path) -> Value {
    fs::read(root.join("status.json"))
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_else(|| json!({"state":"idle", "doneBytes":0,"totalBytes":0,"error":""}))
}

fn relative_path(raw: &str) -> Result<PathBuf, String> {
    if raw.is_empty() || raw.contains(['\\', ':', '\0']) || raw.starts_with('/') {
        return Err(format!("Unsafe pack path: {raw}"));
    }
    for component in raw.split('/') {
        let device = component
            .split('.')
            .next()
            .unwrap_or("")
            .to_ascii_uppercase();
        if component.is_empty()
            || component == "."
            || component == ".."
            || component.ends_with(['.', ' '])
            || component.contains(['<', '>', '"', '|', '?', '*'])
            || component.chars().any(|c| c.is_control())
            || ["CON", "PRN", "AUX", "NUL"].contains(&device.as_str())
            || (device.len() == 4
                && (device.starts_with("COM") || device.starts_with("LPT"))
                && device.as_bytes()[3].is_ascii_digit())
        {
            return Err(format!("Unsafe pack path: {raw}"));
        }
    }
    Ok(PathBuf::from(raw))
}

fn no_link(path: &Path) -> Result<(), String> {
    if let Ok(meta) = fs::symlink_metadata(path) {
        #[cfg(windows)]
        {
            use std::os::windows::fs::MetadataExt;
            if meta.file_attributes() & 0x400 != 0 {
                return Err(format!("Pack path is a reparse point: {}", path.display()));
            }
        }
        if meta.file_type().is_symlink() {
            return Err(format!("Pack path is a symlink: {}", path.display()));
        }
    }
    Ok(())
}

fn safe_destination(root: &Path, raw: &str) -> Result<PathBuf, String> {
    let relative = relative_path(raw)?;
    // Check the complete ancestor chain, including the managed root itself.
    for parent in root.ancestors() {
        no_link(parent)?;
    }
    let mut cursor = root.to_path_buf();
    for component in relative.components() {
        cursor.push(component);
        no_link(&cursor)?;
    }
    Ok(cursor)
}

fn safe_url(url: &Url) -> Result<(), String> {
    let loopback = matches!(
        url.host_str(),
        Some("127.0.0.1" | "localhost" | "[::1]" | "::1")
    );
    if !url.username().is_empty()
        || url.password().is_some()
        || url.fragment().is_some()
        || (url.scheme() != "https" && !(url.scheme() == "http" && loopback))
    {
        return Err("Pack URLs require HTTPS (HTTP is allowed only on loopback).".into());
    }
    Ok(())
}

async fn small_get(client: &Client, url: Url, limit: u64) -> Result<Vec<u8>, String> {
    safe_url(&url)?;
    let mut response = client
        .get(url)
        .send()
        .await
        .map_err(|e| e.to_string())?
        .error_for_status()
        .map_err(|e| e.to_string())?;
    if response.content_length().is_some_and(|n| n > limit) {
        return Err("Manifest/signature is too large".into());
    }
    let mut bytes = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|e| e.to_string())? {
        if bytes.len() as u64 + chunk.len() as u64 > limit {
            return Err("Manifest/signature is too large".into());
        }
        bytes.extend_from_slice(&chunk);
    }
    Ok(bytes)
}

fn sha256(path: &Path) -> Result<String, String> {
    let mut file = File::open(path).map_err(|e| e.to_string())?;
    let mut digest = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        let count = file.read(&mut buffer).map_err(|e| e.to_string())?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

fn verified(path: &Path, entry: &PackFile) -> Result<bool, String> {
    Ok(path.is_file()
        && fs::metadata(path).map_err(|e| e.to_string())?.len() == entry.size
        && sha256(path)? == entry.sha256.to_ascii_lowercase())
}

fn validate(manifest: &Manifest, config: &PackConfig, url: &Url) -> Result<(), String> {
    if manifest
        .delivery_status
        .as_deref()
        .is_some_and(|s| s != "ready")
    {
        return Err("Needs Paul: this external pack has unresolved delivery requirements".into());
    }
    if manifest.schema != "neyvia.base-pack/v1"
        || manifest.pack_id != config.expected_id
        || manifest.version.is_empty()
        || manifest.files.is_empty()
    {
        return Err("Wrong pack schema, identity, version or empty file list".into());
    }
    let mut paths = HashSet::new();
    let mut total = 0u64;
    for entry in &manifest.files {
        relative_path(&entry.path)?;
        if !paths.insert(entry.path.to_lowercase()) {
            return Err("Duplicate pack path".into());
        }
        if entry
            .path
            .split('/')
            .any(|part| part.to_ascii_lowercase().starts_with(".neyvia-"))
            || entry.sha256.len() != 64
            || !entry.sha256.bytes().all(|c| c.is_ascii_hexdigit())
        {
            return Err("Invalid/reserved path or SHA-256".into());
        }
        total = total.checked_add(entry.size).ok_or("Pack size overflow")?;
        safe_url(&url.join(&entry.url).map_err(|e| e.to_string())?)?;
    }
    if total != manifest.total_size {
        return Err("Pack totalSize does not match file sizes".into());
    }
    if total > DOWNLOAD_LIMIT && !config.allow_large {
        return Err("Needs approval: pack exceeds 200 MB".into());
    }
    if config.expected_id == "base" || config.expected_id == "base-pack" {
        let runtime = manifest
            .runtime
            .as_ref()
            .ok_or("Base pack has no Python runtime declaration")?;
        relative_path(&runtime.python)?;
        if runtime.backend != "." {
            relative_path(&runtime.backend)?;
        }
        let backend_cli = if runtime.backend == "." {
            "src/grant_agent/cli.py".to_string()
        } else {
            format!("{}/src/grant_agent/cli.py", runtime.backend)
        };
        if !paths.contains(&runtime.python.to_lowercase())
            || !paths.contains(&backend_cli.to_lowercase())
        {
            return Err("Base pack does not deliver Python and backend".into());
        }
    }
    Ok(())
}

async fn download_file(
    client: &Client,
    url: Url,
    partial: &Path,
    entry: &PackFile,
    cancel: &AtomicBool,
    done: u64,
    status: &mut Value,
    config: &PackConfig,
    emit: &impl Fn(Value),
) -> Result<(), String> {
    no_link(partial)?;
    let mut have = fs::metadata(partial).map(|m| m.len()).unwrap_or(0);
    if have > entry.size {
        File::create(partial).map_err(|e| e.to_string())?;
        have = 0;
    }
    if have == entry.size {
        if entry.size == 0 && !partial.exists() {
            File::create(partial)
                .map_err(|e| e.to_string())?
                .sync_all()
                .map_err(|e| e.to_string())?;
        }
        return Ok(());
    }
    let mut request = client.get(url).header(header::ACCEPT_ENCODING, "identity");
    if have > 0 {
        request = request.header(header::RANGE, format!("bytes={have}-"));
    }
    let response = tokio::select! { result=request.send()=>result.map_err(|e|e.to_string())?, _=wait_cancel(cancel)=>return Err("paused".into()) };
    let mut response = response.error_for_status().map_err(|e| e.to_string())?;
    if response.status() == reqwest::StatusCode::PARTIAL_CONTENT {
        let content_range = response
            .headers()
            .get(header::CONTENT_RANGE)
            .and_then(|v| v.to_str().ok())
            .unwrap_or("");
        let prefix = format!("bytes {have}-");
        let (range, total) = content_range
            .strip_prefix(&prefix)
            .and_then(|s| s.split_once('/'))
            .ok_or("Invalid resume Content-Range")?;
        let end: u64 = range.parse().map_err(|_| "Invalid resume range end")?;
        if total != entry.size.to_string() || end != entry.size.saturating_sub(1) {
            return Err("Resume range does not match manifest".into());
        }
    } else if response.status() == reqwest::StatusCode::OK {
        have = 0;
    } else {
        return Err("Pack server must return 200 or 206".into());
    }
    if response
        .content_length()
        .is_some_and(|n| n != entry.size - have)
    {
        return Err("Download length does not match manifest".into());
    }
    let mut output = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(have == 0)
        .append(have > 0)
        .open(partial)
        .map_err(|e| e.to_string())?;
    loop {
        let next = tokio::select! { result=response.chunk()=>result.map_err(|e|e.to_string())?, _=wait_cancel(cancel)=>{ output.sync_all().map_err(|e|e.to_string())?;return Err("paused".into()); } };
        let Some(chunk) = next else {
            break;
        };
        if cancel.load(Ordering::Relaxed) {
            output.sync_all().map_err(|e| e.to_string())?;
            return Err("paused".into());
        }
        have += chunk.len() as u64;
        if have > entry.size {
            return Err("Download exceeds declared size".into());
        }
        output.write_all(&chunk).map_err(|e| e.to_string())?;
        status["doneBytes"] = json!(done + have);
        emit(status.clone());
    }
    output.sync_all().map_err(|e| e.to_string())?;
    if have != entry.size {
        return Err("Download interrupted before declared size".into());
    }
    // Persist only after flushing file bytes. A restart trusts hashes, never this counter.
    write_json(&config.root.join("status.json"), status)?;
    Ok(())
}

async fn wait_cancel(cancel: &AtomicBool) {
    while !cancel.load(Ordering::Relaxed) {
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
}

async fn runtime_probe(
    target: &Path,
    runtime: &Runtime,
    cancel: &AtomicBool,
) -> Result<Value, String> {
    let backend = if runtime.backend == "." {
        target.to_path_buf()
    } else {
        safe_destination(target, &runtime.backend)?
    };
    let python = safe_destination(target, &runtime.python)?;
    let mut command = tokio::process::Command::new(&python);
    command.arg("-B").arg("-c").arg("import sys,json;sys.path.insert(0,sys.argv[1]);import grant_agent.desktop_bridge,agents,blake3,cryptography,ddgs,jsonschema,PIL,websockets;assert sys.version_info>=(3,11);print(json.dumps({'python':sys.version.split()[0],'backendImported':True}))")
        .arg(backend.join("src")).current_dir(&backend).env_remove("PYTHONHOME").env_remove("PYTHONPATH")
        .env("PYTHONNOUSERSITE","1").env("PYTHONDONTWRITEBYTECODE","1").stdin(std::process::Stdio::null()).kill_on_drop(true);
    #[cfg(windows)]
    command.creation_flags(0x08000000);
    let result = tokio::select! {
        result = tokio::time::timeout(Duration::from_secs(180), command.output()) => result,
        _ = wait_cancel(cancel) => return Err("paused".into()),
    };
    let output = result
        .map_err(|_| "Base runtime check timed out")?
        .map_err(|e| format!("Base Python could not start: {e}"))?;
    if !output.status.success() {
        return Err(format!(
            "Base Python/backend import failed: {}",
            String::from_utf8_lossy(&output.stderr)
                .chars()
                .take(1500)
                .collect::<String>()
        ));
    }
    serde_json::from_slice(&output.stdout)
        .map_err(|e| format!("Base runtime check returned invalid JSON: {e}"))
}

pub async fn install(
    config: &PackConfig,
    cancel: &AtomicBool,
    emit: impl Fn(Value),
) -> Result<Value, String> {
    for parent in config.root.ancestors() {
        no_link(parent)?;
    }
    fs::create_dir_all(&config.root).map_err(|e| e.to_string())?;
    let lock_path = config.root.join("install.lock");
    no_link(&lock_path)?;
    let lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(lock_path)
        .map_err(|e| e.to_string())?;
    lock.try_lock()
        .map_err(|_| "A pack install is already running")?; // OS lock releases on crash/restart.
    let mut state = json!({"state":"running","phase":"manifest","doneBytes":0,"totalBytes":0,"packId":config.expected_id,"error":""});
    write_json(&config.root.join("status.json"), &state)?;
    emit(state.clone());
    let outcome = async {
        let client = Client::builder().redirect(reqwest::redirect::Policy::none()).connect_timeout(Duration::from_secs(20)).timeout(Duration::from_secs(120)).build().map_err(|e|e.to_string())?;
        let source = Url::parse(&config.manifest_url).map_err(|e|e.to_string())?;
        let bytes = small_get(&client,source.clone(),MANIFEST_LIMIT).await?;
        let mut signature_url = source.clone(); signature_url.set_path(&format!("{}.minisig",source.path()));
        let signature_bytes = small_get(&client,signature_url,16384).await?;
        let signature = Signature::decode(std::str::from_utf8(&signature_bytes).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
        let key = PublicKey::from_base64(config.public_key.trim()).or_else(|_|PublicKey::decode(&config.public_key)).map_err(|e|e.to_string())?;
        // Both legacy Ed25519 (Node signer) and prehashed Minisign signatures verify the entire small manifest and trusted comment.
        key.verify(&bytes,&signature,true).map_err(|e|format!("Manifest signature rejected: {e}"))?;
        let manifest: Manifest = serde_json::from_slice(&bytes).map_err(|e|e.to_string())?;
        validate(&manifest,config,&source)?;
        let digest = format!("{:x}",Sha256::digest(&bytes));
        let target = config.root.join("versions").join(&digest);
        no_link(&config.root.join("versions"))?; no_link(&target)?;
        fs::create_dir_all(&target).map_err(|e|e.to_string())?;
        fs::write(safe_destination(&target,".neyvia-manifest.json")?,&bytes).map_err(|e|e.to_string())?;
        fs::write(safe_destination(&target,".neyvia-manifest.minisig")?,&signature_bytes).map_err(|e|e.to_string())?;
        state["totalBytes"] = json!(manifest.total_size); state["version"] = json!(manifest.version); state["phase"] = json!("download");
        let mut done = 0u64; let mut resumed = 0u64; let mut reused = 0u64;
        for (index,entry) in manifest.files.iter().enumerate() {
            if cancel.load(Ordering::Relaxed) { return Err("paused".to_string()); }
            let destination = safe_destination(&target,&entry.path)?;
            fs::create_dir_all(destination.parent().ok_or("Missing pack parent")?).map_err(|e|e.to_string())?;
            if !verified(&destination,entry)? {
                let partial = destination.with_file_name(format!(".neyvia-part-{}",destination.file_name().unwrap().to_string_lossy()));
                no_link(&partial)?;
                resumed += fs::metadata(&partial).map(|m|m.len().min(entry.size)).unwrap_or(0);
                state["currentFile"] = json!(entry.path);
                download_file(&client,source.join(&entry.url).map_err(|e|e.to_string())?,&partial,entry,cancel,done,&mut state,config,&emit).await?;
                if !verified(&partial,entry)? {
                    // Reset only corrupt partial bytes; intact installed versions stay recoverable.
                    File::create(&partial).map_err(|e|e.to_string())?;
                    return Err(format!("SHA-256 mismatch: {}",entry.path));
                }
                rename_file(&partial,&destination)?;
            } else { reused += entry.size; }
            done += entry.size; state["doneBytes"] = json!(done); state["files"] = json!({"done":index+1,"total":manifest.files.len()});
            write_json(&config.root.join("status.json"),&state)?; emit(state.clone());
        }
        if cancel.load(Ordering::Relaxed) { return Err("paused".to_string()); }
        let runtime = if let Some(runtime) = &manifest.runtime { state["phase"] = json!("verifyRuntime"); emit(state.clone()); Some(runtime_probe(&target,runtime,cancel).await?) } else { None };
        if cancel.load(Ordering::Relaxed) { return Err("paused".to_string()); }
        let receipt = json!({"schema":"neyvia.base-pack-receipt/v1","packId":manifest.pack_id,"version":manifest.version,"target":target,"manifestSha256":digest,"signatureVerified":true,"manifestUrl":source.as_str(),"files":manifest.files,"runtimeProbe":runtime,"resumedBytes":resumed,"reusedBytes":reused});
        write_json(&target.join(".neyvia-receipt.json"),&receipt)?;
        if let Some(runtime) = &manifest.runtime {
            write_json(&config.root.join("active.json"),&json!({"schema":"neyvia.active-base-pack/v1","target":target,"manifestSha256":digest,"python":runtime.python,"backend":runtime.backend}))?;
        }
        Ok(receipt)
    }.await;
    match &outcome {
        Ok(receipt) => {
            state["state"] = json!("done");
            state["phase"] = json!("ready");
            state["receipt"] = receipt.clone();
        }
        Err(error) => {
            state["state"] = json!(if error == "paused" {
                "paused"
            } else {
                "failed"
            });
            state["error"] = json!(if error == "paused" { "" } else { error });
        }
    }
    write_json(&config.root.join("status.json"), &state)?;
    emit(state);
    outcome
}

/// Re-check signed bytes and file hashes on each process start before resolving active code.
pub async fn verify_active(config: &PackConfig) -> Result<Value, String> {
    let active: Value = serde_json::from_slice(
        &fs::read(config.root.join("active.json")).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    let digest = active["manifestSha256"]
        .as_str()
        .ok_or("Invalid active pack digest")?;
    if digest.len() != 64 || !digest.bytes().all(|c| c.is_ascii_hexdigit()) {
        return Err("Invalid active pack digest".into());
    }
    let target = config.root.join("versions").join(digest);
    if active["target"].as_str() != Some(target.to_string_lossy().as_ref()) {
        return Err("Active pack points outside managed versions".into());
    }
    let bytes =
        fs::read(safe_destination(&target, ".neyvia-manifest.json")?).map_err(|e| e.to_string())?;
    if format!("{:x}", Sha256::digest(&bytes)) != digest {
        return Err("Active manifest digest changed".into());
    }
    let signature = fs::read_to_string(safe_destination(&target, ".neyvia-manifest.minisig")?)
        .map_err(|e| e.to_string())?;
    let key = PublicKey::from_base64(config.public_key.trim())
        .or_else(|_| PublicKey::decode(&config.public_key))
        .map_err(|e| e.to_string())?;
    key.verify(
        &bytes,
        &Signature::decode(&signature).map_err(|e| e.to_string())?,
        true,
    )
    .map_err(|e| e.to_string())?;
    let manifest: Manifest = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
    validate(
        &manifest,
        config,
        &Url::parse(&config.manifest_url).map_err(|e| e.to_string())?,
    )?;
    for entry in &manifest.files {
        if !verified(&safe_destination(&target, &entry.path)?, entry)? {
            return Err(format!("Active pack changed: {}", entry.path));
        }
    }
    let runtime = manifest
        .runtime
        .as_ref()
        .ok_or("Active base runtime is missing")?;
    if active["python"] != runtime.python || active["backend"] != runtime.backend {
        return Err("Active runtime paths changed".into());
    }
    runtime_probe(&target, runtime, &AtomicBool::new(false)).await
}

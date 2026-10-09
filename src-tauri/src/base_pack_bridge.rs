//! Native bootstrap IPC. These commands deliberately never invoke Python.
use crate::{
    base_pack::{self, PackConfig},
    runtime_env,
};
use serde_json::{json, Value};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use tauri::{AppHandle, Emitter, Manager};

#[derive(Default)]
pub struct PackService {
    running: AtomicBool,
    cancel: Arc<AtomicBool>,
    ready: AtomicBool,
    checking: tokio::sync::Mutex<()>,
}

pub fn enabled() -> bool {
    option_env!("NEYVIA_SLIM_INSTALLER") == Some("1")
}

pub(crate) fn config() -> Result<PackConfig, String> {
    let url = option_env!("NEYVIA_BASE_PACK_URL").unwrap_or("");
    let key = option_env!("NEYVIA_BASE_PACK_PUBLIC_KEY").unwrap_or("");
    if url.is_empty() || key.is_empty() {
        return Err("This installer has no signed base-pack release source. Build it with the release pipeline.".into());
    }
    Ok(PackConfig {
        root: runtime_env::managed_root()
            .ok_or("No writable user runtime directory")?
            .join("base-pack"),
        manifest_url: url.into(),
        public_key: key.into(),
        expected_id: "base".into(),
        allow_large: false,
    })
}

pub fn require_ready(app: &AppHandle) -> Result<(), String> {
    if app.state::<PackService>().ready.load(Ordering::Acquire) {
        Ok(())
    } else {
        Err("Complete the signed base-pack setup before opening your workspace.".into())
    }
}

#[tauri::command]
pub async fn onboarding_base_pack_status_command(app: AppHandle) -> Result<Value, String> {
    let config = config()?;
    let service = app.state::<PackService>();
    if !service.running.load(Ordering::Acquire) && !service.ready.load(Ordering::Acquire) {
        let _guard = service.checking.lock().await;
        if !service.ready.load(Ordering::Acquire) && config.root.join("active.json").is_file() {
            match base_pack::verify_active(&config).await {
                Ok(_) => {
                    service.ready.store(true, Ordering::Release);
                    runtime_env::invalidate_python_cache();
                    runtime_env::confirm_base_pack_verified();
                }
                Err(error) => {
                    let mut state = base_pack::status(&config.root);
                    state["state"] = json!("failed");
                    state["error"] = json!(error);
                    base_pack::write_json(&config.root.join("status.json"), &state)?;
                    return Ok(state);
                }
            }
        }
    }
    let mut state = base_pack::status(&config.root);
    if service.ready.load(Ordering::Acquire) {
        state["state"] = json!("done");
    } else if !service.running.load(Ordering::Acquire) && state["state"] == "running" {
        state["state"] = json!("paused");
    }
    Ok(state)
}

#[tauri::command]
pub async fn onboarding_base_pack_start_command(app: AppHandle) -> Result<Value, String> {
    let config = config()?;
    let service = app.state::<PackService>();
    let _guard = service.checking.lock().await;
    if service.running.swap(true, Ordering::AcqRel) {
        return Ok(base_pack::status(&config.root));
    }
    service.ready.store(false, Ordering::Release);
    service.cancel.store(false, Ordering::Release);
    let cancel = service.cancel.clone();
    let runner = app.clone();
    tauri::async_runtime::spawn(async move {
        let result = base_pack::install(&config, &cancel, |state| {
            let _ = runner.emit("onboarding://base-pack", state);
        })
        .await;
        let service = runner.state::<PackService>();
        service.ready.store(result.is_ok(), Ordering::Release);
        service.running.store(false, Ordering::Release);
        runtime_env::invalidate_python_cache();
        if result.is_ok() {
            runtime_env::confirm_base_pack_verified();
        }
    });
    Ok(json!({"state":"running","phase":"manifest","doneBytes":0,"totalBytes":0,"error":""}))
}

#[tauri::command]
pub fn onboarding_base_pack_pause_command(app: AppHandle) -> Result<Value, String> {
    app.state::<PackService>()
        .cancel
        .store(true, Ordering::Release);
    let config = config()?;
    // Do not promise paused until flushed bytes have been persisted by the worker.
    let mut state = base_pack::status(&config.root);
    state["pauseRequested"] = json!(true);
    Ok(state)
}

pub async fn dispatch(
    app: &AppHandle,
    command: &str,
    _payload: &Option<Value>,
) -> Result<Option<Value>, String> {
    Ok(match command {
        "onboarding_base_pack_status_command" => {
            Some(onboarding_base_pack_status_command(app.clone()).await?)
        }
        "onboarding_base_pack_start_command" => {
            Some(onboarding_base_pack_start_command(app.clone()).await?)
        }
        "onboarding_base_pack_pause_command" => {
            Some(onboarding_base_pack_pause_command(app.clone())?)
        }
        _ => None,
    })
}

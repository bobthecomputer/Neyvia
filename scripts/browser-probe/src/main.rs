//! Task-only shell: never enters Neyvia's supervisor/bootstrap startup.
#[path = "../../../src-tauri/src/browser_runtime.rs"]
mod browser_runtime;

// Optional owned UI proof transport. Product components issue their usual IPC;
// this isolated host forwards the reviewed commands to the real owner backend.
#[tauri::command]
async fn call_desktop_backend_command(webview: tauri::Webview, request: serde_json::Value) -> Result<serde_json::Value, String> {
    if webview.label() != "main" { return Err("Only the owned proof shell may call the backend".into()); }
    let command=request["command"].as_str().ok_or("Missing command")?;
    let allowed=std::env::var("NEYVIA_BROWSER_PROOF_COMMANDS").unwrap_or_else(|_|"browser_call_command".into());
    if !allowed.split(',').any(|value| value==command) { return Err("Command outside the explicitly selected UI proof".into()); }
    let base=std::env::var("NEYVIA_BROWSER_BASE").map_err(|e|e.to_string())?;
    let cookie=std::env::var("NEYVIA_BROWSER_PROOF_OWNER_COOKIE").map_err(|_|"Owned UI proof session missing")?;
    let response=reqwest::Client::new().post(format!("{}/api/backend",base)).header("Cookie",cookie).json(&request).send().await.map_err(|e|e.to_string())?;
    let data:serde_json::Value=response.json().await.map_err(|e|e.to_string())?;
    // Preserve the backend's typed business/auth refusal for the production UI error normalizer.
    if data["ok"] != true { return Ok(data); }
    Ok(data["data"].clone())
}
#[cfg(windows)]
fn require_c7_desktop() {
    #[link(name = "user32")]
    unsafe extern "system" {
        fn GetThreadDesktop(thread: u32) -> *mut core::ffi::c_void;
        fn GetUserObjectInformationW(handle: *mut core::ffi::c_void, index: i32, value: *mut core::ffi::c_void, size: u32, needed: *mut u32) -> i32;
    }
    #[link(name = "kernel32")]
    unsafe extern "system" { fn GetCurrentThreadId() -> u32; }
    let mut name = [0u16; 256];
    let mut needed = 0u32;
    unsafe {
        assert!(GetUserObjectInformationW(GetThreadDesktop(GetCurrentThreadId()), 2, name.as_mut_ptr().cast(), 512, &mut needed) != 0, "Inspect owned worker desktop");
    }
    let end = name.iter().position(|&c| c == 0).unwrap_or(name.len());
    let name = String::from_utf16_lossy(&name[..end]);
    let owned_c7_desktop = name.starts_with("NeyviaC7d-") || name.starts_with("NeyviaBureauC7e-") || name.starts_with("Neyvia-INTN-");
    assert!(owned_c7_desktop, "C7d browser must run on an explicitly owned C7 desktop, never the input desktop");
}
fn main() {
    let base = std::env::var("NEYVIA_BROWSER_BASE").expect("NEYVIA_BROWSER_BASE");
    let owned_url = tauri::Url::parse(&base).expect("Owned proof backend URL");
    let proof_ports = match std::env::var("NEYVIA_BROWSER_PROOF_SCOPE").as_deref() {
        Ok("C9c") => 48761..=48769,
        Ok("FIX") => 48667..=48668,
        Ok("C2") => 48711..=48719,
        Ok("C2b") => 48721..=48739,
        Ok("INT6") => 48351..=48359,
        Ok("INTN") => 48871..=48889,
        _ => 48321..=48329,
    };
    let c7d=std::env::var("NEYVIA_BROWSER_PROOF_SCOPE").as_deref()==Ok("C7d");
    #[cfg(windows)]
    if c7d || std::env::var("NEYVIA_BROWSER_PROOF_SCOPE").as_deref() == Ok("INTN") { require_c7_desktop(); }
    let port = owned_url.port().unwrap_or(0);
    let proof_port_allowed = if c7d {
        let in_c7_scope = |candidate: &u16| (48731..=48739).contains(candidate)
            || (48741..=48749).contains(candidate) || (48871..=48889).contains(candidate)
            || (48941..=48999).contains(candidate);
        match std::env::var("NEYVIA_PROOF_ALLOWED_PORTS") {
            Ok(raw) => {
                let assigned: Vec<u16> = serde_json::from_str(&raw).expect("Explicit C7 proof port list");
                assert!(
                    !assigned.is_empty() && assigned.iter().all(in_c7_scope),
                    "C7 browser proof requires an explicit C7 port block"
                );
                assigned.contains(&port)
            }
            Err(_) => (48731..=48739).contains(&port) || (48741..=48749).contains(&port),
        }
    } else {
        proof_ports.contains(&port)
    };
    assert!(
        proof_port_allowed,
        "Native browser proof requires a port in its explicitly selected task scope"
    );
    let token = std::env::var("NEYVIA_BROWSER_TOKEN").expect("memory-only NEYVIA_BROWSER_TOKEN");
    let c2_root = if matches!(std::env::var("NEYVIA_BROWSER_PROOF_SCOPE").as_deref(), Ok("C2") | Ok("C2b")) {
        let root = std::path::PathBuf::from(std::env::var("NEYVIA_BROWSER_PROOF_ROOT").expect("C2 proof root"));
        assert!(root.is_absolute() && root.starts_with(std::env::current_dir().unwrap()), "C2 profile stays in the worktree");
        Some(root)
    } else { None };
    eprintln!("Owned browser proof starting at {}", base);
    let mut context = tauri::generate_context!();
    context.config_mut().app.windows.clear();
    tauri::Builder::default()
        .manage(browser_runtime::BrowserRuntime::default())
        .invoke_handler(|invoke| {
            if browser_runtime::page_isolated(&invoke) {
                invoke
                    .resolver
                    .reject("Browser content may only send page events");
                return true;
            }
            let handler: fn(tauri::ipc::Invoke<tauri::Wry>) -> bool =
                tauri::generate_handler![browser_runtime::browser_page_event, call_desktop_backend_command];
            handler(invoke)
        })
        .setup(move |app| {
            // WebView2 controller creation requires the Windows message loop.
            // This worker lets setup return before the first window is built.
            let app = app.handle().clone();
            std::thread::spawn(move || {
            eprintln!("Owned browser proof setting up native window after event-loop startup");
            if let Some(root) = &c2_root {
                tauri::WebviewWindowBuilder::new(&app,"main",tauri::WebviewUrl::External(tauri::Url::parse("about:blank").unwrap()))
                    .data_directory(root.join("shell-profile"))
                    .title("Neyvia C2 browser proof")
                    .inner_size(1280.,800.).visible(false)
                    .build().expect("Owned main WebView2 window creation");
            } else {
                tauri::window::WindowBuilder::new(&app, "main")
                    .title("Neyvia T20 owned WebView2 proof")
                    .inner_size(1280., 800.).visible(false)
                    .build().expect("Owned main native window creation");
            }
            eprintln!("Owned browser proof native window created");
            if let Ok(ui) = std::env::var("NEYVIA_BROWSER_PROOF_UI_URL") {
                let url = tauri::Url::parse(&ui).expect("Owned UI proof URL");
                assert_eq!(url.origin(), owned_url.origin(), "UI proof must stay on its owned backend origin");
                let profile = std::path::PathBuf::from(std::env::var("NEYVIA_BROWSER_PROOF_UI_PROFILE").expect("Task-local owned UI profile"));
                assert!(profile.is_absolute() && profile.starts_with(std::env::current_dir().unwrap().join(".agent_control")), "Owned UI profile must stay task-local");
                let builder = tauri::webview::WebviewBuilder::new("main", tauri::WebviewUrl::External(url)).data_directory(profile);
                app.get_window("main").expect("Owned native window")
                    .add_child(builder, tauri::LogicalPosition::new(0., 0.), tauri::LogicalSize::new(1280., 800.))
                    .expect("Owned UI child creation");
            }
            browser_runtime::start(&app, &base, token.clone())
                .expect("Owned browser runtime attachment");
            eprintln!("Owned browser proof bridge attached");
            });
            Ok(())
        })
        .run(context)
        .expect("T20 native proof runtime");
}
use tauri::Manager;

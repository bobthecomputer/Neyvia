//! Owned child WebView2 tabs. Backend capabilities never enter page JavaScript.
use serde_json::{json, Value};
use std::{
    collections::{HashMap, VecDeque},
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};
use tauri::webview::{DownloadEvent, PageLoadEvent, WebviewBuilder};
use tauri::{AppHandle, LogicalPosition, LogicalSize, Manager, Webview, WebviewUrl};

#[derive(Default)]
pub struct BrowserRuntime {
    connection: Mutex<Option<Arc<Connection>>>,
}
struct Connection {
    token: String,
    endpoint: String,
    stop: AtomicBool,
    sender: std::sync::mpsc::Sender<Value>,
    tabs: Mutex<HashMap<String, String>>,
    pending: Mutex<HashMap<String, (String, Instant, Value)>>,
    shields: Mutex<HashMap<String, Value>>,
    private_profiles: Mutex<HashMap<String, PathBuf>>,
    permissions: Mutex<HashMap<String, Value>>,
    navigation_epochs: Mutex<HashMap<String, u64>>,
    downloads: Mutex<HashMap<String, DownloadState>>,
}
#[derive(Default)]
struct DownloadState { granted: bool, count: u32, hooked: bool, navigation_id: String }
fn send(c: &Connection, event: Value) {
    let _ = c.sender.send(event);
}
fn completion(c: &Connection, a: &Value, result: Result<Value, String>) {
    if let Some(id) = a["id"].as_str() {
        c.pending.lock().unwrap().remove(id);
    }
    let event = match result {
        Ok(result) => {
            json!({"type":"action","actionId":a["id"],"tabId":a["tabId"],"ok":true,"result":result})
        }
        Err(error) => {
            json!({"type":"action","actionId":a["id"],"tabId":a["tabId"],"ok":false,"error":error})
        }
    };
    send(c, event);
}
fn tab_label(tab: &str) -> String {
    format!("browser-{}", tab)
}
pub fn page_isolated(invoke: &tauri::ipc::Invoke<tauri::Wry>) -> bool {
    invoke.message.webview_ref().label().starts_with("browser-")
        && invoke.message.command() != "browser_page_event"
}
#[tauri::command]
pub async fn browser_runtime_start(
    app: AppHandle,
    webview: Webview,
    base_url: String,
    token: String,
) -> Result<Value, String> {
    if webview.label() != "main" {
        return Err("Only the shell may attach the browser runtime".into());
    }
    start(&app, &base_url, token)
}
pub fn start(app: &AppHandle, base_url: &str, token: String) -> Result<Value, String> {
    let url = tauri::Url::parse(base_url).map_err(|e| e.to_string())?;
    if url.scheme() != "http"
        || !matches!(url.host_str(), Some("127.0.0.1") | Some("localhost"))
        || url.port().unwrap_or(0) == 0
        || url.username() != ""
        || url.password().is_some()
    {
        return Err(
            "Browser runtime requires an explicitly configured loopback backend port".into(),
        );
    }
    if token.len() < 24 {
        return Err("Invalid runtime capability".into());
    }
    let state = app.state::<BrowserRuntime>();
    let mut slot = state.connection.lock().unwrap();
    if slot.is_some() {
        return Err("Stop the previous browser runtime before reconnecting".into());
    }
    let (sender, receiver) = std::sync::mpsc::channel();
    let c = Arc::new(Connection {
        token,
        endpoint: format!("{}/api/ui/browser/runtime", base_url.trim_end_matches('/')),
        stop: AtomicBool::new(false),
        sender,
        tabs: Mutex::new(HashMap::new()),
        downloads: Mutex::new(HashMap::new()),
        pending: Mutex::new(HashMap::new()),
        shields: Mutex::new(HashMap::new()),
        private_profiles: Mutex::new(HashMap::new()),
        permissions: Mutex::new(HashMap::new()),
        navigation_epochs: Mutex::new(HashMap::new()),
    });
    *slot = Some(c.clone());
    let handle = app.clone();
    std::thread::spawn(move || {
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        runtime.block_on(async move {
            // This capability is loopback-only; ambient OS/HTTP proxies must
            // never intercept the bridge or receive its memory-only token.
            let client = reqwest::Client::builder().no_proxy().timeout(Duration::from_secs(5)).build().unwrap();
            let mut outbox = VecDeque::<Value>::new();
            let mut active_until = Instant::now();
            while !c.stop.load(Ordering::Relaxed) {
                #[cfg(windows)]
                cancel_permissions(&handle, &c, None, "Request expired; ask again", true);
                while let Ok(event) = receiver.try_recv() {
                    active_until = Instant::now() + Duration::from_millis(500);
                    if event["type"] == "projection" && event["actionId"].is_null() {
                        outbox.retain(|old| !(old["type"] == "projection" && old["actionId"].is_null() && old["tabId"] == event["tabId"]));
                    }
                    outbox.push_back(event);
                }
                while let Some(event) = outbox.front() {
                    match client.post(&c.endpoint).json(&json!({"token":c.token,"op":"report","event":event})).send().await {
                        Ok(response) if response.status().is_success() || response.status().is_client_error() => { outbox.pop_front(); },
                        _ => break,
                    }
                }
                let expired:Vec<_> = c.pending.lock().unwrap().iter().filter(|(_,(_,started,_))| started.elapsed() > Duration::from_secs(15)).map(|(id,(tab,_,_))|(id.clone(),tab.clone())).collect();
                for (id,tab) in expired {
                    c.pending.lock().unwrap().remove(&id);
                    send(&c,json!({"type":"action","actionId":id,"tabId":tab,"ok":false,"error":"Page bridge did not acknowledge within 15 seconds; effect is unconfirmed"}));
                }
                let response = client.post(&c.endpoint).json(&json!({"token":c.token,"op":"poll"})).send().await;
                if let Ok(response) = response {
                    if !response.status().is_success() { eprintln!("Browser bridge poll returned HTTP {}",response.status()); }
                    if let Ok(data) = response.json::<Value>().await {
                        if let Some(actions) = data["actions"].as_array() {
                            if !actions.is_empty() { active_until = Instant::now() + Duration::from_millis(500); }
                            for action in actions {
                                if action["op"] == "action" || action["op"] == "permission.answer" || action["op"] == "annotate" {
                                    let grant = client.post(&c.endpoint).json(&json!({"token":c.token,"op":"authorize","actionId":action["id"]})).send().await;
                                    let authorization = match grant { Ok(r) => r.json::<Value>().await.unwrap_or_else(|_|json!({"authorized":false,"status":"authorization_unavailable"})), Err(_) => json!({"authorized":false,"status":"authorization_unavailable"}) };
                                    if authorization["authorized"] != true {
                                        let status=authorization["status"].as_str().unwrap_or("authorization_refused");
                                        send(&c,json!({"type":"action","actionId":action["id"],"tabId":action["tabId"],"ok":false,"result":{"ok":false,"status":status,"dispatched":false,"verification":{"verified":false,"check":"authorization_before_dispatch"}}}));
                                        continue;
                                    }
                                }
                                execute(&handle, &c, action.clone());
                            }
                        }
                    } else {
                        eprintln!("Browser bridge poll returned invalid JSON");
                    }
                } else if let Err(error) = response {
                    eprintln!("Browser loopback bridge unavailable: {}",error);
                }
                tokio::time::sleep(Duration::from_millis(if Instant::now() < active_until {20} else {100})).await;
            }
        });
    });
    Ok(json!({"ok":true,"engine":"WebView2","connected":true}))
}
#[tauri::command]
pub async fn browser_runtime_stop(app: AppHandle, webview: Webview) -> Result<Value, String> {
    if webview.label() != "main" {
        return Err("Only the shell may stop the browser runtime".into());
    }
    stop(&app)
}
pub fn stop(app: &AppHandle) -> Result<Value, String> {
    if let Some(c) = app
        .state::<BrowserRuntime>()
        .connection
        .lock()
        .unwrap()
        .take()
    {
        c.stop.store(true, Ordering::Relaxed);
        #[cfg(windows)]
        cancel_permissions(app, &c, None, "Browser runtime stopped", false);
        for label in c.tabs.lock().unwrap().keys() {
            if let Some(w) = app.get_webview(label) {
                let _ = w.close();
            }
        }
    }
    Ok(json!({"ok":true,"connected":false}))
}
#[tauri::command]
pub fn browser_page_event(
    app: AppHandle,
    webview: Webview,
    mut event: Value,
) -> Result<(), String> {
    let state = app.state::<BrowserRuntime>();
    let slot = state.connection.lock().unwrap();
    let c = slot.as_ref().ok_or("Browser runtime disconnected")?;
    let tab = c
        .tabs
        .lock()
        .unwrap()
        .get(webview.label())
        .cloned()
        .ok_or("Unknown browser sender")?;
    let kind = event["type"].as_str().unwrap_or("");
    if !matches!(kind, "projection" | "reader" | "action" | "user_input") {
        return Err("Invalid page event".into());
    }
    if event.to_string().len() > 512_000 {
        return Err("Projection too large".into());
    }
    if let Some(id) = event["actionId"].as_str() {
        if c.pending.lock().unwrap().get(id).map(|(tab, _, _)| tab) != Some(&tab) {
            return Err("Action does not belong to this page".into());
        }
        c.pending.lock().unwrap().remove(id);
    } else if matches!(kind, "action" | "reader") {
        return Err("Action ID required".into());
    }
    event["tabId"] = json!(tab);
    // Page IPC is untrusted. Durable app checkpoints come only from native
    // ExecuteScript readback for this actual webview, never page-supplied IPC.
    if let Some(projection)=event.get_mut("projection").and_then(Value::as_object_mut){projection.remove("localAppStorage");}
    send(c, event);
    Ok(())
}
fn execute(app: &AppHandle, c: &Arc<Connection>, a: Value) {
    let app_handle = app.clone();
    let connection = c.clone();
    let failure = a.clone();
    if let Err(e) = app.run_on_main_thread(move || {
        let result = execute_main(&app_handle, &connection, &a);
        if result
            .as_ref()
            .map(|v| v["awaitingNativeCallback"] == true)
            .unwrap_or(false)
        {
            return;
        }
        if !matches!(a["op"].as_str(), Some("observe" | "reader" | "action")) || result.is_err() {
            completion(&connection, &a, result);
        }
    }) {
        completion(c, &failure, Err(e.to_string()));
    }
}
fn execute_main(app: &AppHandle, c: &Arc<Connection>, a: &Value) -> Result<Value, String> {
    let id = a["tabId"].as_str().unwrap_or("");
    let label = tab_label(id);
    let op = a["op"].as_str().ok_or("Missing native op")?;
    if op == "open" {
        if app.get_webview(&label).is_some() {
            return Ok(json!({"live":true}));
        }
        let url = tauri::Url::parse(a["url"].as_str().ok_or("Missing URL")?)
            .map_err(|e| e.to_string())?;
        if !matches!(url.scheme(), "http" | "https") {
            return Err("HTTP(S) pages required".into());
        }
        let profile = PathBuf::from(
            a["profilePath"]
                .as_str()
                .ok_or("Missing owned profile directory")?,
        );
        let downloads = PathBuf::from(
            a["downloadRoot"]
                .as_str()
                .ok_or("Missing download directory")?,
        );
        if !profile.is_absolute() || !downloads.is_absolute() {
            return Err("Owned directories must be absolute".into());
        }
        if a["private"] == true {
            validate_private_profile(&profile, id)?;
            c.private_profiles
                .lock()
                .unwrap()
                .insert(label.clone(), profile.clone());
        }
        c.shields
            .lock()
            .unwrap()
            .insert(id.into(), a["shield"].clone());
        std::fs::create_dir_all(&profile).map_err(|e| e.to_string())?;
        std::fs::create_dir_all(&downloads).map_err(|e| e.to_string())?;
        c.tabs.lock().unwrap().insert(label.clone(), id.to_string());
        c.downloads.lock().unwrap().insert(id.to_string(), DownloadState::default());
        let navigation = c.clone();
        let navigation_app = app.clone();
        let tab = id.to_string();
        let page = c.clone();
        let ptab = id.to_string();
        let title = c.clone();
        let ttab = id.to_string();
        let download = c.clone();
        let dtab = id.to_string();
        let popup = c.clone();
        let popup_tab = id.to_string();
        let import = a.get("importState").filter(|v| v.is_object()).cloned();
        let imported_script=import.as_ref().map(|state|format!(r#"(() => {{
            const state={};
            if(location.origin==='null')return;
            const marker='__neyviaImported_'+state.importId;
            try{{if(sessionStorage.getItem(marker))return;sessionStorage.setItem(marker,'1');}}catch(_){{}}
            const storage=(state.origins||[]).find(row=>row.origin===location.origin);
            if(storage)for(const item of storage.localStorage||[]){{try{{localStorage.setItem(item.name,item.value);}}catch(_){{}}}}
            document.addEventListener('DOMContentLoaded',()=>{{
                for(const item of state.forms||[]){{
                    if(state.formOrigin!==location.origin || (item.origin && item.origin!==location.origin))continue;
                    let element;try{{element=document.querySelector(item.selector);}}catch(_){{continue;}}
                    if(!element || element.type==='password' || /password|cc-number|cc-csc|one-time-code/.test(element.autocomplete||''))continue;
                    if('value' in element){{element.value=String(item.value??'');element.dispatchEvent(new Event('input',{{bubbles:true}}));}}
                    if(typeof item.checked==='boolean' && 'checked' in element)element.checked=item.checked;
                }}
            }},{{once:true}});
        }})();"#,json!({"origins":state["origins"],"forms":state["forms"],"formOrigin":url.origin().ascii_serialization(),"importId":uuid::Uuid::new_v4().to_string()}))).unwrap_or_default();
        let checkpoints=a.get("localAppCheckpoints").cloned().unwrap_or(json!({}));
        let checkpoint_script=format!(r#"(() => {{const origins={};const values=origins[location.origin]||{{}};for(const [key,value] of Object.entries(values)){{if(/^neyvia\.app-factory\.[A-Za-z0-9._-]+\.(items\.v1|capability-runs\.v2)$/.test(key)&&typeof value==='string'&&value.length<=512000){{try{{if(Array.isArray(JSON.parse(value)))localStorage.setItem(key,value);}}catch{{}}}}}}}})();"#,checkpoints);
        // Attach native filters before the first external request.
        let initial_url = tauri::Url::parse("about:blank").unwrap();
        let builder=WebviewBuilder::new(&label,WebviewUrl::External(initial_url)).data_directory(profile)
            .user_agent("NeyviaAgent/1.0 (Automation; WebView2)")
            .initialization_script("Object.defineProperty(navigator,'webdriver',{get:()=>true,configurable:true});")
            .initialization_script(checkpoint_script)
            .initialization_script(imported_script)
            .initialization_script(format!("{}\n{}", include_str!("../../src/grant_agent/browser_dom.js"), include_str!("browser_projection.js")))
            .on_navigation(move|url|{if url.as_str()=="about:blank"{return true;}let allowed=matches!(url.scheme(),"http"|"https");if allowed{let navigation_id=uuid::Uuid::new_v4().to_string();if let Some(state)=navigation.downloads.lock().unwrap().get_mut(&tab){state.granted=false;state.count=0;state.navigation_id=navigation_id.clone();}let epoch={let mut epochs=navigation.navigation_epochs.lock().unwrap();let epoch=epochs.entry(tab.clone()).or_default();*epoch+=1;*epoch};#[cfg(windows)] cancel_permissions(&navigation_app,&navigation,Some(tab.clone()),"Page navigated; ask again",false);send(&navigation,json!({"type":"navigation","tabId":tab,"url":url.as_str(),"loading":true,"navigationEpoch":epoch,"navigationId":navigation_id}));}allowed})
            .on_page_load(move|view,payload|{
                if payload.url().as_str()=="about:blank"{return;}
                let epoch=page.navigation_epochs.lock().unwrap().get(&ptab).copied().unwrap_or(0);
                send(&page,json!({"type":"navigation","tabId":ptab,"url":payload.url().as_str(),"loading":matches!(payload.event(),PageLoadEvent::Started),"navigationEpoch":epoch}));
                                if matches!(payload.event(),PageLoadEvent::Finished){
                    #[cfg(windows)]
                    let _=readback_native(&view,&page,&json!({"op":"observe","tabId":ptab}));
                    #[cfg(not(windows))]
                    let _=view.eval("window.__neyviaBrowser && window.__neyviaBrowser.observe()");
                    // A click may destroy its document before it can acknowledge.
                    // Verify the new document against the original pending action;
                    // never repeat the click or manufacture a completion.
                    let actions:Vec<Value>=page.pending.lock().unwrap().values()
                        .filter(|(tab,_,action)|tab==&ptab&&action["op"]=="action")
                        .map(|(_,_,action)|action.clone()).collect();
                    for action in actions {let _=view.eval(&format!("window.__neyviaBrowser && window.__neyviaBrowser.verifyNavigation({})",action));}
                }
            })
            .on_document_title_changed(move|_,value|send(&title,json!({"type":"title","tabId":ttab,"title":value})))
            .on_new_window(move|url,_|{
                if matches!(url.scheme(),"http"|"https") { send(&popup,json!({"type":"new_tab","tabId":popup_tab,"url":url.as_str()})); }
                tauri::webview::NewWindowResponse::Deny
            })
            .on_download(move|_,event|{match event{
                DownloadEvent::Requested{url,destination}=>{
                    let name=destination.file_name().and_then(|x|x.to_str()).unwrap_or("download.bin");
                    let safe:String=name.chars().filter(|x|x.is_ascii_alphanumeric()||"._-".contains(*x)).collect();
                    *destination=downloads.join(format!("{}-{}",uuid::Uuid::new_v4(),safe));
                    {
                        let mut states=download.downloads.lock().unwrap();
                        let state=states.entry(dtab.clone()).or_default();
                        if state.count>0 && !state.granted {
                            send(&download,json!({"type":"download","tabId":dtab,"url":url.as_str(),"path":destination.to_string_lossy(),"status":"cancelled","bytes":0}));
                            return false;
                        }
                        state.count+=1;
                    }
                    send(&download,json!({"type":"download","tabId":dtab,"url":url.as_str(),"path":destination.to_string_lossy(),"status":"started","bytes":0}));true
                },
                DownloadEvent::Finished{url,path,success}=>{let bytes=path.as_ref().and_then(|p|std::fs::metadata(p).ok()).map(|m|m.len()).unwrap_or(0);send(&download,json!({"type":"download","tabId":dtab,"url":url.as_str(),"path":path.map(|p|p.to_string_lossy().to_string()),"status":if success{"completed"}else{"failed"},"bytes":bytes}));true},_=>false}});
        let window = app.get_window("main").ok_or("Main shell window missing")?;
        let view = window
            .add_child(
                builder,
                LogicalPosition::new(180., 50.),
                LogicalSize::new(1050., 700.),
            )
            .map_err(|e| e.to_string())?;
        let _ = view.hide();
        #[cfg(windows)]
        configure_native(&view, c, a, &url, import.is_none())?;
        #[cfg(windows)]
        install_download_permissions(&view,c,id)?;
        #[cfg(windows)]
        if let Some(import) = import {
            import_native(&view, c, a, &url, import)?;
            return Ok(json!({"awaitingNativeCallback":true}));
        }
        #[cfg(not(windows))]
        {
            view.navigate(url).map_err(|e| e.to_string())?;
            return Ok(json!({"live":true,"engine":"native-webview"}));
        }
        #[cfg(windows)]
        return Ok(json!({"awaitingNativeCallback":true}));
    }
    if op == "layout" {
        for item in a["tabs"].as_array().ok_or("Missing layout tabs")? {
            if let Some(view) = app.get_webview(&tab_label(item["tabId"].as_str().unwrap_or(""))) {
                if item["visible"] == true {
                    let n = |key: &str| {
                        item[key]
                            .as_f64()
                            .ok_or_else(|| format!("Invalid layout {}", key))
                    };
                    let x = n("x")?;
                    let y = n("y")?;
                    let width = n("width")?;
                    let height = n("height")?;
                    if ![x, y, width, height].iter().all(|v| v.is_finite())
                        || x < 0.
                        || y < 0.
                        || width < 1.
                        || height < 1.
                        || width > 10000.
                        || height > 10000.
                    {
                        return Err("Invalid native bounds".into());
                    }
                    view.set_position(LogicalPosition::new(x, y))
                        .map_err(|e| e.to_string())?;
                    view.set_size(LogicalSize::new(width, height))
                        .map_err(|e| e.to_string())?;
                    view.show().map_err(|e| e.to_string())?;
                } else {
                    view.hide().map_err(|e| e.to_string())?;
                }
            }
        }
        return Ok(json!({"laidOut":true}));
    }
    if op == "download_grant" {
        let mut states=c.downloads.lock().unwrap();
        let state=states.get_mut(id).ok_or("Native tab missing download state")?;
        if !state.hooked{return Err("Native download permission hook unavailable".into());}
        if state.navigation_id.is_empty() || a["navigationId"].as_str()!=Some(state.navigation_id.as_str()) {
            return Err("Stale native navigation download grant".into());
        }
        state.granted=a["enabled"]==true;
        return Ok(json!({"multipleDownloads":state.granted}));
    }
    let view = app
        .get_webview(&label)
        .ok_or("Tab has no live native webview")?;
    match op {
        #[cfg(windows)]
        "permission.answer" => return answer_permission(c, a),
        "shield_config" => {
            c.shields
                .lock()
                .unwrap()
                .insert(id.into(), a["shield"].clone());
            return Ok(json!({"configured":true,"shield":a["shield"]}));
        }
        #[cfg(windows)]
        "history_clear" => {
            clear_history_native(&view, c, a)?;
            return Ok(json!({"awaitingNativeCallback":true}));
        }
        "grant" => view
            .eval(&format!("window.__neyviaBrowser.grant({})", a))
            .map_err(|e| e.to_string())?,
        #[cfg(windows)]
        "capture" => {
            capture_native(&view, c, a)?;
            return Ok(json!({"awaitingNativeCallback":true}));
        }
        "navigate" => {
            let url = tauri::Url::parse(a["url"].as_str().ok_or("Missing URL")?)
                .map_err(|e| e.to_string())?;
            if !matches!(url.scheme(), "http" | "https") {
                return Err("HTTP(S) required".into());
            }
            view.navigate(url).map_err(|e| e.to_string())?;
        }
        "back" => view.eval("history.back()").map_err(|e| e.to_string())?,
        "forward" => view.eval("history.forward()").map_err(|e| e.to_string())?,
        "reload" => view.eval("location.reload()").map_err(|e| e.to_string())?,
        "close" => {
            #[cfg(windows)]
            deny_permissions(c, Some(id), "Tab closed", false);
            view.close().map_err(|e| e.to_string())?;
            c.tabs.lock().unwrap().remove(&label);
            c.downloads.lock().unwrap().remove(id);
            c.shields.lock().unwrap().remove(id);
            c.navigation_epochs.lock().unwrap().remove(id);
            if let Some(path) = c.private_profiles.lock().unwrap().remove(&label) {
                cleanup_private(c.clone(), a.clone(), path);
                return Ok(json!({"awaitingNativeCallback":true}));
            }
        }
        "dom" | "annotate" => {
            #[cfg(windows)]
            {readback_native(&view,c,a)?;return Ok(json!({"awaitingNativeCallback":true}));}
            #[cfg(not(windows))]
            {return Err("Native DOM readback/annotation is not available on this platform".into());}
        }
        "observe" | "reader" | "action" => {
            #[cfg(windows)]
            if op=="observe" {readback_native(&view,c,a)?;return Ok(json!({"awaitingNativeCallback":true}));}
            let action_id = a["id"].as_str().ok_or("Missing action ID")?;
            c.pending
                .lock()
                .unwrap()
                .insert(action_id.into(), (id.into(), Instant::now(), a.clone()));
            let script = if matches!(op, "observe" | "reader") {
                format!("window.__neyviaBrowser.{}({})", op, json!(action_id))
            } else {
                format!("window.__neyviaBrowser.perform({})", a)
            };
            view.eval(script).map_err(|e| e.to_string())?;
        }
        _ => return Err(format!("Unknown native browser op {}", op)),
    }
    Ok(json!({"ok":true}))
}

fn validate_private_profile(path: &std::path::Path, tab: &str) -> Result<(), String> {
    if !path.is_absolute()
        || path.file_name().and_then(|x| x.to_str()) != Some(tab)
        || path
            .parent()
            .and_then(|x| x.file_name())
            .and_then(|x| x.to_str())
            != Some("private")
        || path
            .parent()
            .and_then(|x| x.parent())
            .and_then(|x| x.file_name())
            .and_then(|x| x.to_str())
            != Some("browser")
        || path
            .components()
            .any(|x| matches!(x, std::path::Component::ParentDir))
    {
        return Err(
            "Private profile must be an exact owned browser/private/<tabId> directory".into(),
        );
    }
    for ancestor in path.ancestors().filter(|x| x.exists()) {
        let metadata = std::fs::symlink_metadata(ancestor).map_err(|e| e.to_string())?;
        #[cfg(windows)]
        {
            use std::os::windows::fs::MetadataExt;
            if metadata.file_attributes() & 0x400 != 0 {
                return Err("Private profile cannot traverse a reparse point".into());
            }
        }
        if metadata.file_type().is_symlink() {
            return Err("Private profile cannot traverse a link".into());
        }
    }
    Ok(())
}

fn cleanup_private(c: Arc<Connection>, a: Value, path: PathBuf) {
    std::thread::spawn(move || {
        let result = (|| -> Result<Value, String> {
            validate_private_profile(&path, a["tabId"].as_str().ok_or("Missing private tab")?)?;
            for _ in 0..100 {
                if !path.exists() {
                    return Ok(json!({"privateProfileDeleted":true}));
                }
                if std::fs::remove_dir_all(&path).is_ok() {
                    return Ok(json!({"privateProfileDeleted":true}));
                }
                std::thread::sleep(Duration::from_millis(100));
            }
            Err("Private tab closed; profile cleanup is blocked by live file handles".into())
        })();
        completion(&c, &a, result);
    });
}

#[cfg(windows)]
struct NativePermission {
    args: webview2_com::Microsoft::Web::WebView2::Win32::ICoreWebView2PermissionRequestedEventArgs,
    deferral: webview2_com::Microsoft::Web::WebView2::Win32::ICoreWebView2Deferral,
    core: webview2_com::Microsoft::Web::WebView2::Win32::ICoreWebView2,
    request: Value,
}
#[cfg(windows)]
thread_local! {
    // COM deferrals stay on the WebView2 UI thread; only metadata crosses threads.
    static PERMISSION_DEFERRALS: std::cell::RefCell<HashMap<String,NativePermission>> = std::cell::RefCell::new(HashMap::new());
}
fn permission_time() -> f64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_secs_f64()
}
fn permission_origin(value: &str) -> Option<String> {
    tauri::Url::parse(value).ok().filter(|url|matches!(url.scheme(),"http"|"https")).map(|url|url.origin().ascii_serialization())
}
#[cfg(windows)]
fn finish_permission(c:&Connection, mut pending:NativePermission, allow:bool, reason:&str) -> Result<Value,String> {
    use webview2_com::Microsoft::Web::WebView2::Win32::*;
    let result=unsafe {
        pending.args.SetState(if allow {COREWEBVIEW2_PERMISSION_STATE_ALLOW}else{COREWEBVIEW2_PERMISSION_STATE_DENY})
            .and_then(|_|pending.deferral.Complete()).map_err(|e|e.to_string())
    };
    c.permissions.lock().unwrap().remove(pending.request["requestId"].as_str().unwrap_or(""));
    pending.request["state"]=json!(if allow && result.is_ok(){"allowed"}else{"denied"});
    pending.request["reason"]=json!(reason);
    pending.request["nativeAcknowledged"]=json!(result.is_ok());
    send(c,pending.request.clone());
    result.map(|_|json!({"requestId":pending.request["requestId"],"state":pending.request["state"],"nativeAcknowledged":true}))
}
#[cfg(windows)]
fn deny_permissions(c:&Connection, tab:Option<&str>, reason:&str, expired_only:bool) {
    let ids:Vec<String>=c.permissions.lock().unwrap().iter().filter(|(_,row)|
        tab.map(|tab|row["tabId"].as_str()==Some(tab)).unwrap_or(true)
        && (!expired_only || row["expiresAt"].as_f64().unwrap_or(0.)<=permission_time()))
        .map(|(id,_)|id.clone()).collect();
    for id in ids { let pending=PERMISSION_DEFERRALS.with(|rows|rows.borrow_mut().remove(&id));
        if let Some(pending)=pending {let _=finish_permission(c,pending,false,reason);}
    }
}
#[cfg(windows)]
fn cancel_permissions(app:&AppHandle,c:&Arc<Connection>,tab:Option<String>,reason:&'static str,expired_only:bool) {
    let needed=c.permissions.lock().unwrap().values().any(|row|
        tab.as_ref().map(|tab|row["tabId"].as_str()==Some(tab.as_str())).unwrap_or(true)
        && (!expired_only || row["expiresAt"].as_f64().unwrap_or(0.)<=permission_time()));
    if !needed{return;} let c=c.clone();
    let _=app.run_on_main_thread(move||deny_permissions(&c,tab.as_deref(),reason,expired_only));
}
#[cfg(windows)]
fn answer_permission(c:&Connection,a:&Value)->Result<Value,String> {
    use windows::core::PWSTR;
    let id=a["requestId"].as_str().ok_or("Exact permission requestId required")?;
    let valid=PERMISSION_DEFERRALS.with(|rows|rows.borrow().get(id).map(|pending|
        ["tabId","profileId","origin","navigationEpoch"].iter().all(|key|pending.request[*key]==a[*key]))).unwrap_or(false);
    if !valid{return Err("Permission request is missing or scope differs; inspect pending requests".into());}
    let pending=PERMISSION_DEFERRALS.with(|rows|rows.borrow_mut().remove(id)).unwrap();
    let mut source=PWSTR::null();
    let source=unsafe{pending.core.Source(&mut source).map(|_|webview2_com::take_pwstr(source)).map_err(|e|e.to_string())};
    let current_epoch=c.navigation_epochs.lock().unwrap().get(a["tabId"].as_str().unwrap_or("")).copied().unwrap_or(0);
    let live=c.tabs.lock().unwrap().get(&tab_label(a["tabId"].as_str().unwrap_or(""))).is_some();
    let fresh=live && !c.stop.load(Ordering::Relaxed) && pending.request["expiresAt"].as_f64().unwrap_or(0.)>permission_time()
        && pending.request["navigationEpoch"].as_u64()==Some(current_epoch)
        && source.ok().and_then(|s|permission_origin(&s)).as_deref()==pending.request["origin"].as_str();
    if !fresh {let _=finish_permission(c,pending,false,"Request became stale; ask again");return Err("Permission request became stale; navigate to the page and ask again".into());}
    match a["decision"].as_str(){Some("allow")=>finish_permission(c,pending,true,"Owner allowed this request only"),Some("deny")=>finish_permission(c,pending,false,"Owner denied this request"),_=>{let _=finish_permission(c,pending,false,"Invalid decision");Err("Allow or deny required".into())}}
}
#[cfg(windows)]
fn attach_permissions(core:&webview2_com::Microsoft::Web::WebView2::Win32::ICoreWebView2,c:&Arc<Connection>,a:&Value)->Result<(),String> {
    use webview2_com::{PermissionRequestedEventHandler,Microsoft::Web::WebView2::Win32::*};
    use windows::core::{Interface,PWSTR};
    let c=c.clone();let a=a.clone();
    let handler=PermissionRequestedEventHandler::create(Box::new(move|sender,args|{unsafe{
        let (Some(core),Some(args))=(sender,args) else{return Ok(());};
        // Refuse by default before any fallible inspection. Never save a grant in the profile.
        args.SetState(COREWEBVIEW2_PERMISSION_STATE_DENY)?;
        if let Ok(modern)=args.cast::<ICoreWebView2PermissionRequestedEventArgs2>(){modern.SetHandled(true)?;}
        let persistence=args.cast::<ICoreWebView2PermissionRequestedEventArgs3>().and_then(|modern|modern.SetSavesInProfile(false));
        let mut uri=PWSTR::null();args.Uri(&mut uri)?;let origin=permission_origin(&webview2_com::take_pwstr(uri));
        let mut source=PWSTR::null();core.Source(&mut source)?;let top_origin=permission_origin(&webview2_com::take_pwstr(source));
        let mut kind=COREWEBVIEW2_PERMISSION_KIND(0);args.PermissionKind(&mut kind)?;
        let tab=a["tabId"].as_str().unwrap_or("");let epoch=c.navigation_epochs.lock().unwrap().get(tab).copied().unwrap_or(0);
        let notification=kind==COREWEBVIEW2_PERMISSION_KIND_NOTIFICATIONS;
        let bounded=c.permissions.lock().unwrap().len()<20;
        let eligible=notification && origin.is_some() && origin==top_origin && persistence.is_ok() && bounded && !c.stop.load(Ordering::Relaxed);
        let mut user=windows::core::BOOL(0);args.IsUserInitiated(&mut user)?;
        let request=json!({"type":"permission","requestId":format!("permission-{}",uuid::Uuid::new_v4()),"tabId":tab,"profileId":a["profileId"],"private":a["private"].as_bool().unwrap_or(false),"origin":origin.unwrap_or_default(),"navigationEpoch":epoch,"kind":if notification{"notifications"}else{"unsupported"},"state":if eligible{"pending"}else{"denied"},"reason":if eligible{"Owner decision required; this request expires in 30 seconds"}else{if persistence.is_err(){"This WebView2 runtime cannot disable profile permission persistence; request denied. Update the app runtime before requesting consent."}else{"This capability or origin is unsupported; native permission was denied"}},"expiresAt":permission_time()+30.,"nativeAcknowledged":!eligible,"userInitiated":user.as_bool(),"savedInProfile":persistence.is_err()});
        if eligible {
            let deferral=args.GetDeferral()?;let id=request["requestId"].as_str().unwrap().to_string();
            c.permissions.lock().unwrap().insert(id.clone(),request.clone());
            PERMISSION_DEFERRALS.with(|rows|rows.borrow_mut().insert(id,NativePermission{args,deferral,core,request:request.clone()}));
        }
        send(&c,request);Ok(())
    }}));
    let mut token=0;unsafe{core.add_PermissionRequested(&handler,&mut token).map_err(|e|e.to_string())}
}

#[cfg(windows)]
fn configure_native(
    view: &Webview,
    c: &Arc<Connection>,
    a: &Value,
    url: &tauri::Url,
    navigate: bool,
) -> Result<(), String> {
    use webview2_com::{
        FaviconChangedEventHandler, Microsoft::Web::WebView2::Win32::*,
        WebResourceRequestedEventHandler,
    };
    use windows::core::{Interface, PCWSTR, PWSTR};
    let c = c.clone();
    let a = a.clone();
    let url = url.to_string();
    view.with_webview(move |platform| {
        let result = (|| -> Result<Value, String> { unsafe {
            let core = platform.controller().CoreWebView2().map_err(|e|e.to_string())?;
            attach_permissions(&core,&c,&a)?;
            let environment = core.cast::<ICoreWebView2_2>().and_then(|x|x.Environment()).map_err(|e|e.to_string())?;
            let filter_c = c.clone(); let tab = a["tabId"].as_str().unwrap_or("").to_string();
            let count = Arc::new(Mutex::new(0_u64));
            let filter = WebResourceRequestedEventHandler::create(Box::new(move |sender, args| {
                let (Some(sender), Some(args)) = (sender, args) else { return Ok(()); };
                let config = filter_c.shields.lock().unwrap().get(&tab).cloned().unwrap_or(Value::Null);
                let enabled = config["enabled"].as_bool().unwrap_or(true);
                let mut source = PWSTR::null(); sender.Source(&mut source)?;
                let site = tauri::Url::parse(&webview2_com::take_pwstr(source)).ok().and_then(|u|u.host_str().map(str::to_owned)).unwrap_or_default();
                let allowed = config["allowSites"].as_array().map(|rows|rows.iter().any(|x|x.as_str()==Some(&site))).unwrap_or(false);
                if !enabled || allowed { return Ok(()); }
                let mut uri = PWSTR::null(); args.Request()?.Uri(&mut uri)?;
                let request = webview2_com::take_pwstr(uri);
                let host = tauri::Url::parse(&request).ok().and_then(|u|u.host_str().map(str::to_owned)).unwrap_or_default();
                let defaults = ["doubleclick.net","googlesyndication.com","google-analytics.com","googleadservices.com","adnxs.com","scorecardresearch.com"];
                let extra = config["filterHosts"].as_array();
                let matches = |rule: &str| host == rule || host.ends_with(&format!(".{}",rule));
                if defaults.iter().any(|rule|matches(rule)) || extra.map(|rows|rows.iter().filter_map(Value::as_str).take(256).any(matches)).unwrap_or(false) {
                    let reason:Vec<u16>="Blocked by Neyvia shield".encode_utf16().chain(Some(0)).collect();
                    let headers:Vec<u16>="Content-Length: 0\r\n".encode_utf16().chain(Some(0)).collect();
                    let response = environment.CreateWebResourceResponse(None,403,PCWSTR(reason.as_ptr()),PCWSTR(headers.as_ptr()))?;
                    args.SetResponse(&response)?;
                    let mut count = count.lock().unwrap(); *count += 1;
                    send(&filter_c,json!({"type":"shield","tabId":tab,"blockedCount":*count,"enabled":enabled,"siteAllowed":false}));
                }
                Ok(())
            }));
            let mut token=0;
            core.AddWebResourceRequestedFilter(PCWSTR([42_u16,0].as_ptr()),COREWEBVIEW2_WEB_RESOURCE_CONTEXT_ALL).map_err(|e|e.to_string())?;
            core.add_WebResourceRequested(&filter,&mut token).map_err(|e|e.to_string())?;
            let modern:ICoreWebView2_15 = core.cast().map_err(|e|e.to_string())?;
            let favicon_c=c.clone(); let favicon_tab=a["tabId"].clone();
            let favicon = FaviconChangedEventHandler::create(Box::new(move |sender,_| {
                if let Some(sender)=sender { let modern:ICoreWebView2_15=sender.cast()?; let mut value=PWSTR::null(); modern.FaviconUri(&mut value)?;
                    send(&favicon_c,json!({"type":"favicon","tabId":favicon_tab,"url":webview2_com::take_pwstr(value)})); }
                Ok(())
            }));
            modern.add_FaviconChanged(&favicon,&mut token).map_err(|e|e.to_string())?;
            if navigate && a["clearHistoryOnOpen"] == true {
                let profile:ICoreWebView2Profile2=core.cast::<ICoreWebView2_13>().and_then(|x|x.Profile()).and_then(|x|x.cast()).map_err(|e|e.to_string())?;
                let callback_c=c.clone();let action=a.clone();let target=url.clone();let kept=core.clone();
                let callback=webview2_com::ClearBrowsingDataCompletedHandler::create(Box::new(move |status| {
                    let result=status.and_then(|_| {
                        send(&callback_c,json!({"type":"history_cleared","tabId":action["tabId"],"profileId":action["profileId"]}));
                        let wide:Vec<_>=target.encode_utf16().chain(Some(0)).collect();kept.Navigate(PCWSTR(wide.as_ptr()))
                    }).map(|_|json!({"live":true,"engine":"WebView2","historyCleared":true,"shieldAttached":true})).map_err(|e|e.to_string());
                    completion(&callback_c,&action,result);Ok(())
                }));
                profile.ClearBrowsingData(COREWEBVIEW2_BROWSING_DATA_KINDS_BROWSING_HISTORY,&callback).map_err(|e|e.to_string())?;
                return Ok(json!({"awaitingNativeCallback":true}));
            }
            if navigate { let wide:Vec<_>=url.encode_utf16().chain(Some(0)).collect(); core.Navigate(PCWSTR(wide.as_ptr())).map_err(|e|e.to_string())?; }
            Ok(json!({"live":true,"engine":"WebView2","shieldAttached":true}))
        }})();
        if (navigate && !result.as_ref().map(|r|r["awaitingNativeCallback"]==true).unwrap_or(false)) || result.is_err() { completion(&c,&a,result); }
    }).map_err(|e|e.to_string())
}

#[cfg(windows)]
fn clear_history_native(view: &Webview, c: &Arc<Connection>, a: &Value) -> Result<(), String> {
    use webview2_com::{ClearBrowsingDataCompletedHandler, Microsoft::Web::WebView2::Win32::*};
    use windows::core::Interface;
    let c = c.clone();
    let a = a.clone();
    view.with_webview(move |platform| {
        let result=(|| -> Result<(),String> { unsafe {
            let core:ICoreWebView2_13=platform.controller().CoreWebView2().and_then(|x|x.cast()).map_err(|e|e.to_string())?;
            let profile:ICoreWebView2Profile2=core.Profile().and_then(|x|x.cast()).map_err(|e|e.to_string())?;
            let callback_c=c.clone();let action=a.clone();
            let callback=ClearBrowsingDataCompletedHandler::create(Box::new(move |status| {
                let result=status.map(|_|{send(&callback_c,json!({"type":"history_cleared","tabId":action["tabId"],"profileId":action["profileId"]}));json!({"historyCleared":true,"profileId":action["profileId"]})}).map_err(|e|e.to_string());
                completion(&callback_c,&action,result);Ok(())
            }));
            profile.ClearBrowsingData(COREWEBVIEW2_BROWSING_DATA_KINDS_BROWSING_HISTORY,&callback).map_err(|e|e.to_string())?;
            Ok(())
        }})();if let Err(error)=result{completion(&c,&a,Err(error));}
    }).map_err(|e|e.to_string())
}

#[cfg(windows)]
fn install_download_permissions(view: &Webview,c: &Arc<Connection>,tab: &str)->Result<(),String>{
    use webview2_com::{PermissionRequestedEventHandler,Microsoft::Web::WebView2::Win32::*};
    use windows::core::Interface;
    let c=c.clone();let tab=tab.to_string();
    view.with_webview(move|platform| unsafe {
        if let Ok(core)=platform.controller().CoreWebView2(){
            let permission=c.clone();let permission_tab=tab.clone();
            let callback=PermissionRequestedEventHandler::create(Box::new(move|_,args|{
                if let Some(args)=args {
                    let mut kind=COREWEBVIEW2_PERMISSION_KIND::default();
                    args.PermissionKind(&mut kind)?;
                    if kind==COREWEBVIEW2_PERMISSION_KIND_MULTIPLE_AUTOMATIC_DOWNLOADS {
                        let requested=permission.downloads.lock().unwrap().get(&permission_tab).map(|s|s.granted).unwrap_or(false);
                        let ephemeral=match args.cast::<ICoreWebView2PermissionRequestedEventArgs3>() {
                            Ok(modern)=>modern.SetSavesInProfile(false).is_ok(),
                            Err(_)=>false,
                        };
                        let allowed=requested && ephemeral;
                        args.SetState(if allowed{COREWEBVIEW2_PERMISSION_STATE_ALLOW}else{COREWEBVIEW2_PERMISSION_STATE_DENY})?;
                        send(&permission,json!({"type":"permission","tabId":permission_tab,"kind":"multiple_automatic_downloads","allowed":allowed}));
                    }
                }
                Ok(())
            }));
            let mut registration=0;
            if core.add_PermissionRequested(&callback,&mut registration).is_ok(){
                if let Some(state)=c.downloads.lock().unwrap().get_mut(&tab){state.hooked=true;}
            }
        }
    }).map_err(|e|e.to_string())
}

#[cfg(windows)]
fn readback_native(view: &Webview, c: &Arc<Connection>, a: &Value) -> Result<(), String> {
    use webview2_com::ExecuteScriptCompletedHandler;
    use windows::core::PCWSTR;
    let c = c.clone();
    let a = a.clone();
    view.with_webview(move |platform| {
        let result = (|| -> Result<(), String> { unsafe {
            let script = if a["op"] == "dom" {
                format!("window.__neyviaBrowser && window.__neyviaBrowser.dom({})",a)
            } else if a["op"] == "observe" {
                "window.__neyviaBrowser && window.__neyviaBrowser.snapshot()".to_string()
            } else if a["op"] == "annotate" {
                format!("(() => {{if(!window.__neyviaBrowser)return null;const result=window.__neyviaBrowser.annotate({});return {{ok:result.ok,result,projection:window.__neyviaBrowser.snapshot()}};}})()",a)
            } else {
                format!("(() => {{if(!window.__neyviaBrowser)return null;const result=window.__neyviaBrowser.perform({},true);return {{ok:result.ok,result,projection:window.__neyviaBrowser.snapshot()}};}})()", a)
            };
            let script: Vec<u16> = script.encode_utf16().chain(Some(0)).collect();
            let connection = c.clone();
            let action = a.clone();
            let callback = ExecuteScriptCompletedHandler::create(Box::new(move |status, raw| {
                let result = status.map_err(|e| e.to_string()).and_then(|_| serde_json::from_str::<Value>(&raw).map_err(|e| e.to_string()));
                match result {
                    Ok(value) if action["op"] == "observe" && value["elements"].is_array() && value["revision"].is_string() => {
                        send(&connection, json!({"type":"projection","actionId":action["id"],"tabId":action["tabId"],"projection":value}));
                    },
                    Ok(value) if (action["op"] == "action" || action["op"] == "annotate") && value["ok"] == true => {
                        send(&connection,json!({"type":"projection","tabId":action["tabId"],"projection":value["projection"]}));
                        completion(&connection,&action,Ok(value["result"].clone()));
                    },
                    Ok(value) if action["op"] == "dom" && value["ok"] == true => completion(&connection,&action,Ok(value)),
                    Ok(value) => completion(&connection,&action,Err(format!("Native page readback unavailable or refused: {}",value))),
                    Err(error) => completion(&connection,&action,Err(error)),
                }
                Ok(())
            }));
            platform.controller().CoreWebView2().map_err(|e| e.to_string())?.ExecuteScript(PCWSTR(script.as_ptr()),&callback).map_err(|e| e.to_string())?;
            Ok(())
        }})();
        if let Err(error) = result { completion(&c,&a,Err(error)); }
    }).map_err(|e| e.to_string())
}

#[cfg(windows)]
fn import_native(
    view: &Webview,
    c: &Arc<Connection>,
    a: &Value,
    url: &tauri::Url,
    state: Value,
) -> Result<(), String> {
    use webview2_com::Microsoft::Web::WebView2::Win32::*;
    use windows::core::{Interface, PCWSTR};
    let c = c.clone();
    let a = a.clone();
    let url = url.to_string();
    view.with_webview(move |platform| {
        let result = (|| -> Result<Value, String> {
            unsafe {
                let core = platform
                    .controller()
                    .CoreWebView2()
                    .map_err(|e| e.to_string())?;
                let modern: ICoreWebView2_2 = core.cast().map_err(|e| e.to_string())?;
                let manager = modern.CookieManager().map_err(|e| e.to_string())?;
                for row in state["cookies"].as_array().into_iter().flatten() {
                    let wide = |key: &str| {
                        row[key]
                            .as_str()
                            .unwrap_or("")
                            .encode_utf16()
                            .chain(Some(0))
                            .collect::<Vec<_>>()
                    };
                    let name = wide("name");
                    let value = wide("value");
                    let domain = wide("domain");
                    let path = wide("path");
                    let cookie = manager
                        .CreateCookie(
                            PCWSTR(name.as_ptr()),
                            PCWSTR(value.as_ptr()),
                            PCWSTR(domain.as_ptr()),
                            PCWSTR(path.as_ptr()),
                        )
                        .map_err(|e| e.to_string())?;
                    cookie
                        .SetIsHttpOnly(row["httpOnly"] == true)
                        .map_err(|e| e.to_string())?;
                    cookie
                        .SetIsSecure(row["secure"] == true)
                        .map_err(|e| e.to_string())?;
                    let same = match row["sameSite"].as_str() {
                        Some("Strict") => COREWEBVIEW2_COOKIE_SAME_SITE_KIND_STRICT,
                        Some("Lax") => COREWEBVIEW2_COOKIE_SAME_SITE_KIND_LAX,
                        _ => COREWEBVIEW2_COOKIE_SAME_SITE_KIND_NONE,
                    };
                    cookie.SetSameSite(same).map_err(|e| e.to_string())?;
                    if let Some(expires) = row["expires"].as_f64().filter(|x| *x > 0.) {
                        cookie.SetExpires(expires).map_err(|e| e.to_string())?;
                    }
                    manager
                        .AddOrUpdateCookie(&cookie)
                        .map_err(|e| e.to_string())?;
                }
                let requested: Vec<_> = url.encode_utf16().chain(Some(0)).collect();
                core.Navigate(PCWSTR(requested.as_ptr()))
                    .map_err(|e| e.to_string())?;
                Ok(json!({"live":true,"engine":"WebView2","importedState":true}))
            }
        })();
        completion(&c, &a, result);
    })
    .map_err(|e| e.to_string())
}

#[cfg(windows)]
fn capture_native(view: &Webview, c: &Arc<Connection>, a: &Value) -> Result<(), String> {
    use webview2_com::{
        CapturePreviewCompletedHandler,
        Microsoft::Web::WebView2::Win32::COREWEBVIEW2_CAPTURE_PREVIEW_IMAGE_FORMAT_PNG,
    };
    use windows::{
        core::PCWSTR,
        Win32::{
            System::Com::{STGC_DEFAULT, STGM_CREATE, STGM_WRITE},
            UI::Shell::SHCreateStreamOnFileEx,
        },
    };
    let path = PathBuf::from(a["path"].as_str().ok_or("Missing owned capture path")?);
    if !path.is_absolute()
        || path.extension().and_then(|x| x.to_str()) != Some("png")
        || path.exists()
    {
        return Err("Capture needs a new absolute PNG path".into());
    }
    std::fs::create_dir_all(path.parent().ok_or("Capture directory missing")?)
        .map_err(|e| e.to_string())?;
    let c = c.clone();
    let a = a.clone();
    view.with_webview(move|platform|{
        let result=(||->Result<(),String>{unsafe{
            let filename:Vec<_>=path.to_string_lossy().encode_utf16().chain(Some(0)).collect();
            let stream=SHCreateStreamOnFileEx(PCWSTR(filename.as_ptr()),STGM_CREATE.0|STGM_WRITE.0,0,true,None).map_err(|e|e.to_string())?;
            let kept=stream.clone();let callback_connection=c.clone();let action=a.clone();let target=path.clone();
            let callback=CapturePreviewCompletedHandler::create(Box::new(move|status|{
                let result=status.and_then(|_|kept.Commit(STGC_DEFAULT)).map_err(|e|e.to_string()).and_then(|_|{
                    std::fs::metadata(&target).map(|m|json!({"path":target.to_string_lossy(),"bytes":m.len(),"format":"png","engine":"WebView2"})).map_err(|e|e.to_string())
                });completion(&callback_connection,&action,result);Ok(())
            }));
            platform.controller().CoreWebView2().map_err(|e|e.to_string())?.CapturePreview(COREWEBVIEW2_CAPTURE_PREVIEW_IMAGE_FORMAT_PNG,&stream,&callback).map_err(|e|e.to_string())?;Ok(())
        }})();
        if let Err(error)=result{completion(&c,&a,Err(error));}
    }).map_err(|e|e.to_string())
}

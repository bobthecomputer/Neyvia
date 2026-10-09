fn main() {
    // Tauri tries URL deserialization before directory deserialization.
    // A Windows drive path therefore becomes a `c:` URL, opening Explorer's
    // directory listing instead of embedding the frontend into the binary.
    println!("cargo:rerun-if-env-changed=TAURI_CONFIG");
    let base = std::fs::read_to_string("tauri.conf.json").expect("read Tauri config");
    let base: serde_json::Value = serde_json::from_str(&base).expect("parse Tauri config");
    let overlay: serde_json::Value = std::env::var("TAURI_CONFIG")
        .ok()
        .map(|value| serde_json::from_str(&value).expect("parse TAURI_CONFIG"))
        .unwrap_or_default();
    let dist = overlay.pointer("/build/frontendDist")
        .or_else(|| base.pointer("/build/frontendDist"))
        .and_then(|value| value.as_str());
    if let Some(dist) = dist {
        assert!(!invalid_local_frontend_url(dist),
            "frontendDist must use a relative directory path, not a Windows drive path or file URL; otherwise Tauri opens a directory listing");
    }
    tauri_build::build()
}

include!("build_frontend_guard.rs");

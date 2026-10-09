#[path = "../../src-tauri/src/base_pack.rs"]
mod base_pack;
use std::sync::{atomic::AtomicBool, Arc};

#[tokio::main]
async fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 5 {
        eprintln!(
            "pack-probe <install|verify> <root> <manifest-url> <public-key> [pack-id] [pause-ms]"
        );
        std::process::exit(2);
    }
    let config = base_pack::PackConfig {
        root: args[2].clone().into(),
        manifest_url: args[3].clone(),
        public_key: args[4].clone(),
        expected_id: args.get(5).cloned().unwrap_or_else(|| "base".into()),
        allow_large: false,
    };
    let cancel = Arc::new(AtomicBool::new(false));
    let stdin_cancel = cancel.clone();
    std::thread::spawn(move || {
        let mut line = String::new();
        if std::io::stdin().read_line(&mut line).is_ok() && line.trim() == "pause" {
            stdin_cancel.store(true, std::sync::atomic::Ordering::Relaxed);
        }
    });
    if let Some(ms) = args.get(6).and_then(|s| s.parse::<u64>().ok()) {
        let flag = cancel.clone();
        tokio::spawn(async move {
            tokio::time::sleep(std::time::Duration::from_millis(ms)).await;
            flag.store(true, std::sync::atomic::Ordering::Relaxed);
        });
    }
    let result = if args[1] == "verify" {
        base_pack::verify_active(&config).await
    } else {
        base_pack::install(&config, &cancel, |state| println!("{}", state)).await
    };
    match result {
        Ok(receipt) => println!("{}", serde_json::json!({"ok":true,"receipt":receipt})),
        Err(error) => {
            println!("{}", serde_json::json!({"ok":false,"error":error}));
            std::process::exit(1);
        }
    }
}

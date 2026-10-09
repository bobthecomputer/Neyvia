use base64::{engine::general_purpose::STANDARD, Engine as _};
use minisign_verify::{PublicKey, Signature};
use std::{env, fs, path::Path};

fn decode_tauri_minisign_file(path: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let text = fs::read_to_string(path)?;
    if text.starts_with("untrusted comment:") {
        return Ok(text);
    }
    Ok(String::from_utf8(STANDARD.decode(text.trim())?)?)
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let arguments: Vec<String> = env::args().collect();
    if arguments.len() != 4 {
        return Err("usage: verify_updater_signature <public-key> <artifact> <signature>".into());
    }
    let public_key_text = decode_tauri_minisign_file(Path::new(&arguments[1]))?;
    let signature_text = decode_tauri_minisign_file(Path::new(&arguments[3]))?;
    let public_key = PublicKey::decode(&public_key_text)?;
    let signature = Signature::decode(&signature_text)?;
    let artifact = fs::read(&arguments[2])?;
    public_key.verify(&artifact, &signature, false)?;
    println!("verified {}", arguments[2]);
    Ok(())
}

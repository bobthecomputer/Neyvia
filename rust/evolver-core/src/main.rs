//! L0 for the restricted text domain. No shell, paths, judges or evaluation
//! rules are executable genome nodes. Newline encoding is an exact rendering
//! equivalence, not a claim of semantic equivalence between different wording.
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::io::{self, BufRead};

fn canonicalize(genome: &Value) -> Result<Value, String> {
    let map = genome.as_object().ok_or("expected a typed text genome")?;
    if map.len() != 2 || map.get("kind").and_then(Value::as_str) != Some("text") {
        return Err("only kind='text' and text are allowed; authority is frozen".into());
    }
    let text = map.get("text").and_then(Value::as_str).ok_or("text must be a string")?;
    if text.is_empty() || text.len() > 256_000 || text.contains('\0') {
        return Err("text must be nonempty, <=256000 bytes, without NUL".into());
    }
    let canonical = json!({"kind":"text", "text":text.replace("\r\n", "\n").replace('\r', "\n")});
    let bytes = serde_json::to_vec(&canonical).map_err(|e| e.to_string())?;
    let id = format!("{:x}", Sha256::digest(bytes));
    Ok(json!({"id":id,"eclass_id":id,"canonical":canonical,"level":"L0","equivalence":"newline-encoding/v1"}))
}

fn main() {
    for line in io::stdin().lock().lines() {
        let result = line.map_err(|e| e.to_string())
            .and_then(|s| serde_json::from_str::<Value>(&s).map_err(|e| e.to_string()))
            .and_then(|v| canonicalize(&v));
        match result {
            Ok(value) => println!("{}", value),
            Err(error) => println!("{}", json!({"error":error,"rejected":true,"level":"L0"})),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn newline_equivalence_preserves_markdown_breaks() {
        let a = canonicalize(&json!({"kind":"text","text":"hello  \r\nworld"})).unwrap();
        let b = canonicalize(&json!({"kind":"text","text":"hello  \nworld"})).unwrap();
        assert_eq!(a["id"], b["id"]);
        assert_ne!(a["id"], canonicalize(&json!({"kind":"text","text":"hello\nworld"})).unwrap()["id"]);
    }
    #[test]
    fn rejects_judge_payload() {
        assert!(canonicalize(&json!({"kind":"text","text":"x","judges":[]})).is_err());
    }
}

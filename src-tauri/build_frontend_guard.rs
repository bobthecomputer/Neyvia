fn invalid_local_frontend_url(path: &str) -> bool {
    let bytes = path.as_bytes();
    path.to_ascii_lowercase().starts_with("file:")
        || (bytes.len() >= 2 && bytes[0].is_ascii_alphabetic() && bytes[1] == b':')
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_windows_paths_and_file_urls() {
        assert!(invalid_local_frontend_url(r"C:\Users\user\build"));
        assert!(invalid_local_frontend_url("D:/build"));
        assert!(invalid_local_frontend_url("file:///C:/build"));
    }

    #[test]
    fn accepts_relative_asset_directories() {
        assert!(!invalid_local_frontend_url("../web/dist"));
        assert!(!invalid_local_frontend_url("../.agent_control/goal-loop-20260928/web-final"));
    }
}

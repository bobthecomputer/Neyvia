# setup_nas_https

Provides script / setup_nas_https in Neyvia.

- **Public API:** `backend_start_command`, `discover_firefox_like_profiles`, `enable_firefox_enterprise_roots`, `ensure_local_ca`, `find_openssl`, `issue_server_certificate`, `main`, `public_url_for`, `run`, `sanitize_name`, `split_hosts`, `unique_values`, `windows_import_current_user_root`, `write_openssl_config`, `write_server_ext`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `d.runtime.nas-setup.hosts`, `d.runtime.nas-setup.tls-command`.
- **Dependencies:** None statically declared.
- **Owner:** Neyvia / neyvia.
- **Files:** [scripts/setup_nas_https.py](../../scripts/setup_nas_https.py).

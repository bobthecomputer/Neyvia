# Skill file importer — 2026-09-27

Use composer + → Tools & integrations → Skills → Choose skill files. The picker accepts multiple .md, .txt, .zip and .rar files. Inspect first, select the detected skills, then Import selected. Existing destinations are skipped, preserving user edits. Imports target the active workspace's .codex/skills and become available in Native's skill catalog, including on-demand reads and Use actions. References and scripts are retained as files; no bundled script runs during import.

ZIP uses the standard ZIP reader. RAR uses a detected libarchive-compatible tar (Windows includes it on this machine), with bounded extraction to stdout; no archive-supplied paths are extracted by the external program. RAR support was verified with a genuine RAR4 archive. Password-protected/multipart archives were not verified. If no compatible tar is present, the UI reports the requirement; ZIP and individual files remain usable.

Limits: 100 uploaded files/skills per batch, 20 MiB compressed/uploaded total, 50 MiB unpacked total, 5 MiB per resource, 512 KiB per SKILL.md. Reject traversal, Windows special paths, links, duplicate path aliases and oversized instructions. Nothing from the user's previous skills.rar was installed.

Verification: Node-driven production checks pass for multi-file selection, selective installation, reference preservation, existing-skill collision, consumed-stage reuse, ZIP traversal, Windows path aliases, links, instruction size and real RAR. Desktop subprocess check accepts >2 MiB batch envelopes and verifies exact installed bytes. Actual local browser journey exercised Markdown+ZIP, deselection, installation/catalog refresh and RAR installation. Disposable samples were moved out of the active catalog into the proof folder afterward. Native reads verified installed instruction hashes and reference contents.

Shared routes: web backend dispatch, local desktop bridge and desktop-controller request envelope. Built frontend and NSIS installer are local artifacts, not an installed/public update.

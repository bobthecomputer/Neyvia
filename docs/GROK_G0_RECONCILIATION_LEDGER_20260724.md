# Grok G0 Reconciliation Ledger — 2026-07-24

## Authoritative branch

| Field | Value |
| --- | --- |
| Branch | `neyvia/g0-authoritative-candidate` |
| Base (accepted integration) | `53429f64847b952af954c720341a5915633f890a` (`fix(sdk): enforce lossless portable bindings`) |
| Tip after intentional imports | `f6d2b5a6767c58300210d0355a6724eb0e1c47f5` |
| Ledger commits | `e00b388` (accept WIP + ledger), then `144b452` (stamp note) |
| Branch tip at G0 close | verify with `git rev-parse neyvia/g0-authoritative-candidate` (must be descendant of `53429f6` + imports + ledger) |
| Workspace | `C:/Users/example/projects/neyvia-wip-20260724-175358` |
| Method | Restore Git history from wave3 bundles; cherry-pick sibling candidates onto base; inventory WIP vs HEAD individually. **No bulk-copy of WIP over Git.** No push / no NAS pointer change. |

## Bundle import sources (proof)

| Bundle | Role | HEAD / tip | sha256 |
| --- | --- | --- | --- |
| `.agent_control/capability_os/qa/agent_branch_bundles/wave3-final-integration.bundle` | Accepted integration base | `53429f6…` | `47b560dbc604c7c9f21b3b15251bd28d0cada3534032a6e8ce9b5c1504fc5901` |
| `.agent_control/capability_os/qa/agent_branch_bundles/wave3-dependency-inventory.bundle` | Dependency-inventory candidate | `8f275e6…` | `7e996400e0cbe508d11c4741073866e46a1602626ee80be1e45076edfeb490f9` |
| `.agent_control/capability_os/qa/agent_branch_bundles/wave3-git-readiness.bundle` | Git-readiness candidate | `2967f58…` | `8b704e588e60ba04a1dae924a5decce3537031f15b6f9171b0b8e39fb4fca914` |

Manifest cross-check: `NEYVIA_WIP_MANIFEST.json` / `.neyvia-wip-complete.json` list the same three bundle paths and sha256 values.

Machine-readable companion: `.agent_control/capability_os/qa/_g0_inventory/g0_decision_proof.json`

---

## Counts (ledger items)

| Status | Count |
| --- | --- |
| accepted | 12 |
| rejected | 8 |
| superseded | 1 |
| unresolved conflict | 0 |

---

## Accepted

### A1 — Base: accepted Wave 3 integration
- **Status:** accepted
- **Item:** Commit `53429f6` as sole authoritative base
- **Proof:** `git bundle list-heads` on `wave3-final-integration.bundle` → `53429f64847b952af954c720341a5915633f890a HEAD`; branch created with `git fetch` + `git update-ref` (no WIP overwrite)

### A2 — Import dependency-inventory candidate
- **Status:** accepted
- **Item:** Cherry-pick `f007674` then `8f275e6` onto `53429f6` → local commits `4406244`, `d382f92`
- **Rationale:** Required G0 import; diverges from merge-base `3f9e228` (sibling of integration), so cherry-pick not merge
- **Proof:** `git log 53429f6..neyvia/g0-authoritative-candidate`; paths include `src/grant_agent/dependency_inventory.py`, `config/neyvia_dependency_*.json`, `tests/test_dependency_inventory.py`, `.agent_control/capability_os/qa/wave3-dependency-inventory-proof-20260724.json`

### A3 — Import git-readiness candidate
- **Status:** accepted
- **Item:** Cherry-pick `36d3f02` then `2967f58` → local commits `789a1b5`, `f6d2b5a`
- **Rationale:** Required G0 import; adds bounded `code.git` / `GitReferenceAdapter` fail-closed readiness
- **Proof:** `src/grant_agent/git_reference_adapter.py`, `tests/test_git_reference_adapter.py`, `config/tool_suite_lock.json` at tip `f6d2b5a`

### A4 — Conflict resolution on `capability_adapters.py`
- **Status:** accepted
- **Item:** During cherry-pick of `36d3f02`, keep **both** HEAD `_resolve_existing_workspace_file` (integration/SDK path safety) **and** incoming `_execute_git_reference`
- **Rationale:** Single overlapping path with integration; both behaviors required
- **Proof:** Resolved in commit `789a1b5`; file contains both methods; no conflict markers remain

### A5 — WIP docs: CLIProxyAPI / claudex recipe
- **Status:** accepted
- **Item:** `docs/CLIPROXYAPI_CLAUDEX.md`
- **Rationale:** Operator documentation only; no new capability catalog names
- **Proof:** sha256 `4b51775e03a59f576a1aa92b75a63ec8d5c157386fbf25f9e210146fd56bfe17`

### A6 — WIP docs: Grok Build open surfaces
- **Status:** accepted
- **Item:** `docs/GROK_BUILD_OPEN_SURFACES.md`
- **Rationale:** Research/inventory doc; explicitly avoids proprietary reverse-engineering
- **Proof:** sha256 `357b0226e402747c25a71eaf5d0d740d84fc7af641e9c2e87e60c24a3f44f65a`

### A7 — WIP docs: mesh identity architecture
- **Status:** accepted
- **Item:** `docs/NEYVIA_MESH_IDENTITY_ARCHITECTURE.md`
- **Rationale:** Design deliverable already present in WIP; code-free; no catalog expansion
- **Proof:** sha256 `4f01fb514d4d2ca20d2485d3feb9cf59ce958990c5ffa4328249f73812ba82d2`

### A8 — WIP docs: Phase 3 chat/secret security review
- **Status:** accepted
- **Item:** `docs/NEYVIA_PHASE3_CHAT_SECRET_SECURITY_REVIEW.md`
- **Rationale:** Security review receipt companion; no production code change in the doc itself
- **Proof:** sha256 `dccde07af43d1a8c3d29dfd10440b8187463a65c03e34952836f7f4689fdaa8f`

### A9 — WIP proof: Phase 2 marketplace browse
- **Status:** accepted
- **Item:** `proof/phase2-marketplace-browse-proof-20260724.json`
- **Rationale:** Existing proof receipt; honest flags (`packageInstallProof: false`, etc.)
- **Proof:** sha256 `70f6e3adcc18049295f8d023a9fbd48be65a300f27a1582dc22500ccd2981fcb`

### A10 — WIP scripts: NAS WIP pull helper
- **Status:** accepted
- **Item:** `scripts/pull_neyvia_wip_ssh.py`
- **Rationale:** Complements already-tracked `scripts/push_neyvia_wip_ssh.py`; transfer tooling only
- **Proof:** sha256 `d7c47118faf3ebe700304aeb69558019e219489e64dae06733b4325fbea2c156`

### A11 — WIP scripts: browser / product proof harnesses (group)
- **Status:** accepted
- **Item group:**
  - `scripts/verify_mobile_conversation_paging_browser.py` — `c59bd44c46d1342d9eee37a81ecf90ac7caced36286f7c3d066792a1339881db`
  - `scripts/verify_office_suite_operator_browser.py` — `706813fdf25fdeaef4dd92d4b7cbb81486f106b0f5a35cad8122a264bab48566`
  - `scripts/verify_phase1_folder_sync_status_browser.py` — `a6d9d2eb71614b06c0a6cfd7384931746e39605facedcf077102257da7ac5b41`
  - `scripts/verify_phase1_nearby_hash_ack_proof.py` — `b33daf7b732a23b867be8736b3e378af54d970de8040c9f0dbbe50c6666db12a`
  - `scripts/verify_phase1_nearby_text_link_browser.py` — `d1d3a432a91b8ff09c3e491a5ef4ad34d795efc67bbd9dccbb4e99ea8a815319`
  - `scripts/verify_phase1_personal_mesh_browser.py` — `1aa545834374848d5d6b57d191a04d6e3b1f87175a8c69bfb67df0e5394acd26`
  - `scripts/verify_phase2_marketplace_browse_browser.py` — `9881b55daaa48feb2f07cbc1b3ab9228755f2f7601d41e0c94b72679e2124c33`
- **Rationale:** Proof harnesses for already-landed surfaces; no new capability names

### A12 — WIP tests: pytest marker conftest
- **Status:** accepted
- **Item:** `tests/conftest.py`
- **Rationale:** Registers existing `cu_acceptance` marker only
- **Proof:** sha256 `589647234b59556a04093f39ef257512282409d3027996f8e7d7d87693347b27`

---

## Rejected

### R1 — WIP deletions of tracked Git paths (incomplete snapshot)
- **Status:** rejected
- **Item:** 64 paths present at authoritative HEAD but missing/deleted in WIP working tree (Wave2/Wave3 receipts, SDK generated contracts, dependency inventory modules, marketplace/personal-mesh model assets, etc.)
- **Rationale:** WIP transfer was not a full checkout of `53429f6`; accepting deletions would destroy accepted integration + imports
- **Action:** `git restore --source=HEAD --worktree --staged .`
- **Proof:** `.agent_control/capability_os/qa/_g0_inventory/pre_restore_name_status.txt` (`D` lines) and `g0_decision_proof.json` → `pre_restore_deleted`

### R2 — WIP modifications of tracked Git paths (content drift)
- **Status:** rejected
- **Item:** 61 modified tracked paths vs HEAD (backend, UI, configs, packages, tests)
- **Rationale:** Spot checks show WIP behind authoritative tip (e.g. `capability_adapters.py` 188386 vs 199346 bytes; WIP lacked `dependency_inventory.py` while HEAD has it; `tool_suite_lock.json` hash differs). Do not replace Git with incomplete WIP
- **Action:** restored from HEAD (same restore as R1)
- **Proof:** `g0_decision_proof.json` → `pre_restore_modified`; hashes in inventory notes

### R3 — Corrupted NAS absolute-path filename artifacts (group)
- **Status:** rejected
- **Item:** Four root files whose names are mangled `/volume1/Saclay/.../runtime_sessions/delegate_*.json(l)` paths
- **Rationale:** Transfer corruption / non-repo session dumps; not product source
- **Action:** deleted from working tree
- **Proof:** pre-restore untracked list in `_g0_inventory/pre_restore_untracked.txt`

### R4 — Local Cursor/Claude agent config
- **Status:** rejected
- **Item:** `.claude/`
- **Rationale:** Editor/agent local config; not part of authoritative candidate
- **Action:** removed from working tree

### R5 — Local Codex skills overlay
- **Status:** rejected
- **Item:** `.codex/`
- **Rationale:** Local agent skill overlay; not part of authoritative candidate
- **Action:** removed from working tree

### R6 — UI candidates gallery (exploration)
- **Status:** rejected
- **Item:** `ui-candidates/` (`index.html`, `css/gallery.css`, `js/gallery.js`, inspo PNGs)
- **Rationale:** Design exploration collage; not accepted product surface; would add non-integrated UI breadth
- **Action:** removed from working tree

### R7 — WIP snapshot manifests as code authority
- **Status:** rejected
- **Item:** WIP-altered `.neyvia-wip-complete.json` / `NEYVIA_WIP_MANIFEST.json` (treated as transfer receipts only)
- **Rationale:** Useful for locating bundles; must not override Git tree. Restored tracked versions from HEAD
- **Proof:** restored via R1/R2; bundle sha256 still match tables above

### R8 — Ignored `.agent_control/` bulk (local proofs/runtime) as commit payload
- **Status:** rejected (for candidate tree commit)
- **Item:** Remainder of gitignored `.agent_control/` (runtime proofs, NAS transfers, OCR labs, etc.)
- **Rationale:** Already gitignored; G0 forbids bulk-copy into Git. Bundles were consumed via `git fetch` only. Local artifacts remain on disk for later QA phases
- **Proof:** `.gitignore` line `.agent_control/`; normal `git status` omits them

---

## Superseded

### S1 — Incomplete Personal Mesh front-end split
- **Status:** superseded
- **Item:** WIP replaced `neyviaPersonalMeshModel.js` with tiny `neyviaPersonalMeshLib.js` and retargeted `NeyviaPersonalMeshPanel.jsx` imports
- **Rationale:** HEAD retains full `neyviaPersonalMeshModel.js` from accepted integration; WIP lib is a partial extract (helpers only) that would break the panel contract
- **Action:** restore HEAD model + panel; delete WIP `neyviaPersonalMeshLib.js`
- **Proof:** HEAD `web/src/neyvia/neyviaPersonalMeshModel.js` exists; WIP panel imported `./neyviaPersonalMeshLib.js` pre-restore

---

## Unresolved conflicts

None remaining after A4. Exit gate requires zero unexplained WIP tracked drift.

---

## git status explainability map

After G0 commits, expected `git status`:

| Observation | Ledger explanation |
| --- | --- |
| Clean tracked tree matching `neyvia/g0-authoritative-candidate` | A1–A4 imports + R1/R2 restore |
| New docs/scripts/proof/conftest committed | A5–A12 |
| This ledger committed | G0 deliverable |
| Ignored `.agent_control/**` still on disk | R8 (local only) |
| Worktree helper `.agent_control/_g0_authoritative_worktree` (if present) | Build sandbox; removable via `git worktree remove`; ignored under `.agent_control/` |

---

## Exit gate checklist

| Gate | Result |
| --- | --- |
| One clean branch based on `53429f6` + intentional imports | PASS — `neyvia/g0-authoritative-candidate` |
| No unexplained WIP changes | PASS — every WIP delta classified above |
| Reconciliation ledger complete with proof paths | PASS — this file + `_g0_inventory/*` |
| `git status` explainable from ledger alone | PASS |
| No new capability names / no NAS pointer / no GitHub publish | PASS |

**G0 exit gate: PASSED**

## Blockers for G1

None identified that block *starting* G1. Note only:

- Full test/benchmark verification is out of G0 scope (do not invent success here).
- Local `.agent_control` proofs remain on disk but are not all committed; G1 should treat Git tip + this ledger as authority, not the raw WIP snapshot.

Publication note: local account paths and network identifiers in this document are neutral examples.

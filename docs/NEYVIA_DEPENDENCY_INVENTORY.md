# Neyvia canonical dependency inventory

Generate the inventory and a compact proof receipt without contacting a package
registry:

```powershell
python scripts/generate_dependency_inventory.py `
  --root . `
  --output .agent_control/dependency_inventory.json `
  --proof-output .agent_control/capability_os/qa/dependency-inventory-proof.json
```

`neyvia.dependency-inventory/v2` parses the exact npm, uv, desktop Cargo, Iroh
cache Cargo, managed-tool, and install-profile inputs named in `sourceFiles`.
Each source input has a SHA-256. Every record has an accountable owner, core or
optional classification, exact locally declared license state, installed size
only when a checked-in measurement exists, and update responsibility. Missing
facts remain explicit blockers; the generator never guesses them or fetches
mutable registry metadata.

License facts absent from lockfile formats come from the checked-in
`config/neyvia_dependency_license_evidence.json`. That file is keyed by full
name, version, and source identity, binds the exact Cargo/uv lock digests, and
records the Windows x86-64 / CPython 3.12 release closure. It is collected from
already-resolved local Cargo and Python metadata by
`scripts/collect_dependency_license_evidence.py`; the inventory generator never
performs that collection or contacts the network. Internal install-profile
rows, externally managed tools, optional packs, and bundled release artifacts
remain separate scopes.

The updater policy requires `.agent_control/dependency_inventory.json`. Before
accepting an update it:

1. validates the inventory schema and canonical digest;
2. rebuilds the inventory from the current checked-in inputs;
3. requires literal byte-for-byte equality with the canonical rendering;
4. rejects unresolved owner, license, or update-responsibility fields on core
   records; and
5. requires the signed update manifest and every signed local gate receipt to
   bind the exact `dependencyInventorySha256`.

Therefore editing a report, changing a lockfile after generation, omitting a
critical license, or presenting a manifest for another inventory fails closed.
Ambiguous npm, uv, or Cargo dependency edges also fail rather than disappearing
from the graph. Inputs must be regular non-reparse files and are hashed from
the exact bytes parsed.

The signed desktop release workflow generates a new ignored inventory in its
clean checkout, enforces `--require-updater-eligible`, uploads both inventory
and proof, and only then reaches the Tauri publication action. The returned
updater plan is nonce-, receipt-set-, creation-time-, and expiry-bound but
remains explicitly non-executable until execution reruns the fresh preflight.

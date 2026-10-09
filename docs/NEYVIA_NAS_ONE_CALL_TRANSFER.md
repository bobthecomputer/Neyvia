# Neyvia one-call NAS transfer

Use one blocking command to transfer a file or a filtered folder:

```powershell
neyvia-transfer send "C:\path\to\data"
```

The command discovers Cowork's configured NAS route, copies recursively, verifies transferred files, writes receipts locally and on the NAS, then prints one JSON result containing the final NAS path. It does not create an asynchronous job and does not require status polling.

Choose an explicit location under the NAS `projects` root when needed:

```powershell
neyvia-transfer send "C:\path\to\data" --destination "incoming/training-data"
```

For a machine without an existing mapped drive, either set `NEYVIA_NAS_TRANSFER_ROOT` to its mounted `projects` directory, or provide `NEYVIA_NAS_USER` and `NEYVIA_NAS_PASSWORD` in the local environment. Credentials are used only for Windows share authentication and are never written into a receipt.

An explicit `--nas-root` fails closed. It must already exist, point exactly to the NAS `projects` directory, and on Windows be a UNC path or mapped network drive. Neyvia never infers a NAS route from the current folder, so an unavailable `Y:\projects` cannot fall back to a local folder such as `C:\Users\example\Projects`.

## Safe folder defaults

Folder transfers exclude generated or unsafe-to-copy data by default:

- agent state: `.agent_control`, `.agent_runs*`
- source-control internals: `.git`, `.hg`, `.svn`
- installed dependencies: `node_modules`, `bower_components`
- caches and virtual environments: `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.cache`, `.tox`, `.nox`, `.venv`, `venv`, `env`
- builds and framework outputs: `dist`, `build`, `out`, `target`, `.next`, `.nuxt`, `.svelte-kit`, `.parcel-cache`, `.turbo`, `.vite`, `coverage`, `htmlcov`
- temporary and log directories: `tmp`, `temp`, `log`, `logs`
- generated or sensitive files: `*.log`, `*.tmp`, `*.temp`, `*.pyc`, `*.pyo`, `.DS_Store`, `Thumbs.db`, `.env`, `.env.local`, `.env.*.local`

Use `--include-all` only when the NAS copy deliberately needs those paths:

```powershell
neyvia-transfer send "C:\path\to\project" --destination "backups/project-complete" --include-all
```

Normal folder updates retain Robocopy restartable mode (`/Z`) and unbuffered large-file I/O (`/J`) but do not use `/IS` or `/IT`. Identical files are skipped. SHA-256 is calculated only for files copied or resumed during the current call; unchanged files are recorded as metadata skips.

## Batch manifest

Transfer many changed paths in one Neyvia process and produce one combined receipt:

```json
{
  "schema": "neyvia.nas_transfer.manifest.v1",
  "destinationRoot": "releases/fluxio-focused-update",
  "entries": [
    {
      "source": "../src/grant_agent/nas_transfer.py",
      "destination": "src/grant_agent/nas_transfer.py"
    },
    {
      "source": "../tests/test_nas_transfer.py",
      "destination": "tests/test_nas_transfer.py"
    }
  ]
}
```

Relative source paths are resolved from the manifest file. Neyvia validates the NAS root, every source, every destination, and destination overlaps before copying anything.

```powershell
neyvia-transfer batch "C:\path\to\transfer-manifest.json"
```

The combined receipt uses schema `neyvia.nas_transfer.batch.v1` and includes per-entry results plus one SHA-256 manifest covering only transferred files. A manifest can also set `"includeAll": true`, or the caller can pass `--include-all` explicitly.

The native agent tool has the same behavior:

```json
{"tool":"nas.transfer","arguments":{"source":"C:\\path\\to\\data"}}
```

For a manifest:

```json
{"tool":"nas.transfer","arguments":{"manifest":"C:\\path\\to\\transfer-manifest.json"}}
```

Folder updates never mirror-delete the destination. Changed files are updated and unrelated files already on the NAS are preserved.

Robocopy option behavior follows [Microsoft's Robocopy documentation](https://learn.microsoft.com/windows-server/administration/windows-commands/robocopy). Windows mapped-drive validation uses the documented `DRIVE_REMOTE` classification from [GetDriveType](https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-getdrivetypew).

Publication note: local account paths and network identifiers in this document are neutral examples.

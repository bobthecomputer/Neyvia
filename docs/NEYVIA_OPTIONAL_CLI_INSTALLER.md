# Neyvia optional CLI installer

## Outcome

Neyvia stays a thin application. Coding-agent CLIs are detected first and are
installed only when the operator chooses one. A managed install is per-user,
does not edit the operating-system `PATH`, and cannot claim or remove a CLI
installed outside Neyvia.

The current verified managed routes are:

- Claude Code: `@anthropic-ai/claude-code`, command `claude`
- OpenCode: `opencode-ai`, command `opencode`
- Kimi Code: `@moonshot-ai/kimi-code`, command `kimi`

Cursor CLI, OpenClaw, Hermes, and Grok Build remain detectable catalogue
entries. Neyvia does not show a managed Install action for them until a package
identity and launcher have been verified.

## Operator journey

1. Open **Settings → Runtimes & Rooms**.
2. Review the detected and optional tools. No registry request is made merely
   by opening the screen.
3. Choose **Install** or **Update**. Neyvia resolves the selected package only;
   it does not query every optional runtime.
4. Review the publisher version and installed-size metadata.
5. Confirm the action. An action-time approval ID is minted only at this point.
6. Neyvia verifies, stages, probes, and promotes the package. A receipt records
   the outcome.

**Skip** records the preference without downloading anything. Provider sign-in
is a separate final step.

## Safety and durability

- The managed root is `%LOCALAPPDATA%\Neyvia\runtime` on Windows and
  `~/.neyvia/runtime` on POSIX systems. Tests can override it with
  `NEYVIA_MANAGED_RUNTIME_ROOT`.
- `npm` downloads the exact resolved archive into a unique staging directory.
- Neyvia streams the archive through SHA-512 and requires an exact match with
  npm's published integrity value before installation.
- The package launcher must exist and pass `--version` before promotion.
- Manifests move from `promoting` to `active`; launcher and manifest writes are
  atomic.
- If promotion fails, the previous launcher bytes and manifest are restored.
- One previous package is retained for rollback; older Neyvia-owned versions
  are pruned.
- Uninstall removes only the managed launcher, package directory, and manifest.
  It leaves receipts and unrelated installations untouched.
- Every install, update, repair, uninstall, approval-required result, and
  failure writes a receipt.

## Backend surface

- `cli_catalog_command`
- `cli_installer_status_command`
- `cli_prepare_action_command`
- `cli_install_command`
- `cli_update_command`
- `cli_repair_command`
- `cli_uninstall_command`

Mutating commands require both `approved: true` and a backend-minted approval
from `cli_prepare_action_command`. The approval expires after two minutes, is
bound to the runtime/action/version tuple, and is consumed even when validation
fails, so it cannot be replayed. Status, catalogue, and preparation are
non-mutating.

## Verification

The focused Python tests cover checksum rejection, approval gating, atomic
promotion, exact launcher rollback, ownership boundaries, uninstall, and
catalogue action honesty.

`npm run verify:authenticated-settings -- --base-url <local-url>` performs a
real authenticated browser journey at desktop and phone sizes. It verifies the
catalogue, opens and cancels an install confirmation, checks for console/page
errors and unexpected failed requests, and fails on horizontal overflow. It
does not install a package.

## Remaining prerequisite boundary

Managed npm installation requires Node.js/npm. If it is missing, Neyvia reports
`prerequisite_missing`; it does not silently install a system-wide prerequisite.
A future prerequisite installer must use an equally verified, per-user,
rollback-capable route before that behavior can be enabled.

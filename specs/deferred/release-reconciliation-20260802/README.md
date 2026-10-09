# Deferred specifications from the 2026-08-02 source reconciliation

These files are preserved design and acceptance specifications. They are not
part of the executable pytest suite because they do not describe the current
shipped contracts consistently enough to be reliable regression tests.

The originals remain recoverable in the pre-sync backup at:

`Y:\projects\.agent_control\neyvia_sync_backups\20260802T203543Z_c-before-nas-current`

## Files recovered from the active NAS release

- `test_mesh_service.py` targets an older boolean-approval API, the retired
  `mesh_` identifier prefix, and reports device revocation as unimplemented.
  The current service requires durable approval receipts, uses opaque
  `mesh-device-*` identifiers, and implements device revocation.
- `test_module_marketplace.py` includes module manifests that violate the
  current namespace constraints for operation IDs, surface IDs, and routes.
  Its useful operator-browse assertions were replaced by a focused current
  contract test in `tests/test_recovered_release_contracts.py`.
- `test_nearby_send.py` specifies unfinished text/link payloads, favorites,
  retry execution, and a loopback receiver with destination hash ACK. Those
  features are not implemented and are now explicitly reported as deferred.

## Local-only draft specifications preserved during the sync

- `test_phase7_acceptance.py`
- `test_product_completion_milestones.py`
- `test_thunder_compute_simulator.py`

These files import APIs that do not exist in either the recovered release or
the pre-sync local implementation. They remain here as product work items.

Do not move a file back under `tests/` merely to make collection discover it.
First reconcile its assumptions with the current security and namespace
contracts, implement the missing behavior without placeholders, and add a
focused end-to-end proof.

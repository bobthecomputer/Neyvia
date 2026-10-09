"""Adverse durable-effect fixtures for native device command contracts."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path


def _rows(store):
    with closing(sqlite3.connect(store.path)) as db:
        return {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                for table in ("device_command_approvals", "device_commands", "device_capabilities", "paired_devices")}


def _make_store(root):
    from .native_pairing import NativePairingStore
    from .native_device_commands import NativeDeviceCommandStore
    pair = NativePairingStore(root)
    request = pair.create("phone", scopes=["device.commands"])
    device = pair.redeem(request["pairingId"], request["pairingToken"], "C7 adverse fixture")
    store = NativeDeviceCommandStore(root)
    store.publish_capabilities(device["deviceId"], device["deviceSecret"], ["app.open"])
    context = {"actor_id": "agent:c7", "session_id": "session:c7", "run_id": "run:c7"}
    return pair, store, device, context


def _approval(store, device, context):
    return store.request_approval(device["deviceId"], "app.open", arguments={"route": "fixture"}, **context)


def _approved(store, device, context):
    approval = _approval(store, device, context)
    return store.decide_approval(approval["approvalId"], decision="approved", decided_by="human:c7", human_confirmed=True)


def _enqueue(store, device, context, approval, key="c7-key-0001"):
    return store.enqueue(device["deviceId"], "app.open", arguments={"route": "fixture"}, idempotency_key=key,
                         approval_id=approval["approvalId"], **context)


def _refuse(action, expected):
    try:
        action()
    except expected:
        return
    raise AssertionError("adverse native command operation unexpectedly succeeded")


def _crash_inside_transaction(root, device, context, command, contract):
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    code = '''import json,os,sys
from pathlib import Path
from contextlib import contextmanager
from grant_agent.native_device_commands import NativeDeviceCommandStore
data=json.load(sys.stdin);root=Path(sys.argv[1]);s=NativeDeviceCommandStore(root)
original=s.connection
@contextmanager
def interrupted(**kwargs):
 with original(**kwargs) as db:
  yield db
  (root/'interrupted-write.json').write_text(json.dumps({'changes':db.total_changes,'operation':data['contract']}))
  os._exit(47)
s.connection=interrupted
d=data['device'];ctx=data['context'];c=data['command'];name=data['contract'].rsplit('.',1)[-1]
if name=='approval':s.request_approval(d['deviceId'],'app.open',arguments={'route':'fixture'},**ctx)
elif name=='cancel':s.cancel(c['commandId'],cancelled_by='human:c7',human_confirmed=True,**ctx)
elif name=='scope':s.publish_capabilities(d['deviceId'],d['deviceSecret'],[])
elif name=='receipt':s.complete(d['deviceId'],d['deviceSecret'],c['commandId'],c['claimId'],status='succeeded',result={'ok':True})
elif name in {'idempotency','secret-free'}:s.enqueue(d['deviceId'],'app.open',arguments={'route':'fixture'},idempotency_key='interrupted-key-0001',approval_id=data['approval']['approvalId'],**ctx)
else:s.claim(d['deviceId'],d['deviceSecret'])
'''
    from .native_device_commands import NativeDeviceCommandStore
    store = NativeDeviceCommandStore(root)
    approval = _approved(store, device, context) if contract.endswith(('idempotency', 'secret-free')) else None
    if contract.endswith('receipt'):
        command = store.claim(device['deviceId'], device['deviceSecret'])
    before = _rows(store)
    result = subprocess.run([sys.executable, "-c", code, str(root)],
                            input=json.dumps({'device': device, 'context': context, 'command': command,
                                              'contract': contract, 'approval': approval}),
                            text=True, capture_output=True, timeout=40,
                            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])},
                            **hidden_windows_subprocess_kwargs())
    if result.returncode != 47:
        raise AssertionError(f"transaction-kill child exited {result.returncode}: {result.stderr[-1000:]!r}")
    marker = json.loads((root / 'interrupted-write.json').read_text())
    if marker['changes'] < 1 or _rows(store) != before:
        raise AssertionError('Interrupted production transaction failed rollback or made no actual write')


def _exit_after_claim(root, device):
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    code = "import json,os,sys;from pathlib import Path;from grant_agent.native_device_commands import NativeDeviceCommandStore;d=json.load(sys.stdin);s=NativeDeviceCommandStore(Path(sys.argv[1]));c=s.claim(d['id'],d['secret']);assert c;os._exit(48)"
    result = subprocess.run([sys.executable, "-c", code, str(root)], input=json.dumps({"id": device["deviceId"], "secret": device["deviceSecret"]}),
                            capture_output=True, text=True, timeout=40,
                            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
                            **hidden_windows_subprocess_kwargs())
    if result.returncode != 48:
        raise AssertionError(f"post-claim child exit was {result.returncode}: {result.stderr[-1000:]}")


def _permissions(store, device, context, contract):
    from .edge_fixture_native import _sharing_denied
    if os.name != "nt":
        raise RuntimeError("database sharing-denial proof requires Windows")
    approval = _approved(store, device, context)
    command = _enqueue(store, device, context, approval)
    before = _rows(store)
    if contract.endswith(('receipt', 'secret-free')):
        action = lambda: store.get(command['commandId'])
    elif contract.endswith('idempotency'):
        action = lambda: _enqueue(store, device, context, approval)
    else:
        action = lambda: store.claim(device['deviceId'], device['deviceSecret'])
    with _sharing_denied(store.path):
        _refuse(action, (OSError, sqlite3.Error))
    if _rows(store) != before:
        raise AssertionError("OS sharing denial changed durable SQLite state")


def _stale_approval(store, device, context, mode):
    approval = _approved(store, device, context)
    with store.connection(immediate=True) as db:
        if mode == "revoked":
            db.execute("UPDATE device_command_approvals SET status='denied' WHERE approval_id=?", (approval["approvalId"],))
        else:
            db.execute("UPDATE device_command_approvals SET expires_at='2000-01-01T00:00:00Z' WHERE approval_id=?", (approval["approvalId"],))
    _refuse(lambda: _enqueue(store, device, context, approval), (PermissionError,))
    current = store.get_approval(approval["approvalId"])
    wanted = "denied" if mode == "revoked" else "expired"
    if current["status"] != wanted:
        raise AssertionError(f"stale approval state {current['status']} != {wanted}")


def _concurrent(store, device, context, contract):
    detail = {}
    if contract.endswith("approval"):
        approval = _approval(store, device, context)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: store.decide_approval(approval["approvalId"], decision="approved", decided_by="human:c7", human_confirmed=True), range(8)))
        assert {row["status"] for row in results} == {"approved"}
        detail["oneApprovalDecision"] = True
    elif contract.endswith("cancel"):
        command = _enqueue(store, device, context, _approved(store, device, context))
        args = {**context, "cancelled_by": "human:c7", "human_confirmed": True}
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: store.cancel(command["commandId"], **args), range(8)))
        assert {row["status"] for row in results} == {"cancelled"}
        detail["idempotentCancellation"] = True
    elif contract.endswith("idempotency"):
        approval = _approved(store, device, context)
        first = _enqueue(store, device, context, approval)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: _enqueue(store, device, context, approval), range(8)))
        assert {row["commandId"] for row in results} == {first["commandId"]}
        detail["oneDurableCommand"] = True
    elif contract.endswith("receipt"):
        approval = _approved(store, device, context); command = _enqueue(store, device, context, approval)
        claimed = store.claim(device["deviceId"], device["deviceSecret"])
        store.complete(device["deviceId"], device["deviceSecret"], command["commandId"], claimed["claimId"], status="succeeded", result={"ok": True})
        committed_row = next(row for row in _rows(store)["device_commands"] if row[0] == command["commandId"])
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: store.complete(device["deviceId"], device["deviceSecret"], command["commandId"], claimed["claimId"], status="succeeded", result={"ok": True}), range(8)))
        assert {row["status"] for row in results} == {"succeeded"}
        assert next(row for row in _rows(store)["device_commands"] if row[0] == command["commandId"]) == committed_row
        detail["oneTerminalReceipt"] = True
        detail["receiptReplayHadNoCommandEffect"] = True
    elif contract.endswith("final-gate"):
        command = _enqueue(store, device, context, _approved(store, device, context))
        store.publish_capabilities(device["deviceId"], device["deviceSecret"], [])
        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(pool.map(lambda _: store.claim(device["deviceId"], device["deviceSecret"]), range(8)))
        assert claims == [None] * 8
        assert store.get(command["commandId"])["status"] == "rejected"
        detail["concurrentRevokedClaimsRefused"] = len(claims)
    elif contract.endswith("uncertainty"):
        command = _enqueue(store, device, context, _approved(store, device, context))
        claimed = store.claim(device["deviceId"], device["deviceSecret"])
        with store.connection(immediate=True) as db:
            db.execute("UPDATE device_commands SET claim_expires_at='2000-01-01T00:00:00Z' WHERE command_id=?", (command["commandId"],))
        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(pool.map(lambda _: store.claim(device["deviceId"], device["deviceSecret"]), range(8)))
        assert claims == [None] * 8
        assert store.get(command["commandId"])["status"] == "uncertain" and claimed["claimId"]
        detail["expiredLeaseNotReplayed"] = True
    elif contract.endswith("deadline"):
        command = _enqueue(store, device, context, _approved(store, device, context))
        with store.connection(immediate=True) as db:
            db.execute("UPDATE device_commands SET expires_at='2000-01-01T00:00:00Z' WHERE command_id=?", (command["commandId"],))
        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(pool.map(lambda _: store.claim(device["deviceId"], device["deviceSecret"]), range(8)))
        assert claims == [None] * 8
        assert store.get(command["commandId"])["status"] == "expired"
        detail["expiredCommandNeverClaimed"] = True
    elif contract.endswith("scope"):
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows = list(pool.map(lambda _: store.publish_capabilities(device["deviceId"], device["deviceSecret"], ["app.open"]), range(8)))
        assert all(row["capabilities"] == ["app.open"] for row in rows)
        with store.connection(immediate=True) as db:
            db.execute("UPDATE paired_devices SET scopes_json='[]' WHERE device_id=?", (device['deviceId'],))
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: _refuse(lambda: store.publish_capabilities(device['deviceId'], device['deviceSecret'], ['app.open']), (PermissionError,)), range(8)))
        detail["scopedCapabilityPublicationSerialized"] = True
        detail['unscopedConcurrentPublicationRefused'] = 8
    elif contract.endswith("secret-free"):
        approval = _approved(store, device, context); _enqueue(store, device, context, approval)
        with ThreadPoolExecutor(max_workers=8) as pool:
            receipts = list(pool.map(lambda _: store.list(device_id=device["deviceId"]), range(8)))
        encoded = json.dumps(receipts).lower()
        assert device["deviceSecret"].lower() not in encoded and all(len(row) == 1 for row in receipts)
        detail["concurrentPublicReceiptsSecretFree"] = True
    else:
        raise ValueError(f"No concurrency invariant for {contract}")
    return detail


def run(root: Path, contract: str, category: str) -> dict:
    from .native_device_commands import NativeDeviceCommandStore
    from .native_pairing import NativePairingStore
    root = Path(root).resolve()
    pair, store, device, context = _make_store(root)
    before = _rows(store)
    detail = {}

    if category == "concurrency":
        detail = _concurrent(store, device, context, contract)
    elif category == "interrupted":
        approval = _approved(store, device, context); command = _enqueue(store, device, context, approval)
        if contract.endswith("uncertainty"):
            _exit_after_claim(root, device)
            with store.connection(immediate=True) as db:
                db.execute("UPDATE device_commands SET claim_expires_at='2000-01-01T00:00:00Z' WHERE command_id=?", (command["commandId"],))
            assert store.claim(device["deviceId"], device["deviceSecret"]) is None
            assert store.get(command["commandId"])["status"] == "uncertain"
            detail["childExitCode"] = 48; detail["committedClaimBecameUncertain"] = True
        else:
            _crash_inside_transaction(root, device, context, command, contract)
            detail["childExitCode"] = 47; detail["transactionRolledBack"] = True
    elif category == "permissions":
        _permissions(store, device, context, contract)
        detail["osDatabaseSharingDenied"] = True
    elif category == "stale":
        if contract.endswith("approval"):
            _stale_approval(store, device, context, "revoked")
            _stale_approval(store, device, context, "expired")
            detail["revokedApprovalRefused"] = True; detail["expiredApprovalRefused"] = True
        elif contract.endswith("idempotency"):
            approval = _approved(store, device, context); _enqueue(store, device, context, approval)
            other = _approved(store, device, context)
            _refuse(lambda: _enqueue(store, device, context, other), (ValueError,))
            assert len(_rows(store)["device_commands"]) == 1
            detail["conflictingIdempotencyRefused"] = True
        elif contract.endswith("receipt"):
            approval = _approved(store, device, context); command = _enqueue(store, device, context, approval)
            claim = store.claim(device["deviceId"], device["deviceSecret"])
            _refuse(lambda: store.complete(device["deviceId"], device["deviceSecret"], command["commandId"], "stale-claim", status="succeeded", result={"ok": True}), (ValueError, PermissionError))
            assert store.get(command["commandId"])["status"] == "claimed" and claim["claimId"] != "stale-claim"
            detail["staleReceiptRefused"] = True
        elif contract.endswith("scope"):
            with store.connection(immediate=True) as db:
                db.execute("UPDATE paired_devices SET scopes_json='[]' WHERE device_id=?", (device["deviceId"],))
            _refuse(lambda: store.publish_capabilities(device["deviceId"], device["deviceSecret"], ["app.open"]), (PermissionError,))
            detail["missingCommandScopeDenied"] = True
        elif contract.endswith("cancel"):
            command = _enqueue(store, device, context, _approved(store, device, context))
            store.claim(device["deviceId"], device["deviceSecret"])
            _refuse(lambda: store.cancel(command["commandId"], **{**context, "cancelled_by": "human:c7", "human_confirmed": True}), (ValueError,))
            assert store.get(command["commandId"])["status"] == "claimed"
            detail["claimedCommandCannotBeCancelled"] = True
        elif contract.endswith("secret-free"):
            approval = _approved(store, device, context)
            _refuse(lambda: store.enqueue(device["deviceId"], "app.open", arguments={"access_token": "fixture-secret"}, idempotency_key="secret-key-0001", approval_id=approval["approvalId"], **context), (ValueError,))
            assert not _rows(store)["device_commands"]
            detail["secretArgumentRejectedBeforePersistence"] = True
        elif contract.endswith("single-flight"):
            command = _enqueue(store, device, context, _approved(store, device, context))
            first = store.claim(device["deviceId"], device["deviceSecret"])
            assert first and store.claim(device["deviceId"], device["deviceSecret"]) is None
            assert store.get(command["commandId"])["claimId"] == first["claimId"]
            detail["activeLeaseIsSingleFlight"] = True
        else:
            _stale_approval(store, device, context, "expired")
            detail["expiredApprovalRefused"] = True
    else:
        raise ValueError(f"Unsupported adverse category: {category}")

    after = _rows(store)
    if not after["paired_devices"] or not after["device_capabilities"]:
        raise AssertionError("independent durable readback returned no pairing/capability state")
    public = [store.get(row[0]) for row in after["device_commands"]]
    encoded = json.dumps(public, sort_keys=True).lower()
    if any(secret.lower() in encoded for secret in (device["deviceSecret"],)):
        raise AssertionError("public command receipt disclosed device secret")
    detail.update(actualStoreEffects=True, independentReadback=True, secretFreePublicReceipts=True,
                  durableApprovalRows=len(after["device_command_approvals"]), durableCommandRows=len(after["device_commands"]))
    return {"actualStoreEffects": True, "contract": contract, "category": category, **detail,
            "physicalDeviceExecutionProven": False}

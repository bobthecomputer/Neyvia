"""Recover scoped workspace deletion after a lost multi-file acknowledgement."""
from functools import wraps
import json
import hashlib

from .durability import atomic_write_json, file_transaction

SCHEMA = 'neyvia.workspace-deletion.v1'


def journal_path(store):
    return store.control_dir / 'workspace_deletion.json'


def begin(store, workspace_id, removed_missions):
    # Admit only readable state. A denied store must not leave a durable intent
    # which could unexpectedly start deleting when permissions later recover.
    paths = (store.workspaces_path, store.missions_path, store.workspace_actions_path)
    before = {path.name: hashlib.sha256(path.read_bytes() if path.exists() else b'').hexdigest()
              for path in paths}
    atomic_write_json(journal_path(store), {'schema': SCHEMA, 'status': 'pending',
        'workspaceId': workspace_id, 'removedMissions': removed_missions, 'beforeHashes': before})


def complete(store):
    path = journal_path(store)
    value = json.loads(path.read_text(encoding='utf8'))
    atomic_write_json(path, {**value, 'status': 'completed'})


def recover(store):
    """Finish only an already admitted deletion, filtering current local state."""
    path = journal_path(store)
    if not path.exists():
        return
    value = json.loads(path.read_text(encoding='utf8'))
    if value.get('schema') != SCHEMA or value.get('status') not in {'pending', 'completed'}:
        raise ValueError('Invalid workspace deletion journal')
    if value['status'] == 'completed':
        return
    workspace_id = value.get('workspaceId')
    if not isinstance(workspace_id, str) or not workspace_id:
        raise ValueError('Workspace deletion journal lacks its exact target')
    store._workspace_delete_in_progress = True
    try:
        remaining = [row for row in store.load_workspaces() if row.workspace_id != workspace_id]
        if not remaining:
            raise ValueError('Workspace deletion recovery would remove the last workspace')
        missions = [row for row in store.load_missions(include_legacy_blocked=True)
                    if row.workspace_id != workspace_id]
        store._rebalance_workspace_queue_in_place(missions)
        store.save_missions(missions)
        histories = store.load_workspace_actions()
        histories.pop(workspace_id, None)
        store._write_json_if_changed(store.workspace_actions_path, histories)
        store.save_workspaces(remaining)
        complete(store)
    finally:
        store._workspace_delete_in_progress = False


def workspace_state(action):
    """Keep deletion, its checked readback and recovery in the existing lock."""
    @wraps(action)
    def invoke(store, *args, **kwargs):
        with file_transaction(journal_path(store)):
            if not getattr(store, '_workspace_delete_in_progress', False):
                recover(store)
            previous = getattr(store, '_workspace_delete_in_progress', False)
            if action.__name__ == 'delete_workspace':
                store._workspace_delete_in_progress = True
            try:
                return action(store, *args, **kwargs)
            finally:
                store._workspace_delete_in_progress = previous
    return invoke

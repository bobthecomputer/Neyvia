"""Semantic CL projections over owner state, without changing archival payloads.

Every E cell is a scalar or a host reference. Containers are explicit typed
relations, including empty ones. Entity refs identify subjects; root refs retain
the complete immutable observation for bounded ``project`` calls.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re

from .renderer import IDENTIFIERS


@dataclass(frozen=True)
class LayerCodec:
    subject: str
    relations: dict[str, str]
    priority: tuple[str, ...] = ()


def _codec(subject, relations, priority=()):
    return LayerCodec(subject, dict(pair.split(':', 1) for pair in relations.split()), tuple(priority))


# These names describe the returned owners' objects, not transport envelopes.
# Unknown fields remain visible as scalar attributes; unknown families are
# explicitly marked generic rather than silently claiming an authored codec.
CODECS = {
    'files': _codec('folder', 'entries:file places:place crumbs:ancestor entry:file action:file-operation', ('path', 'name', 'kind', 'size', 'truncated', 'entries')),
    'folder': _codec('folder', 'entries:file places:place'),
    'workspace': _codec('source', 'matches:match results:match edits:edit', ('path', 'content', 'truncated', 'nextOffset', 'bytes')),
    'terminal': _codec('terminal-command', 'execution:terminal-command sessions:terminal-session events:event', ('shell', 'cwd', 'command', 'exitCode', 'stdout', 'stderr', 'timedOut', 'outputTruncated')),
    'notes': _codec('note', 'notes:note tags:tag', ('path', 'title', 'body', 'pinned', 'tags', 'changed', 'size')),
    'settings': _codec('configuration', 'settings:setting network:network-policy setup:setup cleanup:cleanup-policy nightShift:nightshift-policy children:child-process checks:network-check', ('settings', 'density', 'theme', 'initiative', 'localOnly', 'network', 'setup')),
    'onboarding': _codec('onboarding', 'steps:setup-step packs:pack requirements:requirement'),
    'pdf': _codec('pdf', 'state:document requested:request pages:page matches:match highlights:highlight annotations:annotation renderer:renderer-state event:event', ('state', 'path', 'page', 'pages', 'text', 'requested')),
    'image': _codec('image', 'state:asset requested:request asset:asset assets:asset generation:generation publication:publication region:crop event:event', ('state', 'asset', 'path', 'width', 'height', 'generation')),
    'mobile': _codec('mobile-studio', 'devices:device projects:project packages:package builds:build preview:preview sdk:toolchain emulators:emulator receipts:build-receipt safe:insets', ('project', 'preview', 'packages', 'builds', 'sdk', 'devices')),
    'agents': _codec('agent-state', 'sources:source providers:provider sessions:session running:job tasks:task agents:agent limits:limit subagents:agent checklist:task', ('observedAt', 'sources', 'running', 'sessions', 'agents', 'providers')),
    'conductor': _codec('conductor', 'jobs:job tasks:task agents:agent groups:group runs:run'),
    'session': _codec('session', 'sessions:session messages:message events:event tasks:task'),
    'schedule': _codec('schedule', 'schedules:schedule jobs:job runs:run'),
    'watch': _codec('watch-state', 'watches:watch states:watched-state', ('watches', 'id', 'runId', 'states', 'message', 'status')),
    'nightshift': _codec('nightshift', 'jobs:job tasks:task runs:run resources:resource providers:provider'),
    'manual': _codec('manual', 'manuals:manual chapters:chapter actions:action procedures:procedure checks:check frontier:frontier patches:patch lineage:manual-version scripts:script sourceRuns:source-run feedback:feedback observed:observation diff:change', ('id', 'chapter', 'state', 'mode', 'observed', 'actions', 'procedures', 'patches', 'scripts')),
    'perception': _codec('observation', 'observed:observation source:source state:perceived-object elements:control windows:window entries:file pages:page rows:table-row diff:change', ('layer', 'observer', 'mode', 'observed', 'value', 'truncated')),
    'app_sdk': _codec('app', 'apps:app state:app-state shared:shared-state goals:goal receipts:receipt reducer:reducer'),
    'state': _codec('workspace', 'projects:project sessions:session running:job apps:app'),
    'app': _codec('app', 'apps:app event:event state:app-state'),
    'artifact': _codec('artifact-store', 'artifacts:artifact publication:publication'),
    'runtime': _codec('runtime', 'providers:provider models:model sessions:session capabilities:capability jobs:job'),
    'devices': _codec('device-state', 'devices:device peers:peer transfers:transfer grants:grant sessions:session'),
    'remote': _codec('remote-state', 'sessions:session connections:connection windows:window grants:grant'),
    'gamedev': _codec('game-studio', 'engines:engine sessions:editor-session bridge:bridge receipts:build-receipt'),
    'scroll': _codec('study', 'packs:pack cards:card questions:question results:result active:study-session graph:prerequisite review:review sources:source jobs:job validation:validation archive:archive project:project pack:pack', ('pack', 'packs', 'active', 'cards', 'review')),
    'video': _codec('video', 'frames:frame tracks:track clips:clip streams:stream segments:segment'),
    'web': _codec('document', 'documents:document passages:passage citations:citation results:source'),
    'browser': _codec('browser', 'tabs:tab profiles:profile spaces:space grants:grant downloads:download history:visit elements:control runtime:runtime headless:runtime'),
    'cua': _codec('desktop', 'windows:window elements:control sessions:session driver:driver'),
    'pane': _codec('pane', 'panes:pane event:event payload:pane-request acknowledgement:renderer-ack'),
    'view': _codec('view', 'panes:pane layout:layout event:event'),
    'voice': _codec('voice', 'apps:app commands:command routes:route event:event'),
    'dictation': _codec('dictation', 'sessions:dictation-session segments:segment corrections:correction'),
    'tools': _codec('catalog', 'tools:tool families:family gateways:gateway'),
    'native': _codec('catalog', 'tools:tool families:family gateways:gateway'),
    'memory': _codec('memory', 'memories:memory entries:memory facts:fact sources:source'),
    'semantic': _codec('semantic-state', 'objects:object relations:relation facts:fact recovery:recovery proof:proof changeSet:change-set mission:mission application:application policy:policy decision:decision artifacts:artifact verification:verification', ('recoveryId', 'proofId', 'changeId', 'missionId', 'applicationId', 'policyId', 'artifactPath', 'artifacts')),
    'efficiency': _codec('cascade', 'providers:provider stages:stage measurements:measurement'),
    'evolver': _codec('lab', 'experiments:experiment candidates:candidate scores:score runs:run'),
    'workflow': _codec('workflow', 'stages:stage tasks:task evidence:evidence results:result'),
    'time': _codec('clock', '', ('utc', 'unixSeconds', 'timezone', 'local')),
    'timer': _codec('timer-state', 'timers:timer'),
    'attention': _codec('attention-experiment', 'attentionResult:attention-experiment acceptance:criterion requestedRoute:route actualRoute:reported-route budget:experiment-budget observations:reported-observation items:attention-item tasks:task queue:attention-item'),
    'autopilot': _codec('autopilot', 'tasks:task runs:run plans:plan'),
    'cl': _codec('language', 'layers:layer actions:action procedures:procedure'),
    'claude': _codec('provider', 'sessions:session tasks:task capabilities:capability'),
    'codex': _codec('provider', 'sessions:session tasks:task capabilities:capability'),
    'context': _codec('context', 'items:context-item sources:source memory:memory'),
    'host': _codec('host', 'processes:process capabilities:capability runtimes:runtime tools:tool'),
    'impact': _codec('impact', 'files:source dependencies:dependency dependents:dependency owners:owner'),
    'intelligence': _codec('intelligence', 'units:unit judgments:judgment sources:source'),
    'intent': _codec('intent', 'goals:goal constraints:constraint tasks:task'),
    'lab': _codec('lab', 'experiments:experiment candidates:candidate scores:score runs:run'),
    'laya': _codec('adviser', 'advice:advice observations:observation receipts:receipt'),
    'mission': _codec('mission', 'tasks:task phases:phase receipts:receipt artifacts:artifact'),
    'plan': _codec('plan', 'tasks:task steps:step dependencies:dependency'),
    'preview': _codec('preview', 'frames:frame artifacts:artifact session:session events:event'),
    'project': _codec('project', 'projects:project files:source tasks:task'),
    'research': _codec('research', 'sources:source passages:passage citations:citation claims:claim evidence:evidence'),
    'sidebar': _codec('sidebar', 'items:sidebar-item projects:project sessions:session groups:subject-group candidates:session protected:session moved:session restored:session conflicts:conflict policy:cleanup-policy', ('sessions', 'groups', 'policy', 'moved', 'restored', 'conflicts')),
    'situation': _codec('task-contract', 'contract:task-contract constraints:constraint acceptance:criterion journeys:journey journeyRuns:journey-run facts:fact observations:observation tasks:task'),
    'skill': _codec('skill', 'skills:skill rules:rule checks:check results:check-result'),
    'verify': _codec('verification', 'checks:check receipts:receipt cases:case results:check-result'),
    'work': _codec('work', 'state:adaptive-work focus:focus focusHistory:focus-change problems:problem constraints:constraint dependencies:dependency evidence:evidence nextAction:proposed-action artifacts:artifact claims:claim tasks:task resources:resource owners:owner', ('workId', 'revision', 'focus', 'problems', 'constraints', 'nextAction')),
    'projection': _codec('projection', ''),
    'behavior': _codec('behavior-contract', 'criteria:criterion observation:reported-observation observations:reported-observation artifacts:artifact'),
    'environment': _codec('environment', 'dependencies:dependency processes:process executions:execution artifacts:artifact'),
    'experience': _codec('experience-record', 'episodes:episode investigations:investigation comparisons:comparison traces:trace artifacts:artifact hypotheses:hypothesis'),
    'experiment': _codec('experiment', 'files:source artifacts:artifact snapshots:snapshot results:measurement'),
    'orchestration': _codec('task-graph', 'tasks:task steps:step dependencies:dependency stages:stage artifacts:artifact'),
    'quality': _codec('quality-record', 'criteria:criterion measurements:measurement comparisons:comparison challenges:challenge holdout:held-out-case artifacts:artifact'),
    'taste': _codec('provisional-correction', 'corrections:correction artifacts:artifact evidence:reported-evidence'),
    'nas': _codec('remote-storage', 'files:remote-file messages:message transfers:transfer receipts:receipt'),
    'ui': _codec('interface-reference', 'references:reference images:image results:reference'),
    'execution': _codec('execution-plan', 'steps:step dependencies:dependency artifacts:artifact receipts:receipt'),
    'notify': _codec('notification', 'event:event'),
}

# Singular return objects are relations too; they must not degrade to opaque
# transport cells simply because an observer returns one entity instead of a list.
for _family, _relations in {
    'devices': 'transfer:transfer places:shared-folder entries:file plan:transfer-file',
    'remote': 'elements:remote-control capture:remote-capture',
    'session': 'run:provider-run event:event',
    'claude': 'runs:reported-run checklist:task files:reported-file',
    'codex': 'importedSkills:imported-skill linkedPluginSkills:plugin-skill activationPolicy:import-policy',
    'onboarding': 'state:setup-state status:download-state catalog:onboarding-catalog recommended:recommendation',
    'dictation': 'names:spoken-name actions:editor-action command:spoken-command',
    'efficiency': 'answer:exact-answer trace:cascade-stage validation:validation samples:latency-sample rows:learned-transition',
}.items():
    _original = CODECS[_family]
    CODECS[_family] = LayerCodec(_original.subject, {
        **_original.relations, **dict(pair.split(':', 1) for pair in _relations.split())
    }, _original.priority)

_IDENTITY = ('path', 'id', 'handle', 'sessionId', 'runId', 'window_id', 'windowId',
             'element_token', 'browserId', 'requestId', 'key', 'name', 'engine', 'url')
_PRIVATE = IDENTIFIERS | {'session', 'profileId', 'spaceId', 'activeTabId', 'peekTabId', 'requestId', 'receipt_id'}
_UNSAFE_LINES = {'\u0085': '\\u0085', '\u2028': '\\u2028', '\u2029': '\\u2029'}
_KEYED_RELATIONS = {'session', 'job', 'app', 'asset', 'provider', 'manual', 'generation',
                    'project', 'experiment', 'grant', 'pack', 'device', 'agent', 'task'}


def scalar(value):
    """Quoted untrusted strings cannot introduce CL rows or instructions."""
    if isinstance(value, (dict, list, tuple)):
        raise TypeError('A semantic cell must be scalar')
    if isinstance(value, float) and not math.isfinite(value):
        return '"unknown-nonfinite"'
    text = json.dumps(value, ensure_ascii=False, allow_nan=False)
    for character, replacement in _UNSAFE_LINES.items():
        text = text.replace(character, replacement)
    return text


class SemanticCodecs:
    """One codec context per HostContext; refs are created by the host only."""
    def __init__(self, host, *, budget=4000, row_limit=120, depth_limit=10):
        self.host = host
        self.budget, self.row_limit, self.depth_limit = budget, row_limit, depth_limit
        self.identities = {}

    def _ref(self, layer, kind, value, path):
        if isinstance(value, dict):
            key = next((name for name in _IDENTITY if name in value and isinstance(value[name], (str, int))), None)
            if key == 'element_token':
                return self.host._put(value, 'e', layer, value[key])
            if kind == 'window':
                # Host argument filling needs the complete immutable window row.
                return self.host._put(value, 'w', layer)
            identity = value[key] if key else None
        else:
            identity = None
        if identity is None:
            return self.host._put(value, 'h', layer)
        return self._subject_ref(layer, kind, identity)

    def _subject_ref(self, layer, kind, identity):
        binding = (layer, kind, type(identity).__name__, str(identity))
        if binding not in self.identities:
            self.identities[binding] = self.host._put(identity, 'o', layer)
        return self.identities[binding]

    def _cell(self, layer, field, value):
        if field in _PRIVATE and value is not None:
            binding = (layer, 'identifier', field, type(value).__name__, str(value))
            if binding not in self.identities:
                self.identities[binding] = self.host._put(value, 'i', layer)
            return self.identities[binding]
        return scalar(value)

    def _rows(self, layer, codec, value, kind, ref, parent='-', field='', path='', depth=0):
        if isinstance(value, dict):
            if kind in _KEYED_RELATIONS and value and all(isinstance(child, dict) for child in value.values()):
                yield ('collection', ref, parent, field, str(len(value)))
                if depth >= self.depth_limit:
                    yield ('projection', ref, parent, path, scalar('depth-bound; use project'))
                    return
                for key, child in value.items():
                    child_path = path + '.' + key if path else key
                    child_ref = self._ref(layer, kind, child, child_path)
                    yield from self._rows(layer, codec, child, kind, child_ref, ref, key, child_path, depth + 1)
                return
            yield (kind, ref, parent, field, scalar('object'))
            if depth >= self.depth_limit:
                yield ('projection', ref, parent, path, scalar('depth-bound; use project'))
                return
            order = {name: index for index, name in enumerate(codec.priority)}
            elements = value.get('elements')
            native_tree = 'tree_markdown' in value or isinstance(elements, list) and any(isinstance(row, dict) and 'element_token' in row for row in elements)
            for key in sorted(value, key=lambda name: (order.get(name, len(order)), name)):
                child = value[key]
                if native_tree and key in {'text', 'tree_markdown'} and isinstance(child, str):
                    child = re.sub(r'("(?:[^"\\]|\\.)*")|(\s+id=\d+\b)', lambda match: match.group(1) or '', child)
                child_kind = codec.relations.get(key, kind + '-attribute')
                child_path = path + '.' + key if path else key
                if isinstance(child, (dict, list, tuple)):
                    child_ref = self._ref(layer, child_kind, child, child_path)
                    yield from self._rows(layer, codec, child, child_kind, child_ref, ref, key, child_path, depth + 1)
                else:
                    yield (kind, ref, parent, key, self._cell(layer, key, child))
        elif isinstance(value, (list, tuple)):
            yield ('collection', ref, parent, field, str(len(value)))
            if depth >= self.depth_limit:
                yield ('projection', ref, parent, path, scalar('depth-bound; use project'))
                return
            for index, child in enumerate(value):
                child_path = path + '.' + str(index) if path else str(index)
                if isinstance(child, (dict, list, tuple)):
                    child_ref = self._ref(layer, kind, child, child_path)
                    yield from self._rows(layer, codec, child, kind, child_ref, ref, str(index), child_path, depth + 1)
                else:
                    yield (kind, ref, parent, str(index), self._cell(layer, field, child))
        else:
            yield (kind, ref, parent, field or 'value', self._cell(layer, field, value))

    def render(self, layer, value):
        if not re.fullmatch(r'[A-Za-z_][\w-]*', layer):
            raise ValueError('Invalid semantic layer')
        codec = CODECS.get(layer, LayerCodec('object', {}))
        root = self.host._put(value, 'h', layer)
        header = 'S ' + layer + ' ' + root + ' #' + str(self.host.generations.get(layer, 0)) + ' [type ref parent field value]\n'
        lines, size = [header], len(header)
        reserve = 180
        entity = self._ref(layer, codec.subject, value, '') if isinstance(value, dict) and any(key in value for key in _IDENTITY) else root
        for index, (kind, ref, parent, field, cell) in enumerate(self._rows(layer, codec, value, codec.subject, entity, root if entity != root else '-')):
            row = 'E ' + kind + ' ' + ref + ' ' + parent + ' ' + scalar(field) + ' ' + cell + '\n'
            if index >= self.row_limit or size + len(row) > self.budget - reserve:
                lines.append('Q projection bounded ref=' + root + ' use=project rows=' + str(index) + '\n')
                self.host.metrics['Q'] += 1
                break
            lines.append(row)
            size += len(row)
        if layer not in CODECS:
            lines.append('Q codec generic layer=' + layer + ' ref=' + root + '\n')
            self.host.metrics['Q'] += 1
        return ''.join(lines)

    def _objects(self, layer, codec, value, *, limit=500):
        """Key list entities by owner identity so reorder is not a false delta."""
        objects = {}
        remaining = [limit]
        def visit(item, kind, path, subject=None, depth=0):
            if remaining[0] <= 0 or depth > self.depth_limit:
                return False
            remaining[0] -= 1
            if isinstance(item, dict):
                key = next((name for name in _IDENTITY if name in item and isinstance(item[name], (str, int))), None)
                identity = scalar(item[key]) if key else scalar(subject or path)
                token = (kind, identity)
                fields = objects.setdefault(token, {})
                owner_path = kind + ':' + identity
                for field, child in item.items():
                    if isinstance(child, (dict, list, tuple)):
                        if not visit(child, codec.relations.get(field, kind + '-attribute'), owner_path + '.' + field, depth=depth + 1):
                            return False
                    else:
                        fields[field] = child
                return True
            if isinstance(item, (list, tuple)):
                # Empty/nonempty collection changes are effects too.
                objects[(kind + '-collection', scalar(path))] = {'count': len(item)}
                return all(visit(child, kind, path + '.' + str(i), depth=depth + 1) for i, child in enumerate(item))
            objects[(kind, scalar(subject or path))] = {'value': item}
            return True
        complete = visit(value, codec.subject, '$')
        return objects, complete

    def delta(self, layer, before, after):
        codec = CODECS.get(layer, LayerCodec('object', {}))
        old, old_complete = self._objects(layer, codec, before)
        new, new_complete = self._objects(layer, codec, after)
        lines, size = [], 0
        for token in sorted(old.keys() | new.keys()):
            kind, identity = token
            left, right = old.get(token, {}), new.get(token, {})
            operation = 'added' if token not in old else 'removed' if token not in new else 'changed'
            for field in sorted(left.keys() | right.keys()):
                if field in left and field in right and left[field] == right[field]:
                    continue
                subject = self._subject_ref(layer, kind, json.loads(identity))
                row = 'D ' + layer + ' ' + operation + ' ' + kind + ' ' + subject + ' ' + scalar(field)
                row += ' ' + (self._cell(layer, field, left[field]) if field in left else 'absent')
                row += ' ' + (self._cell(layer, field, right[field]) if field in right else 'absent') + '\n'
                if size + len(row) > self.budget - 180 or len(lines) >= self.row_limit:
                    old_complete = False
                    break
                lines.append(row)
                size += len(row)
            if not old_complete:
                break
        if not old_complete or not new_complete:
            ref = self.host._put({'before': before, 'after': after}, 'h', layer)
            lines.append('Q delta bounded ref=' + ref + ' use=project\n')
            self.host.metrics['Q'] += 1
        return ''.join(lines) or 'D ' + layer + ' unchanged\n'

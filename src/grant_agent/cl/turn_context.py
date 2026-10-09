"""Deterministic, measured context for a CL proposal loop.

The prefix and task never change. Old messages are durable, integrity-checked
records available through context.read rather than silently discarded data.
Host snapshots retain current state/project handles and every actionable ref.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import threading

from ..durability import atomic_write_json
from .tokens import count_tokens


class ContextBudgetError(ValueError):
    """The immutable task or current live bindings cannot fit the chosen budget."""


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class TurnContext:
    """Bound a real host/model loop without a summarizing model or truncation.

    Example::

        context = TurnContext(task, prefix, archive_dir=run / 'history')
        prompt = context.prompt(host=host, guidance=host.help('notes'))
        proposal = model.propose(prompt)
        host.acknowledge_observations()
        context.append('proposal', proposal)
        outcome = host.execute(proposal)
        context.append('result', outcome['text'], metadata={'ok': outcome['ok']})

    The runner exposes read(handle,start,count) as context.read(...) and records
    its response like any other result. Provider usage remains authoritative;
    metrics count exact o200k text, excluding provider envelopes/hidden context.
    """

    def __init__(self, task, prefix, *, token_budget=8000, archive_dir,
                 recent_results=3, max_prefix_tokens=800):
        if not isinstance(task, str) or not task.strip(): raise ValueError('Task must be nonempty text')
        if not isinstance(prefix, str): raise ValueError('Prefix must be text')
        if type(token_budget) is not int or token_budget < 1: raise ValueError('Positive token_budget required')
        if type(recent_results) is not int or recent_results < 1: raise ValueError('Positive recent_results required')
        if count_tokens(prefix) > max_prefix_tokens: raise ContextBudgetError('Stable prefix exceeds short-prefix limit')
        self._task, self._prefix = task, prefix
        self.token_budget, self.recent_results = token_budget, recent_results
        self.archive_dir = Path(archive_dir).resolve()
        self.lock = threading.RLock()
        self.records = []
        self.last_error = None
        self.acknowledgeable_state_refs = []
        self.metrics = {'turns': 0, 'compactions': 0, 'lastTokens': 0, 'maxTokens': 0,
                        'totalTokens': 0, 'archivedRecords': 0, 'tokenizer': 'o200k_base',
                        'scope': 'exact prompt text; excludes provider envelopes and hidden context'}
        if count_tokens(self._render({}, [], '')) > token_budget:
            raise ContextBudgetError('Immutable task and short prefix exceed per-turn context budget; task was not truncated')
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        task_path = self.archive_dir / 'task.json'
        identity = {'task': task, 'prefix': prefix}
        if task_path.exists():
            if json.loads(task_path.read_text(encoding='utf-8')) != identity:
                raise ValueError('Archive belongs to another immutable task or prefix')
        else: atomic_write_json(task_path, identity)
        index = self.archive_dir / 'index.json'
        if index.exists():
            self.records = json.loads(index.read_text(encoding='utf-8'))['records']
            for row in self.records:
                self._load(row['handle'])
                if row.get('error'): self.last_error = row['handle']
        self.metrics['archivedRecords'] = len(self.records)

    @property
    def task(self): return self._task

    @property
    def prefix(self): return self._prefix

    def append(self, role, content, metadata=None):
        """Write the full message before returning its immutable history handle."""
        if not isinstance(role, str) or not role: raise ValueError('History role required')
        text = content if isinstance(content, str) else _encoded(content)
        with self.lock:
            record = {'sequence': len(self.records) + 1, 'role': role, 'content': text,
                      'metadata': deepcopy(metadata or {})}
            if role == 'result':
                record['metadata']['verifiedProcedures'] = re.findall(r'^R ([\w.-]+) ok \+G$', text, re.M)
            digest = hashlib.sha256(_encoded(record).encode('utf-8')).hexdigest()
            handle = 't' + str(record['sequence']) + '-' + digest[:16]
            atomic_write_json(self.archive_dir / (handle + '.json'), {'sha256': digest, 'record': record})
            error = record['metadata'].get('ok') is False or role == 'error'
            self.records.append({'handle': handle, 'role': role, 'error': error})
            atomic_write_json(self.archive_dir / 'index.json', {'records': self.records})
            if error: self.last_error = handle
            self.metrics['archivedRecords'] = len(self.records)
            return handle

    def _load(self, handle):
        if not isinstance(handle, str) or not re.fullmatch(r't[1-9][0-9]*-[a-f0-9]{16}', handle):
            raise ValueError('Invalid history handle')
        row = json.loads((self.archive_dir / (handle + '.json')).read_text(encoding='utf-8'))
        digest = hashlib.sha256(_encoded(row['record']).encode('utf-8')).hexdigest()
        if row.get('sha256') != digest or not handle.endswith('-' + digest[:16]):
            raise ValueError('History record integrity check failed')
        return row['record']

    def read(self, handle, start=0, count=4000, view='raw'):
        """Read a page of full archival message text, with exact offsets.

        count bounds characters, not tokens; context budgets remain enforced
        when this response is added to the next model prompt.
        """
        if type(start) is not int or start < 0: raise ValueError('start must be a nonnegative integer')
        if type(count) is not int or not 1 <= count <= 16000: raise ValueError('count must be 1..16000')
        record = {'role': 'index', 'content': _encoded(self.records)} if handle == 'index' else self._load(handle)
        text = record['content']
        if view not in {'raw', 'source'}: raise ValueError('view must be raw or source')
        if view == 'source': text = self._display(text)
        end = min(len(text), start + count)
        if view == 'source':
            return ('HISTORY PAGE ' + _encoded({'handle':handle, 'role':record['role'], 'start':start,
                    'totalCharacters':len(text), 'nextStart':end if end < len(text) else None,
                    'view':'source', 'continue':'context.read(handle,start=nextStart,count=4000,view="source")'}) +
                    '\n' + text[start:end])
        return _encoded({'handle': handle, 'role': record['role'], 'start': start,
                         'totalCharacters': len(text), 'nextStart': end if end < len(text) else None,
                         'text': text[start:end]})

    def _recent(self):
        selected, remaining = [], self.recent_results
        for row in reversed(self.records):
            if row['role'] == 'manual': continue
            selected.append(row)
            if row['role'] in {'result', 'user', 'error'}:
                remaining -= 1
                if remaining == 0: break
        selected.reverse()
        return [{**row, 'content': self._display(self._load(row['handle'])['content'])} for row in selected]

    @staticmethod
    def _display(text):
        """Lossless source presentation, avoiding JSON escaping of every newline.

        The archive and state values remain byte-for-byte unchanged. Only full
        E dictionaries with a string content field are presented as metadata
        plus an explicitly delimited untrusted data block. No code is selected,
        summarized or inferred; all characters are delivered.
        """
        lines = []
        for line in text.splitlines():
            if line.startswith('E "'):
                try:
                    value = json.loads(line[2:])
                except ValueError:
                    value = None
                if isinstance(value, str):
                    fence = 'DATA-' + hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]
                    while fence in value: fence += '-'
                    lines.append('E UNTRUSTED CONTENT characters=' + str(len(value)) + ' delimiter=' + fence +
                                 '\n' + value + '\n' + fence)
                    continue
            if line.startswith('E {'):
                try:
                    value = json.loads(line[2:])
                except ValueError:
                    value = None
                if isinstance(value, dict) and isinstance(value.get('content'), str):
                    content = value.pop('content')
                    fence = 'DATA-' + hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]
                    while fence in content: fence += '-'
                    lines.append('E ' + _encoded(value) + '\nUNTRUSTED CONTENT characters=' + str(len(content)) +
                                 ' delimiter=' + fence + '\n' + content + '\n' + fence)
                    continue
            lines.append(line)
        return '\n'.join(lines)

    def _render(self, snapshot, recent, guidance):
        sections = [self.prefix, 'TASK\n' + self.task]
        if guidance: sections.append('AVAILABLE CL\n' + guidance)
        if snapshot:
            snapshot = dict(snapshot)
            goals = snapshot.pop('goals', [])
            if goals:
                sections.append('REGISTERED ACCEPTANCE (already active; do not emit these again)\n' +
                                '\n'.join('G: ' + goal for goal in goals))
            sections.append('CURRENT ' + _encoded(snapshot))
        completed = []
        for row in self.records:
            if row['role'] == 'result':
                completed.extend(self._load(row['handle'])['metadata'].get('verifiedProcedures', []))
        if completed:
            sections.append('VERIFIED PROCEDURE RECEIPTS ' + _encoded(completed[-8:]) +
                            '; +G includes exact readback. Run done() to check final task acceptance; repair any failure.')
        if self.last_error:
            sections.append('LAST ERROR ' + self.last_error + '; context.read(' + _encoded(self.last_error) + ')')
            diagnostic = self._load(self.last_error)['metadata'].get('diagnostic')
            if diagnostic:
                sections.append('UNRESOLVED FAILURE DATA (exact check/dispatch feedback)\n' + diagnostic)
        if recent:
            sections.append('RECENT\n' + '\n'.join(row['role'] + ' ' + row['handle'] + '\n' + row.get('content',
                            'Full result available with context.read(' + _encoded(row['handle']) + ')') for row in recent))
        if self.records:
            sections.append('HISTORY ' + str(len(self.records)) + ' records; first=' + self.records[0]['handle'] +
                            ' latest=' + self.records[-1]['handle'] + '; context.read(handle,start=0,count=4000). ' +
                            'context.read("index",start=0,count=4000) lists handles.')
        return '\n\n'.join(sections)

    @staticmethod
    def _payload_handles(snapshot, recent):
        """State payloads reconstructable entirely from this one model view."""
        available = {state['stateRef'] for state in snapshot.get('states', []) if 'state' in state}
        pending = []
        for row in recent:
            if row.get('content', '').startswith('HISTORY PAGE '):
                continue  # A page never proves that a complete baseline was seen.
            delimiter = None
            for line in row.get('content', '').splitlines():
                if delimiter:
                    if line == delimiter: delimiter = None
                    continue
                if line.startswith(('UNTRUSTED CONTENT ', 'E UNTRUSTED CONTENT ')) and ' delimiter=' in line:
                    delimiter = line.split(' delimiter=', 1)[1]
                    continue
                match = re.match(r'^S \S+ (h[0-9]+) #\d+ subject=\S+ (full|delta|refresh|unchanged)(?: base=(h[0-9]+))?$', line)
                if not match: continue
                handle, mode, baseline = match.groups()
                if mode == 'full': available.add(handle)
                else: pending.append((handle, baseline))
        while pending:
            ready = {handle for handle, baseline in pending if baseline in available}
            if not ready: break
            available.update(ready)
            pending = [(handle, baseline) for handle, baseline in pending if handle not in ready]
        return available

    def build(self, *, host=None, guidance=''):
        """Return provider-shaped messages with the exact bounded prompt body."""
        prompt = self.prompt(host=host, guidance=guidance)
        # Keep the system prefix a separate stable cache segment. The remainder
        # is one current user view; archival roles never become system authority.
        body = prompt[len(self.prefix):].lstrip('\n') if self.prefix else prompt
        return ([{'role': 'system', 'content': self.prefix}] if self.prefix else []) + [{'role': 'user', 'content': body}]

    def prompt(self, *, host=None, guidance=''):
        """Deterministically compact state payloads, then oldest recent records.

        Tasks, selected CL signatures, goal status and live ref bindings never
        undergo substring truncation. State values and old messages retain
        explicit readable handles. If those essentials cannot fit, refuse.
        """
        with self.lock:
            recent = self._recent()
            snapshot = host.context_snapshot(compact=False) if host else {}
            # A rendered observation already present in RECENT needs only its
            # current project handle in the state index, not a duplicate payload.
            exposed = self._payload_handles({}, recent)
            if snapshot and recent and all(state['stateRef'] in exposed for state in snapshot.get('states', [])):
                snapshot = host.context_snapshot(compact=True)
            text = self._render(snapshot, recent, guidance)
            compacted = False
            if count_tokens(text) > self.token_budget and host:
                snapshot = host.context_snapshot(compact=True)
                text = self._render(snapshot, recent, guidance)
                compacted = True
            for index in range(len(recent)):
                if count_tokens(text) <= self.token_budget: break
                if index == len(recent)-1 and recent[index]['role'] in {'result','error'}:
                    # Deliver an explicit page of the newest result when the
                    # whole record cannot fit. Otherwise repeated full reads
                    # can be archived before the model ever sees any data.
                    # JSON-wrapped pages are not complete state payloads and
                    # therefore cannot acknowledge an observation baseline.
                    row = recent[index]
                    low, high, best = 1, min(16000,len(row.get('content',''))), None
                    while low <= high:
                        middle = (low+high)//2
                        paged = {**row,'content':self.read(row['handle'],count=middle,view='source')}
                        candidate = self._render(snapshot,recent[:index]+[paged],guidance)
                        if count_tokens(candidate) <= self.token_budget:
                            best,low = (paged,candidate),middle+1
                        else: high = middle-1
                    if best is not None:
                        recent[index],text = best
                        compacted = True
                        break
                recent[index] = {key: value for key, value in recent[index].items() if key != 'content'}
                text = self._render(snapshot, recent, guidance)
                compacted = True
            while recent and count_tokens(text) > self.token_budget:
                recent.pop(0)
                text = self._render(snapshot, recent, guidance)
                compacted = True
            tokens = count_tokens(text)
            if tokens > self.token_budget:
                raise ContextBudgetError('Immutable task, selected CL, goals and live refs exceed context budget; increase budget or narrow the task')
            available = self._payload_handles(snapshot, recent)
            self.acknowledgeable_state_refs = [state['stateRef'] for state in snapshot.get('states', [])
                                              if state['stateRef'] in available]
            self.metrics['turns'] += 1
            self.metrics['compactions'] += int(compacted)
            self.metrics['lastTokens'] = tokens
            self.metrics['maxTokens'] = max(tokens, self.metrics['maxTokens'])
            self.metrics['totalTokens'] += tokens
            return text

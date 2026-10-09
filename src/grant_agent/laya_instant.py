"""Local append-only episodic learning. Frozen encoders; no optimizer on writes.

Exact explicit replay is not a statistical confidence claim. Novel inputs use
leave-one-out cross-conformal label sets in domain/user/layer regions; ambiguous
sets abstain. Independent evaluation holdouts never enter prediction/calibration.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from functools import lru_cache
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import threading
import time

import numpy as np


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def unique_vectors(rows):
    """Copies cannot manufacture neighbour agreement or calibration size."""
    unique = {}
    for row in rows:
        if '_vectorKey' not in row:
            row['_vectorKey'] = hashlib.sha256(np.asarray(row['vector'], dtype=np.float32).round(6).tobytes()).hexdigest()
            row['_nonzero'] = any(row['vector'])
        key = (row['_vectorKey'], canonical(row['label']))
        old = unique.get(key)
        if old is None or (row['weight'], row['id']) > (old['weight'], old['id']):
            unique[key] = row
    return list(unique.values())


def latest_episodes(rows):
    """Resolve revisions before eligibility; a holdout can retire a train row."""
    latest = {}
    for row in rows:
        scope = (row['domain'], row['user'] if row['layer'] == 'personal' else '', row['layer'])
        latest[(*scope, row['key'], row['source'])] = row
    return list(latest.values())


def input_key(value):
    if isinstance(value, dict) and value.get('screenshotPath'):
        paths = value.get('screenshotPaths') or [value['screenshotPath']]
        value = {**value, 'imageSha256': [hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths]}
    if isinstance(value, dict) and set(value) == {'image'}:
        value = {'imageSha256': hashlib.sha256(Path(value['image']).read_bytes()).hexdigest()}
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@lru_cache(maxsize=1)
def encoder():
    from tokenizers import Tokenizer
    default = Path.home() / 'Documents/Codex/2026-09-30/the-ai-was-a-massive-improvement/evidence/r3/shared-state'
    directory = Path(os.environ.get('NEYVIA_INSTANT_ENCODER', default))
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    for name in ('tokenizer.json', 'embedding.npy'):
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != manifest['artifact_sha256'][name]:
            raise ValueError('Frozen encoder artifact changed: ' + name)
    identity = hashlib.sha256(canonical({n: manifest['artifact_sha256'][n]
        for n in ('tokenizer.json', 'embedding.npy')}).encode()).hexdigest()
    return Tokenizer.from_file(str(directory / 'tokenizer.json')), np.load(directory / 'embedding.npy', mmap_mode='r'), identity


@lru_cache(maxsize=1)
def routing_encoder():
    # Reuse the existing frozen lexical encoder, not its supervised head.
    # Vocabulary/IDF are fixed; a write never fits features on the evaluation set.
    from .laya_curriculum import load
    idf = load('manual-router')['idf']
    return idf, sorted(idf), 'manual-idf:' + hashlib.sha256(canonical(idf).encode()).hexdigest()


def encode(value, domain=''):
    if domain.startswith('routing'):
        if os.environ.get('NEYVIA_INSTANT_SEMANTIC'):
            from .laya_instant_semantic import encode as semantic_encode
            return semantic_encode(value if isinstance(value, str) else canonical(value))
        from .laya_curriculum import vector as lexical_vector
        idf, vocabulary, identity = routing_encoder()
        sparse = lexical_vector(value if isinstance(value, str) else canonical(value), idf)
        return np.asarray([sparse.get(t, 0) for t in vocabulary], dtype=np.float32), identity
    if domain == 'outcomes' or domain.startswith('scene:'):
        # Frozen hashing retains polarity and key/value bindings in receipts;
        # averaging semantic token embeddings erased these distinctions.
        text = value if isinstance(value, str) else canonical(value)
        words = re.findall(r'[a-z_]+(?:=[a-z_]+)?', text.lower())
        features = words + [' '.join(words[i:i+2]) for i in range(len(words)-1)]
        vector = np.zeros(1024, dtype=np.float32)
        for feature in features:
            digest = hashlib.sha256(feature.encode()).digest()
            vector[int.from_bytes(digest[:4], 'little') % len(vector)] += 1
        return vector / max(float(np.linalg.norm(vector)), 1e-9), 'receipt-key-value-hash-v1'
    if isinstance(value, dict) and (set(value) == {'image'} or value.get('screenshotPath')):
        from .taste_vision import embedding, encoder_digest, ASSETS
        stat = (ASSETS / 'clip/vision.onnx').stat()
        image_embedding = lambda path: embedding(Path(path), cache_root=Path(os.environ.get('NEYVIA_INSTANT_CACHE', 'D:/NeyviaRuns/laya-train/vision/embeddings')))
        paths = value.get('screenshotPaths', [])
        if len(paths) == 4:
            # C13 blind exports include A/B in both themes. Encode both arms,
            # never attach a pair preference to only the final B screenshot.
            arms = [[p for p in paths if re.search(r'-' + arm + r'-(dark|light)\.[^.]+$', Path(p).name)] for arm in ('A', 'B')]
            if all(len(arm) == 2 for arm in arms):
                means = [np.mean([image_embedding(p) for p in arm], axis=0) for arm in arms]
                difference = np.asarray(means[1] - means[0], dtype=np.float32)
                return difference / max(float(np.linalg.norm(difference)), 1e-9), 'clip-multiview-pair:' + encoder_digest((stat.st_size, stat.st_mtime_ns))
        if len(paths) == 2:
            difference = np.asarray(image_embedding(paths[1]) - image_embedding(paths[0]), dtype=np.float32)
            return difference / max(float(np.linalg.norm(difference)), 1e-9), 'clip-pair:' + encoder_digest((stat.st_size, stat.st_mtime_ns))
        return np.asarray(image_embedding(value.get('image') or value['screenshotPath']), dtype=np.float32), 'clip:' + encoder_digest((stat.st_size, stat.st_mtime_ns))
    text = value if isinstance(value, str) else canonical(value)
    if len(text) > 8192:
        raise ValueError('Instant input exceeds 8192 characters')
    tokenizer, table, identity = encoder()
    vector = np.mean(table[tokenizer.encode(text, add_special_tokens=False).ids or [0]], axis=0)
    return vector / max(float(np.linalg.norm(vector)), 1e-9), identity


class Episodes:
    def __init__(self, root):
        self.path = Path(root) / '.neyvia/laya/instant.sqlite'
        self.lock = threading.RLock()
        self.version = None
        self.rows = []
        self.calibration = {}
        self.query_calibration = {}
        self.forgotten = set()
        self.heads = {}
        self.consolidating = False
        self.consolidation = None
        self.observed_stamp = None
        self.pending_import = None

    @contextmanager
    def import_batch(self):
        """Atomic archive import; online learn remains one durable write.

        Queries on this instance wait for commit. Staged write receipts explicitly
        say pendingImport and must not be used as label-to-effect latency proof.
        """
        with self.lock:
            if self.pending_import is not None:
                raise ValueError('Nested episode import is not supported')
            self.refresh()
            original_rows, original_version = list(self.rows), self.version
            self.pending_import = []
            try:
                yield self
                with self.connect() as db:
                    db.executemany('INSERT INTO events(body) VALUES (?)',
                                   ((canonical(row),) for row in self.pending_import))
            finally:
                self.rows, self.version = original_rows, original_version
                self.pending_import = None
                self.observed_stamp = None
                self.refresh()

    @contextmanager
    def connect(self, *, read_only=False):
        if read_only:
            db = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=.05)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, timeout=5)
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, body TEXT NOT NULL)')
        try:
            with db:
                yield db
        finally:
            db.close()

    def refresh(self):
        if self.pending_import is not None:
            return
        if not self.path.exists():
            self.rows, self.version, self.observed_stamp = [], None, None
            return
        paths = (self.path, Path(str(self.path) + '-wal'))
        stamp = []
        for path in paths:
            try:
                stat = path.stat()
                stamp.append((stat.st_size, stat.st_mtime_ns))
            except FileNotFoundError:
                stamp.append(None)
        if stamp == self.observed_stamp:
            return
        with self.connect(read_only=True) as db:
            version = db.execute('SELECT max(id) FROM events').fetchone()[0]
            self.observed_stamp = stamp
            if version == self.version:
                return
            active = {r['id']: r for r in self.rows}
            forgotten = set(self.forgotten)
            for seq, raw in db.execute('SELECT id,body FROM events WHERE id > ? ORDER BY id', (self.version or 0,)):
                row = json.loads(raw)
                if row['kind'] == 'forget':
                    forgotten.add(row['source'])
                    active = {k: v for k, v in active.items() if v['source'] != row['source']}
                else:
                    row['id'] = seq
                    active[seq] = row
            self.rows, self.version = list(active.values()), version
            self.forgotten = forgotten
            # Update only affected regions, including corrections and tombstones.
            self.update_calibration()

    def update_calibration(self):
        from .laya_instant_calibration import LeaveOneOut
        self.query_calibration.clear()
        regions = {}
        for row in latest_episodes(self.rows):
            if '_nonzero' not in row:
                row['_nonzero'] = any(row['vector'])
            if row['split'] == 'holdout' or not row['_nonzero']:
                continue
            key = (row['domain'], row['user'] if row['layer'] == 'personal' else '', row['layer'], row['encoder'])
            regions.setdefault(key, {})[row['key'], row['source']] = row
        for key in list(self.calibration):
            if key not in regions:
                del self.calibration[key]
        for key, latest in regions.items():
            rows = unique_vectors(latest.values())
            choices = list({canonical(r['label']): r['label'] for r in rows}.values())
            index = self.calibration.setdefault(key, LeaveOneOut())
            index.update(rows, choices, canonical)

    def append(self, row):
        if self.pending_import is not None:
            self.pending_import.append(row)
            seq = -len(self.pending_import)
            self.rows.append({**row, 'id': seq})
            return seq
        with self.connect() as db:
            seq = db.execute('INSERT INTO events(body) VALUES (?)', (canonical(row),)).lastrowid
        self.observed_stamp = None
        self.refresh()
        return seq

    def learn(self, domain, input, label, source, *, user='', layer='corrective', weight=1,
              evidence=None, split=None):
        started = time.perf_counter()
        if not domain or not source or layer not in {'personal', 'corrective'} or (layer == 'personal' and not user):
            raise ValueError('Domain, provenance and personal user identity are required')
        if not isinstance(label, (str, bool, int)) or not 0 < weight <= 1:
            raise ValueError('Expected a scalar label and weight in (0,1]')
        key = input_key(input)
        vector, identity = encode(input, domain)
        # Every new user label has immediate effect. Evaluation holdouts are
        # explicitly assigned by the evaluator, never randomly hidden on write.
        partition = 'train'
        if split is not None and split not in {'train', 'calibration', 'holdout'}:
            raise ValueError('Invalid split')
        with self.lock:
            self.refresh()
            duplicate = next((r for r in reversed(self.rows) if r['key'] == key and r['domain'] == domain
                and r['source'] == source and r['user'] == user and r['layer'] == layer), None)
            if duplicate and canonical(duplicate['label']) == canonical(label) and duplicate['encoder'] == identity and duplicate['weight'] == weight and (split is None or duplicate['split'] == split):
                return {'learned': False, 'episodeId': duplicate['id'], 'reason': 'already-ingested'}
            row = dict(kind='learn', domain=domain, input=input, key=key, vector=vector.tolist(), encoder=identity,
                       label=label, source=source, user=user, layer=layer, weight=weight,
                       evidence=evidence or {}, split=split or partition, at=time.time())
            seq = self.append(row)
            if domain != 'ui-glance' and not domain.startswith('scene:') and self.pending_import is None and len(self.rows) % 25 == 0 and not self.consolidating:
                self.consolidating = True
                def background():
                    try:
                        from .laya_instant_consolidate import consolidate
                        self.consolidation = consolidate(self.path.parents[2])
                    except Exception as exc:
                        self.consolidation = {'error': str(exc)}
                    finally:
                        self.consolidating = False
                threading.Thread(target=background, name='laya-consolidate', daemon=True).start()
        if self.pending_import is not None:
            return {'learned': True, 'pendingImport': True, 'domain': domain, 'layer': layer}
        return {'learned': True, 'episodeId': seq, 'domain': domain, 'layer': layer,
                'labelToEffectMs': (time.perf_counter()-started)*1000, 'signal': 'LAYA learned this'}

    def forget(self, source):
        with self.lock:
            if self.pending_import is not None:
                raise ValueError('Forgetting cannot be mixed with an archive import')
            self.refresh()
            count = sum(r['source'] == source for r in self.rows)
            self.append({'kind': 'forget', 'source': source, 'at': time.time()})
        return {'forgotten': count, 'source': source}

    @staticmethod
    def scores(vector, rows, labels, prior=None, *, vectors=None):
        from .laya_instant_calibration import NEIGHBOURS, TEMPERATURE
        if not rows:
            return {}, 2.0, 0
        matrix = vectors if vectors is not None else np.asarray([r['vector'] for r in rows], dtype=np.float32)
        distances = np.maximum(0, 1 - matrix @ vector)
        indices = np.argsort(distances, kind='stable')[:NEIGHBOURS]
        votes = Counter()
        for i in indices:
            votes[canonical(rows[i]['label'])] += rows[i]['weight'] * float(np.exp(
                (distances[indices[0]] - distances[i]) / TEMPERATURE))
        total = sum(votes.values())
        mix = len(indices) / (len(indices) + 1)
        prior = prior(vector) if callable(prior) else prior
        probabilities = {canonical(label): round(mix * votes[canonical(label)] / total + (1-mix) *
                         float((prior or {}).get(canonical(label), 1/len(labels))), 12) for label in labels}
        return probabilities, float(distances[indices[0]]), len(indices)

    def head_prior(self, domain, user, layer, identity):
        name = hashlib.sha256(canonical([domain, user if layer == 'personal' else '', layer, identity]).encode()).hexdigest()
        path = self.path.parent / 'heads' / (name + '.json')
        if not path.exists():
            return None, None
        stamp = path.stat().st_mtime_ns
        if name not in self.heads or self.heads[name][0] != (stamp, self.version):
            data = json.loads(path.read_text(encoding='utf-8'))
            if not data.get('promoted') or data['encoder'] != identity or data['trainingVersion'] != self.version:
                return None, None
            weights = np.asarray(data['weights'], dtype=np.float32)
            def predict(vector):
                raw = np.maximum(0, np.asarray(vector) @ weights)
                raw = raw / max(float(raw.sum()), 1e-9)
                return {canonical(label): float(p) for label, p in zip(data['labels'], raw)}
            self.heads[name] = ((stamp, self.version), predict)
        return self.heads[name][1], (name, stamp)

    def query(self, domain, input, *, user='', labels=None, prior=None):
        started = time.perf_counter()
        result = {'answer': None, 'confidence': 0, 'escalate': True, 'source': 'laya-instant', 'advisoryOnly': True}
        def done(**values):
            return {**result, **values, 'ms': (time.perf_counter()-started)*1000}
        with self.lock:
            if self.pending_import is not None:
                raise ValueError('Query waits until the archive import is committed')
            self.refresh()
            candidates = [r for r in self.rows if r['domain'] == domain and
                          (r['layer'] == 'corrective' or (user and r['user'] == user))]
            candidates = [r for r in latest_episodes(candidates) if r['split'] != 'holdout']
            if not candidates:
                return done(reason='no-episodes')
            vector, identity = encode(input, domain)
            candidates = [r for r in candidates if r['encoder'] == identity]
            key = input_key(input)
            for layer in ('personal', 'corrective'):
                rows = [r for r in candidates if r['layer'] == layer]
                if not rows:
                    continue
                # Newest correction supersedes the same source, but independent disagreement is retained.
                exact = [r for r in rows if r['key'] == key and r['weight'] == 1]
                if exact:
                    if len({canonical(r['label']) for r in exact}) > 1:
                        return done(reason='contradictory-labels', conflict=True, layer=layer)
                    answer = exact[-1]['label']
                    if labels is None or canonical(answer) in {canonical(v) for v in labels}:
                        return done(answer=answer, confidence=1, escalate=False, layer=layer,
                                    confidenceKind='explicit-exact-replay', episodeId=exact[-1]['id'])
                choices = labels or list({canonical(r['label']): r['label'] for r in rows}.values())
                if len(choices) < 2:
                    continue
                if np.linalg.norm(vector) < 1e-8:
                    return done(reason='empty-visual-difference-is-not-quality-evidence')
                index = self.calibration.get((domain, user if layer == 'personal' else '', layer, identity))
                train = index.rows if index else unique_vectors(r for r in rows if any(r['vector']))
                if not train:
                    continue
                matrix = index.vectors if index is not None and len(index.vectors) == len(train) else np.asarray([r['vector'] for r in train], dtype=np.float32)
                distances = 1 - matrix @ vector
                near = [r for r, d in zip(train, distances) if r['weight'] == 1 and d < 1e-5]
                if len({canonical(r['label']) for r in near}) > 1:
                    return done(reason='contradictory-near-duplicates', conflict=True, layer=layer)
                # A head consolidated on these episodes is not an out-of-fold
                # predictor. Keep it out of statistical admission; episode votes
                # include the same uniform prior in each LOO fold and query.
                probabilities, distance, count = self.scores(vector, train, choices, vectors=matrix)
                samples = index.selected if index else []
                stored_choices = {canonical(r['label']) for r in train}
                if stored_choices != {canonical(v) for v in choices}:
                    from .laya_instant_calibration import LeaveOneOut
                    choice_key = (domain, user, layer, identity, tuple(map(canonical, choices)))
                    if choice_key not in self.query_calibration:
                        extra = LeaveOneOut()
                        extra.update(train, choices, canonical)
                        self.query_calibration[choice_key] = extra
                    index = self.query_calibration[choice_key]
                    samples = index.selected
                if len(samples) < 19 or not probabilities or max(probabilities.values()) < index.threshold:
                    continue
                pvalues = {canonical(label): (1 + sum(s[0] >= 1-probabilities[canonical(label)] for s in samples)) /
                           (len(samples)+1) for label in choices}
                admitted = [label for label in choices if pvalues[canonical(label)] > .05]
                radius = index.radius
                if len(admitted) == 1 and distance <= radius and count >= 3:
                    return done(answer=admitted[0], confidence=.95, escalate=False, layer=layer,
                                confidenceKind='leave-one-out-cross-conformal-singleton',
                                confidenceMeaning='nominal-level-not-selective-accuracy-guarantee', pvalues=pvalues, radius=radius,
                                calibrationCases=len(samples), agreementThreshold=index.threshold,
                                leaveOneOutAccuracy=sum(s[3] for s in samples)/len(samples))
                # A personal region with evidence but uncertainty cannot be overridden by shared taste.
                if layer == 'personal' and distance <= radius:
                    return done(reason='personal-region-ambiguous', pvalues=pvalues)
        return done(reason='insufficient-regional-calibration')

    def status(self):
        with self.lock:
            self.refresh()
            return {'episodes': len(self.rows), 'domains': dict(Counter(r['domain'] for r in self.rows)),
                    'recent': [{k: r[k] for k in ('id', 'domain', 'layer', 'source', 'at', 'label')}
                               for r in self.rows[-5:][::-1]], 'localOnly': True,
                    'consolidating': self.consolidating, 'consolidation': self.consolidation}


@lru_cache(maxsize=32)
def store(root):
    return Episodes(Path(root).resolve())


def query(root, domain, input, **kwargs):
    from .laya_host import WARMING_UP, instant_ready
    if not instant_ready():
        # Never load the encoders on a request: until the background warmup finishes, say so.
        return {'answer': None, 'confidence': 0, 'escalate': True, 'available': False, 'warming': True,
                'reason': WARMING_UP, 'source': 'laya-instant'}
    try:
        return store(str(Path(root).resolve())).query(domain, input, **kwargs)
    except (OSError, ValueError, ImportError, sqlite3.Error) as exc:
        return {'answer': None, 'confidence': 0, 'escalate': True, 'reason': str(exc), 'source': 'laya-instant'}

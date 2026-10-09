"""Incremental leave-one-episode-out scores, never a held-out accuracy claim.

Cross-conformal p-values are empirical admission evidence. Their nominal level
is not a guarantee of conditional/selective accuracy; that is measured outside
the store on independent families. Identical inputs cannot calibrate each other.
"""
import numpy as np

NEIGHBOURS = 3
TEMPERATURE = .1


class LeaveOneOut:
    def __init__(self):
        self.ids = ()
        self.vectors = np.empty((0, 0), dtype=np.float32)
        self.distances = np.empty((0, 0), dtype=np.float32)
        self.samples = []
        self.threshold = None
        self.selected = []
        self.rows = []
        self.neighbours = np.empty((0, 0), dtype=int)
        self.sample_cache = {}
        self.conflicts = 0
        self.radius = None
        self.choices = ()

    def update(self, rows, choices, canonical):
        ids = tuple(r['id'] for r in rows)
        self.rows = rows
        choice_keys = tuple(map(canonical, choices))
        if ids == self.ids and choice_keys == self.choices:
            return
        self.choices = choice_keys
        if len(choices) < 2:
            # A one-class region cannot admit a novel categorical decision.
            self.ids, self.samples, self.selected, self.threshold = ids, [], [], None
            self.radius = None
            self.vectors = np.asarray([r['vector'] for r in rows], dtype=np.float32)
            self.distances = np.empty((0, 0), dtype=np.float32)
            self.neighbours = np.empty((0, 0), dtype=int)
            return
        vectors = np.asarray([r['vector'] for r in rows], dtype=np.float32)
        old = len(self.ids)
        extending = bool(old and ids[:old] == self.ids and self.distances.shape == (old, old))
        if extending:
            # Append only computes distances to new episodes. Corrections/forget
            # rebuild the affected region, not unrelated users or domains.
            distances = np.empty((len(rows), len(rows)), dtype=np.float32)
            distances[:old, :old] = self.distances
            cross = np.maximum(0, 1 - vectors[old:] @ vectors.T)
            distances[old:, :] = cross
            distances[:, old:] = cross.T
        else:
            distances = np.maximum(0, 1 - vectors @ vectors.T)
        self.ids, self.vectors, self.distances = ids, vectors, distances
        masked = distances.copy()
        keys = np.asarray([r['key'] for r in rows])
        masked[keys[:, None] == keys[None, :]] = np.inf
        # Manual declarations and generated paraphrases share an action family.
        # They must not validate one another in an imported production corpus.
        families = np.asarray([str(r.get('evidence', {}).get('family') or r['key'])
            if r.get('domain', '').startswith('routing') else r['key'] for r in rows])
        masked[families[:, None] == families[None, :]] = np.inf
        k = min(NEIGHBOURS, len(rows))
        if extending:
            candidates = np.concatenate((self.neighbours, np.tile(np.arange(old, len(rows)), (old, 1))), axis=1)
            rank = np.argsort(np.take_along_axis(masked[:old], candidates, axis=1), axis=1, kind='stable')[:, :k]
            previous = np.take_along_axis(candidates, rank, axis=1)
            indices = np.concatenate((previous, np.argsort(masked[old:], axis=1, kind='stable')[:, :k]))
        else:
            indices = np.argsort(masked, axis=1, kind='stable')[:, :k]
        self.neighbours = indices
        labels = [canonical(label) for label in choices]
        row_labels = np.asarray([canonical(r['label']) for r in rows])
        conflicts = np.any((distances < 1e-5) & (row_labels[:, None] != row_labels[None, :]), axis=1)
        self.conflicts = int(conflicts.sum())
        samples = []
        cache = {}
        for i, row in enumerate(rows):
            # Query already abstains on conflicting equal vectors. Such points
            # are outside the selective policy, not errors it would admit.
            if row['weight'] != 1 or conflicts[i]:
                continue
            nearest = [int(j) for j in indices[i] if np.isfinite(masked[i, j])]
            if not nearest:
                continue
            cachekey = (row['id'], tuple(rows[j]['id'] for j in nearest), tuple(labels))
            if cachekey in self.sample_cache:
                cache[cachekey] = self.sample_cache[cachekey]
                samples.append(cache[cachekey])
                continue
            votes = {label: 0. for label in labels}
            for j in nearest:
                votes[canonical(rows[j]['label'])] += rows[j]['weight'] * float(np.exp(
                    (masked[i, nearest[0]] - masked[i, j]) / TEMPERATURE))
            total = sum(votes.values())
            mix = len(nearest) / (len(nearest) + 1)
            p = {label: round(mix * value / total + (1-mix)/len(labels), 12) for label, value in votes.items()}
            winner = max(p, key=p.get)
            sample = (1-p[canonical(row['label'])], float(masked[i, nearest[0]]),
                      p[winner], winner == canonical(row['label']))
            samples.append(sample)
            cache[cachekey] = sample
        self.sample_cache = cache
        self.samples = samples
        # Local agreement is calibrated out-of-fold, not on resubstitution.
        # This empirical selective-risk filter has no distribution-free claim.
        # The independent evaluation must still reach the requested 0.95 gate.
        self.threshold, self.radius, self.selected = None, None, []
        if not samples:
            return
        # Jointly calibrate radius AND agreement, as the online policy uses both.
        # Cumulative counts evaluate all observed cut points without O(n^3) loops.
        agreements = sorted({s[2] for s in samples}, reverse=True)
        radii = sorted({s[1] for s in samples})
        ai, ri = {v: i for i, v in enumerate(agreements)}, {v: i for i, v in enumerate(radii)}
        counts = np.zeros((len(agreements), len(radii)), dtype=np.int32)
        wins = np.zeros_like(counts)
        for score, distance, agreement, correct in samples:
            counts[ai[agreement], ri[distance]] += 1
            wins[ai[agreement], ri[distance]] += int(correct)
        counts = counts.cumsum(axis=0, dtype=np.int32).cumsum(axis=1, dtype=np.int32)
        wins = wins.cumsum(axis=0, dtype=np.int32).cumsum(axis=1, dtype=np.int32)
        # Include the same +1 finite-sample correction used by the p-values.
        # Otherwise a nominal 95% region can never yield a singleton at 0.05.
        eligible = (counts >= 19) & ((counts-wins+1)/(counts+1) <= .05)
        maximum = int(np.where(eligible, counts, 0).max())
        if maximum:
            candidates = np.argwhere(eligible & (counts == maximum))
            a, r = min(candidates.tolist(), key=lambda pair: (pair[1], pair[0]))
            self.threshold, self.radius = agreements[a], radii[r]
            self.selected = [s for s in samples if s[2] >= self.threshold and s[1] <= self.radius]

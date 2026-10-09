"""Audio for the LAYA video loop: a deterministic beat-grid bed and exact measurements.

The bed is synthesised from (bpm, seconds, seed, gain) so a render is reproducible.
Measurements are computed from decoded PCM of the rendered file, never from the plan:
ITU-R BS.1770 integrated loudness (K-weighting, 400 ms blocks, absolute and relative
gates), 4x oversampled true peak, clipped samples, silent runs, and beats measured from
an onset envelope (spectral flux) with the tempo found by autocorrelation.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

SR = 48000


def _env(n, attack, decay):
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    return a * np.exp(-np.maximum(t - attack, 0) / max(decay, 1e-4))


def _note(freq, seconds, *, attack=0.01, decay=0.4, kind='sine'):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    if kind == 'tri':
        wave = 2 / np.pi * np.arcsin(np.sin(2 * np.pi * freq * t))
    else:
        wave = np.sin(2 * np.pi * freq * t)
    return wave * _env(n, attack, decay)


def _kick(seconds=0.35):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    sweep = 45 + 70 * np.exp(-t / 0.04)
    return np.sin(2 * np.pi * np.cumsum(sweep) / SR) * _env(n, 0.002, 0.12)


def _hat(rng, seconds=0.06):
    n = int(seconds * SR)
    noise = rng.standard_normal(n)
    b, a = signal.butter(2, 7000 / (SR / 2), 'high')
    return signal.lfilter(b, a, noise) * _env(n, 0.001, 0.018) * 0.35


# A calm minor progression (Am - F - C - G), one chord per bar.
CHORDS = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (130.81, 164.81, 196.0), (196.0, 246.94, 293.66)]


def synth_bed(bpm, seconds, *, seed=7, gain_db=0.0, cover_s=None, tail_s=1.2):
    """Stereo float bed: kick on every beat, hats on off-beats, a pad chord per bar.

    ``cover_s`` limits the music to the first cover_s seconds (the rest is silence),
    which is how a too-short bed produces dead air. No limiter: what is mixed is what is
    measured. Returns (samples[N,2], beat_times).
    """
    rng = np.random.default_rng(seed)
    total = int(round(seconds * SR))
    mono = np.zeros(total + SR)
    beat = 60.0 / bpm
    music_end = min(seconds, cover_s if cover_s is not None else seconds)
    beats = np.arange(0, music_end - 1e-9, beat)
    kick, = [_kick()]
    for i, t in enumerate(beats):
        start = int(round(t * SR))
        level = 0.9 if i % 4 == 0 else 0.7
        mono[start:start + len(kick)] += level * kick[:max(0, len(mono) - start)]
        off = int(round((t + beat / 2) * SR))
        hat = _hat(rng)
        if off < len(mono):
            mono[off:off + len(hat)] += hat[:len(mono) - off]
    bar = 4 * beat
    for j, t in enumerate(np.arange(0, music_end - 1e-9, bar)):
        dur = min(bar, music_end - t) + 0.6
        start = int(round(t * SR))
        for f in CHORDS[j % len(CHORDS)]:
            tone = 0.22 * _note(f, dur, attack=0.25, decay=2.2, kind='tri')
            mono[start:start + len(tone)] += tone[:max(0, len(mono) - start)]
        bass = 0.35 * _note(CHORDS[j % len(CHORDS)][0] / 2, dur, attack=0.02, decay=1.2)
        mono[start:start + len(bass)] += bass[:max(0, len(mono) - start)]
    mono = mono[:total]
    # Fade the music tail to digital silence (designed end, not dead air).
    fade = int(min(tail_s, music_end) * SR)
    end = int(round(music_end * SR))
    if fade > 0 and end <= total:
        mono[end - fade:end] *= np.linspace(1, 0, fade) ** 2
        mono[end:] = 0
    mono *= 10 ** (gain_db / 20)
    stereo = np.stack([mono, mono], axis=1)
    return stereo, beats.tolist()


def write_wav(path, samples):
    from scipy.io import wavfile
    # Float WAV keeps over-full-scale values (the encoder's conversion clips them). scipy
    # writes no timestamped PEAK chunk, so identical audio gives identical bytes.
    wavfile.write(str(path), SR, samples.astype(np.float32))


def k_weight(x):
    """BS.1770 K-weighting (pre-filter + RLB), coefficients re-derived for 48 kHz."""
    b1 = [1.53512485958697, -2.69169618940638, 1.19839281085285]
    a1 = [1.0, -1.69065929318241, 0.73248077421585]
    b2 = [1.0, -2.0, 1.0]
    a2 = [1.0, -1.99004745483398, 0.99007225036621]
    return signal.lfilter(b2, a2, signal.lfilter(b1, a1, x, axis=0), axis=0)


def integrated_lufs(x):
    x = np.atleast_2d(x.T).T if x.ndim == 1 else x
    y = k_weight(x)
    block, hop = int(0.4 * SR), int(0.1 * SR)
    if len(y) < block:
        return -70.0
    starts = np.arange(0, len(y) - block + 1, hop)
    power = np.array([np.mean(y[s:s + block] ** 2, axis=0).sum() for s in starts])
    loud = -0.691 + 10 * np.log10(np.maximum(power, 1e-12))
    gated = power[loud > -70]
    if not len(gated):
        return -70.0
    relative = -0.691 + 10 * np.log10(np.mean(gated)) - 10
    final = power[(loud > -70) & (loud > relative)]
    return float(-0.691 + 10 * np.log10(np.mean(final))) if len(final) else -70.0


def true_peak_db(x):
    up = signal.resample_poly(x, 4, 1, axis=0)
    return float(20 * np.log10(np.max(np.abs(up)) + 1e-12))


def silent_runs(x, *, threshold_db=-50.0, window=0.1):
    """Runs (start_s, end_s) where the windowed RMS stays under threshold_db dBFS."""
    mono = x.mean(axis=1) if x.ndim == 2 else x
    n = int(window * SR)
    frames = len(mono) // n
    if not frames:
        return []
    rms = np.sqrt(np.mean(mono[:frames * n].reshape(frames, n) ** 2, axis=1))
    quiet = 20 * np.log10(rms + 1e-12) < threshold_db
    runs, start = [], None
    for i, q in enumerate(quiet.tolist() + [False]):
        if q and start is None:
            start = i
        elif not q and start is not None:
            runs.append((start * window, i * window))
            start = None
    return runs


def onset_envelope(x, hop=480):
    """Spectral-flux onset strength at 100 Hz (hop 10 ms)."""
    mono = x.mean(axis=1) if x.ndim == 2 else x
    nper = 2048
    freqs, _, z = signal.stft(mono, SR, nperseg=nper, noverlap=nper - hop, boundary=None, padded=False)
    # The beat is carried by the low band (kick, bass); broadband hats sit on off-beats.
    mag = np.log1p(np.abs(z[freqs < 500]) * 100)
    flux = np.maximum(np.diff(mag, axis=1), 0).sum(axis=0)
    flux = np.concatenate([[0], flux])
    flux -= signal.medfilt(flux, 31)
    # Column k is centred at k*hop + nper/2: shift so index i means time i*hop.
    shift = int(round(nper / 2 / hop))
    flux = np.concatenate([np.zeros(shift), flux])
    return np.maximum(flux, 0), hop / SR


def beats(x, *, bpm_range=(60, 180)):
    """Measured beat times: tempo by autocorrelation of the onset envelope, phase by grid fit.

    Returns {tempoBpm, beatTimes, strength}; empty when there is no rhythmic content.
    """
    env, step = onset_envelope(x)
    if env.max() <= 0 or len(env) < 200:
        return {'tempoBpm': None, 'beatTimes': [], 'strength': 0.0}
    env = env / env.max()
    ac = np.correlate(env, env, 'full')[len(env) - 1:]
    lags = np.arange(len(ac)) * step
    valid = (lags >= 60 / bpm_range[1]) & (lags <= 60 / bpm_range[0])
    if not valid.any():
        return {'tempoBpm': None, 'beatTimes': [], 'strength': 0.0}
    lag = int(np.argmax(np.where(valid, ac, -1)))
    period = lag * step
    # Refine the period on a 1 ms grid around the autocorrelation peak.
    best = (-1, period, 0.0)
    times = np.arange(len(env)) * step
    for p in np.arange(period - 0.01, period + 0.0105, 0.001):
        for phase in np.arange(0, p, step):
            grid = np.arange(phase, times[-1], p)
            idx = np.clip(np.round(grid / step).astype(int), 0, len(env) - 1)
            score = env[idx].sum()
            if score > best[0]:
                best = (score, p, phase)
    _, p, phase = best
    grid = np.arange(phase, times[-1], p)
    idx = np.clip(np.round(grid / step).astype(int), 0, len(env) - 1)
    # Keep grid points that carry an onset (music present), so silence has no beats.
    active = [float(t) for t, i in zip(grid, idx) if env[max(0, i - 2):i + 3].max() > 0.15]
    strength = float(env[idx].mean() / (env.mean() + 1e-9))
    return {'tempoBpm': round(60 / p, 2), 'beatTimes': active, 'strength': round(strength, 3)}


def measure(x):
    clipped = int(np.sum(np.abs(x) >= 0.999))
    return {'integratedLufs': round(integrated_lufs(x), 2), 'truePeakDbtp': round(true_peak_db(x), 2),
            'clippedSamples': clipped, 'silentRuns': silent_runs(x)}

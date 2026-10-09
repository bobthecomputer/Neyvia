"""Feed a recorded 16 kHz mono WAV through Neyvia's dictation stream as if it were a live microphone and print
the timeline of partials: when each update arrived, how many words were settled (stable) and how many were
still grey (provisional), plus time-to-first-word and the gap between updates.

    PYTHONPATH=src python tools/dictation_stream_timeline.py sample.wav [--provider local|openai|codex]
        [--engine-url http://127.0.0.1:48911] [--piece-ms 250] [--speed 1.0] [--out timeline.json]

The audio is paced in real time (--speed 2 = twice as fast), so the numbers are what a speaker would see.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
import wave
from pathlib import Path


def read_wav(path: str) -> bytes:
    with wave.open(path, "rb") as handle:
        if handle.getframerate() != 16000 or handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise SystemExit("Need 16 kHz mono 16-bit PCM WAV")
        return handle.readframes(handle.getnframes())


def run(wav: str, provider: str, piece_ms: int, speed: float, engine_url: str = "") -> dict:
    from grant_agent import neyvia_dictation as d

    root = Path(tempfile.mkdtemp(prefix="nx-stream-proof-"))
    os.environ["NEYVIA_UI_STATE_ROOT"] = str(root)
    if engine_url:
        os.environ["NEYVIA_DICTATION_ENGINE_URL"] = engine_url
    d.write_settings(root, {"provider": provider})
    pcm = read_wav(wav)
    step = 32 * piece_ms
    sid = "proof" + str(int(time.time()))
    started = time.perf_counter()
    rows, seq, first_word = [], 0, None
    last_text = ""
    for at in range(0, len(pcm), step):
        piece = pcm[at:at + step]
        due = started + (at / 32000.0) / speed
        wait = due + (piece_ms / 1000.0) / speed - time.perf_counter()  # a piece exists once its audio was spoken
        if wait > 0:
            time.sleep(wait)
        sent = time.perf_counter()
        answer = d.stream(root, sid, "append", seq, piece, history=[])
        seq += 1
        now = time.perf_counter()
        text = (answer.get("partial") or "").strip()
        if text and first_word is None:
            first_word = (now - started) * speed * 1000
        if text != last_text:
            rows.append({"t_ms": round((now - started) * 1000), "audio_ms": round((at + len(piece)) / 32), "call_ms": round((now - sent) * 1000),
                         "stable_words": len((answer.get("stable") or "").split()), "provisional_words": len((answer.get("provisional") or "").split()),
                         "text": text, "provider": answer.get("provider")})
            last_text = text
    release = time.perf_counter()
    final = d.stream(root, sid, "finish", seq, b"", history=[])
    done = time.perf_counter()
    gaps = [b["t_ms"] - a["t_ms"] for a, b in zip(rows, rows[1:])]
    return {
        "wav": Path(wav).name, "audio_ms": round(len(pcm) / 32), "provider": final.get("provider"), "providerNote": final.get("warning") or "",
        "piece_ms": piece_ms, "speed": speed,
        "time_to_first_word_ms": None if first_word is None else round(first_word),
        "updates": len(rows), "median_update_gap_ms": sorted(gaps)[len(gaps) // 2] if gaps else None,
        "max_update_gap_ms": max(gaps) if gaps else None,
        "median_append_call_ms": sorted(r["call_ms"] for r in rows)[len(rows) // 2] if rows else None,
        "release_to_final_ms": round((done - release) * 1000), "final_text": final.get("text"), "timeline": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wav")
    parser.add_argument("--provider", default="local")
    parser.add_argument("--engine-url", default="")
    parser.add_argument("--piece-ms", type=int, default=250)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    report = run(args.wav, args.provider, args.piece_ms, args.speed, args.engine_url)
    for row in report["timeline"]:
        print(f'{row["t_ms"]:>6} ms  audio {row["audio_ms"]:>6}  settled {row["stable_words"]:>3}  grey {row["provisional_words"]:>3}  {row["text"][-70:]}')
    print({k: v for k, v in report.items() if k != "timeline"})
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

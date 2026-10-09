from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .subprocess_utils import hidden_windows_subprocess_kwargs
from .proofs_e_sv import enforced


VIDEO_DIGEST_SCHEMA = "fluxio.video_digest.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], *, cwd: Path, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        **hidden_windows_subprocess_kwargs(),
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(detail[-4000:] or f"Command failed with exit code {completed.returncode}")
    return completed


def _frame_signature(
    ffmpeg: str,
    path: Path,
    *,
    cwd: Path,
    timeout: int = 30,
) -> tuple[bytes, float, float]:
    """Return a small grayscale signature plus normalized brightness/contrast."""
    completed = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vf",
            "crop=iw:ih-60:0:0,scale=64:36,format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        cwd=str(cwd),
        capture_output=True,
        timeout=timeout,
        check=False,
        **hidden_windows_subprocess_kwargs(),
    )
    if completed.returncode != 0 or not completed.stdout:
        return b"", 0.0, 0.0
    signature = completed.stdout
    average = sum(signature) / len(signature)
    variance = sum((value - average) ** 2 for value in signature) / len(signature)
    return signature, round(average / 255, 4), round(math.sqrt(variance) / 255, 4)


def _mean_pixel_delta(left: bytes, right: bytes) -> float:
    if not left or not right or len(left) != len(right):
        return 255.0
    return sum(abs(a - b) for a, b in zip(left, right)) / len(left)


def _number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _frame_rate(value: object) -> float:
    raw = str(value or "").strip()
    if "/" in raw:
        numerator, denominator = raw.split("/", 1)
        divisor = _number(denominator)
        return _number(numerator) / divisor if divisor else 0.0
    return _number(raw)


def _timecode(seconds: float) -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


class VideoEvidenceBuilder:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.ffmpeg = shutil.which("ffmpeg") or ""
        self.ffprobe = shutil.which("ffprobe") or ""

    def availability(self) -> tuple[bool, str]:
        if self.ffmpeg and self.ffprobe:
            whisper = shutil.which("whisper")
            suffix = f" Local Whisper is available at {whisper}." if whisper else " Local Whisper is optional and not installed."
            return True, f"FFmpeg and FFprobe are available.{suffix}"
        return False, "video tools require both ffmpeg and ffprobe on PATH."

    def _input(self, value: object) -> Path:
        path = Path(str(value or "")).expanduser()
        if not path.is_absolute():
            path = self.root / path
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Video file does not exist: {path}")
        return path

    def _output_dir(self, source: Path, requested: object) -> Path:
        if requested:
            output = Path(str(requested)).expanduser()
            if not output.is_absolute():
                output = self.root / output
            output = output.resolve()
            try:
                output.relative_to(self.root)
            except ValueError as exc:
                raise ValueError("Video digest output must stay inside the workspace root.") from exc
            return output
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", source.stem).strip("-") or "video"
        return (
            self.root
            / ".agent_control"
            / "mission_artifacts"
            / "native_tools"
            / "video"
            / f"{safe_stem}-{stamp}-{uuid.uuid4().hex[:6]}"
        )

    @enforced("sv.video.metadata")
    def inspect(
        self,
        path_value: object,
        *,
        timeout_seconds: int = 60,
    ) -> dict[str, Any]:
        available, detail = self.availability()
        if not available:
            raise RuntimeError(detail)
        source = self._input(path_value)
        completed = _run(
            [
                self.ffprobe,
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-print_format",
                "json",
                str(source),
            ],
            cwd=self.root,
            timeout=max(1, min(int(timeout_seconds), 300)),
        )
        payload = json.loads(completed.stdout or "{}")
        streams = list(payload.get("streams") or [])
        video_stream = next((item for item in streams if item.get("codec_type") == "video"), {})
        audio_streams = [item for item in streams if item.get("codec_type") == "audio"]
        duration = _number(video_stream.get("duration")) or _number(payload.get("format", {}).get("duration"))
        return {
            "path": str(source),
            "sha256": _sha256(source),
            "sizeBytes": source.stat().st_size,
            "durationSeconds": round(duration, 3),
            "durationTimecode": _timecode(duration),
            "formatName": str(payload.get("format", {}).get("format_name") or ""),
            "video": {
                "codec": str(video_stream.get("codec_name") or ""),
                "width": int(video_stream.get("width") or 0),
                "height": int(video_stream.get("height") or 0),
                "pixelFormat": str(video_stream.get("pix_fmt") or ""),
                "frameRate": round(_frame_rate(video_stream.get("avg_frame_rate")), 3),
                "frameCount": int(video_stream.get("nb_frames") or 0),
            },
            "audio": {
                "present": bool(audio_streams),
                "streamCount": len(audio_streams),
                "codecs": [str(item.get("codec_name") or "") for item in audio_streams],
                "sampleRates": [int(item.get("sample_rate") or 0) for item in audio_streams],
            },
            "streamCount": len(streams),
            "rawProbe": payload,
        }

    @enforced("sv.video.digest")
    def digest(self, args: dict[str, Any]) -> dict[str, Any]:
        timeout_seconds = max(
            1,
            min(int(args.get("timeoutSeconds") or 1800), 7200),
        )
        deadline = time.monotonic() + timeout_seconds

        def remaining_timeout(step_timeout: int) -> int:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Video digest timed out after {timeout_seconds} seconds."
                )
            return max(1, min(int(step_timeout), math.ceil(remaining)))

        def run_step(
            command: list[str],
            *,
            timeout: int,
        ) -> subprocess.CompletedProcess[str]:
            return _run(
                command,
                cwd=self.root,
                timeout=remaining_timeout(timeout),
            )

        source = self._input(args.get("path"))
        metadata = self.inspect(
            source,
            timeout_seconds=remaining_timeout(60),
        )
        output = self._output_dir(source, args.get("outputDir"))
        output.mkdir(parents=True, exist_ok=True)
        frame_count = max(1, min(int(args.get("maxFrames") or 12), 36))
        available_frames = int(metadata.get("video", {}).get("frameCount") or 0)
        if available_frames > 0:
            frame_count = min(frame_count, available_frames)
        scene_frame_count = max(0, min(int(args.get("maxSceneFrames", 8)), 24))
        scene_threshold = max(0.05, min(float(args.get("sceneThreshold") or 0.32), 0.95))
        duration = float(metadata.get("durationSeconds") or 0)
        uniform_times = (
            [(index * duration / frame_count) for index in range(frame_count)]
            if duration > 0
            else [0.0]
        )
        frames: list[dict[str, Any]] = []
        for index, timestamp in enumerate(uniform_times, start=1):
            frame_path = output / f"frame-{index:03d}.jpg"
            timestamp_label = _timecode(timestamp).replace(":", r"\:")
            frame_filter = (
                "scale=960:-2:force_original_aspect_ratio=decrease,"
                f"drawtext=text='{timestamp_label}':x=12:y=h-th-12:fontsize=24:"
                "fontcolor=white:box=1:boxcolor=black@0.68:boxborderw=6"
            )
            run_step(
                [
                    self.ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{timestamp:.3f}",
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    "-vf",
                    frame_filter,
                    "-y",
                    str(frame_path),
                ],
                timeout=60,
            )
            frames.append(
                {
                    "kind": "uniform",
                    "index": index,
                    "timestampSeconds": round(timestamp, 3),
                    "timecode": _timecode(timestamp),
                    "path": str(frame_path),
                    "sha256": _sha256(frame_path),
                }
            )

        selected_frames: list[dict[str, Any]] = []
        last_selected_signature = b""
        for frame in frames:
            frame_path = Path(frame["path"])
            signature, brightness, contrast = _frame_signature(
                self.ffmpeg,
                frame_path,
                cwd=self.root,
                timeout=remaining_timeout(30),
            )
            delta = _mean_pixel_delta(signature, last_selected_signature)
            rejection_reason = ""
            if brightness >= 0.97:
                rejection_reason = "near_blank_light_frame"
            elif brightness <= 0.012 and contrast <= 0.012:
                rejection_reason = "near_blank_dark_frame"
            elif last_selected_signature and delta < 0.5:
                rejection_reason = "near_duplicate_frame"
            frame["quality"] = {
                "brightness": brightness,
                "contrast": contrast,
                "deltaFromPreviousSelected": round(delta, 3),
                "selected": not rejection_reason,
                "rejectionReason": rejection_reason,
            }
            if rejection_reason:
                continue
            selected_copy = output / f"selected-{len(selected_frames) + 1:03d}.jpg"
            shutil.copy2(frame_path, selected_copy)
            selected = {**frame, "selectedPath": str(selected_copy), "selectedSha256": _sha256(selected_copy)}
            selected_frames.append(selected)
            last_selected_signature = signature

        if not selected_frames:
            fallback = frames[len(frames) // 2]
            selected_copy = output / "selected-001.jpg"
            shutil.copy2(fallback["path"], selected_copy)
            fallback["quality"] = {
                **dict(fallback.get("quality") or {}),
                "selected": True,
                "rejectionReason": "fallback_only_available_frame",
            }
            selected_frames.append(
                {**fallback, "selectedPath": str(selected_copy), "selectedSha256": _sha256(selected_copy)}
            )

        scene_frames: list[dict[str, Any]] = []
        scene_scan_seconds = max(1, min(int(args.get("sceneScanSeconds") or 600), 3600))
        if scene_frame_count and duration > 0:
            scene_pattern = output / "scene-%03d.jpg"
            completed = run_step(
                [
                    self.ffmpeg,
                    "-hide_banner",
                    "-i",
                    str(source),
                    "-t",
                    str(min(scene_scan_seconds, max(1, math.ceil(duration)))),
                    "-vf",
                    f"select=gt(scene\\,{scene_threshold}),showinfo,scale=960:-2:force_original_aspect_ratio=decrease,format=yuvj420p",
                    "-fps_mode",
                    "vfr",
                    "-frames:v",
                    str(scene_frame_count),
                    "-q:v",
                    "2",
                    "-y",
                    str(scene_pattern),
                ],
                timeout=max(90, min(600, scene_scan_seconds + 30)),
            )
            timestamps = [float(item) for item in re.findall(r"pts_time:([0-9.]+)", completed.stderr)]
            for index, scene_path in enumerate(sorted(output.glob("scene-*.jpg")), start=1):
                timestamp = timestamps[index - 1] if index <= len(timestamps) else 0.0
                scene_frames.append(
                    {
                        "kind": "scene_change",
                        "index": index,
                        "timestampSeconds": round(timestamp, 3),
                        "timecode": _timecode(timestamp),
                        "path": str(scene_path),
                        "sha256": _sha256(scene_path),
                    }
                )

        columns = max(1, math.ceil(math.sqrt(len(selected_frames))))
        rows = max(1, math.ceil(len(selected_frames) / columns))
        storyboard = output / "storyboard.jpg"
        run_step(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-framerate",
                "1",
                "-start_number",
                "1",
                "-i",
                str(output / "selected-%03d.jpg"),
                "-vf",
                (
                    "scale=320:180:force_original_aspect_ratio=decrease,"
                    "pad=320:180:(ow-iw)/2:(oh-ih)/2:color=black,"
                    f"tile={columns}x{rows}:nb_frames={len(selected_frames)}:padding=4:margin=4:color=black"
                ),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                "-y",
                str(storyboard),
            ],
            timeout=90,
        )

        artifacts = [
            str(storyboard),
            *[item["selectedPath"] for item in selected_frames],
            *[item["path"] for item in frames],
            *[item["path"] for item in scene_frames],
        ]
        audio_result: dict[str, Any] = {"present": bool(metadata["audio"]["present"]), "status": "not_requested"}
        audio_path = output / "audio-16khz-mono.wav"
        if bool(args.get("extractAudio", True)) and metadata["audio"]["present"]:
            run_step(
                [
                    self.ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(source),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    "-y",
                    str(audio_path),
                ],
                timeout=180,
            )
            audio_result = {
                "present": True,
                "status": "extracted",
                "path": str(audio_path),
                "sha256": _sha256(audio_path),
            }
            artifacts.append(str(audio_path))

        transcription = {"status": "not_requested", "engine": ""}
        transcribe_mode = str(args.get("transcribe") or "auto").strip().lower()
        whisper = shutil.which("whisper")
        if transcribe_mode != "none" and audio_path.is_file():
            if whisper:
                model = str(args.get("whisperModel") or "turbo").strip()
                run_step(
                    [
                        whisper,
                        str(audio_path),
                        "--model",
                        model,
                        "--output_dir",
                        str(output),
                        "--output_format",
                        "json",
                        "--verbose",
                        "False",
                    ],
                    timeout=max(300, min(3600, math.ceil(duration * 4) + 120)),
                )
                transcript_path = output / f"{audio_path.stem}.json"
                transcription = {
                    "status": "completed",
                    "engine": "openai-whisper-local",
                    "model": model,
                    "path": str(transcript_path),
                }
                if transcript_path.is_file():
                    artifacts.append(str(transcript_path))
            else:
                transcription = {
                    "status": "unavailable",
                    "engine": "",
                    "detail": "Local Whisper is not installed. Audio was preserved for another transcription provider.",
                }

        manifest_path = output / "video-digest.json"
        readme_path = output / "MODEL_README.md"
        manifest = {
            "schema": VIDEO_DIGEST_SCHEMA,
            "source": metadata,
            "sampling": {
                "uniformFrameCount": len(frames),
                "selectedFrameCount": len(selected_frames),
                "sceneFrameCount": len(scene_frames),
                "sceneThreshold": scene_threshold,
                "sceneScanSeconds": min(scene_scan_seconds, max(1, math.ceil(duration))) if duration else 0,
            },
            "frames": frames,
            "selectedFrames": selected_frames,
            "sceneFrames": scene_frames,
            "storyboard": {"path": str(storyboard), "sha256": _sha256(storyboard)},
            "audio": audio_result,
            "transcription": transcription,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "timeoutSeconds": timeout_seconds,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        readme_path.write_text(
            "# Model-readable video evidence\n\n"
            "Inspect `storyboard.jpg` first. It contains nonblank, meaningfully changed frames only. "
            "Use `video-digest.json` to map each selected frame to its exact timestamp and review rejected-frame reasons. "
            "Inspect individual selected, uniform, and scene-change frames when visual detail matters. "
            "Use the transcript when present; otherwise the extracted mono WAV remains available for a speech model.\n",
            encoding="utf-8",
        )
        artifacts.extend([str(manifest_path), str(readme_path)])
        return {
            "path": str(source),
            "outputDir": str(output),
            "manifestPath": str(manifest_path),
            "storyboardPath": str(storyboard),
            "frameCount": len(selected_frames),
            "sampledFrameCount": len(frames),
            "sceneFrameCount": len(scene_frames),
            "audio": audio_result,
            "transcription": transcription,
            "artifacts": artifacts,
        }

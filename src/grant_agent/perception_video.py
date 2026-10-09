"""Decode one explicitly requested video frame with an already installed FFmpeg."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def extract_frame(path, scratch, frame):
    if type(frame) is not int or not 0 <= frame <= 100000:
        raise ValueError('Video frame must be 0..100000')
    if path.stat().st_size > 20_000_000:
        raise ValueError('Video exceeds 20 MB observation limit')
    executable = shutil.which('ffmpeg')
    if not executable:
        # Playwright ships a small decoder for its own WebM recordings.
        candidate = Path(os.environ.get('LOCALAPPDATA', '')) / 'ms-playwright/ffmpeg-1011/ffmpeg-win64.exe'
        executable = str(candidate) if candidate.is_file() else None
    if not executable:
        raise RuntimeError('No installed FFmpeg; supply decoded frames or install a decoder separately')
    scratch.mkdir(parents=True, exist_ok=True)
    target = Path(tempfile.mkdtemp(prefix='frame-', dir=scratch)) / 'frame.png'
    result = subprocess.run([executable, '-nostdin', '-hide_banner', '-loglevel', 'error',
        '-protocol_whitelist', 'file,pipe', '-i', str(path), '-vf',
        f"select=eq(n\\,{frame}),scale=1600:1600:force_original_aspect_ratio=decrease",
        '-frames:v', '1', str(target)], capture_output=True, timeout=45,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode or not target.is_file():
        raise RuntimeError('Installed decoder cannot read this video/frame; no visual state inferred')
    return target, {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'frame': frame,
                    'bytes': path.stat().st_size, 'decoder': Path(executable).name,
                    'frontier': ['Only this selected frame was observed; audio and unsampled motion are unknown.']}

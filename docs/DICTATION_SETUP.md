# Dictation Setup (Local-First)

The backend supports push-to-talk dictation sessions with local-first transcription.

## Flow

1. `start_dictation` opens a dictation session.
2. UI records audio and passes the file path to `stop_dictation`.
3. Backend runs local STT command on demand (lazy load behavior).
4. If local STT is not configured or fails, backend falls back to OS dictation guidance.

## Configure local STT

Use `configure_dictation` and provide:

- `strategy`: `local_first` (recommended) or `os_only`
- `localSttCommand`: executable name/path (for example `whisper-cli`)
- `localSttArgs`: args list where `{audio}` is replaced with the recorded file path
- `localSttTimeoutSeconds`: command timeout

Example payload:

```json
{
  "strategy": "local_first",
  "localSttCommand": "whisper-cli",
  "localSttArgs": ["-m", "models/ggml-base.bin", "-f", "{audio}"],
  "localSttTimeoutSeconds": 30,
  "osFallbackHint": "Press your OS dictation shortcut and speak."
}
```

## Notes

- Audio recording is UI-provided; backend transcribes an explicit file path.
- No continuous capture is performed by backend services.

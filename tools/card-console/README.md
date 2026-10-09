# Card Console

A local, read-only dashboard for a small NFC/RFID bench: it tells you what is
plugged in, what tools are installed, and reads a presented tag's UID. Nothing
more.

## What it does

- **Device inventory** - enumerates serial/USB devices and labels the ones it
  recognises (Flipper Zero, Chameleon, PC/SC readers). Uses `pyserial` when
  available, otherwise a Windows PnP query.
- **Toolchain status** - reports whether `chameleon-cli`, `flipper`, `qFlipper`,
  `ufbt`, `mfoc`, `socat` are installed, and their versions.
- **Tag UID read** - non-destructive `FF CA 00 00 00` inventory against a PC/SC
  reader (needs a reader and `pyscard`).

## What it deliberately does NOT do

- No key recovery / attacks (`mfoc` is detected, never invoked).
- No card writes, no cloning.

Those are exactly the steps that turn a bench tool into a credential-forgery
tool, and they are not wired up here. If you have a card you own and are
entitled to dump, run `mfoc` yourself where the law and your authorization
allow it.

## Run

```
python server.py
# -> http://127.0.0.1:7070
```

Stdlib only. Binds `127.0.0.1` by default (not reachable off the machine).
Override with env vars `CARD_CONSOLE_HOST` / `CARD_CONSOLE_PORT`.

Optional, for real tag reads:

```
pip install pyscard   # PC/SC: reader listing + UID inventory
pip install pyserial  # richer serial enumeration
```

## API

| Method | Path              | Returns                                              |
|--------|-------------------|------------------------------------------------------|
| GET    | `/api/environment`| platform, python, host/port                          |
| GET    | `/api/tools`      | toolchain presence + versions                        |
| GET    | `/api/devices`    | serial / USB / smartcard-reader inventory            |
| GET    | `/api/readers`    | PC/SC reader list (or why it is unavailable)         |
| POST   | `/api/scan`       | read a presented tag's UID (`{"reader_index": 0}`)   |

## Extending device recognition

Add a `(VID, PID) -> (label, kind)` entry to `KNOWN_USB` in `server.py`, or a
substring to `NAME_HINTS`. An unlisted device still appears, just without a
friendly label. The Chameleon Ultra USB IDs vary by revision - confirm yours
with `Get-PnpDevice` and add it.

# Windows driver setup

Each checkout needs its own pinned MIT Cua Driver 0.32.0 runtime. Git excludes
the binaries. With system Python, reuse the existing T16 installation:

```powershell
& 'C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe' scripts/install_cua_driver.py --source C:/Users/user/Projects/nx-t16-cua/tools/cua-driver-win/runtime
```

This verifies both executable SHA-256 values before copying and never replaces
unexpected files. Without `--source`, the script downloads the pinned 31 MB
archive and verifies its archive and executable hashes; it never installs globally.
Driver state checks both files and their hashes and gives the setup command when
either file is missing. Native helpers compile locally with the existing Windows
.NET Framework compiler when first used; no compiler download is needed.

Run `python scripts/verify_fix2_driver.py` for a fresh stdio discovery/native
screen-size call and missing/corrupt-runtime refusals. This proves runtime readiness,
not physical takeover or remote control from another PC.

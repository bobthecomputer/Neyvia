# Add an optional Neyvia module

Copy this directory into `apps/<your-module-id>`. Edit `neyvia.module.json`: choose a unique ID, name, purpose, owned files, manual ID and action namespace (`neyvia.mod.<namespace>.<verb>`). Replace the greeting implementation. Modules are trusted repository code, not sandboxed downloaded packages.

Use `manuals/cl/hello-module.cl` as the smallest executable manual example. Name real registered actions and include a check plus a procedure. Add the manual source and artifact to `config/neyvia_manuals.json`, compile, then regenerate the map:

```powershell
& C:/Users/example/AppData/Local/Programs/Python/Python313/python.exe scripts/cl_compile_manuals.py
& C:/Users/example/AppData/Local/Programs/Python/Python313/python.exe scripts/generate_module_map.py
& C:/Users/example/AppData/Local/Programs/Python/Python313/python.exe scripts/cl_compile_manuals.py --check
```

Restart only your owned backend to register the new schema. Search your ID in Settings > Modules. Read its manual and source, call its action through `neyvia.cl`, run the contract, disable it and confirm calls fail, then enable it and confirm persistence after reload. Commit the CL source, compiled artifact, module files and registry together. Full instructions live in `neyvia.cl`, chapter `modding-neyvia`.

Publication note: local account paths and network identifiers in this document are neutral examples.

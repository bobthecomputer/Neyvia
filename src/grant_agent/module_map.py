"""Generate a navigable module map from source ownership, imports and CL manuals."""
from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from .module_plugins import REPO, manifests

SCOPES = {"src/grant_agent": "backend", "web/src/neyvia/next": "surface",
          "web/src/neyvia": "surface",
          "apps": "app", "manuals/cl": "manual", "manuals/skills": "skill", "tools": "tool",
          "connectors": "connector", "plugins/neyvia": "plugin", "scripts/gamedev": "gamedev",
          "src/neyvia_sdk": "sdk-python", "packages/neyvia-sdk": "sdk-js",
          "web/src": "web", "scripts": "script", "config": "configuration",
          "desktop-ui": "desktop", "src-tauri": "desktop-native", "rust": "rust",
          "templates": "template"}
EXCLUDED = {"__pycache__", "node_modules", ".git", ".agent_control", ".neyvia", ".build", "dist", "target", "build"}
REGISTRY = REPO / "config/neyvia.modules.json"
GENERATOR_SOURCES = ('src/grant_agent/module_map.py', 'scripts/generate_module_map.py')
CONFIGURATION_INPUTS = ('config/contract_path_policy.json', 'config/neyvia_manuals.json')
SOURCE_SUFFIXES = frozenset({
    '.py', '.pyw', '.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx', '.css', '.scss', '.sass',
    '.html', '.vue', '.svelte', '.rs', '.cl', '.gd', '.go', '.java', '.cs', '.c', '.cc',
    '.cpp', '.h', '.hpp', '.sh', '.ps1', '.sql',
})
PRIVATE_SOURCE_PATHS = frozenset({"config/neyvia_secret_broker.json"})


def private_source(path):
    """Private runtime configuration is never a browsable module source."""
    name = Path(path)
    if name.is_absolute():
        try:
            name = name.resolve().relative_to(REPO.resolve())
        except ValueError:
            return False
    return name.as_posix().casefold() in PRIVATE_SOURCE_PATHS


def is_source_file(path):
    """Only executable/implementation sources participate in source currency."""
    return Path(path).suffix.lower() in SOURCE_SUFFIXES


def _guard_read(path):
    # The guard inspects only resolved path/name metadata before any bytes are read.
    from .proof_credential_guard import check_access
    check_access(path)


def _normalized_digest(path):
    raw = path.read_bytes()
    try:
        raw = raw.decode("utf-8").replace("\r\n", "\n").encode("utf-8")
    except UnicodeDecodeError:
        pass
    return hashlib.sha256(raw).hexdigest()


def source_digest(path):
    path = Path(path)
    if not is_source_file(path):
        raise ValueError("Module source currency accepts source files only")
    _guard_read(path)
    return _normalized_digest(path)


def source_hashes(files, *, repo=REPO):
    """Hash only source files; ownership-only/configuration rows carry no source digest."""
    result = {}
    for file in files:
        path = Path(file)
        if not path.is_absolute():
            path = Path(repo) / path
        if is_source_file(path):
            result[str(file).replace("\\", "/")] = source_digest(path)
    return result


def source_texts(files, *, repo=REPO):
    """Read text only for source files selected for AST/API/import extraction."""
    result = {}
    for file in files:
        path = Path(file)
        if not path.is_absolute():
            path = Path(repo) / path
        if is_source_file(path):
            _guard_read(path)
            result[str(file).replace("\\", "/")] = path.read_text(encoding="utf-8-sig", errors="replace")
    return result


def configuration_hashes():
    """Keep explicit public generator-policy bindings separate from source currency."""
    result = {}
    for file in CONFIGURATION_INPUTS:
        path = REPO / file
        _guard_read(path)
        result[file] = _normalized_digest(path)
    return result


def inventory():
    from .contract_coverage import classify
    policy_path = REPO / 'config/contract_path_policy.json'
    _guard_read(policy_path)
    policy=json.loads(policy_path.read_text(encoding='utf-8'))
    files=set()
    for scope in SCOPES:
        for directory,children,names in (REPO/scope).walk():
            children[:]=[name for name in children if name not in EXCLUDED
                and not name.endswith(('.egg-info','.dist-info'))
                and not (directory/name).is_junction()
                and not any(((directory/name).relative_to(REPO).as_posix()+'/').startswith(prefix)
                            for prefix in policy['noBehaviourPrefixes'])]
            for name in names:
                path=directory/name
                if path.is_symlink() or path.suffix in {'.pyc','.pyo'}:continue
                relative=path.relative_to(REPO).as_posix()
                if private_source(relative):continue
                if classify(relative,policy)['kind'] in {'behaviour','unknown'}:files.add(relative)
    return sorted(files)


def file_identity(path):
    scope = next(scope for scope in SCOPES if path.startswith(scope + "/"))
    return SCOPES[scope] + "." + str(Path(path[len(scope) + 1:]).with_suffix("")).replace("\\", "/").replace("/", ".")


def native_catalog(catalog_root=None):
    from .native_tools import NativeToolRegistry
    root = Path(catalog_root).resolve() if catalog_root is not None else REPO / ".agent_control/mod/catalog"
    return NativeToolRegistry(root)._specs


def manual_documents():
    from .neyvia_manuals import document
    index = json.loads((REPO / "config/neyvia_manuals.json").read_text(encoding="utf-8"))["manuals"]
    # Reuse exact-source checked artifacts; document() falls back to strict CL
    # compilation if the source, artifact or compiler admission changed.
    return [(row, document(row)[1]) for row in index]


def generate(catalog_root=None):
    files = inventory()
    plugins = manifests()
    ownership = {file: row["id"] for row in plugins for file in row["files"]}
    if len(ownership) != sum(len(row["files"]) for row in plugins):
        raise ValueError("Two optional modules own the same file")
    modules = {}
    text = {}
    imports = defaultdict(set)
    catalog = native_catalog(catalog_root)
    manual_tools = defaultdict(set)
    _guard_read(REPO / 'config/neyvia_manuals.json')
    manuals = manual_documents()
    manual_sources = [(row["id"], json.dumps(document, ensure_ascii=False)) for row, document in manuals]
    references = defaultdict(set)
    for manual_id, encoded in manual_sources:
        for match in re.findall(r'(?:src/grant_agent|web/src/neyvia|apps|manuals/cl|scripts/gamedev|plugins/neyvia|tools|connectors|src/neyvia_sdk|packages/neyvia-sdk)/[A-Za-z0-9_./-]+\.[A-Za-z0-9]+', encoded):
            references[match.rstrip(".")].add(manual_id)
    navigation = next(doc for row, doc in manuals if row["id"] == "neyvia")
    links = " ".join(navigation["chapters"].get("module-manuals", {}).get("guidance", []))
    for manual_row, _ in manuals:
        if "id='" + manual_row["id"] + "'" not in links:
            raise ValueError("Neyvia entry point lacks module manual link: " + manual_row["id"])
    missing = []
    for index_row, document in manuals:
        for chapter in document["chapters"].values():
            for action in chapter["actions"].values():
                name = action["tool"]
                manual_tools[name].add(index_row["id"])
                if name not in catalog:
                    missing.append(index_row["id"] + ": " + name)
    if missing:
        raise ValueError("Manual names missing action(s): " + ", ".join(sorted(set(missing))))
    source_text = source_texts(files)
    for file in files:
        identity = ownership.get(file, file_identity(file))
        row = modules.setdefault(identity, {"id": identity, "name": identity.split(".")[-1],
            "purpose": "Provides " + identity.replace(".", " / ") + " in Neyvia.",
            "files": [], "manual": "neyvia", "manuals": [], "actions": [], "settings": [],
            "events": [], "dependencies": [], "ownerSurface": "Settings / Modules",
            "optional": False, "publicApi": [], "contracts": ["modules.verify-map"]})
        row["files"].append(file)
        if file.startswith(("src/neyvia_sdk/", "packages/neyvia-sdk/")):
            row["manual"] = "modules"
            row["ownerSurface"] = "App / mod SDK"
        path = REPO / file
        source = source_text.get(file)
        if source is None:
            continue
        text[file] = source
        if path.suffix == ".py":
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            doc = ast.get_docstring(tree)
            if doc:
                row["purpose"] = doc.splitlines()[0][:240]
            row["publicApi"] += [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_")]
            for node in ast.walk(tree):
                if isinstance(node, ast.Tuple) and len(node.elts) == 4 and isinstance(node.elts[0], ast.Constant) and isinstance(node.elts[0].value, str):
                    name = node.elts[0].value
                    exact = name if name in catalog else "neyvia." + name
                    if exact in catalog:
                        row["actions"].append(exact)
                if isinstance(node, ast.ImportFrom):
                    if node.level:
                        base = Path(file).parent
                        for _ in range(node.level - 1):
                            base = base.parent
                        target = base / (node.module or "").replace(".", "/")
                    elif (node.module or "").startswith("grant_agent"):
                        target = REPO / "src" / node.module.replace(".", "/")
                        target = target.relative_to(REPO)
                    else:
                        continue
                    imports[file].update([target.as_posix() + ".py", (target / "__init__.py").as_posix()])
        else:
            for match in re.finditer(r'(?:from\s*|import\s*\()[\'\"](\.[^\'\"]+)', source):
                target = (path.parent / match[1]).resolve()
                if target.is_relative_to(REPO.resolve()):
                    name = target.relative_to(REPO.resolve()).as_posix()
                    imports[file].update([name, *(name + extension for extension in (".js", ".jsx", ".ts", ".tsx"))])
            exported = re.findall(r'export\s+(?:const|function|class)\s+(\w+)', source)
            row["publicApi"] += exported
            if exported and file.startswith("web/"):
                row["purpose"] = "Provides " + ", ".join(exported[:4]) + " for Neyvia's " + ("UI controls" if path.suffix == ".jsx" else "UI state and behavior") + "."
                row["ownerSurface"] = "Neyvia / " + row["name"]
            if path.suffix == ".css":
                row["purpose"] = "Styles " + path.stem + " with Neyvia's shared theme tokens."
            if path.suffix == ".cl" and file.startswith("manuals/cl/"):
                row["manual"] = path.stem
                row["purpose"] = "Executable Connected Language manual for " + path.stem + "."
            if file.startswith("apps/scroll-study/"):
                row["manual"] = "scroll-generator"
                row["ownerSurface"] = "Scroll Study"
            if file.startswith("scripts/gamedev/"):
                row["manual"] = "game-dev"
                row["ownerSurface"] = "Game development"
        row["events"] += re.findall(r'(?:bus\.emit|\.publish)\([\'\"]([^\'\"]+)', source)
        row["settings"] += re.findall(r'(?:prefs|settings)\.([A-Za-z_]\w*)', source)
    for plugin in plugins:
        row = modules[plugin["id"]]
        row.update({key: plugin[key] for key in ("name", "purpose", "manual", "settings", "events", "dependencies", "ownerSurface", "optional")})
        row["actions"] = [action["name"] for action in plugin["actions"]]
        row["contracts"].append(plugin["manual"] + ".verify-greeting")
    file_owners = {file: identity for identity, row in modules.items() for file in row["files"]}
    from .contract_gate import sites, python_sites
    from .contract_coverage import SymbolOwners
    python_owners=python_sites(files)
    symbols=SymbolOwners(REPO,files)
    for row in modules.values():row['outcomeContracts']=[]
    for _,document in manuals:
        for contract in document.get('proofs',{}).get('contracts',[]):
            if contract['id']=='modules.verify-map':continue
            for reference in contract.get('checkedAt',[])+contract.get('impact',[]):
                for file in sites(reference,python_owners=python_owners) | symbols.sites(reference):
                    if file in file_owners:modules[file_owners[file]]['outcomeContracts'].append(contract['id'])
    # An adapter's own source owns its executable witnesses. This does not
    # propagate to its imports or to arbitrary sourceFiles lists.
    declared={contract['id'] for _,document in manuals for contract in document.get('proofs',{}).get('contracts',[])
              if contract['id']!='modules.verify-map'}
    for path in (REPO/'config/proofs').glob('*.json'):
        manifest=json.loads(path.read_text(encoding='utf-8'))
        if not manifest.get('area'):continue
        outcomes=[row['id'] for row in manifest.get('contracts',[]) if row['id'] in declared]
        refs=sites(manifest.get('runner',''),python_owners=python_owners) | sites(manifest.get('module',''),python_owners=python_owners)
        for file in refs:
            if file in file_owners:modules[file_owners[file]]['outcomeContracts'].extend(outcomes)
    action_owners = defaultdict(set)
    for identity, row in modules.items():
        for name in row["actions"]:
            action_owners[name].add(identity)
    # The generic registry owns dynamically constructed definitions that cannot
    # be attributed to a literal tuple. Mark provenance instead of guessing.
    registry_owner = modules["backend.native_tools"]
    registry_owner["actions"] += [name for name in catalog if not action_owners[name]]
    for identity, row in modules.items():
        deps = set(row["dependencies"])
        for file in row["files"]:
            deps.update(file_owners[target] for target in imports[file] if target in file_owners and file_owners[target] != identity)
        row["dependencies"] = sorted(deps)
        related = set(row["manuals"])
        for action in row["actions"]:
            related.update(manual_tools[action])
        # Source references in grounded manuals also bind non-tool owners.
        for file in row["files"]:
            related.update(references[file])
        row["manuals"] = sorted(related | {row["manual"]})
        if row["manual"] == "neyvia" and related:
            row["manual"] = sorted(related)[0]
        if not (REPO / "manuals/cl" / (row["manual"] + ".cl")).is_file():
            raise ValueError("Module lacks an existing CL manual: " + identity)
        if not row["optional"] and row["ownerSurface"] == "Settings / Modules":
            row["ownerSurface"] = "Neyvia / " + row["manual"]
        for field in ("actions", "settings", "events", "contracts", "outcomeContracts", "publicApi"):
            row[field] = sorted(set(row[field]))
        for dep in row["dependencies"]:
            if dep not in modules:
                raise ValueError("Unknown module dependency: " + identity + " -> " + dep)
    # Connector owners are explicit manual action groups as well as source files.
    gamedev = next((doc for index_row, doc in manuals if index_row["id"] == "game-dev"), None)
    if gamedev:
        for connector in ("unity", "godot", "blender", "android", "roblox"):
            actions = sorted({row["tool"] for chapter in gamedev["chapters"].values() for row in chapter["actions"].values()
                              if connector in json.dumps(row).lower()})
            modules["connector." + connector] = {"id": "connector." + connector, "name": connector.title(),
                "purpose": "Game development integration described by game-dev.cl for " + connector.title() + ".",
                "files": [], "manual": "game-dev", "manuals": ["game-dev"], "actions": actions,
                "settings": [], "events": [], "dependencies": ["backend.neyvia_gamedev"],
                "ownerSurface": "Game development", "optional": False, "publicApi": actions, "contracts": ["modules.verify-map"]}
    hashes = source_hashes(files)
    return {"schema": "neyvia.module-registry.v1", "scopes": SCOPES, "excludedDirectories": sorted(EXCLUDED),
            "ownedFiles": files, "sourceHashes": hashes,
            "generatorSources": source_hashes(GENERATOR_SOURCES),
            "configurationHashes": configuration_hashes(),
            "modules": sorted(modules.values(), key=lambda row: row["id"])}


def check():
    paths = [*(REPO / file for file in inventory()), REGISTRY, REPO / "config/neyvia_manuals.json",
             REPO / "MODULES.md", *(REPO / "modules").glob("*/README.md")]
    stamp = tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) if path.is_file() else (str(path), None, None)
                  for path in sorted(paths))
    result = _checked_at(stamp)
    return dict(result)


@lru_cache(maxsize=2)
def _checked_at(stamp):
    if not REGISTRY.is_file():raise ValueError('Module registry is missing; generate it first')
    actual=json.loads(REGISTRY.read_text(encoding='utf-8'))
    files=inventory()
    hashes = source_hashes(files)
    if (actual.get('ownedFiles') != files or actual.get('sourceHashes') != hashes
            or actual.get('scopes') != SCOPES
            or actual.get('generatorSources') != source_hashes(GENERATOR_SOURCES)
            or actual.get('configurationHashes') != configuration_hashes()):
        raise ValueError("Module map drifted; run scripts/generate_module_map.py, review and commit")
    owned=[file for row in actual['modules'] for file in row['files']]
    if set(owned) != set(files) or len(owned) != len(set(owned)):
        raise ValueError('Module ownership has missing, unrelated or duplicate files')
    identities={row['id'] for row in actual['modules']}
    if len(identities) != len(actual['modules']) or any(set(row['dependencies'])-identities for row in actual['modules']):
        raise ValueError('Module dependencies or identities are invalid')
    optional={file:row['id'] for row in manifests() for file in row['files']}
    if any(row['id'] != optional.get(file,file_identity(file)) for row in actual['modules'] for file in row['files']):
        raise ValueError('Source was reassigned to an unrelated module')
    for path, content in documentation(actual).items():
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            raise ValueError("Generated module documentation drifted: " + str(path.relative_to(REPO)))
    expected_docs = {path for path in documentation(actual) if path.name == "README.md"}
    if set((REPO / "modules").glob("*/README.md")) != expected_docs:
        raise ValueError("Module documentation has stale owners; regenerate the map")
    owned = {file for row in actual["modules"] for file in row["files"]}
    if any(private_source(file) for file in owned | set(actual["sourceHashes"])):
        raise ValueError("Private runtime configuration leaked into the source map")
    from .neyvia_modules import call
    for file in PRIVATE_SOURCE_PATHS:
        try:
            call(None, "modules.source", {"id": "", "path": file})
        except PermissionError:
            continue
        raise ValueError("Module source API did not refuse private configuration")
    return {"ok": True, "modules": len(actual["modules"]), "files": len(files),
            "sourceFiles": len(hashes), "configurationInputs": len(CONFIGURATION_INPUTS),
            "publicSources": {"privateExcluded": True, "privateReadRefused": True},
            "missingFiles": [], "missingActions": [], "unownedFiles": []}


def documentation(data):
    pages = {}
    index = ["# Neyvia modules", "", "Generated from source ownership, exported APIs, imports and executable CL manuals. Regenerate with `scripts/generate_module_map.py`; `run modules.verify-map()` and the CL compiler's `--check` reject drift.", "",
        "Apps and mods reuse the stable [neyvia-sdk](packages/neyvia-sdk/README.md) boundary. Internal module exports below describe today's source; only documented SDK APIs are compatibility promises. See [Building apps and mods](docs/BUILDING_APPS_AND_MODS.md).", "",
        "| Module | Purpose | API and manual |", "|---|---|---|"]
    for row in data["modules"]:
        directory = REPO / "modules" / row["id"]
        readme = directory / "README.md"
        content = ["# " + row["name"], "", row["purpose"], "",
            "- **Public API:** " + (", ".join("`" + name + "`" for name in row["publicApi"] + row["actions"]) or "No separately exported API; use the owning module.") + ".",
            "- **Manual:** " + ", ".join("[" + name + ".cl](../../manuals/cl/" + name + ".cl)" for name in row["manuals"]) + ".",
            "- **Contracts:** " + ", ".join("`run " + name + "()`" for name in row["contracts"]) + ".",
            "- **Outcome contracts:** " + (", ".join('`'+name+'`' for name in row.get('outcomeContracts',[])) or 'No outcome binding yet') + ".",
            "- **Dependencies:** " + (", ".join("[" + name + "](../" + name + "/README.md)" for name in row["dependencies"]) or "None statically declared") + ".",
            "- **Owner:** " + row["ownerSurface"] + ".",
            "- **Files:** " + (", ".join("[" + name + "](../../" + name + ")" for name in row["files"]) or "Connector facade; implementation belongs to its dependencies") + ".", ""]
        pages[readme] = "\n".join(content)
        index.append("| [" + row["id"] + "](modules/" + row["id"] + "/README.md) | " + row["purpose"].replace("|", " / ") + " | " + row["manual"] + " |")
    pages[REPO / "MODULES.md"] = "\n".join(index) + "\n"
    return pages

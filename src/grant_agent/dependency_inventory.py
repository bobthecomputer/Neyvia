"""Offline canonical dependency inventory used by updater preflight.

Only checked-in manifests, lockfiles, and policy are consumed.  The builder
never queries a registry, invents a license, or mistakes an archive download
size for an installed-size measurement.
"""

from __future__ import annotations

import ast
import hashlib
import hmac
import json
import os
import re
import stat
import tomllib
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


DEPENDENCY_INVENTORY_SCHEMA = "neyvia.dependency-inventory/v2"
DEPENDENCY_POLICY_SCHEMA = "neyvia.dependency-inventory-policy/v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DEPENDENCY_EVIDENCE_SCHEMA = "neyvia.dependency-license-evidence/v1"


class DependencyInventoryError(ValueError):
    """Inventory input, schema, or release-readiness failure."""


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    value = {key: item for key, item in payload.items() if key != "inventorySha256"}
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise DependencyInventoryError("inventory must be canonical JSON data") from exc
    return (text + "\n").encode("utf-8")


def inventory_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _identity_digest(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _declared(value: object, evidence: str) -> dict[str, Any]:
    return {"status": "declared", "value": value, "evidence": evidence}


def _unresolved(reason: str) -> dict[str, str]:
    return {"status": "unresolved", "blocker": reason}


class DependencyInventory:
    """Build and verify an inventory derived from the exact current inputs."""

    REQUIRED_INPUTS = (
        "package.json",
        "package-lock.json",
        "pyproject.toml",
        "uv.lock",
        "src-tauri/Cargo.toml",
        "src-tauri/Cargo.lock",
        "tools/neyvia-iroh-cache/Cargo.toml",
        "tools/neyvia-iroh-cache/Cargo.lock",
        "config/tool_suite_lock.json",
        "config/neyvia_install_profiles.json",
        "config/neyvia_dependency_inventory_policy.json",
        "config/neyvia_dependency_license_evidence.json",
        "scripts/evidence/FOLLOW-license-desktop-metadata.json",
        "scripts/evidence/FOLLOW-license-cache-metadata.json",
        "scripts/evidence/FOLLOW-license-python-metadata.json",
        "scripts/evidence/FOLLOW-license-python-requirements.txt",
    )

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.policy_path = "config/neyvia_dependency_inventory_policy.json"
        self.profile_path = "config/neyvia_install_profiles.json"
        self.tool_path = "config/tool_suite_lock.json"
        self.evidence_path = "config/neyvia_dependency_license_evidence.json"
        self._input_bytes: dict[str, bytes] = {}

    def build(self) -> dict[str, Any]:
        self._input_bytes = self._snapshot_inputs()
        policy = self._json(self.policy_path)
        self._validate_policy(policy)
        profiles = self._json(self.profile_path)
        tools = self._json(self.tool_path)
        evidence = self._json(self.evidence_path)
        indexes = self._evidence_indexes(evidence)
        records: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []

        package_records, package_edges, tool_tiers = self._install_packages(
            profiles, policy
        )
        records += package_records
        edges += package_edges
        records += self._managed_tools(tools, tool_tiers, policy)

        npm_records, npm_edges = self._npm(
            self._json("package.json"),
            self._json("package-lock.json"),
            policy,
            indexes,
        )
        records += npm_records
        edges += npm_edges
        python_records, python_edges = self._python(
            self._toml("pyproject.toml"),
            self._toml("uv.lock"),
            policy,
            indexes,
        )
        records += python_records
        edges += python_edges
        for arguments in (
            (
                "desktop-rust",
                "desktopRust",
                "src-tauri/Cargo.toml",
                "src-tauri/Cargo.lock",
            ),
            (
                "iroh-cache-rust",
                "irohCacheRust",
                "tools/neyvia-iroh-cache/Cargo.toml",
                "tools/neyvia-iroh-cache/Cargo.lock",
            ),
        ):
            cargo_records, cargo_edges = self._cargo(
                *arguments,
                manifest=self._toml(arguments[2]),
                lock=self._toml(arguments[3]),
                policy=policy,
                evidence=indexes,
            )
            records += cargo_records
            edges += cargo_edges

        records.sort(key=lambda item: item["id"])
        edges = [
            {"from": source, "to": target, "kind": kind}
            for source, target, kind in sorted(
                {(edge["from"], edge["to"], edge["kind"]) for edge in edges}
            )
        ]
        payload: dict[str, Any] = {
            "schema": DEPENDENCY_INVENTORY_SCHEMA,
            "deterministic": True,
            "networkAccess": "not-used",
            "sourceFiles": [
                {
                    "path": relative,
                    "sha256": hashlib.sha256(
                        self._input_bytes[relative]
                    ).hexdigest(),
                }
                for relative in self.REQUIRED_INPUTS
            ],
            "policy": {
                key: policy[key]
                for key in (
                    "criticalClassification",
                    "criticalFields",
                    "installedSizePolicy",
                    "licensePolicy",
                )
            },
            "packages": records,
            "graph": {"directed": True, "edges": edges},
        }
        payload["summary"] = self._summary(records, edges)
        payload["inventorySha256"] = inventory_digest(payload)
        self.validate(payload)
        return payload

    def _evidence_indexes(
        self, evidence: Mapping[str, Any]
    ) -> dict[str, Any]:
        if (
            evidence.get("schema") != DEPENDENCY_EVIDENCE_SCHEMA
            or evidence.get("offlineInventoryInput") is not True
            or evidence.get("target")
            != "windows-x86_64-msvc-python312"
        ):
            raise DependencyInventoryError(
                "dependency license evidence schema or target is invalid"
            )
        workspace: dict[str, Mapping[str, Any]] = {}
        for item in evidence.get("workspaceOverrides") or []:
            record_id = str(item.get("id") or "")
            if (
                not record_id
                or record_id in workspace
                or not item.get("license")
                or not item.get("evidence")
            ):
                raise DependencyInventoryError(
                    "workspace license evidence is invalid or duplicated"
                )
            workspace[record_id] = item

        cargo: dict[str, dict[tuple[str, str, str], Mapping[str, Any]]] = {}
        expected_locks = {
            "desktop-rust": "src-tauri/Cargo.lock",
            "iroh-cache-rust": "tools/neyvia-iroh-cache/Cargo.lock",
        }
        for component in evidence.get("cargo") or []:
            name = str(component.get("component") or "")
            lock_path = expected_locks.get(name)
            if (
                lock_path is None
                or name in cargo
                or component.get("target") != "x86_64-pc-windows-msvc"
                or component.get("lockSha256")
                != self._input_sha256(lock_path)
                or not SHA256_RE.fullmatch(
                    str(component.get("metadataCaptureSha256") or "")
                )
            ):
                raise DependencyInventoryError(
                    "Cargo license evidence is stale, duplicated, or mis-scoped"
                )
            entries: dict[tuple[str, str, str], Mapping[str, Any]] = {}
            for item in component.get("packages") or []:
                key = (
                    str(item.get("name") or ""),
                    str(item.get("version") or ""),
                    str(item.get("source") or ""),
                )
                if (
                    not all(key[:2])
                    or key in entries
                    or not item.get("license")
                ):
                    raise DependencyInventoryError(
                        f"Cargo license evidence identity is invalid: {key}"
                    )
                entries[key] = item
            self._verify_cargo_capture(component, entries)
            cargo[name] = entries
        if set(cargo) != set(expected_locks):
            raise DependencyInventoryError(
                "Cargo license evidence components are incomplete"
            )

        python = evidence.get("python") or {}
        if (
            python.get("target") != "cpython-3.12-windows-x86_64"
            or python.get("uvLockSha256") != self._input_sha256("uv.lock")
            or not SHA256_RE.fullmatch(
                str(python.get("requirementsCaptureSha256") or "")
            )
        ):
            raise DependencyInventoryError(
                "Python license evidence is stale or mis-scoped"
            )
        python_entries: dict[tuple[str, str, str], Mapping[str, Any]] = {}
        for item in python.get("packages") or []:
            key = (
                str(item.get("name") or "").lower().replace("_", "-"),
                str(item.get("version") or ""),
                self._source_identity(item.get("source") or {}),
            )
            if (
                not all(key)
                or key in python_entries
                or not item.get("license")
                or not SHA256_RE.fullmatch(
                    str(item.get("metadataSha256") or "")
                )
            ):
                raise DependencyInventoryError(
                    f"Python license evidence identity is invalid: {key}"
                )
            python_entries[key] = item
        production_python = self._verify_python_capture(python, python_entries)
        return {
            "workspace": workspace,
            "cargo": cargo,
            "python": python_entries,
            "pythonProduction": production_python,
        }

    @staticmethod
    def _target_requirements(raw):
        """Project a locked export for the declared Windows CPython 3.12 target.

        Evaluate a restricted expression tree, never Python eval. Unknown target
        facts or marker syntax fail closed instead of guessing a dependency.
        """
        facts = {"python_version": "3.12", "python_full_version": "3.12.11", "implementation_name": "cpython",
                 "platform_python_implementation": "CPython", "sys_platform": "win32", "os_name": "nt",
                 "platform_system": "Windows", "platform_machine": "AMD64", "extra": ""}
        def evaluate(node):
            if isinstance(node, ast.Name) and node.id in facts:
                return facts[node.id]
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
                values = [evaluate(item) for item in node.values]
                return all(values) if isinstance(node.op, ast.And) else any(values)
            if isinstance(node, ast.Compare) and len(node.ops) == 1:
                left, right = evaluate(node.left), evaluate(node.comparators[0])
                op = node.ops[0]
                if isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
                    if any(isinstance(item, ast.Name) and item.id in {"python_version", "python_full_version"}
                           for item in (node.left, node.comparators[0])):
                        if not all(re.fullmatch(r"\d+(?:\.\d+)*", value) for value in (left, right)):
                            raise DependencyInventoryError("Unsupported target version marker")
                        left, right = tuple(map(int, left.split('.'))), tuple(map(int, right.split('.')))
                    return left < right if isinstance(op, ast.Lt) else left <= right if isinstance(op, ast.LtE) else left > right if isinstance(op, ast.Gt) else left >= right
                if isinstance(op, ast.Eq): return left == right
                if isinstance(op, ast.NotEq): return left != right
                if isinstance(op, ast.In): return left in right
                if isinstance(op, ast.NotIn): return left not in right
            raise DependencyInventoryError("Unsupported target requirement marker; refresh its supported projection")
        selected = set()
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith('#') or line == '.':
                continue
            match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)(?:\s*;\s*(.+))?", line)
            if not match:
                raise DependencyInventoryError("Target requirement export is not fully pinned")
            try:
                included = not match[3] or evaluate(ast.parse(match[3], mode="eval").body)
            except SyntaxError as exc:
                raise DependencyInventoryError("Unsupported target requirement marker") from exc
            if included:
                selected.add((match[1].lower().replace('_', '-'), match[2]))
        return selected

    def _verify_python_capture(self, component, entries):
        capture_path = "scripts/evidence/FOLLOW-license-python-metadata.json"
        requirements_path = "scripts/evidence/FOLLOW-license-python-requirements.txt"
        if (component.get("metadataCapturePath") != capture_path
                or component.get("metadataCaptureSha256") != self._input_sha256(capture_path)
                or component.get("requirementsCapturePath") != requirements_path
                or component.get("requirementsCaptureSha256") != self._input_sha256(requirements_path)
                or component.get("pyprojectSha256") != self._input_sha256("pyproject.toml")):
            raise DependencyInventoryError("Python metadata capture is stale, tampered, or mis-scoped")
        capture = self._json(capture_path)
        if (capture.get("schema") != "neyvia.python-license-capture/v1" or capture.get("target") != component["target"]
                or capture.get("uvLockSha256") != component["uvLockSha256"]
                or capture.get("pyprojectSha256") != component["pyprojectSha256"]):
            raise DependencyInventoryError("Python metadata capture scope is invalid")
        raw = str(capture.get("rawLockedExport") or "")
        if hashlib.sha256(raw.encode()).hexdigest() != capture.get("rawLockedExportSha256"):
            raise DependencyInventoryError("Python locked export capture hash differs")
        selected = self._target_requirements(raw)
        projection = self._target_requirements(self._input_bytes[requirements_path].decode("utf-8"))
        if not selected or selected != projection:
            raise DependencyInventoryError("Python target projection differs from its raw locked export")
        from email.parser import Parser
        declarations = {}
        locked = {(item["name"], item["version"]): item for item in self._toml("uv.lock")["package"]}
        for item in capture.get("packages") or []:
            name, version = item.get("name"), item.get("version")
            key = (name, version, self._source_identity(item.get("source") or {}))
            metadata = str(item.get("metadata") or "")
            parsed = Parser().parsestr(metadata)
            if (key in declarations or hashlib.sha256(metadata.encode()).hexdigest() != item.get("metadataSha256")
                    or str(parsed["Name"]).lower().replace('_', '-') != name or parsed["Version"] != version
                    or (name, version) not in locked
                    or item.get("source") != locked[(name, version)].get("source")
                    or "sha256:" + str(item.get("wheelSha256")) not in {wheel["hash"] for wheel in locked[(name, version)].get("wheels", [])}):
                raise DependencyInventoryError("Python metadata identity or pinned artifact is invalid")
            tags = re.findall(r"(?m)^Tag: ([^\r\n]+)", str(item.get("wheelMetadata") or ""))
            def compatible(tag):
                parts = tag.split('-')
                if len(parts) != 3:
                    return False
                interpreter, abi, platform = parts
                if platform not in {"win_amd64", "any"}:
                    return False
                if abi == "none":
                    return interpreter in {"py3", "py312", "cp312"}
                if abi == "cp312":
                    return interpreter == "cp312" and platform == "win_amd64"
                return abi == "abi3" and bool(re.fullmatch(r"cp3\d+", interpreter)) and int(interpreter[2:]) <= 312 and platform == "win_amd64"
            if not any(compatible(tag) for tag in tags):
                raise DependencyInventoryError("Python captured wheel is not compatible with the Windows CP312 target")
            expression, text = parsed.get("License-Expression"), parsed.get("License")
            classifiers = sorted(value for value in parsed.get_all("Classifier", []) if value.startswith("License ::"))
            license_value = {"expression": expression} if expression else {"declaredText": text.strip()} if text and text.strip() not in {"", "UNKNOWN"} and len(text) <= 200 else {"classifiers": classifiers} if classifiers else None
            declarations[key] = (license_value, item["metadataSha256"])
        if ({key[:2] for key in declarations} != selected or set(declarations) != set(entries)
                or any(entries[key]["license"] != value[0] or entries[key]["metadataSha256"] != value[1]
                       for key, value in declarations.items())):
            raise DependencyInventoryError("Python license evidence differs from its selected metadata capture")
        return set(declarations)

    def _verify_cargo_capture(self, component, entries) -> None:
        """Admit target-selected declarations only from the bound actual capture."""
        scope = {
            "desktop-rust": ("scripts/evidence/FOLLOW-license-desktop-metadata.json", "src-tauri/Cargo.toml"),
            "iroh-cache-rust": ("scripts/evidence/FOLLOW-license-cache-metadata.json", "tools/neyvia-iroh-cache/Cargo.toml"),
        }
        capture_path, manifest_path = scope[component["component"]]
        if (component.get("metadataCapturePath") != capture_path
                or component["metadataCaptureSha256"] != self._input_sha256(capture_path)):
            raise DependencyInventoryError("Cargo metadata capture is stale, tampered, or mis-scoped")
        capture = self._json(capture_path)
        packages = capture.get("packages")
        resolve = capture.get("resolve") or {}
        if capture.get("version") != 1 or not isinstance(packages, list) or not packages:
            raise DependencyInventoryError("Cargo metadata capture is incomplete")
        declarations = {}
        ids = set()
        for package in packages:
            key = (str(package.get("name") or ""), str(package.get("version") or ""),
                   str(package.get("source") or ""))
            if key in declarations or not package.get("license") or not package.get("id"):
                raise DependencyInventoryError("Cargo metadata capture has invalid or duplicated identities")
            declarations[key] = package["license"]
            ids.add(package["id"])
        if (len(ids) != len(packages) or resolve.get("root") not in ids
                or {node.get("id") for node in resolve.get("nodes") or []} != ids):
            raise DependencyInventoryError("Cargo metadata capture resolution is incomplete")
        root = next(package for package in packages if package["id"] == resolve["root"])
        manifest = self._toml(manifest_path)["package"]
        if (root.get("source") or root["name"] != manifest["name"]
                or root["version"] != manifest["version"]):
            raise DependencyInventoryError("Cargo metadata capture workspace is mis-scoped")
        if set(declarations) != set(entries) or any(
                entries[key]["license"] != license_value for key, license_value in declarations.items()):
            raise DependencyInventoryError("Cargo license evidence differs from its bound metadata capture")

    def _record(
        self,
        *,
        record_id: str,
        kind: str,
        name: str,
        classification: str,
        ownership: Mapping[str, str],
        owner_evidence: str,
        source: Mapping[str, Any],
        version: object,
        license_value: object,
        license_evidence: str,
        release_scope: str,
        installed_size: object = None,
        installed_size_evidence: str = "",
        integrity: object = None,
        declared_gaps: Iterable[str] = (),
    ) -> dict[str, Any]:
        critical = classification == "core" and release_scope == "bundled-artifact"
        owner = (
            _declared(ownership["owner"], owner_evidence)
            if ownership.get("owner")
            else _unresolved("Dependency owner is not declared in policy.")
        )
        responsibility = (
            _declared(ownership["updateResponsibility"], owner_evidence)
            if ownership.get("updateResponsibility")
            else _unresolved("Update responsibility is not declared in policy.")
        )
        license_state = (
            _declared(license_value, license_evidence)
            if license_value
            else _unresolved(
                "No explicit local license declaration exists; pinned SBOM evidence is required."
            )
        )
        size_state = (
            _declared(installed_size, installed_size_evidence)
            if type(installed_size) is int and installed_size >= 0
            else _unresolved("No checked-in installed-size measurement exists.")
        )
        fields = {
            "owner": owner,
            "license": license_state,
            "updateResponsibility": responsibility,
        }
        blockers = [
            {"field": field, "reason": value["blocker"]}
            for field, value in fields.items()
            if critical and value["status"] == "unresolved"
        ]
        return {
            "id": record_id,
            "kind": kind,
            "name": name,
            "classification": classification,
            "releaseScope": release_scope,
            "critical": critical,
            "owner": owner,
            "license": license_state,
            "updateResponsibility": responsibility,
            "source": dict(source),
            "version": version,
            "integrity": integrity,
            "installedSizeBytes": size_state,
            "blockers": blockers,
            "declaredGaps": sorted({str(item) for item in declared_gaps if item}),
        }

    def _install_packages(
        self, profiles: Mapping[str, Any], policy: Mapping[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, set[str]]]:
        ownership = policy["ownership"]["installPackages"]
        package_ids = {
            str(item["packageId"]) for item in profiles.get("packages") or []
        }
        records: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []
        tool_tiers: dict[str, set[str]] = defaultdict(set)
        for item in profiles.get("packages") or []:
            package_id = str(item["packageId"])
            records.append(
                self._record(
                    record_id=package_id,
                    kind="neyvia-install-package",
                    name=str(item.get("name") or package_id),
                    classification=str(item["tier"]),
                    ownership=ownership,
                    owner_evidence=f"{self.policy_path} ownership.installPackages",
                    source={
                        "input": self.profile_path,
                        "locator": f"packages[{package_id}]",
                    },
                    version=item.get("version"),
                    license_value=item.get("license"),
                    license_evidence=f"{self.profile_path} packages[{package_id}].license",
                    release_scope="logical-install-package",
                    installed_size=item.get("installedSizeBytes"),
                    installed_size_evidence=(
                        f"{self.profile_path} packages[{package_id}].installedSizeBytes"
                    ),
                    integrity={
                        "algorithm": "sha256",
                        "value": self._input_sha256(self.profile_path),
                        "scope": "registry-input",
                    },
                    declared_gaps=[item.get("gap")],
                )
            )
            for dependency in item.get("dependsOn") or []:
                if dependency not in package_ids:
                    raise DependencyInventoryError(
                        f"{package_id} depends on unknown package {dependency}"
                    )
                edges.append(
                    {
                        "from": package_id,
                        "to": dependency,
                        "kind": "install-depends-on",
                    }
                )
            for tool_id in item.get("toolIds") or []:
                tool_tiers[str(tool_id)].add(str(item["tier"]))
                edges.append(
                    {
                        "from": package_id,
                        "to": str(tool_id),
                        "kind": "uses-managed-tool",
                    }
                )
        return records, edges, tool_tiers

    def _managed_tools(
        self,
        lock: Mapping[str, Any],
        tiers: Mapping[str, set[str]],
        policy: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        ownership = policy["ownership"]["managedTools"]
        records = []
        for item in lock.get("tools") or []:
            tool_id = str(item["toolId"])
            digest = item.get("packageSha256")
            records.append(
                self._record(
                    record_id=tool_id,
                    kind="managed-tool",
                    name=str(item.get("name") or tool_id),
                    classification="core" if "core" in tiers.get(tool_id, set()) else "optional",
                    ownership=ownership,
                    owner_evidence=f"{self.policy_path} ownership.managedTools",
                    source={
                        "input": self.tool_path,
                        "locator": f"tools[{tool_id}]",
                        **(
                            {"upstream": item["upstream"]}
                            if item.get("upstream")
                            else {}
                        ),
                    },
                    version=item.get("selectedVersion"),
                    license_value=item.get("license"),
                    license_evidence=f"{self.tool_path} tools[{tool_id}].license",
                    release_scope="externally-managed-tool",
                    installed_size=item.get("installedSizeBytes"),
                    installed_size_evidence=(
                        f"{self.tool_path} tools[{tool_id}].installedSizeBytes"
                    ),
                    integrity=(
                        {"algorithm": "sha256", "value": digest}
                        if isinstance(digest, str) and SHA256_RE.fullmatch(digest)
                        else None
                    ),
                )
            )
        return records

    def _npm(
        self,
        package_json: Mapping[str, Any],
        lock: Mapping[str, Any],
        policy: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        packages = lock.get("packages")
        if lock.get("lockfileVersion") != 3 or not isinstance(packages, dict):
            raise DependencyInventoryError("package-lock.json must use version 3")
        ownership = policy["ownership"]["npm"]
        root_name = str(package_json.get("name") or lock.get("name") or "workspace")
        path_to_id: dict[str, str] = {}
        path_to_record: dict[str, dict[str, Any]] = {}
        records = []
        workspace_license = evidence["workspace"].get("npm:workspace")
        for path, item in sorted(packages.items()):
            name = root_name if path == "" else self._npm_name(path)
            version = item.get("version") or (lock.get("version") if path == "" else None)
            record_id = (
                "npm:workspace"
                if path == ""
                else f"npm:{name}@{version}#{_identity_digest(path)}"
            )
            path_to_id[path] = record_id
            development = bool(item.get("dev"))
            record = self._record(
                    record_id=record_id,
                    kind="npm-workspace" if path == "" else "npm-lock-package",
                    name=name,
                    classification=policy["classification"][
                        "npmDevelopment" if development else "npmProduction"
                    ],
                    ownership=ownership,
                    owner_evidence=f"{self.policy_path} ownership.npm",
                    source={
                        "input": "package-lock.json",
                        "locator": f"packages[{path!r}]",
                        **({"resolved": item["resolved"]} if item.get("resolved") else {}),
                    },
                    version=version,
                    license_value=(
                        workspace_license["license"]
                        if path == "" and workspace_license
                        else package_json.get("license")
                        if path == ""
                        else item.get("license")
                    ),
                    license_evidence=(
                        f"{self.evidence_path} workspaceOverrides[npm:workspace]"
                        if path == "" and workspace_license
                        else "package.json license"
                        if path == ""
                        else f"package-lock.json packages[{path!r}].license"
                    ),
                    release_scope="bundled-artifact",
                    integrity=(
                        {"algorithm": "npm-integrity", "value": item["integrity"]}
                        if item.get("integrity")
                        else {
                            "algorithm": "sha256",
                            "value": self._input_sha256("package-lock.json"),
                            "scope": "workspace-lockfile",
                        }
                        if path == ""
                        else None
                    ),
                )
            records.append(record)
            path_to_record[path] = record
        edges = []
        for path, item in sorted(packages.items()):
            for group in ("dependencies", "optionalDependencies", "peerDependencies"):
                for name in sorted((item.get(group) or {}).keys()):
                    target = self._resolve_npm(path, name, packages)
                    if target is None:
                        peer_meta = item.get("peerDependenciesMeta") or {}
                        if (
                            (
                                group == "peerDependencies"
                                and (peer_meta.get(name) or {}).get("optional") is True
                            )
                            or item.get("optional") is True
                        ):
                            path_to_record[path]["declaredGaps"].append(
                                f"optional dependency not installed: {name}"
                            )
                            path_to_record[path]["declaredGaps"].sort()
                            continue
                        raise DependencyInventoryError(
                            f"npm dependency edge cannot be resolved: {path!r} -> {name}"
                        )
                    edges.append(
                        {
                            "from": path_to_id[path],
                            "to": path_to_id[target],
                            "kind": f"npm-{group}",
                        }
                    )
        return records, edges

    @staticmethod
    def _npm_name(path: str) -> str:
        parts = path.rsplit("node_modules/", 1)[-1].split("/")
        return "/".join(parts[:2]) if parts[0].startswith("@") else parts[0]

    @staticmethod
    def _resolve_npm(
        parent: str, name: str, packages: Mapping[str, Any]
    ) -> str | None:
        parts = list(PurePosixPath(parent).parts)
        candidates = []
        while parts:
            candidates.append(str(PurePosixPath(*parts) / "node_modules" / name))
            if "node_modules" not in parts:
                break
            parts = parts[: len(parts) - 1 - parts[::-1].index("node_modules")]
        candidates.append(f"node_modules/{name}")
        return next((candidate for candidate in candidates if candidate in packages), None)

    def _python(
        self,
        project: Mapping[str, Any],
        lock: Mapping[str, Any],
        policy: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        packages = lock.get("package")
        if lock.get("version") != 1 or not isinstance(packages, list):
            raise DependencyInventoryError("uv.lock must use version 1")
        ownership = policy["ownership"]["python"]
        root_name = str(project["project"]["name"]).lower()
        keys: dict[tuple[str, str, str], str] = {}
        by_name: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        unused_evidence = set(evidence["python"])
        records = []
        for item in sorted(
            packages,
            key=lambda value: (
                value["name"],
                value.get("version", ""),
                self._source_identity(value.get("source") or {}),
            ),
        ):
            name = str(item["name"]).lower().replace("_", "-")
            version = str(item.get("version") or "")
            source_identity = self._source_identity(item.get("source") or {})
            key = (name, version, source_identity)
            record_id = (
                f"pypi:{name}@{version}#{_identity_digest(item.get('source') or {})}"
            )
            keys[key] = record_id
            by_name[name].append(key)
            is_root = name == root_name
            license_entry = evidence["python"].get(key)
            if license_entry:
                unused_evidence.discard(key)
            hashes = sorted(
                {
                    str(artifact["hash"])
                    for artifact in [item.get("sdist"), *(item.get("wheels") or [])]
                    if isinstance(artifact, dict) and artifact.get("hash")
                }
            )
            artifact_digest = (
                hashlib.sha256(
                    ("\n".join(hashes) + "\n").encode("utf-8")
                ).hexdigest()
                if hashes
                else None
            )
            records.append(
                self._record(
                    record_id=record_id,
                    kind="python-workspace" if is_root else "uv-lock-package",
                    name=name,
                    classification=policy["classification"][
                        "pythonProduction"
                        if is_root or key in evidence["pythonProduction"]
                        else "pythonDevelopment"
                    ],
                    ownership=ownership,
                    owner_evidence=f"{self.policy_path} ownership.python",
                    source={
                        "input": "uv.lock",
                        "locator": f"package[{name}]",
                        "lockedSource": item.get("source") or {},
                    },
                    version=version,
                    license_value=(
                        self._license_text(project["project"].get("license"))
                        if is_root
                        else license_entry.get("license")
                        if license_entry
                        else item.get("license")
                    ),
                    license_evidence=(
                        "pyproject.toml project.license"
                        if is_root
                        else f"{self.evidence_path} python.packages[{name}@{version}]"
                        if license_entry
                        else f"uv.lock package[{name}].license"
                    ),
                    release_scope="bundled-artifact",
                    integrity=(
                        {
                            "algorithm": "sha256",
                            "value": artifact_digest,
                            "scope": "canonical-locked-artifact-hash-set",
                            "artifactCount": len(hashes),
                        }
                        if artifact_digest
                        else {
                            "algorithm": "sha256",
                            "value": self._input_sha256("uv.lock"),
                            "scope": "workspace-lockfile",
                        }
                        if is_root
                        else None
                    ),
                )
            )
        if unused_evidence:
            raise DependencyInventoryError(
                "Python license evidence contains identities absent from uv.lock"
            )
        edges = []
        for item in packages:
            source_key = (
                str(item["name"]).lower().replace("_", "-"),
                str(item.get("version") or ""),
                self._source_identity(item.get("source") or {}),
            )
            dependency_groups = [item.get("dependencies") or []]
            dependency_groups += list((item.get("dev-dependencies") or {}).values())
            for dependencies in dependency_groups:
                for dependency in dependencies:
                    target_key = self._resolve_python_dependency(
                        dependency, by_name
                    )
                    edges.append(
                        {
                            "from": keys[source_key],
                            "to": keys[target_key],
                            "kind": "python-dependency",
                        }
                    )
        return records, edges

    @staticmethod
    def _resolve_python_dependency(
        dependency: Mapping[str, Any],
        by_name: Mapping[str, list[tuple[str, str, str]]],
    ) -> tuple[str, str, str]:
        name = str(dependency.get("name") or "").lower().replace("_", "-")
        candidates = list(by_name.get(name) or [])
        if dependency.get("version"):
            candidates = [
                item
                for item in candidates
                if item[1] == str(dependency["version"])
            ]
        if dependency.get("source"):
            source = DependencyInventory._source_identity(
                dependency["source"]
            )
            candidates = [item for item in candidates if item[2] == source]
        if len(candidates) != 1:
            raise DependencyInventoryError(
                f"Python dependency edge is ambiguous or unresolved: {dict(dependency)}"
            )
        return candidates[0]

    def _cargo(
        self,
        ecosystem: str,
        ownership_key: str,
        manifest_path: str,
        lock_path: str,
        *,
        manifest: Mapping[str, Any],
        lock: Mapping[str, Any],
        policy: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        packages = lock.get("package")
        if lock.get("version") not in {3, 4} or not isinstance(packages, list):
            raise DependencyInventoryError(f"{lock_path} has an unsupported format")
        ownership = policy["ownership"][ownership_key]
        root_name = str(manifest["package"]["name"])
        license_entries = evidence["cargo"][ecosystem]
        unused_evidence = set(license_entries)
        keys: dict[tuple[str, str, str], str] = {}
        by_name: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        records = []
        for item in sorted(
            packages,
            key=lambda value: (value["name"], value["version"], str(value.get("source") or "")),
        ):
            name, version = str(item["name"]), str(item["version"])
            source = str(item.get("source") or "")
            key = (name, version, source)
            suffix = _identity_digest(source) if source else "workspace"
            record_id = f"cargo:{ecosystem}:{name}@{version}#{suffix}"
            keys[key] = record_id
            by_name[name].append(key)
            is_root = name == root_name and not source
            license_entry = license_entries.get(key)
            if license_entry:
                unused_evidence.discard(key)
                if license_entry.get("checksum") != item.get("checksum"):
                    raise DependencyInventoryError(
                        f"Cargo license evidence checksum mismatch: {key}"
                    )
            records.append(
                self._record(
                    record_id=record_id,
                    kind="cargo-workspace" if is_root else "cargo-lock-package",
                    name=name,
                    classification=(
                        policy["classification"]["desktopRust"]
                        if ecosystem == "desktop-rust" and license_entry
                        else "optional"
                    ),
                    ownership=ownership,
                    owner_evidence=f"{self.policy_path} ownership.{ownership_key}",
                    source={
                        "input": lock_path,
                        "locator": f"package[{name}@{version}]",
                        **({"registry": source} if source else {"workspace": manifest_path}),
                    },
                    version=version,
                    license_value=(
                        license_entry.get("license")
                        if license_entry
                        else manifest["package"].get("license")
                        if is_root
                        else item.get("license")
                    ),
                    license_evidence=(
                        f"{self.evidence_path} cargo[{ecosystem}].packages[{name}@{version}]"
                        if license_entry
                        else f"{manifest_path} package.license"
                        if is_root
                        else f"{lock_path} package[{name}@{version}].license"
                    ),
                    release_scope=(
                        "bundled-artifact"
                        if ecosystem == "desktop-rust"
                        else "optional-pack-artifact"
                    ),
                    integrity=(
                        {"algorithm": "sha256", "value": item["checksum"]}
                        if item.get("checksum")
                        else {
                            "algorithm": "sha256",
                            "value": self._input_sha256(lock_path),
                            "scope": "workspace-lockfile",
                        }
                        if is_root
                        else None
                    ),
                )
            )
        if unused_evidence:
            raise DependencyInventoryError(
                f"Cargo license evidence contains identities absent from {lock_path}"
            )
        edges = []
        for item in packages:
            source_key = (
                str(item["name"]),
                str(item["version"]),
                str(item.get("source") or ""),
            )
            for raw in item.get("dependencies") or []:
                target_key = self._resolve_cargo_dependency(raw, by_name)
                edges.append(
                    {
                        "from": keys[source_key],
                        "to": keys[target_key],
                        "kind": "cargo-dependency",
                    }
                )
        return records, edges

    @staticmethod
    def _resolve_cargo_dependency(
        raw: object,
        by_name: Mapping[str, list[tuple[str, str, str]]],
    ) -> tuple[str, str, str]:
        match = re.fullmatch(
            r"(\S+)(?:\s+([^\s(]+))?(?:\s+\((.+)\))?",
            str(raw),
        )
        if not match:
            raise DependencyInventoryError(
                f"Cargo dependency edge syntax is invalid: {raw}"
            )
        name, version, dependency_source = match.groups()
        candidates = list(by_name.get(name) or [])
        if version:
            candidates = [
                candidate for candidate in candidates if candidate[1] == version
            ]
        if dependency_source:
            candidates = [
                candidate
                for candidate in candidates
                if candidate[2] == dependency_source
            ]
        if len(candidates) != 1:
            raise DependencyInventoryError(
                f"Cargo dependency edge is ambiguous or unresolved: {raw}"
            )
        return candidates[0]

    @staticmethod
    def _license_text(value: Any) -> Any:
        return value.get("text") if isinstance(value, dict) else value

    @staticmethod
    def _summary(
        records: list[dict[str, Any]], edges: list[dict[str, str]]
    ) -> dict[str, Any]:
        blockers = [
            {"id": item["id"], **blocker}
            for item in records
            for blocker in item["blockers"]
        ]
        return {
            "records": len(records),
            "edges": len(edges),
            "classification": dict(
                sorted(Counter(item["classification"] for item in records).items())
            ),
            "kinds": dict(sorted(Counter(item["kind"] for item in records).items())),
            "criticalRecords": sum(item["critical"] for item in records),
            "criticalBlockers": blockers,
            "updaterPreflightEligible": not blockers,
            "measuredInstalledSizes": sum(
                item["installedSizeBytes"]["status"] == "declared" for item in records
            ),
        }

    @classmethod
    def validate(cls, payload: Mapping[str, Any]) -> None:
        if payload.get("schema") != DEPENDENCY_INVENTORY_SCHEMA:
            raise DependencyInventoryError("unsupported dependency inventory schema")
        sources = payload.get("sourceFiles")
        if not isinstance(sources, list) or not sources:
            raise DependencyInventoryError("sourceFiles must be a non-empty list")
        paths: set[str] = set()
        for source in sources:
            if not isinstance(source, dict) or set(source) != {"path", "sha256"}:
                raise DependencyInventoryError("source file record is malformed")
            path = str(source["path"])
            pure = PurePosixPath(path)
            if (
                pure.is_absolute()
                or not pure.parts
                or any(part in {"", ".", ".."} for part in pure.parts)
                or "\\" in path
                or path in paths
                or not SHA256_RE.fullmatch(str(source["sha256"]))
            ):
                raise DependencyInventoryError("source file path or digest is invalid")
            paths.add(path)
        if set(cls.REQUIRED_INPUTS) - paths:
            raise DependencyInventoryError("required source inputs are missing")

        packages = payload.get("packages")
        if not isinstance(packages, list) or not packages:
            raise DependencyInventoryError("packages must be a non-empty list")
        required = {
            "id",
            "kind",
            "name",
            "classification",
            "releaseScope",
            "critical",
            "owner",
            "license",
            "updateResponsibility",
            "source",
            "version",
            "integrity",
            "installedSizeBytes",
            "blockers",
            "declaredGaps",
        }
        ids: set[str] = set()
        for item in packages:
            if not isinstance(item, dict) or set(item) != required:
                raise DependencyInventoryError("dependency record fields are invalid")
            if not item["id"] or item["id"] in ids:
                raise DependencyInventoryError("dependency ids must be unique")
            ids.add(item["id"])
            if item["classification"] not in {"core", "optional"}:
                raise DependencyInventoryError("dependency classification is invalid")
            expected_critical = (
                item["classification"] == "core"
                and item["releaseScope"] == "bundled-artifact"
            )
            if item["releaseScope"] not in {
                "bundled-artifact",
                "logical-install-package",
                "externally-managed-tool",
                "optional-pack-artifact",
            }:
                raise DependencyInventoryError("dependency release scope is invalid")
            if item["critical"] is not expected_critical:
                raise DependencyInventoryError("dependency criticality is inconsistent")
            for field in ("owner", "license", "updateResponsibility", "installedSizeBytes"):
                state = item[field]
                if not isinstance(state, dict) or state.get("status") not in {
                    "declared",
                    "unresolved",
                }:
                    raise DependencyInventoryError(f"{item['id']}.{field} is invalid")
                if state["status"] == "unresolved" and not state.get("blocker"):
                    raise DependencyInventoryError(
                        f"{item['id']}.{field} requires an explicit blocker"
                    )
        edges = (payload.get("graph") or {}).get("edges")
        if not isinstance(edges, list) or any(
            not isinstance(edge, dict)
            or set(edge) != {"from", "to", "kind"}
            or edge["from"] not in ids
            or edge["to"] not in ids
            for edge in edges
        ):
            raise DependencyInventoryError("dependency graph contains an invalid edge")
        if not hmac.compare_digest(
            str(payload.get("inventorySha256") or ""), inventory_digest(payload)
        ):
            raise DependencyInventoryError("canonical inventory digest does not match")
        blockers = (payload.get("summary") or {}).get("criticalBlockers")
        if not isinstance(blockers, list) or payload["summary"].get(
            "updaterPreflightEligible"
        ) is not (not blockers):
            raise DependencyInventoryError("inventory summary is inconsistent")

    def verify_written(
        self, path: str | Path, *, require_critical_resolved: bool = False
    ) -> dict[str, Any]:
        destination = Path(path)
        if not destination.is_absolute():
            destination = self.root / destination
        try:
            raw = destination.read_bytes()
            written = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DependencyInventoryError(
                f"dependency inventory is missing or unreadable: {destination}"
            ) from exc
        self.validate(written)
        rebuilt = self.build()
        expected = self._rendered_bytes(rebuilt)
        if raw != expected:
            raise DependencyInventoryError(
                "dependency inventory is stale, hand-edited, or not the literal canonical rendering for current inputs"
            )
        blockers = rebuilt["summary"]["criticalBlockers"]
        if require_critical_resolved and blockers:
            sample = ", ".join(
                f"{item['id']}.{item['field']}" for item in blockers[:8]
            )
            more = f" (+{len(blockers) - 8} more)" if len(blockers) > 8 else ""
            raise DependencyInventoryError(
                f"critical dependency ownership/license policy is unresolved: {sample}{more}"
            )
        return rebuilt

    def recheck_sources(self, inventory: Mapping[str, Any]) -> str:
        """Re-read every non-reparse input and require the bound hashes."""

        self.validate(inventory)
        current = self._snapshot_inputs()
        expected = {
            str(item["path"]): str(item["sha256"])
            for item in inventory["sourceFiles"]
        }
        actual = {
            path: hashlib.sha256(value).hexdigest()
            for path, value in current.items()
        }
        if actual != expected:
            raise DependencyInventoryError(
                "dependency input changed after inventory preflight"
            )
        return str(inventory["inventorySha256"])

    def write(self, output: str | Path) -> Path:
        destination = Path(output)
        if not destination.is_absolute():
            destination = self.root / destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self._rendered_bytes(self.build()))
        return destination

    def proof_receipt(self, inventory: Mapping[str, Any]) -> dict[str, Any]:
        self.validate(inventory)
        summary = inventory["summary"]
        return {
            "schema": "neyvia.dependency-inventory-proof/v1",
            "inventorySchema": inventory["schema"],
            "inventorySha256": inventory["inventorySha256"],
            "networkAccess": inventory["networkAccess"],
            "sourceFiles": list(inventory["sourceFiles"]),
            "records": summary["records"],
            "edges": summary["edges"],
            "criticalRecords": summary["criticalRecords"],
            "criticalBlockerCount": len(summary["criticalBlockers"]),
            "criticalBlockerSample": summary["criticalBlockers"][:20],
            "updaterPreflightEligible": summary["updaterPreflightEligible"],
        }

    @staticmethod
    def _rendered_bytes(payload: Mapping[str, Any]) -> bytes:
        return (
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
            + "\n"
        ).encode("utf-8")

    def _snapshot_inputs(self) -> dict[str, bytes]:
        snapshots: dict[str, bytes] = {}
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        for relative in self.REQUIRED_INPUTS:
            path = self.root / relative
            try:
                before = os.lstat(path)
            except OSError as exc:
                raise DependencyInventoryError(
                    f"required dependency input is missing: {relative}"
                ) from exc
            if (
                stat.S_ISLNK(before.st_mode)
                or not stat.S_ISREG(before.st_mode)
                or bool(getattr(before, "st_file_attributes", 0) & reparse_flag)
            ):
                raise DependencyInventoryError(
                    f"dependency input must be a regular non-reparse file: {relative}"
                )
            data = path.read_bytes()
            after = os.lstat(path)
            before_identity = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            )
            after_identity = (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
            if before_identity != after_identity or len(data) != after.st_size:
                raise DependencyInventoryError(
                    f"dependency input changed while being snapshotted: {relative}"
                )
            snapshots[relative] = data
        return snapshots

    def _input_sha256(self, relative: str) -> str:
        try:
            value = self._input_bytes[relative]
        except KeyError as exc:
            raise DependencyInventoryError(
                f"dependency input was not snapshotted: {relative}"
            ) from exc
        return hashlib.sha256(value).hexdigest()

    @staticmethod
    def _validate_policy(policy: Mapping[str, Any]) -> None:
        owners = {
            "installPackages",
            "npm",
            "python",
            "desktopRust",
            "irohCacheRust",
            "managedTools",
        }
        classes = {
            "npmProduction",
            "npmDevelopment",
            "pythonProduction",
            "pythonDevelopment",
            "desktopRust",
            "irohCacheRust",
        }
        if policy.get("schema") != DEPENDENCY_POLICY_SCHEMA:
            raise DependencyInventoryError("unsupported dependency inventory policy")
        if set(policy.get("ownership") or {}) != owners or any(
            set(value) != {"owner", "updateResponsibility"}
            or not all(str(item).strip() for item in value.values())
            for value in policy["ownership"].values()
        ):
            raise DependencyInventoryError("dependency ownership policy is incomplete")
        if set(policy.get("classification") or {}) != classes or any(
            value not in {"core", "optional"}
            for value in policy["classification"].values()
        ):
            raise DependencyInventoryError("dependency classification policy is invalid")
        if (
            policy.get("criticalFields")
            != ["owner", "license", "updateResponsibility"]
            or policy.get("criticalClassification") != "core"
            or not str(policy.get("installedSizePolicy") or "").strip()
            or not str(policy.get("licensePolicy") or "").strip()
        ):
            raise DependencyInventoryError("dependency critical-field policy is invalid")

    def _json(self, relative: str) -> dict[str, Any]:
        try:
            value = json.loads(self._input_bytes[relative].decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DependencyInventoryError(f"cannot parse {relative}") from exc
        if not isinstance(value, dict):
            raise DependencyInventoryError(f"{relative} must contain an object")
        return value

    def _toml(self, relative: str) -> dict[str, Any]:
        try:
            return tomllib.loads(self._input_bytes[relative].decode("utf-8"))
        except (KeyError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise DependencyInventoryError(f"cannot parse {relative}") from exc

    @staticmethod
    def _source_identity(value: object) -> str:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

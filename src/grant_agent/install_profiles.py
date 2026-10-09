"""Truthful core/optional installation composition for Neyvia.

The registry decides what belongs in the thin core and what remains an
operator-selected capability pack. It resolves dependency closure and reports
implementation gaps. It deliberately does not install anything: execution must
sit behind signature, hash, permission, compatibility, and rollback gates.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


INSTALL_PROFILES_SCHEMA = "neyvia.install-profiles/v1"
INSTALL_PLAN_SCHEMA = "neyvia.install-plan/v1"
PACKAGE_TIERS = frozenset({"core", "optional"})
DELIVERY_STATES = frozenset(
    {"bundled", "verified", "foundation", "planned", "blocked"}
)
INSTALL_MODES = frozenset({"bundled", "managed", "service", "remote"})
RESOURCE_CLASSES = frozenset({"light", "medium", "heavy"})
READY_STATES = frozenset({"bundled", "verified"})


class InstallProfileRegistry:
    """Load, validate, summarize, and resolve Neyvia installation profiles."""

    def __init__(
        self,
        root: str | Path,
        *,
        registry_path: str | Path | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        selected = Path(
            registry_path
            or self.root / "config" / "neyvia_install_profiles.json"
        )
        if not selected.is_file():
            selected = (
                Path(__file__).resolve().parents[2]
                / "config"
                / "neyvia_install_profiles.json"
            )
        self.registry_path = selected.resolve()
        self.payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self._validate()
        self.packages = {
            item["packageId"]: dict(item) for item in self.payload["packages"]
        }
        self.profiles = {
            item["profileId"]: dict(item) for item in self.payload["profiles"]
        }

    def _validate(self) -> None:
        payload = self.payload
        errors: list[str] = []
        if not isinstance(payload, dict):
            raise ValueError("Install profile registry must be a JSON object")
        if payload.get("schema") != INSTALL_PROFILES_SCHEMA:
            errors.append(f"schema must be {INSTALL_PROFILES_SCHEMA!r}")

        packages = payload.get("packages")
        profiles = payload.get("profiles")
        if not isinstance(packages, list) or not packages:
            errors.append("packages must be a non-empty array")
            packages = []
        if not isinstance(profiles, list) or not profiles:
            errors.append("profiles must be a non-empty array")
            profiles = []

        package_ids = [
            str(item.get("packageId") or "")
            for item in packages
            if isinstance(item, dict)
        ]
        profile_ids = [
            str(item.get("profileId") or "")
            for item in profiles
            if isinstance(item, dict)
        ]
        errors.extend(self._duplicate_errors("packageId", package_ids))
        errors.extend(self._duplicate_errors("profileId", profile_ids))
        package_id_set = set(package_ids)
        profile_id_set = set(profile_ids)
        package_by_id = {
            item.get("packageId"): item
            for item in packages
            if isinstance(item, dict)
        }

        for index, package in enumerate(packages):
            if not isinstance(package, dict):
                errors.append(f"packages[{index}] must be an object")
                continue
            package_id = str(package.get("packageId") or "")
            if not package_id:
                errors.append(f"packages[{index}].packageId is required")
            if package.get("tier") not in PACKAGE_TIERS:
                errors.append(f"{package_id}.tier is invalid")
            if package.get("deliveryState") not in DELIVERY_STATES:
                errors.append(f"{package_id}.deliveryState is invalid")
            if package.get("installMode") not in INSTALL_MODES:
                errors.append(f"{package_id}.installMode is invalid")
            if package.get("resourceClass") not in RESOURCE_CLASSES:
                errors.append(f"{package_id}.resourceClass is invalid")
            dependencies = package.get("dependsOn")
            if not isinstance(dependencies, list):
                errors.append(f"{package_id}.dependsOn must be an array")
                continue
            unknown = sorted(set(map(str, dependencies)) - package_id_set)
            if unknown:
                errors.append(
                    f"{package_id}.dependsOn references unknown packages {unknown}"
                )

        for index, profile in enumerate(profiles):
            if not isinstance(profile, dict):
                errors.append(f"profiles[{index}] must be an object")
                continue
            profile_id = str(profile.get("profileId") or "")
            inherited = profile.get("inherits") or []
            selected = profile.get("optionalPackages") or []
            if not isinstance(inherited, list):
                errors.append(f"{profile_id}.inherits must be an array")
                inherited = []
            if not isinstance(selected, list):
                errors.append(f"{profile_id}.optionalPackages must be an array")
                selected = []
            unknown_profiles = sorted(set(map(str, inherited)) - profile_id_set)
            unknown_packages = sorted(set(map(str, selected)) - package_id_set)
            if unknown_profiles:
                errors.append(
                    f"{profile_id}.inherits references unknown profiles "
                    f"{unknown_profiles}"
                )
            if unknown_packages:
                errors.append(
                    f"{profile_id}.optionalPackages references unknown packages "
                    f"{unknown_packages}"
                )
            non_optional = sorted(
                package_id
                for package_id in map(str, selected)
                if package_id in package_by_id
                and package_by_id[package_id].get("tier") != "optional"
            )
            if non_optional:
                errors.append(
                    f"{profile_id}.optionalPackages contains core packages "
                    f"{non_optional}"
                )

        if not errors:
            errors.extend(
                self._cycle_errors(
                    "package",
                    {
                        item["packageId"]: list(item.get("dependsOn") or [])
                        for item in packages
                    },
                )
            )
            errors.extend(
                self._cycle_errors(
                    "profile",
                    {
                        item["profileId"]: list(item.get("inherits") or [])
                        for item in profiles
                    },
                )
            )
        if errors:
            raise ValueError("; ".join(errors))

    @staticmethod
    def _duplicate_errors(label: str, values: list[str]) -> list[str]:
        return [
            f"duplicate {label} {value!r}"
            for value, count in Counter(values).items()
            if value and count > 1
        ]

    @staticmethod
    def _cycle_errors(
        label: str,
        graph: dict[str, list[str]],
    ) -> list[str]:
        complete: set[str] = set()
        active: list[str] = []
        errors: list[str] = []

        def visit(node: str) -> None:
            if node in complete:
                return
            if node in active:
                start = active.index(node)
                errors.append(
                    f"{label} dependency cycle: "
                    + " -> ".join(active[start:] + [node])
                )
                return
            active.append(node)
            for dependency in graph.get(node, []):
                visit(dependency)
            active.pop()
            complete.add(node)

        for node in graph:
            visit(node)
        return errors

    def catalog_snapshot(self) -> dict[str, Any]:
        state_counts = Counter(
            item["deliveryState"] for item in self.packages.values()
        )
        tier_counts = Counter(item["tier"] for item in self.packages.values())
        result = {
            "schema": INSTALL_PROFILES_SCHEMA,
            "policy": dict(self.payload.get("policy") or {}),
            "summary": {
                "packages": len(self.packages),
                "profiles": len(self.profiles),
                "corePackages": tier_counts["core"],
                "optionalPackages": tier_counts["optional"],
                "deliveryStates": dict(sorted(state_counts.items())),
                "readyPackages": sum(
                    state_counts[state] for state in READY_STATES
                ),
            },
            "core": [
                self._package_summary(item)
                for item in self.packages.values()
                if item["tier"] == "core"
            ],
            "optional": [
                self._package_summary(item)
                for item in self.packages.values()
                if item["tier"] == "optional"
            ],
            "profiles": [dict(item) for item in self.profiles.values()],
        }
        from .proofs_c_runtime import check_catalog
        check_catalog(self, result)
        return result

    @staticmethod
    def _package_summary(package: dict[str, Any]) -> dict[str, Any]:
        return {
            key: package.get(key)
            for key in (
                "packageId",
                "name",
                "tier",
                "deliveryState",
                "installMode",
                "resourceClass",
                "dependsOn",
                "toolIds",
                "capabilities",
                "gap",
            )
            if package.get(key) is not None
        }

    def resolve(
        self,
        profile_id: str,
        *,
        selected_optional: list[str] | None = None,
        excluded_optional: list[str] | None = None,
    ) -> dict[str, Any]:
        if profile_id not in self.profiles:
            raise KeyError(f"Unknown install profile {profile_id!r}")
        selected = set(self._profile_packages(profile_id))
        selected.update(selected_optional or [])
        excluded = set(excluded_optional or [])
        unknown = sorted((selected | excluded) - set(self.packages))
        if unknown:
            raise KeyError(f"Unknown package ids: {unknown}")
        invalid_selected = sorted(
            item for item in selected if self.packages[item]["tier"] != "optional"
        )
        if invalid_selected:
            raise ValueError(
                f"selected_optional contains core packages {invalid_selected}"
            )
        invalid_excluded = sorted(
            item for item in excluded if self.packages[item]["tier"] != "optional"
        )
        if invalid_excluded:
            raise ValueError(
                f"excluded_optional contains core packages {invalid_excluded}"
            )
        selected.difference_update(excluded)

        resolved: set[str] = {
            item["packageId"]
            for item in self.packages.values()
            if item["tier"] == "core"
        }
        resolved.update(selected)
        queue = list(resolved)
        while queue:
            package_id = queue.pop()
            for dependency in self.packages[package_id]["dependsOn"]:
                if dependency not in resolved:
                    resolved.add(dependency)
                    queue.append(dependency)

        blocked: list[dict[str, Any]] = []
        package_rows: list[dict[str, Any]] = []
        for package_id in self._topological_order(resolved):
            package = self.packages[package_id]
            state = package["deliveryState"]
            row = self._package_summary(package)
            row["readyNow"] = state in READY_STATES
            row["action"] = (
                "retain-bundled"
                if state == "bundled"
                else "ensure-managed"
                if state == "verified"
                else "implementation-required"
            )
            package_rows.append(row)
            if state not in READY_STATES:
                blocked.append(
                    {
                        "packageId": package_id,
                        "deliveryState": state,
                        "gap": package.get("gap")
                        or "A verified installer and acceptance proof are required.",
                    }
                )

        result = {
            "schema": INSTALL_PLAN_SCHEMA,
            "profileId": profile_id,
            "profile": dict(self.profiles[profile_id]),
            "selectedOptional": sorted(selected),
            "excludedOptional": sorted(excluded),
            "packages": package_rows,
            "summary": {
                "packageCount": len(package_rows),
                "coreCount": sum(
                    row["tier"] == "core" for row in package_rows
                ),
                "optionalCount": sum(
                    row["tier"] == "optional" for row in package_rows
                ),
                "readyCount": sum(row["readyNow"] for row in package_rows),
                "blockedCount": len(blocked),
                "resourceClasses": dict(
                    sorted(
                        Counter(
                            row["resourceClass"] for row in package_rows
                        ).items()
                    )
                ),
            },
            "readyToInstall": not blocked,
            "blockedBy": blocked,
            "executionAllowed": False,
            "nextGate": (
                "Implement and verify blocked packages before enabling install execution."
                if blocked
                else "Create a signed, hash-pinned install transaction with rollback receipts."
            ),
        }
        from .proofs_c_runtime import check_plan
        check_plan(self, result)
        return result

    def _profile_packages(self, profile_id: str) -> list[str]:
        resolved: list[str] = []
        seen: set[str] = set()

        def visit(selected_profile: str) -> None:
            if selected_profile in seen:
                return
            seen.add(selected_profile)
            profile = self.profiles[selected_profile]
            for parent in profile.get("inherits") or []:
                visit(parent)
            for package_id in profile.get("optionalPackages") or []:
                if package_id not in resolved:
                    resolved.append(package_id)

        visit(profile_id)
        return resolved

    def _topological_order(self, selected: set[str]) -> list[str]:
        ordered: list[str] = []
        complete: set[str] = set()

        def visit(package_id: str) -> None:
            if package_id in complete:
                return
            for dependency in self.packages[package_id]["dependsOn"]:
                if dependency in selected:
                    visit(dependency)
            complete.add(package_id)
            ordered.append(package_id)

        for package_id in sorted(selected):
            visit(package_id)
        return ordered

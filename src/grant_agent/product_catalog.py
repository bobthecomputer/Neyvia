"""Truthful product boundaries for Neyvia tools, apps, and agents."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from .capability_service import CapabilityService
from .native_tools import NativeToolRegistry


ProductKind = Literal["tool", "app", "agent"]
InteractionAudience = Literal["agent", "user", "shared"]
CATALOG_SCHEMA = "neyvia.product-catalog/v1"


@dataclass(frozen=True)
class ProductDescriptor:
    product_id: str
    name: str
    kind: ProductKind
    audience: InteractionAudience
    summary: str
    operations: tuple[str, ...]
    surfaces: tuple[str, ...] = ()
    source_url: str = ""
    agent_callable: bool = True
    user_interactive: bool = False

    def validate(self) -> None:
        if not self.product_id or not self.name or not self.summary:
            raise ValueError("Product identity, name, and summary are required.")
        if not self.operations:
            raise ValueError(f"{self.product_id} must expose at least one operation.")
        if self.kind == "tool":
            if self.user_interactive or self.surfaces:
                raise ValueError(
                    f"{self.product_id} has a user surface and must be classified as an app."
                )
            if not self.agent_callable:
                raise ValueError(f"{self.product_id} is not callable and cannot be a tool.")
        elif self.kind == "app":
            if not self.user_interactive or not self.surfaces:
                raise ValueError(
                    f"{self.product_id} must expose an interactive user surface."
                )
            if self.audience != "shared" or not self.agent_callable:
                raise ValueError(
                    f"{self.product_id} apps must be shared by the user and agent."
                )
            if not self.source_url.startswith("https://github.com/"):
                raise ValueError(
                    f"{self.product_id} must have an independently versioned GitHub source."
                )
        elif self.kind == "agent":
            required = {"model.run", "tools.search", "tools.call", "session.resume"}
            if not required.issubset(set(self.operations)):
                raise ValueError(
                    f"{self.product_id} lacks native agent operations: "
                    + ", ".join(sorted(required - set(self.operations)))
                )
        else:
            raise ValueError(f"Unsupported product kind: {self.kind}")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        payload = asdict(self)
        product_id = payload.pop("product_id")
        source_url = payload.pop("source_url")
        agent_callable = payload.pop("agent_callable")
        user_interactive = payload.pop("user_interactive")
        return {
            "productId": product_id,
            **payload,
            "sourceUrl": source_url,
            "agentCallable": agent_callable,
            "userInteractive": user_interactive,
        }


def _marketplace_apps(root: Path) -> list[ProductDescriptor]:
    path = root / "config" / "neyvia_marketplace_apps.json"
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("apps") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("neyvia_marketplace_apps.json must contain an apps array.")
    apps: list[ProductDescriptor] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        apps.append(
            ProductDescriptor(
                product_id=str(row.get("appId") or ""),
                name=str(row.get("name") or ""),
                kind="app",
                audience="shared",
                summary=str(row.get("summary") or ""),
                operations=tuple(str(item) for item in row.get("operations") or ()),
                surfaces=tuple(str(item) for item in row.get("surfaces") or ()),
                source_url=str(row.get("sourceUrl") or ""),
                agent_callable=True,
                user_interactive=True,
            )
        )
    return apps


def product_catalog_snapshot(root: str | Path) -> dict[str, Any]:
    workspace = Path(root).resolve()
    native = NativeToolRegistry(workspace).snapshot()
    capability_service = CapabilityService(workspace)
    managed_tools = list(capability_service.tool_manifests.tools.values())
    managed_rows = [
        tool.as_dict(include_operations=True)
        for tool in managed_tools
    ]
    manifest_ready_tools = [
        tool for tool in managed_tools if tool.agent_ready and tool.operations
    ]
    execution_ready_rows = [
        row
        for row in managed_rows
        if row.get("executionReady") and row.get("operations")
    ]

    products: list[ProductDescriptor] = []
    for row in native["tools"]:
        products.append(
            ProductDescriptor(
                product_id=str(row["name"]),
                name=str(row["name"]),
                kind="tool",
                audience="agent",
                summary=str(row["description"]),
                operations=(str(row["name"]),),
            )
        )
    for row in managed_rows:
        operations = tuple(
            str(operation.get("operationId") or "")
            for operation in row.get("operations") or ()
            if isinstance(operation, dict) and operation.get("operationId")
        )
        if not operations:
            continue
        products.append(
            ProductDescriptor(
                product_id=str(row["toolId"]),
                name=str(row["name"]),
                kind="tool",
                audience="agent",
                summary=(
                    f"Managed {row.get('state') or 'catalogued'} tool package "
                    f"with {len(operations)} structured operation(s)."
                ),
                operations=operations,
            )
        )
    products.extend(_marketplace_apps(workspace))
    products.append(
        ProductDescriptor(
            product_id="neyvia.agent",
            name="Neyvia Agent",
            kind="agent",
            audience="shared",
            summary=(
                "Provider-neutral Neyvia agent loop with progressive tools, "
                "durable sessions, specialist delegation, and proof receipts."
            ),
            operations=(
                "model.run",
                "tools.search",
                "tools.describe",
                "tools.call",
                "session.resume",
                "agent.delegate.plan",
                "agent.delegate.verify",
            ),
            surfaces=("agent.thread", "agent.receipts"),
            agent_callable=True,
            user_interactive=True,
        )
    )
    serialized = [product.as_dict() for product in products]
    return {
        "schema": CATALOG_SCHEMA,
        "counts": {
            "products": len(serialized),
            "tools": sum(item["kind"] == "tool" for item in serialized),
            "apps": sum(item["kind"] == "app" for item in serialized),
            "agents": sum(item["kind"] == "agent" for item in serialized),
            "nativeToolHandlers": int(native["total"]),
            "nativeToolsReady": int(native["ready"]),
            "managedToolPackages": len(managed_rows),
            "managedToolPackagesCallable": sum(
                bool(tool.operations) for tool in managed_tools
            ),
            "managedToolOperations": sum(
                len(tool.operations) for tool in managed_tools
            ),
            "manifestReadyManagedToolPackages": len(manifest_ready_tools),
            "manifestReadyManagedToolOperations": sum(
                len(tool.operations) for tool in manifest_ready_tools
            ),
            "executionReadyManagedToolPackages": len(execution_ready_rows),
            "executionReadyManagedToolOperations": sum(
                int(row.get("operationCount") or 0) for row in execution_ready_rows
            ),
            "declaredActionEndpoints": int(native["total"])
            + sum(len(tool.operations) for tool in managed_tools),
            "agentReadyActionEndpoints": int(native["ready"])
            + sum(
                int(row.get("operationCount") or 0) for row in execution_ready_rows
            ),
        },
        "products": serialized,
        "rules": {
            "tool": "Agent-callable structured action with no primary user surface.",
            "app": "Independently versioned interactive surface plus agent-callable operations.",
            "agent": "Model loop with tools, sessions, policy, receipts, and delegation.",
        },
    }

"""Verify bundled skill installation and real fail-closed bridge resolution."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "src"), str(REPO / "scripts")]
import verify_follow_failures as fixtures
fixtures.SCRATCH = REPO / ".agent_control/follow-image-skill" / uuid.uuid4().hex
fixtures.isolate()
from grant_agent.desktop_bridge import _install_bundled_image_skill

spec = importlib.util.spec_from_file_location("follow_image_skill_case", REPO / "tests/test_desktop_bridge.py")
cases = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cases)
with tempfile.TemporaryDirectory(dir=fixtures.SCRATCH) as directory:
    cases.test_desktop_bridge_installs_and_allows_the_bundled_image_skill(Path(directory))
with fixtures.real_http() as (backend, request):
    _install_bundled_image_skill(backend.root)
    source = REPO / ".codex/skills/imagegen/SKILL.md"
    installed = backend.root / ".codex/skills/imagegen/SKILL.md"
    assert source.read_bytes() == installed.read_bytes()
    invocation, error = backend._resolve_image_skill_invocation({"operation": "generate", "skillInvocation": {"skillId": "imagegen"}})
    assert error is None and invocation["skillSha256"] == hashlib.sha256(installed.read_bytes()).hexdigest()
    assert request("/api/auth/local-session", {})["http"] == 200
    refused = request("/api/backend", {"command": "image_playground_operation_command", "payload": {"operation": "generate", "provider": {"id": "unapproved-provider"}, "skillInvocation": {"skillId": "imagegen"}}})
    assert refused["http"] == 200 and "provider_not_allowed" in json.dumps(refused["body"])
    keeper = b"---\nname: imagegen\ndescription: User keeper\n---\nUser-owned image guidance.\n"
    installed.write_bytes(keeper)
    _install_bundled_image_skill(backend.root)
    assert installed.read_bytes() == keeper
receipt = {"boundary": "Exact original installation/allowlist case, byte-exact scratch installation, real backend skill hash resolution and authenticatedHTTP48449 unapproved-provider refusal. Existing user skill preserved. No image/provider execution or pixel-quality claim.",
           "id": "tests/test_desktop_bridge.py::test_desktop_bridge_installs_and_allows_the_bundled_image_skill",
           "passed": True, "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
           "installedBytesMatched": True, "keeperPreserved": True, "unapprovedProviderRefused": True,
           "actualImageGeneration": False, "ownedServerStopped": True}
(REPO / "scripts/evidence/FOLLOW-image-skill.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
print(json.dumps({"passed": True, "actualImageGeneration": False}))

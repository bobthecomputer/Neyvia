from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from grant_agent.context_import import ContextImportService
from grant_agent.runtime_invocation import RuntimeInvocationService
from grant_agent.setup_progress import (
    load_first_run_progress,
    save_first_run_progress,
)


class ProductCompletionMilestonesTests(unittest.TestCase):
    def test_first_run_progress_is_resumable_and_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            saved = save_first_run_progress(
                root,
                {
                    "activeLevel": "recommended",
                    "completedStepIds": ["services", "workspace", "services"],
                    "dismissedOptionalStepIds": ["github"],
                },
            )
            loaded = load_first_run_progress(root)
            self.assertTrue(saved["resumable"])
            self.assertEqual(loaded["activeLevel"], "recommended")
            self.assertEqual(loaded["completedStepIds"], ["services", "workspace"])
            self.assertEqual(loaded["dismissedOptionalStepIds"], ["github"])

    def test_runtime_invocation_records_truthful_lifecycle_and_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def runner(payload: dict) -> dict:
                return {
                    "status": "completed",
                    "reply": "Runtime result",
                    "sessionId": payload["sessionId"],
                    "resumeSupported": True,
                    "filesChanged": ["web/src/example.tsx"],
                    "turnReceipt": {"status": "completed"},
                }

            service = RuntimeInvocationService(root, runner)
            result = service.invoke(
                {
                    "message": "Refine the setup flow",
                    "runtime": "codex",
                    "route": {"provider": "openai", "model": "gpt-test"},
                    "conversationId": "conversation-one",
                }
            )
            self.assertEqual(result["status"], "closed")
            self.assertTrue(result["resumeCapability"])
            self.assertEqual(result["lifecycle"]["changes"], ["web/src/example.tsx"])
            resumed = service.invoke(
                {
                    "message": "Continue",
                    "runtime": "codex",
                    "invocationId": result["invocationId"],
                }
            )
            self.assertEqual(resumed["invocationId"], result["invocationId"])
            self.assertEqual(len(service.list()["invocations"]), 1)

    def test_selective_context_import_only_copies_selected_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "workspace"
            home = base / "home"
            sessions = home / ".codex" / "sessions" / "2026" / "07"
            sessions.mkdir(parents=True)
            first = sessions / "first.jsonl"
            second = sessions / "second.jsonl"
            first.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "response_item",
                                "payload": {
                                    "role": "developer",
                                    "content": "private developer instruction",
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "role": "user",
                                "content": (
                                    "selected context api_key=top-secret-value "
                                    "NAS nas-user another-secret port22"
                                ),
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            second.write_text(
                json.dumps({"role": "user", "content": "must stay excluded"}) + "\n",
                encoding="utf-8",
            )
            service = ContextImportService(root, home=home)
            catalog = service.catalog()
            first_item = next(
                item for item in catalog["items"] if item["sessionIdentity"] == "first"
            )
            receipt = service.import_selected(
                [first_item["id"]],
                conversation_id="conversation-one",
            )
            self.assertEqual(len(receipt["importedItems"]), 1)
            artifact = Path(receipt["importedItems"][0]["artifactPath"])
            content = artifact.read_text(encoding="utf-8")
            self.assertIn("selected context", content)
            self.assertIn("[REDACTED]", content)
            self.assertNotIn("top-secret-value", content)
            self.assertNotIn("another-secret", content)
            self.assertNotIn("private developer instruction", content)
            self.assertNotIn("must stay excluded", content)
            self.assertTrue(receipt["lineage"]["selectionRequired"])


if __name__ == "__main__":
    unittest.main()

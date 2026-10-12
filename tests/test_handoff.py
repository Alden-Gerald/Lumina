from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import call, patch

from local_coder.handoff import HandoffClient, attachment_path, compact_diff, compact_status


class HandoffTests(unittest.TestCase):
    def test_active_status_tells_codex_to_end_without_returning_transcript(self):
        result = compact_status({
            "id": "a" * 32,
            "status": "working",
            "message": "Choosing action 4 of 24",
            "profile": "quality",
            "step": 4,
            "changed_files": ["app.py"],
            "metrics": [{"prompt_eval_count": 9000}],
            "failed_attempts": [{"error": "private local detail"}],
        })
        self.assertEqual(result["run_id"], "a" * 32)
        self.assertIn("End the Codex turn", result["next_step"])
        self.assertNotIn("metrics", result)
        self.assertNotIn("failed_attempts", result)

    def test_completed_status_returns_only_verification_summary(self):
        result = compact_status({
            "id": "b" * 32,
            "status": "completed",
            "message": "Feature implemented",
            "profile": "quality",
            "step": 8,
            "changed_files": ["app.py", "test_app.py"],
            "validation": {"ok": True, "summary": "All checks passed", "diagnostics": ["large output"]},
            "review": {"approved": True, "findings": []},
            "result": "Added validation",
            "commit": "123abc",
        })
        self.assertEqual(result["checks"], {"ok": True, "summary": "All checks passed"})
        self.assertTrue(result["review"]["approved"])
        self.assertNotIn("diagnostics", result["checks"])
        self.assertIn("inspect and apply", result["next_step"])

    def test_diff_is_bounded(self):
        result = compact_diff({"diff": "x" * 5000}, 1000)
        self.assertEqual(len(result["diff"]), 1000)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["characters"], 5000)

    def test_client_sends_compact_task_to_dashboard(self):
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "token";token.write_text("secret")
            client = HandoffClient(token_path=token)
            info = {"profiles": {"quality": {"installed": True}}}
            state = {"id": "c" * 32, "status": "queued", "message": "Preparing", "profile": "quality", "origin": "codex"}
            with patch.object(client, "_request", side_effect=[info, state]) as request:
                result = client.start("Implement the feature", Path("/project"), acceptance="Tests pass")
            self.assertEqual(request.call_args_list,[call("/api/info"),call("/api/runs", {
                "task": "Implement the feature", "source": "/project", "profile": "quality",
                "acceptance": "Tests pass", "test_commands": [], "team": True, "attachments": [],
                "origin": "codex", "auto_apply": True, "desktop_followup": True,
            })])
            self.assertEqual(result["run_id"], "c" * 32)
            self.assertEqual(result["attachments_forwarded"], 0)
            self.assertEqual(result["source"], "/project")

    def test_unavailable_profile_falls_back_to_installed_quality(self):
        client = HandoffClient()
        info = {"profiles": {"balanced": {"installed": False}, "quality": {"installed": True}}}
        state = {"id": "d" * 32, "status": "queued", "message": "Preparing", "profile": "quality"}
        with patch.object(client, "_request", side_effect=[info, state]) as request:
            result = client.start("Implement the feature", Path("/project"), profile="balanced")
        self.assertEqual(request.call_args_list[1].args[1]["profile"], "quality")
        self.assertIn("used installed profile 'quality'", result["profile_notice"])

    def test_only_bounded_codex_clipboard_images_can_be_forwarded(self):
        allowed = Path("/tmp") / f"codex-clipboard-{uuid.uuid4()}.png"
        allowed.write_bytes(b"small image placeholder")
        try:
            self.assertEqual(attachment_path(str(allowed)), allowed)
            with tempfile.NamedTemporaryFile(suffix=".png") as other:
                with self.assertRaisesRegex(ValueError, "Only Codex clipboard images"):
                    attachment_path(other.name)
        finally:
            allowed.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

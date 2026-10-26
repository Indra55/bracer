import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from miband_agent.hook import entrypoint, hook_result, review_params


EVENT = {"hook_event_name": "PermissionRequest", "tool_name": "Bash",
         "cwd": "/some/other/project", "session_id": "chat-1", "turn_id": "turn-1",
         "tool_input": {"command": "touch example.txt", "description": "Create test file"}}


class HookTests(unittest.TestCase):
    def test_only_command_permission_requests_are_reviewed(self):
        self.assertEqual(review_params(EVENT)["command"], "touch example.txt")
        self.assertEqual(review_params(EVENT)["session"], "chat-1")
        self.assertEqual(review_params(EVENT)["cwd"], "/some/other/project")
        for change in ({"hook_event_name": "PreToolUse"}, {"tool_name": "apply_patch"},
                       {"tool_name": "mcp__example__write"}, {"tool_input": {}}, {"tool_input": []}):
            self.assertIsNone(review_params({**EVENT, **change}))

    def test_additional_tool_context_is_preserved(self):
        params = review_params({**EVENT, "tool_input": {**EVENT["tool_input"], "sandbox_permissions": "require_escalated"}})
        self.assertEqual(params["details"], {"sandbox_permissions": "require_escalated"})

    def test_explicit_decisions_match_native_permission_hook_contract(self):
        for decision, behavior in (("accept", "allow"), ("decline", "deny")):
            output = hook_result(decision)["hookSpecificOutput"]
            self.assertEqual(output["hookEventName"], "PermissionRequest")
            self.assertEqual(output["decision"]["behavior"], behavior)
            self.assertNotIn("updatedPermissions", output)
            self.assertNotIn("updatedInput", output)
        self.assertEqual(hook_result("unavailable"), {})
        self.assertEqual(hook_result("unexpected"), {})

    def invoke(self, payload, decision="accept", error=None):
        async def review(_):
            print("transport diagnostic")
            if error:
                raise error
            return decision

        output, diagnostics = io.StringIO(), io.StringIO()
        with patch("sys.stdin", io.StringIO(payload)), contextlib.redirect_stdout(output), \
                contextlib.redirect_stderr(diagnostics), patch("miband_agent.hook.review_on_service", review):
            self.assertEqual(entrypoint(), 0)
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        return json.loads(output.getvalue()), diagnostics.getvalue()

    def test_hook_stdout_is_only_json_and_diagnostics_go_to_stderr(self):
        result, diagnostics = self.invoke(json.dumps(EVENT))
        self.assertEqual(result, hook_result("accept"))
        self.assertIn("transport diagnostic", diagnostics)

    def test_unavailable_service_preserves_native_prompt(self):
        result, diagnostics = self.invoke(json.dumps(EVENT), error=ConnectionError("service offline"))
        self.assertEqual(result, {})
        self.assertIn("normal Codex approval prompt", diagnostics)
        result, _ = self.invoke(json.dumps(EVENT), decision="unavailable")
        self.assertEqual(result, {})

    def test_invalid_input_cannot_grant_permission(self):
        for payload in ("not json", "[]", "null", "{}"):
            result, _ = self.invoke(payload)
            self.assertEqual(result, {})


class HookInstallationTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("installer", Path(__file__).parents[1] / "scripts/install-linux.py")
        self.installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.installer)

    def test_install_preserves_other_hooks_and_is_idempotent(self):
        other = {"type": "command", "command": "other-policy.py"}
        existing = {"description": "Keep this", "hooks": {"Stop": [{"hooks": [other]}],
                    "PermissionRequest": [{"matcher": "Bash", "hooks": [other]}]}}
        root = Path("/tmp/my project")
        merged = self.installer.merge_codex_hook(existing, root)
        self.assertEqual(merged["description"], "Keep this")
        self.assertEqual(merged["hooks"]["Stop"], existing["hooks"]["Stop"])
        self.assertEqual(merged["hooks"]["PermissionRequest"][0], existing["hooks"]["PermissionRequest"][0])
        self.assertEqual(merged, self.installer.merge_codex_hook(merged, root))
        handler = merged["hooks"]["PermissionRequest"][-1]["hooks"][0]
        self.assertNotIn("async", handler)
        self.assertGreaterEqual(handler["timeout"], 150)
        self.assertIn("'/tmp/my project/scripts/codex_approval_hook.py'", handler["command"])
        self.assertEqual(existing["hooks"]["PermissionRequest"], [{"matcher": "Bash", "hooks": [other]}])

    def test_moving_project_updates_only_our_hook(self):
        old = self.installer.merge_codex_hook({}, Path("/old/root"))
        moved = self.installer.merge_codex_hook(old, Path("/new/root"))
        self.assertEqual(len(moved["hooks"]["PermissionRequest"]), 1)
        self.assertIn("/new/root", moved["hooks"]["PermissionRequest"][0]["hooks"][0]["command"])

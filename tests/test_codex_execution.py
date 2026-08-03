import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.codex_execution import CodexExecutionAgent


class CodexExecutionAgentTests(unittest.TestCase):
    def test_requires_explicit_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = CodexExecutionAgent(Path(directory))
            result = agent.run("Implement a test", False)
        self.assertFalse(result.success)
        self.assertIn("approval", result.error.lower())

    @patch("agents.codex_execution.subprocess.run")
    def test_uses_workspace_write_without_dangerous_bypass(self, run):
        run.return_value.returncode = 0
        run.return_value.stderr = ""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent = CodexExecutionAgent(root)
            agent.executable = "codex.exe"
            result = agent.run("Implement a test", True)
            arguments = run.call_args.args[0]
        self.assertTrue(result.success)
        self.assertIn("workspace-write", arguments)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", arguments)
        self.assertEqual(run.call_args.kwargs["input"], "Implement a test")
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(run.call_args.kwargs["errors"], "replace")

    def test_loads_only_openai_key_from_local_env(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.local").write_text(
                "OPENAI_API_KEY=placeholder-value\nOTHER_SECRET=do-not-load\n",
                encoding="utf-8",
            )
            loaded = CodexExecutionAgent(root)._load_local_openai_environment()
        self.assertEqual(loaded, {"OPENAI_API_KEY": "placeholder-value"})


if __name__ == "__main__":
    unittest.main()

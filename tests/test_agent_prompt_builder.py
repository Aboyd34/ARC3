from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agents.configuration import AgentConfiguration
from agents.prompt_builder import PromptBuilder


def configuration() -> AgentConfiguration:
    return AgentConfiguration(
        project_name="ARC3",
        protected_branches=("main", "master"),
        allowed_validation_commands=(
            ("python", "-m", "compileall", "app"),
            ("git", "diff", "--check"),
        ),
        command_timeout_seconds=180,
        maximum_changed_files=40,
        forbidden_file_patterns=(".env", "*.key"),
        ignored_paths=(".git", "__pycache__"),
    )


class PromptBuilderTests(unittest.TestCase):
    def test_prompt_contains_task_branch_safety_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text(
                "# Test instructions\n",
                encoding="utf-8",
            )
            (root / "app").mkdir()
            (root / "app" / "device_manager.py").write_text(
                "",
                encoding="utf-8",
            )
            builder = PromptBuilder(root, configuration())

            prompt = builder.build(
                "Phase 7 Device Manager",
                "phase7",
            )

        self.assertIn("Phase 7 Device Manager", prompt)
        self.assertIn("Current branch: `phase7`", prompt)
        self.assertIn("Never edit `main`", prompt)
        self.assertIn("Never use `shell=True`", prompt)
        self.assertIn("python -m compileall app", prompt)
        self.assertIn("git diff --check", prompt)
        self.assertIn("Do not commit", prompt)
        self.assertIn("app/device_manager.py", prompt)
        self.assertNotIn("permission to commit", prompt.casefold())

    def test_saved_prompt_is_created_under_agent_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text(
                "# Test instructions\n",
                encoding="utf-8",
            )
            builder = PromptBuilder(root, configuration())

            path = builder.save("Safe Task", "phase-safe")

            self.assertTrue(path.is_file())
            self.assertEqual(path.parent.name, "prompts")
            self.assertEqual(path.parent.parent.name, "agent_output")
            self.assertIn("Safe Task", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

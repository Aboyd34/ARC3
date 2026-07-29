from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from agents.configuration import AgentConfiguration
from agents.models import GitStatus
from agents.planner import PlannerAgent


def configuration() -> AgentConfiguration:
    return AgentConfiguration(
        project_name="ARC3",
        protected_branches=("main", "master"),
        allowed_validation_commands=(
            ("python", "-m", "compileall", "app"),
            ("git", "diff", "--check"),
        ),
        command_timeout_seconds=30,
        maximum_changed_files=40,
        forbidden_file_patterns=(".env", "*.key", "*secret*"),
        ignored_paths=(".git", "__pycache__"),
    )


class PlannerAgentTests(unittest.TestCase):
    def test_plan_uses_repository_context_and_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text(
                "Repository instructions", encoding="utf-8"
            )
            agents = root / "agents"
            agents.mkdir()
            (agents / "supervisor.py").write_text(
                "class Supervisor: pass\n", encoding="utf-8"
            )
            git = Mock()
            git.inspect.return_value = GitStatus(
                project_path=root,
                is_repository=True,
                branch="agent-supervisor-v2",
                tracked_changes=("agents/supervisor.py",),
            )

            result = PlannerAgent(root, configuration(), git).run(
                "Extend supervisor"
            )

            self.assertEqual(result.branch, "agent-supervisor-v2")
            self.assertIn("agents/supervisor.py", result.relevant_files)
            self.assertEqual(
                result.validation_commands,
                configuration().allowed_validation_commands,
            )
            self.assertTrue(any("dirty" in item for item in result.warnings))

    def test_empty_task_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            git = Mock()
            with self.assertRaises(ValueError):
                PlannerAgent(
                    Path(directory), configuration(), git
                ).run("   ")


if __name__ == "__main__":
    unittest.main()

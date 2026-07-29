from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from agents.configuration import AgentConfiguration
from agents.models import GitStatus
from agents.reviewer import CodeReviewAgent


def configuration() -> AgentConfiguration:
    return AgentConfiguration(
        project_name="ARC3",
        protected_branches=("main", "master"),
        allowed_validation_commands=(("git", "status", "--short"),),
        command_timeout_seconds=30,
        maximum_changed_files=40,
        forbidden_file_patterns=(".env", "*.key", "*secret*"),
        ignored_paths=(".git", "__pycache__"),
    )


class CodeReviewAgentTests(unittest.TestCase):
    def test_detects_prohibited_python_constructs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "worker.py"
            source.write_text(
                "subprocess.run(command, shell=True)\n",
                encoding="utf-8",
            )
            git = Mock()
            git.inspect.return_value = GitStatus(
                project_path=root,
                is_repository=True,
                branch="feature",
                tracked_changes=("worker.py",),
            )

            result = CodeReviewAgent(root, configuration(), git).run()

            self.assertFalse(result.passed)
            self.assertEqual(
                result.findings[0].category,
                "unsafe-subprocess",
            )
            self.assertEqual(result.findings[0].line, 1)

    def test_skips_symlink_or_outside_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            git = Mock()
            git.inspect.return_value = GitStatus(
                project_path=root,
                is_repository=True,
                branch="feature",
                untracked_files=("../outside.py",),
            )

            result = CodeReviewAgent(root, configuration(), git).run()

            self.assertEqual(result.files_inspected, ())
            self.assertEqual(result.skipped_files, ("../outside.py",))


if __name__ == "__main__":
    unittest.main()

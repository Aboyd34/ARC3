from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from agents.configuration import AgentConfiguration
from agents.models import GitStatus
from agents.security import SecurityAgent


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


class SecurityAgentTests(unittest.TestCase):
    def test_reports_secret_without_exposing_value(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret_value = "do-not-print-this-value"
            (root / "settings.py").write_text(
                f'api_key = "{secret_value}"\n',
                encoding="utf-8",
            )
            git = Mock()
            git.inspect.return_value = GitStatus(
                project_path=root,
                is_repository=True,
                branch="feature",
                tracked_changes=("settings.py",),
            )

            result = SecurityAgent(root, configuration(), git).run()
            serialized = str(result.to_dict())

            self.assertFalse(result.passed)
            self.assertEqual(
                result.findings[0].category,
                "suspected-secret",
            )
            self.assertNotIn(secret_value, serialized)

    def test_protected_filename_is_not_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "SECRET=hidden\n", encoding="utf-8"
            )
            git = Mock()
            git.inspect.return_value = GitStatus(
                project_path=root,
                is_repository=True,
                branch="feature",
                untracked_files=(".env",),
            )

            result = SecurityAgent(root, configuration(), git).run()

            self.assertEqual(result.files_inspected, ())
            self.assertEqual(result.skipped_files, (".env",))
            self.assertEqual(
                result.findings[0].category,
                "protected-filename",
            )


if __name__ == "__main__":
    unittest.main()

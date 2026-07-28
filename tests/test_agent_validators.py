from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from agents.configuration import AgentConfiguration
from agents.validators import CommandNotAllowedError, Validator


def configuration(
    commands: tuple[tuple[str, ...], ...],
    timeout: int = 5,
) -> AgentConfiguration:
    return AgentConfiguration(
        project_name="ARC3",
        protected_branches=("main", "master"),
        allowed_validation_commands=commands,
        command_timeout_seconds=timeout,
        maximum_changed_files=40,
        forbidden_file_patterns=(".env", "*.key"),
        ignored_paths=(".git", "__pycache__"),
    )


class ValidatorTests(unittest.TestCase):
    def test_allowlisted_command_succeeds(self):
        command = (sys.executable, "-c", "print('ok')")
        with tempfile.TemporaryDirectory() as directory:
            result = Validator(
                Path(directory),
                configuration((command,)),
            ).run(command)

        self.assertTrue(result.passed)
        self.assertIn("ok", result.stdout)

    def test_allowlisted_command_fails(self):
        command = (sys.executable, "-c", "raise SystemExit(7)")
        with tempfile.TemporaryDirectory() as directory:
            result = Validator(
                Path(directory),
                configuration((command,)),
            ).run(command)

        self.assertFalse(result.passed)
        self.assertEqual(result.exit_code, 7)

    def test_forbidden_command_is_rejected(self):
        allowed = (sys.executable, "-c", "print('allowed')")
        with tempfile.TemporaryDirectory() as directory:
            validator = Validator(
                Path(directory),
                configuration((allowed,)),
            )
            with self.assertRaises(CommandNotAllowedError):
                validator.run(("git", "commit", "-am", "unsafe"))

    def test_timeout_handling(self):
        command = (
            sys.executable,
            "-c",
            "import time; time.sleep(3)",
        )
        with tempfile.TemporaryDirectory() as directory:
            result = Validator(
                Path(directory),
                configuration((command,), timeout=1),
            ).run(command)

        self.assertFalse(result.passed)
        self.assertTrue(result.timed_out)

    def test_missing_executable_handling(self):
        command = ("arc3-executable-that-does-not-exist", "--version")
        with tempfile.TemporaryDirectory() as directory:
            result = Validator(
                Path(directory),
                configuration((command,)),
            ).run(command)

        self.assertFalse(result.passed)
        self.assertIn("Executable not found", result.error)


if __name__ == "__main__":
    unittest.main()

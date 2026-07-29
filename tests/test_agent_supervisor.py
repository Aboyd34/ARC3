from __future__ import annotations

import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

import arc3_agent
from agents.configuration import (
    AgentConfiguration,
    ConfigurationError,
)
from agents.models import (
    CommandResult,
    GitStatus,
    ReviewResult,
    SecurityResult,
    ValidationResult,
)
from agents.supervisor import Supervisor, UnsafeRepositoryError


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


def initialize_repository(root: Path, branch: str):
    def git(*arguments: str):
        return subprocess.run(
            ["git", *arguments],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
            shell=False,
            check=True,
        )

    git("init")
    git("config", "user.email", "arc3-tests@example.invalid")
    git("config", "user.name", "ARC3 Tests")
    (root / "tracked.txt").write_text("base\n", encoding="utf-8")
    git("add", "tracked.txt")
    git("commit", "-m", "baseline")
    git("branch", "-M", branch)


def successful_command() -> CommandResult:
    return CommandResult(
        command=("git", "status", "--short"),
        exit_code=0,
        duration_seconds=0.01,
    )


class SupervisorTests(unittest.TestCase):
    def test_invalid_configuration_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent_config.json"
            path.write_text("{not-json", encoding="utf-8")

            with self.assertRaises(ConfigurationError):
                AgentConfiguration.load(path)

    def test_prepare_rejects_protected_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_repository(root, "main")
            supervisor = Supervisor(root, configuration())

            with self.assertRaises(UnsafeRepositoryError):
                supervisor.prepare("Unsafe task")

    def test_prepare_rejects_invalid_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            supervisor = Supervisor(Path(directory), configuration())

            with self.assertRaises(UnsafeRepositoryError):
                supervisor.prepare("Invalid repository task")

    def test_supervise_rejects_protected_branch_without_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_repository(root, "main")
            supervisor = Supervisor(root, configuration())

            with patch.object(supervisor, "validate") as validate:
                report, markdown_path, _ = supervisor.supervise()

            self.assertEqual(report.decision, "REJECTED")
            self.assertIsNone(report.validation)
            self.assertTrue(markdown_path.is_file())
            validate.assert_not_called()

    def test_supervise_combines_review_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_repository(root, "agent-test")
            supervisor = Supervisor(root, configuration())
            review = ReviewResult(
                findings=(),
                changed_files=(),
                untracked_files=(),
                diff_stat="",
                diff_check=successful_command(),
            )
            validation = ValidationResult((successful_command(),))

            with (
                patch.object(supervisor, "review", return_value=review),
                patch.object(
                    supervisor,
                    "validate",
                    return_value=validation,
                ),
            ):
                report, markdown_path, json_path = supervisor.supervise(
                    include_json=True
                )

            self.assertEqual(
                report.decision,
                "APPROVED FOR HUMAN REVIEW",
            )
            self.assertTrue(markdown_path.is_file())
            self.assertTrue(json_path and json_path.is_file())
            self.assertIn(
                report.decision,
                markdown_path.read_text(encoding="utf-8"),
            )

    def test_supervise_rejects_failed_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_repository(root, "agent-test")
            supervisor = Supervisor(root, configuration())
            review = ReviewResult(
                findings=(),
                changed_files=(),
                untracked_files=(),
                diff_stat="",
                diff_check=successful_command(),
            )
            failed = CommandResult(
                command=("git", "status", "--short"),
                exit_code=1,
                duration_seconds=0.01,
            )

            with (
                patch.object(supervisor, "review", return_value=review),
                patch.object(
                    supervisor,
                    "validate",
                    return_value=ValidationResult((failed,)),
                ),
            ):
                report, _, _ = supervisor.supervise()

            self.assertEqual(report.decision, "REJECTED")

    def test_cli_returns_unsafe_exit_code(self):
        fake_supervisor = Mock()
        fake_supervisor.prepare.side_effect = UnsafeRepositoryError(
            "protected"
        )

        with patch(
            "arc3_agent.load_supervisor",
            return_value=fake_supervisor,
        ):
            exit_code = arc3_agent.run(["prepare", "Unsafe task"])

        self.assertEqual(exit_code, arc3_agent.EXIT_UNSAFE)

    def test_cli_configuration_error_returns_usage_exit_code(self):
        with patch(
            "arc3_agent.load_supervisor",
            side_effect=ConfigurationError("invalid"),
        ):
            exit_code = arc3_agent.run(["status"])

        self.assertEqual(exit_code, arc3_agent.EXIT_USAGE)

    def test_security_review_primary_command_and_alias_are_equivalent(self):
        result = SecurityResult(
            changed_files=("agents/security.py",),
            findings=(),
            files_inspected=("agents/security.py",),
        )
        fake_supervisor = Mock()
        fake_supervisor.security_review.return_value = result
        outputs = {}

        with patch(
            "arc3_agent.load_supervisor",
            return_value=fake_supervisor,
        ):
            for command in ("security-review", "security"):
                for json_flag in (False, True):
                    arguments = [command]
                    if json_flag:
                        arguments.append("--json")
                    output = StringIO()
                    with redirect_stdout(output):
                        exit_code = arc3_agent.run(arguments)
                    self.assertEqual(exit_code, arc3_agent.EXIT_SUCCESS)
                    outputs[(command, json_flag)] = output.getvalue()

        self.assertEqual(
            outputs[("security-review", False)],
            outputs[("security", False)],
        )
        self.assertEqual(
            outputs[("security-review", True)],
            outputs[("security", True)],
        )
        self.assertEqual(fake_supervisor.security_review.call_count, 4)

    def test_cli_help_documents_primary_security_review_command(self):
        help_text = arc3_agent.build_parser().format_help()

        self.assertIn("security-review", help_text)
        self.assertIn(
            "Alias for the v2 security-review command.",
            help_text,
        )


if __name__ == "__main__":
    unittest.main()

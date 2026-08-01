from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agents.configuration import (
    AgentConfiguration,
    ConfigurationError,
)
from agents.report import (
    engineering_review_text,
    plan_text,
    print_json,
    review_text,
    status_text,
    supervision_markdown,
    validation_text,
)
from agents.supervisor import Supervisor, UnsafeRepositoryError


EXIT_SUCCESS = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_UNSAFE = 3


def build_parser() -> argparse.ArgumentParser:
    examples = """examples:
  python arc3_agent.py status
  python arc3_agent.py status --json
  python arc3_agent.py prepare "Phase 7 Device Manager"
  python arc3_agent.py prepare "Phase 7 Device Manager" --json
  python arc3_agent.py validate
  python arc3_agent.py validate --json
  python arc3_agent.py review
  python arc3_agent.py review --json
  python arc3_agent.py code-review
  python arc3_agent.py code-review --json
  python arc3_agent.py security-review
  python arc3_agent.py security-review --json
  python arc3_agent.py security
  python arc3_agent.py security --json
  python arc3_agent.py supervise
  python arc3_agent.py supervise --json
"""
    parser = argparse.ArgumentParser(
        description=(
            "ARC3 Developer Supervisor Agent: deterministic local "
            "preparation, Git review, and validation."
        ),
        epilog=examples,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("status", "Show repository and branch status."),
        ("validate", "Run only configured validation commands."),
        ("review", "Review current Git changes deterministically."),
        ("supervise", "Run status, review, and validation."),
        ("code-review", "Run the v2 deterministic code review agent."),
        (
            "security-review",
            "Run the v2 deterministic security review agent.",
        ),
        (
            "security",
            "Alias for the v2 security-review command.",
        ),
    ):
        subparser = subparsers.add_parser(name, help=help_text)
        subparser.add_argument(
            "--json",
            action="store_true",
            help="Print JSON output; supervise also saves a JSON report.",
        )

    prepare = subparsers.add_parser(
        "prepare",
        help="Create and save a Codex implementation prompt.",
    )
    prepare.add_argument("task_title", help="Task title for Codex.")
    prepare.add_argument(
        "--json",
        action="store_true",
        help="Print the saved prompt path as JSON.",
    )
    plan = subparsers.add_parser(
        "plan",
        help="Build a deterministic local implementation plan.",
    )
    plan.add_argument("task_title", help="Task title to plan.")
    plan.add_argument(
        "--json",
        action="store_true",
        help="Print JSON output.",
    )
    execute = subparsers.add_parser(
        "execute",
        help="Run an explicitly approved Codex implementation task.",
    )
    execute.add_argument("task_title", help="Task title for Codex.")
    execute.add_argument(
        "--approve",
        action="store_true",
        help="Confirm that Codex may edit this workspace for this task.",
    )
    return parser


def load_supervisor(project_path: Path) -> Supervisor:
    configuration = AgentConfiguration.load(
        project_path / "agent_config.json"
    )
    return Supervisor(project_path, configuration)


def run(arguments: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(arguments)
    project_path = Path(__file__).resolve().parent

    try:
        supervisor = load_supervisor(project_path)
    except ConfigurationError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return EXIT_USAGE

    if args.command == "status":
        status = supervisor.status()
        print(
            print_json(status.to_dict())
            if args.json
            else status_text(status)
        )
        return EXIT_SUCCESS

    if args.command == "prepare":
        try:
            path = supervisor.prepare(args.task_title)
        except (UnsafeRepositoryError, ValueError) as error:
            print(f"Safety rejection: {error}", file=sys.stderr)
            return (
                EXIT_UNSAFE
                if isinstance(error, UnsafeRepositoryError)
                else EXIT_USAGE
            )
        payload = {"saved_prompt": str(path)}
        print(print_json(payload) if args.json else f"Saved prompt: {path}")
        return EXIT_SUCCESS

    if args.command == "plan":
        try:
            plan = supervisor.plan(args.task_title)
        except ValueError as error:
            print(f"Planning error: {error}", file=sys.stderr)
            return EXIT_USAGE
        print(
            print_json(plan.to_dict())
            if args.json
            else plan_text(plan)
        )
        return EXIT_SUCCESS

    if args.command == "execute":
        try:
            result = supervisor.execute_codex(args.task_title, args.approve)
        except UnsafeRepositoryError as error:
            print(f"Safety rejection: {error}", file=sys.stderr)
            return EXIT_UNSAFE
        if result.final_response:
            print(result.final_response)
        if not result.success:
            print(f"Codex execution error: {result.error}", file=sys.stderr)
            return EXIT_FAILED
        return EXIT_SUCCESS

    if args.command == "code-review":
        result = supervisor.code_review()
        print(
            print_json(result.to_dict())
            if args.json
            else engineering_review_text("Code Review Agent", result)
        )
        return EXIT_SUCCESS if result.passed else EXIT_FAILED

    if args.command in {"security-review", "security"}:
        result = supervisor.security_review()
        print(
            print_json(result.to_dict())
            if args.json
            else engineering_review_text("Security Agent", result)
        )
        return EXIT_SUCCESS if result.passed else EXIT_FAILED

    if args.command == "validate":
        validation = supervisor.validate()
        print(
            print_json(validation.to_dict())
            if args.json
            else validation_text(validation)
        )
        return EXIT_SUCCESS if validation.passed else EXIT_FAILED

    if args.command == "review":
        review = supervisor.review()
        print(
            print_json(review.to_dict())
            if args.json
            else review_text(review)
        )
        status = supervisor.status()
        if status.unsafe:
            return EXIT_UNSAFE
        return EXIT_SUCCESS if review.passed else EXIT_FAILED

    if args.command == "supervise":
        report, markdown_path, json_path = supervisor.supervise(args.json)
        print(
            print_json(report.to_dict())
            if args.json
            else supervision_markdown(report)
        )
        print(f"Saved report: {markdown_path}")
        if json_path:
            print(f"Saved JSON report: {json_path}")
        if report.git_status.unsafe:
            return EXIT_UNSAFE
        return (
            EXIT_SUCCESS
            if report.decision
            in {"APPROVED FOR HUMAN REVIEW", "MANUAL REVIEW REQUIRED"}
            else EXIT_FAILED
        )

    parser.error("Unsupported command.")
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(run())

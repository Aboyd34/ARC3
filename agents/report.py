from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents.models import (
    GitStatus,
    ReviewResult,
    SupervisionReport,
    ValidationResult,
)


def command_text(command: tuple[str, ...]) -> str:
    return " ".join(command)


def status_text(status: GitStatus) -> str:
    remotes = (
        ", ".join(f"{name}={url}" for name, url in status.remotes.items())
        or "None"
    )
    return "\n".join(
        (
            f"Project path: {status.project_path}",
            f"Repository: {'yes' if status.is_repository else 'no'}",
            f"Branch: {status.branch or '(detached/unknown)'}",
            f"Protected branch: {'yes' if status.protected_branch else 'no'}",
            f"Detached HEAD: {'yes' if status.detached_head else 'no'}",
            f"Working tree: {'clean' if status.clean else 'dirty'}",
            (
                "Tracked changes: "
                + (", ".join(status.tracked_changes) or "None")
            ),
            (
                "Untracked files: "
                + (", ".join(status.untracked_files) or "None")
            ),
            f"Merge conflicts: {', '.join(status.conflicts) or 'None'}",
            f"Remotes: {remotes}",
            f"Latest commit: {status.latest_commit or 'Unavailable'}",
            f"Error: {status.error or 'None'}",
        )
    )


def validation_text(validation: ValidationResult) -> str:
    lines = []
    for result in validation.commands:
        state = "PASS" if result.passed else "FAIL"
        lines.append(
            f"[{state}] {command_text(result.command)}\n"
            f"  Exit: {result.exit_code}  "
            f"Duration: {result.duration_seconds:.2f}s"
        )
        output = concise_output(result.stdout, result.stderr, result.error)
        if output:
            lines.append(output)
    lines.append(
        "Overall validation: "
        + ("PASS" if validation.passed else "FAIL")
    )
    return "\n".join(lines)


def review_text(review: ReviewResult) -> str:
    lines = [
        f"Changed files ({len(review.changed_files)}): "
        + (", ".join(review.changed_files) or "None"),
        f"Untracked files ({len(review.untracked_files)}): "
        + (", ".join(review.untracked_files) or "None"),
        f"Diff check: {'PASS' if review.diff_check.passed else 'FAIL'}",
        "Diff statistics:",
        review.diff_stat or "(No tracked diff statistics.)",
        "Findings:",
    ]
    lines.extend(
        (
            f"- [{finding.severity}] {finding.title}"
            + (f" ({finding.path})" if finding.path else "")
            + f": {finding.details}"
        )
        for finding in review.findings
    )
    if not review.findings:
        lines.append("- None")
    lines.append(
        "Deterministic review: "
        + ("PASS" if review.passed else "FAIL")
    )
    lines.append(
        "Semantic correctness still requires human review."
    )
    return "\n".join(lines)


def supervision_markdown(report: SupervisionReport) -> str:
    review_section = (
        review_text(report.review)
        if report.review
        else "Review was not run."
    )
    validation_section = (
        validation_text(report.validation)
        if report.validation
        else "Validation was not run."
    )
    notes = "\n".join(f"- {note}" for note in report.notes) or "- None"
    return f"""# ARC3 Developer Supervisor Report

Generated: {report.generated_at}

## Decision

**{report.decision}**

## Repository status

```text
{status_text(report.git_status)}
```

## Deterministic review

```text
{review_section}
```

## Validation

```text
{validation_section}
```

## Notes and human-review boundary

{notes}

This report validates deterministic repository and command checks only.
It does not claim semantic correctness or authorize a commit.
"""


def save_report(
    path: Path,
    report: SupervisionReport,
    include_json: bool = False,
) -> tuple[Path, Path | None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(supervision_markdown(report), encoding="utf-8")
    json_path = None
    if include_json:
        json_path = path.with_suffix(".json")
        json_path.write_text(
            json.dumps(report.to_dict(), indent=2),
            encoding="utf-8",
        )
    return path, json_path


def print_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2)


def concise_output(*values: str, limit: int = 3000) -> str:
    combined = "\n".join(value.strip() for value in values if value.strip())
    if len(combined) > limit:
        return combined[:limit] + "\n... output truncated ..."
    return combined

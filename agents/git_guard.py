from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from agents.models import CommandResult, GitStatus


class GitGuard:
    """Perform read-only Git inspection for one repository."""

    CONFLICT_CODES = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}

    def __init__(
        self,
        project_path: Path,
        protected_branches: tuple[str, ...] = ("main", "master"),
        timeout_seconds: int = 30,
    ) -> None:
        self.project_path = project_path.resolve()
        self.protected_branches = {
            branch.casefold() for branch in protected_branches
        }
        self.timeout_seconds = timeout_seconds

    def repository_root(self) -> Path | None:
        result = self._run_git(("rev-parse", "--show-toplevel"))
        if not result.passed:
            return None
        try:
            return Path(result.stdout.strip()).resolve()
        except OSError:
            return None

    def inspect(self) -> GitStatus:
        root = self.repository_root()
        if root is None or root != self.project_path:
            return GitStatus(
                project_path=self.project_path,
                is_repository=False,
                error="Path is not the root of a Git repository.",
            )

        branch_result = self._run_git(
            ("symbolic-ref", "--quiet", "--short", "HEAD")
        )
        detached = not branch_result.passed
        branch = "" if detached else branch_result.stdout.strip()
        tracked, untracked, conflicts = self._working_tree()

        return GitStatus(
            project_path=root,
            is_repository=True,
            branch=branch,
            detached_head=detached,
            protected_branch=(
                branch.casefold() in self.protected_branches
                if branch
                else False
            ),
            tracked_changes=tuple(tracked),
            untracked_files=tuple(untracked),
            conflicts=tuple(conflicts),
            remotes=self.remote_urls(),
            latest_commit=self.latest_commit(),
        )

    def changed_files(self) -> tuple[str, ...]:
        status = self.inspect()
        return tuple(
            dict.fromkeys(
                (*status.tracked_changes, *status.untracked_files)
            )
        )

    def remote_urls(self) -> dict[str, str]:
        result = self._run_git(("remote", "-v"))
        remotes: dict[str, str] = {}
        if not result.passed:
            return remotes
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] not in remotes:
                remotes[parts[0]] = self._sanitize_url(parts[1])
        return remotes

    def latest_commit(self) -> str:
        result = self._run_git(
            ("log", "-1", "--format=%H%x09%s%x09%aI")
        )
        return result.stdout.strip() if result.passed else ""

    def diff_stat(self) -> str:
        result = self._run_git(("diff", "HEAD", "--stat", "--"))
        return result.stdout.strip() if result.passed else ""

    def diff_check(self) -> CommandResult:
        return self._run_git(("diff", "HEAD", "--check", "--"))

    def diff_text(self) -> str:
        """Return tracked working-tree changes using fixed Git arguments."""
        result = self._run_git(
            ("diff", "HEAD", "--no-ext-diff", "--unified=0", "--")
        )
        return result.stdout if result.passed else ""

    def _working_tree(self) -> tuple[list[str], list[str], list[str]]:
        result = self._run_git(
            ("status", "--porcelain=v1", "-z", "--untracked-files=all")
        )
        if not result.passed:
            return [], [], []

        tracked: list[str] = []
        untracked: list[str] = []
        conflicts: list[str] = []
        entries = result.stdout.split("\x00")
        index = 0

        while index < len(entries):
            entry = entries[index]
            index += 1
            if not entry:
                continue

            code = entry[:2]
            path = entry[3:] if len(entry) > 3 else ""
            if code == "??":
                untracked.append(path)
            else:
                tracked.append(path)

            if code in self.CONFLICT_CODES:
                conflicts.append(path)

            if code[0:1] in {"R", "C"} and index < len(entries):
                destination = entries[index]
                index += 1
                if destination:
                    tracked.append(destination)

        return (
            list(dict.fromkeys(tracked)),
            list(dict.fromkeys(untracked)),
            list(dict.fromkeys(conflicts)),
        )

    def _run_git(self, arguments: tuple[str, ...]) -> CommandResult:
        command = ("git", *arguments)
        started = time.monotonic()
        creation_flags = (
            subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
        try:
            completed = subprocess.run(
                list(command),
                cwd=self.project_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                shell=False,
                creationflags=creation_flags,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return CommandResult(
                command=command,
                exit_code=None,
                duration_seconds=time.monotonic() - started,
                error=str(error),
                timed_out=isinstance(error, subprocess.TimeoutExpired),
            )

        return CommandResult(
            command=command,
            exit_code=completed.returncode,
            duration_seconds=time.monotonic() - started,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    @staticmethod
    def _sanitize_url(url: str) -> str:
        if "://" not in url:
            return url
        parsed = urlsplit(url)
        hostname = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        netloc = hostname + port
        if parsed.username or parsed.password:
            netloc = "***@" + netloc
        return urlunsplit(
            (
                parsed.scheme,
                netloc,
                parsed.path,
                "",
                "",
            )
        )

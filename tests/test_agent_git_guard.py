from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from agents.git_guard import GitGuard


class TemporaryRepository:
    def __init__(self, root: Path):
        self.root = root

    def git(self, *arguments: str, check: bool = True):
        return subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            shell=False,
            check=check,
        )

    def initialize(self, branch: str = "phase-test"):
        self.git("init")
        self.git("config", "user.email", "arc3-tests@example.invalid")
        self.git("config", "user.name", "ARC3 Tests")
        (self.root / "tracked.txt").write_text("base\n", encoding="utf-8")
        self.git("add", "tracked.txt")
        self.git("commit", "-m", "test baseline")
        self.git("branch", "-M", branch)


class GitGuardTests(unittest.TestCase):
    def test_valid_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            TemporaryRepository(root).initialize()

            status = GitGuard(root).inspect()

            self.assertTrue(status.is_repository)
            self.assertEqual(status.branch, "phase-test")
            self.assertTrue(status.clean)

    def test_invalid_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            status = GitGuard(Path(directory)).inspect()

            self.assertFalse(status.is_repository)
            self.assertTrue(status.unsafe)

    def test_protected_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            TemporaryRepository(root).initialize("main")

            status = GitGuard(root).inspect()

            self.assertTrue(status.protected_branch)
            self.assertTrue(status.unsafe)

    def test_detached_head(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = TemporaryRepository(root)
            repository.initialize()
            repository.git("checkout", "--detach")

            status = GitGuard(root).inspect()

            self.assertTrue(status.detached_head)
            self.assertTrue(status.unsafe)

    def test_dirty_working_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            TemporaryRepository(root).initialize()
            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")

            status = GitGuard(root).inspect()

            self.assertFalse(status.clean)
            self.assertIn("tracked.txt", status.tracked_changes)

    def test_untracked_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            TemporaryRepository(root).initialize()
            (root / "new file.txt").write_text("new\n", encoding="utf-8")

            status = GitGuard(root).inspect()

            self.assertIn("new file.txt", status.untracked_files)

    def test_merge_conflict_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = TemporaryRepository(root)
            repository.initialize()
            repository.git("checkout", "-b", "conflict-side")
            (root / "tracked.txt").write_text("side\n", encoding="utf-8")
            repository.git("add", "tracked.txt")
            repository.git("commit", "-m", "side change")
            repository.git("checkout", "phase-test")
            (root / "tracked.txt").write_text("mainline\n", encoding="utf-8")
            repository.git("add", "tracked.txt")
            repository.git("commit", "-m", "mainline change")
            repository.git(
                "merge",
                "conflict-side",
                check=False,
            )

            status = GitGuard(root).inspect()

            self.assertIn("tracked.txt", status.conflicts)
            self.assertTrue(status.unsafe)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path


@dataclass(frozen=True)
class FileRecord:
    path: Path
    size_bytes: int
    modified_at: datetime
    sha256: str

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class FileAnalysis:
    root: Path
    files: tuple[FileRecord, ...]
    duplicate_groups: tuple[tuple[FileRecord, ...], ...]


class FileAnalysisService:
    MAX_FILES = 5000
    HASH_CHUNK_SIZE = 1024 * 1024

    def analyze(self, directory: str | Path, recursive: bool = True) -> FileAnalysis:
        root = Path(directory).expanduser()
        if not root.exists() or not root.is_dir():
            raise ValueError("Select an existing directory to analyze.")
        candidates = root.rglob("*") if recursive else root.iterdir()
        files = []
        for path in candidates:
            if path.is_symlink() or not path.is_file():
                continue
            if len(files) >= self.MAX_FILES:
                raise ValueError(f"The scan exceeds the {self.MAX_FILES}-file safety limit.")
            stat = path.stat()
            files.append(FileRecord(
                path=path.resolve(), size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime),
                sha256=self.sha256(path),
            ))
        groups: dict[tuple[int, str], list[FileRecord]] = {}
        for record in files:
            groups.setdefault((record.size_bytes, record.sha256), []).append(record)
        duplicates = tuple(
            tuple(group) for group in groups.values() if len(group) > 1
        )
        return FileAnalysis(root.resolve(), tuple(files), duplicates)

    def sha256(self, path: str | Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(self.HASH_CHUNK_SIZE), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def format_size(size_bytes: int) -> str:
        value = float(size_bytes)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} TB"

    @staticmethod
    def export_report(analysis: FileAnalysis, destination: str | Path) -> None:
        duplicate_paths = {
            str(record.path) for group in analysis.duplicate_groups for record in group
        }
        report = {
            "schema_version": 1,
            "root": str(analysis.root),
            "file_count": len(analysis.files),
            "duplicate_group_count": len(analysis.duplicate_groups),
            "files": [
                {
                    "path": str(record.path), "size_bytes": record.size_bytes,
                    "modified_at": record.modified_at.isoformat(),
                    "sha256": record.sha256,
                    "duplicate": str(record.path) in duplicate_paths,
                }
                for record in analysis.files
            ],
        }
        with Path(destination).open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")

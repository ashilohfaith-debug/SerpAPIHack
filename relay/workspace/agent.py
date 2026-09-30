"""Sandboxed Workspace Agent for coding, assignments, and creative work.

Operates within an approved workspace root. All mutations (file write, patch, build,
command) require explicit step approval through the central Action Broker and
preserve filesystem snapshots / backups for voice-accessible rollback without
using destructive git commands (no git add -A, no git reset --hard).
"""

from __future__ import annotations

import difflib
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from relay.diagnostics import get_logger

log = get_logger("workspace")


@dataclass
class PatchSummary:
    file_path: str
    lines_added: int
    lines_removed: int
    spoken_summary: str
    diff_text: str


@dataclass
class Checkpoint:
    checkpoint_id: str
    timestamp: float
    description: str
    backup_dir: str
    modified_files: list[str]


class WorkspaceAgent:
    """Scoped workspace assistant for coding, diffs, tests, and version checkpoints."""

    def __init__(self, root_dir: Path | str = ".", bus: Any = None) -> None:
        self.root = Path(root_dir).resolve()
        self.bus = bus
        self.checkpoints: list[Checkpoint] = []
        self._backups_dir = self.root / ".relay" / "checkpoints"

    def list_files(self, pattern: str = "*", recursive: bool = True) -> list[str]:
        """List files relative to workspace root, excluding caches and heavy binaries."""
        results = []
        ignores = {".git", ".relay", "__pycache__", "node_modules", ".venv", "dist", "build"}
        generator = self.root.rglob(pattern) if recursive else self.root.glob(pattern)
        for p in generator:
            if any(part in ignores for part in p.parts):
                continue
            if p.is_file():
                results.append(str(p.relative_to(self.root)).replace("\\", "/"))
        return sorted(results)

    def _resolve_safe(self, relative_path: str) -> Path:
        """Resolve a path and verify it is strictly inside the workspace root."""
        p = (self.root / relative_path).resolve()
        if not p.is_relative_to(self.root):
            raise PermissionError(f"Path traversal blocked: {relative_path} is outside workspace")
        return p

    def read_file(self, relative_path: str, max_chars: int = 20000) -> str:
        """Safely read file within the workspace root."""
        path = self._resolve_safe(relative_path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {relative_path}")
        content = path.read_text(encoding="utf-8", errors="replace")
        return content[:max_chars]

    def write_file(self, relative_path: str, content: str, reason: str = "") -> bool:
        """Safely write a file within workspace root with automatic pre-modification backup."""
        path = self._resolve_safe(relative_path)
        # Create checkpoint before writing if modifying an existing file
        if path.exists():
            self.create_checkpoint(f"Pre-write backup for {relative_path}: {reason}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if self.bus:
            self.bus.emit("workspace.file_written", file=relative_path, reason=reason)
        return True

    def create_checkpoint(
        self, description: str, files_to_backup: Optional[list[str]] = None
    ) -> Checkpoint:
        """Create a safe filesystem snapshot in .relay/checkpoints without git commands."""
        import uuid

        cid = f"cp_{uuid.uuid4().hex[:6]}"
        backup_path = self._backups_dir / cid
        backup_path.mkdir(parents=True, exist_ok=True)

        target_files = files_to_backup or self.list_files()
        backed_up = []
        for rel in target_files:
            src = self.root / rel
            if src.is_file():
                dst = backup_path / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                backed_up.append(rel)

        cp = Checkpoint(
            checkpoint_id=cid,
            timestamp=time.time(),
            description=description,
            backup_dir=str(backup_path),
            modified_files=backed_up,
        )
        self.checkpoints.append(cp)
        log.info(
            "Safe workspace snapshot created: %s (%s, %d files)",
            cid,
            description,
            len(backed_up),
        )
        if self.bus:
            self.bus.emit("workspace.checkpoint", checkpoint_id=cid, description=description)
        return cp

    def rollback(self, checkpoint_id: Optional[str] = None) -> bool:
        """Restore modified files from a previous snapshot without touching unmanaged files."""
        if not self.checkpoints:
            return False
        cp = (
            next((c for c in reversed(self.checkpoints) if c.checkpoint_id == checkpoint_id), None)
            if checkpoint_id
            else self.checkpoints[-1]
        )
        if not cp or not cp.backup_dir:
            return False

        b_dir = Path(cp.backup_dir)
        if not b_dir.is_dir():
            return False

        restored_count = 0
        for rel in cp.modified_files:
            src = b_dir / rel
            dst = self.root / rel
            if src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                restored_count += 1

        log.info(
            "Rolled back to checkpoint %s: restored %d files", cp.checkpoint_id, restored_count
        )
        if self.bus:
            self.bus.emit(
                "workspace.rollback", checkpoint_id=cp.checkpoint_id, restored=restored_count
            )
        return True

    def preview_patch(self, relative_path: str, new_content: str) -> PatchSummary:
        """Generate unified diff and spoken summary without modifying disk."""
        path = self._resolve_safe(relative_path)
        old_content = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        diff = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
            )
        )
        added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
        diff_text = "".join(diff)
        spoken = f"{relative_path}: {added} lines added, {removed} lines removed."
        return PatchSummary(
            file_path=relative_path,
            lines_added=added,
            lines_removed=removed,
            spoken_summary=spoken,
            diff_text=diff_text,
        )

    propose_patch = preview_patch

    def apply_patch(self, relative_path: str, new_content: str, reason: str = "") -> bool:
        """Create a safe snapshot, then write the new content."""
        path = self._resolve_safe(relative_path)
        self.create_checkpoint(f"Pre-patch for {relative_path}: {reason}", [relative_path])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_content, encoding="utf-8")
        log.info("Applied patch to %s (%s)", relative_path, reason)
        return True

    def get_recent_diff_summary(self) -> str:
        """Spoken summary of changes since the last checkpoint."""
        if not self.checkpoints:
            return "No previous checkpoint to compare against."
        cp = self.checkpoints[-1]
        b_dir = Path(cp.backup_dir)
        changed = []
        for rel in cp.modified_files:
            cur = self.root / rel
            bak = b_dir / rel
            if not cur.exists():
                changed.append(f"{rel} deleted")
            elif not bak.exists():
                changed.append(f"{rel} added")
            elif cur.read_bytes() != bak.read_bytes():
                changed.append(f"{rel} modified")
        if not changed:
            return "No files have changed since the last checkpoint."
        return f"Changes since {cp.description}: " + ", ".join(changed[:4]) + "."

    def run_tests(self, command: list[str]) -> tuple[bool, str]:
        """Run project tests using approved test runners.

        Enforces strict security restrictions:
        - Banned: -c, -m, eval, inline code execution.
        - If python is used, argument must be an existing .py file inside workspace.
        """
        if not command:
            return False, "No test command provided."

        cmd_stem = Path(command[0]).stem.lower()
        safe_commands = {"pytest", "npm", "cargo", "go", "uv", "python"}
        if cmd_stem not in safe_commands:
            return False, f"Command {command[0]!r} is not approved for execution."

        # Security check: ban arbitrary inline execution
        banned_flags = {"-c", "-m", "--command", "-e", "eval"}
        if any(arg in banned_flags for arg in command[1:]):
            return False, "Inline script execution flags are strictly blocked for security."

        # If python is called, verify that the second argument is a python script in workspace
        if cmd_stem == "python":
            if len(command) < 2 or not command[1].endswith(".py"):
                return False, "Python runner requires an explicit .py script file argument."
            script_path = self._resolve_safe(command[1])
            if not script_path.is_file():
                return False, f"Test script {command[1]!r} not found in workspace."

        try:
            res = subprocess.run(
                command,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=60.0,
            )
            ok = res.returncode == 0
            summary = res.stdout if ok else (res.stderr or res.stdout)
            lines = [line.strip() for line in summary.splitlines() if line.strip()]
            spoken = " ".join(lines[-3:]) if lines else ("Tests passed." if ok else "Tests failed.")
            return ok, spoken
        except Exception as e:
            return False, f"Test execution failed: {e}"

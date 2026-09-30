"""Sandboxed Workspace Agent for coding, assignments, and creative work.

Operates within an approved workspace root. All mutations (file write, patch, build,
command) require explicit step approval through the central Action Broker and
preserve Git checkpoints / backups for voice-accessible rollback.
"""

from __future__ import annotations

import difflib
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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
    git_commit: Optional[str] = None
    backup_dir: Optional[str] = None


class WorkspaceAgent:
    """Scoped workspace assistant for coding, diffs, tests, and version checkpoints."""

    def __init__(self, root_dir: Path | str) -> None:
        self.root = Path(root_dir).resolve()
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

    def read_file(self, relative_path: str, max_chars: int = 20000) -> str:
        """Safely read file within the workspace root."""
        path = (self.root / relative_path).resolve()
        if not path.is_relative_to(self.root):
            raise PermissionError("Access outside workspace root is blocked")
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {relative_path}")
        content = path.read_text(encoding="utf-8", errors="replace")
        return content[:max_chars]

    def create_checkpoint(self, description: str) -> Checkpoint:
        """Create Git checkpoint or filesystem snapshot before modifying files."""
        import uuid
        cid = f"cp_{uuid.uuid4().hex[:6]}"
        git_commit = None
        backup_path = None

        # Check if root is a git repository
        if (self.root / ".git").is_dir():
            try:
                # Stage and commit locally
                subprocess.run(
                    ["git", "add", "-A"],
                    cwd=str(self.root),
                    check=True,
                    capture_output=True,
                )
                commit_res = subprocess.run(
                    ["git", "commit", "-m", f"Relay Checkpoint: {description}"],
                    cwd=str(self.root),
                    capture_output=True,
                    text=True,
                )
                if commit_res.returncode == 0:
                    git_commit = subprocess.check_output(
                        ["git", "rev-parse", "HEAD"],
                        cwd=str(self.root),
                        text=True,
                    ).strip()
            except Exception as e:
                log.warning("git checkpoint failed, falling back to file snapshot: %s", e)

        if not git_commit:
            # File snapshot fallback
            self._backups_dir.mkdir(parents=True, exist_ok=True)
            backup_path = str(self._backups_dir / cid)
            # Copy text/code files
            for rel in self.list_files():
                src = self.root / rel
                dst = Path(backup_path) / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

        cp = Checkpoint(
            checkpoint_id=cid,
            timestamp=time.time(),
            description=description,
            git_commit=git_commit,
            backup_dir=backup_path,
        )
        self.checkpoints.append(cp)
        log.info("Workspace checkpoint created: %s (%s)", cid, description)
        return cp

    def rollback(self, checkpoint_id: Optional[str] = None) -> bool:
        """Restore workspace to a previous checkpoint."""
        if not self.checkpoints:
            return False
        cp = (
            next((c for c in reversed(self.checkpoints) if c.checkpoint_id == checkpoint_id), None)
            if checkpoint_id
            else self.checkpoints[-1]
        )
        if not cp:
            return False

        if cp.git_commit:
            try:
                subprocess.run(
                    ["git", "reset", "--hard", cp.git_commit],
                    cwd=str(self.root),
                    check=True,
                    capture_output=True,
                )
                return True
            except Exception as e:
                log.error("git rollback failed: %s", e)
                return False

        if cp.backup_dir and Path(cp.backup_dir).is_dir():
            for p in Path(cp.backup_dir).rglob("*"):
                if p.is_file():
                    rel = p.relative_to(cp.backup_dir)
                    dst = self.root / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, dst)
            return True
        return False

    def propose_patch(self, relative_path: str, new_content: str) -> PatchSummary:
        """Generate a structured patch and accessible diff summary before applying."""
        path = (self.root / relative_path).resolve()
        if not path.is_relative_to(self.root):
            raise PermissionError("Access outside workspace root is blocked")

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

        spoken = (
            f"Patch for {Path(relative_path).name}: {added} lines added, "
            f"{removed} lines removed."
        )
        return PatchSummary(
            file_path=relative_path,
            lines_added=added,
            lines_removed=removed,
            spoken_summary=spoken,
            diff_text="".join(diff),
        )

    def apply_patch(self, relative_path: str, new_content: str) -> bool:
        """Apply approved change to workspace file."""
        path = (self.root / relative_path).resolve()
        if not path.is_relative_to(self.root):
            raise PermissionError("Access outside workspace root is blocked")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_content, encoding="utf-8")
        return True

    def run_tests(self, command: list[str]) -> tuple[bool, str]:
        """Run project tests (e.g. pytest, npm test) in workspace directory."""
        safe_commands = {"pytest", "python", "npm", "cargo", "go", "uv"}
        if not command or command[0] not in safe_commands:
            return False, f"Command {command[0] if command else ''} is not approved for execution"

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
            # Take last 5 lines for concise voice feedback
            lines = [line.strip() for line in summary.splitlines() if line.strip()]
            spoken = " ".join(lines[-3:]) if lines else ("Tests passed." if ok else "Tests failed.")
            return ok, spoken
        except Exception as e:
            return False, f"Test execution failed: {e}"

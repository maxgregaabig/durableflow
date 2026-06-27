"""Isolated workspace and idempotent mutating tool layer for CLEAR.

Generated applications live inside a dedicated directory outside the
DurableFlow source tree. Every mutating tool call is scoped to that
directory and recorded through the durable ``side_effect_log`` so that a
crash-retry never duplicates a write (spec §6.5, §6.6, CLEAR-UNIT-004).

This module is Python standard library only.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.store import WorkflowStore


class WorkspaceViolationError(Exception):
    """A mutating tool tried to touch a path outside the workspace."""


class PatchApplicationError(Exception):
    """A search/replace patch could not be applied unambiguously."""


_SEARCH_START = "<<<<<<< SEARCH"
_DIVIDER = "======="
_REPLACE_END = ">>>>>>> REPLACE"


def apply_search_replace(base: str, patch: str) -> tuple[str, int]:
    """Apply a search/replace ``patch`` to ``base``; return (result, n_blocks).

    Each block is::

        <<<<<<< SEARCH
        ...
        =======
        ...
        >>>>>>> REPLACE

    SEARCH text must occur exactly once in the file at that point (a zero
    or multi match raises :class:`PatchApplicationError`). Empty SEARCH
    text inserts the replacement at the end of the file. Blocks are
    applied in order, so earlier replacements are visible to later ones.
    """
    blocks = _parse_patch_blocks(patch)
    if not blocks:
        raise PatchApplicationError("patch contains no search/replace blocks")
    current = base
    applied = 0
    for index, (search, replacement) in enumerate(blocks, start=1):
        if search == "":
            # insertion: append replacement (plus a separating newline if needed)
            sep = "" if current.endswith("\n") or current == "" else "\n"
            current = current + sep + replacement
            applied += 1
            continue
        occurrences = current.count(search)
        if occurrences == 0:
            raise PatchApplicationError(
                f"patch block {index}: SEARCH text not found in file"
            )
        if occurrences > 1:
            raise PatchApplicationError(
                f"patch block {index}: SEARCH text matched {occurrences} times; "
                "make it unique"
            )
        current = current.replace(search, replacement, 1)
        applied += 1
    return current, applied


def _parse_patch_blocks(patch: str) -> list[tuple[str, str]]:
    """Parse a search/replace patch into (search, replacement) blocks."""
    blocks: list[tuple[str, str]] = []
    lines = patch.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].strip() == _SEARCH_START:
            search_lines: list[str] = []
            i += 1
            while i < len(lines) and lines[i].strip() != _DIVIDER:
                search_lines.append(lines[i])
                i += 1
            if i >= len(lines):
                raise PatchApplicationError("patch block missing ======= divider")
            i += 1  # skip divider
            replace_lines: list[str] = []
            while i < len(lines) and lines[i].strip() != _REPLACE_END:
                replace_lines.append(lines[i])
                i += 1
            if i >= len(lines):
                raise PatchApplicationError("patch block missing >>>>>>> REPLACE end")
            i += 1  # skip end marker
            blocks.append(("\n".join(search_lines), "\n".join(replace_lines)))
        else:
            i += 1
    return blocks


@dataclass(frozen=True)
class WriteResult:
    """Result of an idempotent mutating tool call.

    ``already_applied`` is True when the call replayed an existing
    side-effect (i.e. no new write occurred) so callers and tests can
    link retries back to the original write.
    """

    path: str
    bytes_written: int
    already_applied: bool
    idempotency_key: str
    digest: str


@dataclass(frozen=True)
class TestRunResult:
    """Result of running a test command. Non-mutating on source."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    log_path: str
    passed: bool


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Workspace:
    """An isolated directory that hosts the generated application.

    All mutating tool calls validate the resolved path is contained in
    ``root`` before touching the filesystem, and record the side effect
    through ``WorkflowStore.log_side_effect`` using an idempotency key
    derived from ``workflow_id | phase | attempt | path | content``.
    """

    def __init__(self, root: str | Path, store: "WorkflowStore | None" = None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = store

    # --- boundary ---------------------------------------------------------

    def resolve(self, rel_path: str) -> Path:
        """Resolve ``rel_path`` inside the workspace, rejecting escapes.

        Raises :class:`WorkspaceViolationError` if the resolved path is
        not contained in ``self.root``.
        """
        candidate = (self.root / rel_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceViolationError(
                f"path '{rel_path}' resolves outside the generated workspace"
            ) from exc
        return candidate

    # --- non-mutating tools ----------------------------------------------

    def read_file(self, rel_path: str) -> str:
        path = self.resolve(rel_path)
        return path.read_text(encoding="utf-8")

    def git_diff(self) -> str:
        """Return ``git diff`` of the workspace, or a marker if not a repo."""
        try:
            completed = subprocess.run(
                ["git", "diff", "--no-color"],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return "(git not available in workspace)"
        return completed.stdout or "(no unstaged changes)"

    # --- mutating tools ---------------------------------------------------

    def _idempotency_key(
        self,
        workflow_id: str,
        phase: int | str,
        attempt: int,
        rel_path: str,
        content_digest: str,
    ) -> str:
        payload = "|".join(
            [workflow_id, str(phase), str(attempt), rel_path, content_digest]
        )
        return f"clear-write-{_digest(payload)}"

    def write_file(
        self,
        rel_path: str,
        content: str,
        *,
        workflow_id: str,
        phase: int | str,
        attempt: int,
        step_name: str = "phase_runner",
    ) -> WriteResult:
        """Idempotently write ``content`` to ``rel_path``.

        The idempotency key captures the exact (workflow, phase, attempt,
        path, content). Replaying the same key returns the cached result
        and performs no new write side effect — the durable
        ``side_effect_log`` links the retry to the original write.
        """
        content_digest = _digest(content)
        key = self._idempotency_key(workflow_id, phase, attempt, rel_path, content_digest)
        if self.store is not None:
            cached = self.store.get_side_effect(key)
            if cached is not None:
                return WriteResult(
                    path=rel_path,
                    bytes_written=int(cached["bytes_written"]),
                    already_applied=True,
                    idempotency_key=key,
                    digest=content_digest,
                )

        path = self.resolve(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8")
        path.write_bytes(data)

        if self.store is not None:
            self.store.log_side_effect(
                key,
                workflow_id,
                step_name,
                {
                    "path": rel_path,
                    "bytes_written": len(data),
                    "digest": content_digest,
                    "phase": phase,
                    "attempt": attempt,
                },
            )
        return WriteResult(
            path=rel_path,
            bytes_written=len(data),
            already_applied=False,
            idempotency_key=key,
            digest=content_digest,
        )

    def apply_patch(
        self,
        rel_path: str,
        patch: str,
        *,
        workflow_id: str,
        phase: int | str,
        attempt: int,
        step_name: str = "phase_runner",
    ) -> WriteResult:
        """Idempotently apply a search/replace patch to ``rel_path``.

        ``patch`` is one or more blocks of the form::

            <<<<<<< SEARCH
            <original text>
            =======
            <replacement text>
            >>>>>>> REPLACE

        Each SEARCH block must occur exactly once in the current file (an
        ambiguous or missing match raises :class:`PatchApplicationError`).
        The fully-patched result is written through :meth:`write_file`, so
        the idempotency key captures the resulting content — replaying the
        same patch against an already-patched file is a no-op (its SEARCH
        block is gone, so there is nothing to replace and the content is
        unchanged).
        """
        path = self.resolve(rel_path)
        base = path.read_text(encoding="utf-8") if path.exists() else ""
        patched, _applied = apply_search_replace(base, patch)
        return self.write_file(
            rel_path,
            patched,
            workflow_id=workflow_id,
            phase=phase,
            attempt=attempt,
            step_name=step_name,
        )

    def run_tests(
        self,
        command: str,
        *,
        workflow_id: str,
        phase: int | str,
        attempt: int,
        step_name: str = "phase_runner",
    ) -> TestRunResult:
        """Run a test command in the workspace, archiving full output.

        Source is not mutated; the captured stdout/stderr is archived to
        ``test-results/`` so evidence is on disk, not prose-only.
        """
        log_dir = self.resolve("test-results")
        log_dir.mkdir(parents=True, exist_ok=True)
        safe_phase = str(phase).replace("/", "-")
        log_path = log_dir / f"phase-{safe_phase}-attempt-{attempt}.log"

        try:
            completed = subprocess.run(
                command,
                cwd=self.root,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.SubprocessError as exc:
            exit_code = 1
            stdout = ""
            stderr = f"test runner error: {exc}"

        archive = (
            f"$ {command}\n"
            f"exit_code: {exit_code}\n\n"
            f"--- stdout ---\n{stdout}\n"
            f"--- stderr ---\n{stderr}\n"
        )
        log_path.write_text(archive, encoding="utf-8")
        return TestRunResult(
            command=command,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            log_path=str(log_path.relative_to(self.root)),
            passed=(exit_code == 0),
        )

"""Bounded, durable, read-only collection of exact runtime completion events.

No constructor I/O and no Herdr actions. EOF bootstrap is persisted, so restarting
the server resumes cursors rather than forgetting work completed while offline.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .claude_activity import exact_goal_command, _projects_root
from .goal_monitor import _sessions_root
from .notifications import emit_event


def _hash(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _native_epoch(goal: dict, session: str) -> str | None:
    if isinstance(goal.get("id"), str) and goal["id"].strip():
        return goal["id"]
    if isinstance(goal.get("createdAt"), str):
        try:
            created = datetime.fromisoformat(goal["createdAt"].replace("Z", "+00:00"))
            if created.tzinfo is not None:
                return f"{session}:created:{created.isoformat()}"
        except ValueError:
            pass
    return None


class RuntimeEventCollector:
    def __init__(self, store, *, max_files: int = 64, max_bytes: int = 2 * 1024 * 1024,
                 max_file_bytes: int = 256 * 1024, max_inventory: int = 2048) -> None:
        self.store = store
        self.max_files = max_files
        self.max_bytes = max_bytes
        self.max_file_bytes = max_file_bytes
        self.max_inventory = max_inventory
        self._position = 0
        # Coverage is earned across bounded batches, not inferred from how many
        # paths fit in one poll. A changed file loses its previous coverage.
        self._checked_inventory: dict[tuple[str, Path], tuple[int, ...]] = {}
        self._cycle_errors: set[tuple[str, Path]] = set()
        self._project_signature: tuple | None = None

    def _inventory(self) -> tuple[list[tuple[str, Path]], bool]:
        paths: list[tuple[str, Path]] = []
        directories = entries = 0
        for provider, root in (("codex", _sessions_root()), ("claude", _projects_root())):
            if not root.is_dir():
                continue
            pending = [root]
            while pending:
                directory = pending.pop()
                directories += 1
                if directories > 512:
                    return paths, True
                with os.scandir(directory) as listing:
                    for entry in listing:
                        entries += 1
                        if entries > self.max_inventory * 8:
                            return paths, True
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                            continue
                        name = entry.name
                        if entry.is_file(follow_symlinks=False) and name.endswith(".jsonl") and (provider == "claude" or name.startswith("rollout-")):
                            paths.append((provider, Path(entry.path)))
                            if len(paths) > self.max_inventory:
                                return paths[:self.max_inventory], True
        return sorted(paths, key=lambda item: (item[0], str(item[1]))), False

    def _health(self, status: str) -> None:
        with self.store._connect() as connection:
            connection.execute("INSERT INTO collector_health VALUES ('runtime',?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at",
                               (status, datetime.now(timezone.utc).isoformat()))

    @staticmethod
    def _key(provider: str, path: Path) -> str:
        return f"runtime-file:{provider}:{_hash(str(path.resolve()))}"

    @staticmethod
    def _generation(path: Path) -> str:
        info = path.stat()
        return f"{info.st_dev}:{info.st_ino}:{getattr(info, 'st_birthtime_ns', 0)}"

    @staticmethod
    def _fingerprint(path: Path) -> tuple[int, ...]:
        info = path.stat()
        return (info.st_dev, info.st_ino, getattr(info, "st_birthtime_ns", 0), info.st_size, info.st_mtime_ns)

    @staticmethod
    def _save(connection, key: str, generation: str, offset: int, context: dict) -> None:
        connection.execute("""INSERT INTO collector_cursors VALUES (?,?,?,?,?)
            ON CONFLICT(source_key) DO UPDATE SET generation=excluded.generation,
            offset=excluded.offset,context_json=excluded.context_json,updated_at=excluded.updated_at""",
            (key, generation, offset, json.dumps(context), datetime.now(timezone.utc).isoformat()))

    def bootstrap(self) -> None:
        try:
            paths, truncated = self._inventory()
            with self.store._connect() as connection:
                initialized = connection.execute("SELECT 1 FROM collector_cursors WHERE source_key='runtime-bootstrap'").fetchone()
                if not initialized:
                    # Inventory only: baseline every discovered file, even if its
                    # metadata will be processed in a later bounded poll batch.
                    for provider, path in paths:
                        size = path.stat().st_size
                        self._save(connection, self._key(provider, path), self._generation(path), 0,
                                   {"baseline_eof": size})
                    if not truncated:
                        self._save(connection, "runtime-bootstrap", "v1", 0, {})
            self._health("stale" if truncated or paths else "healthy")
        except (OSError, ValueError, sqlite3.Error):
            self._health("error")

    def _projects(self) -> list[tuple[str, Path]]:
        with self.store._connect() as connection:
            rows = connection.execute("SELECT id,source_path FROM projects WHERE source_path IS NOT NULL").fetchall()
        return [(row[0], Path(row[1]).resolve()) for row in rows]

    @staticmethod
    def _project(cwd: str, projects: list[tuple[str, Path]]) -> str | None:
        path = Path(cwd).resolve()
        matches = [(identifier, root) for identifier, root in projects if path == root or root in path.parents]
        if not matches:
            return None
        depth = max(len(root.parts) for _, root in matches)
        best = [identifier for identifier, root in matches if len(root.parts) == depth]
        return best[0] if len(best) == 1 else None

    def _metadata(self, provider: str, path: Path, projects: list[tuple[str, Path]]) -> dict | None:
        # Read only a bounded header until a project/session is authenticated by
        # source metadata. Never search unrelated transcript bodies for projects.
        with path.open("rb") as handle:
            header = handle.read(min(self.max_file_bytes, 64 * 1024))
        for raw in header.splitlines():
            try:
                record = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(record, dict):
                continue
            if provider == "codex":
                if record.get("type") != "session_meta":
                    return None
                data = record.get("payload") if isinstance(record.get("payload"), dict) else {}
                session = data.get("session_id") or data.get("id")
                cwd = data.get("cwd")
            else:
                if record.get("isSidechain") is True:
                    continue
                session = record.get("sessionId") or record.get("session_id")
                cwd = record.get("cwd")
            if isinstance(session, str) and session and isinstance(cwd, str):
                project = self._project(cwd, projects)
                if project is None:
                    return None
                return {"provider": provider, "session": session, "project": project, "cwd": str(Path(cwd).resolve())}
        return None

    def _record(self, connection, record: dict, context: dict, projects, *, deliver: bool) -> None:
        if not isinstance(record, dict) or record.get("isSidechain") is True:
            return
        provider, session = context["provider"], context["session"]
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        event_session = record.get("sessionId") or record.get("session_id") or payload.get("session_id")
        if event_session is not None and event_session != session:
            return
        cwd = record.get("cwd") or (payload.get("cwd") if record.get("type") == "session_meta" else None)
        if cwd is not None and (not isinstance(cwd, str) or self._project(cwd, projects) != context["project"]):
            return
        if record.get("type") == "session_meta" and (payload.get("id") or payload.get("session_id")) != session:
            return
        event_type = None
        identity = {"provider": provider, "runtime_session_id": session}
        source_identity = None
        if provider == "codex" and record.get("type") == "event_msg":
            kind = payload.get("type")
            if kind in {"task_complete", "turn_completed"}:
                turn = payload.get("turn_id")
                if isinstance(turn, str) and turn:
                    event_type, source_identity = "agent.turn_completed", turn
                    identity["turn_id"] = turn
            elif kind in {"thread_goal_updated", "thread_goal_created", "thread_goal_reset"}:
                goal = payload.get("goal") if isinstance(payload.get("goal"), dict) else {}
                objective = _hash(str(goal.get("objective") or ""))
                epoch = _native_epoch(goal, session)
                if kind in {"thread_goal_created", "thread_goal_reset"}:
                    event_id = record.get("uuid") or record.get("id")
                    context["creation_epoch"] = epoch or (f"{session}:event:{event_id}" if isinstance(event_id, str) and event_id else None)
                    context["creation_objective"] = objective
                if not epoch and context.get("creation_objective") == objective:
                    epoch = context.get("creation_epoch")
                context["epoch"] = epoch
                if goal.get("status") == "complete" and epoch:
                    event_type, source_identity = "agent.goal_completed", epoch
                    identity["goal_epoch_id"] = epoch
        elif provider == "claude":
            command = exact_goal_command(record)
            if command:
                event_id = record.get("uuid")
                context["epoch"] = f"{session}:command:{event_id}" if isinstance(event_id, str) and event_id else None
                context["objective"] = _hash(command)
            attachment = record.get("attachment") if isinstance(record.get("attachment"), dict) else {}
            if attachment.get("type") == "goal_status" and isinstance(attachment.get("condition"), str):
                objective = _hash(attachment["condition"].strip())
                native = attachment.get("goal_id") or attachment.get("goalId")
                if isinstance(native, str) and native.strip():
                    context["epoch"] = native
                elif context.get("objective") != objective:
                    context["epoch"] = None
                context["objective"] = objective
                if attachment.get("met") is True and context.get("epoch"):
                    event_type, source_identity = "agent.goal_completed", context["epoch"]
                    identity["goal_epoch_id"] = context["epoch"]
        if event_type:
            event_key = f"runtime:{context['project']}:{provider}:{session}:{event_type}:{source_identity}"
            seen_key = f"runtime-seen:{_hash(event_key)}"
            seen = connection.execute("SELECT 1 FROM collector_cursors WHERE source_key=?", (seen_key,)).fetchone()
            if deliver and not seen:
                emit_event(connection, source_key=event_key, event_type=event_type,
                           project_id=context["project"], entity_id=session, identity=identity,
                           occurred_at=record.get("timestamp") if isinstance(record.get("timestamp"), str) else None)
            # Tombstones prevent historical bootstrap completions becoming new
            # notifications when a source file is copied or replayed later.
            self._save(connection, seen_key, "v1", 0, {})

    def _file(self, provider: str, path: Path, projects, budget: int) -> tuple[int, bool]:
        key, generation = self._key(provider, path), self._generation(path)
        metadata = self._metadata(provider, path, projects)
        if metadata is None:
            return 0, False
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM collector_cursors WHERE source_key=?", (key,)).fetchone()
            context = json.loads(row["context_json"]) if row else {}
            offset = row["offset"] if row else 0
            size = path.stat().st_size
            with path.open("rb") as handle:
                anchor_start = max(0, offset - 64)
                handle.seek(anchor_start)
                anchor = _hash(handle.read(offset - anchor_start))
                rotated = row is not None and (row["generation"] != generation or size < offset or
                    (context.get("anchor") is not None and context["anchor"] != anchor))
                if rotated:
                    offset, context = 0, {}
                if context.get("session") not in (None, metadata["session"]) or context.get("project") not in (None, metadata["project"]):
                    # Different runtime/project at the same path is a new source;
                    # its header must authenticate the new identity first.
                    offset, context = 0, {}
                context.update(metadata)
                handle.seek(offset)
                data = handle.read(min(budget, self.max_file_bytes))
                boundary = data.rfind(b"\n")
                backlog = offset + len(data) < size
                if boundary >= 0:
                    complete = data[:boundary + 1]
                    position = offset
                    for raw in complete.splitlines(keepends=True):
                        deliver = position >= context.get("baseline_eof", 0)
                        position += len(raw)
                        try:
                            self._record(connection, json.loads(raw), context, projects, deliver=deliver)
                        except (ValueError, UnicodeDecodeError):
                            continue
                    offset += len(complete)
                elif backlog:
                    # An oversized record is unsupported, never parsed from a
                    # partial window or silently treated as fully collected.
                    backlog = True
                handle.seek(max(0, offset - 64))
                context["anchor"] = _hash(handle.read(min(offset, 64)))
                self._save(connection, key, generation, offset, context)
                # A trailing partial record is still uncollected even if the
                # read reached EOF. It must keep health stale until completed.
                return len(data), backlog or offset < path.stat().st_size

    def poll(self) -> None:
        try:
            with self.store._connect() as connection:
                initialized = connection.execute("SELECT 1 FROM collector_cursors WHERE source_key='runtime-bootstrap'").fetchone()
            if not initialized:
                self.bootstrap()
                return
            paths, truncated = self._inventory()
            projects = self._projects()
            project_signature = tuple(sorted((identifier, str(root)) for identifier, root in projects))
            if project_signature != self._project_signature:
                self._checked_inventory.clear()
                self._project_signature = project_signature
            inventory = {key: self._fingerprint(key[1]) for key in paths}
            self._checked_inventory = {
                key: fingerprint for key, fingerprint in self._checked_inventory.items()
                if inventory.get(key) == fingerprint
            }
            self._cycle_errors.intersection_update(inventory)
            if not paths:
                with self.store._connect() as connection:
                    known_sources = connection.execute(
                        "SELECT 1 FROM collector_cursors WHERE source_key LIKE 'runtime-file:%' LIMIT 1"
                    ).fetchone()
                self._health("stale" if known_sources else "healthy")
                return
            start = self._position % len(paths)
            ordered = paths[start:] + paths[:start]
            used = count = 0
            for provider, path in ordered[:self.max_files]:
                remaining = self.max_bytes - used
                if remaining <= 0:
                    break
                key = (provider, path)
                try:
                    consumed, backlog = self._file(provider, path, projects, remaining)
                    unchanged_during_read = self._fingerprint(path) == inventory[key]
                except (OSError, ValueError, sqlite3.Error):
                    self._cycle_errors.add(key)
                    self._checked_inventory.pop(key, None)
                    count += 1
                    continue
                used += consumed
                count += 1
                self._cycle_errors.discard(key)
                if backlog or not unchanged_during_read:
                    self._checked_inventory.pop(key, None)
                else:
                    self._checked_inventory[key] = inventory[key]
            self._position = (start + count) % len(paths)
            stale = truncated or len(self._checked_inventory) < len(inventory)
            self._health("error" if self._cycle_errors else "stale" if stale else "healthy")
        except (OSError, ValueError, sqlite3.Error):
            self._health("error")

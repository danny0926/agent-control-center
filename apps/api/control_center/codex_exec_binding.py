from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .goal_monitor import _is_within_project, _sessions_root

_REDIRECT = re.compile(r"(?:^|\s)>\s*(\"[^\"]+\"|'[^']+'|[^\s]+)\s*$")
_THREAD_ID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


@dataclass(frozen=True)
class ChildSessionBinding:
    thread_id: str
    rollout_path: Path
    observed_model: str | None
    cwd: str
    originator: str | None


def extract_events_path(command: str) -> Path | None:
    """只接受命令尾端的 stdout 導向，避免把 stderr 或追加導向當成事件檔。"""
    try:
        match = _REDIRECT.search(command)
        if not match:
            return None
        raw = match.group(1)
        if raw[:1] == raw[-1:] and raw[:1] in {"'", '"'}:
            raw = raw[1:-1]
        return Path(raw) if raw else None
    except (TypeError, ValueError):
        return None


def bind_child_session(command: str, project_root: str) -> ChildSessionBinding | None:
    try:
        events_path = extract_events_path(command)
        if events_path is None:
            return None
        if not events_path.is_absolute():
            events_path = Path(project_root) / events_path
        with events_path.open("rb") as handle:
            event = json.loads(handle.readline(64 * 1024))
        thread_id = event.get("thread_id")
        if event.get("type") != "thread.started" or not isinstance(thread_id, str) or not _THREAD_ID.fullmatch(thread_id):
            return None
        root = _sessions_root()
        matches = list(root.rglob(f"rollout-*-{thread_id}.jsonl")) if root.is_dir() else []
        if len(matches) != 1:
            return None
        rollout_path = matches[0]
        with rollout_path.open("rb") as handle:
            first = json.loads(handle.readline(64 * 1024))
            if first.get("type") != "session_meta":
                return None
            payload = first.get("payload") or {}
            cwd = payload.get("cwd")
            if not isinstance(cwd, str) or not _is_within_project(cwd, project_root):
                return None
            originator = payload.get("originator") if isinstance(payload.get("originator"), str) else None
            observed_model = None
            scanned = 0
            for _ in range(199):
                line = handle.readline(64 * 1024)
                if not line:
                    break
                scanned += len(line)
                if scanned > 1024 * 1024:
                    break
                item = json.loads(line)
                if item.get("type") == "turn_context":
                    model = (item.get("payload") or {}).get("model")
                    observed_model = model if isinstance(model, str) else None
                    break
        return ChildSessionBinding(thread_id, rollout_path, observed_model, cwd, originator)
    except Exception:
        return None

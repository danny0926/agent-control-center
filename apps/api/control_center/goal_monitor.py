from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .herdr_adapter import HerdrUnavailable, list_project_agents, read_agent_output
from .models import GoalSessionCandidate, MonitorSnapshot


SESSION_ID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_DISCOVERY_LOCK = threading.Lock()
_DISCOVERY_CACHE: dict[tuple[str, str], tuple[float, list[GoalSessionCandidate]]] = {}


class GoalMonitorUnavailable(RuntimeError):
    pass


def _sessions_root() -> Path:
    configured = os.environ.get("CODEX_SESSIONS_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".codex" / "sessions"


def _is_within_project(raw_path: str, project_root: str) -> bool:
    try:
        path = Path(raw_path).resolve()
        root = Path(project_root).resolve()
        return path == root or root in path.parents
    except OSError:
        return False


def _session_metadata(path: Path) -> tuple[str, str] | None:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            first = json.loads(handle.readline())
    except (OSError, json.JSONDecodeError):
        return None
    if first.get("type") != "session_meta":
        return None
    payload = first.get("payload") or {}
    session_id = payload.get("session_id") or payload.get("id")
    cwd = payload.get("cwd")
    if not isinstance(session_id, str) or not isinstance(cwd, str):
        return None
    return session_id, cwd


def _reverse_lines(path: Path, chunk_size: int = 64 * 1024, max_bytes: int | None = None):
    """Yield JSONL records newest-first without loading a large rollout."""
    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        floor = max(0, position - max_bytes) if max_bytes is not None else 0
        remainder = b""
        while position > floor:
            read_size = min(chunk_size, position - floor)
            position -= read_size
            handle.seek(position)
            parts = (handle.read(read_size) + remainder).split(b"\n")
            remainder = parts[0]
            for line in reversed(parts[1:]):
                if line:
                    yield line
        if remainder:
            yield remainder


def _goal_from_transcript(
    path: Path, session_id: str, cwd: str, *, max_scan_bytes: int | None = None
) -> GoalSessionCandidate | None:
    latest: dict | None = None
    creation: dict | None = None
    try:
        for line in _reverse_lines(path, max_bytes=max_scan_bytes):
            # Codex normally writes compact JSON, but the semantic event
            # should not depend on a particular whitespace layout.
            if b"thread_goal_" not in line:
                continue
            try:
                item = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if item.get("type") != "event_msg":
                continue
            event_type = (item.get("payload") or {}).get("type")
            if event_type in {"thread_goal_updated", "thread_goal_created", "thread_goal_reset"}:
                if latest is None:
                    latest = item
                    latest_goal = (latest.get("payload") or {}).get("goal") or {}
                    if latest_goal.get("id") or latest_goal.get("createdAt"):
                        break
                if event_type in {"thread_goal_created", "thread_goal_reset"}:
                    creation = item
                    break
    except OSError as error:
        raise GoalMonitorUnavailable("無法讀取指定的 Codex goal transcript。") from error
    if latest is None:
        return None
    goal = (latest.get("payload") or {}).get("goal") or {}
    objective = goal.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        return None
    timestamp = goal.get("updatedAt") or latest.get("timestamp")
    goal_id = goal.get("id") if isinstance(goal.get("id"), str) and goal["id"].strip() else None
    identity_evidence = ["Codex goal.id"] if goal_id else []
    if not goal_id and isinstance(goal.get("createdAt"), str):
        try:
            created_at = datetime.fromisoformat(goal["createdAt"].replace("Z", "+00:00"))
            if created_at.tzinfo is not None:
                goal_id = f"{session_id}:created:{created_at.isoformat()}"
                identity_evidence = ["Codex goal.createdAt（建立時間，非更新時間）"]
        except ValueError:
            pass
    if not goal_id and creation:
        created_goal = (creation.get("payload") or {}).get("goal") or {}
        event_id = creation.get("uuid") or creation.get("id")
        if isinstance(event_id, str) and created_goal.get("objective") == objective:
            goal_id = f"{session_id}:event:{event_id}"
            identity_evidence = [f"Codex {(creation.get('payload') or {}).get('type')} event {event_id}"]
    try:
        updated_at = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        updated_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return GoalSessionCandidate(
        session_id=session_id,
        provider="codex",
        goal_id=goal_id,
        epoch_verified=goal_id is not None,
        identity_evidence=identity_evidence,
        objective=objective.strip(),
        status=str(goal.get("status") or "unknown"),
        cwd=cwd,
        updated_at=updated_at,
        tokens_used=goal.get("tokensUsed") if isinstance(goal.get("tokensUsed"), int) else None,
        time_used_seconds=goal.get("timeUsedSeconds") if isinstance(goal.get("timeUsedSeconds"), int) else None,
    )


def discover_goal_sessions(project_root: str, limit: int = 12) -> list[GoalSessionCandidate]:
    root = _sessions_root()
    if not root.is_dir():
        return []
    cache_key = (str(root.resolve()).casefold(), str(Path(project_root).resolve()).casefold())
    now = time.monotonic()
    with _DISCOVERY_LOCK:
        cached = _DISCOVERY_CACHE.get(cache_key)
        if cached and now - cached[0] < 30:
            return cached[1][:limit]
        try:
            configured = os.environ.get("CODEX_SESSIONS_DIR")
            if configured:
                candidates = list(root.rglob("rollout-*.jsonl"))
            else:
                candidates = []
                today = datetime.now().date()
                for offset in range(45):
                    day = today - timedelta(days=offset)
                    candidates.extend((root / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}").glob("rollout-*.jsonl"))
            files = sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)[:250]
        except OSError as error:
            raise GoalMonitorUnavailable("無法索引 Codex goal sessions。") from error
        results: list[GoalSessionCandidate] = []
        for path in files:
            metadata = _session_metadata(path)
            if metadata is None:
                continue
            session_id, cwd = metadata
            if not _is_within_project(cwd, project_root):
                continue
            goal = _goal_from_transcript(path, session_id, cwd, max_scan_bytes=4 * 1024 * 1024)
            if goal is not None:
                results.append(goal)
            if len(results) >= limit:
                break
        _DISCOVERY_CACHE[cache_key] = (now, results)
        return results[:limit]


def resolve_goal_session(project_root: str, session_id: str) -> GoalSessionCandidate:
    if not SESSION_ID.fullmatch(session_id):
        raise ValueError("Codex goal session ID 格式不正確。")
    root = _sessions_root()
    matches = list(root.rglob(f"rollout-*-{session_id}.jsonl")) if root.is_dir() else []
    if len(matches) != 1:
        raise GoalMonitorUnavailable("找不到唯一的 Codex goal transcript；不會猜測其他 session。")
    metadata = _session_metadata(matches[0])
    if metadata is None or metadata[0].casefold() != session_id.casefold():
        raise GoalMonitorUnavailable("Codex transcript metadata 與指定 session 不一致。")
    if not _is_within_project(metadata[1], project_root):
        raise GoalMonitorUnavailable("Codex goal 不屬於目前專案路徑。")
    goal = _goal_from_transcript(matches[0], metadata[0], metadata[1])
    if goal is None:
        raise GoalMonitorUnavailable("指定 session 沒有可辨識的 `/goal` 狀態。")
    return goal


def _git_lines(project_root: str, *args: str) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "-C", project_root, *args], capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=True, timeout=8,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise GoalMonitorUnavailable("無法取得唯讀 Git 證據。") from error
    return completed.stdout.splitlines()[:200]


def current_git_head(project_root: str) -> str | None:
    lines = _git_lines(project_root, "rev-parse", "HEAD")
    return lines[0] if lines else None


def collect_snapshot(
    project_id: str, project_root: str, monitor_id: str, agent_id: str, session_id: str,
    *, goal_epoch_id: str | None = None, provider: str = "codex",
) -> MonitorSnapshot:
    goal = resolve_goal_session(project_root, session_id)
    if provider != goal.provider or not goal.epoch_verified or not goal_epoch_id or goal.goal_id != goal_epoch_id:
        raise GoalMonitorUnavailable("Goal epoch 無法精確核對，或已切換；停止擷取監工證據。")
    try:
        sessions = list_project_agents(project_root)
        agent = next((item for item in sessions.agents if item.id == agent_id), None)
        if agent is None or agent.provider.casefold() != "codex":
            raise GoalMonitorUnavailable("指定 Herdr pane 已離線、換了 Agent，或不是 Codex。")
        if agent.runtime_session_id and agent.runtime_session_id != session_id:
            raise GoalMonitorUnavailable("Herdr pane 的 runtime session 與監工不一致。")
        transcript = read_agent_output(agent_id, lines=180)
    except HerdrUnavailable as error:
        raise GoalMonitorUnavailable(str(error)) from error
    head = current_git_head(project_root)
    return MonitorSnapshot(
        monitor_id=monitor_id,
        project_id=project_id,
        project_root=str(Path(project_root).resolve()),
        agent_id=agent_id,
        agent_status=agent.status,
        goal_session_id=goal.session_id,
        provider=goal.provider,
        goal_epoch_id=goal.goal_id,
        identity_verified=True,
        goal_objective=goal.objective,
        goal_status=goal.status,
        goal_updated_at=goal.updated_at,
        terminal_excerpt=transcript.content[-20_000:],
        terminal_limitation=transcript.limitation,
        git_head=head,
        git_status=_git_lines(project_root, "status", "--short"),
        git_diff_stat=_git_lines(project_root, "diff", "--stat"),
        captured_at=datetime.now(timezone.utc),
    )

from __future__ import annotations

import json
import hashlib
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .goal_monitor import _is_within_project
from .codex_exec_binding import bind_child_session
from .models import AgentDelegation, GoalSessionCandidate


_GOAL_COMMAND = re.compile(
    r"(?:<command-message>goal</command-message>\s*)?"
    r"<command-name>/goal</command-name>\s*<command-args>(.*?)</command-args>", re.S
)
_CODEX_EXEC = re.compile(r"\bcodex(?:-personal|-secondary)?\s+exec\b", re.I)
_MODEL_FLAG = re.compile(r"(?:^|\s)-m\s+(?:\"([^\"]+)\"|'([^']+)'|(\S+))")
_REQUESTED_MODEL = re.compile(
    r"(?<![A-Za-z0-9])(gpt[\s-]*\d+(?:\.\d+)?(?:-(?:astra|sol|terra|luna))?)(?![A-Za-z0-9])",
    re.I,
)
_TASK_ID = re.compile(r"<task-id>([^<]+)</task-id>")
_TOOL_USE_ID = re.compile(r"<tool-use-id>([^<]+)</tool-use-id>")
_TASK_STATUS = re.compile(r"<status>(completed|failed)</status>", re.I)
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, list[GoalSessionCandidate], list[AgentDelegation]]] = {}


def _projects_root() -> Path:
    configured = os.environ.get("CLAUDE_PROJECTS_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".claude" / "projects"


def _timestamp(value: object, fallback: float) -> datetime:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.fromtimestamp(fallback, timezone.utc)


def _message_blocks(item: dict) -> list[dict]:
    message = item.get("message") if isinstance(item.get("message"), dict) else {}
    content = message.get("content")
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []


def _message_text(item: dict) -> str:
    message = item.get("message") if isinstance(item.get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(block.get("text", "")) for block in content if isinstance(block, dict))
    return ""


def exact_goal_command(item: dict) -> str | None:
    """Accept only a whole user command envelope, never quoted prompt text."""
    if item.get("type") != "user" or item.get("isSidechain") is True:
        return None
    message = item.get("message") if isinstance(item.get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, str):
        text = content
    elif (
        isinstance(content, list) and len(content) == 1 and isinstance(content[0], dict)
        and content[0].get("type") == "text" and isinstance(content[0].get("text"), str)
    ):
        text = content[0]["text"]
    else:
        return None
    match = _GOAL_COMMAND.fullmatch(text.strip())
    return match.group(1).strip() if match and match.group(1).strip() else None


def _delegation_identity(session_id: str, tool_use_id: str) -> str:
    identity = json.dumps(["claude", session_id, tool_use_id], ensure_ascii=False, separators=(",", ":"))
    return f"CLAUDE-{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


def _model_from_command(command: str) -> str | None:
    codex_exec = _CODEX_EXEC.search(command)
    if not codex_exec:
        return None
    match = _MODEL_FLAG.search(command, codex_exec.end())
    if not match:
        return None
    return next((value for value in match.groups() if value), None)


def _requested_model(objective: str | None) -> str | None:
    if not objective:
        return None
    match = _REQUESTED_MODEL.search(objective)
    return re.sub(r"\s+", "-", match.group(1).lower()) if match else None


def _models_match(requested: str | None, launched: str | None) -> str:
    if not requested or not launched:
        return "unknown"
    normalize = lambda value: re.sub(r"[^a-z0-9]", "", value.casefold())
    return "match" if normalize(requested) == normalize(launched) else "mismatch"


def _candidate_files() -> list[Path]:
    root = _projects_root()
    if not root.is_dir():
        return []
    files = [path for path in root.glob("*/*.jsonl") if path.is_file()]
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)[:24]


def _recent_lines(path: Path, max_bytes: int = 12 * 1024 * 1024):
    """Read a bounded recent window; live Claude sessions can be hundreds of MB."""
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        start = max(0, size - max_bytes)
        handle.seek(start)
        if start:
            handle.readline()
        for raw in handle:
            yield raw.decode("utf-8", errors="replace")


def _scan_session(path: Path, project_root: str) -> tuple[list[GoalSessionCandidate], list[AgentDelegation]]:
    goals: list[GoalSessionCandidate] = []
    delegations: dict[str, AgentDelegation] = {}
    tool_to_delegation: dict[str, str] = {}
    task_to_delegation: dict[str, str] = {}
    stop_tool_to_task: dict[str, str] = {}
    seen_goal_commands: set[str] = set()
    current_goal: GoalSessionCandidate | None = None
    bound_session: str | None = None
    project_seen = False
    fallback = path.stat().st_mtime

    try:
        lines = _recent_lines(path)
        for raw in lines:
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if item.get("isSidechain") is True:
                continue
            cwd = item.get("cwd")
            if isinstance(cwd, str) and not _is_within_project(cwd, project_root):
                continue
            if isinstance(cwd, str):
                project_seen = True
            if not project_seen:
                continue
            session_id = item.get("sessionId") or item.get("session_id")
            if session_id:
                if bound_session is not None and session_id != bound_session:
                    continue
                bound_session = session_id
            session_id = bound_session or path.stem
            when = _timestamp(item.get("timestamp"), fallback)

            text = _message_text(item)
            command_goal = exact_goal_command(item)
            command_id = item.get("uuid")
            if command_goal and command_id not in seen_goal_commands:
                # A user command event is reset evidence even when its text is
                # identical. A status update's UUID is not reset evidence.
                verified = isinstance(command_id, str) and bool(command_id)
                current_goal = GoalSessionCandidate(
                    session_id=str(session_id), provider="claude",
                    goal_id=f"{session_id}:command:{command_id}" if verified else None,
                    epoch_verified=verified,
                    identity_evidence=[f"Claude /goal command event {command_id}"] if verified else [],
                    objective=command_goal, status="active", cwd=str(cwd or project_root),
                    updated_at=when, evidence_level="claude_goal_command",
                )
                goals.append(current_goal)
                if verified:
                    seen_goal_commands.add(command_id)

            attachment = item.get("attachment") if isinstance(item.get("attachment"), dict) else {}
            if attachment.get("type") == "goal_status" and isinstance(attachment.get("condition"), str):
                objective = attachment["condition"].strip()
                status = "complete" if attachment.get("met") is True else "active"
                native_id = attachment.get("goal_id") or attachment.get("goalId")
                goal_id = native_id if isinstance(native_id, str) and native_id.strip() else None
                same_epoch = current_goal and (
                    (goal_id is not None and current_goal.goal_id == goal_id)
                    or (goal_id is None and current_goal.objective == objective)
                )
                if same_epoch:
                    current_goal.status = status
                    current_goal.updated_at = when
                else:
                    current_goal = GoalSessionCandidate(
                        session_id=str(session_id or path.stem), provider="claude", goal_id=goal_id,
                        epoch_verified=goal_id is not None,
                        identity_evidence=["Claude goal_status goal_id"] if goal_id else [],
                        objective=objective, status=status, cwd=str(cwd or project_root), updated_at=when,
                        evidence_level="claude_goal_status",
                    )
                    goals.append(current_goal)

            notification_text = str(item.get("content") or "") if item.get("type") == "queue-operation" else ""
            status_match = _TASK_STATUS.search(notification_text)
            if status_match:
                task_match = _TASK_ID.search(notification_text)
                tool_match = _TOOL_USE_ID.search(notification_text)
                delegation_id = None
                if task_match and tool_match:
                    by_task = task_to_delegation.get(task_match.group(1))
                    by_tool = tool_to_delegation.get(tool_match.group(1))
                    if by_task is not None and by_task == by_tool:
                        delegation_id = by_task
                if delegation_id:
                    delegation = delegations[delegation_id]
                    delegation.status = status_match.group(1).casefold()
                    delegation.updated_at = when
                    evidence = f"Claude task-notification 確認 {delegation.status}"
                    if evidence not in delegation.evidence:
                        delegation.evidence.append(evidence)

            for block in _message_blocks(item):
                if block.get("type") != "tool_use":
                    continue
                name = str(block.get("name") or "")
                tool_id = str(block.get("id") or item.get("uuid") or "")
                inputs = block.get("input") if isinstance(block.get("input"), dict) else {}
                if name == "Bash":
                    command = str(inputs.get("command") or "")
                    if not _CODEX_EXEC.search(command):
                        continue
                    delegation_id = _delegation_identity(str(session_id), tool_id)
                    if delegation_id in delegations:
                        continue
                    launched_model = _model_from_command(command)
                    requested = _requested_model(current_goal.objective if current_goal else None)
                    binding = bind_child_session(command, project_root)
                    delegations[delegation_id] = AgentDelegation(
                        id=delegation_id, parent_provider="claude",
                        parent_session_id=str(session_id or path.stem),
                        parent_goal_id=current_goal.goal_id if current_goal else None,
                        parent_goal_objective=current_goal.objective if current_goal else None,
                        child_provider="codex", description=str(inputs.get("description") or "Claude 派給 Codex 的工作"),
                        launch_model=launched_model, requested_model=requested,
                        launch_model_compliance=_models_match(requested, launched_model),
                        model_compliance="unknown", observed_model_compliance="unknown",
                        launch_method="claude_bash_codex_exec",
                        goal_binding="unverified", visibility="background_shell" if inputs.get("run_in_background") else "shell",
                        status="started" if inputs.get("run_in_background") else "unknown",
                        started_at=when, updated_at=when,
                        evidence=["Claude tool_use 精確記錄 codex exec", "尚未取得 child session identity；不以 cwd 或時間猜測"],
                    )
                    if binding is not None:
                        delegation = delegations[delegation_id]
                        delegation.child_session_id = binding.thread_id
                        delegation.goal_binding = "verified"
                        delegation.observed_model = binding.observed_model
                        delegation.observed_model_compliance = _models_match(requested, binding.observed_model)
                        delegation.evidence = [
                            "Claude tool_use 精確記錄 codex exec",
                            f"thread.started 事件檔取得 child thread {binding.thread_id}",
                            f"對應唯一 rollout：{binding.rollout_path.name}",
                        ]
                        if binding.observed_model:
                            delegation.evidence.append(f"rollout turn_context 實際模型 {binding.observed_model}")
                    tool_to_delegation[tool_id] = delegation_id
                elif name == "TaskStop":
                    task_id = str(inputs.get("task_id") or "")
                    delegation_id = task_to_delegation.get(task_id)
                    if delegation_id:
                        stop_tool_to_task[tool_id] = task_id
                        delegations[delegation_id].status = "stopping"
                        delegations[delegation_id].updated_at = when

            result = item.get("toolUseResult") if isinstance(item.get("toolUseResult"), dict) else {}
            background_task_id = result.get("backgroundTaskId")
            for block in _message_blocks(item):
                if block.get("type") != "tool_result" or block.get("is_error") is True:
                    continue
                tool_use_id = str(block.get("tool_use_id") or "")
                delegation_id = tool_to_delegation.get(tool_use_id)
                if delegation_id and isinstance(background_task_id, str):
                    delegations[delegation_id].background_task_id = background_task_id
                    task_to_delegation[background_task_id] = delegation_id
                stopped_task_id = stop_tool_to_task.get(tool_use_id)
                if (
                    stopped_task_id and result.get("task_id") == stopped_task_id
                    and str(result.get("message") or "").strip() == f"Successfully stopped task: {stopped_task_id}"
                ):
                    delegation = delegations[task_to_delegation[stopped_task_id]]
                    delegation.status = "stopped"
                    delegation.updated_at = when
                    delegation.evidence.append(f"Claude TaskStop 已確認停止 {stopped_task_id}")

    except OSError:
        return goals, []
    stale_before = datetime.now(timezone.utc) - timedelta(hours=2)
    for delegation in delegations.values():
        if delegation.status in {"started", "unknown"} and delegation.updated_at < stale_before:
            delegation.status = "stale"
            delegation.evidence.append("超過 2 小時且沒有可驗證的完成或存活事件")
    return goals, list(delegations.values())


def discover_claude_activity(
    project_root: str, *, goal_limit: int = 12, delegation_limit: int = 20
) -> tuple[list[GoalSessionCandidate], list[AgentDelegation]]:
    cache_key = str(Path(project_root).resolve()).casefold()
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and now - cached[0] < 5:
            return cached[1][:goal_limit], cached[2][:delegation_limit]
        goals: list[GoalSessionCandidate] = []
        delegations: list[AgentDelegation] = []
        for path in _candidate_files():
            file_goals, file_delegations = _scan_session(path, project_root)
            goals.extend(file_goals)
            delegations.extend(file_delegations)
        goals.sort(key=lambda item: item.updated_at, reverse=True)
        delegations.sort(key=lambda item: item.started_at, reverse=True)
        _CACHE[cache_key] = (now, goals, delegations)
        return goals[:goal_limit], delegations[:delegation_limit]

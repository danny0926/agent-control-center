from __future__ import annotations

from datetime import datetime

from .goal_monitor import GoalMonitorUnavailable, current_git_head, discover_goal_sessions, resolve_goal_session
from .herdr_adapter import list_project_agents
from .models import CreateMonitorRequest, MonitorReconcileResult, MonitorStatus
from .store import Store


def reconcile_project(store: Store, project_id: str) -> MonitorReconcileResult:
    project = store.get_project(project_id)
    if project is None:
        raise KeyError("找不到這個專案。")
    if not project.source_path:
        return MonitorReconcileResult(
            project_id=project_id,
            explanation="專案沒有本機路徑，無法核對 Herdr 與 Codex goal。",
        )

    agents = [
        agent for agent in list_project_agents(project.source_path).agents
        if agent.provider.casefold() == "codex"
    ]
    goals = discover_goal_sessions(project.source_path)
    monitors = store.list_monitors(project_id)
    rearmed: list[str] = []
    created: list[str] = []
    agent_by_id = {agent.id: agent for agent in agents}

    for monitor in monitors:
        if monitor.status not in (MonitorStatus.COMPLETE, MonitorStatus.ERROR):
            continue
        agent = agent_by_id.get(monitor.agent_id)
        if (
            not agent or not monitor.identity_verified or not monitor.goal_epoch_id
            or agent.runtime_session_id != monitor.goal_session_id
        ):
            continue
        try:
            goal = resolve_goal_session(project.source_path, monitor.goal_session_id)
        except (GoalMonitorUnavailable, ValueError):
            continue
        if (
            goal.status.casefold() != "active" or not goal.epoch_verified
            or (monitor.provider, monitor.goal_epoch_id) != (goal.provider, goal.goal_id)
        ):
            continue
        last_checked = monitor.last_checked_at or datetime.min.replace(tzinfo=goal.updated_at.tzinfo)
        if goal.updated_at > last_checked:
            store.rearm_monitor(project_id, monitor.id, goal.objective, goal=goal)
            rearmed.append(monitor.id)

    monitors = store.list_monitors(project_id)
    known_pairs = {
        (item.agent_id, item.provider, item.goal_session_id, item.goal_epoch_id)
        for item in monitors if item.identity_verified
    }
    known_agent_ids: set[str] = set()
    known_goal_ids: set[str] = set()
    goal_by_id = {item.session_id: item for item in goals}

    # Herdr can expose an exact session identity when the launcher/wrapper has
    # reported it. Only that strong identity is eligible for automatic create.
    for agent in agents:
        session_id = agent.runtime_session_id
        if not session_id:
            continue
        goal = goal_by_id.get(session_id)
        if goal is None:
            try:
                goal = resolve_goal_session(project.source_path, session_id)
            except (GoalMonitorUnavailable, ValueError):
                continue
        if not goal.epoch_verified or not goal.goal_id:
            continue
        if (agent.id, goal.provider, session_id, goal.goal_id) in known_pairs:
            known_agent_ids.add(agent.id)
            known_goal_ids.add(session_id)
            continue
        if goal.status.casefold() != "active":
            continue
        monitor = store.create_monitor(
            project_id,
            CreateMonitorRequest(
                agent_id=agent.id, goal_session_id=session_id, notify_only=True,
                provider=goal.provider, goal_epoch_id=goal.goal_id,
            ),
            goal,
            current_git_head(project.source_path),
        )
        created.append(monitor.id)
        known_agent_ids.add(agent.id)
        known_goal_ids.add(session_id)

    pending_agents = [agent.id for agent in agents if agent.id not in known_agent_ids]
    pending_goals = [goal.session_id for goal in goals if goal.session_id not in known_goal_ids]
    if pending_agents or pending_goals:
        explanation = (
            "已恢復可精確確認的監工；仍有 Agent 或 goal 缺少可靠的一對一 session identity，"
            "因此保留等待配對，不以同目錄或最近時間猜測。"
        )
    else:
        explanation = "所有可辨識的 Codex Agent 與 goal 都已有明確監工關係。"
    return MonitorReconcileResult(
        project_id=project_id,
        rearmed_monitor_ids=rearmed,
        created_monitor_ids=created,
        pending_agent_ids=pending_agents,
        pending_goal_session_ids=pending_goals,
        explanation=explanation,
    )


def reconcile_all_projects(store: Store) -> None:
    for project in store.portfolio().projects:
        if not project.source_path:
            continue
        try:
            reconcile_project(store, project.id)
        except Exception:
            # A broken external adapter must not terminate reconciliation for
            # every other project. The explicit endpoint returns the error.
            continue

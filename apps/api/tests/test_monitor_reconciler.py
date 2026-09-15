from datetime import datetime, timedelta, timezone
from pathlib import Path

from control_center import monitor_reconciler
from control_center.models import (
    AgentSession,
    AgentSessionsResponse,
    Confidence,
    CreateMonitorRequest,
    GoalSessionCandidate,
    MonitorFindingRequest,
    MonitorStatus,
    MonitorVerdict,
)
from control_center.store import Store


def _store_with_project(tmp_path: Path) -> Store:
    store = Store(tmp_path / "control.db")
    now = datetime.now(timezone.utc).isoformat()
    with store._connect() as connection:
        connection.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "project-1", "local", None, "Project", "Purpose", "local_repository",
                str(tmp_path), "high", "confirmed", None, "[]", "[]", now, now,
            ),
        )
    return store


def _agent(session_id: str | None = None) -> AgentSession:
    return AgentSession(
        id="wN:p1", provider="codex", status="working", workspace_id="wN",
        workspace_label="Project", pane_id="wN:p1", cwd="D:\\project", title="Codex",
        task_summary="完成產品", runtime_session_id=session_id,
    )


def _goal(tmp_path: Path, session_id: str, updated_at: datetime) -> GoalSessionCandidate:
    return GoalSessionCandidate(
        session_id=session_id, objective="完成產品", status="active", cwd=str(tmp_path),
        goal_id="epoch-1", epoch_verified=True, identity_evidence=["fixture native goal id"],
        updated_at=updated_at,
    )


def test_reconcile_rearms_completed_monitor_when_same_goal_has_new_update(tmp_path: Path, monkeypatch) -> None:
    store = _store_with_project(tmp_path)
    session_id = "11111111-1111-1111-1111-111111111111"
    original_goal = _goal(tmp_path, session_id, datetime.now(timezone.utc))
    monitor = store.create_monitor(
        "project-1", CreateMonitorRequest(agent_id="wN:p1", goal_session_id=session_id),
        original_goal, "abc123",
    )
    store.record_monitor_finding(
        "project-1", monitor.id,
        MonitorFindingRequest(
            verdict=MonitorVerdict.TERMINAL, finding_type="goal_terminal",
            summary="先前工作已結束。", confidence=Confidence.HIGH,
        ),
    )
    resumed_goal = _goal(tmp_path, session_id, datetime.now(timezone.utc) + timedelta(minutes=1))
    monkeypatch.setattr(
        monitor_reconciler, "list_project_agents",
        lambda root: AgentSessionsResponse(connected=True, source="test", limitation="", agents=[_agent(session_id)]),
    )
    monkeypatch.setattr(monitor_reconciler, "discover_goal_sessions", lambda root: [resumed_goal])
    monkeypatch.setattr(monitor_reconciler, "resolve_goal_session", lambda root, goal_id: resumed_goal)

    result = monitor_reconciler.reconcile_project(store, "project-1")

    assert result.rearmed_monitor_ids == [monitor.id]
    assert store.get_monitor("project-1", monitor.id).status == MonitorStatus.ARMED
    assert store.get_monitor("project-1", monitor.id).events[0].finding_type == "goal_resumed"


def test_reconcile_does_not_guess_session_for_unidentified_pane(tmp_path: Path, monkeypatch) -> None:
    store = _store_with_project(tmp_path)
    session_id = "22222222-2222-2222-2222-222222222222"
    goal = _goal(tmp_path, session_id, datetime.now(timezone.utc))
    monkeypatch.setattr(
        monitor_reconciler, "list_project_agents",
        lambda root: AgentSessionsResponse(connected=True, source="test", limitation="", agents=[_agent()]),
    )
    monkeypatch.setattr(monitor_reconciler, "discover_goal_sessions", lambda root: [goal])

    result = monitor_reconciler.reconcile_project(store, "project-1")

    assert result.created_monitor_ids == []
    assert result.pending_agent_ids == ["wN:p1"]
    assert result.pending_goal_session_ids == [session_id]
    assert store.list_monitors("project-1") == []


def test_reconcile_auto_creates_only_with_reported_exact_session_id(tmp_path: Path, monkeypatch) -> None:
    store = _store_with_project(tmp_path)
    session_id = "33333333-3333-3333-3333-333333333333"
    goal = _goal(tmp_path, session_id, datetime.now(timezone.utc))
    monkeypatch.setattr(
        monitor_reconciler, "list_project_agents",
        lambda root: AgentSessionsResponse(
            connected=True, source="test", limitation="", agents=[_agent(session_id)]
        ),
    )
    monkeypatch.setattr(monitor_reconciler, "discover_goal_sessions", lambda root: [goal])
    monkeypatch.setattr(monitor_reconciler, "current_git_head", lambda root: "abc123")

    result = monitor_reconciler.reconcile_project(store, "project-1")

    assert len(result.created_monitor_ids) == 1
    monitor = store.list_monitors("project-1")[0]
    assert monitor.goal_session_id == session_id
    assert monitor.agent_id == "wN:p1"


def test_reconcile_new_epoch_does_not_rearm_or_overwrite_old_monitor(tmp_path: Path, monkeypatch) -> None:
    store = _store_with_project(tmp_path)
    session_id = "44444444-4444-4444-4444-444444444444"
    original = _goal(tmp_path, session_id, datetime.now(timezone.utc))
    monitor = store.create_monitor("project-1", CreateMonitorRequest(
        agent_id="wN:p1", goal_session_id=session_id), original, None)
    store.record_monitor_finding("project-1", monitor.id, MonitorFindingRequest(
        verdict=MonitorVerdict.TERMINAL, finding_type="complete", summary="舊工作已結束"))
    new_goal = original.model_copy(update={"goal_id": "epoch-2", "updated_at": datetime.now(timezone.utc) + timedelta(minutes=1)})
    monkeypatch.setattr(monitor_reconciler, "list_project_agents", lambda root: AgentSessionsResponse(
        connected=True, source="test", limitation="", agents=[_agent(session_id)]))
    monkeypatch.setattr(monitor_reconciler, "discover_goal_sessions", lambda root: [new_goal])
    monkeypatch.setattr(monitor_reconciler, "resolve_goal_session", lambda root, session: new_goal)
    monkeypatch.setattr(monitor_reconciler, "current_git_head", lambda root: "abc")
    result = monitor_reconciler.reconcile_project(store, "project-1")
    assert result.rearmed_monitor_ids == [] and len(result.created_monitor_ids) == 1
    old = store.get_monitor("project-1", monitor.id)
    assert old.goal_epoch_id == "epoch-1" and old.status == MonitorStatus.COMPLETE


def test_reconcile_unknown_epoch_remains_pending(tmp_path: Path, monkeypatch) -> None:
    store = _store_with_project(tmp_path)
    session_id = "55555555-5555-5555-5555-555555555555"
    goal = _goal(tmp_path, session_id, datetime.now(timezone.utc)).model_copy(update={"epoch_verified": False, "goal_id": None})
    monkeypatch.setattr(monitor_reconciler, "list_project_agents", lambda root: AgentSessionsResponse(
        connected=True, source="test", limitation="", agents=[_agent(session_id)]))
    monkeypatch.setattr(monitor_reconciler, "discover_goal_sessions", lambda root: [goal])
    result = monitor_reconciler.reconcile_project(store, "project-1")
    assert not result.created_monitor_ids and result.pending_goal_session_ids == [session_id]

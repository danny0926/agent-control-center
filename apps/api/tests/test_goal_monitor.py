import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from control_center import goal_monitor
from control_center.models import (
    Confidence,
    CreateMonitorRequest,
    GoalSessionCandidate,
    MonitorFindingRequest,
    MonitorVerdict,
)
from control_center.store import Store


def _write_goal_session(root: Path, session_id: str, cwd: Path, status: str = "active") -> Path:
    path = root / "2026" / "09" / "14" / f"rollout-2026-09-14T10-00-00-{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {"type": "session_meta", "payload": {"session_id": session_id, "cwd": str(cwd)}},
        {
            "timestamp": "2026-09-14T10:00:00Z",
            "type": "event_msg",
            "payload": {
                "type": "thread_goal_updated",
                "goal": {
                    "id": "epoch-1",
                    "objective": "完成可驗證的監工流程",
                    "status": status,
                    "tokensUsed": 123,
                    "timeUsedSeconds": 456,
                    "updatedAt": "2026-09-14T10:00:00Z",
                },
            },
        },
    ]
    path.write_text("\n".join(json.dumps(item) for item in records), encoding="utf-8")
    return path


def test_discovery_only_returns_goals_inside_project(tmp_path: Path, monkeypatch) -> None:
    sessions = tmp_path / "sessions"
    project = tmp_path / "project"
    other = tmp_path / "other"
    project.mkdir(); other.mkdir()
    expected_id = "11111111-1111-1111-1111-111111111111"
    _write_goal_session(sessions, expected_id, project)
    _write_goal_session(sessions, "22222222-2222-2222-2222-222222222222", other)
    monkeypatch.setenv("CODEX_SESSIONS_DIR", str(sessions))

    result = goal_monitor.discover_goal_sessions(str(project))

    assert [item.session_id for item in result] == [expected_id]
    assert result[0].objective == "完成可驗證的監工流程"
    assert result[0].tokens_used == 123


def test_resolve_goal_rejects_session_from_other_project(tmp_path: Path, monkeypatch) -> None:
    sessions = tmp_path / "sessions"
    project = tmp_path / "project"
    other = tmp_path / "other"
    project.mkdir(); other.mkdir()
    session_id = "33333333-3333-3333-3333-333333333333"
    _write_goal_session(sessions, session_id, other)
    monkeypatch.setenv("CODEX_SESSIONS_DIR", str(sessions))

    with pytest.raises(goal_monitor.GoalMonitorUnavailable, match="不屬於目前專案"):
        goal_monitor.resolve_goal_session(str(project), session_id)


def test_monitor_finding_creates_one_human_decision_for_duplicate_alerts(tmp_path: Path) -> None:
    store = Store(tmp_path / "control.db")
    now = datetime.now(timezone.utc).isoformat()
    with store._connect() as connection:
        connection.execute(
            """
            INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "project-1", "local", None, "Project", "Purpose", "local_repository",
                str(tmp_path), "high", "confirmed", None, "[]", "[]", now, now,
            ),
        )
    session_id = "44444444-4444-4444-4444-444444444444"
    monitor = store.create_monitor(
        "project-1",
        CreateMonitorRequest(agent_id="wN:p1", goal_session_id=session_id),
        GoalSessionCandidate(
            session_id=session_id,
            goal_id="epoch-1", epoch_verified=True, identity_evidence=["fixture native goal id"],
            objective="完成產品",
            status="active",
            cwd=str(tmp_path),
            updated_at=datetime.now(timezone.utc),
        ),
        "abc123",
    )
    finding = MonitorFindingRequest(
        verdict=MonitorVerdict.NEEDS_HUMAN,
        finding_type="scope_conflict",
        summary="目前方向與已確認產品範圍衝突。",
        evidence=["PRD 不包含這項功能。"],
        recommendation="請決定是否擴張範圍。",
        confidence=Confidence.HIGH,
    )

    first = store.record_monitor_finding("project-1", monitor.id, finding)
    second = store.record_monitor_finding("project-1", monitor.id, finding)

    assert first.decision_id is not None
    assert second.decision_id == first.decision_id
    decisions = store.list_decisions("project-1")
    assert len(decisions) == 1
    assert decisions[0].status == "waiting_human"
    assert decisions[0].messages[0].role == "agent"


def test_pilot_rejects_auto_injection(tmp_path: Path) -> None:
    store = Store(tmp_path / "control.db")
    now = datetime.now(timezone.utc).isoformat()
    with store._connect() as connection:
        connection.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("project-1", "local", None, "Project", "Purpose", "local_repository", str(tmp_path),
             "high", "confirmed", None, "[]", "[]", now, now),
        )
    session_id = "55555555-5555-5555-5555-555555555555"

    with pytest.raises(ValueError, match="notify-only"):
        store.create_monitor(
            "project-1",
            CreateMonitorRequest(
                agent_id="wN:p1", goal_session_id=session_id, notify_only=False
            ),
            GoalSessionCandidate(
                session_id=session_id, objective="完成產品", status="active", cwd=str(tmp_path),
                updated_at=datetime.now(timezone.utc),
            ),
            None,
        )


def _transcript_goal(tmp_path: Path, goals: list[dict]) -> GoalSessionCandidate:
    transcript = tmp_path / "identity.jsonl"
    transcript.write_text("\n".join(json.dumps(record) for record in goals), encoding="utf-8")
    result = goal_monitor._goal_from_transcript(transcript, "session", str(tmp_path))
    assert result is not None
    return result


def _update(**fields: object) -> dict:
    return {"type": "event_msg", "timestamp": "2026-09-15T01:00:00Z", "payload": {
        "type": "thread_goal_updated", "goal": {"objective": "同一目標", "status": "active", **fields}
    }}


def test_codex_update_timestamp_never_invents_epoch(tmp_path: Path) -> None:
    first = _transcript_goal(tmp_path, [_update(updatedAt="2026-09-15T01:00:00Z")])
    second = _transcript_goal(tmp_path, [_update(updatedAt="2026-09-15T02:00:00Z")])
    assert first.goal_id is second.goal_id is None
    assert not first.epoch_verified and not second.epoch_verified
    assert second.objective == "同一目標"


@pytest.mark.parametrize("identity", [{"id": "native-epoch"}, {"createdAt": "2026-09-15T00:00:00Z"}])
def test_codex_authoritative_epoch_is_stable_across_updates(tmp_path: Path, identity: dict) -> None:
    first = _transcript_goal(tmp_path, [_update(**identity, updatedAt="2026-09-15T01:00:00Z")])
    second = _transcript_goal(tmp_path, [_update(**identity, updatedAt="2026-09-15T02:00:00Z")])
    assert first.goal_id == second.goal_id
    assert second.epoch_verified and second.identity_evidence


def test_codex_explicit_reset_event_splits_same_text_epochs(tmp_path: Path) -> None:
    def reset(event_id: str) -> dict:
        return {"type": "event_msg", "uuid": event_id, "payload": {
            "type": "thread_goal_reset", "goal": {"objective": "同一目標"}
        }}
    first = _transcript_goal(tmp_path, [reset("reset-1"), _update()])
    second = _transcript_goal(tmp_path, [reset("reset-1"), _update(), reset("reset-2"), _update()])
    assert first.goal_id != second.goal_id
    assert first.epoch_verified and second.epoch_verified


def test_codex_reset_without_identity_does_not_reuse_previous_epoch(tmp_path: Path) -> None:
    result = _transcript_goal(tmp_path, [_update(id="old"), {
        "type": "event_msg", "payload": {"type": "thread_goal_reset", "goal": {"objective": "同一目標"}}
    }, _update()])
    assert result.goal_id is None
    assert not result.epoch_verified


def _identity_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "control.db")
    now = datetime.now(timezone.utc).isoformat()
    with store._connect() as connection:
        connection.execute("INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("project-1", "local", None, "Project", "Purpose", "local_repository", str(tmp_path),
             "high", "confirmed", None, "[]", "[]", now, now))
    return store


def _verified_goal(tmp_path: Path, epoch: str = "epoch-1") -> GoalSessionCandidate:
    return GoalSessionCandidate(
        session_id="77777777-7777-7777-7777-777777777777", goal_id=epoch,
        epoch_verified=True, identity_evidence=["native goal id"], objective="同一目標",
        status="active", cwd=str(tmp_path), updated_at=datetime.now(timezone.utc),
    )


def test_monitor_preserves_separate_same_session_epochs(tmp_path: Path) -> None:
    store = _identity_store(tmp_path)
    first_goal, second_goal = _verified_goal(tmp_path), _verified_goal(tmp_path, "epoch-2")
    request = CreateMonitorRequest(agent_id="wN:p1", goal_session_id=first_goal.session_id)
    first = store.create_monitor("project-1", request, first_goal, None)
    second = store.create_monitor("project-1", request, second_goal, None)
    assert first.id != second.id
    assert {item.goal_epoch_id for item in store.list_monitors("project-1")} == {"epoch-1", "epoch-2"}
    with pytest.raises(ValueError, match="已經有監工"):
        store.create_monitor("project-1", request, second_goal, None)
    with pytest.raises(ValueError, match="跨 provider/session/epoch"):
        store.rearm_monitor("project-1", first.id, second_goal.objective, goal=second_goal)


@pytest.mark.parametrize("change", [
    {"epoch_verified": False}, {"goal_id": None}, {"identity_evidence": []},
    {"provider": "claude"}, {"session_id": "88888888-8888-8888-8888-888888888888"},
])
def test_monitor_refuses_unverified_or_mismatched_identity(tmp_path: Path, change: dict) -> None:
    store = _identity_store(tmp_path)
    goal = _verified_goal(tmp_path)
    request = CreateMonitorRequest(agent_id="wN:p1", goal_session_id=goal.session_id)
    with pytest.raises(ValueError, match="身分證據"):
        store.create_monitor("project-1", request, goal.model_copy(update=change), None)
    assert store.list_monitors("project-1") == []


def test_monitor_rejects_stale_explicit_epoch(tmp_path: Path) -> None:
    store = _identity_store(tmp_path)
    goal = _verified_goal(tmp_path)
    with pytest.raises(ValueError, match="身分證據"):
        store.create_monitor("project-1", CreateMonitorRequest(
            agent_id="wN:p1", goal_session_id=goal.session_id, goal_epoch_id="old-epoch"
        ), goal, None)


def test_legacy_monitor_migration_preserves_history_but_does_not_arm(tmp_path: Path) -> None:
    store = _identity_store(tmp_path)
    now = datetime.now(timezone.utc).isoformat()
    with store._connect() as connection:
        connection.execute("INSERT INTO goal_monitors VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            "legacy", "project-1", "wN:p1", "77777777-7777-7777-7777-777777777777",
            "歷史目標", 60, 1, "armed", "abc", now, now, now,
        ))
        connection.execute("INSERT INTO monitor_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            "old-event", "legacy", "clean", "history", "歷史摘要", "[]", "", "unknown", None, now,
        ))
        connection.execute("DELETE FROM schema_migrations WHERE version = 'monitor_epochs_v2'")
    migrated = Store(store.path)
    monitor = migrated.get_monitor("project-1", "legacy")
    assert monitor.provider == "unknown" and monitor.goal_epoch_id is None
    assert not monitor.identity_verified and monitor.status == "paused"
    assert monitor.events[0].id == "old-event" and monitor.start_head == "abc"
    with pytest.raises(ValueError, match="未知身分"):
        migrated.rearm_monitor("project-1", monitor.id, "同一目標", goal=_verified_goal(tmp_path))
    assert Store(store.path).get_monitor("project-1", "legacy").events[0].id == "old-event"
    with migrated._connect() as connection:
        assert connection.execute("SELECT status FROM goal_monitors WHERE id = 'legacy'").fetchone()[0] == "armed"


def test_snapshot_rejects_changed_epoch_before_terminal_read(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(goal_monitor, "resolve_goal_session", lambda root, session: _verified_goal(tmp_path))
    monkeypatch.setattr(goal_monitor, "list_project_agents", lambda root: pytest.fail("must reject before runtime read"))
    with pytest.raises(goal_monitor.GoalMonitorUnavailable, match="epoch"):
        goal_monitor.collect_snapshot("project-1", str(tmp_path), "m", "wN:p1", "session", goal_epoch_id="old")

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from control_center import event_collector
from control_center.event_collector import RuntimeEventCollector
from control_center.notifications import initialize_notifications
from control_center.store import Store


@pytest.fixture
def setup(tmp_path: Path, monkeypatch):
    codex, claude, project = tmp_path / "codex", tmp_path / "claude", tmp_path / "project"
    codex.mkdir(); claude.mkdir(); project.mkdir()
    monkeypatch.setenv("CODEX_SESSIONS_DIR", str(codex))
    monkeypatch.setenv("CLAUDE_PROJECTS_DIR", str(claude))
    store = Store(tmp_path / "test.db")
    now = datetime.now(timezone.utc).isoformat()
    with store._connect() as connection:
        initialize_notifications(connection)
        connection.execute("INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            "p1", "local", None, "Project", "test", "local_repository", str(project), "high", "confirmed",
            None, "[]", "[]", now, now))
    return store, codex, claude, project


def _write(path, records, *, append=False, newline=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a" if append else "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + ("\n" if newline else ""))


def _meta(project, session="s1"):
    return {"type": "session_meta", "payload": {"session_id": session, "cwd": str(project)}}


def _turn(turn="t1", **fields):
    return {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": turn, **fields}}


def _goal(epoch="g1", status="complete", **fields):
    return {"type": "event_msg", "payload": {"type": "thread_goal_updated", "goal": {
        "id": epoch, "objective": "同一目標", "status": status, **fields}}}


def _events(store):
    with store._connect() as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM domain_events ORDER BY sequence")]


def _health(store):
    with store._connect() as connection:
        return connection.execute("SELECT status FROM collector_health WHERE id='runtime'").fetchone()[0]


def test_constructor_does_not_scan_and_bootstrap_suppresses_history(setup):
    store, codex, _, project = setup
    path = codex / "rollout-one.jsonl"
    _write(path, [_meta(project), _turn("old"), _goal("old-goal")])
    collector = RuntimeEventCollector(store)
    with store._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM collector_cursors").fetchone()[0] == 0
    collector.bootstrap()
    _write(path, [_turn("new"), _goal("new-goal")], append=True)
    collector.poll()
    assert [row["event_type"] for row in _events(store)] == ["agent.turn_completed", "agent.goal_completed"]
    assert json.loads(_events(store)[0]["identity_json"])["turn_id"] == "new"


def test_new_file_after_bootstrap_collects_without_open_browser(setup):
    store, codex, _, project = setup
    collector = RuntimeEventCollector(store)
    collector.bootstrap()
    _write(codex / "rollout-new.jsonl", [_meta(project), _turn()])
    collector.poll()
    assert len(_events(store)) == 1 and _health(store) == "healthy"


def test_restart_catches_up_without_resetting_existing_cursor(setup):
    store, codex, _, project = setup
    path = codex / "rollout-one.jsonl"
    _write(path, [_meta(project)])
    collector = RuntimeEventCollector(store)
    collector.bootstrap(); collector.poll()
    _write(path, [_turn("while-offline")], append=True)
    resumed = RuntimeEventCollector(store)
    resumed.bootstrap(); resumed.poll(); resumed.poll()
    assert len(_events(store)) == 1


def test_rotation_replays_neither_baseline_nor_delivered_events(setup):
    store, codex, _, project = setup
    path = codex / "rollout-one.jsonl"
    _write(path, [_meta(project), _turn("historical")])
    collector = RuntimeEventCollector(store)
    collector.bootstrap(); collector.poll()
    _write(path, [_turn("live")], append=True)
    collector.poll()
    replacement = codex / "replacement.tmp"
    _write(replacement, [_meta(project), _turn("historical"), _turn("live"), _turn("new-after-rotation")])
    os.replace(replacement, path)
    collector.poll()
    assert [json.loads(row["identity_json"])["turn_id"] for row in _events(store)] == ["live", "new-after-rotation"]


def test_partial_line_is_not_advanced_until_newline(setup):
    store, codex, _, project = setup
    path = codex / "rollout-one.jsonl"
    _write(path, [_meta(project)])
    collector = RuntimeEventCollector(store)
    collector.bootstrap(); collector.poll()
    _write(path, [_turn()], append=True, newline=False)
    collector.poll()
    assert _events(store) == []
    assert _health(store) == "stale"
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n")
    collector.poll()
    assert len(_events(store)) == 1
    assert _health(store) == "healthy"


def test_missing_turn_or_goal_identity_never_claims_completion(setup):
    store, codex, _, project = setup
    collector = RuntimeEventCollector(store)
    collector.bootstrap()
    _write(codex / "rollout-one.jsonl", [_meta(project), _turn(None), _goal(None, updatedAt="2026-09-15T01:00:00Z")])
    collector.poll()
    assert _events(store) == []


def test_wrong_project_or_session_and_sidechain_are_rejected(setup, tmp_path):
    store, codex, _, project = setup
    other = tmp_path / "other"
    other.mkdir()
    collector = RuntimeEventCollector(store)
    collector.bootstrap()
    _write(codex / "rollout-other.jsonl", [_meta(other), _turn("other-project")])
    _write(codex / "rollout-one.jsonl", [_meta(project), _turn("other-session", session_id="s2"),
        {**_turn("wrong-path"), "cwd": str(other)}, {**_turn("sidechain"), "isSidechain": True}, _turn("valid")])
    collector.poll()
    assert [json.loads(row["identity_json"])["turn_id"] for row in _events(store)] == ["valid"]


def test_more_specific_project_wins_without_parent_leakage(setup):
    store, codex, _, project = setup
    child = project / "child"
    child.mkdir()
    now = datetime.now(timezone.utc).isoformat()
    with store._connect() as connection:
        connection.execute("INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            "p2", "local", "p1", "Child", "test", "local_repository", str(child), "high", "confirmed",
            None, "[]", "[]", now, now))
    collector = RuntimeEventCollector(store)
    collector.bootstrap()
    _write(codex / "rollout-child.jsonl", [_meta(child), _turn()])
    collector.poll()
    assert [row["project_id"] for row in _events(store)] == ["p2"]


def test_goal_repeats_deduplicate_but_native_reset_has_own_notification(setup):
    store, codex, _, project = setup
    collector = RuntimeEventCollector(store)
    collector.bootstrap()
    _write(codex / "rollout-one.jsonl", [_meta(project), _goal("g1"), _goal("g1"), _goal("g2")])
    collector.poll()
    assert [json.loads(row["identity_json"])["goal_epoch_id"] for row in _events(store)] == ["g1", "g2"]


def test_claude_exact_command_resets_same_text_and_updates_do_not(setup):
    store, _, claude, project = setup
    base = {"sessionId": "cs1", "cwd": str(project)}
    def command(identifier):
        return {**base, "type": "user", "uuid": identifier, "message": {"content":
            "<command-name>/goal</command-name><command-args>同一目標</command-args>"}}
    def status(identifier):
        return {**base, "type": "attachment", "uuid": identifier, "attachment": {
            "type": "goal_status", "condition": "同一目標", "met": True}}
    collector = RuntimeEventCollector(store)
    collector.bootstrap()
    _write(claude / "project" / "session.jsonl", [status("unknown"), command("reset-1"), status("update-1"),
        status("update-2"), command("reset-2"), status("update-3")])
    collector.poll()
    assert [json.loads(row["identity_json"])["goal_epoch_id"] for row in _events(store)] == ["cs1:command:reset-1", "cs1:command:reset-2"]


def test_claude_baseline_command_context_is_available_for_later_complete(setup):
    store, _, claude, project = setup
    base = {"sessionId": "cs1", "cwd": str(project)}
    path = claude / "project" / "session.jsonl"
    _write(path, [{**base, "type": "user", "uuid": "reset", "message": {"content":
        "<command-name>/goal</command-name><command-args>同一目標</command-args>"}}])
    collector = RuntimeEventCollector(store)
    collector.bootstrap()
    _write(path, [{**base, "type": "attachment", "attachment": {"type": "goal_status", "condition": "同一目標", "met": True}}], append=True)
    collector.poll()
    assert len(_events(store)) == 1


def test_cursor_and_event_rollback_together_then_retry(setup, monkeypatch):
    store, codex, _, project = setup
    collector = RuntimeEventCollector(store)
    collector.bootstrap()
    _write(codex / "rollout-one.jsonl", [_meta(project), _turn()])
    original = event_collector.emit_event
    def crash(connection, **kwargs):
        original(connection, **kwargs)
        raise sqlite3.OperationalError("simulated crash before cursor commit")
    monkeypatch.setattr(event_collector, "emit_event", crash)
    collector.poll()
    assert _events(store) == [] and _health(store) == "error"
    monkeypatch.setattr(event_collector, "emit_event", original)
    collector.poll()
    assert len(_events(store)) == 1


def test_bounded_batches_make_progress_and_report_backlog(setup):
    store, codex, _, project = setup
    collector = RuntimeEventCollector(store, max_files=1, max_file_bytes=256, max_bytes=256)
    collector.bootstrap()
    _write(codex / "rollout-a.jsonl", [_meta(project)] + [_turn(str(i)) for i in range(6)])
    _write(codex / "rollout-b.jsonl", [_meta(project, "s2"), _turn("b")])
    collector.poll()
    assert _health(store) == "stale"
    for _ in range(12):
        collector.poll()
    assert len(_events(store)) == 7
    assert _health(store) == "healthy"


def test_codex_explicit_created_reset_event_identity_matches_f02(setup):
    store, codex, _, project = setup
    def reset(identifier):
        return {"type": "event_msg", "uuid": identifier, "payload": {"type": "thread_goal_reset", "goal": {"objective": "同一目標"}}}
    collector = RuntimeEventCollector(store)
    collector.bootstrap()
    _write(codex / "rollout-a.jsonl", [_meta(project), reset("r1"), _goal(None), reset("r2"), _goal(None)])
    collector.poll()
    assert [json.loads(row["identity_json"])["goal_epoch_id"] for row in _events(store)] == ["s1:event:r1", "s1:event:r2"]


def test_disappeared_source_is_stale_and_does_not_mean_completed(setup):
    store, codex, _, project = setup
    path = codex / "rollout-a.jsonl"
    _write(path, [_meta(project)])
    collector = RuntimeEventCollector(store)
    collector.bootstrap(); collector.poll()
    path.unlink()
    collector.poll()
    assert _health(store) == "stale" and _events(store) == []


def test_one_unreadable_source_does_not_starve_other_sources(setup, monkeypatch):
    store, codex, _, project = setup
    collector = RuntimeEventCollector(store)
    collector.bootstrap()
    _write(codex / "rollout-a.jsonl", [_meta(project), _turn("a")])
    _write(codex / "rollout-b.jsonl", [_meta(project, "s2"), _turn("b")])
    original = collector._file
    def unreadable(provider, path, projects, budget):
        if path.name == "rollout-a.jsonl":
            raise OSError("fixture unreadable")
        return original(provider, path, projects, budget)
    monkeypatch.setattr(collector, "_file", unreadable)
    collector.poll()
    assert _health(store) == "error" and len(_events(store)) == 1


def test_quoted_goal_command_cannot_create_verified_completion(setup):
    store, _, claude, project = setup
    collector = RuntimeEventCollector(store)
    collector.bootstrap()
    base = {"sessionId": "cs1", "cwd": str(project)}
    _write(claude / "project" / "session.jsonl", [
        {**base, "type": "user", "uuid": "quoted", "message": {"content":
            "範例：<command-name>/goal</command-name><command-args>同一目標</command-args>"}},
        {**base, "type": "attachment", "attachment": {"type": "goal_status", "condition": "同一目標", "met": True}},
    ])
    collector.poll()
    assert _events(store) == []


def test_more_than_one_batch_becomes_healthy_after_complete_coverage(setup):
    store, codex, _, project = setup
    for index in range(65):
        _write(codex / f"rollout-{index:03}.jsonl", [_meta(project, f"s{index}")])
    collector = RuntimeEventCollector(store, max_files=64)
    collector.bootstrap()
    assert _health(store) == "stale"
    collector.poll()
    assert _health(store) == "stale"
    collector.poll()
    assert _health(store) == "healthy"
    collector.poll()
    assert _health(store) == "healthy"
    assert _events(store) == []


def test_changed_unvisited_source_invalidates_cycle_coverage(setup):
    store, codex, _, project = setup
    paths = [codex / f"rollout-{name}.jsonl" for name in ("a", "b", "c")]
    for index, path in enumerate(paths):
        _write(path, [_meta(project, f"s{index}")])
    collector = RuntimeEventCollector(store, max_files=1)
    collector.bootstrap()
    for _ in range(3):
        collector.poll()
    assert _health(store) == "healthy"
    _write(paths[2], [_turn("changed-c")], append=True)
    collector.poll()
    assert _health(store) == "stale" and _events(store) == []
    collector.poll()
    assert _health(store) == "stale"
    collector.poll()
    assert _health(store) == "healthy" and len(_events(store)) == 1


def test_new_source_must_be_checked_before_cycle_is_healthy(setup):
    store, codex, _, project = setup
    for index in range(2):
        _write(codex / f"rollout-{index}.jsonl", [_meta(project, f"s{index}")])
    collector = RuntimeEventCollector(store, max_files=1)
    collector.bootstrap(); collector.poll(); collector.poll()
    assert _health(store) == "healthy"
    _write(codex / "rollout-2.jsonl", [_meta(project, "s2"), _turn("new")])
    collector.poll()
    assert _health(store) == "stale"
    collector.poll()
    assert _health(store) == "stale"
    collector.poll()
    assert _health(store) == "healthy" and len(_events(store)) == 1


def test_source_error_remains_visible_until_that_source_is_rechecked(setup, monkeypatch):
    store, codex, _, project = setup
    for index in range(3):
        _write(codex / f"rollout-{index}.jsonl", [_meta(project, f"s{index}")])
    collector = RuntimeEventCollector(store, max_files=1)
    collector.bootstrap()
    for _ in range(3):
        collector.poll()
    original = collector._file
    def broken(provider, path, projects, budget):
        if path.name == "rollout-0.jsonl":
            raise OSError("fixture failure")
        return original(provider, path, projects, budget)
    monkeypatch.setattr(collector, "_file", broken)
    collector.poll()
    assert _health(store) == "error"
    collector.poll()
    assert _health(store) == "error"
    monkeypatch.setattr(collector, "_file", original)
    collector.poll()
    assert _health(store) == "error"
    collector.poll()
    assert _health(store) == "healthy"

import json
import sqlite3
from pathlib import Path

from control_center import goal_monitor
from control_center import codex_goals_db
from control_center.codex_goals_db import lookup_native_goal, lookup_native_goals


SESSION_ID = "11111111-1111-1111-1111-111111111111"
OBJECTIVE = "native objective"


def _write_transcript(path: Path, objective: str = OBJECTIVE) -> None:
    path.write_text(json.dumps({
        "type": "event_msg",
        "timestamp": "2026-09-17T00:00:00Z",
        "payload": {"type": "thread_goal_updated", "goal": {
            "id": "transcript-id", "objective": objective, "status": "active",
            "tokensUsed": 1, "timeUsedSeconds": 2,
        }},
    }), encoding="utf-8")


def _create_db(path: Path, *, goal_id: str = "native-id", objective: str = OBJECTIVE) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("""
            CREATE TABLE thread_goals (
                thread_id TEXT PRIMARY KEY NOT NULL, goal_id TEXT NOT NULL,
                objective TEXT NOT NULL, status TEXT NOT NULL,
                token_budget INTEGER, tokens_used INTEGER NOT NULL DEFAULT 0,
                time_used_seconds INTEGER NOT NULL DEFAULT 0,
                created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL
            )
        """)
        connection.execute(
            "INSERT INTO thread_goals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (SESSION_ID, goal_id, objective, "paused", 100, 23, 45, 1000, 2000),
        )


def test_native_goal_is_authoritative(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "goals.sqlite"
    _create_db(db)
    monkeypatch.setenv("CODEX_GOALS_DB", str(db))
    transcript = tmp_path / "rollout.jsonl"
    _write_transcript(transcript)

    result = goal_monitor._goal_from_transcript(transcript, SESSION_ID, str(tmp_path))

    assert result is not None
    assert result.goal_id == "native-id"
    assert result.epoch_verified is True
    assert result.identity_evidence == ["Codex goals_1.sqlite thread_goals.goal_id"]
    assert result.status == "paused" and result.tokens_used == 23
    assert result.time_used_seconds == 45


def test_objective_mismatch_keeps_transcript_result(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "goals.sqlite"
    _create_db(db, objective="different")
    monkeypatch.setenv("CODEX_GOALS_DB", str(db))
    transcript = tmp_path / "rollout.jsonl"
    _write_transcript(transcript)

    result = goal_monitor._goal_from_transcript(transcript, SESSION_ID, str(tmp_path))

    assert result is not None
    assert result.goal_id == "transcript-id" and result.status == "active"
    assert "goals_1.sqlite objective 與 transcript 不一致，未採用" in result.identity_evidence


def test_missing_db_preserves_transcript_result(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_GOALS_DB", str(tmp_path / "missing.sqlite"))
    transcript = tmp_path / "rollout.jsonl"
    _write_transcript(transcript)

    result = goal_monitor._goal_from_transcript(transcript, SESSION_ID, str(tmp_path))

    assert result is not None
    assert result.goal_id == "transcript-id" and result.status == "active"
    assert result.tokens_used == 1 and result.time_used_seconds == 2


def test_invalid_schema_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "invalid.sqlite"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE thread_goals (thread_id TEXT PRIMARY KEY)")
    monkeypatch.setenv("CODEX_GOALS_DB", str(db))

    assert lookup_native_goal(SESSION_ID) is None


def test_unknown_thread_is_none(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "goals.sqlite"
    _create_db(db)
    monkeypatch.setenv("CODEX_GOALS_DB", str(db))

    assert lookup_native_goal("22222222-2222-2222-2222-222222222222") is None


def test_batch_lookup_returns_only_existing_threads(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "goals.sqlite"
    _create_db(db)
    second_id = "22222222-2222-2222-2222-222222222222"
    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT INTO thread_goals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (second_id, "native-id-2", OBJECTIVE, "complete", 100, 30, 50, 3000, 4000),
        )
    monkeypatch.setenv("CODEX_GOALS_DB", str(db))

    result = lookup_native_goals((SESSION_ID, second_id, "33333333-3333-3333-3333-333333333333"))

    assert set(result) == {SESSION_ID, second_id}
    assert result[SESSION_ID].goal_id == "native-id"
    assert result[second_id].status == "complete"


def test_discovery_uses_one_native_db_connection(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "goals.sqlite"
    _create_db(db)
    second_id = "22222222-2222-2222-2222-222222222222"
    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT INTO thread_goals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (second_id, "native-id-2", OBJECTIVE, "active", 100, 30, 50, 3000, 4000),
        )
    sessions = tmp_path / "sessions"
    project = tmp_path / "project"
    project.mkdir()
    for name, session_id in (("a", SESSION_ID), ("b", second_id)):
        transcript = sessions / "2026" / "09" / "17" / f"rollout-{name}-{session_id}.jsonl"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        _write_transcript(transcript)
        lines = transcript.read_text(encoding="utf-8")
        transcript.write_text(
            json.dumps({"type": "session_meta", "payload": {
                "session_id": session_id, "cwd": str(project),
            }}) + "\n" + lines,
            encoding="utf-8",
        )
    monkeypatch.setenv("CODEX_SESSIONS_DIR", str(sessions))
    monkeypatch.setenv("CODEX_GOALS_DB", str(db))
    goal_monitor._DISCOVERY_CACHE.clear()
    original_connect = codex_goals_db.sqlite3.connect
    calls = 0

    def counted_connect(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(codex_goals_db.sqlite3, "connect", counted_connect)

    result = goal_monitor.discover_goal_sessions(str(project))

    assert len(result) == 2
    assert calls == 1

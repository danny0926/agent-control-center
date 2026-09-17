from __future__ import annotations

# Runtime UUID literals in this module are synthetic fixtures.

import json
from pathlib import Path

from control_center import claude_activity
from control_center.codex_exec_binding import bind_child_session, extract_events_path

THREAD_ID = "01a0afb4-7fdd-7462-818e-0294e6adeb23"
PROJECT_SESSION = "11111111-1111-1111-1111-111111111111"


def _write_events(path: Path, thread_id: str = THREAD_ID, event_type: str = "thread.started") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"type": event_type, "thread_id": thread_id}) + "\n",
        encoding="utf-8",
    )
    return path


def _write_rollout(
    sessions: Path,
    cwd: Path,
    *,
    thread_id: str = THREAD_ID,
    model: str | None = "gpt-5.6-luna",
    day: str = "17",
) -> Path:
    path = sessions / "2026" / "09" / day / f"rollout-2026-09-{day}T22-10-37-{thread_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict] = [
        {
            "type": "session_meta",
            "payload": {"session_id": thread_id, "cwd": str(cwd), "originator": "codex_exec", "source": "exec"},
        }
    ]
    if model is not None:
        records.append({"type": "turn_context", "payload": {"cwd": str(cwd), "model": model}})
    path.write_text("\n".join(json.dumps(item) for item in records), encoding="utf-8")
    return path


def _command(events: Path) -> str:
    return f'codex exec -m gpt-5.6-luna --json -o "result.md" "任務" > "{events}"'


def test_extract_events_path_accepts_all_quoting_forms() -> None:
    assert extract_events_path('codex exec "t" > "/tmp/dir with space/e.jsonl"') == Path("/tmp/dir with space/e.jsonl")
    assert extract_events_path("codex exec 't' > '/tmp/e.jsonl'") == Path("/tmp/e.jsonl")
    assert extract_events_path("codex exec t > /tmp/e.jsonl") == Path("/tmp/e.jsonl")


def test_extract_events_path_refuses_non_stdout_redirects() -> None:
    # 只有 stdout 導向才會收到 thread.started；把 stderr 或追加導向當成事件檔會綁到錯的檔案。
    assert extract_events_path("codex exec t 2> err.log") is None
    assert extract_events_path("codex exec t >> append.log") is None
    assert extract_events_path("codex exec t &> all.log") is None
    assert extract_events_path("codex exec t") is None


def test_binds_child_session_from_events_and_rollout(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = tmp_path / "sessions"
    events = _write_events(tmp_path / "events" / "run.jsonl")
    rollout = _write_rollout(sessions, project)
    monkeypatch.setenv("CODEX_SESSIONS_DIR", str(sessions))

    binding = bind_child_session(_command(events), str(project))

    assert binding is not None
    assert binding.thread_id == THREAD_ID
    assert binding.rollout_path == rollout
    assert binding.observed_model == "gpt-5.6-luna"
    assert binding.originator == "codex_exec"


def test_first_event_must_be_thread_started(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = tmp_path / "sessions"
    events = _write_events(tmp_path / "events" / "run.jsonl", event_type="turn.started")
    _write_rollout(sessions, project)
    monkeypatch.setenv("CODEX_SESSIONS_DIR", str(sessions))

    assert bind_child_session(_command(events), str(project)) is None


def test_ambiguous_rollout_is_refused(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = tmp_path / "sessions"
    events = _write_events(tmp_path / "events" / "run.jsonl")
    _write_rollout(sessions, project, day="17")
    _write_rollout(sessions, project, day="18")
    monkeypatch.setenv("CODEX_SESSIONS_DIR", str(sessions))

    # 兩份 transcript 都符合時無從判定是哪一次執行，不可任選一個。
    assert bind_child_session(_command(events), str(project)) is None


def test_rollout_outside_project_is_refused(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    sessions = tmp_path / "sessions"
    events = _write_events(tmp_path / "events" / "run.jsonl")
    _write_rollout(sessions, elsewhere)
    monkeypatch.setenv("CODEX_SESSIONS_DIR", str(sessions))

    assert bind_child_session(_command(events), str(project)) is None


def test_missing_turn_context_still_binds_without_observed_model(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = tmp_path / "sessions"
    events = _write_events(tmp_path / "events" / "run.jsonl")
    _write_rollout(sessions, project, model=None)
    monkeypatch.setenv("CODEX_SESSIONS_DIR", str(sessions))

    binding = bind_child_session(_command(events), str(project))

    # 認得出是哪一次執行，只是還沒看到實際模型；這不該讓整筆綁定失效。
    assert binding is not None
    assert binding.thread_id == THREAD_ID
    assert binding.observed_model is None


def _write_claude_transcript(sessions: Path, project: Path, command: str) -> None:
    path = sessions / "project-key" / f"{PROJECT_SESSION}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    items = [
        {
            "type": "attachment", "uuid": "goal-event-1", "timestamp": "2026-09-17T14:06:49Z",
            "cwd": str(project), "sessionId": PROJECT_SESSION, "isSidechain": False,
            "attachment": {
                "type": "goal_status", "goal_id": "goal-event-1", "met": False,
                "sentinel": True, "condition": "請叫 gpt-5.6-luna 完成綁定",
            },
        },
        {
            "type": "assistant", "uuid": "launch-1", "timestamp": "2026-09-17T14:09:31Z",
            "cwd": str(project), "sessionId": PROJECT_SESSION, "isSidechain": False,
            "message": {"content": [{
                "type": "tool_use", "id": "toolu_first", "name": "Bash",
                "input": {"command": command, "description": "外包實作", "run_in_background": True},
            }]},
        },
    ]
    path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in items), encoding="utf-8")


def test_delegation_reports_verified_binding(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = tmp_path / "sessions"
    claude_sessions = tmp_path / "claude-projects"
    events = _write_events(tmp_path / "events" / "run.jsonl")
    _write_rollout(sessions, project)
    _write_claude_transcript(claude_sessions, project, _command(events))
    monkeypatch.setenv("CODEX_SESSIONS_DIR", str(sessions))
    monkeypatch.setenv("CLAUDE_PROJECTS_DIR", str(claude_sessions))
    claude_activity._CACHE.clear()

    _, delegations = claude_activity.discover_claude_activity(str(project))

    assert len(delegations) == 1
    delegation = delegations[0]
    assert delegation.goal_binding == "verified"
    assert delegation.child_session_id == THREAD_ID
    assert delegation.observed_model == "gpt-5.6-luna"
    assert any(THREAD_ID in line for line in delegation.evidence)


def test_delegation_stays_unverified_without_events_file(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = tmp_path / "sessions"
    claude_sessions = tmp_path / "claude-projects"
    _write_rollout(sessions, project)
    missing = tmp_path / "events" / "never-written.jsonl"
    _write_claude_transcript(claude_sessions, project, _command(missing))
    monkeypatch.setenv("CODEX_SESSIONS_DIR", str(sessions))
    monkeypatch.setenv("CLAUDE_PROJECTS_DIR", str(claude_sessions))
    claude_activity._CACHE.clear()

    _, delegations = claude_activity.discover_claude_activity(str(project))

    assert len(delegations) == 1
    delegation = delegations[0]
    # 事件檔不在就是不知道派給了哪一個 thread，不能退化成用時間或 cwd 猜。
    assert delegation.goal_binding == "unverified"
    assert delegation.child_session_id is None
    assert delegation.observed_model is None
    assert delegation.evidence == [
        "Claude tool_use 精確記錄 codex exec",
        "尚未取得 child session identity；不以 cwd 或時間猜測",
    ]

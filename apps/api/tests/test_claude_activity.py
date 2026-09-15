from __future__ import annotations

# Runtime UUID literals in this module are synthetic fixtures.

import json
from pathlib import Path

import pytest

from control_center import claude_activity


def _write(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in items), encoding="utf-8")


def test_discovers_claude_goal_and_keeps_repeated_dispatch_status_separate(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = tmp_path / "claude-projects"
    session_id = "11111111-1111-1111-1111-111111111111"
    transcript = sessions / "project-key" / f"{session_id}.jsonl"
    objective = "請叫gpt6來完成圖片與詳細資料"
    _write(transcript, [
        {
            "type": "attachment", "uuid": "goal-event-1", "timestamp": "2026-09-14T14:06:49Z",
            "cwd": str(project), "sessionId": session_id, "isSidechain": False,
            "attachment": {"type": "goal_status", "goal_id": "goal-event-1", "met": False, "sentinel": True, "condition": objective},
        },
        {
            "type": "assistant", "uuid": "launch-1", "timestamp": "2026-09-14T14:09:31Z",
            "cwd": str(project), "sessionId": session_id, "isSidechain": False,
            "message": {"content": [{
                "type": "tool_use", "id": "toolu_first", "name": "Bash",
                "input": {"command": "codex exec -m gpt-5.6-sol - < task.md", "description": "第一次派工", "run_in_background": True},
            }]},
        },
        {
            "type": "user", "timestamp": "2026-09-14T14:09:32Z", "cwd": str(project),
            "sessionId": session_id, "isSidechain": False,
            "toolUseResult": {"backgroundTaskId": "task-one"},
            "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_first", "content": "running"}]},
        },
        {
            "type": "assistant", "timestamp": "2026-09-14T14:10:40Z", "cwd": str(project),
            "sessionId": session_id, "isSidechain": False,
            "message": {"content": [{"type": "tool_use", "id": "stop-1", "name": "TaskStop", "input": {"task_id": "task-one"}}]},
        },
        {
            "type": "user", "timestamp": "2026-09-14T14:10:41Z", "cwd": str(project),
            "sessionId": session_id, "isSidechain": False,
            "toolUseResult": {"task_id": "task-one", "message": "Successfully stopped task: task-one"},
            "message": {"content": [{"type": "tool_result", "tool_use_id": "stop-1", "content": "stopped"}]},
        },
        {
            "type": "assistant", "uuid": "launch-2", "timestamp": "2026-09-14T14:11:56Z",
            "cwd": str(project), "sessionId": session_id, "isSidechain": False,
            "message": {"content": [{
                "type": "tool_use", "id": "toolu_second", "name": "Bash",
                "input": {"command": "codex exec -m gpt-5.6-sol - < task.md", "description": "第二次派工", "run_in_background": True},
            }]},
        },
        {
            "type": "user", "timestamp": "2026-09-14T14:11:57Z", "cwd": str(project),
            "sessionId": session_id, "isSidechain": False,
            "toolUseResult": {"backgroundTaskId": "task-two"},
            "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_second", "content": "running"}]},
        },
    ])
    monkeypatch.setenv("CLAUDE_PROJECTS_DIR", str(sessions))

    goals, delegations = claude_activity.discover_claude_activity(str(project))

    assert goals[0].provider == "claude"
    assert goals[0].goal_id == "goal-event-1"
    assert goals[0].objective == objective
    assert [item.background_task_id for item in delegations] == ["task-two", "task-one"]
    assert delegations[0].status == "stale"
    assert delegations[1].status == "stopped"
    assert all(item.goal_binding == "unverified" for item in delegations)
    assert all(item.requested_model == "gpt6" for item in delegations)
    assert all(item.launch_model == "gpt-5.6-sol" for item in delegations)
    assert all(item.launch_model_compliance == "mismatch" for item in delegations)
    assert all(item.observed_model_compliance == "unknown" for item in delegations)
    assert all(item.model_compliance == "unknown" for item in delegations)


def test_ignores_sidechain_and_other_project(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    other = tmp_path / "other"
    project.mkdir(); other.mkdir()
    sessions = tmp_path / "claude-projects"
    _write(sessions / "key" / "session.jsonl", [
        {"type": "attachment", "uuid": "side", "cwd": str(project), "sessionId": "one", "isSidechain": True,
         "attachment": {"type": "goal_status", "met": False, "condition": "side goal"}},
        {"type": "attachment", "uuid": "other", "cwd": str(other), "sessionId": "two", "isSidechain": False,
         "attachment": {"type": "goal_status", "met": False, "condition": "other goal"}},
    ])
    monkeypatch.setenv("CLAUDE_PROJECTS_DIR", str(sessions))

    goals, delegations = claude_activity.discover_claude_activity(str(project))

    assert goals == []
    assert delegations == []


def test_task_notification_closes_the_exact_background_dispatch(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = tmp_path / "claude-projects"
    _write(sessions / "key" / "session.jsonl", [
        {"type": "assistant", "timestamp": "2026-09-15T01:00:00Z", "cwd": str(project),
         "sessionId": "parent", "isSidechain": False, "message": {"content": [{"type": "tool_use",
         "id": "toolu_done", "name": "Bash", "input": {"command": "codex exec -m gpt-6-astra task",
         "description": "完成工作", "run_in_background": True}}]}},
        {"type": "user", "timestamp": "2026-09-15T01:00:01Z", "cwd": str(project),
         "sessionId": "parent", "isSidechain": False, "toolUseResult": {"backgroundTaskId": "task-done"},
         "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_done", "content": "running"}]}},
        {"type": "queue-operation", "operation": "enqueue", "timestamp": "2026-09-15T01:03:00Z",
         "sessionId": "parent", "cwd": str(project), "content": "<task-notification>\n<task-id>task-done</task-id>\n<tool-use-id>toolu_done</tool-use-id>\n<status>completed</status>\n</task-notification>"},
    ])
    monkeypatch.setenv("CLAUDE_PROJECTS_DIR", str(sessions))

    _, delegations = claude_activity.discover_claude_activity(str(project))

    assert len(delegations) == 1
    assert delegations[0].status == "completed"
    assert delegations[0].updated_at.isoformat().startswith("2026-09-15T01:03:00")


def test_launch_model_is_read_from_codex_exec_not_an_earlier_python_flag() -> None:
    command = "python -m http.server 9000 && codex exec -m gpt-6-astra task"

    assert claude_activity._model_from_command(command) == "gpt-6-astra"


def _identity_events(project: Path) -> list[dict]:
    base = {"sessionId": "parent", "cwd": str(project), "timestamp": "2026-09-15T01:00:00Z"}
    return [
        {**base, "type": "assistant", "message": {"content": [{"type": "tool_use", "id": "launch",
         "name": "Bash", "input": {"command": "codex exec -m gpt-6-astra task", "run_in_background": True}}]}},
        {**base, "type": "user", "toolUseResult": {"backgroundTaskId": "task-one"}, "message": {"content": [
         {"type": "tool_result", "tool_use_id": "launch", "content": "running"}]}},
        {**base, "type": "assistant", "message": {"content": [{"type": "tool_use", "id": "stop",
         "name": "TaskStop", "input": {"task_id": "task-one"}}]}},
        {**base, "type": "user", "toolUseResult": {"task_id": "task-one", "message": "Successfully stopped task: task-one"},
         "message": {"content": [{"type": "tool_result", "tool_use_id": "stop", "content": "stopped"}]}},
    ]


@pytest.mark.parametrize("invalid", ["wrong_tool", "wrong_task", "no_stop", "is_error", "not_stopped", "other_session"])
def test_stop_requires_exact_successful_chain(tmp_path: Path, invalid: str) -> None:
    project = tmp_path / "project"
    project.mkdir()
    records = _identity_events(project)
    if invalid == "wrong_tool":
        records[-1]["message"]["content"][0]["tool_use_id"] = "other-stop"
    elif invalid == "wrong_task":
        records[-1]["toolUseResult"]["task_id"] = "other-task"
    elif invalid == "no_stop":
        del records[2]
    elif invalid == "is_error":
        records[-1]["message"]["content"][0]["is_error"] = True
    elif invalid == "not_stopped":
        records[-1]["toolUseResult"]["message"] = "task was not stopped"
    elif invalid == "other_session":
        records[-1]["sessionId"] = "other-parent"
    path = tmp_path / "session.jsonl"
    _write(path, records)
    _, delegations = claude_activity._scan_session(path, str(project))
    assert len(delegations) == 1 and delegations[0].status != "stopped"


def test_claude_same_text_reset_requires_command_or_native_id(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    base = {"sessionId": "parent", "cwd": str(project), "timestamp": "2026-09-15T01:00:00Z"}
    command = "<command-name>/goal</command-name><command-args>同一目標</command-args>"
    status = {**base, "type": "attachment", "uuid": "status-1", "attachment": {
        "type": "goal_status", "condition": "同一目標", "met": False}}
    path = tmp_path / "session.jsonl"
    _write(path, [status, {**status, "uuid": "status-2"}])
    unknown, _ = claude_activity._scan_session(path, str(project))
    assert len(unknown) == 1 and unknown[0].goal_id is None and not unknown[0].epoch_verified
    _write(path, [
        {**base, "type": "user", "uuid": "reset-1", "message": {"content": command}}, status,
        {**status, "uuid": "heartbeat"},
        {**base, "type": "user", "uuid": "reset-2", "message": {"content": command}},
        {**status, "uuid": "status-3"},
    ])
    goals, _ = claude_activity._scan_session(path, str(project))
    assert len(goals) == 2
    assert [goal.goal_id for goal in goals] == ["parent:command:reset-1", "parent:command:reset-2"]
    assert all(goal.epoch_verified for goal in goals)


def test_unrelated_assistant_goal_text_is_not_reset(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    _write(path, [{"type": "assistant", "cwd": str(tmp_path), "sessionId": "parent", "uuid": "quoted",
        "message": {"content": "<command-name>/goal</command-name><command-args>fake</command-args>"}}])
    goals, _ = claude_activity._scan_session(path, str(tmp_path))
    assert goals == []


def test_completion_notification_with_conflicting_ids_is_ignored(tmp_path: Path) -> None:
    records = _identity_events(tmp_path)[:2]
    records.append({"type": "queue-operation", "cwd": str(tmp_path), "sessionId": "parent", "content":
        "<task-id>task-one</task-id><tool-use-id>different-launch</tool-use-id><status>completed</status>"})
    path = tmp_path / "session.jsonl"
    _write(path, records)
    _, delegations = claude_activity._scan_session(path, str(tmp_path))
    assert delegations[0].status != "completed"


@pytest.mark.parametrize("content", [
    "以下只是範例：<command-name>/goal</command-name><command-args>fake</command-args>",
    "```xml\n<command-name>/goal</command-name><command-args>fake</command-args>\n```",
    "<command-name>/goal</command-name><command-args>fake</command-args> 請解釋這段",
    "<command-name>/goal</command-name>其他內容<command-args>fake</command-args>",
    "<command-message>other</command-message><command-name>/goal</command-name><command-args>fake</command-args>",
    [{"type": "text", "text": "<command-name>/goal</command-name><command-args>fake</command-args>"},
     {"type": "image", "source": "fixture"}],
])
def test_quoted_or_mixed_user_xml_is_not_goal_reset(content) -> None:
    assert claude_activity.exact_goal_command({"type": "user", "message": {"content": content}}) is None


@pytest.mark.parametrize("content", [
    "<command-name>/goal</command-name><command-args>同一目標</command-args>",
    "\n<command-message>goal</command-message>\n<command-name>/goal</command-name>\n<command-args>同一目標</command-args>\n",
    [{"type": "text", "text": "<command-name>/goal</command-name><command-args>同一目標</command-args>"}],
])
def test_whole_user_goal_envelopes_are_recognized(content) -> None:
    assert claude_activity.exact_goal_command({"type": "user", "message": {"content": content}}) == "同一目標"
    assert claude_activity.exact_goal_command({"type": "assistant", "message": {"content": content}}) is None


def test_delegation_identity_uses_full_case_sensitive_tool_and_parent_session(tmp_path: Path) -> None:
    suffix = "same-suffix1"
    assert len(suffix) == 12
    identifiers = set()
    for session, tool_id in [("parent-a", "first-" + suffix), ("parent-a", "second-" + suffix),
                             ("parent-b", "first-" + suffix), ("parent-a", "first-" + suffix.upper())]:
        records = _identity_events(tmp_path)[:1]
        records[0]["sessionId"] = session
        records[0]["message"]["content"][0]["id"] = tool_id
        path = tmp_path / f"{len(identifiers)}.jsonl"
        _write(path, records)
        _, delegations = claude_activity._scan_session(path, str(tmp_path))
        assert len(delegations) == 1
        identifiers.add(delegations[0].id)
        _, replayed = claude_activity._scan_session(path, str(tmp_path))
        assert replayed[0].id == delegations[0].id
    assert len(identifiers) == 4


def test_replayed_launch_does_not_reset_stopped_delegation(tmp_path: Path) -> None:
    records = _identity_events(tmp_path)
    records.append(records[0])
    path = tmp_path / "session.jsonl"
    _write(path, records)
    _, delegations = claude_activity._scan_session(path, str(tmp_path))
    assert len(delegations) == 1 and delegations[0].status == "stopped"

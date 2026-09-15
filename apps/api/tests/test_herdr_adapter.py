from control_center import herdr_adapter
import subprocess
import pytest


@pytest.mark.parametrize("kind", ["codex", "claude"])
def test_agent_arguments_preserve_native_permission_checks(kind):
    assert herdr_adapter._agent_args(kind, "") == []
    assert herdr_adapter._agent_args(kind, " chosen-model ") == ["--model", "chosen-model"]


def test_unsupported_agent_cannot_get_launch_arguments():
    with pytest.raises(ValueError):
        herdr_adapter._agent_args("unknown", "")


def test_list_project_agents_uses_live_metadata_and_filters_other_projects(monkeypatch) -> None:
    def fake_run_json(*args: str) -> dict:
        if args == ("workspace", "list"):
            return {"result": {"workspaces": [
                {"workspace_id": "w1", "label": "Project"},
                {"workspace_id": "w2", "label": "Other"},
            ]}}
        return {"result": {"agents": [
            {"agent": "codex", "agent_status": "working", "cwd": "D:\\project", "focused": True, "pane_id": "w1:p1", "revision": 8, "workspace_id": "w1", "terminal_title_stripped": "implement-import"},
            {"agent": "claude", "agent_status": "idle", "cwd": "D:\\other", "focused": False, "pane_id": "w2:p1", "revision": 2, "workspace_id": "w2", "terminal_title_stripped": "other"},
        ]}}

    monkeypatch.setattr(herdr_adapter, "_run_json", fake_run_json)
    monkeypatch.setattr(
        herdr_adapter,
        "_read_recent_text",
        lambda agent_id: "› 請完成匯入流程，並補上失敗狀態測試。\n\n• Working",
    )

    result = herdr_adapter.list_project_agents("D:\\project")

    assert result.connected is True
    assert len(result.agents) == 1
    assert result.agents[0].provider == "codex"
    assert result.agents[0].status == "working"
    assert result.agents[0].task_summary == "請完成匯入流程，並補上失敗狀態測試。"
    assert result.agents[0].latest_human_request == "請完成匯入流程，並補上失敗狀態測試。"
    assert result.agents[0].request_source == "terminal_extracted"


def test_latest_request_skips_assent_only_prompt() -> None:
    transcript = """
❯ 請先等 QA 跑完，再整理缺陷並排優先序。

● 好，等它。

❯ OK GO

● 開始處理。
"""

    assert herdr_adapter._latest_substantive_request(transcript) == "請先等 QA 跑完，再整理缺陷並排優先序。"


def test_latest_request_expands_assent_using_agent_question() -> None:
    transcript = """
❯ 請先整理問題。

● 我建議把前端與後端拆成兩個不重疊任務。要我照這個順序派嗎？

❯ OK GO

● 已開始處理。
"""

    assert herdr_adapter._latest_substantive_request(transcript) == (
        "同意執行：我建議把前端與後端拆成兩個不重疊任務。要我照這個順序派嗎？"
    )


def test_extract_multiline_codex_request_and_ignore_placeholder() -> None:
    transcript = """
› 第一行問題
  第二行補充條件

• Working

› Ask Codex to do anything
"""

    assert herdr_adapter._extract_human_requests(transcript) == ["第一行問題\n第二行補充條件"]


def test_redact_terminal_hides_common_secrets() -> None:
    text = "Authorization: Bearer abc123\nAPI_KEY=secret-value\nsk-exampleabcdefghijklmnop"
    redacted = herdr_adapter._redact_terminal(text)
    assert "abc123" not in redacted
    assert "secret-value" not in redacted
    assert "sk-example" not in redacted


def test_terminal_snapshot_falls_back_to_visible_while_agent_is_working(monkeypatch) -> None:
    calls: list[str] = []

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
        source = command[command.index("--source") + 1]
        calls.append(source)
        if source == "recent-unwrapped":
            raise subprocess.CalledProcessError(1, command, stderr="agent_not_idle")
        return subprocess.CompletedProcess(command, 0, stdout="visible output", stderr="")

    monkeypatch.setattr(herdr_adapter.subprocess, "run", fake_run)

    content, source = herdr_adapter._read_terminal_snapshot("wM:p1")

    assert content == "visible output"
    assert source == "visible"
    assert calls == ["recent-unwrapped", "visible"]


def test_send_agent_message_targets_explicit_pane(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setenv("HERDR_ENV", "1")

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(herdr_adapter.subprocess, "run", fake_run)

    herdr_adapter.send_agent_message("wN:p1", "請回報目前 checkpoint")

    assert calls == [["herdr", "agent", "prompt", "wN:p1", "請回報目前 checkpoint"]]


def test_send_agent_message_preserves_slash_commands(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setenv("HERDR_ENV", "1")

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(herdr_adapter.subprocess, "run", fake_run)

    herdr_adapter.send_agent_message("wN:p1", "/model gpt-5.6-sol")

    assert calls == [
        ["herdr", "pane", "send-text", "wN:p1", "/model gpt-5.6-sol"],
        ["herdr", "pane", "send-keys", "wN:p1", "enter"],
    ]


def test_start_project_agent_passes_model_and_initial_prompt(monkeypatch) -> None:
    json_calls: list[list[str]] = []
    prompt_calls: list[tuple[str, str]] = []

    def fake_run_json_control(args: list[str], timeout: int = 30) -> dict:
        json_calls.append(args)
        if args[:2] == ["pane", "split"]:
            return {"result": {"pane": {"pane_id": "wT:p2"}}}
        return {"result": {"agent": {"pane_id": "wT:p2"}}}

    monkeypatch.setattr(herdr_adapter, "_run_json_control", fake_run_json_control)
    monkeypatch.setattr(
        herdr_adapter,
        "send_agent_message",
        lambda agent_id, body: prompt_calls.append((agent_id, body)),
    )

    result = herdr_adapter.start_project_agent("D:\\project", "codex", "gpt-6-astra", "/goal ship it")

    assert result["pane_id"] == "wT:p2"
    assert json_calls[0][:6] == ["pane", "split", "--current", "--direction", "right", "--cwd"]
    assert json_calls[1][-2:] == ["--model", "gpt-6-astra"]
    assert "--yolo" not in json_calls[1]
    assert "--" in json_calls[1]
    assert prompt_calls == [("wT:p2", "/goal ship it")]


def test_shell_command_blocks_dangerous_commands_without_confirmation() -> None:
    risk = herdr_adapter.run_shell_command("wT:p2", "git reset --hard", confirm_dangerous=False)

    assert risk is not None


def test_shell_command_runs_when_confirmed(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(herdr_adapter.subprocess, "run", fake_run)

    risk = herdr_adapter.run_shell_command("wT:p2", "git reset --hard", confirm_dangerous=True)

    assert risk is None
    assert calls == [["herdr", "pane", "run", "wT:p2", "git reset --hard"]]


def test_stream_identity_rejects_pane_after_it_moves_to_another_project(monkeypatch) -> None:
    monkeypatch.setattr(
        herdr_adapter,
        "_run_json",
        lambda *args: {"result": {"agents": [
            {"pane_id": "wN:p1", "cwd": "D:\\other"},
        ]}},
    )

    assert herdr_adapter.agent_belongs_to_project("wN:p1", "D:\\project") is False
    assert herdr_adapter.agent_belongs_to_project("not-a-pane", "D:\\project") is False


def test_terminal_snapshot_marks_claude_internal_scroll_as_not_latest(monkeypatch) -> None:
    monkeypatch.setenv("HERDR_ENV", "1")
    monkeypatch.setattr(
        herdr_adapter,
        "_read_terminal_snapshot",
        lambda agent_id, lines: ("older output\n5 new messages (ctrl+End) ↓", "visible"),
    )

    transcript = herdr_adapter.read_agent_output("wM:p1")

    assert transcript.is_at_latest is False
    assert transcript.freshness_warning is not None
    assert "5 則新訊息" in transcript.freshness_warning

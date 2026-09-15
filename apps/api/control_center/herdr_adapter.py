from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from .models import AgentSession, AgentSessionsResponse, AgentTranscript, ShellPaneResponse


class HerdrUnavailable(RuntimeError):
    pass


def _run_json(*args: str) -> dict:
    if os.environ.get("HERDR_ENV") != "1":
        raise HerdrUnavailable("Control Center 不是從 Herdr 環境啟動，無法安全判定目前 session。")
    try:
        completed = subprocess.run(
            ["herdr", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=True, timeout=8,
        )
    except FileNotFoundError as error:
        raise HerdrUnavailable("找不到 Herdr CLI。") from error
    except subprocess.TimeoutExpired as error:
        raise HerdrUnavailable("Herdr socket 回應逾時。") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or error.stdout.strip() or "Herdr command failed"
        raise HerdrUnavailable(detail) from error
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise HerdrUnavailable("Herdr 回傳了無法解析的狀態。") from error


def _is_within_project(cwd: str, project_root: str) -> bool:
    try:
        cwd_path = Path(cwd).resolve()
        root_path = Path(project_root).resolve()
        return cwd_path == root_path or root_path in cwd_path.parents
    except OSError:
        return False


_PROMPT_MARKER = re.compile(r"^[\u203a\u276f]\s*(.*)$")
_ASSENT_ONLY = re.compile(
    r"^(?:ok(?:ay)?(?:\s+go)?|go|yes|y|好|好的|可以|同意|繼續|開始|執行|照做)[！!。.]?$",
    re.IGNORECASE,
)
_PLACEHOLDERS = {"ask codex to do anything", "ask claude to do anything"}


def _read_terminal_snapshot(agent_id: str, lines: int = 240) -> tuple[str, str]:
    last_error: subprocess.CalledProcessError | None = None
    for source in ("recent-unwrapped", "visible"):
        try:
            completed = subprocess.run(
                ["herdr", "agent", "read", agent_id, "--source", source, "--lines", str(lines)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", check=True, timeout=8,
            )
            return _redact_terminal(completed.stdout)[-30_000:], source
        except subprocess.CalledProcessError as error:
            last_error = error
    assert last_error is not None
    raise last_error


def _read_recent_text(agent_id: str, lines: int = 240) -> str:
    content, _ = _read_terminal_snapshot(agent_id, lines)
    return content


def _extract_human_requests(text: str) -> list[str]:
    """Extract visible Codex/Claude human prompt blocks from a Herdr terminal snapshot."""
    requests: list[str] = []
    current: list[str] | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        marker = _PROMPT_MARKER.match(line)
        if marker:
            if current:
                requests.append("\n".join(current).strip())
            first_line = marker.group(1).strip()
            current = [first_line] if first_line else None
            continue
        if current is None:
            continue
        stripped = line.strip()
        if not stripped:
            requests.append("\n".join(current).strip())
            current = None
        elif re.match(r"^[\u2022\u25cf\u273b\u2500\u250c\u251c\u2514\u2502]", stripped):
            requests.append("\n".join(current).strip())
            current = None
        else:
            current.append(stripped)
    if current:
        requests.append("\n".join(current).strip())
    return [
        request for request in requests
        if request and request.casefold() not in _PLACEHOLDERS
    ]


def _latest_substantive_request(text: str) -> str | None:
    requests = _extract_human_requests(text)
    if requests and _ASSENT_ONLY.fullmatch(requests[-1].strip()):
        assent = requests[-1].strip()
        marker_matches = list(
            re.finditer(
                rf"^[\u203a\u276f]\s*{re.escape(assent)}\s*$",
                text,
                re.MULTILINE | re.IGNORECASE,
            )
        )
        if marker_matches:
            earlier = text[:marker_matches[-1].start()]
            questions = re.findall(r"([^\n]{4,500}?[？?])", earlier)
            if questions:
                question = re.sub(r"^[\s\u2022\u25cf\u2502\u251c\u2514]+", "", questions[-1]).strip()
                return f"同意執行：{question}"
    for request in reversed(requests):
        if not _ASSENT_ONLY.fullmatch(request.strip()):
            return request
    return requests[-1] if requests else None


def _request_preview(request: str, limit: int = 180) -> str:
    compact = re.sub(r"\s+", " ", request).strip()
    return compact if len(compact) <= limit else f"{compact[:limit - 1].rstrip()}…"


def list_project_agents(project_root: str) -> AgentSessionsResponse:
    workspaces_payload = _run_json("workspace", "list")
    agents_payload = _run_json("agent", "list")
    workspace_labels = {
        item["workspace_id"]: item.get("label") or item["workspace_id"]
        for item in workspaces_payload["result"].get("workspaces", [])
    }
    agents: list[AgentSession] = []
    for item in agents_payload["result"].get("agents", []):
        cwd = item.get("cwd") or ""
        if not _is_within_project(cwd, project_root):
            continue
        title = item.get("terminal_title_stripped") or workspace_labels.get(item["workspace_id"], "未命名工作")
        root_name = Path(project_root).name.casefold()
        generic_title = title.casefold() in {root_name, "codex", "claude", "powershell", "cmd"}
        latest_request = None
        request_source = "unavailable"
        request_explanation = "最近的終端畫面中找不到可辨識的人類指派。"
        try:
            latest_request = _latest_substantive_request(_read_recent_text(item["pane_id"]))
        except (OSError, subprocess.SubprocessError):
            pass
        if latest_request:
            task_summary = _request_preview(latest_request)
            request_source = "terminal_extracted"
            request_explanation = "從 Herdr 最近可見的 Codex／Claude 人類輸入標記擷取；不保證涵蓋更早的完整對話。"
        elif not generic_title:
            task_summary = title
            request_source = "pane_title"
            request_explanation = "最近輸出中沒有可辨識的人類指派，目前以 Herdr pane 標題代替。"
        else:
            task_summary = "尚未取得最近的人類指派"
        agents.append(
            AgentSession(
                id=item["pane_id"],
                provider=item.get("agent", "unknown"),
                status=item.get("agent_status", "unknown"),
                workspace_id=item["workspace_id"],
                workspace_label=workspace_labels.get(item["workspace_id"], item["workspace_id"]),
                pane_id=item["pane_id"],
                cwd=cwd,
                title=title,
                task_summary=task_summary,
                latest_human_request=latest_request,
                request_source=request_source,
                request_explanation=request_explanation,
                focused=bool(item.get("focused")),
                state_revision=item.get("revision"),
                runtime_session_id=item.get("agent_session_id"),
            )
        )
    return AgentSessionsResponse(
        connected=True,
        source="Herdr socket API",
        limitation="狀態來自 Herdr；最近指派由可見終端中的人類輸入標記擷取，找不到時才使用 pane 標題。",
        agents=agents,
    )


def agent_belongs_to_project(agent_id: str, project_root: str) -> bool:
    """Revalidate a stream target without scraping every Agent transcript."""
    if not re.fullmatch(r"w[A-Za-z0-9]+:p\d+", agent_id):
        return False
    payload = _run_json("agent", "list")
    return any(
        item.get("pane_id") == agent_id and _is_within_project(item.get("cwd") or "", project_root)
        for item in payload["result"].get("agents", [])
    )


def _redact_terminal(text: str) -> str:
    patterns = (
        (r"(?i)(authorization:\s*bearer\s+)[^\s]+", r"\1[REDACTED]"),
        (r"(?i)((?:api[_-]?key|token|password|secret)\s*[=:]\s*)[^\s]+", r"\1[REDACTED]"),
        (r"\bsk-[A-Za-z0-9_-]{16,}\b", "[REDACTED_OPENAI_KEY]"),
    )
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text


def read_agent_output(agent_id: str, lines: int = 120) -> AgentTranscript:
    if not re.fullmatch(r"w[A-Za-z0-9]+:p\d+", agent_id):
        raise ValueError("無效的 Herdr pane ID。")
    if os.environ.get("HERDR_ENV") != "1":
        raise HerdrUnavailable("Control Center 不是從 Herdr 環境啟動。")
    try:
        content, snapshot_source = _read_terminal_snapshot(agent_id, lines)
    except (OSError, subprocess.SubprocessError) as error:
        raise HerdrUnavailable("無法讀取 Agent 最近的終端輸出。") from error
    unread = re.search(r"\b(\d+)\s+new messages?\s*\(ctrl\+End\)", content, re.IGNORECASE)
    freshness_warning = None
    if unread:
        freshness_warning = (
            f"Claude 畫面停在較早位置，下方還有 {unread.group(1)} 則新訊息；"
            "Herdr 目前只能讀到這個可見畫面。請在原 Claude 視窗按 Ctrl+End。"
        )
    return AgentTranscript(
        agent_id=agent_id,
        content=content,
        source=f"Herdr {snapshot_source} terminal output",
        limitation=(
            "Agent 正在工作，Herdr 只允許讀目前可見畫面；不包含已捲出的內容。敏感字串已做基本遮罩。"
            if snapshot_source == "visible"
            else "這是最近終端輸出，不保證包含完整對話歷史；敏感字串已做基本遮罩。"
        ),
        is_at_latest=unread is None,
        freshness_warning=freshness_warning,
    )


def send_agent_message(agent_id: str, body: str) -> None:
    if not re.fullmatch(r"w[A-Za-z0-9]+:p\d+", agent_id):
        raise ValueError("無效的 Herdr pane ID。")
    if os.environ.get("HERDR_ENV") != "1":
        raise HerdrUnavailable("Control Center 不是從 Herdr 環境啟動。")
    try:
        if body.lstrip().startswith("/"):
            subprocess.run(
                ["herdr", "pane", "send-text", agent_id, body],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                check=True, timeout=8,
            )
            subprocess.run(
                ["herdr", "pane", "send-keys", agent_id, "enter"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                check=True, timeout=8,
            )
        else:
            subprocess.run(
                ["herdr", "agent", "prompt", agent_id, body], capture_output=True, text=True,
                encoding="utf-8", errors="replace", check=True, timeout=12,
            )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or error.stdout.strip() or "無法傳送訊息。"
        raise HerdrUnavailable(detail) from error
    except (OSError, subprocess.TimeoutExpired) as error:
        raise HerdrUnavailable("傳送訊息時 Herdr 沒有及時回應。") from error
def _run_json_control(args: list[str], timeout: int = 30) -> dict:
    if os.environ.get("HERDR_ENV") != "1":
        raise HerdrUnavailable("Control Center is not running inside Herdr.")
    try:
        completed = subprocess.run(
            ["herdr", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=timeout,
        )
    except FileNotFoundError as error:
        raise HerdrUnavailable("Herdr CLI is not available.") from error
    except subprocess.TimeoutExpired as error:
        raise HerdrUnavailable("Herdr command timed out.") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or error.stdout.strip() or "Herdr command failed"
        raise HerdrUnavailable(detail) from error
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise HerdrUnavailable("Herdr returned non-JSON output.") from error


def pane_belongs_to_project(pane_id: str, project_root: str) -> bool:
    if not re.fullmatch(r"w[A-Za-z0-9]+:p\d+", pane_id):
        return False
    payload = _run_json("pane", "get", pane_id)
    pane = payload["result"].get("pane", {})
    return _is_within_project(pane.get("cwd") or "", project_root)


def _agent_args(kind: str, model: str) -> list[str]:
    cleaned_model = model.strip()
    if kind == "codex":
        args = []
        if cleaned_model:
            args.extend(["--model", cleaned_model])
        return args
    if kind == "claude":
        args = []
        if cleaned_model:
            args.extend(["--model", cleaned_model])
        return args
    raise ValueError("Only Codex and Claude are supported.")


def start_project_agent(project_root: str, kind: str, model: str = "", initial_prompt: str = "") -> dict[str, str | None]:
    if kind not in {"codex", "claude"}:
        raise ValueError("Only Codex and Claude are supported.")
    root = str(Path(project_root).resolve())
    split_payload = _run_json_control(
        ["pane", "split", "--current", "--direction", "right", "--cwd", root, "--no-focus"],
        timeout=15,
    )
    pane_id = split_payload["result"]["pane"]["pane_id"]
    agent_name = f"acc_{kind}_{int(time.time())}"
    start_args = ["agent", "start", agent_name, "--kind", kind, "--pane", pane_id, "--timeout", "60000"]
    native_args = _agent_args(kind, model)
    if native_args:
        start_args.extend(["--", *native_args])
    _run_json_control(start_args, timeout=75)
    if initial_prompt.strip():
        send_agent_message(pane_id, initial_prompt.strip())
    return {"agent_id": pane_id, "pane_id": pane_id, "kind": kind, "model": model.strip() or None}


def create_project_shell(project_root: str) -> ShellPaneResponse:
    root = str(Path(project_root).resolve())
    payload = _run_json_control(
        ["pane", "split", "--current", "--direction", "down", "--cwd", root, "--no-focus"],
        timeout=15,
    )
    pane_id = payload["result"]["pane"]["pane_id"]
    return ShellPaneResponse(pane_id=pane_id, cwd=root)


_DANGEROUS_COMMAND = re.compile(
    r"(?is)\b("
    r"rm\s+-rf|remove-item\b.*\b-recurse\b|del\s+/s|rmdir\s+/s|format\b|diskpart\b|"
    r"git\s+reset\s+--hard|git\s+clean\b|stop-process\b|taskkill\b"
    r")"
)


def command_risk(command: str) -> str | None:
    if _DANGEROUS_COMMAND.search(command):
        return "這個 shell 指令可能刪除、重置或終止本機資料／程序；請明確勾選危險指令確認。"
    return None


def read_pane_output(pane_id: str, lines: int = 180) -> AgentTranscript:
    if not re.fullmatch(r"w[A-Za-z0-9]+:p\d+", pane_id):
        raise ValueError("Invalid Herdr pane ID.")
    try:
        completed = subprocess.run(
            ["herdr", "pane", "read", pane_id, "--source", "recent-unwrapped", "--lines", str(lines)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise HerdrUnavailable("Unable to read shell pane output.") from error
    return AgentTranscript(
        agent_id=pane_id,
        content=_redact_terminal(completed.stdout)[-30_000:],
        source="Herdr pane recent-unwrapped output",
        limitation="Shell pane output comes from Herdr scrollback; full-screen interactive apps may be incomplete.",
    )


def run_shell_command(pane_id: str, command: str, confirm_dangerous: bool = False) -> str | None:
    risk = command_risk(command)
    if risk and not confirm_dangerous:
        return risk
    if not re.fullmatch(r"w[A-Za-z0-9]+:p\d+", pane_id):
        raise ValueError("Invalid Herdr pane ID.")
    try:
        subprocess.run(
            ["herdr", "pane", "run", pane_id, command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=8,
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or error.stdout.strip() or "Herdr pane run failed"
        raise HerdrUnavailable(detail) from error
    except (OSError, subprocess.TimeoutExpired) as error:
        raise HerdrUnavailable("Unable to send shell command to Herdr.") from error
    return None

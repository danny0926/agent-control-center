"""Synthetic browser-test server; never import this as a production entry point.

The matching Playwright config opts in explicitly and uses port 18765. All source
files, Git history, database rows and event injections are disposable fixtures.
"""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

if os.getenv("CONTROL_CENTER_BROWSER_FIXTURE") != "1":
    raise RuntimeError("Synthetic browser fixture requires explicit test-only opt-in.")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_temporary = tempfile.TemporaryDirectory(prefix="control-center-synthetic-browser-")
atexit.register(_temporary.cleanup)
TEST_ROOT = Path(_temporary.name).resolve()
SOURCE = TEST_ROOT / "synthetic-source"
SOURCE.mkdir()
for folder in ("codex-sessions", "claude-projects", "empty-hooks"):
    (TEST_ROOT / folder).mkdir()

# These are public fixture credentials, scoped to this disposable process only.
TEST_USER, TEST_PASSWORD = "synthetic-browser-user", "synthetic-browser-password"
os.environ.update({
    "CONTROL_CENTER_DB": str(TEST_ROOT / "synthetic.sqlite"),
    "CONTROL_CENTER_BACKGROUND_ENABLED": "0",
    "CONTROL_CENTER_USER": TEST_USER,
    "CONTROL_CENTER_PASSWORD": TEST_PASSWORD,
    "CONTROL_CENTER_MODE": "standalone",
    "CONTROL_CENTER_ALLOWED_ACTIONS": "",
    "CONTROL_CENTER_ALLOWED_ORIGINS": "http://127.0.0.1:18765",
    "CODEX_SESSIONS_DIR": str(TEST_ROOT / "codex-sessions"),
    "CLAUDE_PROJECTS_DIR": str(TEST_ROOT / "claude-projects"),
})

(SOURCE / "README.md").write_text("# 合成測試專案\n\nSYNTHETIC fixture，並非即時專案或真實 Agent。\n", encoding="utf-8")
(SOURCE / "reports").mkdir()
(SOURCE / "reports" / "evidence.json").write_text(json.dumps({"source": "synthetic", "fixture_check": "passed"}), encoding="utf-8")
for args in (["init", "--quiet"], ["add", "README.md", "reports/evidence.json"], ["commit", "--quiet", "-m", "Synthetic browser fixture"]):
    subprocess.run(["git", "-C", str(SOURCE), "-c", "user.name=Synthetic Browser Fixture",
                    "-c", "user.email=synthetic@example.invalid", "-c", "commit.gpgsign=false",
                    "-c", f"core.hooksPath={TEST_ROOT / 'empty-hooks'}", *args],
                   check=True, capture_output=True, timeout=15)

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from control_center import main
from control_center.models import AgentSessionsResponse, PlanNode
from control_center.notifications import emit_event


def _forbidden_runtime(*_args, **_kwargs):
    raise AssertionError("Synthetic browser fixture must never access a live runtime.")


main.list_project_agents = lambda _root: AgentSessionsResponse(
    connected=False, source="synthetic", limitation="合成測試：未連接任何真實 Herdr。", agents=[])
main.discover_goal_sessions = lambda _root: []
main.discover_claude_activity = lambda _root: ([], [])
for _name in ("read_agent_output", "read_pane_output", "send_agent_message", "start_project_agent",
              "create_project_shell", "run_shell_command", "agent_belongs_to_project", "pane_belongs_to_project",
              "resolve_goal_session", "collect_snapshot", "reconcile_project", "reconcile_all_projects"):
    setattr(main, _name, _forbidden_runtime)

PROJECT_ID, NODE_ID = "synthetic-browser-project", "synthetic-browser-work"
node = PlanNode(id=NODE_ID, kind="work_item", title="合成成果：通知與驗收流程", description="SYNTHETIC browser fixture",
                state="implemented", state_explanation="合成資料：等待本次測試核對證據。",
                acceptance_total=1, acceptance_criteria=["合成情境可以完成驗收"], source_paths=["README.md"])
now = datetime.now(timezone.utc).isoformat()
with main.store._connect() as connection:
    connection.execute("""INSERT INTO projects
        (id,workspace_id,parent_project_id,name,purpose,source_kind,source_path,confidence,plan_status,
         facts_json,documents_json,plan_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (PROJECT_ID, "local", None, "合成測試專案", "SYNTHETIC：僅供隔離的瀏覽器驗收，不是即時來源。",
         "local_repository", str(SOURCE), "high", "confirmed", None, "[]", json.dumps([node.model_dump(mode="json")]), now, now))

app = FastAPI(title="Synthetic browser fixture — isolated test entry point")
_basic = HTTPBasic()


def fixture_auth(credentials: HTTPBasicCredentials = Depends(_basic)):
    if credentials.username != TEST_USER or credentials.password != TEST_PASSWORD:
        raise HTTPException(401, "Synthetic fixture credentials required", headers={"WWW-Authenticate": "Basic"})


@app.get("/__fixture__/health")
def fixture_health():
    return {"status": "ok", "source": "synthetic", "background_enabled": False}


@app.get("/__fixture__/info", dependencies=[Depends(fixture_auth)])
def fixture_info():
    return {"source": "synthetic", "project_id": PROJECT_ID, "node_id": NODE_ID,
            "evidence_path": "reports/evidence.json", "acceptance": node.acceptance_criteria[0]}


class SyntheticCompletion(BaseModel):
    event_key: str = Field(pattern=r"^[a-z0-9-]{1,64}$")


@app.post("/__fixture__/completion", dependencies=[Depends(fixture_auth)])
def fixture_completion(body: SyntheticCompletion):
    with main.store._connect() as connection:
        event_id = emit_event(connection, source_key=f"synthetic-browser:{body.event_key}",
                             event_type="agent.turn_completed", project_id=PROJECT_ID,
                             entity_id="SYNTHETIC-session", identity={"source_kind": "synthetic",
                             "runtime_session_id": "SYNTHETIC-session", "turn_id": body.event_key})
    return {"id": event_id, "source": "synthetic"}


# Production routes, middleware and built UI remain real; only fixture setup and
# explicit synthetic event injection live outside the production application.
app.mount("/", main.app)

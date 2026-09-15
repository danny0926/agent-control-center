from __future__ import annotations

# 最先載入專案根的 .env（見 _bootstrap_env），確保固定的遠端存取帳密
# 不論本服務被誰、用什麼方式重啟都會被補上。必須排在讀取 os.getenv 之前。
from control_center import _bootstrap_env as _bootstrap_env  # noqa: F401

import asyncio
import json
import logging
import os
import sqlite3
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .importer import scan_local_repository
from .models import (
    AgentMessageRequest,
    AgentDelegationsResponse,
    AgentSessionsResponse,
    AgentTranscript,
    ConfirmImportRequest,
    CreateMonitorRequest,
    CreateDecisionRequest,
    DecisionAnswerRequest,
    DecisionCard,
    DecisionMessageRequest,
    ImportPreview,
    ImportPreviewRequest,
    GoalMonitor,
    GoalSessionCandidatesResponse,
    MonitorEvent,
    MonitorFindingRequest,
    MonitorSnapshot,
    MonitorReconcileResult,
    PortfolioResponse,
    PlanState,
    ProjectDetail,
    ShellCommandRequest,
    ShellCommandResponse,
    ShellPaneResponse,
    StartAgentRequest,
    StartAgentResponse,
)
from .herdr_adapter import (
    HerdrUnavailable,
    _request_preview,
    agent_belongs_to_project,
    create_project_shell,
    list_project_agents,
    pane_belongs_to_project,
    read_agent_output,
    read_pane_output,
    run_shell_command,
    send_agent_message,
    start_project_agent,
)
from .goal_monitor import (
    GoalMonitorUnavailable,
    collect_snapshot,
    current_git_head,
    discover_goal_sessions,
    resolve_goal_session,
)
from .claude_activity import discover_claude_activity
from .store import Store
from .monitor_reconciler import reconcile_all_projects, reconcile_project
from .security import load_security_policy, authenticate_request, authorize_action, validate_request_origin, SecurityError
from .notifications import NotificationStore, NotificationPage, NotificationItem, NotificationPreferences, ReadNotification, ReadAllNotifications
from .verification import VerificationService, VerificationPolicyRequest, VerificationRequest, flatten, scope_hash, clean_revision


ROOT = Path(__file__).resolve().parents[3]
store = Store(Path(os.getenv("CONTROL_CENTER_DB", str(ROOT / "data" / "control-center.db"))))
inbox = NotificationStore(store._connect)
verification = VerificationService(store)
logger = logging.getLogger(__name__)


async def _monitor_reconcile_loop() -> None:
    await asyncio.sleep(2)
    while True:
        try:
            await asyncio.to_thread(reconcile_all_projects, store)
        except (sqlite3.Error, OSError, ValueError):
            logger.warning("Monitor reconciliation temporarily unavailable; will retry.")
        await asyncio.sleep(max(15, int(os.getenv("CONTROL_CENTER_RECONCILE_SECONDS", "60"))))


async def _event_collection_loop(collector) -> None:
    while True:
        try:
            await asyncio.to_thread(collector.poll)
            for project in store.portfolio().projects:
                try:
                    await asyncio.to_thread(verification.reconcile, project.id)
                except (sqlite3.Error, ValueError, OSError):
                    logger.warning("Verification reconciliation temporarily unavailable; will retry.")
        except (sqlite3.Error, ValueError, OSError):
            logger.warning("Event collection temporarily unavailable; will retry.")
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_security_policy()
    tasks = []
    if os.getenv("CONTROL_CENTER_BACKGROUND_ENABLED", "1") != "0":
        from .event_collector import RuntimeEventCollector
        collector = RuntimeEventCollector(store)
        await asyncio.to_thread(collector.bootstrap)
        tasks = [asyncio.create_task(_monitor_reconcile_loop()), asyncio.create_task(_event_collection_loop(collector))]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="Agent Control Center API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_remote_login(request: Request, call_next):
    from starlette.routing import Match
    route_template = "unmatched"
    for route in app.routes:
        match, _ = route.matches(request.scope)
        if match == Match.FULL:
            route_template = getattr(route, "path", "static")
            break
    mutation = request.method not in {"GET", "HEAD", "OPTIONS"}
    action = "local.write" if mutation else "local.read"
    runtime_routes = {
        "/api/projects/{project_id}/agents/{agent_id}/messages": "agent.message",
        "/api/projects/{project_id}/agents/start": "agent.start",
        "/api/projects/{project_id}/shell": "shell.create",
        "/api/projects/{project_id}/shell/{pane_id:path}/commands": "shell.execute",
    }
    local_mutations = {
        "/api/imports/local/preview", "/api/projects", "/api/projects/{project_id}/plan/confirm",
        "/api/projects/{project_id}/plan/refresh", "/api/projects/{project_id}/decisions",
        "/api/projects/{project_id}/decisions/{decision_id}/messages",
        "/api/projects/{project_id}/decisions/{decision_id}/answer",
        "/api/projects/{project_id}/monitors/reconcile", "/api/projects/{project_id}/monitors",
        "/api/projects/{project_id}/monitors/{monitor_id}/snapshot",
        "/api/projects/{project_id}/monitors/{monitor_id}/findings",
        "/api/projects/{project_id}/monitors/{monitor_id}/pause",
        "/api/notifications/{notification_id}", "/api/notifications/read-all", "/api/notification-preferences",
        "/api/projects/{project_id}/verification-policy/{node_id}", "/api/projects/{project_id}/verifications",
    }
    if mutation:
        action = runtime_routes.get(route_template, "local.write" if route_template in local_mutations else "unclassified")
    principal = None
    try:
        policy = load_security_policy()
        principal = authenticate_request(request.headers.get("authorization"), request.client.host if request.client else None, policy)
        authorize_action(principal, action, policy)
        if mutation:
            validate_request_origin(request.headers.get("origin"), request.headers.get("sec-fetch-site"),
                                    str(request.base_url).rstrip("/"), policy)
            await asyncio.to_thread(inbox.audit, principal.id, action, request.method, route_template, "accepted")
        request.state.principal = principal
        response = await call_next(request)
        if mutation:
            await asyncio.to_thread(inbox.audit, principal.id, action, request.method, route_template, f"http_{response.status_code}")
        response.headers["Cache-Control"] = "no-store"
        return response
    except SecurityError as error:
        await asyncio.to_thread(inbox.audit, principal.id if principal else None, action, request.method, route_template, error.code)
        return JSONResponse({"detail": error.detail, "code": error.code}, status_code=error.status_code,
                            headers={"WWW-Authenticate": 'Basic realm="Agent Control Center"'} if error.status_code == 401 else {})


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/capabilities")
def capabilities():
    policy = load_security_policy()
    return {"mode": "standalone", "allowed_actions": sorted(policy.allowed_actions), "fleet_available": False,
            "notification_delivery": "page_open", "push_available": False}


@app.get("/api/notifications", response_model=NotificationPage)
def notifications(request: Request, after: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), before: int | None = Query(None, ge=0), tail: bool = False):
    return inbox.page(request.state.principal.id, after, limit, before, tail=tail)


@app.get("/api/notifications/stream")
async def notifications_stream(request: Request, after: int = Query(0, ge=0)):
    try:
        cursor = int(request.headers.get("last-event-id", str(after)))
        if cursor < 0:
            raise ValueError
    except ValueError:
        raise HTTPException(400, "通知游標格式不正確。") from None
    async def events():
        nonlocal cursor
        while not await request.is_disconnected():
            try:
                principal = authenticate_request(request.headers.get("authorization"), request.client.host if request.client else None)
                authorize_action(principal, "local.read")
            except SecurityError:
                yield 'event: resync\ndata: {"reason":"authorization_changed"}\n\n'
                return
            page = await asyncio.to_thread(inbox.page, principal.id, cursor, 100, tail=True)
            if cursor > page.high_watermark:
                yield 'event: resync\ndata: {"reason":"cursor_reset"}\n\n'
                return
            for item in page.items:
                cursor = item.sequence
                yield f"id: {cursor}\nevent: notification\ndata: {item.model_dump_json()}\n\n"
            if not page.items:
                yield ": keepalive\n\n"
            await asyncio.sleep(0 if page.next_cursor is not None else 2)
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.patch("/api/notifications/{notification_id}", response_model=NotificationItem)
def read_notification(notification_id: str, body: ReadNotification, request: Request):
    try:
        return inbox.read(request.state.principal.id, notification_id, body.read)
    except KeyError as error:
        raise HTTPException(404, str(error).strip("'")) from error


@app.post("/api/notifications/read-all")
def read_all_notifications(body: ReadAllNotifications, request: Request):
    inbox.read_all(request.state.principal.id, body.through_sequence)
    return {"status": "ok"}


@app.get("/api/notification-preferences", response_model=NotificationPreferences)
def notification_preferences(request: Request):
    return inbox.preferences(request.state.principal.id)


@app.put("/api/notification-preferences", response_model=NotificationPreferences)
def update_notification_preferences(body: NotificationPreferences, request: Request):
    try:
        return inbox.save_preferences(request.state.principal.id, body)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.get("/api/notification-status")
def notification_status():
    with store._connect() as c:
        rows = c.execute("SELECT * FROM collector_health").fetchall()
    return {"background_enabled": os.getenv("CONTROL_CENTER_BACKGROUND_ENABLED", "1") != "0", "sources": [dict(row) for row in rows]}


@app.get("/api/projects/{project_id}/verification-state/{node_id}")
def verification_state(project_id: str, node_id: str):
    try:
        project, node = verification._project_node(project_id, node_id)
        revision, error = None, None
        try:
            revision = clean_revision(project.source_path or "")
        except ValueError as exc:
            error = str(exc)
        return {"revision": revision, "revision_error": error, "scope_hash": scope_hash(node),
                "policy": verification.policy(project_id, node_id), "acceptance_criteria": node.acceptance_criteria,
                "records": [r for r in verification.list(project_id) if r["node_id"] == node_id]}
    except KeyError as error:
        raise HTTPException(404, str(error).strip("'")) from error


@app.put("/api/projects/{project_id}/verification-policy/{node_id}")
def set_verification_policy(project_id: str, node_id: str, body: VerificationPolicyRequest):
    try:
        return verification.set_policy(project_id, node_id, body)
    except KeyError as error:
        raise HTTPException(404, str(error).strip("'")) from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@app.post("/api/projects/{project_id}/verifications", status_code=201)
def submit_verification(project_id: str, body: VerificationRequest, request: Request):
    try:
        return verification.submit(project_id, body, request.state.principal.id)
    except KeyError as error:
        raise HTTPException(404, str(error).strip("'")) from error
    except (ValueError, OSError) as error:
        raise HTTPException(409, str(error) if isinstance(error, ValueError) else "無法讀取驗收證據。") from error


@app.get("/api/portfolio", response_model=PortfolioResponse)
def portfolio() -> PortfolioResponse:
    return store.portfolio()


@app.post("/api/imports/local/preview", response_model=ImportPreview)
def preview_local_import(request: ImportPreviewRequest) -> ImportPreview:
    try:
        preview = scan_local_repository(request.path)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    store.remember_preview(preview)
    return preview


@app.post("/api/projects", response_model=ProjectDetail, status_code=201)
def confirm_import(request: ConfirmImportRequest) -> ProjectDetail:
    try:
        return store.confirm_import(request)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error).strip("'")) from error


@app.get("/api/projects/{project_id}", response_model=ProjectDetail)
def project_detail(project_id: str) -> ProjectDetail:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="找不到這個專案。")
    verified = {r["node_id"]: r for r in verification.list(project_id) if r["invalidated_at"] is None}
    for node in flatten(project.plan):
        if node.id in verified:
            node.state = PlanState.VERIFIED
            node.state_explanation = "擁有者已逐條核對驗收；目前版本與證據檔案相符。"
            node.acceptance_met = len(node.acceptance_criteria)
            node.evidence_count = len(verified[node.id]["evidence"])
    return project


@app.post("/api/projects/{project_id}/plan/confirm", response_model=ProjectDetail)
def confirm_project_plan(project_id: str) -> ProjectDetail:
    try:
        return store.confirm_plan(project_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error).strip("'")) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/projects/{project_id}/plan/refresh", response_model=ProjectDetail)
def refresh_project_plan(project_id: str) -> ProjectDetail:
    try:
        return store.refresh_plan(project_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error).strip("'")) from error
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/projects/{project_id}/decisions", response_model=list[DecisionCard])
def list_project_decisions(project_id: str) -> list[DecisionCard]:
    try:
        return store.list_decisions(project_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error).strip("'")) from error


@app.post("/api/projects/{project_id}/decisions", response_model=DecisionCard, status_code=201)
def create_project_decision(project_id: str, request: CreateDecisionRequest) -> DecisionCard:
    try:
        return store.create_decision(project_id, request)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error).strip("'")) from error


@app.post("/api/projects/{project_id}/decisions/{decision_id}/messages", response_model=DecisionCard)
def add_project_decision_message(
    project_id: str, decision_id: str, request: DecisionMessageRequest
) -> DecisionCard:
    try:
        return store.add_decision_message(project_id, decision_id, request)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error).strip("'")) from error


@app.post("/api/projects/{project_id}/decisions/{decision_id}/answer", response_model=DecisionCard)
def answer_project_decision(
    project_id: str, decision_id: str, request: DecisionAnswerRequest
) -> DecisionCard:
    try:
        return store.answer_decision(project_id, decision_id, request)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error).strip("'")) from error


@app.get("/api/projects/{project_id}/agents", response_model=AgentSessionsResponse)
def project_agents(project_id: str) -> AgentSessionsResponse:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="找不到這個專案。")
    if not project.source_path:
        return AgentSessionsResponse(
            connected=False, source="none", limitation="專案沒有本機路徑，無法比對 Herdr Agent。", agents=[]
        )
    try:
        sessions = list_project_agents(project.source_path)
        message_allowed = "agent.message" in load_security_policy().allowed_actions
        for agent in sessions.agents:
            agent.can_send_message = agent.can_send_message and message_allowed
            request_identity = f"{agent.provider.casefold()}:{agent.runtime_session_id}" if agent.runtime_session_id else None
            if agent.latest_human_request:
                if request_identity:
                    store.remember_agent_request(
                        project_id, request_identity, agent.latest_human_request, agent.request_source
                    )
                continue
            remembered = store.latest_agent_request(project_id, request_identity) if request_identity else None
            if remembered:
                body, source = remembered
                agent.latest_human_request = body
                agent.task_summary = _request_preview(body)
                agent.request_source = source
                agent.request_explanation = (
                    "這是 Control Center 先前看見或送出的最後一個人類指派；目前終端畫面已看不到原文。"
                )
        return sessions
    except HerdrUnavailable as error:
        return AgentSessionsResponse(connected=False, source="Herdr", limitation=str(error), agents=[])


@app.get("/api/projects/{project_id}/agents/{agent_id}/transcript", response_model=AgentTranscript)
def project_agent_transcript(project_id: str, agent_id: str) -> AgentTranscript:
    sessions = project_agents(project_id)
    if agent_id not in {agent.id for agent in sessions.agents}:
        raise HTTPException(status_code=404, detail="這個 Agent 不屬於目前專案或已經離線。")
    try:
        return read_agent_output(agent_id)
    except (HerdrUnavailable, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/projects/{project_id}/agents/{agent_id}/transcript/stream")
async def project_agent_transcript_stream(
    project_id: str, agent_id: str, request: Request
) -> StreamingResponse:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="找不到這個專案。")
    if not project.source_path:
        raise HTTPException(status_code=409, detail="專案沒有本機路徑，無法串流 Herdr Agent。")
    try:
        belongs = await asyncio.to_thread(agent_belongs_to_project, agent_id, project.source_path)
    except HerdrUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if not belongs:
        raise HTTPException(status_code=404, detail="這個 Agent 不屬於目前專案或已經離線。")

    async def events():
        last_content: str | None = None
        idle_ticks = 0
        while not await request.is_disconnected():
            try:
                principal = authenticate_request(request.headers.get("authorization"), request.client.host if request.client else None)
                authorize_action(principal, "local.read")
                still_belongs = await asyncio.to_thread(
                    agent_belongs_to_project, agent_id, project.source_path
                )
                if not still_belongs:
                    payload = {"message": "Agent 已離線或不再屬於目前專案。"}
                    yield f"event: agent_error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    return
                transcript = await asyncio.to_thread(read_agent_output, agent_id, 180)
            except (HerdrUnavailable, ValueError, SecurityError) as error:
                payload = {"message": str(error)}
                yield f"event: agent_error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                return

            if transcript.content != last_content:
                payload = transcript.model_dump(mode="json")
                yield f"event: transcript\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last_content = transcript.content
                idle_ticks = 0
            else:
                idle_ticks += 1
                if idle_ticks >= 10:
                    yield ": heartbeat\n\n"
                    idle_ticks = 0
            await asyncio.sleep(1.5)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/projects/{project_id}/agents/{agent_id}/messages", status_code=202)
def project_agent_message(project_id: str, agent_id: str, request: AgentMessageRequest) -> dict[str, str]:
    sessions = project_agents(project_id)
    if agent_id not in {agent.id for agent in sessions.agents}:
        raise HTTPException(status_code=404, detail="這個 Agent 不屬於目前專案或已經離線。")
    try:
        send_agent_message(agent_id, request.body)
    except (HerdrUnavailable, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    target = next(agent for agent in sessions.agents if agent.id == agent_id)
    if target.runtime_session_id:
        store.remember_agent_request(project_id, f"{target.provider.casefold()}:{target.runtime_session_id}", request.body, "control_center_sent")
    return {"status": "sent", "agent_id": agent_id}


@app.post("/api/projects/{project_id}/agents/start", response_model=StartAgentResponse, status_code=201)
def project_agent_start(project_id: str, request: StartAgentRequest) -> StartAgentResponse:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="找不到這個專案。")
    if not project.source_path:
        raise HTTPException(status_code=409, detail="這個專案沒有本機來源路徑，不能啟動 Herdr agent。")
    try:
        result = start_project_agent(project.source_path, request.kind, request.model, request.initial_prompt)
    except (HerdrUnavailable, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    # A new pane is not yet a verified runtime session; do not attach durable
    # request history until Herdr reports the session identity.
    return StartAgentResponse(**result)


@app.post("/api/projects/{project_id}/shell", response_model=ShellPaneResponse, status_code=201)
def project_shell_create(project_id: str) -> ShellPaneResponse:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="找不到這個專案。")
    if not project.source_path:
        raise HTTPException(status_code=409, detail="這個專案沒有本機來源路徑，不能建立 shell pane。")
    try:
        return create_project_shell(project.source_path)
    except HerdrUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/projects/{project_id}/shell/{pane_id:path}/transcript", response_model=AgentTranscript)
def project_shell_transcript(project_id: str, pane_id: str) -> AgentTranscript:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="找不到這個專案。")
    if not project.source_path:
        raise HTTPException(status_code=409, detail="這個專案沒有本機來源路徑。")
    try:
        if not pane_belongs_to_project(pane_id, project.source_path):
            raise HTTPException(status_code=404, detail="這個 shell pane 不屬於目前專案。")
        return read_pane_output(pane_id)
    except (HerdrUnavailable, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/projects/{project_id}/shell/{pane_id:path}/commands", response_model=ShellCommandResponse, status_code=202)
def project_shell_command(project_id: str, pane_id: str, request: ShellCommandRequest) -> ShellCommandResponse:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="找不到這個專案。")
    if not project.source_path:
        raise HTTPException(status_code=409, detail="這個專案沒有本機來源路徑。")
    try:
        if not pane_belongs_to_project(pane_id, project.source_path):
            raise HTTPException(status_code=404, detail="這個 shell pane 不屬於目前專案。")
        blocked = run_shell_command(pane_id, request.command, request.confirm_dangerous)
    except (HerdrUnavailable, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if blocked:
        return ShellCommandResponse(
            pane_id=pane_id, command=request.command, status="blocked", blocked_reason=blocked,
        )
    return ShellCommandResponse(pane_id=pane_id, command=request.command, status="sent")


@app.get("/api/projects/{project_id}/goal-sessions", response_model=GoalSessionCandidatesResponse)
def project_goal_sessions(project_id: str) -> GoalSessionCandidatesResponse:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="找不到這個專案。")
    if not project.source_path:
        return GoalSessionCandidatesResponse(
            source="none", limitation="專案沒有本機路徑，無法比對 Codex goal。", sessions=[]
        )
    try:
        codex_sessions = discover_goal_sessions(project.source_path)
        claude_sessions, _ = discover_claude_activity(project.source_path)
        sessions = sorted(
            [*codex_sessions, *claude_sessions], key=lambda item: item.updated_at, reverse=True
        )
    except GoalMonitorUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return GoalSessionCandidatesResponse(
        source="Codex + Claude local structured session metadata",
        limitation="列出本專案可驗證的 `/goal`；尚未取得 runtime session identity 的項目會保持未配對，不會用 cwd 或時間猜測。",
        sessions=sessions,
    )


@app.get("/api/projects/{project_id}/agent-delegations", response_model=AgentDelegationsResponse)
def project_agent_delegations(project_id: str) -> AgentDelegationsResponse:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="找不到這個專案。")
    if not project.source_path:
        return AgentDelegationsResponse(
            source="none", limitation="專案沒有本機路徑，無法核對代理派工。", delegations=[]
        )
    _, delegations = discover_claude_activity(project.source_path)
    return AgentDelegationsResponse(
        source="Claude structured tool events",
        limitation="直接 shell 派工可以辨識啟動模型與 TaskStop；沒有 child session identity 時不會假裝已掛載 `/goal`。",
        delegations=delegations,
    )


@app.get("/api/projects/{project_id}/monitors", response_model=list[GoalMonitor])
def project_monitors(project_id: str) -> list[GoalMonitor]:
    try:
        return store.list_monitors(project_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error).strip("'")) from error


@app.post("/api/projects/{project_id}/monitors/reconcile", response_model=MonitorReconcileResult)
def reconcile_project_monitors(project_id: str) -> MonitorReconcileResult:
    try:
        return reconcile_project(store, project_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error).strip("'")) from error
    except (GoalMonitorUnavailable, HerdrUnavailable, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/projects/{project_id}/monitors", response_model=GoalMonitor, status_code=201)
def create_project_monitor(project_id: str, request: CreateMonitorRequest) -> GoalMonitor:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="找不到這個專案。")
    if not project.source_path:
        raise HTTPException(status_code=409, detail="專案沒有本機路徑，不能啟用 Herdr 監工。")
    try:
        sessions = list_project_agents(project.source_path)
        target = next((item for item in sessions.agents if item.id == request.agent_id), None)
        if target is None or target.provider.casefold() != "codex":
            raise GoalMonitorUnavailable("指定的 Herdr pane 不屬於目前專案、已離線或不是 Codex。")
        goal = resolve_goal_session(project.source_path, request.goal_session_id)
        if target.runtime_session_id != goal.session_id:
            raise GoalMonitorUnavailable("Herdr 尚未回報相符的 runtime session identity，請等待可靠配對。")
        return store.create_monitor(project_id, request, goal, current_git_head(project.source_path))
    except (GoalMonitorUnavailable, HerdrUnavailable, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/projects/{project_id}/monitors/{monitor_id}/snapshot", response_model=MonitorSnapshot)
def snapshot_project_monitor(project_id: str, monitor_id: str) -> MonitorSnapshot:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="找不到這個專案。")
    if not project.source_path:
        raise HTTPException(status_code=409, detail="專案沒有本機路徑。")
    try:
        monitor = store.get_monitor(project_id, monitor_id)
        return collect_snapshot(
            project_id, project.source_path, monitor.id, monitor.agent_id, monitor.goal_session_id,
            goal_epoch_id=monitor.goal_epoch_id, provider=monitor.provider,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error).strip("'")) from error
    except (GoalMonitorUnavailable, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/projects/{project_id}/monitors/{monitor_id}/findings", response_model=MonitorEvent)
def report_project_monitor_finding(
    project_id: str, monitor_id: str, request: MonitorFindingRequest
) -> MonitorEvent:
    try:
        return store.record_monitor_finding(project_id, monitor_id, request)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error).strip("'")) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/projects/{project_id}/monitors/{monitor_id}/pause", response_model=GoalMonitor)
def pause_project_monitor(project_id: str, monitor_id: str) -> GoalMonitor:
    try:
        return store.pause_monitor(project_id, monitor_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error).strip("'")) from error


WEB_DIST = ROOT / "apps" / "web" / "dist"
if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="control-center-web")

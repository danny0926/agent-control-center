from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import (
    CreateDecisionRequest,
    DecisionAnswerRequest,
    DecisionCard,
    DecisionMessage,
    DecisionMessageRequest,
    DecisionStatus,
    ConfirmImportRequest,
    ImportPreview,
    CreateMonitorRequest,
    GoalMonitor,
    GoalSessionCandidate,
    MonitorEvent,
    MonitorFindingRequest,
    MonitorStatus,
    MonitorVerdict,
    PlanNode,
    PlanState,
    PlanStatus,
    PortfolioResponse,
    ProjectDetail,
    ProjectSummary,
    SourceKind,
)


class _ClosingConnection(sqlite3.Connection):
    """Each unit of work commits/rolls back, then releases its database handle."""

    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._previews: dict[str, ImportPreview] = {}
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, factory=_ClosingConnection)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            from .notifications import initialize_notifications
            from .verification import initialize_verification
            initialize_notifications(connection)
            initialize_verification(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    parent_project_id TEXT,
                    name TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_path TEXT,
                    confidence TEXT NOT NULL,
                    plan_status TEXT NOT NULL DEFAULT 'draft',
                    facts_json TEXT,
                    documents_json TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(projects)")}
            if "plan_status" not in columns:
                connection.execute("ALTER TABLE projects ADD COLUMN plan_status TEXT NOT NULL DEFAULT 'draft'")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    context TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    impact TEXT NOT NULL,
                    status TEXT NOT NULL,
                    answer TEXT,
                    messages_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_requests (
                    project_id TEXT NOT NULL,
                    pane_id TEXT NOT NULL,
                    body TEXT NOT NULL,
                    source TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    PRIMARY KEY (project_id, pane_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS goal_monitors (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    goal_session_id TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    cadence_minutes INTEGER NOT NULL,
                    notify_only INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    start_head TEXT,
                    last_checked_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, agent_id, goal_session_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS monitor_events (
                    id TEXT PRIMARY KEY,
                    monitor_id TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    finding_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    decision_id TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            # Add a versioned table: the legacy UNIQUE(session) constraint
            # cannot represent multiple goal epochs. Preserve the old table
            # and all event IDs; never upgrade an inferred identity to verified.
            connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY)")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS goal_monitors_v2 (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, agent_id TEXT NOT NULL,
                    goal_session_id TEXT NOT NULL, objective TEXT NOT NULL,
                    cadence_minutes INTEGER NOT NULL, notify_only INTEGER NOT NULL,
                    status TEXT NOT NULL, start_head TEXT, last_checked_at TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    provider TEXT NOT NULL DEFAULT 'unknown', goal_epoch_id TEXT,
                    identity_verified INTEGER NOT NULL DEFAULT 0,
                    identity_evidence_json TEXT NOT NULL DEFAULT '[]',
                    UNIQUE(project_id, agent_id, provider, goal_session_id, goal_epoch_id)
                )
            """)
            migrated = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 'monitor_epochs_v2'"
            ).fetchone()
            if not migrated:
                connection.execute("""
                    INSERT INTO goal_monitors_v2 (
                        id, project_id, agent_id, goal_session_id, objective, cadence_minutes,
                        notify_only, status, start_head, last_checked_at, created_at, updated_at
                    ) SELECT id, project_id, agent_id, goal_session_id, objective, cadence_minutes,
                        notify_only, CASE WHEN status = 'armed' THEN 'paused' ELSE status END,
                        start_head, last_checked_at, created_at, updated_at FROM goal_monitors
                """)
                connection.execute("INSERT INTO schema_migrations VALUES ('monitor_epochs_v2')")

    def remember_agent_request(self, project_id: str, pane_id: str, body: str, source: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_requests (project_id, pane_id, body, source, observed_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id, pane_id) DO UPDATE SET
                    body = excluded.body,
                    source = excluded.source,
                    observed_at = excluded.observed_at
                """,
                (project_id, pane_id, body, source, now),
            )

    def latest_agent_request(self, project_id: str, pane_id: str) -> tuple[str, str] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT body, source FROM agent_requests WHERE project_id = ? AND pane_id = ?",
                (project_id, pane_id),
            ).fetchone()
        return (row["body"], row["source"]) if row else None

    def remember_preview(self, preview: ImportPreview) -> None:
        self._previews[preview.preview_id] = preview

    def preview(self, preview_id: str) -> ImportPreview | None:
        return self._previews.get(preview_id)

    def _starter_plan(self, project_id: str, preview: ImportPreview, purpose: str) -> list[PlanNode]:
        if preview.proposed_plan:
            plan = [PlanNode.model_validate(item.model_dump()) for item in preview.proposed_plan]
            plan[0].title = purpose
            return plan
        return [
            PlanNode(
                id="product-goal",
                kind="goal",
                title=purpose,
                description="已確認產品基本說明，但目前沒有找到可解析的 Roadmap。",
                technical_label="product-goal",
                state=PlanState.UNKNOWN,
                state_explanation="產品基本理解已確認；需要補上 Roadmap，才能建立成果樹。",
                acceptance_met=0,
                acceptance_total=0,
                evidence_count=0,
                source_paths=preview.understanding.evidence_paths,
            )
        ]

    def confirm_import(self, request: ConfirmImportRequest) -> ProjectDetail:
        preview = self._previews.get(request.preview_id)
        if preview is None:
            raise KeyError("匯入預覽不存在或已過期，請重新掃描。")
        if request.parent_project_id and not self.get_project(request.parent_project_id):
            raise KeyError("指定的父專案不存在。")

        project_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        plan = self._starter_plan(project_id, preview, request.purpose)
        plan_status = PlanStatus.DRAFT if preview.proposed_plan else PlanStatus.NEEDS_SOURCE
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO projects (
                    id, workspace_id, parent_project_id, name, purpose, source_kind,
                    source_path, confidence, plan_status, facts_json, documents_json, plan_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    "local",
                    request.parent_project_id,
                    request.display_name,
                    request.purpose,
                    SourceKind.LOCAL_REPOSITORY.value,
                    preview.facts.root_path,
                    preview.understanding.confidence.value,
                    plan_status.value,
                    preview.facts.model_dump_json(),
                    json.dumps([item.model_dump(mode="json") for item in preview.documents], ensure_ascii=False),
                    json.dumps([item.model_dump(mode="json") for item in plan], ensure_ascii=False),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        self._previews.pop(request.preview_id, None)
        project = self.get_project(project_id)
        assert project is not None
        return project

    def _row_to_summary(self, row: sqlite3.Row) -> ProjectSummary:
        plan = [PlanNode.model_validate(item) for item in json.loads(row["plan_json"])]
        health = plan[0].state if plan else PlanState.UNKNOWN
        explanation = plan[0].state_explanation if plan else "尚未建立產品成果樹。"
        with self._connect() as connection:
            decision_count = connection.execute(
                "SELECT COUNT(*) FROM decisions WHERE project_id = ? AND status IN (?, ?)",
                (row["id"], DecisionStatus.WAITING_HUMAN.value, DecisionStatus.WAITING_AGENT.value),
            ).fetchone()[0]
        return ProjectSummary(
            id=row["id"],
            workspace_id=row["workspace_id"],
            parent_project_id=row["parent_project_id"],
            name=row["name"],
            purpose=row["purpose"],
            source_kind=row["source_kind"],
            source_path=row["source_path"],
            confidence=row["confidence"],
            plan_status=row["plan_status"],
            health=health,
            health_explanation=explanation,
            decision_count=decision_count,
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def portfolio(self) -> PortfolioResponse:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return PortfolioResponse(
            workspace_id="local",
            workspace_name="我的工作區",
            projects=[self._row_to_summary(row) for row in rows],
        )

    def get_project(self, project_id: str) -> ProjectDetail | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            return None
        summary = self._row_to_summary(row)
        return ProjectDetail(
            **summary.model_dump(),
            facts=json.loads(row["facts_json"]) if row["facts_json"] else None,
            documents=json.loads(row["documents_json"]),
            plan=json.loads(row["plan_json"]),
        )

    def confirm_plan(self, project_id: str) -> ProjectDetail:
        project = self.get_project(project_id)
        if project is None:
            raise KeyError("找不到這個專案。")
        if not project.plan or not project.plan[0].children:
            raise ValueError("目前沒有可確認的成果樹；請先補上或重新讀取 Roadmap。")
        project.plan[0].state = PlanState.IN_PROGRESS
        project.plan[0].state_explanation = "產品計畫已由人確認；各項成果仍必須個別連結驗收條件與證據。"
        now = datetime.now(timezone.utc)
        with self._connect() as connection:
            connection.execute(
                "UPDATE projects SET plan_status = ?, plan_json = ?, updated_at = ? WHERE id = ?",
                (
                    PlanStatus.CONFIRMED.value,
                    json.dumps([item.model_dump(mode="json") for item in project.plan], ensure_ascii=False),
                    now.isoformat(),
                    project_id,
                ),
            )
        confirmed = self.get_project(project_id)
        assert confirmed is not None
        return confirmed

    def refresh_plan(self, project_id: str) -> ProjectDetail:
        project = self.get_project(project_id)
        if project is None:
            raise KeyError("找不到這個專案。")
        if not project.source_path:
            raise ValueError("這個專案沒有可重新讀取的本機來源。")
        from .importer import scan_local_repository

        preview = scan_local_repository(project.source_path)
        plan = self._starter_plan(project_id, preview, project.purpose)
        def structure(nodes: list[PlanNode]) -> list[dict]:
            return [
                {
                    "kind": node.kind,
                    "title": node.title,
                    "children": structure(node.children),
                }
                for node in nodes
            ]

        unchanged = structure(project.plan) == structure(plan)
        if preview.proposed_plan and project.plan_status == PlanStatus.CONFIRMED and unchanged:
            status = PlanStatus.CONFIRMED
            plan[0].state = PlanState.IN_PROGRESS
            plan[0].state_explanation = "產品計畫已由人確認；重新讀取未發現結構變更。各項成果仍需個別驗證。"
        else:
            status = PlanStatus.DRAFT if preview.proposed_plan else PlanStatus.NEEDS_SOURCE
        now = datetime.now(timezone.utc)
        with self._connect() as connection:
            connection.execute(
                "UPDATE projects SET plan_status = ?, plan_json = ?, documents_json = ?, updated_at = ? WHERE id = ?",
                (
                    status.value,
                    json.dumps([item.model_dump(mode="json") for item in plan], ensure_ascii=False),
                    json.dumps([item.model_dump(mode="json") for item in preview.documents], ensure_ascii=False),
                    now.isoformat(),
                    project_id,
                ),
            )
        refreshed = self.get_project(project_id)
        assert refreshed is not None
        return refreshed

    def list_decisions(self, project_id: str) -> list[DecisionCard]:
        if self.get_project(project_id) is None:
            raise KeyError("找不到這個專案。")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM decisions WHERE project_id = ? ORDER BY updated_at DESC", (project_id,)
            ).fetchall()
        return [self._decision_from_row(row) for row in rows]

    def _decision_from_row(self, row: sqlite3.Row) -> DecisionCard:
        return DecisionCard(
            id=row["id"],
            project_id=row["project_id"],
            question=row["question"],
            context=row["context"],
            recommendation=row["recommendation"],
            impact=row["impact"],
            status=row["status"],
            answer=row["answer"],
            messages=json.loads(row["messages_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def create_decision(self, project_id: str, request: CreateDecisionRequest) -> DecisionCard:
        if self.get_project(project_id) is None:
            raise KeyError("找不到這個專案。")
        now = datetime.now(timezone.utc)
        decision_id = f"DEC-{uuid.uuid4().hex[:8].upper()}"
        message = DecisionMessage(id=str(uuid.uuid4()), role="human", body=request.question, created_at=now)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    decision_id, project_id, request.question, request.context, "", "medium",
                    DecisionStatus.WAITING_AGENT.value, None,
                    json.dumps([message.model_dump(mode="json")], ensure_ascii=False), now.isoformat(), now.isoformat(),
                ),
            )
        return self.get_decision(project_id, decision_id)

    def get_decision(self, project_id: str, decision_id: str) -> DecisionCard:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM decisions WHERE project_id = ? AND id = ?", (project_id, decision_id)
            ).fetchone()
        if row is None:
            raise KeyError("找不到這個決策問題。")
        return self._decision_from_row(row)

    def add_decision_message(
        self, project_id: str, decision_id: str, request: DecisionMessageRequest
    ) -> DecisionCard:
        decision = self.get_decision(project_id, decision_id)
        now = datetime.now(timezone.utc)
        decision.messages.append(
            DecisionMessage(id=str(uuid.uuid4()), role="human", body=request.body, created_at=now)
        )
        with self._connect() as connection:
            connection.execute(
                "UPDATE decisions SET status = ?, messages_json = ?, updated_at = ? WHERE id = ?",
                (
                    DecisionStatus.WAITING_AGENT.value,
                    json.dumps([item.model_dump(mode="json") for item in decision.messages], ensure_ascii=False),
                    now.isoformat(), decision_id,
                ),
            )
        return self.get_decision(project_id, decision_id)

    def answer_decision(
        self, project_id: str, decision_id: str, request: DecisionAnswerRequest
    ) -> DecisionCard:
        decision = self.get_decision(project_id, decision_id)
        now = datetime.now(timezone.utc)
        decision.messages.append(
            DecisionMessage(id=str(uuid.uuid4()), role="human", body=request.answer, created_at=now)
        )
        with self._connect() as connection:
            connection.execute(
                "UPDATE decisions SET status = ?, answer = ?, messages_json = ?, updated_at = ? WHERE id = ?",
                (
                    DecisionStatus.ANSWERED.value, request.answer,
                    json.dumps([item.model_dump(mode="json") for item in decision.messages], ensure_ascii=False),
                    now.isoformat(), decision_id,
                ),
            )
        return self.get_decision(project_id, decision_id)

    def _monitor_event_from_row(self, row: sqlite3.Row) -> MonitorEvent:
        return MonitorEvent(
            id=row["id"],
            monitor_id=row["monitor_id"],
            verdict=row["verdict"],
            finding_type=row["finding_type"],
            summary=row["summary"],
            evidence=json.loads(row["evidence_json"]),
            recommendation=row["recommendation"],
            confidence=row["confidence"],
            decision_id=row["decision_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _monitor_from_row(self, row: sqlite3.Row) -> GoalMonitor:
        with self._connect() as connection:
            event_rows = connection.execute(
                "SELECT * FROM monitor_events WHERE monitor_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 30",
                (row["id"],),
            ).fetchall()
        return GoalMonitor(
            id=row["id"],
            project_id=row["project_id"],
            agent_id=row["agent_id"],
            goal_session_id=row["goal_session_id"],
            provider=row["provider"],
            goal_epoch_id=row["goal_epoch_id"],
            identity_verified=bool(row["identity_verified"]),
            identity_evidence=json.loads(row["identity_evidence_json"]),
            objective=row["objective"],
            cadence_minutes=row["cadence_minutes"],
            notify_only=bool(row["notify_only"]),
            status=row["status"],
            start_head=row["start_head"],
            last_checked_at=datetime.fromisoformat(row["last_checked_at"]) if row["last_checked_at"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            events=[self._monitor_event_from_row(item) for item in event_rows],
        )

    def list_monitors(self, project_id: str) -> list[GoalMonitor]:
        if self.get_project(project_id) is None:
            raise KeyError("找不到這個專案。")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM goal_monitors_v2 WHERE project_id = ? ORDER BY updated_at DESC", (project_id,)
            ).fetchall()
        return [self._monitor_from_row(row) for row in rows]

    def get_monitor(self, project_id: str, monitor_id: str) -> GoalMonitor:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM goal_monitors_v2 WHERE project_id = ? AND id = ?", (project_id, monitor_id)
            ).fetchone()
        if row is None:
            raise KeyError("找不到這個監工。")
        return self._monitor_from_row(row)

    def create_monitor(
        self,
        project_id: str,
        request: CreateMonitorRequest,
        goal: GoalSessionCandidate,
        start_head: str | None,
    ) -> GoalMonitor:
        if self.get_project(project_id) is None:
            raise KeyError("找不到這個專案。")
        if not request.notify_only:
            raise ValueError("Pilot 階段只允許 notify-only，不能自動向 Codex 傳訊。")
        if (
            request.goal_session_id != goal.session_id or request.provider != goal.provider
            or goal.provider != "codex" or not goal.goal_id or not goal.epoch_verified
            or not goal.identity_evidence
            or (request.goal_epoch_id is not None and request.goal_epoch_id != goal.goal_id)
        ):
            raise ValueError("Goal provider/session/epoch 缺少可靠身分證據或不一致，不能啟動監工。")
        now = datetime.now(timezone.utc)
        monitor_id = f"MON-{uuid.uuid4().hex[:8].upper()}"
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO goal_monitors_v2 (
                        id, project_id, agent_id, goal_session_id, objective, cadence_minutes,
                        notify_only, status, start_head, last_checked_at, created_at, updated_at,
                        provider, goal_epoch_id, identity_verified, identity_evidence_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        monitor_id, project_id, request.agent_id, request.goal_session_id, goal.objective,
                        request.cadence_minutes, 1, MonitorStatus.ARMED.value, start_head, None,
                        now.isoformat(), now.isoformat(),
                        goal.provider, goal.goal_id, 1, json.dumps(goal.identity_evidence, ensure_ascii=False),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError("這個 Codex goal 與 Herdr pane 已經有監工。") from error
        return self.get_monitor(project_id, monitor_id)

    def pause_monitor(self, project_id: str, monitor_id: str) -> GoalMonitor:
        self.get_monitor(project_id, monitor_id)
        now = datetime.now(timezone.utc)
        with self._connect() as connection:
            connection.execute(
                "UPDATE goal_monitors_v2 SET status = ?, updated_at = ? WHERE id = ?",
                (MonitorStatus.PAUSED.value, now.isoformat(), monitor_id),
            )
        return self.get_monitor(project_id, monitor_id)

    def rearm_monitor(
        self, project_id: str, monitor_id: str, objective: str,
        *, goal: GoalSessionCandidate | None = None,
    ) -> GoalMonitor:
        monitor = self.get_monitor(project_id, monitor_id)
        if (
            goal is None or not goal.epoch_verified or not goal.identity_evidence
            or not monitor.identity_verified or not monitor.goal_epoch_id
            or (monitor.provider, monitor.goal_session_id, monitor.goal_epoch_id)
            != (goal.provider, goal.session_id, goal.goal_id)
            or goal.status.casefold() != "active"
        ):
            raise ValueError("不能跨 provider/session/epoch 或以未知身分恢復監工。")
        if monitor.status == MonitorStatus.PAUSED:
            return monitor
        if monitor.status == MonitorStatus.ARMED:
            return monitor
        now = datetime.now(timezone.utc)
        event_id = f"EVT-{uuid.uuid4().hex[:10].upper()}"
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE goal_monitors_v2
                SET status = ?, objective = ?, updated_at = ?
                WHERE id = ? AND project_id = ?
                """,
                (MonitorStatus.ARMED.value, objective, now.isoformat(), monitor_id, project_id),
            )
            connection.execute(
                """
                INSERT INTO monitor_events (
                    id, monitor_id, verdict, finding_type, summary, evidence_json,
                    recommendation, confidence, decision_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id, monitor_id, MonitorVerdict.ATTENTION.value, "goal_resumed",
                    "同一個 Codex goal 在監工結束後又出現較新的 active 更新，已自動恢復監工。",
                    json.dumps([*goal.identity_evidence, "同一 provider/session/epoch 的 active 更新"], ensure_ascii=False),
                    "繼續巡查；Agent 再次宣稱完成時仍需重新驗證。", "high", None, now.isoformat(),
                ),
            )
        return self.get_monitor(project_id, monitor_id)

    def _create_monitor_decision(
        self, project_id: str, monitor_id: str, request: MonitorFindingRequest, now: datetime,
        connection: sqlite3.Connection,
    ) -> str:
        decision_id = f"DEC-{uuid.uuid4().hex[:8].upper()}"
        context_parts = [f"由 Monitor {monitor_id} 提出。", *request.evidence]
        message = DecisionMessage(
            id=str(uuid.uuid4()), role="agent",
            body=f"{request.summary}\n\n建議：{request.recommendation or '請人檢視證據後決定下一步。'}",
            created_at=now,
        )
        connection.execute(
            "INSERT INTO decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                decision_id, project_id, request.summary, "\n".join(context_parts),
                request.recommendation, "high", DecisionStatus.WAITING_HUMAN.value, None,
                json.dumps([message.model_dump(mode="json")], ensure_ascii=False),
                now.isoformat(), now.isoformat(),
            ),
        )
        from .notifications import emit_event
        emit_event(connection, source_key=f"decision:{decision_id}:waiting_human", event_type="decision.waiting_human",
                   project_id=project_id, entity_id=decision_id)
        return decision_id

    def record_monitor_finding(
        self, project_id: str, monitor_id: str, request: MonitorFindingRequest
    ) -> MonitorEvent:
        monitor = self.get_monitor(project_id, monitor_id)
        if monitor.status != MonitorStatus.ARMED:
            raise ValueError("監工目前沒有啟用，不能接受新的巡查結果。")
        now = datetime.now(timezone.utc)
        decision_id: str | None = None
        event_id = f"EVT-{uuid.uuid4().hex[:10].upper()}"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT status FROM goal_monitors_v2 WHERE id=? AND project_id=?",
                                         (monitor_id, project_id)).fetchone()
            if not current or current[0] != MonitorStatus.ARMED.value:
                raise ValueError("監工目前沒有啟用，不能接受新的巡查結果。")
            if request.verdict == MonitorVerdict.NEEDS_HUMAN:
                duplicate = connection.execute(
                    """
                    SELECT decision_id FROM monitor_events
                    WHERE monitor_id = ? AND verdict = ? AND finding_type = ? AND summary = ?
                      AND decision_id IS NOT NULL
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (monitor_id, request.verdict.value, request.finding_type, request.summary),
                ).fetchone()
                if duplicate:
                    decision_id = duplicate["decision_id"]
                else:
                    decision_id = self._create_monitor_decision(project_id, monitor_id, request, now, connection)
            connection.execute(
                """
                INSERT INTO monitor_events (
                    id, monitor_id, verdict, finding_type, summary, evidence_json,
                    recommendation, confidence, decision_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id, monitor_id, request.verdict.value, request.finding_type, request.summary,
                    json.dumps(request.evidence, ensure_ascii=False), request.recommendation,
                    request.confidence.value, decision_id, now.isoformat(),
                ),
            )
            next_status = (
                MonitorStatus.COMPLETE.value
                if request.verdict == MonitorVerdict.TERMINAL
                else MonitorStatus.ERROR.value if request.verdict == MonitorVerdict.ERROR else MonitorStatus.ARMED.value
            )
            connection.execute(
                "UPDATE goal_monitors_v2 SET status = ?, last_checked_at = ?, updated_at = ? WHERE id = ?",
                (next_status, now.isoformat(), now.isoformat(), monitor_id),
            )
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM monitor_events WHERE id = ?", (event_id,)).fetchone()
        assert row is not None
        return self._monitor_event_from_row(row)

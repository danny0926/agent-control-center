from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class SourceKind(StrEnum):
    LOCAL_REPOSITORY = "local_repository"
    GITHUB = "github"
    EMPTY = "empty"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class PlanState(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    IMPLEMENTED = "implemented"
    PARTIAL = "partial"
    AT_RISK = "at_risk"
    BLOCKED = "blocked"
    VERIFIED = "verified"
    UNKNOWN = "unknown"


class PlanStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    NEEDS_SOURCE = "needs_source"


class DecisionStatus(StrEnum):
    WAITING_HUMAN = "waiting_human"
    WAITING_AGENT = "waiting_agent"
    ANSWERED = "answered"
    RESOLVED = "resolved"


class MonitorStatus(StrEnum):
    ARMED = "armed"
    PAUSED = "paused"
    COMPLETE = "complete"
    ERROR = "error"


class MonitorVerdict(StrEnum):
    CLEAN = "clean"
    ATTENTION = "attention"
    NEEDS_HUMAN = "needs_human"
    TERMINAL = "terminal"
    ERROR = "error"


class DiscoveredDocument(BaseModel):
    kind: str
    path: str
    title: str
    explanation: str


class RepositoryFacts(BaseModel):
    root_path: str
    repository_name: str
    current_branch: str | None = None
    remote_url: str | None = None
    languages: list[str] = Field(default_factory=list)
    test_commands: list[str] = Field(default_factory=list)


class ProductUnderstanding(BaseModel):
    name: str
    plain_language_purpose: str
    confidence: Confidence
    evidence_paths: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class PlanNode(BaseModel):
    id: str
    kind: str
    title: str
    description: str
    technical_label: str | None = None
    state: PlanState = PlanState.UNKNOWN
    state_explanation: str
    acceptance_met: int = 0
    acceptance_total: int = 0
    evidence_count: int = 0
    documented_done: list[str] = Field(default_factory=list)
    documented_remaining: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    source_paths: list[str] = Field(default_factory=list)
    children: list["PlanNode"] = Field(default_factory=list)


class ImportPreviewRequest(BaseModel):
    path: str


class ImportPreview(BaseModel):
    preview_id: str
    source_kind: SourceKind = SourceKind.LOCAL_REPOSITORY
    facts: RepositoryFacts
    understanding: ProductUnderstanding
    documents: list[DiscoveredDocument]
    proposed_plan: list[PlanNode] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    scanned_at: datetime


class ConfirmImportRequest(BaseModel):
    preview_id: str
    display_name: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=500)
    parent_project_id: str | None = None


class ProjectSummary(BaseModel):
    id: str
    workspace_id: str
    parent_project_id: str | None = None
    name: str
    purpose: str
    source_kind: SourceKind
    source_path: str | None = None
    confidence: Confidence
    plan_status: PlanStatus = PlanStatus.DRAFT
    health: PlanState
    health_explanation: str
    decision_count: int = 0
    updated_at: datetime


class ProjectDetail(ProjectSummary):
    facts: RepositoryFacts | None = None
    documents: list[DiscoveredDocument] = Field(default_factory=list)
    plan: list[PlanNode] = Field(default_factory=list)


class PortfolioResponse(BaseModel):
    workspace_id: str
    workspace_name: str
    projects: list[ProjectSummary]


class DecisionMessage(BaseModel):
    id: str
    role: str
    body: str
    created_at: datetime


class DecisionCard(BaseModel):
    id: str
    project_id: str
    question: str
    context: str = ""
    recommendation: str = ""
    impact: str = "medium"
    status: DecisionStatus
    answer: str | None = None
    messages: list[DecisionMessage] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class CreateDecisionRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    context: str = Field(default="", max_length=2000)


class DecisionMessageRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class DecisionAnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)


class AgentSession(BaseModel):
    id: str
    provider: str
    status: str
    workspace_id: str
    workspace_label: str
    pane_id: str
    cwd: str
    title: str
    task_summary: str
    latest_human_request: str | None = None
    request_source: str = "unavailable"
    request_explanation: str = "尚未取得最近的人類指派。"
    focused: bool = False
    state_revision: int | None = None
    can_read_recent_output: bool = True
    can_send_message: bool = True
    observation: str = "live_herdr_socket"
    runtime_session_id: str | None = None


class AgentSessionsResponse(BaseModel):
    connected: bool
    source: str
    limitation: str
    agents: list[AgentSession] = Field(default_factory=list)


class AgentTranscript(BaseModel):
    agent_id: str
    content: str
    source: str
    limitation: str
    is_at_latest: bool = True
    freshness_warning: str | None = None


class AgentMessageRequest(BaseModel):
    body: str = Field(min_length=1, max_length=8000)


class StartAgentRequest(BaseModel):
    kind: str = Field(pattern=r"^(codex|claude)$")
    model: str = Field(default="", max_length=80)
    initial_prompt: str = Field(default="", max_length=8000)


class StartAgentResponse(BaseModel):
    agent_id: str
    pane_id: str
    kind: str
    model: str | None = None
    status: str = "started"


class ShellPaneResponse(BaseModel):
    pane_id: str
    cwd: str
    status: str = "ready"


class ShellCommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=4000)
    confirm_dangerous: bool = False


class ShellCommandResponse(BaseModel):
    pane_id: str
    command: str
    status: str
    blocked_reason: str | None = None


class GoalSessionCandidate(BaseModel):
    session_id: str
    provider: str = "codex"
    goal_id: str | None = None
    epoch_verified: bool = False
    identity_evidence: list[str] = Field(default_factory=list)
    objective: str
    status: str
    cwd: str
    updated_at: datetime
    tokens_used: int | None = None
    time_used_seconds: int | None = None
    evidence_level: str = "structured_session"


class GoalSessionCandidatesResponse(BaseModel):
    source: str
    limitation: str
    sessions: list[GoalSessionCandidate] = Field(default_factory=list)


class AgentDelegation(BaseModel):
    id: str
    parent_provider: str
    parent_session_id: str
    parent_goal_id: str | None = None
    parent_goal_objective: str | None = None
    child_provider: str
    description: str
    launch_model: str | None = None
    observed_model: str | None = None
    requested_model: str | None = None
    model_compliance: str = "unknown"
    launch_model_compliance: str = "unknown"
    observed_model_compliance: str = "unknown"
    launch_method: str
    background_task_id: str | None = None
    child_session_id: str | None = None
    child_agent_id: str | None = None
    goal_binding: str = "unverified"
    visibility: str = "untracked_runtime"
    status: str = "unknown"
    started_at: datetime
    updated_at: datetime
    evidence: list[str] = Field(default_factory=list)


class AgentDelegationsResponse(BaseModel):
    source: str
    limitation: str
    delegations: list[AgentDelegation] = Field(default_factory=list)


class CreateMonitorRequest(BaseModel):
    agent_id: str = Field(pattern=r"^w[A-Za-z0-9]+:p\d+$")
    goal_session_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    provider: str = "codex"
    goal_epoch_id: str | None = None
    cadence_minutes: int = Field(default=60, ge=15, le=240)
    notify_only: bool = True


class MonitorEvent(BaseModel):
    id: str
    monitor_id: str
    verdict: MonitorVerdict
    finding_type: str
    summary: str
    evidence: list[str] = Field(default_factory=list)
    recommendation: str = ""
    confidence: Confidence = Confidence.UNKNOWN
    decision_id: str | None = None
    created_at: datetime


class GoalMonitor(BaseModel):
    id: str
    project_id: str
    agent_id: str
    goal_session_id: str
    provider: str = "unknown"
    goal_epoch_id: str | None = None
    identity_verified: bool = False
    identity_evidence: list[str] = Field(default_factory=list)
    objective: str
    cadence_minutes: int
    notify_only: bool
    status: MonitorStatus
    start_head: str | None = None
    last_checked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    events: list[MonitorEvent] = Field(default_factory=list)


class MonitorSnapshot(BaseModel):
    monitor_id: str
    project_id: str
    project_root: str
    agent_id: str
    agent_status: str
    goal_session_id: str
    provider: str = "codex"
    goal_epoch_id: str | None = None
    identity_verified: bool = False
    goal_objective: str
    goal_status: str
    goal_updated_at: datetime
    terminal_excerpt: str
    terminal_limitation: str
    git_head: str | None = None
    git_status: list[str] = Field(default_factory=list)
    git_diff_stat: list[str] = Field(default_factory=list)
    captured_at: datetime


class MonitorFindingRequest(BaseModel):
    verdict: MonitorVerdict
    finding_type: str = Field(min_length=2, max_length=80)
    summary: str = Field(min_length=3, max_length=1000)
    evidence: list[str] = Field(default_factory=list, max_length=20)
    recommendation: str = Field(default="", max_length=2000)
    confidence: Confidence = Confidence.UNKNOWN


class MonitorReconcileResult(BaseModel):
    project_id: str
    rearmed_monitor_ids: list[str] = Field(default_factory=list)
    created_monitor_ids: list[str] = Field(default_factory=list)
    pending_agent_ids: list[str] = Field(default_factory=list)
    pending_goal_session_ids: list[str] = Field(default_factory=list)
    explanation: str



def normalized_path(raw_path: str) -> Path:
    return Path(raw_path).expanduser().resolve(strict=True)

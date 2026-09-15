export type Confidence = 'high' | 'medium' | 'low' | 'unknown'
export type PlanState = 'not_started' | 'in_progress' | 'implemented' | 'partial' | 'at_risk' | 'blocked' | 'verified' | 'unknown'

export interface DiscoveredDocument {
  kind: string
  path: string
  title: string
  explanation: string
}

export interface RepositoryFacts {
  root_path: string
  repository_name: string
  current_branch: string | null
  remote_url: string | null
  languages: string[]
  test_commands: string[]
}

export interface ImportPreview {
  preview_id: string
  source_kind: 'local_repository'
  facts: RepositoryFacts
  understanding: {
    name: string
    plain_language_purpose: string
    confidence: Confidence
    evidence_paths: string[]
    missing_information: string[]
    conflicts: string[]
  }
  documents: DiscoveredDocument[]
  proposed_plan: PlanNode[]
  warnings: string[]
  scanned_at: string
}

export interface PlanNode {
  id: string
  kind: string
  title: string
  description: string
  technical_label: string | null
  state: PlanState
  state_explanation: string
  acceptance_met: number
  acceptance_total: number
  evidence_count: number
  documented_done: string[]
  documented_remaining: string[]
  acceptance_criteria: string[]
  source_paths: string[]
  children: PlanNode[]
}

export interface ProjectSummary {
  id: string
  workspace_id: string
  parent_project_id: string | null
  name: string
  purpose: string
  source_kind: string
  source_path: string | null
  confidence: Confidence
  plan_status: 'draft' | 'confirmed' | 'needs_source'
  health: PlanState
  health_explanation: string
  decision_count: number
  updated_at: string
}

export interface ProjectDetail extends ProjectSummary {
  facts: RepositoryFacts | null
  documents: DiscoveredDocument[]
  plan: PlanNode[]
}

export interface Portfolio {
  workspace_id: string
  workspace_name: string
  projects: ProjectSummary[]
}

export interface DecisionMessage {
  id: string
  role: 'human' | 'agent'
  body: string
  created_at: string
}

export interface DecisionCard {
  id: string
  project_id: string
  question: string
  context: string
  recommendation: string
  impact: string
  status: 'waiting_human' | 'waiting_agent' | 'answered' | 'resolved'
  answer: string | null
  messages: DecisionMessage[]
  created_at: string
  updated_at: string
}

export interface AgentSession {
  id: string
  provider: string
  status: string
  workspace_id: string
  workspace_label: string
  pane_id: string
  cwd: string
  title: string
  task_summary: string
  latest_human_request: string | null
  request_source: 'terminal_extracted' | 'control_center_sent' | 'pane_title' | 'unavailable'
  request_explanation: string
  focused: boolean
  state_revision: number | null
  can_read_recent_output: boolean
  can_send_message: boolean
  observation: string
  runtime_session_id?: string | null
}

export interface AgentSessionsResponse {
  connected: boolean
  source: string
  limitation: string
  agents: AgentSession[]
}

export interface AgentTranscript {
  agent_id: string
  content: string
  source: string
  limitation: string
  is_at_latest: boolean
  freshness_warning: string | null
}

export interface StartAgentResponse {
  agent_id: string
  pane_id: string
  kind: 'codex' | 'claude' | string
  model: string | null
  status: string
}

export interface ShellPaneResponse {
  pane_id: string
  cwd: string
  status: string
}

export interface ShellCommandResponse {
  pane_id: string
  command: string
  status: 'sent' | 'blocked' | string
  blocked_reason: string | null
}

export interface GoalSessionCandidate {
  session_id: string
  provider: 'claude' | 'codex' | string
  goal_id: string | null
  epoch_verified: boolean
  identity_evidence: string[]
  objective: string
  status: string
  cwd: string
  updated_at: string
  tokens_used: number | null
  time_used_seconds: number | null
  evidence_level: string
}

export interface GoalSessionCandidatesResponse {
  source: string
  limitation: string
  sessions: GoalSessionCandidate[]
}

export interface AgentDelegation {
  id: string
  parent_provider: string
  parent_session_id: string
  parent_goal_id: string | null
  parent_goal_objective: string | null
  child_provider: string
  description: string
  launch_model: string | null
  observed_model: string | null
  requested_model: string | null
  model_compliance: 'match' | 'mismatch' | 'unknown' | string
  launch_model_compliance: string
  observed_model_compliance: string
  launch_method: string
  background_task_id: string | null
  child_session_id: string | null
  child_agent_id: string | null
  goal_binding: 'verified' | 'unverified' | 'absent' | string
  visibility: string
  status: string
  started_at: string
  updated_at: string
  evidence: string[]
}

export interface AgentDelegationsResponse {
  source: string
  limitation: string
  delegations: AgentDelegation[]
}

export type MonitorVerdict = 'clean' | 'attention' | 'needs_human' | 'terminal' | 'error'

export interface MonitorEvent {
  id: string
  monitor_id: string
  verdict: MonitorVerdict
  finding_type: string
  summary: string
  evidence: string[]
  recommendation: string
  confidence: Confidence
  decision_id: string | null
  created_at: string
}

export interface GoalMonitor {
  id: string
  project_id: string
  agent_id: string
  goal_session_id: string
  provider: string
  goal_epoch_id: string | null
  identity_verified: boolean
  identity_evidence: string[]
  objective: string
  cadence_minutes: number
  notify_only: boolean
  status: 'armed' | 'paused' | 'complete' | 'error'
  start_head: string | null
  last_checked_at: string | null
  created_at: string
  updated_at: string
  events: MonitorEvent[]
}

export interface MonitorSnapshot {
  monitor_id: string
  project_id: string
  project_root: string
  agent_id: string
  agent_status: string
  goal_session_id: string
  provider: string
  goal_epoch_id: string | null
  identity_verified: boolean
  goal_objective: string
  goal_status: string
  goal_updated_at: string
  terminal_excerpt: string
  terminal_limitation: string
  git_head: string | null
  git_status: string[]
  git_diff_stat: string[]
  captured_at: string
}

export interface Capabilities {
  mode: string
  allowed_actions: string[]
  fleet_available: boolean
  notification_delivery: string
  push_available: boolean
}

export interface MonitorReconcileResult {
  project_id: string
  rearmed_monitor_ids: string[]
  created_monitor_ids: string[]
  pending_agent_ids: string[]
  pending_goal_session_ids: string[]
  explanation: string
}

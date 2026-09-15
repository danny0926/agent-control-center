import type { AgentDelegationsResponse, AgentSessionsResponse, AgentTranscript, DecisionCard, GoalMonitor, GoalSessionCandidatesResponse, ImportPreview, MonitorReconcileResult, MonitorSnapshot, Portfolio, ProjectDetail, ShellCommandResponse, ShellPaneResponse, StartAgentResponse } from './types'
import type { Capabilities } from './types'

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options?.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail ?? `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export const api = {
  capabilities: () => request<Capabilities>('/api/capabilities'),
  portfolio: () => request<Portfolio>('/api/portfolio'),
  previewLocalImport: (path: string) =>
    request<ImportPreview>('/api/imports/local/preview', {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),
  confirmImport: (input: {
    preview_id: string
    display_name: string
    purpose: string
    parent_project_id?: string | null
  }) =>
    request<ProjectDetail>('/api/projects', {
      method: 'POST',
      body: JSON.stringify(input),
    }),
  project: (id: string) => request<ProjectDetail>(`/api/projects/${id}`),
  confirmPlan: (id: string) =>
    request<ProjectDetail>(`/api/projects/${id}/plan/confirm`, { method: 'POST' }),
  refreshPlan: (id: string) =>
    request<ProjectDetail>(`/api/projects/${id}/plan/refresh`, { method: 'POST' }),
  decisions: (projectId: string) => request<DecisionCard[]>(`/api/projects/${projectId}/decisions`),
  createDecision: (projectId: string, question: string, context: string) =>
    request<DecisionCard>(`/api/projects/${projectId}/decisions`, {
      method: 'POST', body: JSON.stringify({ question, context }),
    }),
  addDecisionMessage: (projectId: string, decisionId: string, body: string) =>
    request<DecisionCard>(`/api/projects/${projectId}/decisions/${decisionId}/messages`, {
      method: 'POST', body: JSON.stringify({ body }),
    }),
  answerDecision: (projectId: string, decisionId: string, answer: string) =>
    request<DecisionCard>(`/api/projects/${projectId}/decisions/${decisionId}/answer`, {
      method: 'POST', body: JSON.stringify({ answer }),
    }),
  agents: (projectId: string) =>
    request<AgentSessionsResponse>(`/api/projects/${projectId}/agents`),
  agentTranscript: (projectId: string, agentId: string) =>
    request<AgentTranscript>(`/api/projects/${projectId}/agents/${encodeURIComponent(agentId)}/transcript`),
  agentTranscriptStreamUrl: (projectId: string, agentId: string) =>
    `/api/projects/${projectId}/agents/${encodeURIComponent(agentId)}/transcript/stream`,
  sendAgentMessage: (projectId: string, agentId: string, body: string) =>
    request<{ status: string; agent_id: string }>(`/api/projects/${projectId}/agents/${encodeURIComponent(agentId)}/messages`, {
      method: 'POST', body: JSON.stringify({ body }),
    }),
  startAgent: (projectId: string, input: { kind: 'codex' | 'claude'; model: string; initial_prompt: string }) =>
    request<StartAgentResponse>(`/api/projects/${projectId}/agents/start`, {
      method: 'POST', body: JSON.stringify(input),
    }),
  createShell: (projectId: string) =>
    request<ShellPaneResponse>(`/api/projects/${projectId}/shell`, { method: 'POST' }),
  shellTranscript: (projectId: string, paneId: string) =>
    request<AgentTranscript>(`/api/projects/${projectId}/shell/${encodeURIComponent(paneId)}/transcript`),
  runShellCommand: (projectId: string, paneId: string, command: string, confirm_dangerous: boolean) =>
    request<ShellCommandResponse>(`/api/projects/${projectId}/shell/${encodeURIComponent(paneId)}/commands`, {
      method: 'POST', body: JSON.stringify({ command, confirm_dangerous }),
    }),
  goalSessions: (projectId: string) =>
    request<GoalSessionCandidatesResponse>(`/api/projects/${projectId}/goal-sessions`),
  agentDelegations: (projectId: string) =>
    request<AgentDelegationsResponse>(`/api/projects/${projectId}/agent-delegations`),
  monitors: (projectId: string) =>
    request<GoalMonitor[]>(`/api/projects/${projectId}/monitors`),
  reconcileMonitors: (projectId: string) =>
    request<MonitorReconcileResult>(`/api/projects/${projectId}/monitors/reconcile`, { method: 'POST' }),
  createMonitor: (projectId: string, input: {
    agent_id: string
    goal_session_id: string
    provider: string
    goal_epoch_id: string
    cadence_minutes: number
    notify_only: boolean
  }) => request<GoalMonitor>(`/api/projects/${projectId}/monitors`, {
    method: 'POST', body: JSON.stringify(input),
  }),
  monitorSnapshot: (projectId: string, monitorId: string) =>
    request<MonitorSnapshot>(`/api/projects/${projectId}/monitors/${monitorId}/snapshot`, { method: 'POST' }),
  pauseMonitor: (projectId: string, monitorId: string) =>
    request<GoalMonitor>(`/api/projects/${projectId}/monitors/${monitorId}/pause`, { method: 'POST' }),
}

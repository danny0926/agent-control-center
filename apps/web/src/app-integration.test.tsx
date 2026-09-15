import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { App } from './App'
import type { NotificationTarget } from './notifications'

let notificationTarget: NotificationTarget = { project_id: 'p1', view: 'agents', entity_id: 'old-session' }
vi.mock('./NotificationCenter', () => ({ NotificationCenter: ({ onNavigate }: { onNavigate: (target: NotificationTarget) => void }) => <button onClick={() => onNavigate(notificationTarget)}>開啟測試通知</button> }))
const leaf = { id: 'leaf', kind: 'work', title: '可驗收成果', description: '', state: 'implemented', state_explanation: '', acceptance_met: 0, acceptance_total: 1, evidence_count: 0, documented_done: [], documented_remaining: [], acceptance_criteria: ['主要流程完成'], source_paths: [], children: [] }
const project = { id: 'p1', name: '測試專案', purpose: '測試整合', workspace_id: 'local', parent_project_id: null, source_path: '/fixture', confidence: 'high', plan_status: 'confirmed', health: 'unknown', health_explanation: '尚未驗收', updated_at: new Date().toISOString(), documents: [], plan: [{ ...leaf, id: 'root', title: '產品', children: [{ ...leaf, id: 'middle', children: [{ ...leaf, id: 'deep', children: [leaf] }] }] }] }
const agent = { id: 'w1:p1', provider: 'codex', status: 'working', runtime_session_id: 'new-session', workspace_id: 'w1', workspace_label: '測試專案', pane_id: 'w1:p1', cwd: '/fixture', title: '工作', task_summary: '目前的新任務', can_send_message: true, request_explanation: '', latest_human_request: '新任務', request_source: 'pane_title' }
const goal = { session_id: 'new-session', provider: 'codex', goal_id: 'epoch-one', epoch_verified: true, identity_evidence: [], objective: '已核對目標', status: 'active', updated_at: new Date().toISOString() }
const fetchMock = vi.fn()
let allowed: string[] = []
let runtimeSession = 'new-session'
beforeEach(() => {
  allowed = []; runtimeSession = 'new-session'
  notificationTarget = { project_id: 'p1', view: 'agents', entity_id: 'old-session' }
  vi.stubGlobal('EventSource', undefined)
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockImplementation(async (input: string, options?: RequestInit) => {
    let value: unknown = project
    if (input === '/api/portfolio') value = { workspace_id: 'local', workspace_name: '測試工作區', projects: [project] }
    else if (input === '/api/capabilities') value = { allowed_actions: allowed }
    else if (input.endsWith('/agents')) value = { connected: true, limitation: '', agents: [{ ...agent, runtime_session_id: runtimeSession }] }
    else if (input.endsWith('/goal-sessions')) value = { sessions: [goal, { ...goal, session_id: 'other-session', goal_id: 'other-epoch', objective: '另一個目標' }, { ...goal, goal_id: 'unknown-epoch', epoch_verified: false, objective: '未核對目標' }] }
    else if (input.endsWith('/agent-delegations')) value = { delegations: [], limitation: '' }
    else if (input.endsWith('/monitors/reconcile')) value = { explanation: '未建立任何配對', rearmed_monitor_ids: [], pending_agent_ids: [] }
    else if (input.endsWith('/monitors')) value = options?.method === 'POST' ? { id: 'monitor-one', project_id: 'p1', agent_id: agent.id, goal_session_id: runtimeSession, provider: 'codex', goal_epoch_id: goal.goal_id, identity_verified: true, identity_evidence: [], objective: goal.objective, cadence_minutes: 60, status: 'armed', events: [] } : []
    else if (input.includes('/verification-state/')) value = { revision: null, revision_error: '測試目錄未提交', scope_hash: 'scope', policy: null, acceptance_criteria: leaf.acceptance_criteria, records: [] }
    else if (input.endsWith('/transcript')) value = { agent_id: agent.id, content: '目前來源輸出', limitation: '', is_at_latest: true }
    return { ok: true, json: async () => value }
  })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
async function openProject() {
  render(<App />)
  fireEvent.click(await screen.findByText('測試專案'))
  await screen.findByRole('button', { name: '工作' })
}

test('write controls stay disabled without capabilities and an old session never opens the reused pane', async () => {
  await openProject()
  fireEvent.click(screen.getByRole('button', { name: '開啟測試通知' }))
  await screen.findByText(/通知中的歷史 Agent session 已不可用/)
  expect(screen.getByRole('button', { name: '啟動 Agent' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '建立 Shell pane' })).toBeDisabled()
  expect(fetchMock.mock.calls.some(call => call[0].endsWith('/transcript'))).toBe(false)
  fireEvent.click(screen.getByText('目前的新任務'))
  expect(await screen.findByRole('button', { name: '傳送訊息' })).toBeDisabled()
})

test('monitor binding permits only the explicit runtime session and verified goal epoch', async () => {
  await openProject()
  fireEvent.click(screen.getByRole('button', { name: '監工' }))
  fireEvent.click(await screen.findByRole('button', { name: '綁定 `/goal`' }))
  const create = screen.getByRole('button', { name: '建立唯讀監工' })
  expect(create).toBeDisabled()
  fireEvent.change(screen.getByLabelText('正在工作的 Codex pane'), { target: { value: 'w1:p1' } })
  await screen.findByRole('option', { name: /已核對目標/ })
  expect(screen.queryByRole('option', { name: /另一個目標|未核對目標/ })).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('已核對的 Codex 目標輪次'), { target: { value: 'epoch-one' } })
  fireEvent.click(create)
  await waitFor(() => expect(fetchMock.mock.calls.some(call => call[0].endsWith('/monitors') && call[1]?.method === 'POST')).toBe(true))
  const body = fetchMock.mock.calls.find(call => call[0].endsWith('/monitors') && call[1]?.method === 'POST')![1].body
  expect(JSON.parse(body)).toMatchObject({ agent_id: 'w1:p1', goal_session_id: 'new-session', provider: 'codex', goal_epoch_id: 'epoch-one', notify_only: true })
})

test('deep leaf work exposes verification evidence rather than stopping at an intermediate parent', async () => {
  await openProject()
  fireEvent.click(screen.getByRole('button', { name: '工作' }))
  fireEvent.click(screen.getByRole('button', { name: '查看已完成與待辦' }))
  fireEvent.click(screen.getByText('核對驗收證據'))
  await screen.findByText('目前不能提交驗收：測試目錄未提交')
  expect(fetchMock.mock.calls.some(call => call[0] === '/api/projects/p1/verification-state/leaf')).toBe(true)
})

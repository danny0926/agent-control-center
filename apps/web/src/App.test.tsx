// Runtime UUID literals in this module are synthetic fixtures.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { App } from './App'

const emptyPortfolio = { workspace_id: 'local', workspace_name: '我的工作區', projects: [] }
const summary = {
  id: 'project-1', workspace_id: 'local', parent_project_id: null, name: 'Clear Product',
  purpose: '讓團隊看懂下一步。', source_kind: 'local_repository', source_path: 'D:\\project',
  confidence: 'high', plan_status: 'draft', health: 'unknown',
  health_explanation: '成果樹等待確認。', decision_count: 0, updated_at: new Date().toISOString(),
}
const detail = {
  ...summary,
  facts: { root_path: 'D:\\project', repository_name: 'project', current_branch: 'main', remote_url: null, languages: ['TypeScript / JavaScript'], test_commands: ['npm test'] },
  documents: [],
  plan: [{
    id: 'goal', kind: 'goal', title: '讓團隊看懂下一步。', description: '草稿', technical_label: 'product-goal',
    state: 'unknown', state_explanation: '等待確認', acceptance_met: 0, acceptance_total: 1,
    evidence_count: 0, source_paths: ['ROADMAP.md'], children: [],
  }],
}

const fetchMock = vi.fn()
vi.stubGlobal('fetch', fetchMock)

beforeEach(() => {
  fetchMock.mockReset()
  fetchMock.mockResolvedValue({ ok: true, json: async () => emptyPortfolio })
})

test('explains the empty workspace in plain language', async () => {
  render(<App />)
  await waitFor(() => expect(screen.getByText('先加入一個專案，讓全貌變得清楚')).toBeInTheDocument())
  expect(screen.getByText('第一版不會修改來源 repository')).toBeInTheDocument()
})

test('lets the owner confirm a generated plan instead of leaving a dead end', async () => {
  fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url === '/api/portfolio') return { ok: true, json: async () => ({ ...emptyPortfolio, projects: [summary] }) }
    if (url.endsWith('/decisions')) return { ok: true, json: async () => [] }
    if (url.endsWith('/agents')) return { ok: true, json: async () => ({ connected: true, source: 'Herdr socket API', limitation: '只顯示可靠狀態。', agents: [{ id: 'w1:p1', provider: 'codex', status: 'working', workspace_id: 'w1', workspace_label: 'Clear Product', pane_id: 'w1:p1', cwd: 'D:\\project', title: 'implementing', task_summary: '完成匯入流程', latest_human_request: '請完成匯入流程，並補上失敗狀態測試。', request_source: 'terminal_extracted', request_explanation: '從最近的人類輸入擷取。', focused: true, state_revision: 3, can_read_recent_output: true, can_send_message: true, observation: 'live_herdr_socket' }] }) }
    if (url.endsWith('/goal-sessions')) return { ok: true, json: async () => ({ source: 'Claude', limitation: '', sessions: [{ session_id: '11111111-1111-1111-1111-111111111111', provider: 'claude', goal_id: 'goal-1', objective: '請叫 gpt6 完成功能', status: 'active', cwd: 'D:\\project', updated_at: new Date().toISOString(), tokens_used: null, time_used_seconds: null, evidence_level: 'claude_goal_status' }] }) }
    if (url.endsWith('/agent-delegations')) return { ok: true, json: async () => ({ source: 'Claude', limitation: '沒有 child identity 時不猜測。', delegations: [{ id: 'dispatch-1', parent_provider: 'claude', parent_session_id: '11111111-1111-1111-1111-111111111111', parent_goal_id: 'goal-1', parent_goal_objective: '請叫 gpt6 完成功能', child_provider: 'codex', description: '實作功能', launch_model: 'gpt-5.6-sol', observed_model: null, requested_model: 'gpt6', model_compliance: 'mismatch', launch_method: 'claude_bash_codex_exec', background_task_id: 'task-one', child_session_id: null, child_agent_id: null, goal_binding: 'unverified', visibility: 'background_shell', status: 'started', started_at: new Date().toISOString(), updated_at: new Date().toISOString(), evidence: [] }] }) }
    if (url.endsWith('/transcript')) return { ok: true, json: async () => ({ agent_id: 'w1:p1', content: '正在處理', source: 'Herdr', limitation: '最近終端輸出。' }) }
    if (url.endsWith('/plan/confirm')) {
      return { ok: true, json: async () => ({ ...detail, plan_status: 'confirmed', plan: [{ ...detail.plan[0], state: 'in_progress', state_explanation: '產品計畫已由人確認。' }] }) }
    }
    return { ok: true, json: async () => detail }
  })

  render(<App />)
  await waitFor(() => expect(screen.getByText('Clear Product')).toBeInTheDocument())
  fireEvent.click(screen.getByText('Clear Product'))
  await waitFor(() => expect(screen.getByRole('button', { name: '確認這份計畫' })).toBeInTheDocument())
  fireEvent.click(screen.getByRole('button', { name: '確認這份計畫' }))
  await waitFor(() => expect(screen.getByText('產品計畫已確認')).toBeInTheDocument())

  fireEvent.click(screen.getByRole('button', { name: '工作' }))
  expect(screen.getByText('工作與產品成果')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Agents' }))
  await waitFor(() => expect(screen.getByText(/完成匯入流程/)).toBeInTheDocument())
  expect(screen.getByText('未驗證 child Goal')).toBeInTheDocument()
  expect(screen.getByText(/要求 gpt6.*啟動設定 gpt-5.6-sol/)).toBeInTheDocument()
  fireEvent.click(screen.getByText(/完成匯入流程/))
  await waitFor(() => expect(screen.getByText('請完成匯入流程，並補上失敗狀態測試。')).toBeInTheDocument())
  fireEvent.click(screen.getByRole('button', { name: '證據' }))
  expect(screen.getByText('系統理解專案所使用的來源')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '決策' }))
  await waitFor(() => expect(screen.getByText('目前沒有需要你回答的問題')).toBeInTheDocument())
})

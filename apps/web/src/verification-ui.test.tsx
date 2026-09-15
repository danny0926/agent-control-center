import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { VerificationPanel } from './VerificationPanel'
import type { PlanNode } from './types'

const node: PlanNode = { id: 'leaf', kind: 'work', title: '成果', description: '', technical_label: null, state: 'implemented', state_explanation: '', acceptance_met: 0, acceptance_total: 1, evidence_count: 0, documented_done: [], documented_remaining: [], acceptance_criteria: ['主要流程可完成'], source_paths: [], children: [] }
const ready = { revision: 'abcdef', revision_error: null, scope_hash: 'scope-1', policy: { id: 'policy-1', required_gates: ['單元測試'], scope_hash: 'scope-1' }, acceptance_criteria: node.acceptance_criteria, records: [] }
const fetchMock = vi.fn()
beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockReset()
  fetchMock.mockResolvedValue({ ok: true, json: async () => ready })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
async function open() {
  fireEvent.click(screen.getByText('核對驗收證據'))
  await waitFor(() => expect(fetchMock).toHaveBeenCalled())
  await screen.findByText('必要檢查：單元測試')
}
function fillEvidence() {
  fireEvent.click(screen.getByRole('checkbox', { name: '我已核對「主要流程可完成」通過' }))
  fireEvent.change(screen.getByLabelText('驗收條件 1 的報告相對路徑（每行一項）'), { target: { value: 'reports/acceptance.json' } })
  fireEvent.click(screen.getByRole('checkbox', { name: '我已核對「單元測試」通過' }))
  fireEvent.change(screen.getByLabelText('必要檢查 1 的報告相對路徑（每行一項）'), { target: { value: 'reports/unit.xml\nreports/unit-summary.json' } })
}

test('existing policy requires each evidence check before saving an owner-attested result', async () => {
  const verified = vi.fn()
  fetchMock.mockImplementation(async (_url: string, options?: RequestInit) => ({ ok: true, json: async () => options?.method === 'POST' ? { id: 'record-1', status: 'verified', source: 'owner_attested', revision: 'abcdef' } : ready }))
  render(<VerificationPanel projectId="p1" node={node} onVerified={verified} />)
  expect(fetchMock).not.toHaveBeenCalled()
  await open()
  expect(screen.getByRole('button', { name: '確認證據並保存驗收' })).toBeDisabled()
  fillEvidence()
  fireEvent.click(screen.getByRole('button', { name: '確認證據並保存驗收' }))
  await waitFor(() => expect(verified).toHaveBeenCalledTimes(1))
  const call = fetchMock.mock.calls.find(call => call[1]?.method === 'POST')!
  expect(call[0]).toBe('/api/projects/p1/verifications')
  expect(JSON.parse(call[1].body)).toMatchObject({ node_id: 'leaf', revision: 'abcdef', policy_id: 'policy-1', acceptance_results: [{ name: '主要流程可完成', passed: true, evidence_paths: ['reports/acceptance.json'] }], gate_results: [{ name: '單元測試', passed: true, evidence_paths: ['reports/unit.xml', 'reports/unit-summary.json'] }] })
  expect(fetchMock.mock.calls.some(call => call[1]?.method === 'PUT')).toBe(false)
  expect(screen.getByText(/由你核對證據；系統驗證檔案與版本/)).toBeInTheDocument()
})

test('dirty revision and unsafe paths cannot be submitted even with all boxes checked', async () => {
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({ ...ready, revision_error: '工作目錄有未提交變更。' }) })
  render(<VerificationPanel projectId="p1" node={node} />)
  await open(); fillEvidence()
  expect(screen.getByRole('alert')).toHaveTextContent('未提交變更')
  expect(screen.getByRole('button', { name: '確認證據並保存驗收' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('驗收條件 1 的報告相對路徑（每行一項）'), { target: { value: '../other/secret.txt' } })
  expect(screen.getByText(/請使用專案內相對路徑/)).toBeInTheDocument()
  expect(fetchMock.mock.calls.some(call => call[1]?.method === 'POST')).toBe(false)
})

test('new policy starts empty and requires explicitly supplied gates', async () => {
  let saved = false
  fetchMock.mockImplementation(async (_url: string, options?: RequestInit) => {
    if (options?.method === 'PUT') saved = true
    return { ok: true, json: async () => ({ ...ready, policy: saved ? ready.policy : null }) }
  })
  render(<VerificationPanel projectId="p1" node={node} />)
  fireEvent.click(screen.getByText('核對驗收證據'))
  const input = await screen.findByLabelText('必要檢查（必填，每行一項）')
  expect(input).toHaveValue('')
  expect(screen.getByRole('button', { name: '儲存必要檢查' })).toBeDisabled()
  fireEvent.change(input, { target: { value: '單元測試' } })
  fireEvent.click(screen.getByRole('button', { name: '儲存必要檢查' }))
  await screen.findByText('必要檢查：單元測試')
  expect(JSON.parse(fetchMock.mock.calls.find(call => call[1]?.method === 'PUT')![1].body)).toEqual({ required_gates: ['單元測試'] })
  expect(screen.getByRole('button', { name: '確認證據並保存驗收' })).toBeDisabled()
})

test('non-leaf nodes never fetch or offer a verification submission', async () => {
  render(<VerificationPanel projectId="p1" node={{ ...node, children: [{ ...node, id: 'child' }] }} />)
  fireEvent.click(screen.getByText('核對驗收證據'))
  await screen.findByText('請選擇最末層成果，逐項核對驗收。')
  expect(fetchMock).not.toHaveBeenCalled()
  expect(screen.queryByRole('button', { name: '確認證據並保存驗收' })).not.toBeInTheDocument()
})

test('server revision rejection never reports a verified result', async () => {
  const verified = vi.fn()
  fetchMock.mockImplementation(async (_url: string, options?: RequestInit) => options?.method === 'POST' ? { ok: false, status: 409, json: async () => ({ detail: 'Git 版本已變動，請重新核對。' }) } : { ok: true, json: async () => ready })
  render(<VerificationPanel projectId="p1" node={node} onVerified={verified} />)
  await open(); fillEvidence()
  fireEvent.click(screen.getByRole('button', { name: '確認證據並保存驗收' }))
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Git 版本已變動'))
  expect(verified).not.toHaveBeenCalled()
})

test('an old policy scope and expired evidence cannot be attested as current', async () => {
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({ ...ready, scope_hash: 'changed-scope' }) })
  render(<VerificationPanel projectId="p1" node={node} />)
  await open(); fillEvidence()
  expect(screen.getByRole('alert')).toHaveTextContent('驗收範圍已改變')
  expect(screen.getByRole('button', { name: '確認證據並保存驗收' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('證據有效期限（本機時間）'), { target: { value: '2020-01-01T12:00' } })
  expect(screen.getByText('有效期限必須晚於目前時間。')).toBeInTheDocument()
})

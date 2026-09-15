import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { NotificationCenter } from './NotificationCenter'
import { defaultPreferences, isQuiet, showDesktopOnce } from './notifications'
import type { Notice } from './notifications'

const item = (sequence: number): Notice => ({ id: `notice-${sequence}`, sequence, event_type: 'agent.turn_completed', project_id: 'p1', title: `Agent 完成第 ${sequence} 輪`, summary: '這一輪已結束，尚未代表驗收通過。', created_at: new Date(Date.now() + 1000).toISOString(), read_at: null, target: { project_id: 'p1', view: 'agents', entity_id: 'w1:p1' } })
class FakeSource extends EventTarget {
  static all: FakeSource[] = []
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  close = vi.fn()
  constructor(public url: string) { super(); FakeSource.all.push(this) }
  send(notice: Notice) { this.dispatchEvent(new MessageEvent('notification', { data: JSON.stringify(notice) })) }
}
const fetchMock = vi.fn()
let healthFixture = { background_enabled: true, sources: [{ id: 'runtime', status: 'healthy', checked_at: new Date().toISOString() }] }
let desktopCalls: unknown[] = []
const permission = vi.fn()
class FakeNotification {
  static permission = 'granted'
  static requestPermission = permission
  onclick = null
  close() {}
  constructor(...args: unknown[]) { desktopCalls.push(args) }
}
beforeEach(() => {
  FakeSource.all = []; desktopCalls = []; localStorage.clear(); fetchMock.mockReset(); permission.mockReset()
  healthFixture = { background_enabled: true, sources: [{ id: 'runtime', status: 'healthy', checked_at: new Date().toISOString() }] }
  vi.stubGlobal('fetch', (url: string, options?: RequestInit) => url.endsWith('notification-status') ? Promise.resolve({ ok: true, json: async () => healthFixture }) : fetchMock(url, options)); vi.stubGlobal('EventSource', FakeSource); vi.stubGlobal('Notification', FakeNotification); vi.stubGlobal('isSecureContext', true)
  vi.stubGlobal('BroadcastChannel', undefined)
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (_: string, callback: () => unknown) => callback() } })
  fetchMock.mockImplementation(async (url: string, options?: RequestInit) => {
    if (url.endsWith('notification-preferences')) return { ok: true, json: async () => options?.method === 'PUT' ? JSON.parse(options.body as string) : { ...defaultPreferences, desktop_enabled: true } }
    if (options?.method === 'PATCH') return { ok: true, json: async () => ({ ...item(2), read_at: new Date().toISOString() }) }
    return { ok: true, json: async () => ({ items: [item(1)], high_watermark: 1, next_cursor: null, unread_count: 1 }) }
  })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

test('baseline is silent and the stream starts at the snapshot watermark; duplicate events produce one alert', async () => {
  const navigate = vi.fn()
  render(<NotificationCenter onNavigate={navigate} />)
  await waitFor(() => expect(FakeSource.all).toHaveLength(1))
  expect(FakeSource.all[0].url).toContain('after=1')
  expect(desktopCalls).toHaveLength(0)
  const next = item(2)
  act(() => { FakeSource.all[0].send(next); FakeSource.all[0].send(next) })
  await waitFor(() => expect(desktopCalls).toHaveLength(1))
  expect(screen.getByRole('button', { name: '通知，2 則未讀' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /Agent 完成第 2 輪/ }))
  await waitFor(() => expect(navigate).toHaveBeenCalledWith(next.target))
})

test('a denied permission request stays inside a user action and never saves enabled preferences', async () => {
  fetchMock.mockImplementation(async (url: string) => ({ ok: true, json: async () => url.endsWith('notification-preferences') ? defaultPreferences : { items: [], high_watermark: 0, next_cursor: null, unread_count: 0 } }))
  permission.mockResolvedValue('denied')
  render(<NotificationCenter onNavigate={vi.fn()} />)
  await waitFor(() => expect(FakeSource.all).toHaveLength(1))
  expect(permission).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '通知，0 則未讀' }))
  fireEvent.click(screen.getByRole('button', { name: '通知偏好' }))
  fireEvent.click(screen.getByRole('button', { name: '啟用系統通知' }))
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('未獲允許'))
  expect(fetchMock.mock.calls.some(call => call[1]?.method === 'PUT')).toBe(false)
})

test('two tabs serialize the same desktop event and no-lock browsers retain only the inbox', async () => {
  let queue = Promise.resolve<unknown>(undefined)
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: (_: string, callback: () => unknown) => { queue = queue.then(callback); return queue } } })
  const prefs = { ...defaultPreferences, desktop_enabled: true }
  const results = await Promise.all([showDesktopOnce(item(10), prefs, vi.fn()), showDesktopOnce(item(10), prefs, vi.fn())])
  expect(results).toEqual([true, false]); expect(desktopCalls).toHaveLength(1)
  Object.defineProperty(navigator, 'locks', { configurable: true, value: undefined })
  expect(await showDesktopOnce(item(11), prefs, vi.fn())).toBe(false)
})

test('quiet hours use the configured timezone and span midnight', () => {
  const prefs = { ...defaultPreferences, timezone: 'Asia/Taipei', quiet_start: '22:00', quiet_end: '08:00' }
  expect(isQuiet(prefs, new Date('2026-09-15T15:00:00Z'))).toBe(true)
  expect(isQuiet(prefs, new Date('2026-09-15T01:00:00Z'))).toBe(false)
})

test('old replay events remain in the inbox without raising a fresh desktop alert', async () => {
  render(<NotificationCenter onNavigate={vi.fn()} />)
  await waitFor(() => expect(FakeSource.all).toHaveLength(1))
  act(() => FakeSource.all[0].send({ ...item(2), created_at: '2020-01-01T00:00:00Z' }))
  expect(desktopCalls).toHaveLength(0)
  fireEvent.click(screen.getByRole('button', { name: '通知，2 則未讀' }))
  expect(screen.getByText('Agent 完成第 2 輪')).toBeInTheDocument()
})

test('older history uses the before cursor and stays silent; reset can move a cursor backwards', async () => {
  let baselineCalls = 0
  fetchMock.mockImplementation(async (url: string) => {
    if (url.endsWith('notification-preferences')) return { ok: true, json: async () => defaultPreferences }
    if (url.includes('before=')) return { ok: true, json: async () => ({ items: [item(1)], high_watermark: 50, next_cursor: null, unread_count: 2 }) }
    baselineCalls++
    const sequence = baselineCalls === 1 ? 50 : 2
    return { ok: true, json: async () => ({ items: [item(sequence)], high_watermark: sequence, next_cursor: baselineCalls === 1 ? 49 : null, unread_count: 1 }) }
  })
  render(<NotificationCenter onNavigate={vi.fn()} />)
  await waitFor(() => expect(FakeSource.all).toHaveLength(1))
  fireEvent.click(screen.getByRole('button', { name: '通知，1 則未讀' }))
  fireEvent.click(screen.getByRole('button', { name: '載入較早通知' }))
  await waitFor(() => expect(screen.getByText('Agent 完成第 1 輪')).toBeInTheDocument())
  expect(fetchMock.mock.calls.some(call => call[0].includes('before=49'))).toBe(true)
  expect(desktopCalls).toHaveLength(0)
  act(() => FakeSource.all[0].dispatchEvent(new MessageEvent('reset', { data: '{}' })))
  await waitFor(() => expect(FakeSource.all).toHaveLength(2))
  expect(FakeSource.all[1].url).toContain('after=2')
  expect(screen.queryByText('Agent 完成第 50 輪')).not.toBeInTheDocument()
})

test('rejected preferences are reported and are not presented as saved', async () => {
  fetchMock.mockImplementation(async (url: string, options?: RequestInit) => {
    if (options?.method === 'PUT') return { ok: false, status: 403 }
    return { ok: true, json: async () => url.endsWith('notification-preferences') ? defaultPreferences : { items: [], high_watermark: 0, next_cursor: null, unread_count: 0 } }
  })
  render(<NotificationCenter onNavigate={vi.fn()} />)
  await waitFor(() => expect(FakeSource.all).toHaveLength(1))
  fireEvent.click(screen.getByRole('button', { name: '通知，0 則未讀' }))
  fireEvent.click(screen.getByRole('button', { name: '通知偏好' }))
  const checkbox = screen.getByRole('checkbox', { name: 'Agent 本輪完成' })
  fireEvent.click(checkbox)
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('存取已失效'))
  expect(checkbox).toBeChecked()
})

test('collector health remains distinct from the browser connection', async () => {
  healthFixture = { background_enabled: false, sources: [{ id: 'runtime', status: 'healthy', checked_at: '2020-01-01T00:00:00Z' }] }
  render(<NotificationCenter onNavigate={vi.fn()} />)
  await waitFor(() => expect(FakeSource.all).toHaveLength(1))
  act(() => FakeSource.all[0].onopen?.())
  fireEvent.click(screen.getByRole('button', { name: '通知，1 則未讀' }))
  expect(screen.getByText('通知連線正常')).toBeInTheDocument()
  expect(screen.getByText(/背景事件收集已停用/)).toBeInTheDocument()
  expect(screen.getByText(/回報已過期/)).toBeInTheDocument()
})

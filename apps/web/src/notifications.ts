export type NotificationTarget = { project_id: string | null; view: 'agents' | 'decisions' | 'work' | 'overview'; entity_id: string | null }
export type Notice = { id: string; sequence: number; event_type: string; project_id: string | null; title: string; summary: string; created_at: string; read_at: string | null; target: NotificationTarget }
export type NoticePage = { items: Notice[]; high_watermark: number; next_cursor: number | null; unread_count: number }
export type NoticePreferences = { desktop_enabled: boolean; event_types: string[]; project_ids: string[] | null; quiet_start: string | null; quiet_end: string | null; timezone: string }
export type NotificationHealth = { background_enabled: boolean; sources: { id: string; status: string; checked_at: string }[] }
export const eventLabels: Record<string, string> = { 'agent.turn_completed': 'Agent 本輪完成', 'agent.goal_completed': 'Agent 回報目標完成', 'decision.waiting_human': '需要你決定', 'work.verified': '項目通過驗收', 'work.verification_invalidated': '驗收需重新確認', 'run.failed': '工作失敗', 'quota.blocked': '額度不足', 'node.offline': '電腦離線' }
export const defaultPreferences: NoticePreferences = { desktop_enabled: false, event_types: Object.keys(eventLabels), project_ids: null, quiet_start: null, quiet_end: null, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone }
async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const result = await fetch(`/api/${path}`, { method, headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined })
  if (!result.ok) throw new Error(result.status === 401 || result.status === 403 ? '通知存取已失效，請重新登入。' : '無法更新通知，請稍後重試。')
  return result.status === 204 ? undefined as T : result.json()
}
export const noticesApi = {
  health: () => request<NotificationHealth>('notification-status'),
  list: (after = 0, tail = false) => request<NoticePage>(`notifications?after=${after}&limit=50${tail ? '&tail=true' : ''}`),
  older: (before: number) => request<NoticePage>(`notifications?before=${before}&limit=50`),
  read: (id: string) => request<Notice>(`notifications/${encodeURIComponent(id)}`, 'PATCH', { read: true }),
  readAll: (through: number) => request<void>('notifications/read-all', 'POST', { through_sequence: through }),
  preferences: () => request<NoticePreferences>('notification-preferences'),
  save: (value: NoticePreferences) => request<NoticePreferences>('notification-preferences', 'PUT', value),
}
export function isQuiet(prefs: NoticePreferences, now = new Date()) {
  if (!prefs.quiet_start || !prefs.quiet_end) return false
  try {
    const parts = new Intl.DateTimeFormat('en-GB', { timeZone: prefs.timezone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(now)
    const time = `${parts.find(p => p.type === 'hour')?.value}:${parts.find(p => p.type === 'minute')?.value}`
    return prefs.quiet_start <= prefs.quiet_end ? time >= prefs.quiet_start && time < prefs.quiet_end : time >= prefs.quiet_start || time < prefs.quiet_end
  } catch { return true }
}
export function wantsAlert(item: Notice, prefs: NoticePreferences) {
  return prefs.event_types.includes(item.event_type) && (prefs.project_ids === null || (item.project_id !== null && prefs.project_ids.includes(item.project_id))) && !isQuiet(prefs)
}
// Persist the receipt under a Web Lock: concurrent tabs cannot both display it.
// Without atomic coordination, retain the inbox rather than promise duplicate-free desktop delivery.
export async function showDesktopOnce(item: Notice, prefs: NoticePreferences, navigate: (target: NotificationTarget) => void) {
  if (!prefs.desktop_enabled || !wantsAlert(item, prefs) || typeof Notification === 'undefined' || Notification.permission !== 'granted' || !navigator.locks) return false
  return navigator.locks.request('control-center-notification-display', async () => {
    const key = `control-center-notice:${item.id}`
    try {
      if (localStorage.getItem(key)) return false
      localStorage.setItem(key, String(Date.now()))
      const notice = new Notification('Control Center 有新的工作狀態', { body: '開啟通知中心查看詳情。', tag: item.id })
      notice.onclick = () => { window.focus(); navigate(item.target); notice.close() }
      return true
    } catch { return false }
  })
}

import { useEffect, useRef, useState } from 'react'
import { Bell, X } from 'lucide-react'
import { defaultPreferences, eventLabels, noticesApi, showDesktopOnce, wantsAlert } from './notifications'
import type { Notice, NoticePreferences, NotificationTarget, NotificationHealth } from './notifications'
import './notifications.css'

export function NotificationCenter({ onNavigate, projects = [] }: { onNavigate: (target: NotificationTarget) => void; projects?: { id: string; name: string }[] }) {
  const [open, setOpen] = useState(false)
  const [settings, setSettings] = useState(false)
  const [items, setItems] = useState<Notice[]>([])
  const [unread, setUnread] = useState(0)
  const [prefs, setPrefs] = useState<NoticePreferences>(defaultPreferences)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('正在連接通知…')
  const [toast, setToast] = useState<Notice | null>(null)
  const [filter, setFilter] = useState('')
  const [busy, setBusy] = useState(false)
  const [olderCursor, setOlderCursor] = useState<number | null>(null)
  const [health, setHealth] = useState<NotificationHealth | null>(null)
  const [healthError, setHealthError] = useState('')
  const cursor = useRef(0)
  const seen = useRef(new Set<string>())
  const records = useRef(new Map<string, Notice>())
  const prefsRef = useRef(prefs)
  const navigateRef = useRef(onNavigate)
  const channel = useRef<BroadcastChannel | null>(null)
  const bell = useRef<HTMLButtonElement>(null)
  prefsRef.current = prefs
  navigateRef.current = onNavigate

  useEffect(() => {
    let active = true
    const refresh = async () => {
      try {
        const value = await noticesApi.health()
        if (active) {
          if (!Array.isArray(value.sources) || typeof value.background_enabled !== 'boolean') throw new Error('未取得事件收集狀態。')
          setHealth(value); setHealthError('')
        }
      } catch { if (active) { setHealth(null); setHealthError('無法核對事件來源，通知連線正常也不代表完成事件已被收集。') } }
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 15000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])

  useEffect(() => {
    let active = true
    let source: EventSource | null = null
    let syncing = false
    let initialized = false
    const listeningSince = Date.now()
    const merge = (incoming: Notice[], live: boolean) => {
      if (!active) return
      incoming = incoming.map(item => ({ ...item, read_at: item.read_at ?? records.current.get(item.id)?.read_at ?? null }))
      for (const item of incoming) {
        if (live && !seen.current.has(item.id)) {
          if (!item.read_at) setUnread(n => n + 1)
          if (new Date(item.created_at).getTime() >= listeningSince && wantsAlert(item, prefsRef.current)) {
            setToast(item)
            void showDesktopOnce(item, prefsRef.current, target => navigateRef.current(target))
          }
        }
        seen.current.add(item.id)
        records.current.set(item.id, item)
        cursor.current = Math.max(cursor.current, item.sequence)
      }
      setItems(previous => {
        const map = new Map(previous.map(item => [item.id, item]))
        incoming.forEach(item => map.set(item.id, item))
        return [...map.values()].sort((a, b) => b.sequence - a.sequence)
      })
    }
    const connect = () => {
      source?.close()
      if (!active || typeof EventSource === 'undefined') { setStatus('以定期更新接收通知'); return }
      source = new EventSource(`/api/notifications/stream?after=${cursor.current}`)
      source.onopen = () => { if (active) setStatus('通知連線正常') }
      source.onerror = () => { if (active) setStatus('通知連線中斷，正在重新連接') }
      source.addEventListener('notification', event => {
        try { merge([JSON.parse((event as MessageEvent).data)], true) } catch { setError('通知格式無法辨識，正在等待重新同步。') }
      })
      source.addEventListener('resync', () => { source?.close(); void sync(true) })
      source.addEventListener('reset', () => { source?.close(); void sync(true) })
    }
    const sync = async (baseline: boolean) => {
      if (syncing) return
      syncing = true
      try {
        let after = baseline ? 0 : cursor.current
        const incoming: Notice[] = []
        let firstWatermark: number | null = null
        let unreadCount = 0
        let lastWatermark = 0
        do {
          const page = await noticesApi.list(after, !baseline)
          if (!Array.isArray(page.items)) throw new Error('通知服務尚未就緒。')
          firstWatermark ??= page.high_watermark
          unreadCount = page.unread_count
          lastWatermark = page.high_watermark
          incoming.push(...page.items)
          if (baseline) { setOlderCursor(page.next_cursor); break }
          if (page.next_cursor === null) break
          if (page.next_cursor <= after) throw new Error('通知分頁無法繼續，請重試。')
          after = page.next_cursor
        } while (active)
        if (!active) return
        if (baseline) { seen.current.clear(); records.current.clear(); cursor.current = 0; setItems([]); setToast(null) }
        merge(incoming, !baseline)
        setUnread(unreadCount + [...records.current.values()].filter(item => item.sequence > lastWatermark && !item.read_at).length)
        cursor.current = Math.max(cursor.current, firstWatermark ?? 0)
        setError('')
        initialized = true
        if (baseline) connect()
      } catch (reason) { if (active) {
        const message = reason instanceof Error ? reason.message : '通知同步失敗。'
        if (message.includes('存取已失效')) { source?.close(); source = null; initialized = false; setItems([]); setUnread(0); setToast(null) }
        setError(message); setStatus('通知尚未同步')
      } }
      finally { syncing = false }
    }
    void noticesApi.preferences().then(value => { if (active && Array.isArray(value.event_types)) setPrefs(value) }).catch(() => { if (active) setError('無法讀取通知偏好，桌面通知暫不啟用。') })
    void sync(true)
    const timer = window.setInterval(() => void sync(!initialized), 15000)
    if (typeof BroadcastChannel !== 'undefined') {
      channel.current = new BroadcastChannel('control-center-notifications')
      channel.current.onmessage = event => {
        if (event.data?.type === 'read') {
          const record = records.current.get(event.data.id)
          if (record) records.current.set(record.id, { ...record, read_at: event.data.read_at })
          setItems(previous => previous.map(item => item.id === event.data.id ? { ...item, read_at: event.data.read_at } : item))
          void sync(false)
        } else if (event.data?.type === 'preferences') {
          void noticesApi.preferences().then(value => { if (active) setPrefs(value) }).catch(() => {})
        } else if (event.data?.type === 'read-all') void sync(true)
      }
    }
    return () => { active = false; source?.close(); window.clearInterval(timer); channel.current?.close(); channel.current = null }
  }, [])

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(null), 8000)
    return () => window.clearTimeout(timer)
  }, [toast])

  async function choose(item: Notice) {
    try {
      if (!item.read_at) {
        const updated = await noticesApi.read(item.id)
        records.current.set(updated.id, updated)
        setItems(previous => previous.map(row => row.id === item.id ? updated : row))
        setUnread(n => Math.max(0, n - 1))
        channel.current?.postMessage({ type: 'read', id: item.id, read_at: updated.read_at })
      }
      setOpen(false); setToast(null); onNavigate(item.target)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '無法開啟通知。') }
  }
  async function save(value: NoticePreferences) {
    setBusy(true)
    try { setPrefs(await noticesApi.save(value)); channel.current?.postMessage({ type: 'preferences' }); setError('') }
    catch (reason) { setError(reason instanceof Error ? reason.message : '偏好未儲存。') }
    finally { setBusy(false) }
  }
  async function enableDesktop() {
    if (typeof Notification === 'undefined' || !window.isSecureContext) { setError('此瀏覽器或連線不支援系統通知，仍可使用站內通知。'); return }
    try {
      const permission = await Notification.requestPermission()
      if (permission !== 'granted') { setError('系統通知未獲允許，仍可使用站內通知。'); return }
      if (!navigator.locks) { setError('此瀏覽器缺少多分頁協調能力，請使用站內通知。'); return }
      await save({ ...prefs, desktop_enabled: true })
    } catch { setError('無法啟用系統通知，仍可使用站內通知。') }
  }
  async function readAll() {
    try {
      const through = cursor.current
      await noticesApi.readAll(through)
      for (const [id, record] of records.current) if (record.sequence <= through) records.current.set(id, { ...record, read_at: record.read_at ?? new Date().toISOString() })
      setItems(previous => previous.map(item => item.sequence <= through ? { ...item, read_at: item.read_at ?? new Date().toISOString() } : item))
      const page = await noticesApi.list(cursor.current)
      setUnread(page.unread_count + [...records.current.values()].filter(item => item.sequence > page.high_watermark && !item.read_at).length)
      channel.current?.postMessage({ type: 'read-all' })
    } catch { setError('無法標示已讀，請重試。') }
  }
  async function older() {
    if (olderCursor === null) return
    setBusy(true)
    try {
      const page = await noticesApi.older(olderCursor)
      setItems(previous => [...new Map([...previous, ...page.items].map(item => [item.id, item])).values()].sort((a, b) => b.sequence - a.sequence))
      page.items.forEach(item => seen.current.add(item.id))
      page.items.forEach(item => records.current.set(item.id, item))
      setOlderCursor(page.next_cursor)
    } catch { setError('無法載入較早通知，請重試。') }
    finally { setBusy(false) }
  }
  return <div className="notification-root">
    <button ref={bell} className="notification-bell" aria-label={`通知，${unread} 則未讀`} aria-expanded={open} aria-controls="notification-panel" onClick={() => setOpen(!open)}><Bell size={19} /><span>通知</span>{unread > 0 && <b>{unread}</b>}</button>
    {open && <section id="notification-panel" className="notification-panel" aria-label="通知中心" onKeyDown={event => { if (event.key === 'Escape') { setOpen(false); bell.current?.focus() } }}>
      <header><h2>通知中心</h2><button aria-label="關閉通知中心" onClick={() => { setOpen(false); bell.current?.focus() }}><X size={18} /></button></header>
      <p className="notification-status">{status}</p>
      <section aria-label="通知事件來源" className="notification-status">
        <strong>事件收集狀態</strong>
        {healthError ? <p>{healthError}</p> : !health ? <p>正在核對事件來源…</p> : <>
          <p>{health.background_enabled ? '背景事件收集已啟用' : '背景事件收集已停用，無法保證即時完成提醒。'}</p>
          {health.sources.length === 0 && <p>尚未收到事件收集器的健康回報。</p>}
          <ul>{health.sources.map(source => {
            const checked = new Date(source.checked_at).getTime()
            const stale = !Number.isFinite(checked) || Date.now() - checked > 120000
            const label = stale ? '回報已過期，狀態待確認' : source.status === 'healthy' ? '收集正常' : source.status === 'stale' ? '來源尚未完整更新' : source.status === 'error' ? '收集發生錯誤' : '狀態尚未確認'
            return <li key={source.id}>{source.id === 'runtime' ? 'Agent 事件' : '事件來源'}：{label}<br />最近核對：{Number.isFinite(checked) ? new Date(checked).toLocaleString('zh-TW') : '未知'}</li>
          })}</ul>
        </>}
      </section>
      <div className="notification-actions"><button onClick={() => setSettings(!settings)} aria-expanded={settings}>通知偏好</button><button onClick={() => void readAll()} disabled={!unread}>全部標為已讀</button></div>
      {error && <p role="alert" className="notification-error">{error}</p>}
      {settings && <div className="notification-settings">
        <p>系統通知只顯示一般摘要，詳細內容請回到網站查看。</p>
        <button disabled={busy} onClick={() => prefs.desktop_enabled ? void save({ ...prefs, desktop_enabled: false }) : void enableDesktop()}>{prefs.desktop_enabled ? '停用系統通知' : '啟用系統通知'}</button>
        <fieldset disabled={busy}><legend>提醒事件</legend>{Object.entries(eventLabels).map(([type, label]) => <label key={type}><input type="checkbox" checked={prefs.event_types.includes(type)} onChange={event => void save({ ...prefs, event_types: event.target.checked ? [...prefs.event_types, type] : prefs.event_types.filter(value => value !== type) })} />{label}</label>)}</fieldset>
        <fieldset disabled={busy}><legend>訂閱專案</legend><label><input type="checkbox" checked={prefs.project_ids === null} onChange={event => void save({ ...prefs, project_ids: event.target.checked ? null : [] })} />所有有權限的專案</label>{prefs.project_ids !== null && projects.map(project => <label key={project.id}><input type="checkbox" checked={prefs.project_ids!.includes(project.id)} onChange={event => void save({ ...prefs, project_ids: event.target.checked ? [...prefs.project_ids!, project.id] : prefs.project_ids!.filter(id => id !== project.id) })} />{project.name}</label>)}</fieldset>
        <fieldset disabled={busy}><legend>安靜時段（{prefs.timezone}）</legend><label>開始<input type="time" value={prefs.quiet_start ?? ''} onChange={event => setPrefs({ ...prefs, quiet_start: event.target.value || null })} /></label><label>結束<input type="time" value={prefs.quiet_end ?? ''} onChange={event => setPrefs({ ...prefs, quiet_end: event.target.value || null })} /></label><button onClick={() => void save(prefs)}>儲存安靜時段</button></fieldset>
      </div>}
      <label className="notification-filter">查看專案<select value={filter} onChange={event => setFilter(event.target.value)}><option value="">全部專案</option>{projects.map(project => <option value={project.id} key={project.id}>{project.name}</option>)}</select></label>
      <ul>{items.filter(item => !filter || item.project_id === filter).map(item => <li key={item.id} className={item.read_at ? '' : 'is-unread'}><button onClick={() => void choose(item)}><strong>{!item.read_at && <span aria-label="未讀">● </span>}{item.title}</strong><span>{item.summary}</span><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString('zh-TW')}</time></button></li>)}</ul>
      {items.length === 0 && <p>目前沒有通知。完成事件及驗收結果會保留在這裡。</p>}
      {olderCursor !== null && <button disabled={busy} onClick={() => void older()}>載入較早通知</button>}
    </section>}
    <div className="notification-announcement" role="status" aria-live="polite">{toast ? '有新的工作狀態通知。' : ''}</div>
    {toast && <aside className="notification-toast"><button onClick={() => void choose(toast)}><strong>{toast.title}</strong><span>查看詳情</span></button><button aria-label="關閉提醒" onClick={() => setToast(null)}><X size={16} /></button></aside>}
  </div>
}

import { useEffect, useState } from 'react'
import type { PlanNode } from './types'

type EvidenceCheck = { name: string; passed: boolean; paths: string }
type VerificationState = {
  revision: string | null
  revision_error: string | null
  scope_hash: string
  policy: { id: string; required_gates: string[]; scope_hash: string } | null
  acceptance_criteria: string[]
  records: { id: string; status: string; source?: string; revision?: string; expires_at?: string }[]
}
function futureLocalTime() {
  const date = new Date(Date.now() + 7 * 24 * 3600 * 1000)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}
function lines(value: string) { return [...new Set(value.split(/\r?\n/).map(line => line.trim()).filter(Boolean))] }
function validPaths(value: string) {
  const paths = lines(value)
  return paths.length > 0 && paths.every(path => !/^(?:[a-z]:|[\\/]|[a-z]+:\/\/)/i.test(path) && !path.split(/[\\/]/).includes('..'))
}
async function verificationRequest<T>(url: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(url, { method, headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined })
  if (!response.ok) {
    let detail = ''
    try { const payload = await response.json(); if (typeof payload.detail === 'string') detail = payload.detail } catch { /* Error pages need not be JSON. */ }
    throw new Error(detail || (response.status === 409 ? '版本或驗收規則已變動，請重新讀取後再核對。' : '驗收資料無法儲存，請稍後重試。'))
  }
  return response.json()
}

export function VerificationPanel({ projectId, node, onVerified }: { projectId: string; node: PlanNode; onVerified?: () => void }) {
  const [open, setOpen] = useState(false)
  const [state, setState] = useState<VerificationState | null>(null)
  const [acceptance, setAcceptance] = useState<EvidenceCheck[]>([])
  const [gates, setGates] = useState<EvidenceCheck[]>([])
  const [required, setRequired] = useState('')
  const [editingPolicy, setEditingPolicy] = useState(false)
  const [expires, setExpires] = useState(futureLocalTime)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [refresh, setRefresh] = useState(0)
  const prefix = `/api/projects/${encodeURIComponent(projectId)}`
  const nodePath = encodeURIComponent(node.id)
  const criteriaKey = JSON.stringify(node.acceptance_criteria)

  useEffect(() => {
    if (!open || node.children.length > 0) return
    let active = true
    setBusy(true); setError(''); setState(null)
    verificationRequest<VerificationState>(`${prefix}/verification-state/${nodePath}`).then(value => {
      if (!active) return
      setState(value)
      setAcceptance(value.acceptance_criteria.map(name => ({ name, passed: false, paths: '' })))
      setGates((value.policy?.required_gates ?? []).map(name => ({ name, passed: false, paths: '' })))
      setRequired((value.policy?.required_gates ?? []).join('\n'))
      setEditingPolicy(!value.policy)
    }).catch(reason => { if (active) setError(reason instanceof Error ? reason.message : '無法讀取驗收狀態。') })
      .finally(() => { if (active) setBusy(false) })
    return () => { active = false }
  }, [open, prefix, nodePath, refresh, criteriaKey, node.children.length])

  const scopeMatches = state?.policy?.scope_hash === state?.scope_hash
  const validExpiry = Number.isFinite(new Date(expires).getTime()) && new Date(expires).getTime() > Date.now()
  const canSubmit = !busy && !editingPolicy && node.children.length === 0 && !!state?.revision && !state?.revision_error && !!state?.policy && scopeMatches && acceptance.length > 0 && gates.length > 0 && [...acceptance, ...gates].every(check => check.passed && validPaths(check.paths)) && validExpiry

  async function savePolicy() {
    const requiredGates = lines(required)
    if (!requiredGates.length) { setError('請至少填寫一項必要檢查。'); return }
    setBusy(true); setError(''); setMessage('')
    try {
      await verificationRequest(`${prefix}/verification-policy/${nodePath}`, 'PUT', { required_gates: requiredGates })
      setMessage('必要檢查已儲存，請逐項重新核對證據。')
      setRefresh(value => value + 1)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '無法儲存必要檢查。'); setBusy(false) }
  }
  async function submit() {
    if (!canSubmit || !state?.policy) return
    setBusy(true); setError(''); setMessage('')
    const payloadCheck = (check: EvidenceCheck) => ({ name: check.name, passed: true, evidence_paths: lines(check.paths) })
    try {
      const result = await verificationRequest<{ id: string; status: string; source: string; revision: string }>(`${prefix}/verifications`, 'POST', {
        node_id: node.id, revision: state.revision, policy_id: state.policy.id,
        acceptance_results: acceptance.map(payloadCheck), gate_results: gates.map(payloadCheck), expires_at: new Date(expires).toISOString(),
      })
      if (result.status !== 'verified' || result.source !== 'owner_attested') throw new Error('伺服器尚未確認驗收結果，請重新讀取。')
      setMessage('已保存你核對的驗收結果。這筆紀錄由你確認證據，系統未代跑測試。')
      onVerified?.()
      setRefresh(value => value + 1)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '驗收未成功儲存。'); setBusy(false) }
  }
  function checkRows(checks: EvidenceCheck[], update: (value: EvidenceCheck[]) => void, category: string) {
    return checks.map((check, index) => <fieldset key={`${category}-${index}`} disabled={busy} style={{ border: '1px solid #d5e2dc', borderRadius: 8, margin: '10px 0', padding: 12 }}>
      <legend>{category} {index + 1}：{check.name}</legend>
      <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}><input type="checkbox" checked={check.passed} onChange={event => update(checks.map((row, i) => i === index ? { ...row, passed: event.target.checked } : row))} />我已核對「{check.name}」通過</label>
      <label className="field"><span>{category} {index + 1} 的報告相對路徑（每行一項）</span><textarea rows={2} value={check.paths} placeholder="reports/acceptance.json" onChange={event => update(checks.map((row, i) => i === index ? { ...row, paths: event.target.value } : row))} /></label>
      {check.paths && !validPaths(check.paths) && <small style={{ color: '#9b2828' }}>請使用專案內相對路徑，不可包含上層目錄、網址或磁碟機名稱。</small>}
    </fieldset>)
  }
  const stateText: Record<string, string> = { verified: '驗收有效', invalidated: '驗收已失效', expired: '已超過有效期限', superseded: '已由新紀錄取代', stale: '需要重新驗收' }
  return <details open={open} onToggle={event => setOpen(event.currentTarget.open)} style={{ margin: '16px 0', border: '1px solid #cbded4', borderRadius: 10, padding: 14, overflowWrap: 'anywhere' }}>
    <summary style={{ cursor: 'pointer', fontWeight: 650 }}>核對驗收證據</summary>
    {open && <div>
      <p>由你核對證據；系統驗證檔案與版本，並未代替你執行測試。</p>
      {node.children.length > 0 ? <p>請選擇最末層成果，逐項核對驗收。</p> : <>
        <button className="secondary-button compact" disabled={busy} onClick={() => { setMessage(''); setRefresh(value => value + 1) }}>重新讀取驗收狀態</button>
        {busy && <p role="status">正在處理驗收資料…</p>}
        {error && <p role="alert" className="inline-error">{error}</p>}
        {message && <p role="status">{message}</p>}
        {state && <>
          {state.revision_error && <p role="alert" className="inline-error">目前不能提交驗收：{state.revision_error}</p>}
          {!state.revision && !state.revision_error && <p>目前沒有可核對的 Git 版本，暫時不能提交。</p>}
          {!acceptance.length && <p>請先在產品計畫補齊明確驗收條件，重新讀取後再核對。</p>}
          {state.policy && !scopeMatches && <p role="alert">驗收範圍已改變，請更新必要檢查後重新核對。</p>}
          {editingPolicy ? <fieldset disabled={busy} style={{ border: '1px solid #d5e2dc', padding: 12, marginTop: 12 }}>
            <legend>設定必要檢查</legend>
            <p>每項都必須有通過證據。修改後會建立新版本，先前的驗收紀錄會失效。</p>
            <label className="field"><span>必要檢查（必填，每行一項）</span><textarea rows={3} value={required} onChange={event => setRequired(event.target.value)} placeholder={'例如：單元測試\n瀏覽器驗收'} /></label>
            <button className="secondary-button compact" disabled={!lines(required).length} onClick={() => void savePolicy()}>儲存必要檢查</button>
            {state.policy && <button className="secondary-button compact" onClick={() => { setRequired(state.policy!.required_gates.join('\n')); setEditingPolicy(false) }}>取消修改</button>}
          </fieldset> : <p>必要檢查：{state.policy?.required_gates.join('、')} <button className="secondary-button compact" disabled={busy} onClick={() => setEditingPolicy(true)}>修改必要檢查</button></p>}
          {!editingPolicy && <>
            {checkRows(acceptance, setAcceptance, '驗收條件')}
            {checkRows(gates, setGates, '必要檢查')}
            <label className="field"><span>證據有效期限（本機時間）</span><input type="datetime-local" value={expires} disabled={busy} onChange={event => setExpires(event.target.value)} /></label>
            {!validExpiry && <p>有效期限必須晚於目前時間。</p>}
            <button className="primary-button" disabled={!canSubmit} onClick={() => void submit()}>確認證據並保存驗收</button>
          </>}
          {state.records.length > 0 && <section aria-label="既有驗收紀錄"><h4>既有驗收紀錄</h4><ul>{state.records.map(record => <li key={record.id}>{stateText[record.status] ?? '狀態待核對'}{record.source === 'owner_attested' && ' · 由擁有者核對證據'}{record.expires_at && ` · 有效至 ${new Date(record.expires_at).toLocaleString('zh-TW')}`}</li>)}</ul></section>}
        </>}
      </>}
    </div>}
  </details>
}

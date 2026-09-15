import { useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, Dispatch, SetStateAction } from 'react'
import {
  AlertCircle,
  Activity,
  ArrowLeft,
  Bot,
  Box,
  Check,
  ChevronDown,
  ChevronRight,
  CircleDot,
  FileText,
  FolderGit2,
  GitBranch,
  Import,
  LayoutDashboard,
  LoaderCircle,
  Network,
  Plus,
  Pause,
  Play,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Terminal,
  X,
} from 'lucide-react'
import { api } from './api'
import { NotificationCenter } from './NotificationCenter'
import { VerificationPanel } from './VerificationPanel'
import type { NotificationTarget } from './notifications'
import type { AgentDelegation, AgentSession, AgentTranscript, DecisionCard, GoalMonitor, GoalSessionCandidate, ImportPreview, MonitorReconcileResult, MonitorSnapshot, PlanNode, PlanState, Portfolio, ProjectDetail, ProjectSummary } from './types'

const stateText: Record<PlanState, string> = {
  not_started: '尚未開始',
  in_progress: '進行中',
  implemented: '已實作・待驗證',
  partial: '第一版已完成',
  at_risk: '需要注意',
  blocked: '被阻塞',
  verified: '已有證據完成',
  unknown: '尚不確定',
}

function relativeTime(value: string) {
  const seconds = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000)
  if (seconds < 60) return '剛剛'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分鐘前`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小時前`
  return `${Math.floor(seconds / 86400)} 天前`
}

function EmptyPortfolio({ onImport }: { onImport: () => void }) {
  return (
    <section className="empty-portfolio">
      <div className="empty-illustration" aria-hidden="true">
        <div className="orbit orbit-one" />
        <div className="orbit orbit-two" />
        <div className="empty-core"><Network size={32} /></div>
      </div>
      <div className="eyebrow">你的專案控制塔</div>
      <h1>先加入一個專案，讓全貌變得清楚</h1>
      <p>
        Control Center 會先唯讀理解產品目的、工作規則和驗證方式。你確認它沒有讀錯後，才會建立產品計畫。
      </p>
      <button className="primary-button" onClick={onImport}><Import size={18} />匯入本機專案</button>
      <div className="trust-note"><ShieldCheck size={16} />第一版不會修改來源 repository</div>
    </section>
  )
}

function ProjectCard({ project, children, onOpen }: {
  project: ProjectSummary
  children: ProjectSummary[]
  onOpen: (id: string) => void
}) {
  return (
    <article className="project-card">
      <button className="project-card-main" onClick={() => onOpen(project.id)}>
        <div className="project-card-head">
          <div className="project-icon"><FolderGit2 size={20} /></div>
          <span className={`status status-${project.health}`}>{stateText[project.health]}</span>
        </div>
        <h3>{project.name}</h3>
        <p>{project.purpose}</p>
        <div className="project-card-reason"><CircleDot size={14} />{project.health_explanation}</div>
        <div className="project-card-foot">
          <span>{project.source_path ?? '沒有連接來源'}</span>
          <span>{relativeTime(project.updated_at)}</span>
        </div>
      </button>
      {children.length > 0 && (
        <div className="subproject-list">
          <span>子專案</span>
          {children.map((child) => (
            <button key={child.id} onClick={() => onOpen(child.id)}>
              <span className="subproject-branch">↳</span>
              <strong>{child.name}</strong>
              <span className={`status status-${child.health}`}>{stateText[child.health]}</span>
              <ChevronRight size={15} />
            </button>
          ))}
        </div>
      )}
    </article>
  )
}

function PortfolioPage({ portfolio, onImport, onOpen }: {
  portfolio: Portfolio
  onImport: () => void
  onOpen: (id: string) => void
}) {
  const topLevel = portfolio.projects.filter((project) => !project.parent_project_id)
  const childrenByParent = portfolio.projects.reduce<Record<string, ProjectSummary[]>>((result, project) => {
    if (project.parent_project_id) (result[project.parent_project_id] ??= []).push(project)
    return result
  }, {})
  const needsAttention = portfolio.projects.filter((project) => ['at_risk', 'blocked', 'unknown'].includes(project.health)).length
  return (
    <main className="page-shell portfolio-page">
      <header className="page-header">
        <div>
          <div className="eyebrow">{portfolio.workspace_name}</div>
          <h1>所有專案</h1>
          <p>先看哪個產品需要你介入，再進入細節；不同專案的完成率不會被混成一個假數字。</p>
        </div>
        <button className="primary-button" onClick={onImport}><Plus size={18} />加入專案</button>
      </header>
      {portfolio.projects.length === 0 ? <EmptyPortfolio onImport={onImport} /> : (
        <>
          <section className="portfolio-summary">
            <div><span>正在管理</span><strong>{portfolio.projects.length}</strong><small>個專案與子專案</small></div>
            <div><span>需要注意</span><strong>{needsAttention}</strong><small>有風險、阻塞或資訊不足</small></div>
            <div><span>等待你回答</span><strong>{portfolio.projects.reduce((sum, item) => sum + item.decision_count, 0)}</strong><small>個產品決策</small></div>
          </section>
          <section>
            <div className="section-heading"><div><h2>專案</h2><p>每張卡只顯示能改變判斷的狀態。</p></div></div>
            <div className="project-grid">
              {topLevel.map((project) => <ProjectCard key={project.id} project={project} children={childrenByParent[project.id] ?? []} onOpen={onOpen} />)}
            </div>
          </section>
        </>
      )}
    </main>
  )
}

function SourceChoice() {
  return (
    <div className="source-grid">
      <div className="source-card selected">
        <FolderGit2 size={23} />
        <div><strong>本機 Git 專案</strong><span>從電腦上的 repository 唯讀掃描</span></div>
        <Check size={18} />
      </div>
      <div className="source-card disabled" aria-disabled="true">
        <GitBranch size={23} />
        <div><strong>GitHub</strong><span>連接 Issue、PR 與 Actions</span></div>
        <small>下一階段</small>
      </div>
      <div className="source-card disabled" aria-disabled="true">
        <Sparkles size={23} />
        <div><strong>建立空白產品</strong><span>從想法開始建立第一版 PRD</span></div>
        <small>下一階段</small>
      </div>
    </div>
  )
}

function ImportWizard({ projects, onClose, onComplete }: {
  projects: ProjectSummary[]
  onClose: () => void
  onComplete: (project: ProjectDetail) => void
}) {
  const [path, setPath] = useState('')
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [name, setName] = useState('')
  const [purpose, setPurpose] = useState('')
  const [parentId, setParentId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function scan() {
    if (!path.trim()) return
    setBusy(true)
    setError('')
    try {
      const result = await api.previewLocalImport(path.trim())
      setPreview(result)
      setName(result.understanding.name)
      setPurpose(result.understanding.plain_language_purpose)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '無法掃描這個專案。')
    } finally {
      setBusy(false)
    }
  }

  async function confirm() {
    if (!preview) return
    setBusy(true)
    setError('')
    try {
      const project = await api.confirmImport({
        preview_id: preview.preview_id,
        display_name: name,
        purpose,
        parent_project_id: parentId || null,
      })
      onComplete(project)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '無法加入這個專案。')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="import-modal" role="dialog" aria-modal="true" aria-labelledby="import-title">
        <header className="modal-header">
          <div>
            <div className="eyebrow">{preview ? '步驟 2 / 2 · 確認理解' : '步驟 1 / 2 · 選擇來源'}</div>
            <h2 id="import-title">{preview ? '系統對這個專案的理解' : '加入一個專案'}</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="關閉"><X size={20} /></button>
        </header>

        {!preview ? (
          <div className="modal-content">
            <p className="lead">先選擇專案在哪裡。掃描只會讀取少數已知文件和 Git 資訊，不會更動任何檔案。</p>
            <SourceChoice />
            <label className="field">
              <span>本機 repository 路徑</span>
              <div className="path-input"><FolderGit2 size={18} /><input value={path} onChange={(event) => setPath(event.target.value)} placeholder="例如 C:\projects\example" autoFocus /></div>
              <small>目前支援已初始化 Git 的資料夾。</small>
            </label>
            {error && <div className="inline-error"><AlertCircle size={17} />{error}</div>}
          </div>
        ) : (
          <div className="modal-content preview-content">
            <div className="understanding-banner">
              <div className={`confidence confidence-${preview.understanding.confidence}`}><Sparkles size={18} />理解信心：{preview.understanding.confidence === 'high' ? '高' : preview.understanding.confidence === 'medium' ? '中等' : '偏低'}</div>
              <p>以下是草稿，不是已核准的產品計畫。請先修正名稱和目的。</p>
            </div>
            <div className="two-column-form">
              <label className="field"><span>專案名稱</span><input value={name} onChange={(event) => setName(event.target.value)} /></label>
              <label className="field"><span>作為哪個專案的子專案？</span><select value={parentId} onChange={(event) => setParentId(event.target.value)}><option value="">不是子專案</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
            </div>
            <label className="field"><span>這個產品用人話來說是什麼？</span><textarea value={purpose} onChange={(event) => setPurpose(event.target.value)} rows={3} /></label>
            <section className="preview-section">
              <h3>找到的依據 <span>{preview.documents.length}</span></h3>
              <div className="document-list">
                {preview.documents.map((document) => <div className="document-row" key={document.path}><FileText size={17} /><div><strong>{document.explanation}</strong><span>{document.path} · {document.title}</span></div></div>)}
              </div>
            </section>
            <section className="preview-section plan-preview-summary">
              <h3><Network size={17} />準備建立的成果樹</h3>
              {preview.proposed_plan.length > 0 ? (
                <p>
                  找到 {preview.proposed_plan[0].children.length} 個產品階段與{' '}
                  {preview.proposed_plan[0].children.reduce((sum, item) => sum + item.children.length, 0)} 個成果項目。
                  加入後會先標為草稿，不會把 Roadmap 的「已完成」直接當成驗證通過。
                </p>
              ) : <p>目前找不到可解析的 Roadmap；加入後會清楚標示需要補上計畫來源。</p>}
            </section>
            {preview.understanding.missing_information.length > 0 && <section className="preview-section warning-section"><h3><AlertCircle size={17} />還不知道的事</h3>{preview.understanding.missing_information.map((item) => <p key={item}>{item}</p>)}</section>}
            <div className="read-only-note"><ShieldCheck size={18} /><div><strong>保持唯讀</strong><span>確認加入只會在 Control Center 建立紀錄，不會寫回 {preview.facts.root_path}</span></div></div>
            {error && <div className="inline-error"><AlertCircle size={17} />{error}</div>}
          </div>
        )}
        <footer className="modal-footer">
          {preview && <button className="text-button" onClick={() => { setPreview(null); setError('') }}><ArrowLeft size={17} />重新選擇</button>}
          <div className="footer-spacer" />
          <button className="secondary-button" onClick={onClose}>取消</button>
          {!preview ? <button className="primary-button" disabled={!path.trim() || busy} onClick={scan}>{busy ? <LoaderCircle className="spin" size={18} /> : <Search size={18} />}掃描專案</button> : <button className="primary-button" disabled={!name.trim() || !purpose.trim() || busy} onClick={confirm}>{busy ? <LoaderCircle className="spin" size={18} /> : <Check size={18} />}確認加入</button>}
        </footer>
      </section>
    </div>
  )
}

function OutcomeTree({ root }: { root: PlanNode }) {
  const [closedMilestones, setClosedMilestones] = useState<Set<string>>(new Set())
  const [openSubMilestones, setOpenSubMilestones] = useState<Set<string>>(
    () => new Set(root.children.flatMap((milestone) => milestone.children.slice(0, 1).map((item) => item.id))),
  )
  const [openOutcomes, setOpenOutcomes] = useState<Set<string>>(new Set())
  function toggle(setter: Dispatch<SetStateAction<Set<string>>>, id: string) {
    setter((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  return (
    <div className="outcome-tree" role="tree" aria-label="產品成果樹">
      <div className="outcome-root-wrap">
        <article className="outcome-node outcome-root-node" role="treeitem">
          <div className="outcome-node-top"><span className="node-kind">產品目標</span><span className={`status status-${root.state}`}>{stateText[root.state]}</span></div>
          <h3>{root.title}</h3>
          <p>{root.description}</p>
          <small>{root.children.length} 個里程碑 · 沿著樹枝查看子里程碑與交付成果</small>
        </article>
      </div>
      <div className="outcome-branches" style={{ '--branch-count': root.children.length, '--branch-inset': `${50 / Math.max(root.children.length, 1)}%` } as CSSProperties}>
        {root.children.map((milestone) => {
          const open = !closedMilestones.has(milestone.id)
          return <section className={`outcome-branch ${open ? 'open' : 'closed'}`} key={milestone.id} role="group">
            <button className="outcome-node milestone-node" onClick={() => toggle(setClosedMilestones, milestone.id)} aria-expanded={open}>
              <div className="outcome-node-top"><span className="node-kind">里程碑</span><span className={`status status-${milestone.state}`}>{stateText[milestone.state]}</span></div>
              <h3>{milestone.title}</h3>
              <p>{milestone.state_explanation}</p>
              <small>{milestone.children.length} 個子里程碑 {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</small>
            </button>
            {open && <div className="submilestone-list">
              {milestone.children.map((subMilestone) => {
                const subOpen = openSubMilestones.has(subMilestone.id)
                return <section className={`submilestone-item ${subOpen ? 'open' : 'closed'}`} key={subMilestone.id} role="group">
                  <button className={`outcome-node submilestone-node status-border-${subMilestone.state}`} onClick={() => toggle(setOpenSubMilestones, subMilestone.id)} aria-expanded={subOpen} role="treeitem">
                    <div className="outcome-node-top"><span className="node-kind submilestone-kind">子里程碑</span><span className={`status status-${subMilestone.state}`}>{stateText[subMilestone.state]}</span></div>
                    <h4>{subMilestone.title}</h4>
                    <p>{subMilestone.state_explanation}</p>
                    <small>{subMilestone.children.length > 0 ? `${subMilestone.children.length} 項交付成果` : '交付成果待拆解'} {subOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</small>
                  </button>
                  {subOpen && subMilestone.children.length > 0 && <div className="deliverable-list">
                    {subMilestone.children.map((outcome) => {
                      const detailOpen = openOutcomes.has(outcome.id)
                      return <button className={`outcome-node outcome-leaf deliverable-leaf status-border-${outcome.state}`} key={outcome.id} onClick={() => toggle(setOpenOutcomes, outcome.id)} aria-expanded={detailOpen} role="treeitem">
                        <div className="outcome-node-top"><span className="node-kind deliverable-kind">交付成果</span><span className={`status status-${outcome.state}`}>{stateText[outcome.state]}</span></div>
                        <h4>{outcome.title}</h4>
                        <p>{detailOpen ? outcome.description : outcome.state_explanation}</p>
                        <small>{detailOpen ? '收起來源' : '查看說明與來源'} {detailOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</small>
                        {detailOpen && <div className="leaf-source">來源：{outcome.source_paths.join('、') || '尚未連結'}</div>}
                      </button>
                    })}
                  </div>}
                </section>
              })}
            </div>}
          </section>
        })}
      </div>
    </div>
  )
}

function WorkPage({ project, targetId, onVerified }: { project: ProjectDetail; targetId?: string | null; onVerified: () => void }) {
  function leaves(item: PlanNode, parent: string): (PlanNode & { milestone: string })[] {
    return item.children.length ? item.children.flatMap(child => leaves(child, item.title)) : [{ ...item, milestone: parent }]
  }
  const outcomes = project.plan.flatMap(root => leaves(root, project.name))
  const [liveAgents, setLiveAgents] = useState<AgentSession[]>([])
  const [expandedItems, setExpandedItems] = useState<Set<string>>(new Set())
  useEffect(() => { if (targetId) setExpandedItems(new Set([targetId])) }, [targetId])
  const stageLevel: Partial<Record<PlanState, number>> = {
    not_started: 0, in_progress: 1, at_risk: 1, blocked: 1, partial: 2, implemented: 3, verified: 4,
  }
  function toggleItem(id: string) {
    setExpandedItems((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  useEffect(() => {
    let active = true
    const refresh = () => void api.agents(project.id).then((result) => {
      if (active) setLiveAgents(result.agents.filter((agent) => ['working', 'blocked'].includes(agent.status)))
    }).catch(() => undefined)
    refresh()
    const timer = window.setInterval(refresh, 5000)
    return () => { active = false; window.clearInterval(timer) }
  }, [project.id])
  return (
    <section className="content-panel">
      <div className="section-heading"><div><h2>工作與產品成果</h2><p>這裡先顯示 Roadmap 中可辨識的成果；後續會再連接 Issue、branch 與 Agent owner。</p></div><span className="view-chip">{outcomes.length} 項</span></div>
      {liveAgents.length > 0 && <div className="live-work"><div className="live-work-title"><span className="live-pulse" /><strong>目前正在執行</strong><small>Herdr 每 5 秒更新</small></div>{liveAgents.map((agent) => <div className="live-work-row" key={agent.id}><Bot size={17} /><div><strong>{agent.provider === 'codex' ? 'Codex' : agent.provider === 'claude' ? 'Claude' : agent.provider}</strong><span>{agent.task_summary}</span></div><span className={`status status-${agent.status === 'blocked' ? 'blocked' : 'in_progress'}`}>{agentStatusText[agent.status] ?? agent.status}</span><small>{agent.workspace_label} · {agent.pane_id} · 尚未連結成果項目</small></div>)}</div>}
      {outcomes.length === 0 ? <div className="friendly-empty"><Box size={28} /><h3>還沒有可辨識的工作</h3><p>目前的 Roadmap 沒有能轉成成果項目的標題或清單。</p></div> : (
        <div className="work-list">
          {outcomes.map((item) => (
            <article key={item.id} className={`work-row ${expandedItems.has(item.id) ? 'expanded' : ''}`}>
              <div><span className="work-parent">{item.milestone}</span><h3>{item.title}</h3><p>{item.description}</p><button className="progress-toggle" onClick={() => toggleItem(item.id)}>{expandedItems.has(item.id) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}{expandedItems.has(item.id) ? '收起進度' : '查看已完成與待辦'}</button></div>
              <div className="work-status"><span className={`status status-${item.state}`}>{stateText[item.state]}</span><div className={`stage-rail ${item.state === 'unknown' ? 'unknown' : ''}`} aria-label={`開發階段：${stateText[item.state]}`}>{[1, 2, 3, 4].map((level) => <span className={(stageLevel[item.state] ?? -1) >= level ? 'active' : ''} key={level} />)}</div><small>開發階段，不是活動量百分比</small><small>{item.acceptance_total > 0 ? `${item.acceptance_met}/${item.acceptance_total} 個驗收條件已有證據` : '尚未定義驗收條件'}</small></div>
              {expandedItems.has(item.id) && <div className="work-progress-detail">
                <VerificationPanel projectId={project.id} node={item} onVerified={onVerified} />
                <div className="progress-summary"><strong>現在做到哪</strong><p>{item.state_explanation}</p></div>
                <div className="progress-columns">
                  <div><h4>已做到</h4>{item.documented_done.length > 0 ? <ul>{item.documented_done.map((entry) => <li key={entry}>{entry}</li>)}</ul> : <p>{item.state === 'implemented' ? '文件宣告已實作，但沒有逐項列出完成內容。' : item.state === 'partial' || item.state === 'in_progress' ? '文件有進度宣告，但尚未逐項列出已完成內容。' : '尚無明確完成紀錄。'}</p>}</div>
                  <div><h4>還差什麼</h4>{item.documented_remaining.length > 0 ? <ul>{item.documented_remaining.map((entry) => <li key={entry}>{entry}</li>)}</ul> : <p>{item.state === 'implemented' ? '開發宣告完成；還要把下列驗收條件連到證據。' : item.state === 'partial' ? '第一版之外的完整範圍尚未量化；還要補齊驗收證據。' : item.state === 'in_progress' ? '文件尚未列出完整剩餘清單。' : '產品文件尚未提供可判斷的剩餘工作。'}</p>}</div>
                  <div><h4>完成時要證明</h4>{item.acceptance_criteria.length > 0 ? <ul>{item.acceptance_criteria.map((entry) => <li key={entry}>{entry}</li>)}</ul> : <p>尚未定義可查核的驗收條件。</p>}</div>
                </div>
              </div>}
            </article>
          ))}
        </div>
      )}
    </section>
  )
}

const decisionStatusText: Record<DecisionCard['status'], string> = {
  waiting_human: '等待你回答', waiting_agent: '等待 Agent 補充', answered: '已回答', resolved: '已完成',
}

function DecisionsPage({ projectId, targetId }: { projectId: string; targetId?: string | null }) {
  const [decisions, setDecisions] = useState<DecisionCard[]>([])
  const [selectedId, setSelectedId] = useState(targetId ?? '')
  useEffect(() => { if (targetId) setSelectedId(targetId) }, [targetId])
  const [showCreate, setShowCreate] = useState(false)
  const [question, setQuestion] = useState('')
  const [context, setContext] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const selected = decisions.find((item) => item.id === selectedId) ?? (targetId ? undefined : decisions[0])

  async function load() {
    setBusy(true)
    try {
      const result = await api.decisions(projectId)
      setDecisions(result)
      if (result[0] && !selectedId) setSelectedId(result[0].id)
      setError('')
    } catch (reason) { setError(reason instanceof Error ? reason.message : '無法讀取決策。') }
    finally { setBusy(false) }
  }
  useEffect(() => { void load() }, [projectId])

  async function createDecision() {
    if (!question.trim()) return
    setBusy(true)
    try {
      const created = await api.createDecision(projectId, question.trim(), context.trim())
      setDecisions((items) => [created, ...items])
      setSelectedId(created.id); setQuestion(''); setContext(''); setShowCreate(false); setError('')
    } catch (reason) { setError(reason instanceof Error ? reason.message : '無法建立問題。') }
    finally { setBusy(false) }
  }

  async function send(kind: 'message' | 'answer') {
    if (!selected || !message.trim()) return
    setBusy(true)
    try {
      const updated = kind === 'message'
        ? await api.addDecisionMessage(projectId, selected.id, message.trim())
        : await api.answerDecision(projectId, selected.id, message.trim())
      setDecisions((items) => items.map((item) => item.id === updated.id ? updated : item))
      setMessage(''); setError('')
    } catch (reason) { setError(reason instanceof Error ? reason.message : '無法送出內容。') }
    finally { setBusy(false) }
  }

  if (busy && decisions.length === 0) return <section className="content-panel"><div className="friendly-empty"><LoaderCircle className="spin" /><p>正在讀取決策…</p></div></section>
  return (
    <section className="content-panel decisions-panel">
      <div className="section-heading"><div><h2>需要人與 Agent 說清楚的問題</h2><p>追問不等於正式回答；兩種操作會留下不同狀態。</p></div><button className="primary-button" onClick={() => setShowCreate(true)}><Plus size={17} />新增問題</button></div>
      {error && <div className="inline-error"><AlertCircle size={17} />{error}</div>}
      {showCreate && <div className="decision-create"><label className="field"><span>你想問 Agent 什麼？</span><textarea rows={2} value={question} onChange={(event) => setQuestion(event.target.value)} autoFocus /></label><label className="field"><span>背景或你不滿意的地方（選填）</span><textarea rows={2} value={context} onChange={(event) => setContext(event.target.value)} /></label><div><button className="text-button" onClick={() => setShowCreate(false)}>取消</button><button className="primary-button" onClick={createDecision} disabled={!question.trim() || busy}>送給 Agent</button></div></div>}
      {decisions.length === 0 && !showCreate ? <div className="friendly-empty"><CircleDot size={28} /><h3>目前沒有需要你回答的問題</h3><p>你也可以主動建立問題，請 Agent 解釋或補充。</p><button className="secondary-button" onClick={() => setShowCreate(true)}>新增一個問題</button></div> : decisions.length > 0 && (
        <div className="decision-layout">
          <div className="decision-list">{decisions.map((item) => <button key={item.id} className={item.id === selected?.id ? 'active' : ''} onClick={() => setSelectedId(item.id)}><span>{item.id} · {decisionStatusText[item.status]}</span><strong>{item.question}</strong><small>{relativeTime(item.updated_at)}</small></button>)}</div>
          {selected && <article className="decision-detail"><div className="decision-detail-head"><div><span>{selected.id}</span><h3>{selected.question}</h3></div><span className={`decision-state decision-${selected.status}`}>{decisionStatusText[selected.status]}</span></div>{selected.context && <p className="decision-context">{selected.context}</p>}<div className="message-thread">{selected.messages.map((item) => <div className={`message message-${item.role}`} key={item.id}><span>{item.role === 'human' ? '你' : 'Agent'}</span><p>{item.body}</p></div>)}</div><label className="field"><span>繼續追問，或直接提供你的答案</span><textarea rows={3} value={message} onChange={(event) => setMessage(event.target.value)} placeholder="請 Agent 補充……或寫下你的決定" /></label><div className="decision-actions"><button className="secondary-button" disabled={!message.trim() || busy} onClick={() => void send('message')}>送出追問</button><button className="primary-button" disabled={!message.trim() || busy} onClick={() => void send('answer')}>作為我的答案</button></div></article>}
        </div>
      )}
    </section>
  )
}

const agentStatusText: Record<string, string> = {
  working: '執行中', idle: '等待工作', done: '已完成一輪', blocked: '需要處理', unknown: '無法判斷',
}

const delegationStatusText: Record<string, string> = {
  running: '執行中', started: '已啟動，狀態未知', stopping: '停止中', stopped: '已停止',
  completed: '已完成', failed: '執行失敗', stale: '歷史・狀態不明', unknown: '狀態不明',
}

function DelegationCard({ item }: { item: AgentDelegation }) {
  const active = ['running', 'started', 'stopping'].includes(item.status)
  return <article><div className="delegation-path"><span>Claude</span><ChevronRight size={14} /><span>Codex</span><strong>{item.description}</strong></div><div className="delegation-badges"><span className={`trace-badge ${item.status === 'running' ? 'trace-live' : active ? 'trace-warn' : item.status === 'failed' ? 'trace-danger' : ''}`}>{delegationStatusText[item.status] ?? item.status}</span><span className={`trace-badge ${item.goal_binding === 'verified' ? 'trace-ok' : 'trace-warn'}`}>{item.goal_binding === 'verified' ? '已驗證掛載 Goal' : '未驗證 child Goal'}</span><span className={`trace-badge ${item.launch_model_compliance === 'mismatch' ? 'trace-danger' : ''}`}>{item.requested_model ? `要求 ${item.requested_model}` : '未指定模型'} → {item.launch_model ? `啟動設定 ${item.launch_model}` : '啟動模型未知'}</span><span className={`trace-badge ${item.observed_model_compliance === 'mismatch' ? 'trace-danger' : ''}`}>{item.observed_model ? `實際模型 ${item.observed_model}` : '實際模型尚未核對'}</span><span className="trace-badge trace-warn">{item.child_agent_id ? `Herdr ${item.child_agent_id}` : 'Herdr 看不到'}</span></div><small>{item.background_task_id ? `背景任務 ${item.background_task_id}` : item.launch_method} · {relativeTime(item.updated_at)}</small></article>
}

function AgentsPage({ projectId, targetId }: { projectId: string; targetId?: string | null }) {
  const [allowedActions, setAllowedActions] = useState<string[]>([])
  const [capabilityError, setCapabilityError] = useState('正在核對操作權限；確認前暫停寫入操作。')
  useEffect(() => {
    let active = true
    const refresh = () => api.capabilities().then(value => {
      if (active) { setAllowedActions(Array.isArray(value.allowed_actions) ? value.allowed_actions : []); setCapabilityError('') }
    }).catch(() => { if (active) { setAllowedActions([]); setCapabilityError('無法核對操作權限，寫入操作暫不開放。') } })
    void refresh()
    const timer = window.setInterval(() => void refresh(), 15000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])
  const can = (action: string) => allowedActions.includes(action)
  const [agents, setAgents] = useState<AgentSession[]>([])
  const [goals, setGoals] = useState<GoalSessionCandidate[]>([])
  const [delegations, setDelegations] = useState<AgentDelegation[]>([])
  const [traceLimitation, setTraceLimitation] = useState('')
  const [connected, setConnected] = useState(false)
  const [limitation, setLimitation] = useState('')
  const [selected, setSelected] = useState<AgentSession | null>(null)
  const openedNotificationTarget = useRef<string | null>(null)
  useEffect(() => { setSelected(null); openedNotificationTarget.current = null }, [targetId])
  useEffect(() => {
    if (!targetId || openedNotificationTarget.current === targetId) return
    const matches = agents.filter(item => item.runtime_session_id === targetId)
    if (matches.length === 1) { setSelected(matches[0]); openedNotificationTarget.current = targetId }
  }, [targetId, agents])
  const [transcript, setTranscript] = useState<AgentTranscript | null>(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [streamState, setStreamState] = useState<'closed' | 'connecting' | 'live' | 'reconnecting' | 'unavailable'>('closed')
  const [streamError, setStreamError] = useState('')
  const [newAgentKind, setNewAgentKind] = useState<'codex' | 'claude'>('codex')
  const [newAgentModel, setNewAgentModel] = useState('gpt-6-astra')
  const [newAgentPrompt, setNewAgentPrompt] = useState('')
  const [selectedAgentModel, setSelectedAgentModel] = useState('gpt-5.6-sol')
  const [shellPaneId, setShellPaneId] = useState('')
  const [shellTranscript, setShellTranscript] = useState<AgentTranscript | null>(null)
  const [shellCommand, setShellCommand] = useState('')
  const [confirmDangerousShell, setConfirmDangerousShell] = useState(false)
  const [shellBusy, setShellBusy] = useState(false)
  const [shellError, setShellError] = useState('')
  const transcriptRef = useRef<HTMLPreElement>(null)
  const shellRef = useRef<HTMLPreElement>(null)

  async function load() {
    setBusy(true)
    try {
      const [result, goalResult, delegationResult] = await Promise.all([
        api.agents(projectId), api.goalSessions(projectId), api.agentDelegations(projectId),
      ])
      setAgents(result.agents); setConnected(result.connected); setLimitation(result.limitation); setError('')
      setGoals(goalResult.sessions); setDelegations(delegationResult.delegations)
      setTraceLimitation(delegationResult.limitation)
      setSelected((current) => current ? result.agents.find((agent) => agent.id === current.id && (!current.runtime_session_id || agent.runtime_session_id === current.runtime_session_id)) ?? null : null)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '無法讀取 Agent 狀態。') }
    finally { setBusy(false) }
  }
  useEffect(() => {
    void load()
    const timer = window.setInterval(() => {
      void Promise.all([api.agents(projectId), api.goalSessions(projectId), api.agentDelegations(projectId)]).then(([result, goalResult, delegationResult]) => {
        setAgents(result.agents); setConnected(result.connected); setLimitation(result.limitation)
        setGoals(goalResult.sessions); setDelegations(delegationResult.delegations); setTraceLimitation(delegationResult.limitation)
        setSelected((current) => current ? result.agents.find((agent) => agent.id === current.id && (!current.runtime_session_id || agent.runtime_session_id === current.runtime_session_id)) ?? null : null)
      }).catch(() => undefined)
    }, 5000)
    return () => window.clearInterval(timer)
  }, [projectId])

  useEffect(() => {
    if (!selected) { setStreamState('closed'); setStreamError(''); return }
    let cancelled = false
    const refreshSnapshot = async () => {
      try {
        const update = await api.agentTranscript(projectId, selected.id)
        if (!cancelled && update.agent_id === selected.id) setTranscript(update)
      } catch (reason) {
        if (!cancelled) setStreamError(reason instanceof Error ? reason.message : '無法讀取 Agent 最近輸出。')
      }
    }
    if (typeof EventSource === 'undefined') {
      setStreamState('unavailable')
      void refreshSnapshot()
      const fallbackTimer = window.setInterval(() => void refreshSnapshot(), 5000)
      return () => { cancelled = true; window.clearInterval(fallbackTimer) }
    }
    setStreamState('connecting'); setStreamError('')
    const source = new EventSource(api.agentTranscriptStreamUrl(projectId, selected.id))
    source.onopen = () => { setStreamState('live'); setStreamError('') }
    source.addEventListener('transcript', (event) => {
      try {
        const update = JSON.parse((event as MessageEvent<string>).data) as AgentTranscript
        if (update.agent_id !== selected.id) return
        setTranscript(update)
        setStreamState('live'); setStreamError('')
      } catch { setStreamState('reconnecting'); setStreamError('收到無法解析的串流內容。') }
    })
    source.addEventListener('agent_error', (event) => {
      try { setStreamError((JSON.parse((event as MessageEvent<string>).data) as { message: string }).message) }
      catch { setStreamError('終端串流暫時中斷。') }
      setStreamState('reconnecting')
    })
    source.onerror = () => { setStreamState('reconnecting'); void refreshSnapshot() }
    // Some mobile networks and HTTPS proxies buffer SSE. Keep a bounded snapshot
    // fallback so the terminal remains useful even when no stream event arrives.
    const fallbackTimer = window.setInterval(() => void refreshSnapshot(), 5000)
    return () => { cancelled = true; window.clearInterval(fallbackTimer); source.close(); setStreamState('closed') }
  }, [projectId, selected?.id])

  useEffect(() => {
    const terminal = transcriptRef.current
    if (terminal) terminal.scrollTop = terminal.scrollHeight
  }, [selected?.id, transcript?.content])

  useEffect(() => {
    if (!shellPaneId) return
    let cancelled = false
    const refresh = async () => {
      try {
        const update = await api.shellTranscript(projectId, shellPaneId)
        if (!cancelled) { setShellTranscript(update); setShellError('') }
      } catch (reason) {
        if (!cancelled) setShellError(reason instanceof Error ? reason.message : '無法讀取 Shell 輸出。')
      }
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 3000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [projectId, shellPaneId])

  useEffect(() => {
    const terminal = shellRef.current
    if (terminal) terminal.scrollTop = terminal.scrollHeight
  }, [shellPaneId, shellTranscript?.content])

  async function openAgent(agent: AgentSession) {
    setSelected(agent); setTranscript(null); setBusy(true); setError(''); setStreamState('connecting'); setStreamError('')
    try {
      // Always load an immediate snapshot. Waiting only for EventSource leaves
      // mobile users on an empty terminal when a tunnel buffers the first event.
      setTranscript(await api.agentTranscript(projectId, agent.id))
    } catch (reason) { setError(reason instanceof Error ? reason.message : '無法讀取最近輸出。') }
    finally { setBusy(false) }
  }

  async function send() {
    if (!selected || !message.trim() || !can('agent.message')) return
    setBusy(true); setError('')
    try {
      await api.sendAgentMessage(projectId, selected.id, message.trim())
      setMessage('')
      if (typeof EventSource === 'undefined') setTranscript(await api.agentTranscript(projectId, selected.id))
      await load()
    } catch (reason) { setError(reason instanceof Error ? reason.message : '無法傳送訊息。') }
    finally { setBusy(false) }
  }

  async function switchSelectedModel() {
    if (!selected || !selectedAgentModel.trim() || !can('agent.message')) return
    setBusy(true); setError('')
    try {
      await api.sendAgentMessage(projectId, selected.id, `/model ${selectedAgentModel.trim()}`)
      if (typeof EventSource === 'undefined') setTranscript(await api.agentTranscript(projectId, selected.id))
      await load()
    } catch (reason) { setError(reason instanceof Error ? reason.message : '無法送出模型切換指令。') }
    finally { setBusy(false) }
  }

  async function startAgent() {
    if (!can('agent.start')) return
    setBusy(true); setError('')
    try {
      const created = await api.startAgent(projectId, {
        kind: newAgentKind,
        model: newAgentModel,
        initial_prompt: newAgentPrompt.trim(),
      })
      setNewAgentPrompt('')
      await load()
      const next = await api.agents(projectId)
      const agent = next.agents.find((item) => item.id === created.agent_id)
      if (agent) await openAgent(agent)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '無法啟動 Agent。') }
    finally { setBusy(false) }
  }

  async function createShell() {
    if (!can('shell.create')) return
    setShellBusy(true); setShellError('')
    try {
      const created = await api.createShell(projectId)
      setShellPaneId(created.pane_id)
      setShellTranscript(await api.shellTranscript(projectId, created.pane_id))
    } catch (reason) { setShellError(reason instanceof Error ? reason.message : '無法建立 Shell pane。') }
    finally { setShellBusy(false) }
  }

  async function runShell() {
    if (!shellPaneId || !shellCommand.trim() || !can('shell.execute')) return
    setShellBusy(true); setShellError('')
    try {
      const result = await api.runShellCommand(projectId, shellPaneId, shellCommand.trim(), confirmDangerousShell)
      if (result.status === 'blocked') {
        setShellError(result.blocked_reason ?? '這個 Shell 指令已被安全規則擋下。')
        return
      }
      setShellCommand('')
      setConfirmDangerousShell(false)
      setShellTranscript(await api.shellTranscript(projectId, shellPaneId))
    } catch (reason) { setShellError(reason instanceof Error ? reason.message : '無法送出 Shell 指令。') }
    finally { setShellBusy(false) }
  }

  const streamText = streamState === 'live' && transcript?.is_at_latest === false ? '串流已連接，但 Claude 畫面不是最新位置' : streamState === 'live' ? '即時更新中' : streamState === 'connecting' ? '正在連線' : streamState === 'reconnecting' ? '連線中斷，正在重連' : streamState === 'unavailable' ? '瀏覽器不支援串流，顯示單次快照' : '串流已關閉'
  const recentGoalCutoff = Date.now() - 24 * 60 * 60 * 1000
  const activeGoals = goals.filter((item) => item.status === 'active' && new Date(item.updated_at).getTime() >= recentGoalCutoff)
  const historicalGoals = goals.filter((item) => item.status !== 'active' || new Date(item.updated_at).getTime() < recentGoalCutoff)
  const activeDelegations = delegations.filter((item) => ['running', 'started', 'stopping'].includes(item.status))
  const historicalDelegations = delegations.filter((item) => !['running', 'started', 'stopping'].includes(item.status))

  return <section className="content-panel"><div className="section-heading"><div><h2>Agents</h2><p>直接看每個 Agent 最近收到的人類指派，以及父 Goal 是否真的交給了可追蹤的子 Agent。</p></div><button className="secondary-button compact" onClick={() => void load()} disabled={busy}><RefreshCw className={busy ? 'spin' : ''} size={15} />更新</button></div>{error && <div className="inline-error"><AlertCircle size={17} />{error}</div>}<div className="runtime-source"><span className={connected ? 'health-dot' : 'health-dot offline'} /><strong>{connected ? 'Herdr 已連接' : 'Herdr 未連接'}</strong><span>{limitation}</span></div>
    {targetId && !busy && agents.filter(agent => agent.runtime_session_id === targetId).length !== 1 && <p role="status" className="connector-note">通知中的歷史 Agent session 已不可用或無法唯一核對；不會改開其他 Agent。</p>}
    <div className="connector-note"><div><strong>操作權限</strong><p>{capabilityError || '以下操作依本機授權設定開放，後端會在執行時再次核對。'}</p><ul>{[['agent.start', '啟動 Agent'], ['agent.message', '傳訊與切換模型'], ['shell.create', '建立 Shell'], ['shell.execute', '執行 Shell 指令']].map(([action, label]) => <li key={action}>{label}：{can(action) ? '已允許' : '未授權，暫不開放'}</li>)}</ul></div></div>
    <div className="agent-console">
      <div className="console-section current-agent-console">
        <div className="console-title"><Send size={17} /><div><strong>Current agent model</strong><span>先在下方選一個現有 Agent，再把 /model 指令忠實送進那個 pane。</span></div></div>
        <div className="console-grid">
          <label className="field"><span>Target</span><input value={selected ? `${selected.provider} · ${selected.pane_id}` : '尚未選擇 Agent'} readOnly /></label>
          <label className="field"><span>Model</span><select value={selectedAgentModel} onChange={(event) => setSelectedAgentModel(event.target.value)}><option value="gpt-5.6-sol">gpt-5.6-sol</option><option value="gpt-6-astra">gpt-6-astra</option><option value="gpt-5.6-terra">gpt-5.6-terra</option><option value="gpt-5.6-luna">gpt-5.6-luna</option><option value="claude-opus-4-1">claude-opus-4-1</option><option value="claude-sonnet-4">claude-sonnet-4</option></select></label>
        </div>
        <div className="decision-actions"><button className="secondary-button" disabled={!selected || busy || !selected.can_send_message || !can('agent.message')} onClick={() => void switchSelectedModel()}>Send /model</button></div>
      </div>
      <div className="console-section">
        <div className="console-title"><Bot size={17} /><div><strong>Start agent</strong><span>選模型、開一個新的 Herdr pane，必要時直接交付第一句任務。</span></div></div>
        <div className="console-grid">
          <label className="field"><span>Agent</span><select value={newAgentKind} onChange={(event) => setNewAgentKind(event.target.value as 'codex' | 'claude')}><option value="codex">Codex</option><option value="claude">Claude</option></select></label>
          <label className="field"><span>Model</span><select value={newAgentModel} onChange={(event) => setNewAgentModel(event.target.value)}><option value="gpt-6-astra">gpt-6-astra</option><option value="gpt-5.6-terra">gpt-5.6-terra</option><option value="gpt-5.6-luna">gpt-5.6-luna</option><option value="claude-opus-4-1">claude-opus-4-1</option><option value="claude-sonnet-4">claude-sonnet-4</option></select></label>
        </div>
        <label className="field"><span>Initial prompt</span><textarea rows={3} value={newAgentPrompt} onChange={(event) => setNewAgentPrompt(event.target.value)} placeholder="留空也可以，只開 Agent；或直接貼 /goal 任務。" /></label>
        <div className="decision-actions"><button className="primary-button" disabled={busy || !can('agent.start')} onClick={() => void startAgent()}><Play size={15} />啟動 Agent</button></div>
      </div>
      <div className="console-section shell-console">
        <div className="console-title"><Terminal size={17} /><div><strong>Project shell</strong><span>建立獨立 shell pane，不干擾正在跑的 Codex/Claude。</span></div></div>
        {!shellPaneId ? <button className="secondary-button" disabled={shellBusy || !can('shell.create')} onClick={() => void createShell()}><Terminal size={15} />建立 Shell pane</button> : <>
          <div className="shell-pane-label">Pane {shellPaneId}</div>
          {shellError && <div className="inline-error"><AlertCircle size={17} />{shellError}</div>}
          <pre ref={shellRef} className="agent-transcript shell-transcript">{shellTranscript?.content || (shellBusy ? '讀取中…' : '目前沒有 shell 輸出。')}</pre>
          <label className="field"><span>Shell command</span><textarea rows={2} value={shellCommand} onChange={(event) => setShellCommand(event.target.value)} placeholder="例如 npm run test --workspace apps/web" /></label>
          <label className="danger-check"><input type="checkbox" checked={confirmDangerousShell} onChange={(event) => setConfirmDangerousShell(event.target.checked)} />允許這次送出可能危險的指令</label>
          <div className="decision-actions"><button className="primary-button" disabled={!shellCommand.trim() || shellBusy || !can('shell.execute')} onClick={() => void runShell()}><Send size={15} />送出 Shell 指令</button></div>
        </>}
      </div>
    </div>
    <div className="goal-trace"><div className="goal-trace-head"><div><h3>目前偵測到的 Goal 與派工</h3><p>進行中區只保留尚可能活動的派工；完成、失敗、停止與過期項目會自動收到歷史。</p></div><span>{activeDelegations.length} 個可能進行中的子任務</span></div>
      {activeGoals.length === 0 ? <div className="friendly-empty compact-empty"><CircleDot size={22} /><p>目前沒有來源標為 active 的 `/goal`。</p></div> : <div className="goal-list">{activeGoals.slice(0, 3).map((goal) => <article key={`${goal.provider}-${goal.goal_id ?? goal.session_id}`}><div><span>{goal.provider === 'claude' ? 'Claude Goal' : 'Codex Goal'} · {relativeTime(goal.updated_at)}</span><strong>{goal.objective}</strong><small>Session {goal.session_id.slice(0, 8)} · 來源仍標記 active，不代表本機程序一定在執行</small></div><span className="trace-badge trace-live">來源 active · {goal.epoch_verified ? '目標輪次已核對' : '目標輪次未驗證'}</span></article>)}</div>}
      {activeDelegations.length === 0 ? <div className="no-active-delegations"><Check size={16} /><span>目前沒有可辨識為仍在執行的子代理。</span></div> : <div className="delegation-list">{activeDelegations.map((item) => <DelegationCard item={item} key={item.id} />)}</div>}
      {(historicalDelegations.length > 0 || historicalGoals.length > 0) && <details className="trace-history"><summary>歷史：{historicalDelegations.length} 筆派工、{historicalGoals.length} 個已結束 Goal</summary><div className="delegation-list">{historicalDelegations.slice(0, 12).map((item) => <DelegationCard item={item} key={item.id} />)}</div></details>}
      <small className="trace-limitation">{traceLimitation}</small>
    </div>
    {busy && agents.length === 0 ? <div className="friendly-empty"><LoaderCircle className="spin" /><p>正在讀取 Agent…</p></div> : agents.length === 0 ? <div className="friendly-empty"><Bot size={28} /><h3>這個專案目前沒有可辨識的 Agent</h3><p>只有 cwd 位於此專案範圍內的 Herdr session 才會出現在這裡。</p></div> : <div className="agent-list">{agents.map((agent) => <button className={selected?.id === agent.id ? 'agent-row selected' : 'agent-row'} key={agent.id} onClick={() => void openAgent(agent)}><div className="agent-avatar"><Bot size={20} /></div><div><h3>{agent.provider === 'codex' ? 'Codex' : agent.provider === 'claude' ? 'Claude' : agent.provider}<small>最近指派</small></h3><p>{agent.task_summary}</p><small>{agent.workspace_label} · {agent.pane_id}</small></div><span className={`status status-${agent.status === 'working' ? 'in_progress' : agent.status === 'blocked' ? 'blocked' : agent.status === 'done' ? 'verified' : 'unknown'}`}>{agentStatusText[agent.status] ?? agent.status}</span><ChevronRight size={16} /></button>)}</div>}{selected && <article className="agent-detail"><div className="agent-detail-head"><div><span>{selected.workspace_label} · {selected.pane_id}</span><h3>{selected.provider === 'codex' ? 'Codex' : 'Claude'} 對話與最近輸出</h3></div><button className="icon-button" aria-label="關閉 Agent 詳情" onClick={() => { setSelected(null); setTranscript(null) }}><X size={18} /></button></div><div className="agent-request"><span>最近的人類指派</span><p>{selected.latest_human_request ?? selected.task_summary}</p><small>{selected.request_explanation}</small></div><div className="stream-health"><span className={`stream-dot stream-${streamState}`} /><strong>{streamText}</strong>{streamError && <small>{streamError}</small>}</div><div className="transcript-warning"><AlertCircle size={15} />{transcript?.freshness_warning ?? transcript?.limitation ?? '正在取得最近輸出…'}</div><pre ref={transcriptRef} className="agent-transcript" aria-live="polite">{transcript?.content || (busy ? '讀取中…' : '目前沒有可見輸出。')}</pre><label className="field"><span>傳訊息給這個 Agent</span><textarea rows={3} value={message} onChange={(event) => setMessage(event.target.value)} placeholder="補充任務、要求 checkpoint，或回答它的問題……" /></label><div className="decision-actions"><button className="primary-button" disabled={!message.trim() || busy || !selected.can_send_message || !can('agent.message')} onClick={() => void send()}>傳送訊息</button></div></article>}</section>
}

const monitorStatusText: Record<GoalMonitor['status'], string> = {
  armed: '等待／持續巡查', paused: '已暫停', complete: '目標已結束', error: '監控異常',
}

const monitorVerdictText = {
  clean: '方向正常', attention: '需要注意', needs_human: '需要你決定', terminal: '目標已結束', error: '巡查失敗',
}

function MonitorsPage({ projectId }: { projectId: string }) {
  const [monitors, setMonitors] = useState<GoalMonitor[]>([])
  const [agents, setAgents] = useState<AgentSession[]>([])
  const [goals, setGoals] = useState<GoalSessionCandidate[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [agentId, setAgentId] = useState('')
  const [goalId, setGoalId] = useState('')
  const [cadence, setCadence] = useState(60)
  const [showCreate, setShowCreate] = useState(false)
  const [snapshot, setSnapshot] = useState<MonitorSnapshot | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [reconcile, setReconcile] = useState<MonitorReconcileResult | null>(null)
  const selected = monitors.find((item) => item.id === selectedId) ?? monitors[0]
  const selectedAgent = agents.find(item => item.id === agentId)
  const eligibleGoals = goals.filter(item => item.epoch_verified && item.goal_id && item.status === 'active' && item.session_id === selectedAgent?.runtime_session_id && item.provider.toLowerCase() === selectedAgent?.provider.toLowerCase())
  const matchingGoals = eligibleGoals.filter(item => item.goal_id === goalId)
  const boundGoal = matchingGoals.length === 1 ? matchingGoals[0] : null
  const exactBinding = !!boundGoal && agents.filter(item => item.runtime_session_id === boundGoal.session_id).length === 1

  async function load() {
    setBusy(true)
    try {
      const [monitorItems, agentResult, goalResult] = await Promise.all([
        api.monitors(projectId), api.agents(projectId), api.goalSessions(projectId),
      ])
      const codexAgents = agentResult.agents.filter((item) => item.provider.toLowerCase() === 'codex')
      const codexGoals = goalResult.sessions.filter((item) => item.provider.toLowerCase() === 'codex')
      setMonitors(monitorItems); setAgents(codexAgents); setGoals(codexGoals)
      setSelectedId((current) => current || monitorItems[0]?.id || '')
      setAgentId(current => codexAgents.some(item => item.id === current) ? current : '')
      setGoalId(current => codexGoals.some(item => item.goal_id === current && item.epoch_verified) ? current : '')
      setError('')
    } catch (reason) { setError(reason instanceof Error ? reason.message : '無法讀取監工狀態。') }
    finally { setBusy(false) }
  }
  useEffect(() => { void load() }, [projectId])
  useEffect(() => {
    let cancelled = false
    void api.reconcileMonitors(projectId).then(async (result) => {
      if (cancelled) return
      setReconcile(result)
      const refreshed = await api.monitors(projectId)
      if (!cancelled) { setMonitors(refreshed); setSelectedId((current) => current || refreshed[0]?.id || '') }
    }).catch((reason) => { if (!cancelled) setError(reason instanceof Error ? reason.message : '無法自動核對監工。') })
    const timer = window.setInterval(() => {
      void api.monitors(projectId).then((items) => {
        if (!cancelled) setMonitors(items)
      }).catch(() => undefined)
    }, 15_000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [projectId])

  async function createMonitor() {
    if (!exactBinding || !boundGoal?.goal_id) return
    setBusy(true)
    try {
      const created = await api.createMonitor(projectId, {
        agent_id: agentId, goal_session_id: boundGoal.session_id, provider: boundGoal.provider,
        goal_epoch_id: boundGoal.goal_id, cadence_minutes: cadence, notify_only: true,
      })
      setMonitors((items) => [created, ...items]); setSelectedId(created.id); setShowCreate(false); setError('')
    } catch (reason) { setError(reason instanceof Error ? reason.message : '無法建立監工。') }
    finally { setBusy(false) }
  }

  async function capture() {
    if (!selected?.identity_verified || !selected.goal_epoch_id) return
    setBusy(true); setSnapshot(null)
    try { setSnapshot(await api.monitorSnapshot(projectId, selected.id)); setError('') }
    catch (reason) { setError(reason instanceof Error ? reason.message : '無法擷取巡查證據。') }
    finally { setBusy(false) }
  }

  async function pause() {
    if (!selected) return
    setBusy(true)
    try {
      const updated = await api.pauseMonitor(projectId, selected.id)
      setMonitors((items) => items.map((item) => item.id === updated.id ? updated : item)); setError('')
    } catch (reason) { setError(reason instanceof Error ? reason.message : '無法暫停監工。') }
    finally { setBusy(false) }
  }

  return (
    <section className="content-panel monitors-panel">
      <div className="section-heading"><div><h2>獨立監工</h2><p>Claude 只讀檢查 Codex 是否仍朝成果前進；第一版只通知，不會自行改程式或傳話。</p></div><button className="primary-button" onClick={() => setShowCreate(true)}><Plus size={17} />綁定 `/goal`</button></div>
      {error && <div className="inline-error"><AlertCircle size={17} />{error}</div>}
      <div className="monitor-safety"><ShieldCheck size={18} /><div><strong>Notify-only pilot</strong><span>建立紀錄不等於 Claude 排程已啟動。啟動後每次巡查都必須留下證據與 verdict。</span></div></div>
      {reconcile && <div className="connector-note"><RefreshCw size={17} /><div><strong>自動核對已啟用</strong><span>{reconcile.explanation}{reconcile.rearmed_monitor_ids.length > 0 ? ` 已恢復 ${reconcile.rearmed_monitor_ids.join('、')}。` : ''}{reconcile.pending_agent_ids.length > 0 ? ` 等待配對：${reconcile.pending_agent_ids.join('、')}。` : ''}</span></div></div>}
      {showCreate && <div className="decision-create monitor-create">
        <label className="field"><span>正在工作的 Codex pane</span><select value={agentId} onChange={(event) => { setAgentId(event.target.value); setGoalId('') }}><option value="">請選擇</option>{agents.map((item) => <option value={item.id} key={item.id} disabled={!item.runtime_session_id}>{item.pane_id} · {item.task_summary}{!item.runtime_session_id ? '（缺少執行身分）' : ''}</option>)}</select></label>
        <label className="field"><span>已核對的 Codex 目標輪次</span><select value={goalId} onChange={(event) => setGoalId(event.target.value)}><option value="">請選擇</option>{eligibleGoals.map((item) => <option value={item.goal_id!} key={`${item.session_id}:${item.goal_id}`}>{item.objective.slice(0, 80)} · {item.session_id.slice(0, 8)}</option>)}</select></label>
        {!exactBinding && <p>必須由 Herdr 提供執行身分，並與已確認的目標輪次唯一對應；目前不以目錄或最近活動推測配對。</p>}
        <label className="field"><span>巡查間隔</span><select value={cadence} onChange={(event) => setCadence(Number(event.target.value))}><option value={30}>30 分鐘</option><option value={60}>1 小時</option><option value={120}>2 小時</option></select></label>
        <div><button className="text-button" onClick={() => setShowCreate(false)}>取消</button><button className="primary-button" disabled={!exactBinding || busy} onClick={() => void createMonitor()}>建立唯讀監工</button></div>
      </div>}
      {busy && monitors.length === 0 ? <div className="friendly-empty"><LoaderCircle className="spin" /><p>正在核對 Herdr 與 Codex goal…</p></div> : monitors.length === 0 ? <div className="friendly-empty"><Activity size={28} /><h3>還沒有監工</h3><p>先讓 Codex 啟動一個有明確完成條件的 `/goal`，再把它與正確 pane 綁在一起。</p></div> : (
        <div className="monitor-layout">
          <div className="monitor-list">{monitors.map((item) => <button className={item.id === selected?.id ? 'active' : ''} key={item.id} onClick={() => { setSelectedId(item.id); setSnapshot(null) }}><span>{item.id} · {monitorStatusText[item.status]}</span><strong>{item.objective}</strong><small>{item.agent_id} · 每 {item.cadence_minutes} 分鐘</small></button>)}</div>
          {selected && <article className="monitor-detail">
            <div className="decision-detail-head"><div><span>{selected.id} · {selected.goal_session_id}</span><h3>{selected.objective}</h3></div><span className={`decision-state monitor-${selected.status}`}>{monitorStatusText[selected.status]}</span></div>
            <div className="monitor-facts"><div><span>目標 Agent</span><strong>{selected.agent_id}</strong></div><div><span>模式</span><strong>只通知，不自動傳話</strong></div><div><span>最近巡查</span><strong>{selected.last_checked_at ? relativeTime(selected.last_checked_at) : '尚未收到 Claude 巡查'}</strong></div></div>
            <div className="monitor-command"><span>交給獨立 Claude pane</span><code>/monitor-agent-goal-herdr {projectId} {selected.id}</code><small>接著用 Claude `/loop` 依上方間隔重複執行；Control Center 不會假裝已替你啟動排程。</small></div>
            <p>{selected.identity_verified ? '已核對目標身分與輪次' : '歷史身分未驗證，暫不擷取其他 runtime 的證據。'}</p>
            <details><summary>查看目標身分證據</summary><p>{selected.provider} · {selected.goal_epoch_id ?? '未確認輪次'}</p><ul>{(selected.identity_evidence ?? []).map((value, index) => <li key={index}>{value}</li>)}</ul></details>
            <div className="decision-actions"><button className="secondary-button" disabled={busy || !selected.identity_verified || !selected.goal_epoch_id} onClick={() => void capture()}><RefreshCw className={busy ? 'spin' : ''} size={15} />立即擷取證據</button>{selected.status === 'armed' && <button className="secondary-button" disabled={busy} onClick={() => void pause()}><Pause size={15} />暫停</button>}</div>
            {snapshot && <div className="monitor-snapshot"><h4>剛剛擷取到的證據</h4><p>Codex：{snapshot.agent_status} · Goal：{snapshot.goal_status} · Git：{snapshot.git_head?.slice(0, 10) ?? '未知'}</p><small>{snapshot.terminal_limitation}</small><details><summary>查看 Git 與最近輸出</summary><pre>{[...snapshot.git_status, ...snapshot.git_diff_stat, '', snapshot.terminal_excerpt].join('\n')}</pre></details></div>}
            <div className="monitor-events"><h4>巡查紀錄</h4>{selected.events.length === 0 ? <p>尚未收到 Claude 的語意巡查。活動狀態不會自動算成產品進度。</p> : selected.events.map((event) => <div className={`monitor-event verdict-${event.verdict}`} key={event.id}><div><strong>{monitorVerdictText[event.verdict]}</strong><span>{relativeTime(event.created_at)} · 信心 {event.confidence}</span></div><p>{event.summary}</p>{event.recommendation && <small>建議：{event.recommendation}</small>}{event.decision_id && <span className="decision-link">已建立 {event.decision_id}</span>}</div>)}</div>
          </article>}
        </div>
      )}
    </section>
  )
}

function EvidencePage({ project }: { project: ProjectDetail }) {
  return <section className="content-panel"><div className="section-heading"><div><h2>系統理解專案所使用的來源</h2><p>這些是文件來源，不等於成果已驗證；真正的測試、PR 與人工驗收會另外列出。</p></div><span className="view-chip">{project.documents.length} 個來源</span></div><div className="evidence-list">{project.documents.map((document) => <article key={document.path}><div className="evidence-icon"><FileText size={18} /></div><div><span>{document.explanation}</span><h3>{document.title}</h3><p>{document.path}</p></div><span className="status status-unknown">文件來源</span></article>)}</div>{project.documents.length === 0 && <div className="friendly-empty"><FileText size={28} /><h3>尚未找到文件來源</h3><p>重新讀取專案，或在 repo 補上 README、PRD、Roadmap 或 Agent 規則。</p></div>}</section>
}

function ProjectPage({ project, onBack, onImport, onUpdate, notificationTarget }: {
  project: ProjectDetail
  onBack: () => void
  onImport: () => void
  onUpdate: (project: ProjectDetail) => void
  notificationTarget?: NotificationTarget | null
}) {
  type ProjectSection = 'plan' | 'work' | 'decisions' | 'agents' | 'monitors' | 'evidence'
  const [activeSection, setActiveSection] = useState<ProjectSection>('plan')
  useEffect(() => {
    if (notificationTarget?.project_id === project.id) setActiveSection(notificationTarget.view === 'overview' ? 'plan' : notificationTarget.view)
  }, [notificationTarget, project.id])
  const [actionBusy, setActionBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const sectionCopy: Record<ProjectSection, { label: string; explanation: string }> = {
    plan: { label: '產品計畫', explanation: '從最上層結果一路展開，理解為什麼要做、現在卡在哪裡，以及哪些完成條件真的有證據。' },
    work: { label: '工作', explanation: '查看 Roadmap 中的具體成果、完成條件與驗證缺口；活動本身不會自動變成進度。' },
    decisions: { label: '決策', explanation: '集中處理需要人與 Agent 說清楚的問題；你可以追問，也可以直接寫下自己的答案。' },
    agents: { label: 'Agents', explanation: '查看 Codex、Claude 與 Herdr 的可靠連線狀態；沒有 adapter 時不會假裝正在工作。' },
    monitors: { label: '監工', explanation: '把長時間 Codex 目標交給獨立 Claude 定期查核；只有成果證據增加才算真的前進。' },
    evidence: { label: '證據', explanation: '查看系統理解專案使用了哪些來源，並區分「文件來源」和真正的驗證證據。' },
  }

  async function runPlanAction(action: 'confirm' | 'refresh') {
    setActionBusy(true)
    setActionError('')
    try {
      onUpdate(action === 'confirm' ? await api.confirmPlan(project.id) : await api.refreshPlan(project.id))
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : '無法更新產品計畫。')
    } finally {
      setActionBusy(false)
    }
  }

  return (
    <div className="project-layout">
      <aside className="sidebar">
        <button className="brand" onClick={onBack}><div className="brand-mark"><Network size={19} /></div><div><strong>Control Center</strong><span>Local workspace</span></div></button>
        <button className="project-switcher" onClick={onBack}><div><small>目前專案</small><strong>{project.name}</strong></div><ChevronDown size={17} /></button>
        <nav>
          <button className={activeSection === 'plan' ? 'active' : ''} onClick={() => setActiveSection('plan')}><LayoutDashboard size={18} />產品計畫</button>
          <button className={activeSection === 'work' ? 'active' : ''} onClick={() => setActiveSection('work')}><Box size={18} />工作</button>
          <button className={activeSection === 'decisions' ? 'active' : ''} onClick={() => setActiveSection('decisions')}><CircleDot size={18} />決策</button>
          <button className={activeSection === 'agents' ? 'active' : ''} onClick={() => setActiveSection('agents')}><Bot size={18} />Agents</button>
          <button className={activeSection === 'monitors' ? 'active' : ''} onClick={() => setActiveSection('monitors')}><Activity size={18} />監工</button>
          <button className={activeSection === 'evidence' ? 'active' : ''} onClick={() => setActiveSection('evidence')}><ShieldCheck size={18} />證據</button>
        </nav>
        <div className="sidebar-bottom"><div className="source-health"><span className="health-dot" /><div><strong>本機來源</strong><small>唯讀連接</small></div></div><button className="secondary-button compact" onClick={onImport}><Plus size={16} />加入專案</button></div>
      </aside>
      <main className="project-main">
        <header className="context-bar"><div className="breadcrumbs"><button onClick={onBack}>所有專案</button><ChevronRight size={14} /><span>{project.name}</span></div><div className="context-actions"><span>更新於 {relativeTime(project.updated_at)}</span><button className="icon-button" aria-label="重新讀取產品計畫" onClick={() => void runPlanAction('refresh')} disabled={actionBusy}><RefreshCw className={actionBusy ? 'spin' : ''} size={17} /></button></div></header>
        <div className="project-content">
          <section className="project-hero">
            <div><div className="eyebrow">{sectionCopy[activeSection].label}</div><h1>{project.name}</h1><p>{project.purpose}</p></div>
            <div className={`hero-health health-${project.health}`}><span>{stateText[project.health]}</span><strong>{project.health_explanation}</strong></div>
          </section>
          <div className="plain-language-callout"><Sparkles size={18} /><div><strong>這頁看什麼？</strong><span>{sectionCopy[activeSection].explanation}</span></div></div>
          {activeSection === 'plan' && project.plan_status === 'draft' && (
            <section className="plan-review-banner">
              <div><strong>這是一份等待確認的產品計畫草稿</strong><span>系統已從 Roadmap 整理出階段與成果，但沒有把文件中的完成宣稱當成驗證證據。請先看過樹狀結構是否合理。</span></div>
              <button className="primary-button" disabled={actionBusy} onClick={() => void runPlanAction('confirm')}>{actionBusy ? <LoaderCircle className="spin" size={18} /> : <Check size={18} />}確認這份計畫</button>
            </section>
          )}
          {activeSection === 'plan' && project.plan_status === 'confirmed' && (
            <section className="plan-confirmed-banner"><ShieldCheck size={19} /><div><strong>產品計畫已確認</strong><span>確認的是計畫結構；每項成果仍要有測試、PR 或人工驗收才能算完成。</span></div></section>
          )}
          {activeSection === 'plan' && project.plan_status === 'needs_source' && (
            <section className="plan-review-banner needs-source"><div><strong>還沒有可建立成果樹的 Roadmap</strong><span>產品基本說明已確認，但系統沒有找到 ROADMAP.md 或已知的產品完成計畫。</span></div><button className="secondary-button" disabled={actionBusy} onClick={() => void runPlanAction('refresh')}><RefreshCw size={17} />重新讀取</button></section>
          )}
          {activeSection === 'plan' && actionError && <div className="inline-error"><AlertCircle size={17} />{actionError}</div>}
          {activeSection === 'plan' && <>
            <section className="plan-panel">
              <div className="section-heading"><div><h2>可展開的成果樹</h2><p>活動不會自動變成產品進度。</p></div><span className="view-chip"><Network size={15} />樹狀檢視</span></div>
              {project.plan.map((node) => <OutcomeTree key={node.id} root={node} />)}
            </section>
            <section className="source-panel">
              <div className="section-heading"><div><h2>系統目前讀到的來源</h2><p>這些是理解專案的入口，不代表每份內容都已核准。</p></div></div>
              <div className="source-facts"><div><span>本機位置</span><strong>{project.facts?.root_path}</strong></div><div><span>目前分支</span><strong>{project.facts?.current_branch ?? '無法判斷'}</strong></div><div><span>技術</span><strong>{project.facts?.languages.join('、') || '尚未辨識'}</strong></div></div>
            </section>
          </>}
          {activeSection === 'work' && <WorkPage project={project} onVerified={() => { void api.project(project.id).then(onUpdate).catch(() => setActionError('驗收已儲存，但專案狀態尚未重新讀取。')) }} targetId={notificationTarget?.view === 'work' ? notificationTarget.entity_id : null} />}
          {activeSection === 'decisions' && <DecisionsPage projectId={project.id} targetId={notificationTarget?.view === 'decisions' ? notificationTarget.entity_id : null} />}
          {activeSection === 'agents' && <AgentsPage projectId={project.id} targetId={notificationTarget?.view === 'agents' ? notificationTarget.entity_id : null} />}
          {activeSection === 'monitors' && <MonitorsPage projectId={project.id} />}
          {activeSection === 'evidence' && <EvidencePage project={project} />}
        </div>
      </main>
    </div>
  )
}

export function App() {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null)
  const [project, setProject] = useState<ProjectDetail | null>(null)
  const [showImport, setShowImport] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notificationTarget, setNotificationTarget] = useState<NotificationTarget | null>(null)

  async function loadPortfolio() {
    setLoading(true)
    try {
      setPortfolio(await api.portfolio())
      setError('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '無法連接本機服務。')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void loadPortfolio() }, [])
  const projects = useMemo(() => portfolio?.projects ?? [], [portfolio])

  async function openProject(id: string) {
    setNotificationTarget(null)
    try { setProject(await api.project(id)) } catch (reason) { setError(reason instanceof Error ? reason.message : '找不到專案。') }
  }

  if (loading) return <div className="app-loading"><LoaderCircle className="spin" /><span>正在讀取工作區…</span></div>
  if (error && !portfolio) return <div className="app-error"><AlertCircle /><h1>無法開啟 Control Center</h1><p>{error}</p><button className="primary-button" onClick={loadPortfolio}>再試一次</button></div>

  return (
    <>
      <NotificationCenter projects={projects} onNavigate={target => {
        if (!target.project_id) { setProject(null); setNotificationTarget(null); return }
        void api.project(target.project_id).then(value => { setProject(value); setNotificationTarget({ ...target }) }).catch(() => setError('通知指向的專案已移除或你沒有存取權限。'))
      }} />
      {error && portfolio && <div role="alert" className="inline-error">{error}</div>}
      {project ? <ProjectPage key={project.id} project={project} notificationTarget={notificationTarget} onBack={() => { setProject(null); void loadPortfolio() }} onImport={() => setShowImport(true)} onUpdate={setProject} /> : <PortfolioPage portfolio={portfolio!} onImport={() => setShowImport(true)} onOpen={openProject} />}
      {showImport && <ImportWizard projects={projects} onClose={() => setShowImport(false)} onComplete={(created) => { setShowImport(false); setProject(created); void loadPortfolio() }} />}
    </>
  )
}

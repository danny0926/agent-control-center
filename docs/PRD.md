# Agent Development Control Center — PRD

狀態：`proposed`\
產品 owner：Workspace owner\
執行 owner：主 AGENT\
最後更新：2026-09-15

目前 MVP-A 擴充處於實作／整合驗證：單機通知、安全執行預設及 owner-attested 驗收的已接線契約見 [API_CONTRACT.md](API_CONTRACT.md)。本文其餘需求仍是產品目標，不代表皆已實作；fleet、額度派工與 Web Push 尚未交付。

通知必須區分 Agent 本輪結束、Agent 回報 goal 完成、等待人類決策與成果驗收。`work.verified` 目前只來自擁有者對已確認計畫最末層成果的逐條 attestation：必要 acceptance 與預先保存的 gates 完整、版本乾淨且一致、來源綁定及檔案 hash 可核對、期限有效。服務不代執行測試，來源固定 `owner_attested`；上層節點不直接套用下層完成。scope、policy、來源、版本、證據或期限失效時保留紀錄並發一次更正通知。

## 1. 產品摘要

Agent Development Control Center（以下簡稱 Control Center）是一個獨立、本機優先的多專案產品工程
控制面。它將每個專案散落於 PRD、Roadmap、Agent 規則、Git branch/worktree、GitHub、測試輸出與
Agent runtime 的狀態，整理成可供人和 Agent 共用的產品地圖與決策收件匣。

核心承諾：

> 讓 Agent 自主推進可由既有證據決定的工作；只有遇到不可推導且影響重大的問題才開卡問人，並讓人
> 隨時知道產品目標、實際進度、證據缺口、風險與下一步。

它不是任何來源專案的子功能。合成示例專案 是第一個驗證匯入、計畫理解與 Agent 交接的 fixture；核心資料
模型不得依賴任何來源產品的領域語意。第一版服務單一 workspace、多個本機 repo、階層式子專案與少量本機 Agent。

## 2. 問題

許多專案已有代理治理，但狀態通常散落在 Markdown、terminal、Git 與不同外部服務中：

- 人必須逐一查看文件、pane、branch、測試和 diff 才知道整體進度。
- Herdr 能顯示 Agent 是否工作或阻塞，卻沒有結構化問題、選項、回答期限與決策歷史。
- Issue 可以記錄工作，但單張 Issue 無法自然回答產品為何做、里程碑是否真的達成。
- 「程式完成」「測試通過」「產品已驗證」「已 release」容易被混成同一種完成。
- Agent 的合理推測、已確認決策與真人驗證若沒有分級，會把假說包裝成產品事實。

## 3. 目標與非目標

### 3.1 目標

1. 一個畫面看懂產品目標、里程碑、實作進度、驗證進度、阻塞與 release 信心。
2. Agent 只為符合升級政策的事項建立 Decision Card；人能在卡片上回答並恢復原工作。
3. 每個完成宣稱都能連到 PR、測試、實驗、人工驗收或部署事件。
4. GitHub/repo 保持長期真實來源；Herdr 保持本機 Agent 執行與即時狀態來源。
5. 降低 owner 找狀態、重複回答與事後返工所花時間，且不提高漏問重大決策的比例。
6. 讓使用者能以唯讀方式匯入現有 repo，先確認系統理解，再加入工作區。
7. 讓多個專案與任意層子專案共享管理介面，但保持來源、權限、Agent 與證據隔離。

### 3.2 非目標

- 不重做通用 Jira、Linear 或 GitHub。
- 不把 terminal 完整串流當成主要產品介面。
- 不讓 Agent 以投票決定品牌、隱私、付費服務或產品真相。
- 不在 MVP 自動執行 production deploy、不可逆資料變更、force-push 或付費服務開通。
- 不以 Issue/PR 數、token 使用量或 Agent 忙碌時間代表產品價值。
- 不把 Control Center 放進任何來源產品的使用者導覽或領域資料模型。
- 不在匯入時自動修改來源 repo、建立 Issue、推送 branch 或啟動 Agent。

## 4. 使用者與核心工作

### 4.1 主要使用者

- **產品 owner**：看方向、回答少數重大問題、核准 release。
- **主 AGENT**：維護計畫、拆工作、套用治理、彙整狀態與證據。
- **執行 Agent**：取得有界工作、回報結構化狀態、提出 Decision Card。
- **Reviewer／QA**：檢查 diff、測試、反例、未跑驗證與剩餘風險。

### 4.2 Jobs to be done

- 當我打開系統時，我想在一分鐘內知道產品目前在哪裡、是否偏離目標，以及我現在需要做什麼。
- 當 Agent 無法繼續時，我想看到建議答案、其他選項與影響，不必重新閱讀整段對話。
- 當某項工作顯示完成時，我想知道完成的是實作、驗證還是 release，以及證據在哪裡。
- 當我回答過偏好或產品取捨後，我想讓後續 Agent 引用它，但仍能查看、撤回或取代。

## 5. 產品原則

1. **目標先於工作**：每個 Work Item 必須連到 Milestone 或明確標為 maintenance/unplanned。
2. **證據先於完成**：狀態不能只靠 Agent 自述跳到 `VERIFIED` 或 `SHIPPED`。
3. **不知道就說不知道**：未知、未跑、過期、失敗與部分完成必須分開呈現。
4. **少問但不漏問**：先搜尋權威來源；低風險可逆事項採預設並記錄，高影響事項才阻塞。
5. **單一真實來源**：計畫與長期紀錄以 repo/GitHub 為準；Control Center 可快取但不能形成第二份真相。
6. **人在高風險迴路中**：品牌、隱私、付費、不可逆變更、產品語意衝突與 production release 由人決定。
7. **Agent 不共寫高耦合範圍**：延續現有 worktree、明確讀寫範圍與單一 owner 規則。

## 6. Workspace、專案匯入與專案模型

### 6.1 層級

```text
Workspace
├─ Project
│  ├─ Subproject（仍是 Project，以 parent_project_id 表示）
│  ├─ Sources
│  ├─ Product Plan
│  ├─ Work／Decisions／Agents
│  └─ Evidence／Releases
└─ Project
```

每個 Project 可以連接獨立 repo，也可以用 `root_path` 指向 monorepo 內的一段範圍。專案各自保存來源、
權限、Agent 規則、測試入口、Decision authority、evidence freshness 與 release gates。未經明確指派，
Agent 不得跨專案讀取內容或套用另一個專案的規則。

### 6.2 匯入流程

```text
選擇本機 repo／GitHub／空白產品
              ↓
          唯讀掃描
              ↓
   產品理解草稿＋依據＋缺口＋衝突
              ↓
          人類確認
              ↓
     加入 Workspace 並建立成果樹
```

MVP 先支援本機 Git repo。掃描只讀取已知產品文件、Agent 規則、package metadata 與 Git facts；確認加入
只寫入 Control Center 自己的 local store。GitHub 與來源 repo 的寫入權限必須在後續分別開啟並留下
audit record。

### 6.3 產品成果結構

Control Center 使用四層計畫結構：

```text
Goal：希望改變的產品結果
└─ Milestone：可驗收的階段成果
   └─ Epic：一組有共同交付結果的工作
      └─ Work Item：Task／Bug／Research／Decision／Risk
```

以下完全合成的「示例任務板」只用於測試與說明，不對應任何真實客戶、內部 repo 或產品計畫：

- Goal：讓使用者可靠地建立與追蹤示例任務。
- Milestone：M0 登入、M1 任務匯入、M2 錯誤處理。
- Epic：登入表單、匯入預覽、重複資料提示、失敗重試與基本可及性。
- Work Item：每個可獨立驗收的小修改、測試或文件工作。

## 7. 進度語意

### 7.1 不使用單一模糊百分比

首頁至少分開呈現：

- **Scope progress**：已完成工作量／目前確認範圍工作量。
- **Verification progress**：已有必要證據的工作量／需驗證工作量。
- **Milestone confidence**：`on_track | at_risk | off_track | unknown`，附理由與更新時間。
- **Decision blockers**：正在等待人的高影響問題數與最舊等待時間。
- **Release readiness**：必要 gate 通過數、未通過數、未執行數。

工作量以 `effort` 欄位彙整；沒有估算時顯示「未估算」，不能偷偷按卡片數補算。新增 scope 時，burn-up
總量應上升，不能製造進度倒退或完成率被灌水的假象。

### 7.2 完成層級

```text
BACKLOG → READY → WORKING → REVIEW → VERIFYING → DONE
                         ↘ NEEDS_DECISION
                         ↘ BLOCKED
```

- `DONE`：該 Work Item 的 Definition of Done 已滿足。
- `VERIFIED`：屬於 evidence/gate 結果，不是一般工作狀態；必須有 Verification Record。
- `SHIPPED`：必須由 merge/deployment/release event 證明。
- `CANCELED/REFUTED/ARCHIVED`：保留原因，不計入已完成價值。

## 8. 功能需求

### FR-1 產品總覽

系統必須顯示目前 Goal、Active Milestone、最近狀態更新、五項進度指標、前三個風險、下一個交付點與
待 owner 動作。任何指標都要能 drill down 到構成它的卡片與證據。所有頁面必須先以一般人可理解的
一句話說明「這頁回答什麼」與「現在需要做什麼」；技術 ID、內部狀態、branch、gate 與原始證據放在
第二層，不得用工程術語取代產品敘述。

### FR-2 計畫與 Roadmap

系統必須以 Goal → Milestone → Epic → Work Item 顯示階層、相依、目標日期、owner、health 與驗收條件。
遠期工作可只有 Goal/Epic；只有進入 `READY` 的工作才要求完整 scope、owner 與驗證方式。

預設畫面是可折疊的產品計畫，不是靜態流程圖。每一層先顯示使用者看得懂的結果敘述，例如「讓前端
與後端使用相同資料格式」，再把「API 契約機械化」等工程名稱作為次要標籤。Archify 可從相同資料
產生架構或交付流程說明，但不作為計畫編輯、狀態追蹤或進度計算的主要 UI。

### FR-3 工作管理

Work Item 必須包含 type、status、priority、effort、area、owner、parent、dependencies、read/write scope、
acceptance criteria、verification tier、branch/worktree、PR 與 retirement condition。未規劃工作可進入
intake，但不可無聲混入 active milestone。

### FR-4 Decision Inbox

Agent 提問前必須附上：

- 無法由哪些權威來源推導，以及已查過哪些地方。
- 一句話問題、影響、可逆性、阻塞範圍與最晚回答時間。
- 建議預設及理由；最多三個互斥選項與各自代價。
- 相關 prototype、畫面、diff、證據與衝突決策。
- 若不回答：安全預設、暫停或到期策略。

人可選擇、編輯答案、要求補證、延後、拒絕問題或標記「其實已有答案」。Decision Card 必須提供限定在
該問題範圍內的文字討論串：人可追問 Agent、指出答案不滿意、要求比較或補充證據，也可輸入選項以外
的自訂答案。一般訊息與「送出正式決策」是兩個不同操作；追問只把狀態改為 `WAITING_AGENT`，不會
結案或恢復工作。Agent 補充後回到 `WAITING_HUMAN`，且舊建議、選項與證據版本仍可查看。

自訂答案在正式提交前，系統先整理成 statement、scope、受影響工作與不受影響項目供人預覽；只有人按
「確認為決策」才形成 versioned Decision Record 並通知主 AGENT。恢復執行前由 policy 檢查 authority、
答案 scope 與工作是否仍有效。

### FR-5 Agent 與工作執行

顯示 Herdr workspace/pane、Agent/模型、所屬工作、即時狀態、開始時間、最後活動、token/cost（若可得）、
query budget、branch/worktree 與目前 gate。`blocked` 只代表執行觀測，不能自動等同 `NEEDS_DECISION`。
結構化 Decision Card 必須由 Agent 或 wrapper 明確建立。

系統必須將 Agent goal 與派工執行分開建模。Claude、Codex 的 `/goal` 以 provider + session + goal epoch
辨識；父 goal 不視為自動傳給 child。每次派工顯示要求模型、啟動模型、runtime 實際模型、child session／
Herdr pane、Goal 掛載證據與 lifecycle。只能看到背景 shell 啟動而沒有 child identity 時，必須顯示
`untracked_runtime` 與「已啟動，狀態未知」，不能顯示為已驗證執行中。

主 Agent 與各執行 Agent 都必須能開啟對話詳情，且 Claude、Codex 使用相同介面。對話詳情預設顯示經
adapter 正規化的 human/agent 訊息、結構化 checkpoint、decision 與工具摘要；冗長工具輸出和 terminal
控制字元預設折疊。使用者可傳送訊息、要求 checkpoint、前往關聯工作，並以「開啟原始 terminal」
切換到精確的 Herdr pane。瀏覽器不得直接控制 terminal；所有 read/send/focus 操作經本機 backend bridge、
pane identity 驗證、secret redaction 與 audit。adapter 無法可靠取得歷史時要明示 `partial`，不可補寫或
假裝成完整對話。

### FR-6 Evidence 與驗證

每項 claim 或 gate 可連到 Evidence Record：來源、產生時間、revision/hash、PIT/授權（若適用）、實際命令、
結果、未跑項目、scope 與失效條件。測試須依 `AGENTS.md` 分為 unit/component/contract/browser/external/
slow/serial，UI 不得把 fast suite 顯示成 full suite。

### FR-7 Release Center

每個 release candidate 顯示變更目的、包含 Work Items、diff/PR、已跑與未跑驗證、資料或 UI 風險、rollback、
決策依據與 gate 結果。MVP 的 merge/deploy 核准必須由人觸發；按鈕前必須顯示副作用與目標環境。

### FR-8 活動與稽核

保存 append-only 事件：誰在何時建立/改變什麼、使用哪個 policy 版本、從哪個狀態到哪個狀態、引用哪些
證據。對覆寫、撤回、過期與 supersede 必須保留前值。

### FR-9 搜尋、篩選與 stale 提示

可依 milestone、area、owner、type、status、risk、branch 與 evidence state 搜尋。超過設定時間未更新的
Agent、Project Update、Decision 或驗證結果必須標示 stale，不能延續綠色狀態。

### FR-10 Codex `/goal` 獨立監工

owner 可把一個 Project 內的 Herdr Codex pane 與同一路徑的 Codex `/goal` session 明確配對，建立 notify-only monitor。Control Center 每次只提供有界的 goal、terminal 與 Git snapshot；獨立 Claude 依產品文件與驗收證據判斷 `clean`、`attention`、`needs_human`、`terminal` 或 `error`。

`needs_human` 必須建立可對話的 Decision Card，說明問題、證據與建議；相同發現重複巡查時沿用既有 card。Pilot 不允許 monitor 自動向工作中的 Agent 傳訊或修改專案。UI 必須清楚區分「已登記監工」與「Claude 週期排程確實運作中」，不得把前者冒充後者。

後端 Reconciler 定期核對現存 monitor：同一個已確認的 pane＋goal session 在 terminal verdict 後又出現較新的 active goal update 時，自動恢復為 armed 並留下事件。新 pane 只有在 Herdr／launcher 回報精確 `agent_session_id` 時才能自動建立 monitor；否則列為等待配對，不以 cwd 或時間接近猜測。

## 9. 最小資料契約

第一版至少需要以下實體；詳細 schema 在實作階段版本化定義，不修改任何來源產品的 domain schema：

| 實體 | 核心內容 | 權威來源 |
| --- | --- | --- |
| Goal/Milestone/Epic | outcome、acceptance、owner、health、dates | repo/GitHub Project |
| WorkItem | scope、owner、status、DoD、dependency、PR | GitHub Issue/Project |
| DecisionCard | question、options、recommendation、impact、deadline | GitHub Issue + audit record |
| DecisionRecord | answer、authority、scope、status、supersedes | versioned repo record |
| AgentRun | Herdr pane、work item、branch、activity、budget | Herdr/runtime cache |
| EvidenceRecord | kind、source、command、result、scope、freshness | repo/CI/artifact metadata |
| GateDecision | policy、inputs、result、approver、side effects | append-only audit |
| StatusUpdate | health、summary、changes、risks、next | GitHub Project/repo record |

## 10. 整合與系統邊界

### 10.1 GitHub／repo

- 長期計畫、Work Item、Decision Card、PR 與 audit link 的真實來源。
- Control Center 透過 GitHub API/CLI 讀寫，不直接重新實作 Git operation。
- 本機 cache 可提高速度，但須顯示最後同步時間與 sync failure。

### 10.2 Herdr

- 提供 workspace、pane、Agent 狀態、focus/prompt/notification 等本機能力。
- 不把 terminal scraping 當穩定契約；結構化狀態由 wrapper/CLI 主動送出。
- Herdr 失聯時，Project/Decision/Evidence 仍可讀；Agent 即時狀態顯示 unknown。

### 10.3 來源專案 adapter

- 核心只依賴公開、通用的 adapter 契約，不直接匯入來源產品的 server 或 domain schema。
- 只讀取使用者授權的產品文件及工程證據；業務資料、個資、登入資料與私密內容不因加入專案而自動分享。
- 公開測試使用暫存 repo 與合成紀錄，不複製實際產品的資料、路徑或 session identity。

## 11. 權限與安全

- 預設 local single-user；遠端共享另立隱私與權限決策。
- GitHub token、Agent provider token、登入資料不可寫入 card、log 或 screenshot。
- 任何可變更 Git、啟動 Agent、執行測試、合併或部署的操作都要顯示 actor、scope 與結果。
- Production、副作用高或不可逆操作預設要求人類核准並二次確認。
- Decision 回答必須驗證 authority；Agent 不能冒充 owner 確認自己的提案。

## 12. MVP 使用旅程

1. Control Center 讀取合成示例任務板的產品計畫，建立 M0/M1/M2 的可瀏覽階層。
2. owner 打開 Overview，看到 active milestone、實作/驗證差距與一張待決策卡。
3. owner 開啟 Decision Card，比較 Agent 建議與兩個替代方案，要求補證或回答。
4. 回答寫入 Decision Record，相關 Work Item 恢復為 `READY/WORKING`，原 Herdr pane 收到通知。
5. Agent 完成工作並附 PR、測試和未跑驗證；卡片進入 `REVIEW/VERIFYING`，不直接宣稱 release。
6. gate 通過後 Release Center 顯示變更、風險與 rollback；owner 核准後才觸發後續 merge/deploy 流程。

## 13. MVP 驗收條件

1. 可從同一入口查看 Goal、Milestone、Epic、Work Item 的階層與來源連結。
2. Overview 的每個進度數字可追溯到工作量、狀態與證據，不以未估算卡片猜百分比。
3. Agent 能建立一張符合 FR-4 的 Decision Card；人回答後形成不可覆蓋歷史並可通知原工作。
4. Herdr Agent 的 working/idle/blocked/done/unknown 與產品 `NEEDS_DECISION` 清楚分離。
5. 工作不能在缺少指定 verification bundle 時顯示為 verified；未跑類別清楚列出。
6. 可完整演示：計畫 → Agent 工作 → 人工決策 → 恢復 → PR/證據 → release candidate。
7. GitHub、Herdr 或 CI 任一來源失聯時，UI 顯示最後同步時間、缺口和可用的降級內容。
8. 所有高副作用操作有權限、scope、確認與 audit event。
9. 點擊主 Agent、Claude 或 Codex 可開啟一致的對話介面、傳送 Demo/真實訊息或聚焦原始 Herdr pane；
   transcript 不完整時清楚標示缺口。
10. 所有主要頁面都有一般人可理解的目的、現況和下一步；只看第一層文案即可做產品判斷，不必理解
    `gate`、`effort`、branch 或 API 名稱。

## 14. 衡量指標

- owner 每日理解整體狀態所需時間。
- 每個 accepted increment 的人工分鐘與問題數。
- avoidable question rate、decision yield、missed-decision rate。
- build 後 requirement churn。
- 沒有足夠證據卻顯示完成的 false-complete rate（目標為 0）。
- decision 回答後成功恢復工作的比例與時間。
- stale/unknown 狀態被錯顯示為正常的比例（目標為 0）。

## 15. 交付階段

### Phase 0：契約與唯讀總覽

- 定義資料 schema、adapter boundary 與 sample dataset。
- 只讀取 repo/GitHub/Herdr，完成 Overview、Plan、Decisions、Agents、Release 五個畫面原型。
- 用完全合成的 M0/M1/M2 工作回放，驗證資訊是否足以讓 owner 判斷下一步。

### Phase 1：Decision loop

- 建立 Decision Card、回答、versioned Decision Record、通知與 resume handoff。
- 先不自動執行任意 terminal 指令；恢復由明確 wrapper 與 policy gate 處理。
- 加入 notify-only `/goal` monitor：精確 session 配對、證據 snapshot、語意 verdict 與自動建立 Decision Card；自動介入延後到另行驗證的階段。

### Phase 2：Work/Evidence sync

- GitHub Project/Issue/PR 與 CI evidence 雙向同步。
- 自動產生但不自動發布 Project Status Update；由 owner 或主 AGENT確認。

### Phase 3：Controlled execution

- 加入 worktree/branch ownership、測試 tier、budget、checkpoint 與 release gates。
- 只有經量測證明安全的低風險動作才逐項開放自動化。

## 16. 風險與待驗證事項

- GitHub Project 權限與 personal repository 能力是否足以支援所有欄位；不足時以 labels/custom fields 降級。
- Herdr 是否提供足夠穩定的狀態 API；不能依賴的欄位必須由 wrapper 補足。
- 百分比可能製造虛假精準；需要以合成示例里程碑回放校準 effort 與 gate。
- 自動同步可能造成 card 與 repo 互相覆寫；必須指定每個欄位的唯一 authority。
- 網頁能看 terminal/diff 不代表已驗證產品價值；產品驗證和工程驗證必須維持分離。
- 子專案名稱、是否遠端共享、第三方 SaaS/付費服務均尚未形成產品決策；MVP 不預設開通。

## 17. 參考模式

- [GitHub Projects](https://docs.github.com/en/issues/planning-and-tracking-with-projects)：table/board/roadmap、
  sub-issues、custom fields、insights 與 status update。
- [Linear](https://linear.app/docs/conceptual-model)：Initiative → Project → Milestone → Issue、health 與週期性
  project update。
- [GitHub Spec Kit](https://github.com/github/spec-kit)：Specify → Plan → Tasks → Implement 的 artifact chain。
- [LangGraph Agent Inbox](https://github.com/langchain-ai/agent-inbox)：durable interrupt 與
  accept/edit/respond 模式。
- [Vibe Kanban](https://github.com/BloopAI/vibe-kanban)：work item → isolated workspace → Agent →
  diff/review → PR；只借鏡模式，不依賴已 sunset 的產品。

# Orca 整合設計：ACC 收斂為驗收層

狀態：`proposal`。本文是設計提案，尚未實作。
除 §5.1 的 `/goal` 綁定已在本機核對外，其餘尚未取得實機證據。
提案日期：2026-09-17。

參與討論：Claude Opus 5（讀 Orca 原始碼、盤點介面）、gpt-6-astra（架構與模組去留）。
兩方獨立作答後合併；分歧處在 §7 明列，未強行收斂。

核對基準：Orca clone 於 commit `0d23ea6e688410c878096dab8b1779857354b7d4`。
本文引用的 Orca 介面皆已在該 commit 的原始碼核對過存在，但**未經實機執行驗證**。

## 0. 先承認的現況

- **本機尚未安裝 Orca。** `PATH` 中有 Herdr（`~/AppData/Local/Programs/Herdr/bin`），
  沒有 `orca`，`~/.orca` 不存在。本文全部推論來自讀原始碼。
- 因此第 0 階段的第一件事是安裝 Orca 並實跑一個真實交付週期。
  在那之前，本文任何一條都不得當成已確認的事實。

## 1. 判斷依據：誰有權做哪一種判定

分工不該用「目前誰少一個頁面」來切——那會隨 Orca 每次改版失效。
該用**誰有權作出哪一種判定**來切，這個界線不會因為對方多做一個功能而移動。

| 判定 | 唯一負責者 |
| --- | --- |
| agent 在哪執行、如何開啟／傳訊／停止 | Orca |
| task、issue、PR、worktree、diff、merge | Orca 與其上游系統 |
| 產品究竟承諾交付什麼 | ACC 的 owner 確認成果樹 |
| 某成果對某版本是否驗收有效 | ACC |
| 證據是否完整、過期、對錯版本 | ACC |
| 獨立巡查發現什麼、需要 owner 決定什麼 | ACC |

ACC 剩下的必要核心是三件事：

1. **版本化的驗收契約**：成果描述、驗收條件、owner 確認的結構版本。
2. **可追溯的驗收帳本**：提交版本、證據內容、hash、有效期限、owner 決定與撤銷紀錄。
3. **獨立查核流程**：查證執行者的主張、提出 Decision Card；不自行改派工作、不自動接受成果。

### 1.1 成果樹不可與 Orca task 同步成同一棵樹

成果樹表達「產品承諾」，Orca 的 task／issue 表達「執行工作」。
一個成果可對應多個 task，一個 task 也可能同時支撐多個成果。
ACC 只保存對外部工作的**參照**，不建立雙向同步的副本。

### 1.2 接縫在哪裡

Orca 的 orchestration 已有 `task status`（`src/cli/specs/orchestration.ts`），
但那是**執行者自己宣告**的狀態。ACC 存在的理由正是這句話：
自稱完成不等於有驗證證據。這條接縫就是兩個系統的分界。

## 2. 整合形態評估

| 形態 | 介面 | 優點 | 缺點 | 判斷 |
| --- | --- | --- | --- | --- |
| 各自獨立，只靠 Git 與證據包 | commit OID、JSON manifest、檔案匯入 | 最耐版本變動；Orca 關閉仍可驗收 | 無即時巡查線索 | **保留為永久基礎與降級路徑** |
| 獨立 ACC ＋唯讀 CLI adapter | `orca worktree ps --json`、`orca terminal list --json` | 改動小、邊界明確、容易測試與替換 | 輪詢會漏掉短暫狀態 | **推薦為正式第一版** |
| 獨立 ACC ＋薄 plugin | plugin 訂閱 `agent.status.changed` 轉送 ACC | 事件即時 | Plugin API 在 `plugin-host-api.ts` 明確標示 `stability: 'experimental'` | 後續可選 |
| fork Orca／讀內部 state／攔截 managed hook | 改主程式、讀 cache、改 agent 設定 | 資料最深 | 綁死內部生命週期，維護成本最高 | **不推薦** |

### 2.1 一個必須釐清的誤解

**managed hook 是 agent → Orca 的輸入，不是 Orca → ACC 的公開事件 API。**
不要把 endpoint file 當訂閱介面，也不要讓 ACC 再管理一次各家 agent 的設定檔——
那等於重建一套 Orca 已經在維護的東西，並且兩套會互相覆寫。

### 2.2 不把 Orca 狀態當證據的具體理由

Orca 自己的 `docs/reference/agent-status-store.md` 記載：狀態目前有三份主行程副本、
六個 producer、三個 consumer，各自套用不同的 precedence 與 freshness 規則，
同一個 pane 在桌面、手機、CLI 上可以合理地讀出不同結果；統一工作仍在進行中（PR 2A 邊界）。

這不是批評 Orca——那是它的內部演進。但它直接證明：
**agent 狀態是排程資訊，不是驗收證據。** ACC 必須維持這個區分。

### 2.3 資料流

```text
Owner ──確認成果／驗收／決策────────────→ ACC
                                            ↑
Git ──固定 commit、檔案內容──────────────────┤
實作者／獨立查核者 ──證據包、查核報告─────────┤
                                            ↑
Agents ──managed hooks──→ Orca ──唯讀 CLI adapter
                           ↑
                    Owner 執行工作操作
```

ACC 不向 Orca 發送任何 agent 指令。ACC 可產生一份「驗收需求包」供 owner 帶到 Orca，
內含成果 ID、條件版本與要求的證據——那是交接資料，不是派工系統。

## 3. Provider 介面

新增 `execution_provider.py` 介面與 `orca_adapter.py`，**只提供三個方法**：

```text
list_workspaces()
list_execution_observations()
get_capabilities()
```

刻意不設計 `send_message()` 或 `create_worker()`。介面裡留下那些方法，
等於為「把已經放棄的責任長回來」預留了入口。

輪詢起始設定：每 10 秒一次，單次 timeout 3 秒；連續 30 秒無成功查詢即顯示
「連線資訊過期」。這只代表 ACC 讀取失敗，**不能判定 agent 已停止**。
讀到 cache 也不能刷新原始事件的證據時間。

adapter 保存：外部識別、來源、原始觀察時間、接收時間、payload hash。
Orca 沒提供的欄位就留空，不能從 pane 名稱或終端文字補猜。

## 4. 驗收模型

兩個維度必須分開，且禁止隱式轉換：

| 維度 | 取值 |
| --- | --- |
| 執行觀察 | `working` / `idle` / `unknown`，附來源與時間 |
| 成果驗收 | 未驗收 / 待 owner / `owner_attested` / 過期 / 版本不符 / 證據缺失 / 已撤銷 |

驗收紀錄至少包含：

```text
outcome_id + criteria_revision
repository_id + commit_oid
evidence_manifest_hash
owner_identity + attested_at + expires_at
revocation_reference
```

`owner_attested` 是**對特定版本與特定條件**的判定：

- 條件改變、新 commit、證據缺失或到期，都不能沿用現有的有效標示。
- 舊驗收保留為歷史事實，不覆寫、不刪除。
- merge／squash 後的提交**不自動承接**來源 worktree 的驗收。
- 測試證據需記錄實際 checkout、dirty 狀態、指令與環境；第一版要求乾淨 checkout 對應固定 commit。

證據原始 bytes 必須複製進 ACC 管理的內容定址目錄，**不能只保存隨時會被刪除的 worktree 路徑**。
資料庫與證據目錄必須一起備份。

hash 能檢查保存內容是否被變動；它不能證明測試正確、提交者誠實，或產品符合需求。

## 5. Herdr 的去留

**Herdr 退出 ACC 的正式依賴。** 使用者仍可自行使用 Herdr，但 ACC 不再維護第二套 agent 管理能力。

過渡（可回滾）：

1. 現有讀取封裝為 `HerdrProvider`，來源明確標示 `terminal_inferred`。
2. 加入 `OrcaProvider`，短期並行觀察。同一次執行的來源由 owner 明確選定，
   **不能把兩者拼起來宣稱可信度更高**。
3. 新工作一律在 Orca；既有 Herdr 工作自然結束，歷史證據留在 ACC。
4. 移除 Herdr 傳訊、pane 管理與新綁定入口，最後刪除 adapter。

### 5.1 `/goal` 綁定：已查證，不是門檻

**結論：`/goal` 綁定不依賴 Herdr，也不依賴 Orca。** 原先把它列為遷移門檻是找錯方向。

`/goal` 是 Codex CLI 自己的功能，狀態寫在兩個地方，與誰啟動那個終端機無關：

| 來源 | 內容 |
| --- | --- |
| `~/.codex/goals_1.sqlite` 的 `thread_goals` | **原生 `goal_id`**、`thread_id`、`objective`、`status`（`active` / `paused` / `blocked` / `usage_limited` / `budget_limited` / `complete`）、`token_budget`、`tokens_used`、`time_used_seconds`、`created_at_ms`、`updated_at_ms` |
| `~/.codex/sessions/**/rollout-<ts>-<thread_id>.jsonl` | 逐筆 transcript，檔名尾碼即 `thread_id` |

2026-09-17 在本機核對：`thread_goals` 9 筆，**9/9 的 `thread_id` 都能對到
`sessions/` 底下唯一一個 rollout 檔**。`goal_monitor.py:_sessions_root()` 本來就直接讀
`~/.codex/sessions`，Herdr 只被用在 `list_project_agents` 與 `read_agent_output`
這條終端機刮取路徑上——那條路徑本來就要退場。

#### 順帶修掉一個既有缺陷

`IMPLEMENTATION_PLAN.md` 記載「Codex 缺原生 goal ID 時以更新時間補 ID」。
**原生 `goal_id` 其實存在**，只是 `_goal_from_transcript` 沒去讀它。
改讀 `thread_goals` 可同時解掉 goal epoch 的推測問題，不必等 Orca 遷移。

#### 仍要承認的限制

1. `goals_1.sqlite` 是 Codex 私有 schema（內有 `_sqlx_migrations`，檔名 `_1` 顯示它會改版）。
   讀它等於依賴 Codex 內部，風險等級與依賴 Orca 內部相同。必須唯讀、必須放在帶 schema 檢查的
   adapter 後面、不符時回報 `unverifiable` 而**不是退回猜測**。
2. 它綁在 **使用者家目錄**。Orca 若把 Codex 跑在 SSH 遠端或 WSL，goals db 在**那台主機**上，
   不在本機。遠端 worktree 的 `/goal` 綁定在第一版顯示為未支援。
3. **只有 Codex 有 `/goal`。** Claude 無等價物，`claude_activity.py` 目前以相同 objective 文字合併。
   這個不對稱不會因為換成 Orca 而消失，不得把兩者當成同強度的識別。

## 6. 模組逐一處置

| 模組 | 處置 | 具體變更 |
| --- | --- | --- |
| `verification.py` | **保留並強化，成為核心** | 驗證 commit、條件版本、證據 hash、期限、撤銷與版本適用性 |
| `plan_parser.py` | 保留 | 解析結果只是草案；穩定 node ID、條件 revision、owner 確認後才生效 |
| `store.py` | 保留並遷移 | 條件版本、不可覆寫的驗收／撤銷、證據索引、綁定；agent 觀察採有限保存期 |
| `models.py` | 改寫邊界 | 分開執行觀察、實作者主張、查核報告、owner 驗收，禁止隱式轉換 |
| `importer.py` | 保留但縮限 | 唯讀登錄 repo／匯入成果文件；**不替 Orca 建工作 worktree** |
| `main.py` | 瘦身、拆分 | 移除 pane／傳訊／shell 路由；拆成成果、證據、驗收、決策、整合健康 |
| `goal_monitor.py` | **保留並升級**（§7.2） | 識別改讀 `thread_goals` 原生 `goal_id`；移除 `herdr_adapter` import；缺資料回報 `unverifiable`；固定 notify-only |
| `event_collector.py` | 改寫 | 收集有來源的觀察、去重、記錄缺口；不再把文字解析成任務真相 |
| `notifications.py` | 保留但縮限 | 只通知待驗收、過期、Decision Card、巡查失聯；agent 完成／等待交給 Orca |
| `claude_activity.py` | 刪除活動推測職責 | 若仍需讀 Claude 結構化資料，另設狹窄 reader；終端解析不進入驗收判定 |
| `herdr_adapter.py` | 過渡後刪除 | 暫包為舊 provider；新建唯讀 `orca_adapter.py`，**不搬終端 regex** |

前端 SSE 保留，但串流內容改為 ACC 的驗收／決策事件；移除終端輸出主畫面。
UI 只留三個主要入口：**成果**、**待驗收／待決策**、**驗收歷史**。
agent 狀態縮成成果旁的背景資訊，點擊可複製定位資訊回 Orca 操作。

## 7. 已收斂的兩項決定

兩項原本未收斂的分歧已由 owner 於 2026-09-17 決定。

### 7.1 Decision Card 交給 Orca gate

**決定：ACC 只產生「需要決定」的報告，互動式 gate 交給 Orca
（`orchestration gate create/resolve/list`），不自建第二套待辦。**

ACC 產出的是查核報告與其中的待決事項；owner 在 Orca 裡處理 gate。
ACC 保存 gate 的外部參照，不複製其狀態機。

未完成的查證：Orca gate 的語意是否足以承載 ACC 的待決事項（欄位、解析結果的可追溯性、
與成果節點的對應）。**這一項列入階段 0 的實機確認清單**；若確認不足，
退路是 ACC 只在報告內以純文字呈現待決事項，仍不自建 gate。

### 7.2 `goal_monitor.py` 保留並升級

**決定：保留，且要有 `/goal`。**

依 §5.1 的查證結果，這是可行的，而且不需要等 Orca：

- 識別來源從 transcript 推測改為 `thread_goals` 的**原生 `goal_id`**。
- 移除 `herdr_adapter` 的 import；巡查輸入改為 goals db ＋ rollout 檔 ＋ git 證據。
- 維持 notify-only，維持「缺資料回報 `unverifiable`」。
- 遠端／WSL 情境與 Claude 側顯示為未支援，不以其他 ID 代替。

因為這條路徑完全不經過終端機管理器，**它可以排在階段 1，不必等接 Orca**。

### 7.3 subagent 外包的 delegation 證據鏈

**決定：`codex-worker` subagent 回報 `thread_id`，ACC 用它補完 delegation 鏈。**

ACC 早已有 `AgentDelegation`（`claude_activity.py:_delegation_identity`），
以 `(session_id, tool_use_id)` 把一次 Claude `/goal` 與一次 `codex exec` 配對，
並比對 requested／launched model、追 TaskStop 結果鏈。缺的只是 Codex 那一端的原生識別。

#### 已查證的事實（2026-09-17 本機實測）

| 查證項 | 結果 |
| --- | --- |
| `codex exec` 有無 `--goal` 旗標 | **沒有**。整份 `--help` 無 goal 字樣 |
| `codex exec` 會不會建立 Codex `/goal` | **不會**。實跑一次後 `thread_goals` 無對應 row |
| `codex exec --json` 有無原生識別 | **有**。第一行即 `{"type":"thread.started","thread_id":"…"}` |
| 該 `thread_id` 有無 transcript | **有**。對到唯一一個 `sessions/**/rollout-*-<thread_id>.jsonl` |

結論：**Codex 的 `/goal` 是 TUI 專屬功能，接不上非互動的 `codex exec`。**
不要嘗試把它硬接上去；要的識別由 `thread.started` 提供。

#### 證據鏈

```text
Claude 原生 goal_id（attachment.goal_status）
  → AgentDelegation(session_id, tool_use_id)      ← ACC 已有
  → codex thread_id（thread.started 第一行）       ← 本次補上
  → sessions/**/rollout-*-<thread_id>.jsonl       ← 執行證據
```

全程原生 ID，不經 Herdr、不經 Orca、不含猜測。因此**排在階段 1**。

#### 已實施的改動

`~/.claude/agents/codex-worker.md`（使用者全域設定，非本 repo）已加上：
`--json` 旗標、stdout 導向事件檔、從第一行取 `thread_id` 的步驟，
以及回報必須附上 `thread_id`。

該 agent 明確禁止用時間、cwd 或「最新的 rollout 檔」推測是哪一次執行——
平行外包時那會綁錯對象。這與 §9.2 的原則一致。

#### 派工指令的形狀是產品約束

實作後用本 session 真實的派工紀錄驗證，結果**全部 unverified**。原因不是綁定寫錯，
而是真實指令長這樣：

```text
... )" > "$S/luna-events.jsonl" 2>"$S/luna-err.log"; echo "EXIT=$?"; head -1 "$S/luna-events.jsonl"
```

兩個問題，綁定拒絕兩次都是對的：

1. 路徑是 shell 變數 `$S`。ACC 不展開 shell 變數——展開就是猜。
2. 指令不以導向結尾，後面還接著 `2>`、`; echo`、`; head`。
   複合指令裡有多個導向時，挑哪一個都是猜。

修法是**約束派工端，不是放寬驗證端**。`codex-worker` 已加上規定：
事件檔必須是字面絕對路徑，`codex exec` 要自成一句並以導向結尾，要看結果另外下一句。

不符合這個形狀不會出錯，只是那筆委派在控制台顯示「未驗證 child Goal」——
這正是預期行為。

#### 限制

1. **只涵蓋由 `codex-worker` 發動的外包。** 使用者自己在 TUI 開的 Codex pane
   走的是 `thread_goals` 那條路（§5.1），兩條路並存，不可混用識別。
2. Claude 側的 `/goal` 是 Claude Code 內建功能，其 transcript 格式非公開契約，
   與讀 `goals_1.sqlite` 同屬依賴內部；處置方式相同：唯讀、帶格式檢查、
   不符時回報 `unverifiable`。
3. `thread_id` 證明的是「哪一次執行」，**不證明那次執行達成了需求**。
   驗收仍然只能由 owner 依 §4 的模型作出。

## 8. 分階段實施與通過條件

通過條件一律是可檢驗的證據，不是完成度百分比。每階段通過才進下一階段。

| 階段 | 內容 | 通過條件 |
| --- | --- | --- |
| 0 保存基準、確認介面 | 安裝 Orca 並實跑一個真實交付週期；備份 SQLite 與證據；鎖定 Orca 版本；錄製 CLI fixtures；**確認 gate 語意是否夠承載待決事項（§7.1）** | 備份可還原並重算 hash；fixtures 涵蓋正常、斷線、重啟；gate 欄位對應表寫出「夠用／不夠用」與依據 |
| 1 建立獨立驗收核心 ＋ `/goal` 原生綁定 | 拆狀態、條件 revision、證據包、owner API；`goal_monitor` 改讀 `thread_goals`（§7.2）；delegation 鏈接上 `thread_id`（§7.3） | **不啟動 Orca 與 Herdr 也能完成驗收**；agent 宣告 `done` 不改變驗收狀態；版本錯誤、過期、hash 不符皆被阻擋；每個 monitor 綁定都帶原生 `goal_id`，schema 不符時回報 `unverifiable` 而非猜測；每筆 `AgentDelegation` 都帶 `thread_id` 並對得到唯一一個 rollout 檔 |
| 2 接入唯讀 Orca | CLI adapter、明確工作綁定、來源與新鮮度標示 | 重複輪詢不產生重複領域事件；Orca 中斷顯示 `unknown`；重啟不誤綁其他 session；執行紀錄中無傳訊或建立工作的命令 |
| 3 移植獨立巡查 | 不同 session 的查核者、固定證據輸入、查核報告；待決事項輸出為 Orca gate 參照（§7.1） | 刻意失敗測試／缺證據／錯 commit 三組案例分別得到失敗／不可驗證／版本不符；查核者無法建立 owner 驗收；ACC 內不存在第二套待辦狀態機 |
| 4 退役 Herdr | 舊綁定結案、移除程式與 UI 入口 | 無 Herdr 安裝的環境可跑完「成果→實作→證據→巡查→owner 驗收」；舊歷史可查閱；執行紀錄無 Herdr／capture-pane 呼叫 |
| 5 選擇性即時事件 | 若輪詢確實不足，再加薄 plugin | 事件重複、亂序、斷線不會改錯狀態；停用 plugin 後仍能 CLI 降級與獨立驗收 |

第一版不做 fleet、多人 ACL、額度池、自動派工、worker 隔離、Web Push。
這些不影響上述閉環成立。

## 9. 三個最大風險

### 9.1 Orca 快速演進，介面與語意會變

Electron 不是核心問題，核心是依賴一個別人控制的執行平台。
Orca 的狀態收斂仍在進行（§2.2），Plugin API 標示 experimental。

對策：依賴限制在單一 adapter；維護已驗證版本清單與 JSON fixtures；升級前跑契約測試。
schema 不相容時停止該整合並顯示 unavailable，**不能悄悄退回 regex 猜測**。
ACC 核心永遠可用 Git ＋證據包運作。

### 9.2 把結構化訊號誤認為可信成果，或綁錯版本

hook 改善的是觀測，不是完成度的證明。平行 worktree、session 重啟、merge
都可能讓報告對錯對象。

對策：顯式 binding、固定 commit、條件 revision、保存證據原件；
識別不足就拒絕自動歸屬。獨立查核者只產生報告，只有 owner 能驗收。

另註：同一帳號下兩個 pane 只是流程上的獨立，**並非安全隔離**。
第一版要明確承認這個限制；owner UI 使用獨立 session，提交證據用的 token 沒有 attestation 權限。

### 9.3 ACC 長回第二套專案管理系統

最容易發生的是重做 task、聊天、agent dashboard、手機通知，
再為 Orca 的每個功能加一層同步邏輯。

對策：任何新功能都必須直接改善「定義成果、保存證據、判定驗收、處理決策」四者之一。
工作管理只保存外部參照，不建立雙向同步副本。

## 10. 結論與退場條件

**值得保留 ACC，但應大幅縮小。** 先交付「沒有 Orca 也成立的驗收閉環」，
再接入 Orca 的執行觀察。

退場條件寫在這裡，以免日後自我合理化：
若跑完一個真實交付週期後，owner 根本不逐條驗收、也不查證據，
就應把 ACC 收成簡單的驗收 CLI／報告產生器，不再維護完整 Web app。

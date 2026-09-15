# Agent Development Control Center — 前端產品規格

狀態：`proposed`\
對應：[PRD](PRD.md)\
最後更新：2026-09-15

目前 MVP-A 的通知／驗收前後端契約見 [API_CONTRACT.md](API_CONTRACT.md)，屬實作／整合驗證階段。本文件其餘設計不可視為已交付能力；多人節點管理、額度派工與關頁推播尚未完成。

全域通知中心保存已讀狀態並返回精確專案／項目；初次載入歷史不彈桌面提醒。事件種類、專案與安靜時段控制提醒，不刪除既有通知紀錄。桌面提醒由使用者主動授權，使用一般摘要；無瀏覽器能力／原子多分頁協調時保留站內通知，不承諾關頁收到。

成果驗收 UI 只對最末層開啟；owner 先保存必要 gates，再逐條確認 acceptance／gates 與相對證據檔案，選擇有效期限。畫面明示「擁有者已核對」，不冒充自動跑測試；伺服器回報規則、版本、證據變動時要求重新讀取，不能保留舊勾選直接送出。有效紀錄動態影響成果狀態，失效後不延續 verified。

## 1. 前端要回答的五個問題

使用者打開首頁後，不需要閱讀 Agent 對話就能回答：

1. 我們現在要達成哪個產品結果？
2. 實作完成多少、真正驗證多少？
3. 哪些風險或資料缺口可能讓進度不可信？
4. 哪些 Agent 正在做什麼，是否卡住或已 stale？
5. 現在有哪些問題必須由我回答？

首頁不是聊天框，也不是滿版 terminal。聊天、log 與 diff 都是 drill-down 證據，不是最高資訊層。

### 人話優先的三層資訊

每一頁和每個主要項目都使用同一順序：

1. **人話**：這件事要讓使用者或產品變得怎樣、現在發生什麼、下一步是什麼。
2. **管理資訊**：負責人、狀態、風險、目標日期與完成條件。
3. **工程細節**：Work ID、API、branch、gate、命令、diff、log 與原始證據。

第一層不能出現只有工程師才懂的孤立詞彙，例如 `Browser gate unrun` 應先寫成「網站還沒在真實瀏覽器
完整走過主要流程」，再於次要文字標示 `browser: unrun`。每頁標題下固定放一段「這頁看什麼」；若有
owner action，再放一句「你現在要做什麼」。

## 2. 導覽與整體版面

### 2.0 產品入口與專案切換

未加入專案時，首頁先解釋匯入是唯讀掃描，提供「本機 Git repo／GitHub／空白產品」三種入口；MVP 只
啟用本機 Git repo。掃描後必須先顯示系統理解到的名稱、產品目的、依據、缺口與衝突，讓人修正並確認，
不能把 Agent 推測直接存成核准計畫。

已加入專案時，最上層先顯示「所有專案」portfolio：每個專案的人話健康狀態、待決策數、主要風險與
最後可靠更新。不同專案不得合併成單一完成百分比。進入專案後才顯示 Overview、Plan、Work、Decisions、
Agents、Releases 與 Evidence。左上角 project switcher 可返回所有專案或匯入新專案。

子專案使用同一張 Project card 與同一組頁面，只以父子關係出現在 portfolio 和產品樹；不得另造一套
較弱的子專案資料模型。

### 2.1 桌面

```text
┌──────────────┬──────────────────────────────────────────────────────┐
│ 示例任務板     │  M1 任務匯入     At risk · 12 分鐘前同步          │
│ Control      ├──────────────────────────────────────────────────────┤
│              │                                                      │
│ ● Overview   │                    主內容                            │
│   Plan       │                                                      │
│   Work       │                                                      │
│   Decisions  │                                                      │
│   Agents     │                                                      │
│   Releases   │                                                      │
│   Evidence   │                                                      │
│              │                                                      │
│ GitHub ✓     │                                                      │
│ Herdr  ✓     │                                                      │
│ CI     !     │                                                      │
└──────────────┴──────────────────────────────────────────────────────┘
```

- 左側固定 rail：主要區域、待決策數量 badge、資料源健康狀態。
- 上方 context bar：repo、active milestone、health、最後同步、全域搜尋、同步按鈕。
- 主內容最大寬度不鎖死；計畫表與 diff 可使用寬螢幕。
- 右側 detail drawer：查看卡片、決策、Agent 或證據，不必一直離開總覽。

### 2.2 手機

- 底部導覽只保留 `總覽／工作／決策／更多`。
- 預設顯示 owner 需要動作的內容，不嘗試在手機完整呈現 Roadmap/Gantt。
- Roadmap 改為 Milestone 縱向時間線；大型表格改為 summary card + detail page。
- approve/merge 等高風險操作固定在 detail page 底部，避免滑動時誤觸。

## 3. Overview／總覽

### 3.1 首屏

```text
┌──────────────────────────────────────────────────────────────────┐
│ 目前目標：讓 示例任務板 的任務匯入可正常使用       │
│ M1 任務匯入 · At risk                                           │
│ 原因：browser 驗證落後；1 項匯入測試證據已過期                    │
│ [查看里程碑]                                      更新 12 分鐘前  │
└──────────────────────────────────────────────────────────────────┘

┌──────────────┬──────────────┬──────────────┬─────────────────────┐
│ Scope        │ Verification │ Decisions    │ Release readiness   │
│ 21/34 effort │ 12/29 effort │ 2 等待回答   │ 6 passed / 2 unrun  │
│ 62%          │ 41%          │ oldest 3h    │ At risk             │
└──────────────┴──────────────┴──────────────┴─────────────────────┘
```

規則：

- 不顯示孤立的「專案完成 73%」。
- 每張統計卡都顯示分子、分母、計算方法與最後更新時間，點擊可看到構成項。
- unknown/unestimated 不納入分母時必須另外顯示數量。
- 綠色只代表有足夠且未過期的證據；不是單純 status 字串為 done。

### 3.2 需要你處理

放在首屏統計下方，最多顯示三項：

```text
需要你決定 · P0
是否允許 Control Center 將專案狀態同步到遠端服務？
建議：第一版只保留本機與 GitHub
影響：資料隱私、高 · 阻塞：遠端共享
[查看證據] [稍後] [回答]
```

若沒有 Decision，顯示下一個需要 review/release approval 的動作；不要用空白歡迎畫面填充。

### 3.3 目前進行中

- 依 Epic 分組顯示最多五個 active Work Items。
- 每列顯示 owner/Agent、目前階段、已持續時間、branch、最新證據與阻塞。
- 長時間沒有 activity 顯示 `stale`，而不是繼續顯示 working 動畫。

### 3.4 風險與最近變化

- 風險依 impact × urgency 排序，不依建立時間。
- 最近變化只收錄會改變計畫判斷的事件：scope 增減、健康變化、重大決策、gate 結果、release。
- 細碎 terminal log 不進首頁活動流。

## 4. Plan／產品計畫

### 4.1 兩種視圖

- **可展開計畫（預設）**：Goal → Milestone → Epic，適合理解「為什麼」、目前情況與完成條件。
- **Roadmap**：依開始/目標日期呈現 Milestone/Epic，適合看順序、重疊與依賴。

這裡的「樹」是可折疊、可篩選、可操作的前端 outline/tree component，不是流程圖。連接線只協助理解
父子關係；每個節點仍是可閱讀的產品敘述。Archify 的 architecture/workflow 圖可作為「查看系統架構」
或「查看交付流程」的輔助連結，不取代計畫 UI。

```text
讓示例任務板的使用者可靠地建立與追蹤任務（完全合成）
├─ 讓使用者登入後建立自己的任務                 已完成
├─ 讓匯入結果清楚且可修正                       有風險
│  ├─ 先預覽再確認新增資料                     審查中
│  ├─ 遇到重複資料時提供清楚說明               完成第一版
│  └─ 確認鍵盤操作與錯誤提示可用               驗證中
└─ 補齊取消與重試的說明                         尚未開始
```

每個節點第一行顯示：產品結果、人話狀態與下一步；展開後才顯示 owner、health、目標日期、
scope/verification、未滿足 acceptance、工程標籤與阻塞依賴。「已完成第一版」必須保留 `partial` 語意，
不能因文字包含「完成」就解析成 Done。

匯入後先顯示 `draft` banner，列出從 Roadmap 整理出的階段、成果與來源。使用者按「確認這份計畫」只
表示樹的結構可以作為管理基準；不會把 Roadmap 中的「已完成」轉成 `VERIFIED`。確認後 banner 改成
「產品計畫已確認」，每項成果仍以 acceptance 與 evidence 個別計算。找不到 Roadmap 時使用
`needs_source`，直接說明缺少計畫來源並提供重新讀取，不建立「仍需確認」但無法操作的死路。

### 4.2 範圍變更

- 新增未規劃工作時顯示 scope change badge。
- 移除工作必須選擇 `not planned/canceled/superseded` 並填理由。
- Roadmap 遠期項目允許不估 effort；以「尚未細化」顯示，不製造假百分比。

## 5. Work／工作台

### 5.1 預設 Board

欄位：`Backlog / Ready / Working / Review / Verifying / Done`，另以 filter 顯示 `Needs decision / Blocked`。

Work card 最小顯示：

- type、priority、標題、parent Epic。
- owner 或 Agent、area、effort。
- branch/worktree/PR 狀態。
- verification progress 與未跑類別。
- blocked/decision/evidence stale badge。

卡片不能只靠顏色表達狀態；badge 必須有文字與 icon。

### 5.2 Table

供主 AGENT 批次檢查 scope、ownership、dependencies、dates 與 evidence。支援儲存 view，例如：

- Active milestone
- Unestimated
- No owner
- Missing verification
- Cross-boundary/API changes
- Research awaiting adoption

### 5.3 Work detail drawer

順序固定為：

1. Outcome 與 acceptance criteria。
2. 現況與 next action。
3. scope/owner/branch/worktree/dependency。
4. PR/diff。
5. 已跑驗證。
6. 未跑驗證與風險。
7. Decisions/Evidence/Activity。

把 next action 放在 log 前面，避免使用者先閱讀數百行執行紀錄。

## 6. Decisions／決策收件匣

### 6.1 列表

預設依 `阻塞程度 → impact → deadline → age` 排序，分成：

- 現在需要回答
- 等待 Agent 補證
- 已回答、尚未恢復
- 最近完成

每張列表卡顯示問題、建議預設、影響類型、阻塞項目、提出者、等待時間與期限。

### 6.2 決策詳情

```text
┌───────────────────────────────────────────────────────────────┐
│ DEC-024 · 隱私 · 高影響 · 阻塞遠端共享                        │
│ Control Center 是否可將 Herdr 執行 metadata 傳到第三方服務？  │
├───────────────────────────────────────────────────────────────┤
│ Agent 建議                                                     │
│ ● 第一版只存本機與 GitHub；terminal 內容不外傳                 │
│ 理由：滿足 MVP，同時避免新增隱私與付費服務決策                 │
├───────────────────────────────────────────────────────────────┤
│ ○ A 採建議       最小風險；暫無遠端即時共享                    │
│ ○ B 使用 SaaS    UI 完整；需確認資料、權限與費用                │
│ ○ C 自架 Plane   可共享；增加部署和維護成本                    │
├───────────────────────────────────────────────────────────────┤
│ 已查來源：AGENTS.md、PRD、現有 Herdr API                        │
│ 證據／prototype／受影響工作 [展開]                             │
│ 不回答：維持本機，該功能不進 active scope                      │
├───────────────────────────────────────────────────────────────┤
│ [要求補證] [其實已有答案] [稍後]             [確認選擇]         │
└───────────────────────────────────────────────────────────────┘
```

在選項下方固定提供文字輸入區，不藏在「其他」選項裡：

```text
還想問 Agent 或提供自己的答案？
[ 請解釋為什麼不能只傳工作狀態，不傳 terminal 內容……        ]
[附上目前畫面]                        [送出追問] [作為我的答案]
```

`送出追問` 將訊息加入此 Decision 的討論串並改為「等待 Agent 補充」，不算回答；`作為我的答案` 則先
將文字整理為正式決策預覽，讓人確認 scope、影響與會恢復哪些工作。討論串只包含本題相關訊息，主 Agent
的完整對話仍從 Agents 頁進入。

互動規則：

- 預設選中 Agent 建議，但必須由人按確認；不能因倒數到期自動視為 confirmed。
- `採安全預設繼續` 只允許 policy 明確標記為可逆且不涉及人類保留權限的問題。
- 自由文字永遠可用；追問與正式回答使用不同按鈕、不同狀態與不同確認流程。
- Agent 每次補充都形成新版本；先前建議、選項、證據和對話保留，可比較「改了什麼」。
- 自由文字回答先由系統整理成 statement/scope，顯示預覽後再確認；系統的整理不能擴張人的原意。
- 若回答與既有 Decision Record 衝突，顯示兩者 scope、authority、日期與「取代舊決策」操作。
- 回答後顯示「已寫入哪裡、會恢復哪個工作、仍有哪些工作不受影響」。

Decision lifecycle：

```text
WAITING_HUMAN → WAITING_AGENT → WAITING_HUMAN → ANSWERED → RESUME_PENDING → RESOLVED
       └──────────────── 自訂答案／選項確認 ────────────────┘
```

## 7. Agents／Agent 執行狀態

### 7.1 Agent 列表

```text
Codex · backend-delivery     WORKING   18m   WORK-211
Claude · research-critic     IDLE       4m   RESEARCH-018
Codex · qa-release           BLOCKED   11m   WORK-214
Herdr disconnected           UNKNOWN    —    last seen 10:42
```

列表上方提供「目前 Goal 與派工」區：先列 Claude／Codex 的 active goal，再以父 Agent → 子 Agent 顯示每次
派工。固定呈現 `已驗證掛載 Goal／未驗證 child Goal`、`Herdr 可見／Herdr 看不到`、要求／啟動／實際模型
及停止狀態。未收到 lifecycle heartbeat 或完成事件時使用「已啟動，狀態未知」，不得讓啟動紀錄永久保持
綠色 running。

每列顯示：Agent/角色、Herdr workspace/pane、Work Item、狀態、elapsed、last activity、branch、budget、目前
工具或 gate（若有可靠結構化資料）。

主 Agent 固定置頂並標示「負責規劃、決策交接與整合」；每一列都提供「開啟對話」，Claude 與 Codex
使用同一種對話 UI，不要求使用者理解不同 CLI 的輸出格式。

### 7.2 Agent 詳情

- **對話（預設 tab）**：human/agent 訊息、結構化 checkpoint、Decision 與工具摘要；支援傳訊息。
- 工作契約：目標、read/write/forbidden scope、驗收、退休條件。
- 執行摘要：已完成、正在做、下一步；由結構化 checkpoint 提供。
- event timeline：啟動、工具、測試、decision、checkpoint、停止。
- 快速操作：傳送訊息、要求 checkpoint、前往工作、開啟原始 terminal、停止；操作前顯示目標 pane。
- terminal output 預設折疊，且 secrets redaction 失敗時不顯示。

`BLOCKED` 附原因分類：等待人、等待 Agent、環境、測試、外部服務、未知。只有「等待人」且有 Decision
Card 才連到 Decisions。

### 7.3 Claude／Codex 對話 adapter

前端只依賴共同能力：`list_sessions`、`read_messages`、`send_message`、`request_checkpoint`、
`focus_terminal`。本機 backend bridge 分別實作 Claude、Codex 與 Herdr adapter，將可靠內容轉成共同
message schema。若只能讀到 terminal window，畫面顯示「目前只取得最近終端輸出」與最後可見時間；
不得自行推測遺失的訊息或把 terminal log 假裝成完整 conversation history。

選中 Agent 後，終端區以同源 SSE 串流接收 Herdr 的有界快照；內容沒有變化時不重繪。畫面必須顯示
「正在連線／即時更新中／正在重連／單次快照」之一，串流斷線不得繼續顯示為 live。切換 Agent 或關閉
詳情時立即關閉舊串流，避免讀錯 pane；後端每次更新都重新確認 pane 仍屬於目前 Project。

## 8. Releases／交付中心

每個 release candidate 使用 gate matrix：

| Gate | 結果 | 證據 | 時間 | 說明 |
| --- | --- | --- | --- | --- |
| Acceptance | passed | 8/8 scenarios | 10:20 | |
| Unit | passed | command + SHA | 10:25 | fast suite 不是 full |
| Contract | passed | report | 10:31 | |
| Browser | unrun | — | — | 尚無可用瀏覽器環境 |
| External | not required | policy | 09:10 | 本次未碰 provider |
| Human decision | waiting | DEC-024 | — | privacy |

頁尾依序顯示：未解風險、rollback、目標 branch/environment、副作用、核准權限。`Approve` 只有所有硬 gate
通過時可用；`Override` 是獨立高風險流程，必須填原因並永久留痕。

## 9. Evidence／證據庫

- 不是檔案總管；以「它支持哪個 claim/gate」為主索引。
- 顯示 evidence type、scope、來源、revision/hash、產生時間、fresh/stale、結果與限制。
- 支援比較同一 gate 的新舊證據；過期證據保留但不再支持綠色狀態。
- research_only、synthetic、bounded_observed、human_validated 必須使用文字標籤，不能只靠 tooltip。

## 10. 全域狀態與錯誤

### 10.1 資料源指示器

左側底部固定顯示：

- GitHub：connected / syncing / stale / failed。
- Herdr：connected / partial / disconnected。
- CI：healthy / running / failed / unavailable。
- Local records：clean / unsynced / conflict。

點擊後顯示最後成功時間、錯誤、受影響畫面與可行動修復；不得將 cache 當成 live。

### 10.2 Empty states

- 沒有待決策：顯示「目前沒有需要你回答的問題」，並提供最近決策，不以動畫製造忙碌感。
- 沒有 Agent：說明可以先規劃工作，不暗示系統故障。
- 沒有 evidence：明示尚不能驗證，不顯示 0% passed。
- 權限不足：保留唯讀內容，精確說明哪個 action/field 無法同步。

## 11. 視覺語言

- 控制台使用獨立的設計 token 與通用狀態語言，不沿用來源產品的業務判定或樣式識別。
- 使用平台系統字體、tabular numbers、清楚層級、固定 rail 與「不確定要明示」原則。
- 狀態色限制：綠=有新鮮證據通過；黃=風險/部分；紅=硬阻塞/失敗；灰=未知/未跑；藍=一般進行中。
- 卡片只用於真正可操作項目與統計，不做卡片套卡片；詳細證據以 section/divider 呈現。
- 進度條旁永遠顯示文字分子/分母；unknown 和 scope change 另列。
- 動畫只用於可靠的 running/syncing 狀態；超過 heartbeat 時切換 stale。

## 12. 可及性與操作安全

- 所有狀態同時有文字/icon，不只靠顏色。
- 全功能鍵盤操作；drawer/modal 有 focus trap、Escape 與返回焦點。
- 圖表都有等價表格或文字摘要。
- 高風險確認顯示 action、target、side effect、rollback，不使用模糊的「確定嗎？」。
- Decision 選項使用 radio + 完整 label；自由文字與 evidence request 可明確區分。
- 時間同時顯示相對值與完整 timestamp/timezone。

## 13. 前端 MVP 切片

### Slice A：可點擊唯讀原型

- Overview、Plan、Decisions、Agents、Releases。
- 使用完全合成的 M0/M1/M2 計畫與 Agent runtime fixture。
- 所有合成資料固定顯示 `DEMO`，不得看似即時 Herdr/GitHub 狀態。

### Slice B：真實唯讀 adapters

- GitHub/repo/Herdr 狀態與最後同步。
- drill-down 到既有文件、Issue/PR、branch/worktree 和測試證據。
- failure/partial/stale 狀態完整。

### Slice C：Decision write loop

- 建卡、補證、回答、Decision Record、通知、resume handoff。
- 權限、conflict、expired、already answered 與 source unavailable 測試。

### Slice D：Release gate

- gate matrix、未跑驗證、人工核准與 audit。
- MVP 不直接部署 production；只交接既有 Git/CI 流程。

## 14. 前端驗收重點

1. 新使用者能在 60 秒內指出 active milestone、最大風險、驗證缺口與需要自己回答的問題。
2. 不看 terminal/chat，也能回答每個 Agent 正在做什麼及下一步。
3. 不會把 `blocked`、`partial`、`unknown`、`unrun`、`stale` 和 `failed` 混在一起。
4. Decision Card 在首屏可理解問題、建議、取捨、影響與不回答策略。
5. 所有完成與健康狀態都能 drill down 到 evidence；缺 evidence 時不顯示綠色完成。
6. 1440px、1024px、390px 均能完成「找決策→回答→確認恢復目標」流程。
7. 鍵盤、screen reader label、對比、focus、錯誤關聯與高風險確認通過可及性檢查。

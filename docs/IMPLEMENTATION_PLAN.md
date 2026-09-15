# 公開模板、通知與多機器協作開發計畫

狀態：`in_progress`；MVP-A 單機通知、安全預設與 owner-attested 驗收已實作，驗證範圍見 [交付紀錄](MVP_A_DELIVERY.md)。本文工作包是完整後續計畫，不能由部分測試通過推定全部完成。

目前邊界：通知中心、網頁開啟時桌面提醒、驗收紀錄與安全啟動已有程式；瀏覽器／OS 實機證據仍須按當次交付列明。fleet、多人節點 ACL、額度管理、自動派工、隔離 worker、關頁 Web Push 尚未完成，也未授權接管其他電腦。公開 owner 已選 danny0926；LICENSE 已選 MIT，第一階段只使用擁有者自己的電腦。實際已接線契約見 [API_CONTRACT.md](API_CONTRACT.md)。

規劃日期：2026-09-15。依據：[PRD](PRD.md)、[前端規格](FRONTEND_SPEC.md)、[Agent adapter](AGENT_ADAPTERS.md)、根目錄 `AGENTS.md` 與目前程式／測試。

## 1. 要交付的使用體驗

1. 團隊能自行安裝同一套公開產品，內部部署持續接收上游更新。
2. 使用者能收到 Agent 本輪結束、需要決策、項目通過驗收的通知；每則通知能返回正確目標與證據。
3. 一個畫面看見被允許分享的電腦、專案、Agent、可用容量與資料新鮮度。
4. 電腦擁有者決定分享什麼、誰能操作、可用時段與資源上限；加入組織不自動授予遠端控制。
5. 可獨立的工作送到已授權且合適的機器與 AI 帳號，保留可核對的派工、用量、停止與驗收紀錄。

主要成效看「完成且驗收通過的工作所需時間、成本與人工介入」。機器利用率和額度剩餘是排程資訊，不是產品進度；不用刻意耗盡額度。

本文是既有 local-first MVP 的後續擴充提案。尚未形成的遠端資料分享、節點執行與付費決策不因寫入本計畫而自動核准。

## 2. 本次查核的現況與前置缺口

| 現況 | 程式證據 | 對計畫的影響 |
| --- | --- | --- |
| 單機 SQLite；Project 直接保存本機路徑 | `main.py` 的 `Store(ROOT / "data" / "control-center.db")`；`store.py`、`models.py` | 新增節點與 checkout 對應，不能把不同電腦的相同字串路徑當成同一目標 |
| 一組 Basic Auth；缺任一帳密時放行 | `main.py:require_remote_login` | fleet 模式要有個人身分及逐項授權；本機登入不能充當多人 ACL |
| 既有傳訊、啟動 Agent、shell API | `main.py:project_agent_message/project_agent_start/project_shell_command` | UI 隱藏按鈕不足；後端與節點都要拒絕未授權動作 |
| 啟動預設帶 `--yolo` 或 `--dangerously-skip-permissions` | `herdr_adapter.py:_agent_args`；`test_herdr_adapter.py` 固定此行為 | 公開模板前改為明確安全執行設定；更新測試，不能把舊測試綠燈當安全證明 |
| 依 cwd 判斷專案歸屬；shell 使用危險命令 regex | `herdr_adapter.py:_is_within_project/pane_belongs_to_project/run_shell_command` | cwd 與 regex 不構成 OS 隔離；父路徑包含子專案也不代表授權繼承 |
| transcript SSE 僅是目前所選 Agent 的快照 | `main.py:project_agent_transcript_stream`；`App.tsx` 的 `EventSource` | 新增全域持久事件流與補播，不能由目前畫面猜通知 |
| 重複巡查仍插入新 MonitorEvent | `store.py:record_monitor_finding`；`test_goal_monitor.py` | Decision Card 去重不等於通知去重 |
| Codex 缺原生 goal ID 時以更新時間補 ID；Claude 以同文 objective 合併 | `goal_monitor.py:_goal_from_transcript`；`claude_activity.py:_scan_session` | 先修 goal epoch；一般更新不換 epoch，同文重設必須分輪 |
| monitor 唯一鍵與模型只綁 goal session；TaskStop 結果鏈不完整 | `store.py` 的 `goal_monitors`；`models.py:GoalMonitor`；`claude_activity.py` | 歷史不能跨 epoch 混用；停止要核對 tool-use → task → result |
| 模型欄位已有 requested/launch/observed，但合規比較使用 launch | `models.py:AgentDelegation`；`claude_activity.py:_models_match` 呼叫 | 啟動設定符合與實際模型符合必須分開；observed 缺失顯示未知 |
| PlanNode 主要是文件解析與計數 | `models.py:PlanNode`；`plan_parser.py` | 「項目已驗證」需新增逐條驗收與 revision 對應的證據紀錄 |
| 沒有機器容量、帳號額度、預留與工作佇列 | `models.py`、`store.py` | 原型並非已具備分散式排程器 |

本機 Git 已初始化但沒有 commit 或 remote；先前已加入 `.env.example`，排除本機資料並移除 AGENTS 明文憑證。這是公開準備的一部分，尚非完整發布稽核。

## 3. 架構與信任邊界

中央控制台保存邏輯 Project、使用者權限、工作佇列、通知與允許匯出的證據。每台節點主動以 HTTPS 連線回報事件、領取工作；瀏覽器透過中央 API 操作，沒有直接通往其他人的 Herdr socket 或 shell 的通道。

初期採一個中央程序與持久 DB、每節點一份本機操作 journal／事件緩衝。沿用 SQLite 做小型 pilot，使用版本化 migration、交易、唯一鍵與備份還原；跨節點不共享 SQLite 檔。需多中央副本或量測發現寫入瓶頸時，再驗證 PostgreSQL 遷移，不先引入 Kubernetes 或多套訊息系統。

### 3.1 兩種節點

| 模式 | 預設能力 | 自動工作範圍 |
| --- | --- | --- |
| 個人電腦 observer | 擁有者選定專案的摘要、狀態與明確允許的證據 | 不自動接管既有互動 pane；若日後啟用 worker，需另配隔離執行環境 |
| 共享 worker | 擁有者預先設定的 checkout、工具、帳號與工作時段 | 自動領取符合 grant、容量與預算的工作，每個 run 獨立工作目錄 |

允許與拒絕由中央 ACL 和節點本機 policy 共同判斷，取兩者交集。中央管理員不能單方面擴張個人節點權限。節點配對採一次性且短效的 enrollment，節點自行產生私鑰；連線使用各自的 client certificate，支援撤銷及重新註冊。私鑰不送往中央。

使用者身分採成熟 OIDC 登入整合與 server session；節點身分與人類登入分開。cookie 設定、CSRF 防護、事件串流撤權與不同裝置登出是 fleet 模式驗收項。F01 先建立 deny-by-default 授權介面、local owner 與執行權限 gate；M01 完成前 fleet 模式一律不可啟用。M01 再整合 OIDC／多人 ACL，缺身分或授權設定仍須拒絕啟動。現有執行中服務帳密與隧道不在規劃工作中變更。

分享設定及 grant 的核准／擴權只能由已驗證的節點 owner 執行。中央管理員不能藉改 owner、重新 enrollment 或重發 certificate 替換本機 policy；移轉所有權需本機重新確認。中央允許而本機拒絕、本機允許而中央拒絕，兩者都必須沒有執行副作用。

### 3.2 身分與操作契約

| 實體 | 必要欄位／意義 |
| --- | --- |
| Node | `node_id, workspace_id, owner_id, incarnation, key_id, capabilities, last_seen, policy_version`；重註冊與重啟可區分 |
| ProjectCheckout | `checkout_id, project_id, node_id, canonical_root, repository_identity, revision, mapping_version`；一個 Project 可有多個 clone，路徑由節點解析 |
| RuntimeBinding | `node_id, runtime_instance_id, provider_session_id, pane_id, run_id, goal_epoch_id, evidence_refs`；pane 名稱不可全域唯一化 |
| ExecutionGrant | `grant_id, issuer, subject, node_id, checkout_id, actions, expiry, policy_version, limits, revoked_at`；精確綁動作及目標 |
| Job / Run | Job 保存 outcome、依賴、scope、驗收；Run 保存某次派工、租約、模型、child identity、結果與證據 |
| AuditEvent | actor、核准者、grant、policy、target、操作摘要／hash、允許或拒絕、接收／開始／停止結果、時間 |

動作至少分為 `status.read`、`evidence.read`、`agent.start`、`agent.message`、`run.stop`、`shell.execute`。metadata 分享也要授權；只讀不代表沒有隱私風險。每次列出、搜尋、串流、通知、下載證據與寫入都核對 Project 權限。

短效操作憑證綁定特定節點、run、checkout mapping version、動作與 payload hash，防止授權後換目標。啟動 Agent 可能造成寫入與額度支出，不因操作名稱是「傳訊」而降低授權級別。前端的 `confirm_dangerous` 不能代替後端核准。

### 3.3 隔離、斷線與停止

- shared worker 使用專用 OS 身分與經實機驗證的 sandbox／VM。只掛載授權 checkout 及必要工具，限制網路與憑證；worktree 用於避免修改衝突，不能代替 sandbox。
- 本機節點負責最後一次核對及執行。若 Herdr 只能先讀 pane 再另呼叫 prompt，無法保證中間未換 runtime，該能力保持不可自動遠端操作，直到 wrapper 可原子核對受管 run。
- 領取工作使用交易；節點執行前先持久記錄 `run_id + operation_id`。重送同一操作回傳原 receipt，不能再啟動一次。
- 憑證到期禁止新操作。執行中的工作另有 lease、最長時限與本機 watchdog；擁有者明定失聯後停止或在有界時間內繼續。UI 依實際回報顯示停止結果。
- 離線、lease 到期、HTTP timeout 都不足以證明原工作已停止。原 run 未確認終止或未被可靠隔離前，不釋放相同工作範圍的 writer ownership 重新派到另一台。
- 可靠隔離必須證明舊 run 已無法寫入同一邏輯資源，包含共享 repo、遠端 API 與寫入憑證。只關閉本機 checkout 或 VM 失聯不算；無法強制隔離時只接受精確停止確認。watchdog 到期須嘗試終止受管 process tree，失敗保留待確認狀態。
- 「要求停止」「停止已確認」「停止失敗／待確認」分開；只能停止受管或另行授權的 process tree。停止不能撤回已產生的副作用。
- 提供中央暫停新派工、節點本機撤銷遠端控制、指定 run 停止三種入口。撤權後新動作立即拒絕；失聯時以本機 lease 上限約束，不承諾瞬間終止。
- 獨立 `/goal` 監工保留 `notify_only`。排程服務與監工使用不同身分；監工 verdict 不直接產生執行授權。

## 4. 通知：先可信，再即時

### 4.1 事件與人話文案

| 事件 | 觸發證據 | 預設提醒 |
| --- | --- | --- |
| `agent.turn_completed` | 精確 session／run／turn 的結束事件 | 「Agent 已完成這一輪」；不是 idle、pane 消失或沒新輸出 |
| `agent.goal_completed` | 指定 epoch 的 runtime complete | 「Agent 回報目標完成」；與產品驗收分列 |
| `decision.waiting_human` | 新卡或真正轉入等待人類的版本 | 「有一項問題需要你決定」；同一發現沿用原卡與提醒 |
| `work.verified` | 當前 scope/revision 的全部必要 acceptance/gate 有有效證據 | 「項目已通過驗收」；僅確認 Roadmap 結構不觸發 |
| `work.verification_invalidated` | scope／revision 改變或證據失效 | 「先前驗收需要重新確認」；保留原紀錄 |
| `run.failed` / `quota.blocked` | 受管 run 的精確失敗／額度阻塞事件 | 一次顯示原因與下一步；不把所有 blocked 都變 Decision Card |
| `node.offline` | 心跳超時狀態轉換 | 「電腦已離線，執行狀態待確認」；短暫重連去抖動 |

沒有可靠 turn ID 的來源可顯示 Agent 狀態，但不產生已確認本輪完成事件。沒有可靠 epoch 時保留觀測、標記未驗證配對；不能以一般 updated timestamp、objective 文案或 cwd 補成 epoch。

里程碑／整個專案完成通知沿用相同驗收規則：確認當前 scope 的必要子項及上層驗收全部滿足，並綁定該 scope revision；不因最後一個 Agent 結束就宣告專案完成。發布另需 release 證據。

### 4.2 持久資料與 API 草案

- `DomainEvent`：`event_id, sequence, schema_version, workspace_id, project_id, node_id, provider, runtime_session_id, run_id, goal_epoch_id, source_event_id, event_type, occurred_at, observed_at, evidence_refs, safe_summary, source_kind`。依事件種類要求必要身分。
- 來源唯一鍵含事件產生時的 origin incarnation、source 與 source event ID；原值隨本機 journal 持久保存，重啟後重送不能換成新的 boot identity。此次傳輸連線／boot identity 另欄保存。source 沒 ID 時僅採可證明穩定的紀錄位置／順序。事件順序用持久 sequence，機器時鐘不當排序或 epoch 權威。
- 後端持續執行有界的 adapter event collector，保存每來源 cursor 並在重啟後補讀；節點 wrapper 可主動送可靠 lifecycle 事件。是否有人打開 Agents 頁不影響收集。來源僅有快照而未保留 turn 事件時，明示觀測缺口，不推算遺漏的完成輪次。
- 業務狀態與 outbox 同一交易提交。dispatch 可重試；通知依 `event_id + recipient_id` 唯一化。MonitorEvent 與通知不是一對一。
- `Notification`、每人已讀、各裝置投遞 receipt 分開保存；單機版也使用 local owner recipient，之後可遷移。
- `VerificationRecord` 保存 `scope_revision, acceptance_results, required_gate_results, evidence_refs, verifier, verified_at, supersedes`；接受／失效判斷及事件在 server 執行。
- 草案 API：`GET /api/notifications?after=&limit=`、`GET /api/notifications/stream`、`PATCH /api/notifications/{id}`、`GET/PUT /api/notification-preferences`；驗證紀錄在 Project scope API 提交，必須驗證 actor authority。
- 列表回傳同一 snapshot 的 `high_watermark` 及分頁 cursor，SSE 從此 watermark 接續，涵蓋列表讀完到串流建立之間的新事件；分頁查詢固定邊界。SSE 帶 `id:` 與 `Last-Event-ID` 補播；游標過期要求重新同步。首次載入只填通知中心，重連累積提醒可合併；輪詢只作降級。
- 新增 API 的 Pydantic、OpenAPI/schema fixture、前端 TypeScript 及 contract tests 同步更新。上述是設計草案，不宣稱現有 endpoint 已可呼叫。

### 4.3 三種通知介面

| 交付 | 使用體驗 | 限制與驗收 |
| --- | --- | --- |
| 站內通知中心 | 全域鈴鐺、未讀、按專案／事件篩選、點擊返回詳情、安靜時段 | 不依賴目前選中專案；以 `aria-live` 提示、不搶焦點，390px 可使用 |
| 網頁開啟時的系統通知 | 主動按「啟用通知」後請求權限；背景分頁可提醒 | denied／unsupported 時保留站內通知；多 tab 協調＋event tag／receipt 減少重複 |
| 關頁推播 | Service Worker、每裝置 subscription、server 投遞、撤銷與 TTL | 需要穩定 HTTPS origin、相容瀏覽器與系統允許；不能承諾瀏覽器完全退出／OS 禁止背景後仍準時送達 |

預設鎖定畫面只顯示一般摘要，不含 terminal、prompt、絕對路徑或憑證。詳細標題由使用者選擇。點擊通知只導航，之後重新授權，不能直接傳訊或執行命令。

站內紀錄是可查核來源；OS 通知當機邊界無法保證 exactly-once。UI 分開記錄已入列、已提交推播、失敗、已讀；推播服務接受不等於使用者已看到。推播 subscription 與金鑰只放部署私密儲存，撤權／登出需清除裝置訂閱及私密快取。

## 5. 機器與 AI 額度調度

### 5.1 先建立兩本資源帳

| 資源帳 | 記錄方式 | 不確定時的處理 |
| --- | --- | --- |
| 機器 | OS、工具／runtime 版本、可用 CPU/RAM、並行 slot、已掛載 repo、使用時段、owner policy | 心跳過期停止新派工，已跑工作標未知並核對 |
| AI 帳號 | provider、account/quota bucket、API／訂閱類型、允許的模型與專案、限制窗口、reset 時間、資料來源與 observed_at | 沒有官方可讀資料就標手動／估算／未知，不假裝有精準剩餘百分比 |

同一帳號在三台電腦登入仍屬於同一額度池；不同人的帳號只有本人或組織已明確允許的工作可用。憑證留在節點或核准的 secret store，中央只保存不含秘密的 credential reference。provider 是否支援自動化、用量查詢與用量上限，要以各 adapter 的官方介面與實際權限驗證，不能推論所有訂閱都可共用或自動切換。

容量、訂閱限制、API 金額、tokens、rate limit 各用自己的單位與窗口；tokens 不能直接當剩餘訂閱比例。區分要求模型、啟動模型、觀測模型，以及估算成本、已觀測用量、provider 結算成本。

同一帳號在控制台外仍可能消耗額度，本地帳本不能充當全帳戶餘額。snapshot 保存 `valid_until`，過期重取或降為未知；admission 留緩衝。provider 拒絕後暫停該 pool 新派工並核對原因，不透過換機器反覆撞額度限制。

### 5.2 工作包與選擇順序

每個 `JobSpec` 明定 outcome、repo revision、讀寫範圍、依賴、驗收、工具需求、模型要求、最大時間／用量、停止條件、交接資料與 owner。沒有完成定義的工作先整理，不進自動佇列。

依賴明列需要 `artifact_ready` 還是 `verification_passed`，並綁定 revision；Agent 完成本輪不能一律解鎖下游。拒絕循環依賴；前置取消、證據失效或 revision 改變時重新 admission，已啟動的下游結果標待重驗，不沿用舊證據。

排程先做硬限制檢查：授權 → 節點能力／線上 → 依賴已滿足 → scope 沒衝突 → 帳號與模型可用 → 容量及預算可預留。符合後才按優先級、截止風險、等待時間、專案公平性及資料已在節點上的成本排序。初期使用可解釋規則，不用 LLM 決定每次排程。

| 工作 | 初始分配策略 |
| --- | --- |
| 格式化、lint、既有測試、build | 一般 worker 執行工具，通常不需模型 |
| 清楚界定的小修改、摘要或文件整理 | 先用經此類任務驗證可用的較低成本模型 |
| 架構、高耦合修正、棘手 debug | 使用有足夠成功紀錄的高能力模型，降低並行衝突 |
| 驗收／安全審查 | 獨立 reviewer 與可重現測試；檢查結果不單憑另一個 Agent 認可 |
| 同專案多路工作 | 契約先定、獨立 checkout；同一共享寫入範圍只有一個 owner |

要求特定模型的 Job 不默默降級。只有 Job 的預授權 fallback 允許時才可換模型，保留原因、舊／新 run 與驗證證據。簡單模型失敗先分類原因；環境失敗不靠換更貴模型解決。以一組代表性工作比較驗收成功率、返工、總成本與時間，再調整分配。

硬模型要求的自動工作只能派給可提供可信 runtime 模型證據的 adapter；若須先啟動才可辨識，取得 receipt 前不提交實質工作。取得不到就標未知並依有界政策停止／等待。發現 mismatch 時停止後續派工，保存已發生用量與結果並按預授權策略處理；失敗或不符不自動視為成本退款。

### 5.3 預算預留、失敗與節省

- 新增 `QuotaSnapshot`、`BudgetPolicy`、`Reservation`、`UsageObservation`。派工時在同一交易預留 account bucket、project budget 與 node slot，避免不同節點同時花掉同一餘額。
- 本地预算帳保存已觀測消耗、未結算估算及有效預留，不能重複計算或提早釋放。只有核對該 snapshot 覆蓋哪些 run 後才與 provider 最新用量對帳；來源窗口與延遲必須保留。
- quota 未知時禁止無限自動派工。可由擁有者預先設定有界 pilot 預算／並行與最長時間；沒有這種授權就排隊等資料。
- runtime 可停止時設軟停點與保留餘量；精準硬金額上限只有 provider／隔離帳號確實可強制時才宣稱。既有個人 CLI 或延迟計費只能做軟限制與停新任務。
- 額度耗盡先 checkpoint；依允許策略等待重置或以新 run 交接。先確認舊 run 停止才釋放寫入 ownership；不要把同一段完整 transcript 不斷複製給新模型。
- checkpoint 包含 commit／diff artifact、未完成驗收、已跑／未跑測試、剩餘問題及目標 epoch。派工不假裝父 goal 已自動掛到 child。
- 同一 source event 重送不增加預留或重跑工作。程序重啟後從 journal 對帳；不確定的 run 保留預留上界，待核對後調整。
- 若 journal 與已失效的啟動權限可證明 offer 未接受且不會再啟動，原子釋放該 reservation，避免 crash 永久占滿容量。遲到 receipt 不得復活已失效 attempt；已啟動但 ACK 遺失者走核對路徑，不能當未啟動退還。
- 每 run 有總時限、無進展 checkpoint 時限及最大重試次數。持續 heartbeat 不等於進展；沒有 terminal 輸出也不等於死亡。逾限先取有界 checkpoint／runtime 證據，再依 grant 要求停止；未確認停止不重派相同 writer scope。
- 一般狀態以程式事件處理；語意監工只在新 checkpoint、證據變動或有界巡查時讀必要差異。保留 cadence 安全上限，避免每幾秒請大模型重新讀全部歷史。
- pilot 先每台一個可寫 run，再用實測提高並行；把重要工作的預算保留做成明確 policy，不用「有閒置額度就一直派」。

排程先提供 dry-run：「建議哪台、哪個帳號、何種模型、預估成本與等候原因」。dry-run 不呼叫 runtime。正式自動派工只套用預先核准範圍內的規則。

## 6. 公開版、模板與內部部署

建議 organization 維護公開 `agent-control-center`，公開共同核心、節點協定、權限／通知／排程實作、測試與範例。內部另設 private deployment repo，保存不含明文秘密的部署宣告、版本鎖定、內部 adapter 及組織政策；機密仍放 secret store／未追蹤設定。

初期維護一份通用核心。內部部署引用公開 release/tag 或 image digest，升級經私有環境驗收；通用修正回到公開核心。避免先複製兩份完整產品再長期人工同步。公開程式碼與內部實際控制台、資料、登入是不同的發布範圍。

GitHub Template 適合建立自己的起始 repo，不提供自動升級；同一套軟體跨機器安裝應使用相同 release。建議核心 repo 配合部署範例即可，日後有足夠需求再抽成 deployment template。GitHub public repo 的 fork 仍是 public；私有部署 repo 必須獨立建立，不能把 public fork 當私有內部版。

公開發布工作包括：乾淨環境安裝、Python/Node 依賴可重現、空資料庫啟動、單機／fleet 限制說明、安全啟動設定、授權檔、貢獻／安全回報說明、CI、秘密與個資檢查、第三方檔案來源檢查。首次 CI 使用 GitHub-hosted runner，公開 PR 不直接落到團隊個人電腦或帶內部憑證的 worker。

LICENSE 已選 MIT；公開 owner 已選 danny0926。公開產品原始碼與未追蹤的私人部署資料分開，第一階段使用單機模式。

## 7. 派工與整合順序

採最多三個有界執行分工加一個整合 owner。每張工作單必須附 scope、禁止修改範圍、依賴、驗收、測試及交付證據；只對可獨立的工作平行。

| 角色 | 本次規劃分工 | 後續實作責任 |
| --- | --- | --- |
| Notification / UX | 已完成事件與通知方案靜態查核 | 通知 UI、prefs、SSE client、桌面／push；以契約 fixture 起步 |
| Fleet / Security | 已完成本機權限與跨節點方案靜態查核 | node agent、grant、隔離、receipt、停止與拒絕測試 |
| Resource / Scheduler | 已完成模型證據與資源調度方案靜態查核 | capacity/quota ledger、dry-run、scheduler、fault tests |
| Integration owner | 整合前置缺口、里程碑、發布與驗收 | 共用 models/store/main/types、migration、跨層整合、驗收及發布交接 |

本次 sub-agent 任務是對話內可核對的規劃工作，並不宣稱已在 Herdr 註冊或掛載獨立 `/goal`。未來若 UI 顯示實作 child run，必須從 runtime 取得身分與實際模型證據。

共用契約先由 integration owner 建立；`models.py`、`store.py`、`main.py`、`types.ts` 同批只有一個寫入 owner。功能逐步拆到專屬模組／router，分工在各自檔案或隔離 worktree 交付；整合後才算跨 API 契約完成。

### 7.1 工作包與退出條件

以下 ID 是可派工的規劃工作包，不是已建立的 runtime Job 或 GitHub Issue。

| ID／負責角色 | 交付與依賴 | 驗收 gate |
| --- | --- | --- |
| F01 Integration + Security | local owner、預設拒絕的授權介面、execution profile；處理預設 bypass | M01 前 fleet 不可啟用；所有寫入路由直接呼叫有拒絕測試；單機登入有回歸測試 |
| F02 Integration | 穩定 epoch、完整 TaskStop 鏈、模型三欄、monitor 歷史 migration | 同文重設分輪、heartbeat 不換輪、錯 task/result 不停止、observed 缺失不宣稱符合 |
| F03 Integration | identity/schema v1、migration、常駐有界 event collector及cursor、domain event/outbox、VerificationRecord；依 F02 | 無任何瀏覽器時仍收事件；舊資料保留 unknown 與歷史；crash/replay、不完整／過期證據測試 |
| N01 Notification + Integration | 通知中心、prefs、read state、global SSE/replay；依 F03 | 首次歷史不轟炸、同發現去重、server 重啟補播、換專案不漏自己訂閱事件 |
| N02 Notification | 網頁開啟時桌面通知、tab 協調、一般摘要；依 N01 | granted/denied/unsupported、三分頁、安靜時段、點擊正確目標與鍵盤操作 |
| O01 Integration | 公開安裝／發布骨架；與 N01 並行，發布依 F01 | 空環境完整啟動與基線測試、無敏感資料、license/owner 定稿後才 publish |
| M01 Security + Integration | 使用者 ACL、node enrollment、撤銷、checkout、observer sync；依 F01/F03 | 兩人兩節點同名 pane 不串線；列表／事件／證據／通知／串流均拒絕越權 |
| R01 Resource | capacity/quota snapshots、手動／未知展示；依 F03，以 M01 fixtures 並行 | 同帳號跨機同bucket、來源時間／單位清楚、權限過濾、stale 不當可用 |
| M02 Security | 本機 grant、受管 runner、sandbox、run journal/watchdog；依 M01 | 不碰其他使用者檔案／程序；payload換目標、過期、撤權、重播均拒絕；停止有實機證據 |
| R02 Resource | Job DAG、scope ownership、budget reservation、dry-run；依 R01/F02 | 排程可解釋、不能超預留、依賴revision/種類與循環拒絕、scope排隊、未知額度有界、公平性回放 |
| R03 Resource + Security | 有界自動派工、lease/receipt、checkpoint/handoff；依 M02/R02 | 兩節點競領只起一run；ACK遺失不重複寫；模型未知/不符與無進展逾時受控；停止鏈完整 |
| N03 Notification | 穩定 origin 的 Web Push、裝置撤銷、投遞狀態；依 N01/M01 與部署決策 | 關頁實測、subscription過期、登出撤權、TTL、敏感payload與投遞失敗測試 |
| V01 Integration + reviewer | 端到端 pilot、成本／品質量測、備份還原、發布限制；依以上所選發布範圍 | 取得各項 gate 的直接證據，無 false-complete／越權；未跑能力明列不發布為支援 |

R01／R02 可先以 M01 fixture 平行開發；向真實多人部署前仍須通過 M01 整合驗收。dry-run 候選節點、帳號、成本及拒絕原因也需 ACL 過濾，不能透過排程結果洩漏其他人的資源。

### 7.2 四個可交付里程碑

1. **MVP-A：單機可靠通知與可公開的安全骨架。** F01–F03、N01–N02、O01。最先讓使用者得到完成／驗收提醒；先修身分證據，禁止假完成。
2. **MVP-B：團隊唯讀總覽。** M01、R01，補多人通知 ACL。能看授權的多台電腦及額度來源，不需要先交出控制權。
3. **MVP-C：受限自動工作。** M02、R02–R03。先 dry-run，再在兩個隔離 worker 的合成專案實測，最後由擁有者對真實專案開啟有界 grant。
4. **MVP-D：關頁提醒與可維護部署。** N03、V01。穩定 HTTPS 部署、推播、完整恢復與成效量測。N03 在 M01 與部署条件具備後可與 M02/R02 平行。

每個里程碑獨立驗收與 release note，不必等待全部多機功能才公開本機版。這是依賴順序，不是日曆承諾；完成 F01/F02 與第一個 notification slice 後，再以實際速度估後續工期。

## 8. 必跑驗收矩陣

| 範圍 | 直接證據／反例 |
| --- | --- |
| 通知真實性 | idle、失聯、monitor terminal 不觸發 work.verified；同文新 goal 各自通知；同一事件十次重播僅一筆收件匣紀錄 |
| 驗收證據 | 缺一條 acceptance、revision 不符、gate 未跑／stale 均不可 verified；失效後通知更正並保留歷史 |
| 通知持久性 | 無瀏覽器仍收集；DB 提交後 crash、ACK遺失後節點重啟重送journal、列表到SSE間插入事件、分頁中新事件、游標過期、三分頁與已讀同步 |
| 跨機器權限 | 兩使用者×兩節點×同名 pane；父／子專案、猜 ID、直接 API、串流中撤權；中央/本機任一拒絕皆無副作用；改owner/重新配對不得擴權；拒絕有audit |
| 本機隔離 | 真實 OS 下嘗試讀寫未授權路徑、連未允許網路、讀別人憑證、操作未受管 process；都應被底層隔離拒絕 |
| 執行可靠性 | 領取後 crash、啟動後 ACK 遺失、雙節點競領、lease 過期、舊 attempt 晚回報、節點重新註冊；不得重複有效寫入 |
| 停止與恢復 | 精確 process tree 停止、watchdog失敗、heartbeat正常但無進展；既有互動Agent不受影響；未停止/無可靠fencing不重派；有權相容節點才可接checkpoint |
| 額度與模型 | 同帳號跨三機競爭及控制台外消耗最後預算、reset/遲到結算/未知、未啟動預留釋放與遲到receipt、模型不符/無證據、refund重播；不超賣、不偷偷降級 |
| 工作依賴 | 循環拒絕；artifact與驗收兩種解鎖、取消/證據失效/revision改變重新判斷；下游不得沿用過期通過結果 |
| 效率 | 代表性工作組對照手動分配，報告驗收成功率、返工、總成本、等待／交付時間、人工分鐘；先量基線再定改善目標 |
| 公開安裝 | 乾淨環境、不帶私有.env／data／Herdr，依README安裝可啟動基本功能且缺失能力清楚；release可回退、DB可還原 |

實作每批必跑：`python -m pytest apps/api/tests`、`npm run test --workspace apps/web`、`npm run build --workspace apps/web`。在測試自己的 temp DB 與明確測試身分下執行，不使用既有工作中的 pane 當 fixture。

通知增加隔離的 Playwright 情境；真實 desktop permission／OS notification、關頁 push、兩節點故障與 sandbox 另跑實機驗收。單元測試只能證明涵蓋的邏輯，不能代替跨機器或瀏覽器平台支援。

## 9. 實作時才需補齊的部署資料

| 事項 | 規劃預設 | 影響哪一步 |
| --- | --- | --- |
| 公開 owner 與 license | MIT；danny0926 | O01 公開發布 |
| 機器／OS 清單 | 第一階段只用擁有者自己的 Windows 電腦；多機測試延後 | M02/V01 實機矩陣 |
| AI 帳號與可查額度介面 | 手動／未知可誠實展示；不搬憑證，不推定共享 | R01 provider adapter、R03 真實預算 |
| 中央登入、穩定網址與資料保存位置 | 自架、摘要最小化；不擅自開付費服務或重啟既有 tunnel | M01 遠端pilot、N03 push |
| 第一批分享專案與控制範圍 | personal observer；shared worker 按本機owner grant | 真實跨機執行 |

用一份部署設定表集中收集這些資料，不重複對同一決策開卡。已核准 scope 內的日常派工由規則執行，只有擴權／新增費用／不可推導的產品取捨才升級。

## 10. 參考與規劃階段的歷史驗證範圍

- [GitHub Template](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-repository-from-a-template)：建立獨立歷史的起點，不是部署升級機制。
- [GitHub Fork visibility](https://docs.github.com/en/pull-requests/reference/forks)：public fork 保持 public；內部部署應用獨立 private repo。
- [GitHub runner routing](https://docs.github.com/en/actions/reference/runners/self-hosted-runners)：以能力及空閒狀態分配工作的參考。
- [GitHub Actions 安全](https://docs.github.com/en/actions/reference/security/secure-use)：自架 runner 不應直接承接不可信公開 PR 的程式。
- [Notifications API](https://developer.mozilla.org/en-US/docs/Web/API/Notifications_API/Using_the_Notifications_API)：使用者授權、安全 origin 與平台限制。
- [Push API](https://developer.mozilla.org/en-US/docs/Web/API/Push_API)：Service Worker／裝置訂閱與背景推播；關頁通知需另建投遞能力。

以下是最初「只交付規劃」階段的歷史紀錄，不代表目前實作階段未跑測試。最新整合驗證由當次交付／release notes 分列，不能沿用此歷史段落判定狀態。

規劃階段已做：三個有界 sub-agent 的規格／程式／測試靜態查核、主 Agent 複核關鍵實作與 Git 狀態、官方通知及 GitHub 文件核對；三組對整合草案再次審查，12 項實質修正已納入。文件本機連結、13 張工作包的唯一 ID、索引入口與 Markdown 格式已檢查。

規劃階段未跑：API／前端功能測試、build、跨機器實測、瀏覽器通知或 push；當時交付只有計畫文件。後續 MVP-A 已開始程式實作及測試，但不能把舊基線或局部綠燈當成所有多機器功能已驗證。

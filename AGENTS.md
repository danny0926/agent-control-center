# Agent Control Center Agent Guide

本產品是獨立的多專案 Agent 管理控制台。核心不得依賴任何單一來源專案的領域語意；公開文件只使用明確標示的合成示例。

## 遠端存取與本機設定

帳密的唯一來源是專案根目錄的 `.env`（`CONTROL_CENTER_USER` /
`CONTROL_CENTER_PASSWORD`）。app 啟動時由 `control_center/_bootstrap_env.py`
自動載入；已存在的環境變數優先。啟動或重啟服務時不要自行產生新帳密，
也不要在啟動指令裡覆寫既有設定。`.env` 與隧道資訊不得進版控。

本機服務預設聽 `127.0.0.1:8765`。若目前透過 Cloudflare quick tunnel
對外提供服務，只重啟 uvicorn，不要重啟既有 cloudflared 進程；quick
tunnel 重啟後會換網址。固定網址需要 named tunnel。

## 核心規則

- 人話在前，技術識別與原始證據放在展開層。
- 活動不等於進度；只有滿足 acceptance 且有足夠證據才能顯示已驗證。
- 匯入預設唯讀。任何回寫來源 repo、GitHub 或 Agent runtime 的能力都必須個別授權並留痕。
- Project 與 Subproject 使用同一模型；子專案以 `parent_project_id` 表示。
- 專案資料、權限、文件、Agent session 與 evidence 必須隔離。
- 合成與 demo 資料必須明確標示，不能看似即時來源。
- 文件與使用者可見文案以繁體中文為主，程式碼維持英文識別名稱。

## 變更前

先讀 `docs/PRD.md`、`docs/FRONTEND_SPEC.md` 與受影響測試。跨 API 邊界時同步更新契約與前後端型別。

## 驗證

- API：`python -m pytest apps/api/tests`
- Frontend：`npm run test --workspace apps/web`
- Build：`npm run build --workspace apps/web`
- 所有回報必須分列已跑與未跑驗證。

## Codex `/goal` 獨立監工

- Control Center 只登記監工、擷取有界證據、保存 verdict，並在必要時建立 Decision Card；不把活動量當成產品進度。
- 每個監工必須精確綁定 Project 本機路徑、Herdr Codex pane ID 與 Codex goal session ID。任何一項無法唯一核對就停止，不猜測替代目標。
- Pilot 固定為 `notify_only`：監工不得向受監看的 Agent 傳訊、注入按鍵、修改其工作目錄或替它執行工作。
- 語意巡查由獨立 Claude pane 使用 `monitor-agent-goal-herdr` skill 執行；建立 monitor record 不代表排程已啟動。
- `needs_human` 只用於現有 PRD、程式、測試與既有決策無法推導的實質問題；相同發現不得重複製造決策卡。
- 監工讀取 transcript、terminal 與 Git 時只取完成判斷所需的最小範圍，外部顯示前須避免洩漏憑證與個資。
- Reconciler 可自動恢復同一 pane＋goal session 的既有 monitor；只有 Herdr 明確提供 `agent_session_id` 時才可自動建立新 monitor。僅憑 cwd、最近更新時間或「看起來只有一個」不得猜測配對。

## 跨代理 Goal 與派工證據

- Claude 與 Codex 的 `/goal` 都可以作為可見目標，但同一 session 每次重設 goal 都是不同 epoch；不得只用
  session ID 合併歷史。
- 父 goal 不等於 child goal。每筆派工必須分開顯示 parent goal、child runtime identity、要求模型、啟動
  模型、實際模型、Goal 掛載證據、Herdr 可見性與停止／完成事件。
- 從 Claude Bash 發現的 `codex exec` 若沒有 child session identity，只能標為 `untracked_runtime`／
  `未驗證 child Goal`。啟動事件不能永久顯示為 working；缺少後續事件時顯示「已啟動，狀態未知」。
- TaskStop 必須用 tool-use → background task ID → stop result 的精確事件鏈更新；重派產生新 run，不共享
  前一輪狀態。模型啟動參數與 runtime 實際回報必須分欄，不能互相冒充。

# Agent runtime adapter 架構

最後更新：2026-09-13

## 目的

Control Center 必須能回答三件事：哪些 Agent 真的存在、現在處於什麼狀態，以及人如何安全地讀取與傳送
訊息。它不能只看到 `codex.exe` 或 `claude.exe` process 就猜測任務，也不能把 terminal buffer 說成完整
conversation history。

## 目前已實作：Herdr adapter

本機 Herdr 0.8.2 提供 socket API。Control Center 從 Herdr 環境啟動時使用：

```text
herdr workspace list                 → workspace ID、名稱與整體狀態
herdr agent list                     → provider、pane ID、cwd、working/idle/blocked/done
herdr agent read <pane>              → 最近終端輸出（不是完整對話）
herdr agent prompt <pane> <message>  → 傳送訊息給該 Codex／Claude
```

Control Center 只將 `cwd` 位於 Project `source_path` 內的 session 顯示在該專案。狀態每五秒重新讀取；沒有
結構化 task/checkpoint 時顯示「尚未回報結構化任務名稱」，不從輸出內容猜測。

讀取輸出時使用 `recent-unwrapped` 並做常見 token／password 遮罩。畫面固定標示它只是最近終端輸出，不能
恢復已離開 alternate screen 的訊息，也不等於 provider 的完整 conversation。

## Codex

### 經 Herdr（目前使用）

Herdr 辨識 pane 中的 Codex，提供 list/read/prompt。這是本機 CLI Agent 的首選路徑，因為 workspace、cwd、
pane 與 lifecycle 已在同一個介面內。

### Codex app-server（後續直接 adapter）

本機 Codex CLI 提供實驗性的 `codex app-server`，支援 stdio、Unix socket 與 WebSocket，也能產生 JSON
Schema／TypeScript bindings。直接 adapter 應使用獨立 loopback app-server、capability token 與明確 thread
授權；不能掃描 `~/.codex` session 檔或連到 Codex desktop 的私人 control socket。

## Claude

### 經 Herdr（目前使用）

互動式 Claude Code pane 使用相同 Herdr list/read/prompt 介面，前端不需要理解 Claude TUI 的控制字元。

### Claude background session（後續直接 adapter）

目前本機 Claude CLI 支援 `--background`、`agents`、`logs`、`attach` 與 `stop`。後續 adapter 可管理由
Control Center 自己啟動的 background session；既有互動 session 仍以 Herdr 為準。不得直接解析 Claude
內部 session storage。

## 共同前端契約

```text
list_sessions(project)
get_recent_output(session)
send_message(session, text)
request_checkpoint(session)
focus_terminal(session)
```

共同欄位包含 provider、workspace/pane、cwd、status、task summary、observation source 與 limitations。
`working` 只代表 runtime 正在工作，不代表 Work Item 有進度；`done` 只代表一輪互動完成，不代表產品成果
已驗證。

## 安全邊界

- Project 以 `source_path` 隔離 session；跨專案傳訊必須從 portfolio 明確選擇目標。
- 傳送前顯示 provider、workspace、pane 與 cwd，避免訊息送錯 Agent。
- `blocked` 時先顯示 terminal 問題，不自動回答權限或高風險確認。
- 不記錄完整 terminal 到 git；本機快取需可清除並有大小上限。
- 直接 adapter 只管理 Control Center 建立或使用者明確授權的 session。
- 終端即時檢視使用同源 SSE。後端固定間隔讀取有界且已遮罩的 Herdr 快照，只在內容變更時推送，並在每輪重新確認 pane 仍位於目前 Project；切換路徑或離線後立即終止該串流。
- Claude TUI 可能在應用程式內部停留於舊位置，即使 Herdr terminal scroll offset 為零。若畫面出現 `new messages (ctrl+End)`，adapter 必須回報 `is_at_latest=false`，前端不得稱為最新輸出；Pilot 不自動注入 Ctrl+End。

## `/goal` monitor adapter

Monitor 不是另一種 terminal scraper。它以三個不可互換的識別為邊界：Project `source_path`、Herdr pane ID、Codex goal session UUID。後端只從本機 Codex session metadata 找出 cwd 位於該專案的 `/goal`，再確認 Herdr pane 仍是同路徑的 Codex Agent；不唯一或不一致就回報 error。

每次 snapshot 只包含目前 goal 狀態、Herdr 最近輸出的有界片段，以及 read-only Git HEAD/status/diff stat。真正的「是否偏離、卡死、需要人」由隔離的 Claude monitor 判斷並寫回 event；Control Center 不從 working/idle、token 或檔案數自行推算產品進度。Pilot 的 monitor API 不提供對目標 pane 傳訊的能力。

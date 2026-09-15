# Agent Control Center

一個本機優先、以證據判定進度的多專案 Agent 管理控制台。

目前單機切片支援：

1. 查看所有已加入的專案。
2. 唯讀掃描本機 Git repository。
3. 在匯入前預覽系統找到的文件、規則、測試與產品敘述。
4. 確認後將專案加入獨立 workspace。
5. 從常見 Markdown Roadmap 產生人話優先的可折疊成果樹草稿。
6. 由 owner 確認計畫結構；文件自稱完成仍不等於已有驗證證據。
7. 經 Herdr socket 顯示同專案 Codex／Claude 的即時狀態，以 SSE 串流更新最近輸出並傳送訊息。
8. 顯示最近可辨識的人類指派；Agent 工作中無法讀歷史時，自動降級讀取目前可見終端。
9. 持久通知中心、已讀與安靜時段；網頁開啟時可主動授權桌面提醒。
10. 擁有者對最末層成果逐條核對驗收與必要檢查，將紀錄綁定已提交版本、證據 hash 與有效期限。

通知與驗收已通過本機與合成瀏覽器流程驗證，範圍見 [MVP-A 交付紀錄](docs/MVP_A_DELIVERY.md)。`owner_attested` 表示擁有者確認證據，系統不會因此宣稱已自動執行測試。詳見[目前 API 契約](docs/API_CONTRACT.md)。

## 本機啟動

需要 Python 3.12+ 與 Node.js 20.19+（Node 20）。從專案根目錄安裝：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
npm ci
npm run build --workspace apps/web
.\.venv\Scripts\python.exe -m uvicorn control_center.main:app --app-dir apps/api --host 127.0.0.1 --port 8765 --no-proxy-headers
```

build 後網站與 API 都由 `http://127.0.0.1:8765` 提供。需要前端開發模式時另開 terminal 執行 `npm run dev:web`，位址為 `http://127.0.0.1:5173`；完整安裝、Linux／macOS 指令及代理設定見[部署文件](docs/DEPLOYMENT.md)。

首次安裝可參考 `.env.example` 建立未追蹤 `.env`；既有安裝保留原檔與帳密。遠端開放前，由該安裝的擁有者設定自己的
`CONTROL_CENTER_USER` 與 `CONTROL_CENTER_PASSWORD`。`.env`、本機資料庫、
執行紀錄與隧道設定都不應提交到 Git。帳密只填一半會拒絕啟動；完全未設定時僅允許 loopback peer。代理／tunnel 也可能從 loopback 連入，因此對外服務必須設定完整帳密並使用 HTTPS。

執行動作預設全部拒絕。`CONTROL_CENTER_ALLOWED_ACTIONS` 需明列 `agent.start`、`agent.message`、`shell.create`、`shell.execute` 等已授權動作；登入成功或勾選危險指令確認不會取得額外權限。新啟動的 Agent 不再自動加入略過原生權限的旗標；這仍不是作業系統 sandbox。[安全範圍](docs/SECURITY.md)另列限制。

## 多電腦部署範圍

目前每個部署節點各自保存 SQLite 資料，並從該節點可存取的專案路徑、
Herdr socket 與 Agent session 讀取資訊。GitHub Template 可用來建立多個
獨立部署；跨電腦集中管理尚未實作，不能只靠公開一個 repo 達成。未來的
中央控制台需要明確的節點身分、受驗證的節點連線、專案與 session 對應、
以及跨節點權限與證據隔離。

`fleet` 模式目前拒絕啟用；跨機器唯讀總覽、個人 ACL、額度池、派工、受管 worker 與關頁 Web Push 尚未完成。後續順序見[實作計畫](docs/IMPLEMENTATION_PLAN.md)。授權採用 [MIT](LICENSE)。第一階段只在擁有者自己的電腦部署；公開模板位於 [danny0926/agent-control-center](https://github.com/danny0926/agent-control-center)。

## 驗證

```powershell
.\.venv\Scripts\python.exe -m pytest apps/api/tests
npm run test --workspace apps/web
npm run build --workspace apps/web
```

隔離瀏覽器測試會啟動專用測試服務、暫存 Git 專案與資料庫，不使用現有 Agent：

```powershell
npx playwright install chromium
npm run test:e2e
```

API 與瀏覽器測試使用暫存資料庫、明示合成的專案與模擬來源，不向工作中的 Agent 下指令。公開版本不包含私人工作環境的測試快照、專案資料或實機測試腳本。

## 產品邊界

- 匯入預設唯讀，不修改來源 repo。
- 不以 commit、Issue 或 Agent 活動量冒充產品成果。
- 不確定、找不到或過期的資訊會明確標示。
- 依專案保存文件、規則、Agent 與證據；目前仍是單一 owner，不宣稱具有多人 ACL 或 OS 隔離。

詳細規格見 [docs/PRD.md](docs/PRD.md) 與 [docs/FRONTEND_SPEC.md](docs/FRONTEND_SPEC.md)。

## 獨立監工 pilot

「監工」頁可把目前專案的一個 Herdr Codex pane 與精確的 `/goal` session 綁在一起。建立後，把畫面顯示的 `/monitor-agent-goal-herdr <project-id> <monitor-id>` 交給獨立 Claude pane；每次巡查會留下證據與 verdict，需要人決定時自動建立可繼續對話的 Decision Card。

這一版固定為 notify-only：不會自動向 Codex 傳話，也不會因為有 terminal 活動就宣稱產品有進度。Claude skill 的產品來源位於 `skills/monitor-agent-goal-herdr/`；本機啟用副本安裝於 `~/.claude/skills/monitor-agent-goal-herdr/`。週期執行需由 Claude Code 的 `/loop` 另外啟動，僅建立 monitor record 不代表背景排程已開始。

Control Center 會每分鐘自動核對 monitor。同一個 Codex goal 結束後若又收到工作並更新，monitor 會自動恢復；新 Agent 只有在 Herdr 明確回報其 session ID 時才會自動建立，無法唯一配對時會在人話提示中列為「等待配對」。

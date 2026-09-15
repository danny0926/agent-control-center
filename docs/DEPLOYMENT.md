# 安裝與部署

目前支援從原始碼 checkout 安裝單機版。多機器 enrollment、OIDC 與節點授權尚未完成，`fleet` 模式必須拒絕啟動；本文件不表示已支援共享 worker。公開原始碼不會公開你實際部署的資料、控制台或帳號。

## 安裝

使用 Python 3.12 以上及 Node.js 20.19 以上的 Node 20。先取得已核准的原始碼版本並進入專案根目錄。

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
npm ci
npm run build --workspace apps/web
```

Linux／macOS shell 的安裝指令：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
npm ci
npm run build --workspace apps/web
```

這些指令使用 editable install；`control_center` 套件從 `apps/api` 取得，保留專案根目錄的前端產物及本機設定位置。單獨發行 wheel、容器與 OS 上的 Herdr 控制需另行驗證，不能由安裝成功推定。`npm ci` 使用已提交 lockfile；Python 目前使用 `pyproject.toml` 的版本範圍，尚非完全固定的 dependency lock。

## 首次設定

新安裝的擁有者自行建立未追蹤 `.env`，可參考 `.env.example`。若檔案已存在，保留原設定，不覆寫、複製其他人的密碼或在啟動指令另塞帳密。不同安裝各自配置登入資料；秘密不得提交到公開或私有 repo。

| 設定 | 意義 |
| --- | --- |
| `CONTROL_CENTER_MODE=standalone` | 目前唯一支援的部署模式；其他值拒絕 |
| `CONTROL_CENTER_USER`、`CONTROL_CENTER_PASSWORD` | 必須同時設定；缺半組拒絕。對外提供服務前須設定完整帳密 |
| `CONTROL_CENTER_ALLOWED_ACTIONS` | 逗號分隔的執行動作，預設空白、全部拒絕 |
| `CONTROL_CENTER_ALLOWED_ORIGINS` | 額外允許執行變更的瀏覽器 origin；預設兩個本機開發 origin。設為空字串取消額外例外 |
| `CONTROL_CENTER_DB` | 選用的 SQLite 完整檔案路徑；CI 與測試使用暫存資料庫 |
| `CONTROL_CENTER_BACKGROUND_ENABLED=0` | 停用背景巡查；測試使用此設定避免觸及工作中的 runtime |

允許的執行動作為 `agent.start`、`agent.message`、`shell.create`、`shell.execute`、`run.stop`。只有真正需要的動作才加入設定；`run.stop` 權限名稱不表示停止 API 已實作。其他未知動作或萬用字元會使設定無效。這是單機 owner 的執行政策，不能當成跨使用者或跨機器 ACL。

`.env` 由啟動程式載入，已存在的環境變數優先。登入成功不會自動開啟上述執行動作；前端「確認危險指令」也不能代替本機政策。Agent 啟動不再自動加入略過權限的旗標；仍需檢查安裝者自己的 Agent 原生設定。

## 啟動與連線

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -m uvicorn control_center.main:app --app-dir apps/api --host 127.0.0.1 --port 8765 --no-proxy-headers
```

Linux／macOS 使用相同參數，將 Python 路徑換成 `.venv/bin/python`。前端 build 後由 API 提供網站。未安裝 Herdr 仍可啟動基本單機功能；相關 Agent 能力應顯示不可用。

僅供本機使用且未設帳密時，後端只允許 loopback peer。反向代理或 tunnel 也可能以 loopback 連入，因此任何對外部署都必須先設定完整帳密並使用 HTTPS。Basic Auth 是此部署的單一 owner 身分，不能多人共用後視為有個別授權。

不要把 `X-Forwarded-*` 當成登入或任意可信 origin。代理提供的公開 origin 與後端 origin 不同時，將實際網站的完整 HTTPS origin 明列於 `CONTROL_CENTER_ALLOWED_ORIGINS`，例如 `https://control.example.org`，不可使用 `*`、路徑或帳密。origin 檢查與身分驗證都須通過。

上面的啟動指令使用 `--no-proxy-headers`，讓應用收到直接連線 peer。若另行啟用 Uvicorn proxy headers，`request.client` 可能在 middleware 之前已被轉寫；必須將可信代理 IP 明列於伺服器設定，代理也須清除使用者帶入的 forwarded headers，不使用信任所有來源的萬用設定。應用沒有直接讀 forwarded headers 不等於伺服器層已安全配置。無帳密部署不得透過任何 loopback proxy 公開。

開發前端預設 `http://127.0.0.1:5173` 與 `http://localhost:5173`。允許的 origin 只是變更請求的來源檢查；跨 origin 前端若另需 CORS 設定，還需同步核對 API CORS，不由此變數自動推定已支援。

重啟既有服務時保留 `.env` 帳密，只重啟 uvicorn。已運作的 Cloudflare quick tunnel 不要重啟，否則其網址會變；穩定公開網址須另行配置，不在安裝步驟中自動開通。

## 驗證與升級

```sh
python -m pytest apps/api/tests
npm run test --workspace apps/web
npm run build --workspace apps/web
```

用安裝好的虛擬環境 Python 執行 API 測試。測試使用隔離資料庫及模擬 Herdr，不向既有工作中的 pane 發指令。CI 使用 GitHub-hosted runner，不帶部署 `.env` 或內部憑證，跑 Python 3.12、Node 20 與上述三項驗證。

升級前保存目前版本、依賴及一致的資料庫備份；SQLite 若正在寫入，使用其備份機制或先停止 API 再複製，不能只複製部分 WAL 狀態。migration 前先在備份上演練；回退時程式版本與相容資料備份一起還原。多機器與推播目前僅屬後續計畫，未經對應實機驗收不可宣稱支援。

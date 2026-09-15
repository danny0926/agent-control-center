# 安全範圍與問題回報

目前是單一擁有者的本機控制台。多人登入、節點 enrollment、跨機器 ACL、受管 worker sandbox 與分散式停止保證仍需依[實作計畫](IMPLEMENTATION_PLAN.md)交付，不能把現有 Basic Auth 或 cwd 比對當成這些能力。

## 執行與存取邊界

- 執行動作預設拒絕，只有本機設定明列的動作可用；登入、origin 檢查、action 授權與目標歸屬必須各自通過。
- 不在 Agent 啟動時加入 `--yolo` 或 `--dangerously-skip-permissions`。這不會覆寫使用者既有 CLI 的設定；請依實際 runtime 權限判斷。
- shell 的危險指令提示不能限制任意命令，cwd／worktree 也不是作業系統隔離。啟用 shell 或傳訊可能使 Agent 使用目前 OS 帳號及其憑證，僅適合已授權的單機 owner。
- 監工維持 `notify_only`，不可因監工 verdict 自動擴權或接管其他 pane。
- 多人節點控制尚未完成前，`fleet` 模式拒絕啟動；使用同一帳密讓多人登入並不會建立各自權限。
- 瀏覽器變更請求驗證 Origin；缺 Origin 的 `Sec-Fetch-Site: cross-site` 拒絕。CLI 可無瀏覽器標頭，但仍須身分驗證及操作授權。CORS 本身不能代替變更授權。

## 秘密與公開發布

公開候選須檢查工作目錄、Git index 與所有將推送的 commit。除了憑證，也須移除真實個人路徑、私人 email、內部專案名稱與計畫、runtime session／task 識別碼，以及實機截圖與輸出。範例必須使用明示合成的資料。

私人部署備份與舊實機測試可保留於未追蹤的 `_private/`；該目錄不得加入公開版本。提交者須檢查 commit author／committer 與簽章是否暴露不希望公開的身分，不可只清理檔案文字。GitHub repository 歸屬與平台記錄仍由所選公開帳號決定，檔案清理不代表匿名發布。

不要提交 `.env`、provider token、節點私鑰、資料庫、個人路徑、terminal transcript 或隧道資訊。私有 deployment repo 也應只存設定宣告與 secret reference。每個安裝的 owner 自行配置秘密，升級工具不能自動替換既有帳密。

公開 PR 只在無內部資料的 GitHub-hosted runner 驗證，不直接交給個人電腦或帶秘密的 self-hosted worker。CI 不接收部署權限、不發布 release。原始碼採用 [MIT](../LICENSE) 授權；公開 repository 位於 `danny0926/agent-control-center`。

## 回報問題

公開 repo 的私人漏洞回報管道尚待維護者配置，目前沒有已驗證的回報網址或承諾回覆時限。若涉及憑證、跨專案內容或可執行命令的漏洞，透過與專案擁有者既有的私人管道聯絡；不要在公開 issue 貼秘密或完整 terminal。

回報可包含受影響版本、OS、部署模式、最小重現、預期及實際結果。使用合成專案與假憑證，遮罩個資；保存必要證據即可，不用擴大探查其他人的電腦。確認憑證外洩時由擁有者撤銷或更換，並檢查已公開歷史；只刪目前檔案不能清除歷史中的秘密。

## 驗證聲明

單元測試只能證明已涵蓋的登入、政策與模擬 adapter 行為。跨機器隔離、停止、proxy、瀏覽器通知與各 OS 的支援須另附實機證據。發布說明須分列已跑、未跑與不支援能力，不以 CI 綠燈表示整個安全設計已完成。

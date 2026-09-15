# MVP-A 通知與驗收契約

狀態：已接線並完成本機整合驗證的單機契約，範圍見 [交付紀錄](MVP_A_DELIVERY.md)。權威實作為 `main.py`、`security.py`、`notifications.py`、`verification.py` 與前端型別；HTTP schema 可由服務 `/openapi.json` 取得。本文不宣稱 fleet、quota、dispatch 或 Web Push 已實作。

## 身分與能力

所有 API 驗證單機 `local-owner`。缺半組帳密或不支援的模式／政策設定拒絕；runtime 動作另需 `CONTROL_CENTER_ALLOWED_ACTIONS` 明列。變更 API 檢查 origin，認證、授權與安全稽核獨立於 UI。

`GET /api/capabilities` 回傳 `mode="standalone"`、`allowed_actions`、`fleet_available=false`、`notification_delivery="page_open"`、`push_available=false`。401 表示需登入，403 表示動作／來源不允許，503 表示安全配置無效或模式未支援。Pydantic 請求格式錯誤為 422。

## 持久通知

| API | 輸入／輸出 |
| --- | --- |
| `GET /api/notifications` | `after>=0, limit=1..100, before>=0?, tail=false`；回 `items, high_watermark, next_cursor, unread_count` |
| `GET /api/notifications/stream` | SSE；`Last-Event-ID` 優先於 `after`，事件名稱 `notification`，`id` 為持久 sequence |
| `PATCH /api/notifications/{id}` | `{read: boolean}`；回更新後 item；非本人紀錄或不存在為 404 |
| `POST /api/notifications/read-all` | `{through_sequence: integer>=0}`；只標記指定游標以前的本人通知 |
| `GET/PUT /api/notification-preferences` | `desktop_enabled, event_types, project_ids, quiet_start, quiet_end, timezone` |
| `GET /api/notification-status` | `background_enabled` 及 collector health；不能由網頁 SSE 連線推定來源健康 |

item 欄位為 `id, sequence, event_type, project_id, title, summary, created_at, read_at, target`；target 包含 `project_id, view, entity_id`。標題與摘要使用服務預定文案，不把原始 transcript 放入 OS 通知。

第一次列表回最新一頁，頁內由舊至新排列；需要更早紀錄時以 `before=next_cursor` 載入。增量使用 `after` 或 `tail=true`；有下一頁時以 `next_cursor` 續讀。列表 snapshot 與 `high_watermark` 同交易取得，再接 SSE，避免列表與串流之間漏事件。首次歷史只加入通知中心。

SSE 無資料時送 keepalive；授權變動或游標超過目前資料上限時送 `resync` 並結束。client 重新載入列表；串流失聯不能繼續聲稱即時連線。此版本沒有刪除舊事件的保留期限機制。

notification 以 event／recipient 唯一化；業務事件與通知在同一 DB 交易寫入。偏好與安靜時段控制前端提醒，既有收件匣仍保留。`project_ids=null` 表示所有單機專案，空清單表示不提醒任何專案；quiet 時間為 `HH:MM`，須成對且 timezone 可解析。

目前可信事件來源包含具備明確 turn／goal epoch 身分的 runtime 完成紀錄、Decision 等待狀態轉換，以及下述驗收。只有 idle、pane 消失或 terminal verdict 不代表 work verified。來源不足時不補造完成事件；首次 collector 初始化不轟炸歷史。`run.failed`、`quota.blocked`、`node.offline` 雖有共同事件名稱，並不表示多節點／quota producer 已交付。

桌面提醒要求使用者允許 Notifications API，且頁面仍開啟；使用 Web Locks 與 localStorage receipt 減少同源多 tab 重複。此機制不保證 OS 已顯示或使用者已看到，也不支援關頁 Web Push。

## 擁有者驗收

| API | 契約 |
| --- | --- |
| `GET /api/projects/{project_id}/verification-state/{node_id}` | 回 `revision, revision_error, scope_hash, policy, acceptance_criteria, records`；不存在為 404 |
| `PUT /api/projects/{project_id}/verification-policy/{node_id}` | `{required_gates: string[]}`；1–20 個不重複的名稱；建立新 policy，舊驗收失效並通知 |
| `POST /api/projects/{project_id}/verifications` | 提交下述 request；成功 201，回 `id, status="verified", source="owner_attested", revision`；版本／證據／規則不符合為 409 |
| `GET /api/projects/{project_id}` | 動態核對有效紀錄後更新對應 leaf 的 verified 狀態，不修改文件中的原始完成宣稱 |

request 含 `node_id, revision, policy_id, acceptance_results, gate_results, expires_at`。每個 result 是 `{name, passed, evidence_paths}`；名稱集合必須與目前逐條 acceptance、預先保存的必要 gates 完全一致，且全部 passed，不允許漏項、替代項或重複。期限是含時區的未來時間。

只有已確認計畫、具有本機 Git 來源及 acceptance 的最末層可提交。驗收綁定 canonical source root、clean Git HEAD、scope hash、最新 policy、證據 SHA-256 與期限。證據使用專案內相對路徑，Windows 也用 `/`；拒絕越界、symlink／junction、`.env`、`.git` 與 runtime metadata。單檔至多 8 MiB，單次至多 40 個不同證據；ignored reports 可作為證據，不需讓測試產物污染待驗收 revision。

服務只核對擁有者聲明與證據檔案的一致性，不會自動執行其中聲稱的測試，也不解析報告就斷言測試通過。紀錄一律標示 `owner_attested`。record 對外僅回白名單識別、時間、失效原因與相對 path→hash，不回原始檔案內容、本機根路徑或內部 request JSON。

相同 revision／scope／policy／evidence 重送沿用 record 與通知；已過期／已失效的相同紀錄不能用較新期限恢復。重新驗收需要更新證據或明確保存新 policy，再重新確認全部條件。policy 更新、record 失效與對應通知同交易提交；來源、版本、scope、確認狀態、policy、hash 或期限不再有效時，保留舊紀錄並發一次 `work.verification_invalidated`。

核對表示某個觀測時點的證據一致，並不鎖住外部 Git repo。背景 reconcile 與讀取狀態時會重新檢查；不可宣稱整段時間內來源不可能被別的程序修改。

# Agent Control Center 文件

狀態：`prototype`\
產品類型：獨立、本機優先的多專案 Agent 管理控制台\
公開示例：完全合成的示例任務板，不對應任何真實內部專案\
最後更新：2026-09-13

Control Center 把不同產品的目標、工作、Agent 執行、待人工決策、驗證與 release readiness 整理成一個
可追蹤介面。它不取代 Git、GitHub、測試或各專案的 `AGENTS.md`；而是從這些真實來源產生人和 Agent
都能理解的現在狀態。

## 文件

- [MVP-A 交付紀錄](MVP_A_DELIVERY.md)：本機通知、驗收、安全預設、已跑與未跑驗證，以及發布待決事項。
- [PRD](PRD.md)：產品問題、專案匯入、多專案模型、資料契約與驗收。
- [前端產品規格](FRONTEND_SPEC.md)：資訊架構、頁面、元件、互動與狀態呈現。
- [公開模板、通知與多機器協作計畫](IMPLEMENTATION_PLAN.md)：目前程式缺口、分期派工、權限與額度策略、驗收條件；屬於後續擴充提案。
- [設計建議](DESIGN_RECOMMENDATION.md)：公開控制台的資訊設計與互動原則；所有案例為完全合成。

## 一句話架構

```text
本機 repo／GitHub／文件／CI／Agent runtime（真實來源）
                         ↓ 唯讀匯入與 adapter
                  Agent Control Center
                 ↙          ↓          ↘
             所有專案     人工決策     Agent 上工包
```

第一版只做「匯入、確認理解、可見、可問、可追蹤、可查核」。任何寫回來源專案的能力都必須另外授權。

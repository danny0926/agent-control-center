from control_center.plan_parser import parse_product_plan


def test_parse_product_plan_builds_cautious_hierarchy() -> None:
    markdown = """# Roadmap

## P0：先讓主流程完整

### 1. 保存使用者選擇（已完成）

問題：重新整理後會失去選擇。

交付：

- 保存目前選擇。
- 讓方案排序跟著目標更新。

驗收：

- 重新整理後仍保留。
- 無效選擇有清楚提示。

## P1：提高可信度

### 2. 顯示資料時效

交付：讓人知道資料何時取得，以及是否過期。
"""

    plan = parse_product_plan(markdown, "ROADMAP.md", "讓產品可以放心使用")

    assert len(plan) == 1
    assert [item.title for item in plan[0].children] == ["P0：先讓主流程完整", "P1：提高可信度"]
    completed_claim = plan[0].children[0].children[0]
    assert completed_claim.title == "保存使用者選擇"
    assert completed_claim.acceptance_total == 2
    assert completed_claim.acceptance_met == 0
    assert completed_claim.state == "implemented"
    assert "已實作" in completed_claim.state_explanation
    assert completed_claim.documented_done == ["保存目前選擇。", "讓方案排序跟著目標更新。"]
    assert completed_claim.acceptance_criteria == ["重新整理後仍保留。", "無效選擇有清楚提示。"]
    assert completed_claim.kind == "sub_milestone"
    assert [item.title for item in completed_claim.children] == ["保存目前選擇", "讓方案排序跟著目標更新"]
    assert plan[0].children[0].state == "implemented"


def test_parse_product_plan_keeps_bullet_only_future_scope() -> None:
    markdown = """# Roadmap

## P2：之後再擴充

以下不是目前里程碑的阻塞項：

- 新的資料來源。
- 團隊共享模式。
"""

    plan = parse_product_plan(markdown, "ROADMAP.md", "讓工作變清楚")

    future = plan[0].children[0]
    assert [item.title for item in future.children] == ["新的資料來源", "團隊共享模式"]
    assert all(item.state == "not_started" for item in future.children)
    assert future.state == "not_started"


def test_parse_product_plan_understands_explicit_future_phase() -> None:
    markdown = """# Roadmap

## Phase 2：執行 Pilot（尚未開始）

### 招募測試者（尚未開始）

交付：

- 招募 20 位測試者。
"""

    phase = parse_product_plan(markdown, "ROADMAP.md", "驗證需求")[0].children[0]

    assert phase.state == "not_started"
    assert phase.children[0].state == "not_started"


def test_parse_product_plan_tracks_each_deliverable_status_without_inheriting_partial() -> None:
    markdown = """# Roadmap

## Phase 1：可展示版本（進行中）

### 固定 Demo（部分完成）

交付：

- [已完成] 保存使用者選擇。
- [尚未開始] 錄製 Demo。
- 尚未逐項標記的工作。
"""

    items = parse_product_plan(markdown, "ROADMAP.md", "完成展示")[0].children[0].children[0].children

    assert [(item.title, item.state) for item in items] == [
        ("保存使用者選擇", "implemented"),
        ("錄製 Demo", "not_started"),
        ("尚未逐項標記的工作", "unknown"),
    ]


def test_parse_product_plan_separates_partial_implementation_from_verification() -> None:
    markdown = """# Roadmap

## P0：主流程

### 匯入後確認（已完成第一版）

驗收：

- 可以確認。
- 可以修正。
"""

    outcome = parse_product_plan(markdown, "ROADMAP.md", "完成產品")[0].children[0].children[0]

    assert outcome.state == "partial"
    assert outcome.acceptance_met == 0
    assert outcome.acceptance_total == 2
    assert "驗收條件" in outcome.state_explanation


def test_parse_product_plan_exposes_done_remaining_and_acceptance_lists() -> None:
    markdown = """# Roadmap

## P1：可信度

### 校準工作流

狀態：後端與最小操作入口第一版完成。

目前已完成：

- 可以記錄人工答案。
- 可以清除紀錄。

目前未完成：

- 自動調參。

驗收：

- UNKNOWN 不進負例分母。
"""

    outcome = parse_product_plan(markdown, "ROADMAP.md", "完成產品")[0].children[0].children[0]

    assert outcome.documented_done == ["可以記錄人工答案。", "可以清除紀錄。"]
    assert outcome.documented_remaining == ["自動調參。"]
    assert outcome.acceptance_criteria == ["UNKNOWN 不進負例分母。"]


def test_parse_product_plan_places_deliverables_under_sub_milestones() -> None:
    markdown = """# Roadmap

## P0：完成主流程

### 最佳化目標切換（已完成）

交付：

- 加入目標切換控制。
- 讓方案排序跟著目標更新。

驗收：

- 四種目標都能切換。
"""

    milestone = parse_product_plan(markdown, "ROADMAP.md", "完成產品")[0].children[0]
    sub_milestone = milestone.children[0]

    assert sub_milestone.kind == "sub_milestone"
    assert [item.kind for item in sub_milestone.children] == ["outcome", "outcome"]
    assert [item.title for item in sub_milestone.children] == [
        "加入目標切換控制",
        "讓方案排序跟著目標更新",
    ]

from __future__ import annotations

import re
import unicodedata

from .models import PlanNode, PlanState


MILESTONE_PATTERN = re.compile(
    r"^(?:P\d+\s*[:：]|Phase\s+\d+\s*[:：]?|階段\s*\d+\s*[:：]?|里程碑\s*\d*\s*[:：]?)",
    re.IGNORECASE,
)
STATUS_SUFFIX = re.compile(r"\s*[（(](已完成(?:第一版)?|完成|進行中|部分完成|尚未開始)[）)]\s*$")
NUMBER_PREFIX = re.compile(r"^\d+[.)、]\s*")
ITEM_STATUS_PREFIX = re.compile(r"^\[(已完成|進行中|部分完成|尚未開始)\]\s*")
SECTION_BOUNDARY = r"^(?:問題|目的|交付|摘要|負責|驗收|狀態|目前狀態|目前已完成|目前未完成|M\d+\s*目前狀態)[：:]"


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", normalized).strip("-")
    return slug[:64] or "item"


def _clean_title(value: str) -> str:
    value = NUMBER_PREFIX.sub("", value.strip())
    return STATUS_SUFFIX.sub("", value).strip()


def _deliverable_state(value: str, parent_state: PlanState) -> tuple[str, PlanState, str]:
    match = ITEM_STATUS_PREFIX.match(value)
    if match:
        label = match.group(1)
        state = {
            "已完成": PlanState.IMPLEMENTED,
            "進行中": PlanState.IN_PROGRESS,
            "部分完成": PlanState.PARTIAL,
            "尚未開始": PlanState.NOT_STARTED,
        }[label]
        return ITEM_STATUS_PREFIX.sub("", value).strip(), state, f"產品計畫將這項交付成果標示為「{label}」。"
    if parent_state in {PlanState.IMPLEMENTED, PlanState.NOT_STARTED}:
        return value, parent_state, "狀態暫時沿用所屬子里程碑；仍需逐項連結完成證據。"
    return value, PlanState.UNKNOWN, "所屬子里程碑已有整體進度，但產品計畫尚未逐項標明這項交付成果的狀態。"


def _claimed_state(value: str, body: str) -> tuple[PlanState, str]:
    status_lines = "\n".join(
        line for line in body[:1600].splitlines()
        if re.match(r"^(?:狀態|目前狀態|M\d+\s*目前狀態)[：:]", line.strip())
    )
    combined = f"{value}\n{status_lines}"
    if re.search(r"已完成第一版|第一版完成|部分完成", combined):
        return PlanState.PARTIAL, "產品文件記載第一版或部分功能已實作；驗收條件仍需逐項連結測試或人工驗收。"
    if re.search(r"已完成|✅", combined):
        return PlanState.IMPLEMENTED, "產品文件記載功能已實作；目前尚未逐項連結測試、PR 或人工驗收證據。"
    if re.search(r"尚未開始|未開始|not started", combined, re.IGNORECASE):
        return PlanState.NOT_STARTED, "產品文件明確將這項工作列為尚未開始。"
    if re.search(r"blocked|^阻塞$|^卡住$", combined, re.IGNORECASE | re.MULTILINE):
        return PlanState.BLOCKED, "Roadmap 記載這項成果受到阻塞；仍需連結目前的阻塞來源。"
    if re.search(r"進行中|目前狀態|目前已完成", combined):
        return PlanState.IN_PROGRESS, "Roadmap 記載已有進展；實際完成程度仍需用驗收條件與證據確認。"
    return PlanState.UNKNOWN, "產品文件沒有明確寫出這項工作的實作狀態。"


def _aggregate_milestone_state(milestone: PlanNode) -> None:
    if not milestone.children:
        return
    states = {child.state for child in milestone.children}
    if states <= {PlanState.VERIFIED, PlanState.IMPLEMENTED}:
        milestone.state = PlanState.IMPLEMENTED
        milestone.state_explanation = "這個里程碑的所有成果都已記載為實作完成；仍需補齊逐項驗證證據。"
    elif states <= {PlanState.VERIFIED, PlanState.IMPLEMENTED, PlanState.PARTIAL}:
        milestone.state = PlanState.PARTIAL
        milestone.state_explanation = "這個里程碑的所有成果都有實作，其中部分仍是第一版或部分完成。"
    elif states == {PlanState.NOT_STARTED}:
        milestone.state = PlanState.NOT_STARTED
        milestone.state_explanation = "產品文件將這個里程碑的成果列為後續範圍，目前尚未開始。"
    elif states & {PlanState.IN_PROGRESS, PlanState.IMPLEMENTED, PlanState.PARTIAL, PlanState.VERIFIED}:
        milestone.state = PlanState.IN_PROGRESS
        milestone.state_explanation = "這個里程碑已有成果實作或進行中，也仍有狀態未明的項目。"


def _section_value(body: str, labels: tuple[str, ...]) -> str:
    label_pattern = "|".join(map(re.escape, labels))
    match = re.search(
        rf"^(?:{label_pattern})[：:]\s*(.*?)(?={SECTION_BOUNDARY}|^#|\Z)",
        body,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        return ""
    value = re.sub(r"\s+", " ", match.group(1)).strip()
    return re.sub(r"^[-*]\s*", "", value)[:360]


def _section_bullets(body: str, labels: tuple[str, ...]) -> list[str]:
    label_pattern = "|".join(map(re.escape, labels))
    match = re.search(
        rf"^(?:{label_pattern})[：:]\s*(.*?)(?={SECTION_BOUNDARY}|^#|\Z)",
        body,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        return []
    items: list[str] = []
    current = ""
    for line in match.group(1).splitlines():
        bullet = re.match(r"^\s*[-*]\s+(.+)$", line)
        if bullet:
            if current:
                items.append(re.sub(r"\s+", " ", current).strip())
            current = bullet.group(1).strip()
        elif current and line.strip():
            current += f" {line.strip()}"
    if current:
        items.append(re.sub(r"\s+", " ", current).strip())
    return items[:20]


def _heading_blocks(markdown: str) -> list[tuple[int, str, str]]:
    matches = list(re.finditer(r"^(#{2,3})\s+(.+?)\s*$", markdown, flags=re.MULTILINE))
    blocks: list[tuple[int, str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        blocks.append((len(match.group(1)), match.group(2).strip(), markdown[match.end():end]))
    return blocks


def parse_product_plan(markdown: str, source_path: str, purpose: str) -> list[PlanNode]:
    """Turn common Markdown roadmap headings into a cautious, reviewable outcome tree."""
    blocks = _heading_blocks(markdown)
    milestones: list[PlanNode] = []
    milestone_bodies: dict[str, str] = {}
    current: PlanNode | None = None
    seen_ids: dict[str, int] = {}

    def unique_id(title: str) -> str:
        base = _slug(title)
        seen_ids[base] = seen_ids.get(base, 0) + 1
        return base if seen_ids[base] == 1 else f"{base}-{seen_ids[base]}"

    for level, heading, body in blocks:
        if level == 2 and MILESTONE_PATTERN.match(heading):
            state, explanation = _claimed_state(heading, body)
            current = PlanNode(
                id=unique_id(heading),
                kind="milestone",
                title=_clean_title(heading),
                description=_section_value(body, ("目標", "摘要", "交付")) or "這個階段包含多項產品成果；展開查看目前可辨識的項目。",
                technical_label=f"{source_path}#{_slug(heading)}",
                state=state,
                state_explanation=explanation,
                source_paths=[source_path],
            )
            milestones.append(current)
            milestone_bodies[current.id] = body
            continue
        if level == 3 and current is not None:
            state, explanation = _claimed_state(heading, body)
            deliverables = _section_bullets(body, ("交付",))
            if not deliverables:
                inline_deliverable = _section_value(body, ("交付",))
                if inline_deliverable:
                    deliverables = [inline_deliverable]
            acceptance_criteria = _section_bullets(body, ("驗收",))
            documented_done = _section_bullets(body, ("目前已完成", "目前狀態", "M3 目前狀態"))
            documented_remaining = _section_bullets(body, ("目前未完成",))
            if state == PlanState.IMPLEMENTED and not documented_done:
                documented_done = deliverables
            if state in {PlanState.NOT_STARTED, PlanState.UNKNOWN} and not documented_remaining:
                documented_remaining = deliverables
            description = _section_value(body, ("問題", "目的", "交付", "摘要"))
            sub_milestone = PlanNode(
                    id=unique_id(heading),
                    kind="sub_milestone",
                    title=_clean_title(heading),
                    description=description or "Roadmap 有列出這項工作，但還沒有可直接顯示的產品問題說明。",
                    technical_label=f"{source_path}#{_slug(heading)}",
                    state=state,
                    state_explanation=explanation,
                    acceptance_met=0,
                    acceptance_total=len(acceptance_criteria),
                    evidence_count=0,
                    documented_done=documented_done,
                    documented_remaining=documented_remaining,
                    acceptance_criteria=acceptance_criteria,
                    source_paths=[source_path],
                )
            for deliverable in deliverables:
                deliverable_title, child_state, child_explanation = _deliverable_state(deliverable, state)
                sub_milestone.children.append(
                    PlanNode(
                        id=unique_id(deliverable_title),
                        kind="outcome",
                        title=deliverable_title.rstrip("。"),
                        description="這是 Roadmap 在此子里程碑下列出的交付成果。",
                        technical_label=f"{source_path}#{_slug(heading)}",
                        state=child_state,
                        state_explanation=child_explanation,
                        source_paths=[source_path],
                    )
                )
            current.children.append(sub_milestone)

    if not milestones:
        return []
    for milestone in milestones:
        if milestone.children:
            milestone.acceptance_total = len(milestone.children)
            _aggregate_milestone_state(milestone)
            continue
        bullets = [
            re.sub(r"\s+", " ", match).strip()
            for match in re.findall(r"^\s*[-*]\s+(.+)$", milestone_bodies.get(milestone.id, ""), flags=re.MULTILINE)
        ]
        for bullet in bullets[:20]:
            milestone.children.append(
                PlanNode(
                    id=unique_id(bullet),
                    kind="sub_milestone",
                    title=bullet.rstrip("。"),
                    description="Roadmap 將這項內容列在此階段，但尚未提供獨立的產品問題與驗收條件。",
                    technical_label=f"{source_path}#{_slug(bullet)}",
                    state=PlanState.NOT_STARTED,
                    state_explanation="Roadmap 將它列為後續範圍；目前沒有可查核的完成宣稱或證據。",
                    documented_remaining=[bullet.rstrip("。")],
                    source_paths=[source_path],
                )
            )
        _aggregate_milestone_state(milestone)
        milestone.acceptance_total = len(milestone.children)
    return [
        PlanNode(
            id="product-goal",
            kind="goal",
            title=purpose,
            description="這是從產品摘要與 Roadmap 整理出的成果樹草稿；確認計畫不等於確認成果已完成。",
            technical_label="product-goal",
            state=PlanState.UNKNOWN,
            state_explanation=f"已整理出 {len(milestones)} 個階段，等待你確認這棵樹是否正確表達產品計畫。",
            acceptance_met=0,
            acceptance_total=len(milestones),
            evidence_count=0,
            source_paths=[source_path],
            children=milestones,
        )
    ]

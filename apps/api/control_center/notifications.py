"""Durable local-owner inbox. Domain events and deliveries share a transaction."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Callable, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, model_validator

EVENT_TYPES = (
    "agent.turn_completed", "agent.goal_completed", "decision.waiting_human",
    "work.verified", "work.verification_invalidated", "run.failed", "quota.blocked", "node.offline",
)
TITLES = dict(zip(EVENT_TYPES, (
    "Agent 已完成這一輪", "Agent 回報目標完成", "有一項問題需要你決定",
    "項目已通過驗收", "先前驗收需要重新確認", "工作執行失敗", "工作正在等待額度", "電腦已離線",
)))
SUMMARIES = {
    "agent.turn_completed": "這是執行輪次結束，產品成果仍需個別驗收。",
    "agent.goal_completed": "已收到指定目標的完成回報，請查看驗收證據。",
    "decision.waiting_human": "請開啟決策詳情，查看問題與依據。",
    "work.verified": "目前版本的必要驗收條件已有有效證據。",
    "work.verification_invalidated": "版本、驗收範圍或證據已改變，請重新驗收。",
}


class NotificationTarget(BaseModel):
    project_id: str | None
    view: Literal["agents", "decisions", "work", "overview"]
    entity_id: str | None = None


class NotificationItem(BaseModel):
    id: str
    sequence: int
    event_type: str
    project_id: str | None
    title: str
    summary: str
    created_at: str
    read_at: str | None
    target: NotificationTarget


class NotificationPage(BaseModel):
    items: list[NotificationItem]
    high_watermark: int
    next_cursor: int | None = None
    unread_count: int


class NotificationPreferences(BaseModel):
    desktop_enabled: bool = False
    event_types: list[str] = Field(default_factory=lambda: list(EVENT_TYPES), max_length=20)
    project_ids: list[str] | None = Field(default=None, max_length=500)
    quiet_start: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    quiet_end: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: str = "Asia/Taipei"

    @model_validator(mode="after")
    def valid_preferences(self):
        if any(kind not in EVENT_TYPES for kind in self.event_types):
            raise ValueError("不支援的通知種類。")
        if (self.quiet_start is None) != (self.quiet_end is None):
            raise ValueError("安靜時段需要同時設定開始與結束。")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("時區不存在。") from None
        self.event_types = list(dict.fromkeys(self.event_types))
        return self


class ReadNotification(BaseModel):
    read: bool = True


class ReadAllNotifications(BaseModel):
    through_sequence: int = Field(ge=0)


def initialize_notifications(connection: sqlite3.Connection) -> None:
    # No executescript: it would commit its caller's migration transaction.
    statements = [
        """CREATE TABLE IF NOT EXISTS domain_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
            source_key TEXT UNIQUE NOT NULL, event_type TEXT NOT NULL, project_id TEXT NOT NULL,
            identity_json TEXT NOT NULL, entity_id TEXT, occurred_at TEXT NOT NULL,
            observed_at TEXT NOT NULL, schema_version INTEGER NOT NULL DEFAULT 1)""",
        """CREATE TABLE IF NOT EXISTS notifications (
            event_id TEXT NOT NULL, recipient_id TEXT NOT NULL, read_at TEXT,
            PRIMARY KEY(event_id, recipient_id))""",
        """CREATE TABLE IF NOT EXISTS notification_preferences (
            recipient_id TEXT PRIMARY KEY, preferences_json TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS collector_cursors (
            source_key TEXT PRIMARY KEY, generation TEXT NOT NULL, offset INTEGER NOT NULL,
            context_json TEXT NOT NULL, updated_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS collector_health (
            id TEXT PRIMARY KEY, status TEXT NOT NULL, checked_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS security_audit (
            id TEXT PRIMARY KEY, actor TEXT, action TEXT NOT NULL, method TEXT NOT NULL,
            target TEXT NOT NULL, outcome TEXT NOT NULL, created_at TEXT NOT NULL)""",
    ]
    for statement in statements:
        connection.execute(statement)


def emit_event(connection: sqlite3.Connection, *, source_key: str, event_type: str,
               project_id: str, entity_id: str | None = None, identity: dict | None = None,
               occurred_at: str | None = None) -> str:
    """Internal only. Callers validate evidence; arbitrary summaries never enter the inbox."""
    if event_type not in EVENT_TYPES:
        raise ValueError("Unsupported event type")
    now = datetime.now(timezone.utc).isoformat()
    event_id = str(uuid.uuid4())
    connection.execute(
        """INSERT OR IGNORE INTO domain_events
        (id,source_key,event_type,project_id,identity_json,entity_id,occurred_at,observed_at)
        VALUES (?,?,?,?,?,?,?,?)""",
        (event_id, hashlib.sha256(source_key.encode()).hexdigest(), event_type, project_id,
         json.dumps(identity or {}, sort_keys=True), entity_id, occurred_at or now, now),
    )
    row = connection.execute("SELECT id FROM domain_events WHERE source_key=?",
                             (hashlib.sha256(source_key.encode()).hexdigest(),)).fetchone()
    event_id = row[0]
    connection.execute("INSERT OR IGNORE INTO notifications VALUES (?,?,NULL)", (event_id, "local-owner"))
    return event_id


class NotificationStore:
    def __init__(self, connect: Callable[[], sqlite3.Connection]):
        self.connect = connect
        with self.connect() as connection:
            initialize_notifications(connection)

    @staticmethod
    def _item(row: sqlite3.Row) -> NotificationItem:
        kind = row["event_type"]
        view = "decisions" if kind.startswith("decision.") else "work" if kind.startswith("work.") else "agents"
        return NotificationItem(
            id=row["id"], sequence=row["sequence"], event_type=kind, project_id=row["project_id"],
            title=TITLES[kind], summary=SUMMARIES.get(kind, "請開啟詳情查看目前狀態與下一步。"),
            created_at=row["occurred_at"], read_at=row["read_at"],
            target=NotificationTarget(project_id=row["project_id"], view=view, entity_id=row["entity_id"]),
        )

    def page(self, recipient: str, after: int = 0, limit: int = 50, before: int | None = None,
             *, tail: bool = False) -> NotificationPage:
        with self.connect() as c:
            c.execute("BEGIN")
            high = c.execute("SELECT COALESCE(MAX(sequence),0) FROM domain_events").fetchone()[0]
            base = """FROM domain_events e JOIN notifications n ON n.event_id=e.id
                JOIN projects p ON p.id=e.project_id WHERE n.recipient_id=?"""
            unread = c.execute("SELECT COUNT(*) " + base + " AND n.read_at IS NULL", (recipient,)).fetchone()[0]
            incremental = tail or after > 0
            if incremental:
                rows = c.execute("SELECT e.*,n.read_at " + base + " AND e.sequence>? AND e.sequence<=? ORDER BY e.sequence LIMIT ?",
                                 (recipient, after, high, limit + 1)).fetchall()
            else:
                rows = c.execute("SELECT e.*,n.read_at " + base + " AND e.sequence<=? ORDER BY e.sequence DESC LIMIT ?",
                                 (recipient, min(high, before) if before is not None else high, limit + 1)).fetchall()
            more = len(rows) > limit
            rows = rows[:limit]
            cursor = (rows[-1]["sequence"] if incremental else rows[-1]["sequence"] - 1) if more else None
            if not incremental:
                rows.reverse()
            return NotificationPage(items=[self._item(row) for row in rows], high_watermark=high,
                                    next_cursor=cursor, unread_count=unread)

    def read(self, recipient: str, event_id: str, read: bool) -> NotificationItem:
        with self.connect() as c:
            row = c.execute("""SELECT e.*,n.read_at FROM domain_events e JOIN notifications n ON n.event_id=e.id
                JOIN projects p ON p.id=e.project_id WHERE e.id=? AND n.recipient_id=?""", (event_id, recipient)).fetchone()
            if row is None:
                raise KeyError("找不到這則通知。")
            when = (row["read_at"] or datetime.now(timezone.utc).isoformat()) if read else None
            c.execute("UPDATE notifications SET read_at=? WHERE event_id=? AND recipient_id=?", (when, event_id, recipient))
            item = self._item(row)
            item.read_at = when
            return item

    def read_all(self, recipient: str, through: int) -> None:
        with self.connect() as c:
            c.execute("""UPDATE notifications SET read_at=? WHERE recipient_id=? AND read_at IS NULL
                AND event_id IN (SELECT id FROM domain_events WHERE sequence<=?)""",
                      (datetime.now(timezone.utc).isoformat(), recipient, through))

    def preferences(self, recipient: str) -> NotificationPreferences:
        with self.connect() as c:
            row = c.execute("SELECT preferences_json FROM notification_preferences WHERE recipient_id=?", (recipient,)).fetchone()
        return NotificationPreferences.model_validate_json(row[0]) if row else NotificationPreferences()

    def save_preferences(self, recipient: str, prefs: NotificationPreferences) -> NotificationPreferences:
        with self.connect() as c:
            if prefs.project_ids is not None:
                valid = {r[0] for r in c.execute("SELECT id FROM projects")}
                if any(p not in valid for p in prefs.project_ids):
                    raise ValueError("通知設定包含不存在的專案。")
            c.execute("INSERT INTO notification_preferences VALUES (?,?) ON CONFLICT(recipient_id) DO UPDATE SET preferences_json=excluded.preferences_json",
                      (recipient, prefs.model_dump_json()))
        return prefs

    def audit(self, actor: str | None, action: str, method: str, target: str, outcome: str) -> None:
        # Store only route templates, never passwords, body, query strings, or user paths.
        with self.connect() as c:
            c.execute("INSERT INTO security_audit VALUES (?,?,?,?,?,?,?)", (
                str(uuid.uuid4()), actor, action, method, target, outcome, datetime.now(timezone.utc).isoformat()))

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Sequence


_REQUIRED_COLUMNS = {
    "thread_id",
    "goal_id",
    "objective",
    "status",
    "token_budget",
    "tokens_used",
    "time_used_seconds",
    "created_at_ms",
    "updated_at_ms",
}


@dataclass(frozen=True)
class NativeGoalRecord:
    thread_id: str
    goal_id: str
    objective: str
    status: str
    tokens_used: int | None
    time_used_seconds: int | None
    created_at: datetime
    updated_at: datetime


def _db_path() -> Path:
    configured = os.environ.get("CODEX_GOALS_DB")
    return Path(configured).expanduser() if configured else Path.home() / ".codex" / "goals_1.sqlite"


def lookup_native_goal(thread_id: str) -> NativeGoalRecord | None:
    return lookup_native_goals((thread_id,)).get(thread_id)


def lookup_native_goals(thread_ids: Sequence[str]) -> dict[str, NativeGoalRecord]:
    if not thread_ids:
        return {}
    path = _db_path()
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(thread_goals)")
            }
            if not _REQUIRED_COLUMNS.issubset(columns):
                return {}
            unique_thread_ids = tuple(dict.fromkeys(thread_ids))
            placeholders = ", ".join("?" for _ in unique_thread_ids)
            rows = connection.execute(
                """
                SELECT thread_id, goal_id, objective, status, tokens_used,
                       time_used_seconds, created_at_ms, updated_at_ms
                FROM thread_goals
                WHERE thread_id IN (""" + placeholders + ")",
                unique_thread_ids,
            ).fetchall()
            return {
                row[0]: NativeGoalRecord(
                    thread_id=row[0],
                    goal_id=row[1],
                    objective=row[2],
                    status=row[3],
                    tokens_used=row[4],
                    time_used_seconds=row[5],
                    created_at=datetime.fromtimestamp(row[6] / 1000, timezone.utc),
                    updated_at=datetime.fromtimestamp(row[7] / 1000, timezone.utc),
                )
                for row in rows
            }
    except (OSError, sqlite3.Error, TypeError, ValueError):
        # Codex 的本機資料庫可能不存在、正在切換版本或正被其他程序更新；此時不能把推測當成權威證據。
        return {}

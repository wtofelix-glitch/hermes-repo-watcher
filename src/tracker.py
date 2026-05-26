# hermes-repo-watcher - tracker.py
"""SQLite 事件去重与状态跟踪模块。

管理事件处理状态，确保同一事件不会被重复处理。
"""

from __future__ import annotations

import os
import sqlite3
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("repo-watcher.tracker")

# 数据库默认路径
_DB_DIR = os.path.expanduser("~/.hermes/repo-watcher/db")
_DB_PATH = os.path.join(_DB_DIR, "state.db")

# 建表 SQL
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_id TEXT NOT NULL,
    action TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    handler TEXT,
    result TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    processed_at TEXT,
    UNIQUE(repo, event_id, action)
);
"""


class Tracker:
    """事件跟踪器，提供去重和状态管理功能。"""

    def __init__(self, db_path: Optional[str] = None):
        """初始化跟踪器，自动创建数据库目录和表。

        Args:
            db_path: SQLite 数据库路径，默认为 ~/.hermes/repo-watcher/db/state.db。
        """
        self.db_path = db_path or _DB_PATH
        self._ensure_db()

    def _ensure_db(self) -> None:
        """确保数据库目录和表存在。"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = self._get_conn()
        try:
            conn.execute(_CREATE_TABLE_SQL)
            conn.commit()
        finally:
            conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def is_new(self, event: Dict[str, Any]) -> bool:
        """检查事件是否为新（未被处理过）。

        按 repo + event_id + action 组合去重。

        Args:
            event: 事件字典，必须包含 repo、event_id、action 字段。

        Returns:
            如果事件尚未被记录返回 True，否则返回 False。
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT 1 FROM events WHERE repo = ? AND event_id = ? AND action = ?",
                (event["repo"], str(event["event_id"]), event["action"]),
            )
            return cursor.fetchone() is None
        except Exception as e:
            logger.error("检查事件去重失败: %s", e)
            return True  # 查错时当作新事件处理
        finally:
            conn.close()

    def mark(
        self,
        event: Dict[str, Any],
        state: str,
        result: Optional[str] = None,
        handler: Optional[str] = None,
    ) -> bool:
        """记录或更新事件状态。

        Args:
            event: 事件字典。
            state: 状态值（pending / running / done / failed / skipped）。
            result: 执行结果摘要（可选）。
            handler: 执行的 handler 名称（可选）。

        Returns:
            操作成功返回 True，失败返回 False。
        """
        conn = self._get_conn()
        try:
            if self.is_new(event):
                conn.execute(
                    """INSERT INTO events (repo, event_type, event_id, action, state, handler, result)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event["repo"],
                        event["type"],
                        str(event["event_id"]),
                        event["action"],
                        state,
                        handler,
                        result,
                    ),
                )
            else:
                processed_at = "datetime('now')" if state in ("done", "failed", "skipped") else None
                if processed_at:
                    conn.execute(
                        """UPDATE events
                           SET state = ?, handler = COALESCE(?, handler),
                               result = COALESCE(?, result),
                               processed_at = datetime('now')
                           WHERE repo = ? AND event_id = ? AND action = ?""",
                        (state, handler, result, event["repo"], str(event["event_id"]), event["action"]),
                    )
                else:
                    conn.execute(
                        """UPDATE events
                           SET state = ?, handler = COALESCE(?, handler),
                               result = COALESCE(?, result)
                           WHERE repo = ? AND event_id = ? AND action = ?""",
                        (state, handler, result, event["repo"], str(event["event_id"]), event["action"]),
                    )
            conn.commit()
            return True
        except Exception as e:
            logger.error("标记事件状态失败: %s", e)
            conn.rollback()
            return False
        finally:
            conn.close()

    def get_stats(self) -> Dict[str, Any]:
        """获取事件统计信息。

        Returns:
            字典包含总事件数和各状态的数量。
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT COUNT(*) as total FROM events")
            total = cursor.fetchone()["total"]

            cursor = conn.execute(
                "SELECT state, COUNT(*) as cnt FROM events GROUP BY state"
            )
            state_counts: Dict[str, int] = {}
            for row in cursor.fetchall():
                state_counts[row["state"]] = row["cnt"]

            return {
                "total": total,
                "states": state_counts,
                "db_path": self.db_path,
            }
        except Exception as e:
            logger.error("获取统计信息失败: %s", e)
            return {"total": 0, "states": {}, "db_path": self.db_path}
        finally:
            conn.close()

    def get_pending(self) -> List[Dict[str, Any]]:
        """获取所有 pending 状态的事件。

        Returns:
            pending 状态的事件列表。
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM events WHERE state = 'pending' ORDER BY created_at ASC"
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("获取 pending 事件失败: %s", e)
            return []
        finally:
            conn.close()


# 模块级单例
_default_tracker: Optional[Tracker] = None


def get_tracker(db_path: Optional[str] = None) -> Tracker:
    """获取默认的 Tracker 实例（单例模式）。

    Args:
        db_path: 可选的自定义数据库路径。

    Returns:
        Tracker 实例。
    """
    global _default_tracker
    if _default_tracker is None or db_path is not None:
        _default_tracker = Tracker(db_path)
    return _default_tracker


def is_new(event: Dict[str, Any]) -> bool:
    """快捷函数：检查事件是否为新。"""
    return get_tracker().is_new(event)


def mark(
    event: Dict[str, Any],
    state: str,
    result: Optional[str] = None,
    handler: Optional[str] = None,
) -> bool:
    """快捷函数：记录事件状态。"""
    return get_tracker().mark(event, state, result, handler)


def get_stats() -> Dict[str, Any]:
    """快捷函数：获取统计信息。"""
    return get_tracker().get_stats()
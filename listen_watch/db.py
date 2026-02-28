import json
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path.home() / ".listen_watch" / "processed.db"

WATCH_EXTENSIONS = {".m4a", ".mp4", ".caf"}

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS processed_files (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path           TEXT    NOT NULL UNIQUE,
    file_size           INTEGER NOT NULL,
    status              TEXT    NOT NULL,       -- 'success' | 'failed'
    processed_at        TEXT    NOT NULL,
    transcription_text  TEXT,                   -- 豆包转写结果缓存
    ai_result_json      TEXT,                   -- ProcessedMemo 序列化（JSON）
    memo_title          TEXT,                   -- iOS 语音备忘录显示的文件名
    duration_seconds    REAL                    -- 录音时长（秒）
)
"""

# 旧版数据库迁移：补充新列（幂等）
MIGRATE_SQLS = [
    "ALTER TABLE processed_files ADD COLUMN transcription_text TEXT",
    "ALTER TABLE processed_files ADD COLUMN ai_result_json TEXT",
    "ALTER TABLE processed_files ADD COLUMN memo_title TEXT",
    "ALTER TABLE processed_files ADD COLUMN duration_seconds REAL",
]


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """初始化数据库，创建表并迁移旧版本（幂等）。"""
    with _connect() as conn:
        conn.execute(CREATE_TABLE_SQL)
        for sql in MIGRATE_SQLS:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # 列已存在，忽略
    logger.debug("数据库初始化完成: %s", DB_PATH)


def is_processed(path: Path) -> bool:
    """文件是否已成功处理过。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT status FROM processed_files WHERE file_path = ?",
            (str(path),)
        ).fetchone()
    return row is not None and row["status"] == "success"


def get_transcription(path: Path) -> Optional[str]:
    """读取缓存的转写文本，无缓存返回 None。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT transcription_text FROM processed_files WHERE file_path = ?",
            (str(path),)
        ).fetchone()
    return row["transcription_text"] if row else None


def get_ai_result(path: Path):
    """读取缓存的 AI 结果（ProcessedMemo），无缓存返回 None。"""
    from listen_watch.processor import ProcessedMemo
    with _connect() as conn:
        row = conn.execute(
            "SELECT ai_result_json FROM processed_files WHERE file_path = ?",
            (str(path),)
        ).fetchone()
    if not row or not row["ai_result_json"]:
        return None
    data = json.loads(row["ai_result_json"])
    return ProcessedMemo(**data)


def save_file_info(path: Path, memo_title: Optional[str], duration_seconds: Optional[float]) -> None:
    """保存录音的文件名和时长（upsert）。"""
    size = path.stat().st_size if path.exists() else 0
    now = datetime.now().isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO processed_files (file_path, file_size, status, processed_at, memo_title, duration_seconds)
            VALUES (?, ?, 'pending', ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                memo_title       = excluded.memo_title,
                duration_seconds = excluded.duration_seconds
            """,
            (str(path), size, now, memo_title, duration_seconds)
        )
    logger.debug("文件信息已记录: %s", path.name)


def save_transcription(path: Path, text: str) -> None:
    """缓存转写结果（upsert）。"""
    size = path.stat().st_size if path.exists() else 0
    now = datetime.now().isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO processed_files (file_path, file_size, status, processed_at, transcription_text)
            VALUES (?, ?, 'pending', ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                transcription_text = excluded.transcription_text
            """,
            (str(path), size, now, text)
        )
    logger.debug("转写结果已缓存: %s", path.name)


def save_ai_result(path: Path, memo) -> None:
    """缓存 AI 处理结果（upsert）。"""
    from dataclasses import asdict
    with _connect() as conn:
        conn.execute(
            """
            UPDATE processed_files SET ai_result_json = ?
            WHERE file_path = ?
            """,
            (json.dumps(asdict(memo), ensure_ascii=False), str(path))
        )
    logger.debug("AI 结果已缓存: %s", path.name)


def mark_success(path: Path) -> None:
    """标记文件处理成功。"""
    _set_status(path, "success")
    logger.debug("标记成功: %s", path.name)


def mark_failed(path: Path) -> None:
    """标记文件处理失败（下次启动时会重试）。"""
    _set_status(path, "failed")
    logger.debug("标记失败: %s", path.name)


def _set_status(path: Path, status: str) -> None:
    size = path.stat().st_size if path.exists() else 0
    now = datetime.now().isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO processed_files (file_path, file_size, status, processed_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                file_size    = excluded.file_size,
                status       = excluded.status,
                processed_at = excluded.processed_at
            """,
            (str(path), size, status, now)
        )


def get_unprocessed(directory: Path) -> list:
    """
    扫描目录，返回尚未成功处理的音频文件列表（按文件名排序）。
    用于程序启动时补处理遗漏的文件。
    """
    with _connect() as conn:
        done = {
            row["file_path"]
            for row in conn.execute(
                "SELECT file_path FROM processed_files WHERE status = 'success'"
            ).fetchall()
        }
    return sorted(
        p for p in directory.iterdir()
        if p.suffix.lower() in WATCH_EXTENSIONS and str(p) not in done
    )
